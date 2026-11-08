'use client';

import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { getVoiceStream, subscribeVoice } from '@/lib/voice-signal';

/**
 * JAI's intelligence field (Upgrade 8): an original Three.js network of about 2,000 nodes in a slowly turning
 * sphere, thin connections between nearby nodes, and signals of light travelling along the connections from node
 * to node. It is driven by JAI's real state (the Command Center derives it from missions, approvals, the feed and
 * the live voice) and by the audio of JAI's own voice, so it moves with every word JAI says.
 */
export type FieldState =
  | 'idle' | 'listening' | 'thinking' | 'planning' | 'executing' | 'speaking'
  | 'approval' | 'completed' | 'failed' | 'recovery';

export const FIELD_STATES: FieldState[] = [
  'idle', 'listening', 'thinking', 'planning', 'executing', 'speaking', 'approval', 'completed', 'failed', 'recovery',
];

export interface FieldLook {
  color: number;      // the field's light
  radius: number;     // how far the network opens
  turbulence: number; // how much each node wanders
  spin: number;       // turns per minute, roughly
  signals: number;    // share of the signal pool travelling (0 to 1)
  signalSpeed: number;// connections crossed per second
  order: number;      // 0 free, 1 drawn into ordered bands (planning)
  links: number;      // brightness of the connections
  pulse: number;      // breathing speed (0 none)
  inward: number;     // 1: signals head for the centre (waiting on Richard)
  shake: number;      // a failure's tremor
}

/** How the field looks in each of JAI's ten states. Blue is normal; amber waits for Richard; red is a failure. */
export const FIELD_LOOKS: Record<FieldState, FieldLook> = {
  idle:      { color: 0x2f7bff, radius: 1.0,  turbulence: 0.025, spin: 0.6, signals: 0.15, signalSpeed: 0.8, order: 0, links: 0.55, pulse: 0.5, inward: 0, shake: 0 },
  listening: { color: 0x48a2ff, radius: 1.06, turbulence: 0.035, spin: 0.8, signals: 0.3,  signalSpeed: 1.2, order: 0, links: 0.7,  pulse: 1.4, inward: 0.4, shake: 0 },
  thinking:  { color: 0x5b7cff, radius: 0.92, turbulence: 0.07,  spin: 1.6, signals: 0.55, signalSpeed: 2.2, order: 0, links: 0.8,  pulse: 2.2, inward: 0, shake: 0 },
  planning:  { color: 0x3a8dff, radius: 1.0,  turbulence: 0.02,  spin: 1.0, signals: 0.5,  signalSpeed: 1.6, order: 1, links: 0.95, pulse: 0.8, inward: 0, shake: 0 },
  executing: { color: 0x3d9bff, radius: 1.12, turbulence: 0.04,  spin: 1.3, signals: 1.0,  signalSpeed: 3.2, order: 0.25, links: 0.9, pulse: 1.6, inward: 0, shake: 0 },
  speaking:  { color: 0x6ab8ff, radius: 1.1,  turbulence: 0.04,  spin: 1.0, signals: 0.7,  signalSpeed: 2.4, order: 0, links: 0.85, pulse: 0,   inward: 0, shake: 0 },
  approval:  { color: 0xfbbf24, radius: 0.94, turbulence: 0.015, spin: 0.35, signals: 0.4, signalSpeed: 0.9, order: 0, links: 0.75, pulse: 0.9, inward: 1, shake: 0 },
  completed: { color: 0x34d399, radius: 1.08, turbulence: 0.02,  spin: 0.7, signals: 0.35, signalSpeed: 1.4, order: 0, links: 0.8,  pulse: 0.6, inward: 0, shake: 0 },
  failed:    { color: 0xfb7185, radius: 0.9,  turbulence: 0.03,  spin: 0.3, signals: 0.12, signalSpeed: 0.6, order: 0, links: 0.45, pulse: 0,   inward: 0, shake: 1 },
  recovery:  { color: 0x2fb5ff, radius: 0.98, turbulence: 0.045, spin: 0.9, signals: 0.6,  signalSpeed: 2.0, order: 0.4, links: 0.75, pulse: 1.2, inward: 0, shake: 0 },
};

/** Nodes for a field of this size: about 2,000 on a desktop panel, fewer on a phone so it stays smooth. */
export function nodeCount(width: number, height: number): number {
  const area = Math.max(1, width) * Math.max(1, height);
  return Math.round(Math.max(700, Math.min(2000, area / 160)));
}

const SIGNALS = 160;
const LINKS_PER_NODE = 3;

function glow(): THREE.CanvasTexture {
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext('2d');
  if (context) {
    const gradient = context.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    gradient.addColorStop(0, 'rgba(255,255,255,1)');
    gradient.addColorStop(0.25, 'rgba(255,255,255,0.7)');
    gradient.addColorStop(1, 'rgba(255,255,255,0)');
    context.fillStyle = gradient;
    context.fillRect(0, 0, size, size);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/** A deterministic random sequence, so the network is the same shape every time the page opens. */
function seeded(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

interface Network {
  homes: Float32Array;   // each node's resting place
  banded: Float32Array;  // the same node drawn onto an ordered latitude band (planning)
  phases: Float32Array;
  edges: Uint32Array;    // pairs of node indices
  neighbours: number[][];// edge indices touching each node
}

export function buildNetwork(count: number, seed = 7): Network {
  const random = seeded(seed);
  const homes = new Float32Array(count * 3);
  const banded = new Float32Array(count * 3);
  const phases = new Float32Array(count);
  const golden = Math.PI * (3 - Math.sqrt(5));
  const bands = 9;
  for (let i = 0; i < count; i += 1) {
    const y = 1 - (i / Math.max(1, count - 1)) * 2;
    const ring = Math.sqrt(1 - y * y);
    const theta = golden * i;
    const depth = 0.55 + 0.45 * Math.cbrt(random()); // a shell with depth, denser near the surface
    homes[i * 3] = Math.cos(theta) * ring * depth;
    homes[i * 3 + 1] = y * depth;
    homes[i * 3 + 2] = Math.sin(theta) * ring * depth;
    const bandY = Math.round(((y + 1) / 2) * (bands - 1)) / (bands - 1) * 2 - 1;
    const bandRing = Math.sqrt(Math.max(0, 1 - bandY * bandY));
    banded[i * 3] = Math.cos(theta) * bandRing * 0.92;
    banded[i * 3 + 1] = bandY * 0.92;
    banded[i * 3 + 2] = Math.sin(theta) * bandRing * 0.92;
    phases[i] = random() * Math.PI * 2;
  }
  // Each node links to its nearest few within reach: thin connections between neighbours only.
  const reach = 2.4 / Math.sqrt(count) + 0.06;
  const reach2 = reach * reach;
  const seen = new Set<number>();
  const pairs: number[] = [];
  const neighbours: number[][] = Array.from({ length: count }, () => []);
  for (let i = 0; i < count; i += 1) {
    const near: Array<[number, number]> = [];
    let closest: [number, number] = [Infinity, -1];
    for (let j = 0; j < count; j += 1) {
      if (i === j) continue;
      const dx = homes[i * 3] - homes[j * 3];
      const dy = homes[i * 3 + 1] - homes[j * 3 + 1];
      const dz = homes[i * 3 + 2] - homes[j * 3 + 2];
      const d2 = dx * dx + dy * dy + dz * dz;
      if (d2 < reach2) near.push([d2, j]);
      if (d2 < closest[0]) closest = [d2, j];
    }
    if (near.length === 0 && closest[1] >= 0) near.push(closest); // no node is left unconnected
    near.sort((a, b) => a[0] - b[0]);
    for (const [, j] of near.slice(0, LINKS_PER_NODE)) {
      const key = i < j ? i * count + j : j * count + i;
      if (seen.has(key)) continue;
      seen.add(key);
      const edge = pairs.length / 2;
      pairs.push(i, j);
      neighbours[i].push(edge);
      neighbours[j].push(edge);
    }
  }
  return { homes, banded, phases, edges: Uint32Array.from(pairs), neighbours };
}

export function IntelligenceField({ state }: { state: FieldState }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef<FieldState>(state);
  const changedRef = useRef(0);
  const redrawRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (stateRef.current !== state) changedRef.current = performance.now();
    stateRef.current = state;
    redrawRef.current?.();
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
    mount.dataset.renderState = 'ready';
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    renderer.setPixelRatio(pixelRatio);
    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.domElement.setAttribute('aria-hidden', 'true');
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 50);
    camera.position.set(0, 0, 4.4);
    const group = new THREE.Group();
    scene.add(group);

    const count = nodeCount(mount.clientWidth || 640, mount.clientHeight || 520);
    const network = buildNetwork(count);
    const edgeCount = network.edges.length / 2;
    const texture = glow();
    const look = { ...FIELD_LOOKS[stateRef.current] };
    const color = new THREE.Color(look.color);

    // Nodes.
    const nodePositions = new Float32Array(count * 3);
    const nodeGeometry = new THREE.BufferGeometry();
    nodeGeometry.setAttribute('position', new THREE.BufferAttribute(nodePositions, 3).setUsage(THREE.DynamicDrawUsage));
    const nodeMaterial = new THREE.PointsMaterial({ size: 0.028, map: texture, color, transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending, sizeAttenuation: true, opacity: 0.9 });
    const nodes = new THREE.Points(nodeGeometry, nodeMaterial);
    group.add(nodes);

    // Connections: drawn from the nodes' current places every frame.
    const linkPositions = new Float32Array(edgeCount * 6);
    const linkGeometry = new THREE.BufferGeometry();
    linkGeometry.setAttribute('position', new THREE.BufferAttribute(linkPositions, 3).setUsage(THREE.DynamicDrawUsage));
    const linkMaterial = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.18, depthWrite: false,
      blending: THREE.AdditiveBlending });
    const links = new THREE.LineSegments(linkGeometry, linkMaterial);
    group.add(links);

    // Signals: lights travelling along connections, hopping on from node to node.
    const random = seeded(99);
    const signalEdge = new Uint32Array(SIGNALS);
    const signalForward = new Uint8Array(SIGNALS);
    const signalProgress = new Float32Array(SIGNALS);
    for (let s = 0; s < SIGNALS; s += 1) {
      signalEdge[s] = Math.floor(random() * Math.max(1, edgeCount));
      signalForward[s] = random() > 0.5 ? 1 : 0;
      signalProgress[s] = random();
    }
    const signalPositions = new Float32Array(SIGNALS * 3);
    const signalGeometry = new THREE.BufferGeometry();
    signalGeometry.setAttribute('position', new THREE.BufferAttribute(signalPositions, 3).setUsage(THREE.DynamicDrawUsage));
    const signalMaterial = new THREE.PointsMaterial({ size: 0.075, map: texture, color: new THREE.Color(0xffffff),
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true, opacity: 0.95 });
    const signals = new THREE.Points(signalGeometry, signalMaterial);
    group.add(signals);

    const resize = () => {
      const width = Math.max(mount.clientWidth, 1);
      const height = Math.max(mount.clientHeight, 1);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.position.z = width < height ? 4.4 * (height / width) * 0.85 : 4.4;
      camera.updateProjectionMatrix();
    };
    const resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
      resize();
      redrawRef.current?.();
    });
    resizeObserver?.observe(mount);
    resize();

    // JAI's voice: the field listens to the live voice stream (analysed only, never played twice).
    let audioContext: AudioContext | null = null;
    let analyser: AnalyserNode | null = null;
    let source: MediaStreamAudioSourceNode | null = null;
    let samples: Uint8Array<ArrayBuffer> | null = null;
    let listened: MediaStream | null = null;
    const listen = () => {
      const stream = getVoiceStream();
      if (stream === listened) return;
      listened = stream;
      source?.disconnect();
      source = null;
      if (!stream || stream.getAudioTracks().length === 0) return;
      try {
        const Context = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
        if (!Context) return;
        audioContext = audioContext ?? new Context();
        if (audioContext.state === 'suspended') void audioContext.resume();
        analyser = analyser ?? audioContext.createAnalyser();
        analyser.fftSize = 512;
        analyser.smoothingTimeConstant = 0.55;
        samples = new Uint8Array(new ArrayBuffer(analyser.fftSize));
        source = audioContext.createMediaStreamSource(stream);
        source.connect(analyser);
      } catch {
        analyser = null;
      }
    };
    listen();
    const unsubscribe = subscribeVoice(listen);
    const loudness = (time: number, speaking: boolean): number => {
      if (analyser && samples && listened) {
        analyser.getByteTimeDomainData(samples);
        let sum = 0;
        for (let i = 0; i < samples.length; i += 1) {
          const v = (samples[i] - 128) / 128;
          sum += v * v;
        }
        return Math.min(1, Math.sqrt(sum / samples.length) * 4.5);
      }
      // No analysable stream (the browser blocked it): a speech-like rhythm while JAI speaks.
      return speaking ? 0.35 + 0.3 * Math.abs(Math.sin(time * 7.3) * Math.sin(time * 2.9 + 1.1)) : 0;
    };

    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    const clock = new THREE.Clock();
    let audio = 0;
    let spin = 0;
    let time = 0;

    const place = (delta: number, now: number) => {
      const target = FIELD_LOOKS[stateRef.current];
      const ease = reducedMotion ? 1 : Math.min(delta * 1.8, 1);
      (Object.keys(look) as Array<keyof FieldLook>).forEach((key) => {
        if (key === 'color') return;
        look[key] += (target[key] - look[key]) * ease;
      });
      color.lerp(new THREE.Color(target.color), reducedMotion ? 1 : Math.min(delta * 2.5, 1));
      const level = reducedMotion ? 0 : loudness(time, stateRef.current === 'speaking');
      audio += (level - audio) * Math.min(delta * (level > audio ? 6 : 2), 1);
      const since = (now - changedRef.current) / 1000;
      // Completed: one bright wave outward, then calm. Failed: a short tremor that fades.
      const flash = stateRef.current === 'completed' ? Math.max(0, 1 - since / 1.6) : 0;
      const tremor = look.shake * Math.max(0, 1 - since / 2.5);
      const breathe = look.pulse ? 1 + 0.03 * Math.sin(time * look.pulse * 2) : 1;
      const radius = (look.radius + audio * 0.22 + flash * 0.18) * breathe;
      for (let i = 0; i < count; i += 1) {
        const p = network.phases[i];
        const wander = look.turbulence * (1 + audio * 1.5);
        for (let axis = 0; axis < 3; axis += 1) {
          const k = i * 3 + axis;
          const home = network.homes[k] + (network.banded[k] - network.homes[k]) * look.order;
          const drift = reducedMotion ? 0 : Math.sin(time * (0.6 + axis * 0.17) + p * (axis + 1)) * wander;
          const shake = tremor ? Math.sin(time * 41 + p * 13 + axis) * 0.02 * tremor : 0;
          nodePositions[k] = home * radius + drift + shake;
        }
      }
      for (let e = 0; e < edgeCount; e += 1) {
        const a = network.edges[e * 2] * 3;
        const b = network.edges[e * 2 + 1] * 3;
        linkPositions.set(nodePositions.subarray(a, a + 3), e * 6);
        linkPositions.set(nodePositions.subarray(b, b + 3), e * 6 + 3);
      }
      const travelling = Math.round(SIGNALS * Math.min(1, look.signals + audio * 0.3));
      for (let s = 0; s < SIGNALS; s += 1) {
        if (s >= travelling || edgeCount === 0) {
          signalPositions[s * 3] = signalPositions[s * 3 + 1] = signalPositions[s * 3 + 2] = 9999; // off-screen, resting
          continue;
        }
        if (!reducedMotion) signalProgress[s] += delta * look.signalSpeed * (1 + audio);
        while (signalProgress[s] >= 1) {
          signalProgress[s] -= 1;
          const edge = signalEdge[s];
          const arrived = network.edges[edge * 2 + (signalForward[s] ? 1 : 0)];
          const next = network.neighbours[arrived];
          let choice = next[Math.floor(random() * next.length)] ?? edge;
          if (look.inward > 0.5) { // waiting on Richard: signals make their way to the centre and wait there
            let best = Infinity;
            for (const candidate of next) {
              const other = network.edges[candidate * 2] === arrived ? network.edges[candidate * 2 + 1] : network.edges[candidate * 2];
              const d = network.homes[other * 3] ** 2 + network.homes[other * 3 + 1] ** 2 + network.homes[other * 3 + 2] ** 2;
              if (d < best) { best = d; choice = candidate; }
            }
          }
          signalEdge[s] = choice;
          signalForward[s] = network.edges[choice * 2] === arrived ? 1 : 0;
        }
        const edge = signalEdge[s];
        const from = network.edges[edge * 2 + (signalForward[s] ? 0 : 1)] * 3;
        const to = network.edges[edge * 2 + (signalForward[s] ? 1 : 0)] * 3;
        const t = signalProgress[s];
        for (let axis = 0; axis < 3; axis += 1) {
          signalPositions[s * 3 + axis] = nodePositions[from + axis] + (nodePositions[to + axis] - nodePositions[from + axis]) * t;
        }
      }
      nodeGeometry.attributes.position.needsUpdate = true;
      linkGeometry.attributes.position.needsUpdate = true;
      signalGeometry.attributes.position.needsUpdate = true;
      nodeMaterial.color.copy(color);
      nodeMaterial.opacity = Math.min(1, 0.75 + audio * 0.25 + flash * 0.25);
      nodeMaterial.size = 0.026 + audio * 0.012 + flash * 0.02;
      linkMaterial.color.copy(color);
      linkMaterial.opacity = Math.min(0.6, look.links * 0.22 + audio * 0.15 + flash * 0.2) * (1 - tremor * 0.4 * Math.abs(Math.sin(time * 23)));
      signalMaterial.color.copy(color).lerp(new THREE.Color(0xffffff), 0.65);
      group.rotation.y = spin;
      group.rotation.x = Math.sin(spin * 0.4) * 0.18;
    };

    let frame = 0;
    let running = true;
    const draw = () => {
      place(0, performance.now());
      renderer.render(scene, camera);
    };
    const animate = () => {
      if (!running) return;
      frame = window.requestAnimationFrame(animate);
      const delta = Math.min(clock.getDelta(), 0.1);
      time += delta;
      spin += delta * (look.spin / 60) * Math.PI * 2 * (1 + audio * 0.4);
      place(delta, performance.now());
      renderer.render(scene, camera);
    };
    // Reduced motion: one still frame, redrawn only when the state or size changes.
    redrawRef.current = reducedMotion ? draw : null;
    const visibility = () => {
      if (reducedMotion) return;
      if (document.visibilityState === 'hidden') {
        running = false;
        window.cancelAnimationFrame(frame);
      } else if (!running) {
        running = true;
        clock.getDelta();
        animate();
      }
    };
    document.addEventListener('visibilitychange', visibility);
    if (reducedMotion) draw();
    else animate();

    return () => {
      running = false;
      redrawRef.current = null;
      window.cancelAnimationFrame(frame);
      document.removeEventListener('visibilitychange', visibility);
      resizeObserver?.disconnect();
      unsubscribe();
      source?.disconnect();
      void audioContext?.close();
      [nodeGeometry, linkGeometry, signalGeometry].forEach((geometry) => geometry.dispose());
      [nodeMaterial, linkMaterial, signalMaterial].forEach((material) => material.dispose());
      texture.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return (
    <div ref={mountRef} className="core-canvas" role="img" data-state={state}
      aria-label={`Intelligence field: a network of linked nodes with signals moving through it as JAI works. Current state: ${state}.`} />
  );
}
