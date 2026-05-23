"""Vision — multi-modal incident analysis agent.

Purpose:
    Accepts rack photos, thermal-camera images, or console screenshots
    plus incident context. Routes through the LLM router with the
    MULTIMODAL task class (vision model) and returns a structured
    `VisionFinding` that the dashboard attaches to the existing incident.

Topics:
    in:  vision.request    (request payload: {incident_id?, context, images: [b64,...]})
    out: incidents.vision_addendum
"""

from __future__ import annotations

from base64 import b64decode
from binascii import Error as B64Error
from hashlib import sha256
from typing import Any
from uuid import UUID

from apps.agents.shared.base import BaseAgent
from apps.agents.shared.events import IncidentVisionAddendum
from apps.agents.shared.kg_client import KnowledgeGraph
from apps.agents.shared.llm_router import LLMRouter, ModelTier, TaskClass
from apps.agents.shared.quality import KG_GROUND_ENABLED, VERIFIER_ENABLED
from apps.agents.shared.quality.kg_grounding import format_grounding_errors
from apps.agents.shared.quality.schemas import VisionFinding
from apps.agents.shared.quality.semantic_cache import SemanticCache
from apps.agents.shared.quality.structured import (
    StructuredOutputError,
    call_structured,
)
from apps.agents.shared.quality.verifier import with_verifier
from apps.agents.shared.vector_client import VectorStore

_VISION_TOPIC_OUT = "incidents.vision_addendum"
_VISION_SYSTEM = (
    "You are the Vision agent. Inspect the supplied image plus incident "
    "context and produce a structured finding. Only reference device IDs "
    "that appear in the supplied context. Cite concrete visual observations "
    "(LEDs, smoke, deformation, panel readings) — do not speculate."
)


class VisionAgent(BaseAgent):
    name = "vision"
    subscribed_topic = "vision.request"
    event_model = None

    async def on_start(self) -> None:
        await super().on_start()
        self.kg = KnowledgeGraph.from_env()
        self.vec = VectorStore.from_env()
        await self.kg.connect()
        await self.vec.connect()

        self.cache = SemanticCache(client=self.vec.client)
        self.llm = LLMRouter(agent_name=self.name, event_bus=self.bus)

        self.log.info(
            "vision.ready",
            quality_stack={
                "verifier": VERIFIER_ENABLED,
                "kg_ground": KG_GROUND_ENABLED,
                "cache": self.cache.enabled,
                "kg": self.kg.enabled,
            },
        )

    async def on_stop(self) -> None:
        await self.kg.close()
        await self.vec.close()
        await super().on_stop()

    async def handle(self, event: Any) -> None:
        request = self._extract_request(event)
        if request is None:
            self.log.debug("vision.skip", reason="invalid payload")
            return

        try:
            finding = await self._analyze(request)
        except StructuredOutputError as exc:
            self.log.warning("vision.structured_failed", error=str(exc)[:200])
            return

        self.log.info(
            "vision.finding_produced",
            severity=finding.severity.value,
            n_devices=len(finding.affected_device_ids),
            confidence=finding.confidence,
        )
        await self._publish(request, finding)

    # --- pipeline --------------------------------------------------------------

    async def _analyze(self, request: dict[str, Any]) -> VisionFinding:
        cache_key = self._cache_key(request)
        cached = await self.cache.get(cache_key)
        if cached is not None:
            try:
                return VisionFinding.model_validate_json(cached)
            except Exception:  # noqa: BLE001
                pass

        context = request.get("context", "")
        images = request.get("images", [])

        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Incident context:\n{context}"},
                    *[{"type": "image", "image": img} for img in images],
                ],
            }
        ]

        finding, _result = await call_structured(
            self.llm,
            schema=VisionFinding,
            task_class=TaskClass.MULTIMODAL,
            system=_VISION_SYSTEM,
            messages=messages,
            max_tokens=1024,
            max_retries=2,
            force_tier=ModelTier.SONNET,
        )

        if VERIFIER_ENABLED:
            finding = await self._verify(finding, messages)

        if KG_GROUND_ENABLED and finding.affected_device_ids:
            finding = await self._kg_ground(finding, messages)

        await self.cache.put(
            cache_key,
            finding.model_dump_json(),
            metadata={"agent": self.name, "site_id": self.site_id},
        )
        return finding

    async def _verify(
        self,
        finding: VisionFinding,
        messages: list[dict[str, Any]],
    ) -> VisionFinding:
        verified = await with_verifier(
            self.llm,
            task_class=TaskClass.MULTIMODAL,
            system=_VISION_SYSTEM,
            messages=[
                *messages,
                {"role": "assistant", "content": finding.model_dump_json()},
                {
                    "role": "user",
                    "content": (
                        "Review the above finding against the image evidence. "
                        "If anything is unsupported by what is actually visible, "
                        "return a corrected JSON finding."
                    ),
                },
            ],
            max_tokens=1024,
            max_revisions=1,
            force_tier=ModelTier.SONNET,
        )
        try:
            return VisionFinding.model_validate_json(verified.text)
        except Exception:  # noqa: BLE001
            return finding

    async def _kg_ground(
        self,
        finding: VisionFinding,
        messages: list[dict[str, Any]],
    ) -> VisionFinding:
        unknown = await self.kg.validate_device_ids(finding.affected_device_ids)
        if not unknown:
            return finding
        hint = format_grounding_errors(unknown_devices=unknown)
        revised_messages = [
            *messages,
            {"role": "assistant", "content": finding.model_dump_json()},
            {"role": "user", "content": hint or ""},
        ]
        try:
            revised, _ = await call_structured(
                self.llm,
                schema=VisionFinding,
                task_class=TaskClass.MULTIMODAL,
                system=_VISION_SYSTEM,
                messages=revised_messages,
                max_tokens=1024,
                max_retries=1,
                force_tier=ModelTier.SONNET,
            )
            return revised
        except StructuredOutputError:
            self.log.warning("vision.kg_ground_revise_failed", unknown=unknown)
            return finding

    # --- publish ---------------------------------------------------------------

    async def _publish(self, request: dict[str, Any], finding: VisionFinding) -> None:
        incident_id_raw = request.get("incident_id")
        incident_id: UUID | None = None
        if incident_id_raw:
            try:
                incident_id = UUID(str(incident_id_raw))
            except (ValueError, TypeError):
                incident_id = None

        # Echo the API's request_id back in metadata so the route can match.
        metadata: dict[str, Any] = {}
        request_id_raw = request.get("request_id")
        if isinstance(request_id_raw, str):
            metadata["request_id"] = request_id_raw

        addendum = IncidentVisionAddendum(
            site_id=self.site_id,
            incident_id=incident_id,
            finding_summary=finding.finding_summary,
            affected_device_ids=finding.affected_device_ids,
            severity=finding.severity.value,
            confidence=finding.confidence,
            evidence_observations=finding.evidence_observations,
            metadata=metadata,
        )
        try:
            await self.bus.publish(_VISION_TOPIC_OUT, addendum)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("vision.publish_failed", error=str(exc))

    # --- helpers ---------------------------------------------------------------

    @staticmethod
    def _extract_request(event: Any) -> dict[str, Any] | None:
        if not isinstance(event, dict):
            return None
        if "context" not in event and "images" not in event:
            return None
        return event

    @staticmethod
    def _cache_key(request: dict[str, Any]) -> str:
        """Stable cache key. Base64 images are decoded once before hashing."""
        context = str(request.get("context", ""))
        images = request.get("images") or []
        digest = sha256()
        digest.update(context.encode("utf-8"))
        digest.update(b"\x00")
        for img in images:
            if not isinstance(img, str):
                continue
            try:
                raw = b64decode(img, validate=True)
            except (B64Error, ValueError):
                raw = img.encode("utf-8")
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
        return f"vision:{digest.hexdigest()[:32]}"


if __name__ == "__main__":
    VisionAgent.run()
