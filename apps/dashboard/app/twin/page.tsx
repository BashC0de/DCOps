"use client";

// Three.js digital twin. Renders the active site's racks as 3D meshes
// colored by inlet temperature. Camera + orbit are interactive.
//
// `use client` because @react-three/fiber needs the browser.

import { Canvas } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import { useMemo, useState } from "react";

import { StatusBadge } from "../../components/StatusBadge";
import { TwinRack, useFleetState, useTwinState } from "../../lib/api";

// Color ramp matching ThermalHeatmap: blue (cool) → green → amber → red (hot).
function tempColor(c: number | null | undefined): string {
  if (c == null) return "#475569";       // slate when no reading
  if (c < 22) return "#3b82f6";          // info / cool
  if (c < 26) return "#22c55e";          // ok / nominal
  if (c < 30) return "#f59e0b";          // warn
  return "#ef4444";                       // critical
}

interface RackMeshProps {
  rack: TwinRack;
  position: [number, number, number];
  hovered: boolean;
  onHover: (id: string | null) => void;
}

function RackMesh({ rack, position, hovered, onHover }: RackMeshProps) {
  const color = tempColor(rack.inlet_c);
  return (
    <group position={position}>
      <mesh
        onPointerOver={(e) => {
          e.stopPropagation();
          onHover(rack.id);
        }}
        onPointerOut={() => onHover(null)}
      >
        <boxGeometry args={[0.45, 2.0, 0.7]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={hovered ? 0.55 : 0.18}
          roughness={0.5}
          metalness={0.15}
        />
      </mesh>
      {hovered && (
        <Html distanceFactor={8} position={[0, 1.3, 0]} center>
          <div className="rounded border border-ink-100/20 bg-ink-950/95 px-2 py-1 font-mono text-[10px] text-ink-50 shadow-xl">
            <div className="text-accent-info">{rack.id}</div>
            <div>
              inlet {rack.inlet_c?.toFixed(1) ?? "?"}°C · outlet{" "}
              {rack.outlet_c?.toFixed(1) ?? "?"}°C
            </div>
            <div className="text-ink-100/60">{rack.device_count} devices</div>
          </div>
        </Html>
      )}
    </group>
  );
}

interface RackPlacement extends TwinRack {
  pos: [number, number, number];
}

function placeRacks(racks: TwinRack[]): RackPlacement[] {
  // Cluster racks by hall, lay each hall out as a grid on its own row.
  // Position fields from Neo4j are `[row, col]` per `apps/simulator/devices.py`,
  // but we fall back to deterministic placement if absent.
  const byHall = new Map<string, TwinRack[]>();
  for (const r of racks) {
    const arr = byHall.get(r.hall_id) ?? [];
    arr.push(r);
    byHall.set(r.hall_id, arr);
  }
  const halls = Array.from(byHall.keys()).sort();
  const out: RackPlacement[] = [];
  halls.forEach((hall, hallIdx) => {
    const hallRacks = byHall.get(hall) ?? [];
    hallRacks.forEach((r, i) => {
      // Use Neo4j position if available, else fall back to index.
      const row =
        Array.isArray(r.position) && typeof r.position[0] === "number"
          ? r.position[0]
          : Math.floor(i / 5);
      const col =
        Array.isArray(r.position) && typeof r.position[1] === "number"
          ? r.position[1]
          : i % 5;
      // Lay halls along z; rows in x, columns in z within a hall block.
      const x = col * 1.0 - 2.0;
      const z = hallIdx * 4.0 + row * 1.0 - 1.0;
      out.push({ ...r, pos: [x, 1.0, z] });
    });
  });
  return out;
}

export default function TwinPage() {
  const fleet = useFleetState();
  const sites = fleet.data?.sites ?? [];
  const [siteId, setSiteId] = useState<string | null>(null);
  const activeSite = siteId ?? sites[0]?.site_id ?? "frankfurt";

  const twin = useTwinState(activeSite);
  const [hovered, setHovered] = useState<string | null>(null);

  const placements = useMemo(
    () => placeRacks(twin.data?.racks ?? []),
    [twin.data?.racks],
  );

  // Camera looks down the row of racks; pull back if there are many.
  const cameraZ = Math.max(8, placements.length * 0.4);

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Digital twin</h1>
          <p className="mt-1 text-sm text-ink-100/60">
            3D representation · racks colored by inlet temperature · live refresh
          </p>
        </div>
        <div className="flex items-center gap-2">
          {(sites.length > 0 ? sites.map((s) => s.site_id) : ["frankfurt"]).map(
            (s) => (
              <button
                key={s}
                onClick={() => setSiteId(s)}
                className={`rounded-full border px-3 py-1 text-xs ${
                  activeSite === s
                    ? "border-accent-info bg-accent-info/10 text-accent-info"
                    : "border-ink-100/10 text-ink-100/70 hover:border-accent-info/30"
                }`}
              >
                {s}
              </button>
            ),
          )}
          {twin.data?.status === "degraded" && (
            <StatusBadge status="degraded">degraded</StatusBadge>
          )}
        </div>
      </header>

      <div className="flex flex-wrap gap-2 text-xs text-ink-100/60">
        <LegendChip color="#3b82f6" label="< 22°C cool" />
        <LegendChip color="#22c55e" label="22–26°C ok" />
        <LegendChip color="#f59e0b" label="26–30°C warn" />
        <LegendChip color="#ef4444" label="≥ 30°C hot" />
        <LegendChip color="#475569" label="no reading" />
      </div>

      <div className="relative h-[65vh] overflow-hidden rounded-xl border border-ink-100/10 bg-ink-950">
        {placements.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-ink-100/60">
            No rack topology yet for{" "}
            <span className="ml-1 font-mono text-accent-info">{activeSite}</span>
            . Run <code className="ml-1 font-mono text-accent-info">make seed</code>{" "}
            and wait for telemetry to flow.
          </div>
        ) : (
          <Canvas camera={{ position: [cameraZ * 0.6, cameraZ * 0.5, cameraZ], fov: 45 }}>
            <ambientLight intensity={0.55} />
            <directionalLight position={[8, 12, 6]} intensity={0.9} />
            <directionalLight position={[-8, 6, -6]} intensity={0.3} />
            {placements.map((rp) => (
              <RackMesh
                key={rp.id}
                rack={rp}
                position={rp.pos}
                hovered={hovered === rp.id}
                onHover={setHovered}
              />
            ))}
            <gridHelper args={[30, 30, "#1f2937", "#1f2937"]} />
            <OrbitControls
              enablePan
              enableZoom
              enableRotate
              maxDistance={40}
              minDistance={3}
            />
          </Canvas>
        )}
      </div>

      <p className="text-xs text-ink-100/50">
        {placements.length} rack(s) · drag to orbit · scroll to zoom · hover a rack
        for details
      </p>
    </div>
  );
}

function LegendChip({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-ink-100/10 bg-ink-900/40 px-2 py-0.5">
      <span
        className="inline-block h-2.5 w-2.5 rounded-sm"
        style={{ backgroundColor: color }}
      />
      <span>{label}</span>
    </span>
  );
}
