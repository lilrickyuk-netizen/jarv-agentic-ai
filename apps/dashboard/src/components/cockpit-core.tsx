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

const ACTIVE: CoreState[] = ['listening', 'thinking', 'planning', 'executing', 'speaking'];

/** A soft round glow, drawn once, used by every point and halo (additive blending makes overlaps brighter). */
function glowTexture(): THREE.CanvasTexture {
  const size = 128;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext('2d');
  if (context) {
    const gradient = context.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    gradient.addColorStop(0, 'rgba(255,255,255,1)');
    gradient.addColorStop(0.18, 'rgba(255,255,255,0.85)');
    gradient.addColorStop(0.45, 'rgba(255,255,255,0.22)');
    gradient.addColorStop(1, 'rgba(255,255,255,0)');
    context.fillStyle = gradient;
    context.fillRect(0, 0, size, size);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

const POINT_VERTEX = `
  attribute float aSize;
  attribute float aPhase;
  uniform float uTime;
  uniform float uPixelRatio;
  uniform float uPulse;
  uniform float uBackFade;
  varying float vAlpha;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    float twinkle = 0.55 + 0.45 * sin(uTime * 1.7 + aPhase);
    vec3 n = normalize((modelMatrix * vec4(position, 0.0)).xyz);
    float facing = mix(1.0, 0.25 + 0.75 * smoothstep(-0.7, 0.6, n.z), uBackFade);
    vAlpha = twinkle * facing;
    gl_PointSize = aSize * uPixelRatio * (1.0 + uPulse * 0.35) * (18.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;

const POINT_FRAGMENT = `
  uniform sampler2D uMap;
  uniform vec3 uColor;
  uniform float uWhite;
  varying float vAlpha;
  void main() {
    float a = texture2D(uMap, gl_PointCoord).a * vAlpha;
    gl_FragColor = vec4(mix(uColor, vec3(1.0), uWhite) * a, a);
  }
`;

function pointMaterial(map: THREE.Texture, color: THREE.Color, white: number, backFade: number) {
  return new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uPixelRatio: { value: 1 },
      uPulse: { value: 0 },
      uBackFade: { value: backFade },
      uMap: { value: map },
      uColor: { value: color },
      uWhite: { value: white },
    },
    vertexShader: POINT_VERTEX,
    fragmentShader: POINT_FRAGMENT,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
}

/** Points spread evenly over a sphere (Fibonacci lattice), each with its own size and twinkle phase. */
function globePoints(count: number, radius: number) {
  const positions = new Float32Array(count * 3);
  const sizes = new Float32Array(count);
  const phases = new Float32Array(count);
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < count; i += 1) {
    const y = 1 - (i / (count - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    const theta = golden * i;
    const jitter = radius * (1 + (Math.random() - 0.5) * 0.018);
    positions[i * 3] = Math.cos(theta) * r * jitter;
    positions[i * 3 + 1] = y * jitter;
    positions[i * 3 + 2] = Math.sin(theta) * r * jitter;
    sizes[i] = 0.9 + Math.random() * 1.6 + (Math.random() < 0.04 ? 2.6 : 0);
    phases[i] = Math.random() * Math.PI * 2;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1));
  geometry.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1));
  return geometry;
}

/** A swirling band of dust around the globe. */
function dustBand(count: number, inner: number, outer: number) {
  const positions = new Float32Array(count * 3);
  const sizes = new Float32Array(count);
  const phases = new Float32Array(count);
  for (let i = 0; i < count; i += 1) {
    const angle = Math.random() * Math.PI * 2;
    const radius = inner + Math.pow(Math.random(), 1.6) * (outer - inner);
    positions[i * 3] = Math.cos(angle) * radius;
    positions[i * 3 + 1] = (Math.random() - 0.5) * 0.16 * (radius - inner + 0.4);
    positions[i * 3 + 2] = Math.sin(angle) * radius;
    sizes[i] = 0.6 + Math.random() * 1.4;
    phases[i] = Math.random() * Math.PI * 2;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1));
  geometry.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1));
  return geometry;
}

/** Latitude and longitude lines of the globe. */
function gridLines(radius: number) {
  const vertices: number[] = [];
  const segments = 96;
  for (let lat = -75; lat <= 75; lat += 15) {
    const y = radius * Math.sin((lat * Math.PI) / 180);
    const r = radius * Math.cos((lat * Math.PI) / 180);
    for (let s = 0; s < segments; s += 1) {
      const a0 = (s / segments) * Math.PI * 2;
      const a1 = ((s + 1) / segments) * Math.PI * 2;
      vertices.push(Math.cos(a0) * r, y, Math.sin(a0) * r, Math.cos(a1) * r, y, Math.sin(a1) * r);
    }
  }
  for (let lon = 0; lon < 180; lon += 15) {
    const phi = (lon * Math.PI) / 180;
    for (let s = 0; s < segments; s += 1) {
      const a0 = (s / segments) * Math.PI * 2;
      const a1 = ((s + 1) / segments) * Math.PI * 2;
      vertices.push(
        Math.cos(a0) * radius * Math.cos(phi), Math.sin(a0) * radius, Math.cos(a0) * radius * Math.sin(phi),
        Math.cos(a1) * radius * Math.cos(phi), Math.sin(a1) * radius, Math.cos(a1) * radius * Math.sin(phi),
      );
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
  return geometry;
}

type Orbit = { group: THREE.Group; curve: THREE.EllipseCurve; comet: THREE.Points; speed: number; offset: number };
const TRAIL = 28;

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
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'high-performance' });
    } catch {
      mount.dataset.renderState = 'unavailable';
      return;
    }

    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    renderer.setPixelRatio(pixelRatio);
    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.domElement.setAttribute('aria-hidden', 'true');
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 100);
    camera.position.set(0, 0, 7.4);

    const glow = glowTexture();
    const accent = new THREE.Color(stateColors[stateRef.current]);
    const root = new THREE.Group();
    root.rotation.z = -0.18;
    scene.add(root);

    // Halo: the bright light the whole field sits in.
    const haloMaterial = new THREE.SpriteMaterial({ map: glow, color: accent, transparent: true, opacity: 0.55, blending: THREE.AdditiveBlending, depthWrite: false });
    const halo = new THREE.Sprite(haloMaterial);
    halo.scale.setScalar(5.4);
    scene.add(halo);
    const innerHaloMaterial = new THREE.SpriteMaterial({ map: glow, color: 0xffffff, transparent: true, opacity: 0.16, blending: THREE.AdditiveBlending, depthWrite: false });
    const innerHalo = new THREE.Sprite(innerHaloMaterial);
    innerHalo.scale.setScalar(2.6);
    scene.add(innerHalo);

    // Core: a dark sphere lit at its edge (fresnel), slowly banded.
    const coreMaterial = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      uniforms: { uTime: { value: 0 }, uColor: { value: accent } },
      vertexShader: `
        varying vec3 vNormal;
        varying vec3 vWorld;
        varying vec3 vPos;
        void main() {
          vNormal = normalize(normalMatrix * normal);
          vPos = position;
          vec4 world = modelMatrix * vec4(position, 1.0);
          vWorld = world.xyz;
          gl_Position = projectionMatrix * viewMatrix * world;
        }
      `,
      fragmentShader: `
        uniform float uTime;
        uniform vec3 uColor;
        varying vec3 vNormal;
        varying vec3 vWorld;
        varying vec3 vPos;
        void main() {
          vec3 view = normalize(cameraPosition - vWorld);
          float rim = pow(1.0 - max(dot(normalize(vNormal), view), 0.0), 2.4);
          float bands = sin(vPos.y * 16.0 + atan(vPos.z, vPos.x) * 4.0 - uTime * 0.9) * 0.5 + 0.5;
          float light = rim * 1.15 + bands * 0.06 + 0.04;
          gl_FragColor = vec4(mix(uColor, vec3(1.0), rim * 0.35) * light, light);
        }
      `,
    });
    const core = new THREE.Mesh(new THREE.SphereGeometry(1.18, 96, 72), coreMaterial);
    root.add(core);

    const globe = new THREE.Group();
    root.add(globe);
    const gridMaterial = new THREE.LineBasicMaterial({ color: accent, transparent: true, opacity: 0.2, blending: THREE.AdditiveBlending, depthWrite: false });
    globe.add(new THREE.LineSegments(gridLines(1.24), gridMaterial));
    const globeMaterial = pointMaterial(glow, accent, 0.45, 1);
    const globeCloud = new THREE.Points(globePoints(2600, 1.26), globeMaterial);
    globe.add(globeCloud);

    // Outer field: two dust bands at different tilts, turning in opposite directions.
    const dustMaterial = pointMaterial(glow, accent, 0.2, 0);
    const dustA = new THREE.Points(dustBand(900, 1.55, 2.5), dustMaterial);
    dustA.rotation.set(1.22, 0, 0.3);
    root.add(dustA);
    const dustB = new THREE.Points(dustBand(500, 1.7, 2.35), dustMaterial);
    dustB.rotation.set(0.5, 0, -0.9);
    root.add(dustB);

    // Orbits: bright ellipses, each with a comet and its trail travelling round it.
    const orbitMaterial = new THREE.LineBasicMaterial({ color: accent, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending, depthWrite: false });
    const cometMaterial = pointMaterial(glow, accent, 0.7, 0);
    const orbitSpecs = [
      { rx: 2.25, ry: 0.72, tilt: [1.2, 0.15, -0.42], speed: 0.16, offset: 0 },
      { rx: 2.0, ry: 0.95, tilt: [0.62, -0.5, 0.78], speed: -0.12, offset: 2.1 },
      { rx: 1.78, ry: 1.78, tilt: [1.45, 0.62, 0.1], speed: 0.21, offset: 4.2 },
    ];
    const orbits: Orbit[] = orbitSpecs.map((spec) => {
      const group = new THREE.Group();
      group.rotation.set(spec.tilt[0], spec.tilt[1], spec.tilt[2]);
      const curve = new THREE.EllipseCurve(0, 0, spec.rx, spec.ry, 0, Math.PI * 2, false, 0);
      const line = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(curve.getPoints(240)), orbitMaterial);
      group.add(line);
      const trail = new THREE.BufferGeometry();
      trail.setAttribute('position', new THREE.BufferAttribute(new Float32Array(TRAIL * 3), 3));
      const sizes = new Float32Array(TRAIL);
      const phases = new Float32Array(TRAIL);
      for (let i = 0; i < TRAIL; i += 1) {
        sizes[i] = i === 0 ? 9 : 5.5 * (1 - i / TRAIL) + 0.6;
        phases[i] = Math.PI / 2;
      }
      trail.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1));
      trail.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1));
      const comet = new THREE.Points(trail, cometMaterial);
      group.add(comet);
      root.add(group);
      return { group, curve, comet, speed: spec.speed, offset: spec.offset };
    });

    const pointMaterials = [globeMaterial, dustMaterial, cometMaterial];
    pointMaterials.forEach((material) => { material.uniforms.uPixelRatio.value = pixelRatio; });

    const resize = () => {
      const width = Math.max(mount.clientWidth, 1);
      const height = Math.max(mount.clientHeight, 1);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      // Keep the whole field in view on narrow screens.
      camera.position.z = width < height ? 7.4 * (height / width) * 0.85 : 7.4;
      camera.updateProjectionMatrix();
    };
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(mount);
    resize();

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const clock = new THREE.Clock();
    const point = new THREE.Vector2();
    let pulse = 0;
    let frame = 0;
    const animate = () => {
      frame = window.requestAnimationFrame(animate);
      const current = stateRef.current;
      const active = ACTIVE.includes(current);
      const delta = Math.min(clock.getDelta(), 0.1);
      const time = reducedMotion ? 0 : clock.elapsedTime;
      accent.lerp(new THREE.Color(stateColors[current]), Math.min(delta * 2, 1));
      haloMaterial.color.copy(accent);
      gridMaterial.color.copy(accent);
      orbitMaterial.color.copy(accent);

      // Busy states pulse and turn faster; approval breathes slowly so it reads as waiting.
      const beat = current === 'approval' ? 0.5 + 0.5 * Math.sin(time * 1.4) : active ? 0.5 + 0.5 * Math.sin(time * 3.2) : 0;
      pulse += ((reducedMotion ? 0 : beat) - pulse) * Math.min(delta * 6, 1);
      const speed = reducedMotion ? 0 : active ? 1 : 0.45;

      coreMaterial.uniforms.uTime.value = time;
      pointMaterials.forEach((material) => {
        material.uniforms.uTime.value = time;
        material.uniforms.uPulse.value = pulse;
      });
      haloMaterial.opacity = 0.5 + pulse * 0.2;
      halo.scale.setScalar(5.4 + pulse * 0.35);
      innerHaloMaterial.opacity = 0.14 + pulse * 0.1;

      globe.rotation.y += delta * 0.22 * speed;
      core.rotation.y -= delta * 0.1 * speed;
      dustA.rotation.y += delta * 0.09 * speed;
      dustB.rotation.y -= delta * 0.13 * speed;
      root.rotation.x = Math.sin(time * 0.2) * 0.06;

      orbits.forEach((orbit) => {
        orbit.group.rotation.z += delta * 0.03 * speed;
        const head = (((time * orbit.speed * (active ? 1.6 : 1)) + orbit.offset) % 1 + 1) % 1;
        const positions = orbit.comet.geometry.getAttribute('position') as THREE.BufferAttribute;
        for (let i = 0; i < TRAIL; i += 1) {
          const t = ((head - Math.sign(orbit.speed) * i * 0.0065) % 1 + 1) % 1;
          orbit.curve.getPoint(t, point);
          positions.setXYZ(i, point.x, point.y, 0);
        }
        positions.needsUpdate = true;
      });

      renderer.render(scene, camera);
    };
    animate();

    return () => {
      window.cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      const materials = new Set<THREE.Material>();
      scene.traverse((object) => {
        const holder = object as THREE.Object3D & { geometry?: THREE.BufferGeometry; material?: THREE.Material | THREE.Material[] };
        if (holder.geometry) holder.geometry.dispose();
        if (holder.material) (Array.isArray(holder.material) ? holder.material : [holder.material]).forEach((m) => materials.add(m));
      });
      materials.forEach((material) => material.dispose());
      glow.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div ref={mountRef} className="core-canvas" role="img" aria-label={`Animated intelligence field. Current operational state: ${state}.`} data-state={state} />;
}
