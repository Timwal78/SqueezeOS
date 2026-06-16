import { useRef, useEffect, useMemo } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Environment } from "@react-three/drei";
import * as THREE from "three";
import gsap from "gsap";

function Globe() {
  const meshRef = useRef<THREE.Mesh>(null);
  const wireRef = useRef<THREE.LineSegments>(null);
  const atmosphereRef = useRef<THREE.Mesh>(null);

  useFrame((state) => {
    const t = state.clock.getElapsedTime();
    if (meshRef.current) {
      meshRef.current.rotation.y = t * 0.1;
    }
    if (wireRef.current) {
      wireRef.current.rotation.y = t * 0.1;
    }
    if (atmosphereRef.current) {
      atmosphereRef.current.rotation.y = t * 0.08;
      atmosphereRef.current.rotation.x = Math.sin(t * 0.05) * 0.1;
    }
  });

  const wireGeo = useMemo(() => {
    const geo = new THREE.IcosahedronGeometry(1.8, 3);
    const edges = new THREE.EdgesGeometry(geo);
    return edges;
  }, []);

  return (
    <group>
      {/* Core sphere */}
      <mesh ref={meshRef}>
        <sphereGeometry args={[1.8, 32, 32]} />
        <meshStandardMaterial
          color="#050505"
          roughness={0.8}
          metalness={0.9}
          emissive="#00E5FF"
          emissiveIntensity={0.05}
          transparent
          opacity={0.9}
        />
      </mesh>

      {/* Wireframe overlay */}
      <lineSegments ref={wireRef} geometry={wireGeo}>
        <lineBasicMaterial color="#00E5FF" transparent opacity={0.3} />
      </lineSegments>

      {/* Atmosphere glow */}
      <mesh ref={atmosphereRef}>
        <sphereGeometry args={[2.1, 32, 32]} />
        <meshStandardMaterial
          color="#00E5FF"
          transparent
          opacity={0.04}
          side={THREE.BackSide}
          emissive="#00E5FF"
          emissiveIntensity={0.2}
        />
      </mesh>
    </group>
  );
}

function OrbitLines() {
  const groupRef = useRef<THREE.Group>(null);

  useFrame((state) => {
    if (groupRef.current) {
      groupRef.current.rotation.y = state.clock.getElapsedTime() * 0.03;
    }
  });

  const orbits = useMemo(() => {
    return [
      { radius: 3.2, color: "#00E5FF", opacity: 0.15 },
      { radius: 4.0, color: "#7B2D8E", opacity: 0.1 },
      { radius: 5.0, color: "#39FF14", opacity: 0.08 },
    ];
  }, []);

  return (
    <group ref={groupRef}>
      {orbits.map((orbit, i) => {
        const points = [];
        for (let j = 0; j <= 64; j++) {
          const angle = (j / 64) * Math.PI * 2;
          points.push(
            new THREE.Vector3(
              Math.cos(angle) * orbit.radius,
              Math.sin(i * 0.3) * 0.3,
              Math.sin(angle) * orbit.radius
            )
          );
        }
        const geometry = new THREE.BufferGeometry().setFromPoints(points);
        return (
          <primitive key={i} object={new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: orbit.color, transparent: true, opacity: orbit.opacity }))} />
        );
      })}
    </group>
  );
}

function DataNodes() {
  const nodesRef = useRef<THREE.Group>(null);

  const nodes = useMemo(() => {
    const positions: { pos: [number, number, number]; color: string; size: number }[] = [];
    const colors = ["#00E5FF", "#39FF14", "#7B2D8E", "#FFFFFF"];
    const numNodes = 20;
    const phi = Math.PI * (3 - Math.sqrt(5)); // golden angle
    
    for (let i = 0; i < numNodes; i++) {
      const y = 1 - (i / (numNodes - 1)) * 2; // y goes from 1 to -1
      const radiusAtY = Math.sqrt(1 - y * y); // radius at y
      const theta = phi * i; // golden angle increment
      
      const r = 2.5 + (i % 3) * 0.5; // deterministic radius layering
      
      positions.push({
        pos: [
          r * Math.cos(theta) * radiusAtY,
          r * y,
          r * Math.sin(theta) * radiusAtY,
        ],
        color: colors[i % colors.length],
        size: 0.03 + (i % 3) * 0.01,
      });
    }
    return positions;
  }, []);

  useFrame((state) => {
    if (nodesRef.current) {
      nodesRef.current.rotation.y = state.clock.getElapsedTime() * 0.05;
    }
  });

  return (
    <group ref={nodesRef}>
      {nodes.map((node, i) => (
        <mesh key={i} position={node.pos}>
          <sphereGeometry args={[node.size, 8, 8]} />
          <meshStandardMaterial
            color={node.color}
            emissive={node.color}
            emissiveIntensity={0.8}
            transparent
            opacity={0.7}
          />
        </mesh>
      ))}
    </group>
  );
}

function Scene() {
  return (
    <>
      <ambientLight intensity={Math.PI / 2} />
      <spotLight position={[10, 10, 10]} angle={0.15} penumbra={1} decay={0} intensity={Math.PI} />
      <Environment preset="city" blur={10} />
      <Globe />
      <OrbitLines />
      <DataNodes />
    </>
  );
}

function generateMatrix3D(rotationY: number, rotationX: number): string {
  return new DOMMatrix()
    .rotateAxisAngleSelf(1, 0, 0, rotationX)
    .rotateAxisAngleSelf(0, 1, 0, rotationY)
    .toString();
}

export default function HolographicGlobe() {
  const containerRef = useRef<HTMLDivElement>(null);
  const targetRot = useRef({ x: -10, y: 25 });
  const currentRot = useRef({ x: -10, y: 25 });
  const rafId = useRef<number>(0);

  useEffect(() => {
    function onMouseMove(e: MouseEvent) {
      const x = (e.clientX / window.innerWidth - 0.5) * 2;
      const y = (e.clientY / window.innerHeight - 0.5) * 2;
      targetRot.current.y = 25 + x * 20;
      targetRot.current.x = -10 + y * 10;
    }

    function render() {
      (currentRot.current as Record<string, number>).x = gsap.utils.interpolate(
        (currentRot.current as Record<string, number>).x,
        (targetRot.current as Record<string, number>).x,
        0.05
      );
      (currentRot.current as Record<string, number>).y = gsap.utils.interpolate(
        (currentRot.current as Record<string, number>).y,
        (targetRot.current as Record<string, number>).y,
        0.05
      );

      if (containerRef.current) {
        containerRef.current.style.transform = generateMatrix3D(
          (currentRot.current as Record<string, number>).y,
          (currentRot.current as Record<string, number>).x
        );
      }

      rafId.current = requestAnimationFrame(render);
    }

    render();
    document.body.addEventListener("mousemove", onMouseMove);

    return () => {
      cancelAnimationFrame(rafId.current);
      document.body.removeEventListener("mousemove", onMouseMove);
    };
  }, []);

  return (
    <div className="scene-container" style={{ perspective: "1000px", transformStyle: "preserve-3d" }}>
      <div
        ref={containerRef}
        className="projection-card"
        style={{
          background: "transparent",
          border: "1px solid rgba(0, 229, 255, 0.2)",
          boxShadow: "0 0 50px rgba(0, 229, 255, 0.05)",
          backdropFilter: "blur(2px)",
          transformStyle: "preserve-3d",
          width: "100%",
          height: "100%",
          minHeight: "500px",
        }}
      >
        <Canvas flat linear camera={{ position: [0, 0, 8], fov: 45 }} style={{ width: "100%", height: "100%" }}>
          <Scene />
        </Canvas>
      </div>
    </div>
  );
}
