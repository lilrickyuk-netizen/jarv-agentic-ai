'use client';

import { useEffect, useRef } from 'react';
import * as THREE from 'three';

type CoreState = 'idle' | 'listening' | 'thinking' | 'planning' | 'executing' | 'speaking' | 'approval' | 'completed' | 'failed' | 'recovery';

const stateColors: Record<CoreState, number> = {
  idle: 0x38bdf8,
  listening: 0x5eead4,
  thinking: 0x60a5fa,
  planning: 0x93c5fd,
  executing: 0x38bdf8,
  speaking: 0x67e8f9,
  approval: 0xfbbf24,
  completed: 0xb8c2cc,
  failed: 0xfb7185,
  recovery: 0xf97316,
};

export function CockpitCore({ state }: { state: CoreState }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef(state);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'low-power' });
    } catch {
      mount.dataset.renderState = 'unavailable';
      return;
    }

    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.domElement.setAttribute('aria-hidden', 'true');
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 100);
    camera.position.set(0, 0, 7.2);

    const root = new THREE.Group();
    scene.add(root);

    const coreMaterial = new THREE.ShaderMaterial({
      transparent: true,
      uniforms: { uTime: { value: 0 }, uColor: { value: new THREE.Color(stateColors[stateRef.current]) } },
      vertexShader: `
        varying vec3 vNormal;
        varying vec3 vPosition;
        varying vec3 vWorldPosition;
        void main() {
          vNormal = normalize(normalMatrix * normal);
          vPosition = position;
          vec4 worldPosition = modelMatrix * vec4(position, 1.0);
          vWorldPosition = worldPosition.xyz;
          gl_Position = projectionMatrix * viewMatrix * worldPosition;
        }
      `,
      fragmentShader: `
        uniform float uTime;
        uniform vec3 uColor;
        varying vec3 vNormal;
        varying vec3 vPosition;
        varying vec3 vWorldPosition;
        void main() {
          vec3 viewDirection = normalize(cameraPosition - vWorldPosition);
          float rim = pow(1.0 - max(dot(normalize(vNormal), viewDirection), 0.0), 2.25);
          float bands = sin(vPosition.y * 20.0 + atan(vPosition.z, vPosition.x) * 5.0 - uTime * 0.65) * 0.5 + 0.5;
          float current = 0.075 + bands * 0.075 + rim * 0.82;
          vec3 color = mix(vec3(0.025, 0.08, 0.15), uColor, clamp(rim + bands * 0.14, 0.0, 1.0));
          gl_FragColor = vec4(color * current, 0.28 + rim * 0.68);
        }
      `,
    });

    const core = new THREE.Mesh(new THREE.SphereGeometry(1.16, 96, 72), coreMaterial);
    root.add(core);

    const shellMaterial = new THREE.MeshBasicMaterial({
      color: 0xb8c2cc,
      wireframe: true,
      transparent: true,
      opacity: 0.13,
    });
    const shell = new THREE.Mesh(new THREE.IcosahedronGeometry(1.38, 2), shellMaterial);
    root.add(shell);

    const ringMaterials = [
      new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.62 }),
      new THREE.MeshBasicMaterial({ color: 0xb8c2cc, transparent: true, opacity: 0.24 }),
      new THREE.MeshBasicMaterial({ color: 0x1e3a8a, transparent: true, opacity: 0.92 }),
    ];
    const rings = [
      new THREE.Mesh(new THREE.TorusGeometry(1.76, 0.009, 6, 160), ringMaterials[0]),
      new THREE.Mesh(new THREE.TorusGeometry(2.03, 0.007, 6, 160), ringMaterials[1]),
      new THREE.Mesh(new THREE.TorusGeometry(1.54, 0.012, 6, 160), ringMaterials[2]),
    ];
    rings[0].rotation.set(1.08, 0.28, -0.44);
    rings[1].rotation.set(0.42, -0.72, 0.82);
    rings[2].rotation.set(0.98, 0.76, 0.2);
    rings.forEach((ring) => root.add(ring));

    const particlePositions = new Float32Array(210 * 3);
    for (let index = 0; index < 210; index += 1) {
      const radius = 2.05 + Math.random() * 0.65;
      const theta = Math.random() * Math.PI * 2;
      const vertical = Math.random() * 2 - 1;
      const horizontal = Math.sqrt(1 - vertical * vertical);
      particlePositions[index * 3] = radius * horizontal * Math.cos(theta);
      particlePositions[index * 3 + 1] = radius * vertical;
      particlePositions[index * 3 + 2] = radius * horizontal * Math.sin(theta);
    }
    const particleGeometry = new THREE.BufferGeometry();
    particleGeometry.setAttribute('position', new THREE.BufferAttribute(particlePositions, 3));
    const particles = new THREE.Points(particleGeometry, new THREE.PointsMaterial({ color: 0x8e9baa, size: 0.018, transparent: true, opacity: 0.62 }));
    root.add(particles);

    const resize = () => {
      const width = Math.max(mount.clientWidth, 1);
      const height = Math.max(mount.clientHeight, 1);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(mount);
    resize();

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const clock = new THREE.Clock();
    let frame = 0;
    const animate = () => {
      frame = window.requestAnimationFrame(animate);
      const currentState = stateRef.current;
      const active = ['listening', 'thinking', 'planning', 'executing', 'speaking'].includes(currentState);
      const delta = clock.getDelta();
      const time = reducedMotion ? 0 : clock.elapsedTime;
      const targetColor = new THREE.Color(stateColors[currentState]);
      coreMaterial.uniforms.uColor.value.lerp(targetColor, Math.min(delta * 1.8, 1));
      coreMaterial.uniforms.uTime.value = time;
      const speed = reducedMotion ? 0 : active ? 0.15 : 0.045;
      root.rotation.y += delta * speed;
      root.rotation.x = Math.sin(time * 0.16) * (reducedMotion ? 0 : 0.035);
      core.scale.setScalar(1 + (active && !reducedMotion ? Math.sin(time * 1.7) * 0.018 : 0));
      shell.rotation.y -= delta * speed * 1.6;
      rings[0].rotation.z += delta * speed * 0.25;
      rings[1].rotation.x -= delta * speed * 0.18;
      rings[2].rotation.y += delta * speed * 0.4;
      particles.rotation.y -= delta * speed * 0.15;
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      window.cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh || object instanceof THREE.Points) {
          object.geometry.dispose();
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          materials.forEach((material) => material.dispose());
        }
      });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div ref={mountRef} className="core-canvas" role="img" aria-label={`Animated intelligence core. Current operational state: ${state}.`} data-state={state} />;
}