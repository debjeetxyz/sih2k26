import React, { useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Environment, ContactShadows, useGLTF } from '@react-three/drei';
import * as THREE from 'three';

function EngineMesh({ cht }) {
  const { nodes } = useGLTF('/engine.glb');

  const materials = useMemo(() => ({
    body: new THREE.MeshStandardMaterial({ color: '#111822', metalness: 0.8, roughness: 0.3 }),
    cyl1: new THREE.MeshStandardMaterial({ color: '#10b981', metalness: 0.6, roughness: 0.4 }),
    cyl2: new THREE.MeshStandardMaterial({ color: '#10b981', metalness: 0.6, roughness: 0.4 }),
    cyl3: new THREE.MeshStandardMaterial({ color: '#10b981', metalness: 0.6, roughness: 0.4 }),
    cyl4: new THREE.MeshStandardMaterial({ color: '#10b981', metalness: 0.6, roughness: 0.4 }),
  }), []);

  useFrame(({ clock }) => {
    const updateCylinder = (mat, temp) => {
      if (!mat) return;
      const normalizedTemp = Math.max(0, Math.min(1, (temp - 115) / 20));
      const targetColor = new THREE.Color().lerpColors(
        new THREE.Color('#10b981'), 
        new THREE.Color('#ef4444'), 
        normalizedTemp
      );
      
      mat.color.lerp(targetColor, 0.1);

      if (temp > 125) {
        mat.emissive = targetColor;
        mat.emissiveIntensity = 0.4 + Math.sin(clock.elapsedTime * 8) * 0.4;
      } else {
        mat.emissiveIntensity = 0;
      }
    };

    updateCylinder(materials.cyl1, cht[0]);
    updateCylinder(materials.cyl2, cht[1]);
    updateCylinder(materials.cyl3, cht[2]);
    updateCylinder(materials.cyl4, cht[3]);
  });

  return (
    <group dispose={null} scale={[1, 1, 1]} position={[0, -1, 0]}>
      {nodes.Engine_Body && <mesh geometry={nodes.Engine_Body.geometry} material={materials.body} />}
      {nodes.Cylinder_1 && <mesh geometry={nodes.Cylinder_1.geometry} material={materials.cyl1} />}
      {nodes.Cylinder_2 && <mesh geometry={nodes.Cylinder_2.geometry} material={materials.cyl2} />}
      {nodes.Cylinder_3 && <mesh geometry={nodes.Cylinder_3.geometry} material={materials.cyl3} />}
      {nodes.Cylinder_4 && <mesh geometry={nodes.Cylinder_4.geometry} material={materials.cyl4} />}
    </group>
  );
}

export default function EngineDigitalTwin({ telemetry }) {
  const cht = telemetry?.cht || [115, 115, 115, 115];

  return (
    <div className="w-full h-full min-h-[400px] bg-black/40 rounded border border-gcs-border relative">
      <div className="absolute top-4 left-4 z-10 text-xs font-mono text-gcs-text pointer-events-none">
        <span className="text-gcs-blue">GL_RENDERER</span>: ACTIVE<br/>
        <span className="text-gcs-highlight">MESH</span>: ROTAX_912_IMPORTED<br/>
        <span className="text-gcs-green">SHADERS</span>: DYNAMIC_THERMAL
      </div>

      <Canvas camera={{ position: [5, 4, 6], fov: 45 }}>
        <ambientLight intensity={0.4} />
        <directionalLight position={[10, 10, 5]} intensity={1.5} color="#e5e7eb" />
        <spotLight position={[-10, 10, -10]} intensity={1} color="#3b82f6" />
        <Environment preset="city" />

        <React.Suspense fallback={null}>
          <EngineMesh cht={cht} />
        </React.Suspense>

        <OrbitControls enablePan={false} autoRotate autoRotateSpeed={0.5} maxPolarAngle={Math.PI / 2 + 0.1} />
        <ContactShadows resolution={1024} scale={10} blur={2} opacity={0.8} far={10} color="#080c11" position={[0, -1.5, 0]} />
      </Canvas>
    </div>
  );
}