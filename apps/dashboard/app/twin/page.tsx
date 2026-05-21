"use client";

// Three.js digital twin. Renders a coarse 3D representation of the data hall.
// Ships full implementation in Week 10 (real geometry, color by temp, rotate
// to affected rack on incident).
//
// `use client` because @react-three/fiber needs the browser.

import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";

function PlaceholderRack({
  position,
  hot,
}: {
  position: [number, number, number];
  hot?: boolean;
}) {
  return (
    <mesh position={position}>
      <boxGeometry args={[0.5, 2, 0.6]} />
      <meshStandardMaterial color={hot ? "#ef4444" : "#3b82f6"} />
    </mesh>
  );
}

export default function TwinPage() {
  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-2xl font-semibold">Digital twin</h1>
        <p className="mt-1 text-sm text-ink-100/60">
          3D representation of the active hall. Rotates to the affected rack on incident.
          {/* TODO(week-10): fetch /twin/state and color racks by inlet temp */}
        </p>
      </header>

      <div className="h-[60vh] rounded-xl border border-ink-100/10 bg-ink-950">
        <Canvas camera={{ position: [6, 4, 8], fov: 45 }}>
          <ambientLight intensity={0.6} />
          <directionalLight position={[5, 10, 5]} intensity={0.8} />
          {Array.from({ length: 10 }).map((_, i) => (
            <PlaceholderRack
              key={i}
              position={[i - 5, 1, 0]}
              hot={i === 6 /* placeholder "hot" rack */}
            />
          ))}
          <gridHelper args={[20, 20]} />
          <OrbitControls />
        </Canvas>
      </div>
    </div>
  );
}
