"""Synthetic past-incidents corpus seeded into ChromaDB by `seed_incidents.py`.

Each entry is a `{symptoms, root_cause, resolution, severity, kind}` tuple.
Symptoms text is what gets embedded for similarity search; the rest is
attached as Chroma metadata and rendered into the LLM context by
`apps.agents.shared.quality.few_shot.FewShotRetriever.format_as_examples`.

Curated to cover the common failure modes the rule layer and the
ML model are likely to flag. Realistic-ish — drawn from public incident
postmortems and NVIDIA / Backblaze / Dell support docs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PastIncident:
    id: str
    symptoms: str
    root_cause: str
    resolution: str
    severity: str           # "info" | "warn" | "error" | "critical"
    kind: str               # mirrors failure_kind labels


CORPUS: tuple[PastIncident, ...] = (
    # --- GPU ECC + XID ---
    PastIncident(
        id="inc-gpu-ecc-001",
        symptoms=(
            "GPU correctable ECC errors climbed from baseline 30/min to >5000/min "
            "over 15 minutes. GPU temperature held at 78C; utilization steady."
        ),
        root_cause=(
            "HBM stack on the GPU showed early-life failure pattern; correctable "
            "ECC storm preceded uncorrectable errors by ~6 hours."
        ),
        resolution=(
            "Drained workloads from the affected GPU and submitted RMA. "
            "Pre-emptive replacement avoided uncorrectable failure and node fault."
        ),
        severity="error",
        kind="gpu_ecc_drift",
    ),
    PastIncident(
        id="inc-gpu-xid-43",
        symptoms=(
            "XID 43 reported in dmesg; GPU page-retirement table grew. "
            "Workload became unresponsive on the affected device."
        ),
        root_cause=(
            "Double-bit memory error retired a page; GPU continued in degraded "
            "mode but with reduced effective memory."
        ),
        resolution="Replaced GPU within the 24h SLA window; no further XID since.",
        severity="critical",
        kind="gpu_fatal_xid",
    ),
    PastIncident(
        id="inc-gpu-xid-48",
        symptoms="XID 48 (double-bit ECC) in dmesg; CUDA jobs crash on launch.",
        root_cause="Catastrophic HBM failure — uncorrectable double-bit error.",
        resolution="GPU removed from service; replaced same day. RMA to NVIDIA.",
        severity="critical",
        kind="gpu_fatal_xid",
    ),
    PastIncident(
        id="inc-gpu-thermal-001",
        symptoms=(
            "GPU temperature reached 93C; clock throttled to base clock. "
            "Two adjacent GPUs in the same chassis showed 88-90C."
        ),
        root_cause=(
            "Inlet air temperature drifted to 28C following a CRAC fault "
            "in the same hall; chassis thermal envelope exceeded."
        ),
        resolution=(
            "Restored CRAC capacity, migrated half the rack's GPU workload, "
            "thermals recovered within 20 minutes."
        ),
        severity="error",
        kind="gpu_thermal",
    ),

    # --- PSU / power ---
    PastIncident(
        id="inc-psu-eff-001",
        symptoms=(
            "PSU efficiency drifted from baseline 94% to 82% over 6 hours. "
            "No load change; ambient inlet stable at 22C."
        ),
        root_cause="PSU degradation — likely capacitor aging; failure imminent.",
        resolution=(
            "Scheduled PSU swap during next maintenance window. "
            "Drift continued until replacement; no outage."
        ),
        severity="warn",
        kind="psu_efficiency_drift",
    ),
    PastIncident(
        id="inc-psu-fail-001",
        symptoms=(
            "Server lost PSU1 voltage; system continued on PSU2 with redundant "
            "power but lost N+1 redundancy. Power draw dropped to 0W on PSU1."
        ),
        root_cause="Total PSU failure — internal short.",
        resolution="Hot-swap PSU within 4 hours; restored N+1.",
        severity="critical",
        kind="psu_fail",
    ),

    # --- Cooling / thermal cascade ---
    PastIncident(
        id="inc-crac-fail-001",
        symptoms=(
            "Single CRAC unit fan_percent dropped to 0%. Hall return temperature "
            "rose 8C in 12 minutes; rack inlet temps started climbing."
        ),
        root_cause="CRAC compressor failed; backup CRAC scaled up but lagged.",
        resolution=(
            "Failed unit serviced; load redistributed across remaining CRACs. "
            "Brief workload migration from highest-density racks."
        ),
        severity="critical",
        kind="crac_fail",
    ),
    PastIncident(
        id="inc-fan-stuck-001",
        symptoms=(
            "Server fan_rpm dropped from 4200 to 0; CPU temperature rose to 84C "
            "within 5 minutes; thermal throttling kicked in."
        ),
        root_cause="Bearing failure on chassis fan #1; lockup with no rotation.",
        resolution=(
            "Workload migrated off the affected server; fan module replaced "
            "during maintenance window."
        ),
        severity="error",
        kind="thermal_cascade",
    ),
    PastIncident(
        id="inc-thermal-cascade-001",
        symptoms=(
            "Multiple racks in one hall showed inlet temperatures climbing "
            "simultaneously; GPU temps tracked the inlet rise."
        ),
        root_cause=(
            "Hot-aisle/cold-aisle containment failure — a ceiling tile shifted "
            "and disrupted airflow."
        ),
        resolution="Facilities resealed the tile; thermals stabilized.",
        severity="error",
        kind="thermal_cascade",
    ),

    # --- Storage / SMART ---
    PastIncident(
        id="inc-disk-smart-001",
        symptoms=(
            "SMART reallocated_sector_count rose from 8 to 142 over 36 hours. "
            "No I/O errors yet but pattern matches imminent failure."
        ),
        root_cause="Disk media degradation — track pre-empted failure pattern.",
        resolution=(
            "Drive evacuated and replaced before any read errors surfaced; "
            "Backblaze-trained model flagged at delta=50."
        ),
        severity="warn",
        kind="disk_smart_drift",
    ),
    PastIncident(
        id="inc-disk-realloc-burst",
        symptoms=(
            "Reallocated sector count jumped 200+ in 4 hours; pending sector "
            "count also rising. SMART status still 'PASSED' but trend bad."
        ),
        root_cause="Cascading media failure; impending uncorrectable read.",
        resolution=(
            "Removed drive from RAID; replaced. Caught before data loss "
            "because of monitoring."
        ),
        severity="error",
        kind="disk_smart_drift",
    ),

    # --- Network ---
    PastIncident(
        id="inc-switch-flap",
        symptoms=(
            "ToR switch reported port_up count dropping by 4-8 ports intermittently "
            "every 10-15 minutes. ifInErrors elevated."
        ),
        root_cause=(
            "Faulty optical transceiver caused recurring link flaps; affected "
            "ports were all on the same line card."
        ),
        resolution=(
            "Replaced transceiver; ifInErrors returned to baseline. Affected "
            "servers had transient packet loss during the flapping period."
        ),
        severity="warn",
        kind="switch_port_flap",
    ),
    PastIncident(
        id="inc-nic-drops",
        symptoms=(
            "Single server reported 5% packet drop on its primary NIC; "
            "all other NICs in the rack healthy."
        ),
        root_cause="NIC firmware bug triggered by specific traffic pattern.",
        resolution="Updated NIC firmware; drops returned to <0.01%.",
        severity="warn",
        kind="nic_packet_loss",
    ),

    # --- PDU / power distribution ---
    PastIncident(
        id="inc-pdu-overload",
        symptoms=(
            "PDU load_percent climbed to 95% (cap 80%). New deployments to "
            "the rack were rejected by the placement system."
        ),
        root_cause=(
            "Workload growth pushed rack power consumption above PDU capacity "
            "limit; capacity planning lagged actual deployment."
        ),
        resolution=(
            "Migrated three GPU servers to a cooler rack with PDU headroom. "
            "Updated capacity-planning thresholds."
        ),
        severity="error",
        kind="pdu_overload",
    ),

    # --- Mixed / multi-signal ---
    PastIncident(
        id="inc-multi-gpu-degraded",
        symptoms=(
            "Two GPUs on the same server reported ECC drift simultaneously; "
            "third GPU healthy. Server PSU efficiency also dropping."
        ),
        root_cause=(
            "PCIe slot riser issue caused intermittent signal integrity errors "
            "on two of three GPU slots."
        ),
        resolution=(
            "Reseated riser; ECC counts returned to baseline. Server pulled "
            "for further diagnosis during off-hours."
        ),
        severity="error",
        kind="gpu_ecc_drift",
    ),
    PastIncident(
        id="inc-rack-cascade",
        symptoms=(
            "Whole rack saw CPU temps climb 6-8C over 30 minutes; GPU temps "
            "climbed less but tracked the same trend. PDU load steady."
        ),
        root_cause=(
            "Adjacent rack hot-aisle containment was opened by a technician "
            "during a maintenance task; warm air recirculated."
        ),
        resolution=(
            "Containment closed; thermals recovered within 15 minutes. "
            "No workload migration required."
        ),
        severity="warn",
        kind="thermal_cascade",
    ),

    # --- Federation / cross-site (forward-looking) ---
    PastIncident(
        id="inc-federation-001",
        symptoms=(
            "Frankfurt site's Sentinel learned a new GPU ECC pattern; "
            "control plane propagated it to Singapore and Mumbai. Singapore "
            "flagged a matching pattern in shadow mode within 48 hours."
        ),
        root_cause=(
            "Same GPU revision in Singapore exhibited the same HBM degradation "
            "pattern Frankfurt's detector caught."
        ),
        resolution=(
            "Singapore enabled the rule in active mode after 48h shadow; "
            "pre-emptive RMA of three GPUs."
        ),
        severity="warn",
        kind="gpu_ecc_drift",
    ),

    # --- Operator / dashboard usage examples (for runbook collection later) ---
    PastIncident(
        id="inc-operator-001",
        symptoms="Operator was asked 'which racks ran hottest last 24h?'.",
        root_cause="N/A — informational query.",
        resolution=(
            "Operator generated a SELECT over telemetry filtered by "
            "metric=env.outlet.celsius, grouped by rack_id, ordered by max(value_num) DESC."
        ),
        severity="info",
        kind="operator_query",
    ),
)


def by_kind() -> dict[str, list[PastIncident]]:
    out: dict[str, list[PastIncident]] = {}
    for p in CORPUS:
        out.setdefault(p.kind, []).append(p)
    return out


__all__ = ["PastIncident", "CORPUS", "by_kind"]
