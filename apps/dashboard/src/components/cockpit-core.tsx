'use client';

import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { getVoiceStream, subscribeVoice } from '@/lib/voice-signal';

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

/** The swarm's size: thousands of lights moving as one. */
export const SWARM_LIGHTS = 36000;
export const DRIFT_LIGHTS = 9000;

/** A soft round glow, drawn once, used by every light (additive blending makes overlaps brighter). */
function glowTexture(): THREE.CanvasTexture {
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext('2d');
  if (context) {
    const gradient = context.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    gradient.addColorStop(0, 'rgba(255,255,255,1)');
    gradient.addColorStop(0.2, 'rgba(255,255,255,0.8)');
    gradient.addColorStop(0.5, 'rgba(255,255,255,0.2)');
    gradient.addColorStop(1, 'rgba(255,255,255,0)');
    context.fillStyle = gradient;
    context.fillRect(0, 0, size, size);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/**
 * Every light is moved on the graphics card, like bees: each one loops fast and tight around one of five
 * gathering points, with its own speed and a constant buzz, and the gathering points themselves wheel around the
 * field, so the swarm keeps splitting, stretching and rejoining instead of holding one smooth outline. Some lights
 * roam between the groups. Every light flashes on its own rhythm and the whole swarm shares a heartbeat. JARV's
 * voice (uAudio) makes the lights buzz harder, flash brighter, spread out and run through their colours faster.
 */
const SWARM_VERTEX = `
  attribute vec3 aHome;
  attribute float aSize;
  attribute float aPhase;
  uniform float uTime;
  uniform float uPixelRatio;
  uniform float uPulse;
  uniform float uAudio;
  uniform float uSpread;
  uniform float uFlow;
  uniform float uRoam;
  uniform vec3 uCentre;
  uniform vec3 uColor;
  uniform float uSpectrum;
  varying float vAlpha;
  varying vec3 vColor;

  vec3 spectrum(float t) {
    return vec3(0.45, 0.62, 0.85) + vec3(0.40, 0.33, 0.20) * cos(6.28318 * (t + vec3(0.55, 0.40, 0.30)));
  }

  // Five gathering points wheeling around the field on their own paths.
  vec3 gathering(float k, float t) {
    float a = 0.31 + k * 0.07, b = 0.23 + k * 0.05, c = 0.27 + k * 0.04, o = k * 1.7;
    return vec3(sin(t * a + o) * 1.35, sin(t * b + o * 1.3) * 0.75, cos(t * c + o * 0.7) * 0.9);
  }

  void main() {
    float t = uTime * uFlow;
    float seed = fract(aPhase * 7.13);
    float k = floor(seed * 5.0);
    float k2 = mod(k + 1.0, 5.0);
    // Each bee mostly keeps to its group but drifts between two, so groups stretch towards each other and merge.
    float pull = 0.5 + 0.5 * sin(t * (0.2 + seed * 0.3) + aPhase);
    vec3 home = mix(gathering(k, t), gathering(k2, t), pull * uRoam);

    // A fast, tight loop around the gathering point: its own speeds, its own size.
    float r = (0.12 + length(aHome) * 0.75) * uSpread * (1.0 + uAudio * 0.6);
    vec3 freq = vec3(1.6, 2.1, 1.3) + fract(aHome * 13.7) * 2.6;
    vec3 loop = vec3(sin(t * freq.x + aPhase), sin(t * freq.y + aPhase * 1.7), cos(t * freq.z + aPhase * 0.6));
    vec3 p = home + loop * r * normalize(abs(aHome) + 0.35);

    // The buzz: a tiny, very fast jitter on every light, harder while JARV speaks.
    p += vec3(sin(uTime * 23.0 + aPhase * 5.0), sin(uTime * 19.0 + aPhase * 3.0), sin(uTime * 29.0 + aPhase * 7.0))
         * (0.012 + uAudio * 0.04);

    p += uCentre;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);

    // Flashing: each light on its own sharp rhythm, all of them on a shared heartbeat.
    float own = pow(0.5 + 0.5 * sin(uTime * (2.5 + seed * 5.0) + aPhase * 3.0), 3.0);
    float heartbeat = 0.6 + 0.4 * pow(0.5 + 0.5 * sin(uTime * (1.6 + uAudio * 5.0)), 4.0);
    vAlpha = min(1.0, (0.18 + own * (0.9 + uAudio * 1.2)) * heartbeat * (1.0 + uPulse * 0.3));

    float hue = aPhase * 0.159 + uTime * (0.05 + uAudio * 0.4) + k * 0.12 + own * 0.15;
    vColor = mix(uColor, spectrum(hue), clamp(uSpectrum + uAudio * 0.6, 0.0, 1.0));

    gl_PointSize = aSize * uPixelRatio * (0.8 + own * 0.9 + uAudio * 0.9) * (16.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;

const SWARM_FRAGMENT = `
  uniform sampler2D uMap;
  uniform float uWhite;
  varying float vAlpha;
  varying vec3 vColor;
  void main() {
    float a = texture2D(uMap, gl_PointCoord).a * vAlpha;
    gl_FragColor = vec4(mix(vColor, vec3(1.0), uWhite) * a, a);
  }
`;

/** Homes for the lights in a soft cloud, densest in the middle. */
function swarmGeometry(count: number, reach: number) {
  const homes = new Float32Array(count * 3);
  const sizes = new Float32Array(count);
  const phases = new Float32Array(count);
  for (let i = 0; i < count; i += 1) {
    const u = Math.random() * 2 - 1;
    const angle = Math.random() * Math.PI * 2;
    const ring = Math.sqrt(1 - u * u);
    const distance = reach * Math.pow(Math.random(), 0.55);
    homes[i * 3] = Math.cos(angle) * ring * distance;
    homes[i * 3 + 1] = u * distance * 0.8;
    homes[i * 3 + 2] = Math.sin(angle) * ring * distance;
    sizes[i] = 0.35 + Math.random() * 0.8 + (Math.random() < 0.02 ? 1.8 : 0);
    phases[i] = Math.random() * Math.PI * 2;
  }
  const geometry = new THREE.BufferGeometry();
  // Positions are computed on the graphics card from aHome; three.js still needs a position attribute.
  geometry.setAttribute('position', new THREE.BufferAttribute(homes, 3));
  geometry.setAttribute('aHome', new THREE.BufferAttribute(homes, 3));
  geometry.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1));
  geometry.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1));
  geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(), reach * 4);
  return geometry;
}

function swarmMaterial(map: THREE.Texture, color: THREE.Color,
  options: { white: number; spectrum: number; flow: number; roam: number }) {
  return new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uPixelRatio: { value: 1 },
      uPulse: { value: 0 },
      uAudio: { value: 0 },
      uSpread: { value: 1 },
      uFlow: { value: options.flow },
      uRoam: { value: options.roam },
      uCentre: { value: new THREE.Vector3() },
      uColor: { value: color },
      uSpectrum: { value: options.spectrum },
      uMap: { value: map },
      uWhite: { value: options.white },
    },
    vertexShader: SWARM_VERTEX,
    fragmentShader: SWARM_FRAGMENT,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
}

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
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: false, powerPreference: 'high-performance' });
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
    const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
    camera.position.set(0, 0, 6.2);

    const glow = glowTexture();
    const accent = new THREE.Color(stateColors[stateRef.current]);

    const bodyMaterial = swarmMaterial(glow, accent, { white: 0.25, spectrum: 0.45, flow: 1, roam: 0.35 });
    const body = new THREE.Points(swarmGeometry(SWARM_LIGHTS, 1), bodyMaterial);
    scene.add(body);
    // Roamers: lights that wander widely between the groups, so the swarm is never one closed shape.
    const driftMaterial = swarmMaterial(glow, accent, { white: 0.1, spectrum: 0.65, flow: 0.8, roam: 1 });
    const drift = new THREE.Points(swarmGeometry(DRIFT_LIGHTS, 1.6), driftMaterial);
    scene.add(drift);
    const materials = [bodyMaterial, driftMaterial];
    materials.forEach((material) => { material.uniforms.uPixelRatio.value = pixelRatio; });

    const resize = () => {
      const width = Math.max(mount.clientWidth, 1);
      const height = Math.max(mount.clientHeight, 1);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.position.z = width < height ? 6.2 * (height / width) * 0.9 : 6.2;
      camera.updateProjectionMatrix();
    };
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(mount);
    resize();

    // JARV's voice: an analyser on the live voice stream gives the loudness the swarm moves with.
    let audioContext: AudioContext | null = null;
    let analyser: AnalyserNode | null = null;
    let source: MediaStreamAudioSourceNode | null = null;
    let samples: Uint8Array<ArrayBuffer> | null = null;
    let listenedStream: MediaStream | null = null;
    const listen = () => {
      const stream = getVoiceStream();
      if (stream === listenedStream) return;
      listenedStream = stream;
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
        analyser.smoothingTimeConstant = 0.6;
        samples = new Uint8Array(new ArrayBuffer(analyser.fftSize));
        // Analysed only, never played twice: the conversation's own audio element plays the voice.
        source = audioContext.createMediaStreamSource(stream);
        source.connect(analyser);
      } catch {
        analyser = null;
      }
    };
    listen();
    const unsubscribe = subscribeVoice(listen);
    const loudness = (time: number, speaking: boolean): number => {
      if (analyser && samples && listenedStream) {
        analyser.getByteTimeDomainData(samples);
        let sum = 0;
        for (let i = 0; i < samples.length; i += 1) {
          const v = (samples[i] - 128) / 128;
          sum += v * v;
        }
        return Math.min(1, Math.sqrt(sum / samples.length) * 4.5);
      }
      // No analysable stream (the browser blocked it): a speech-like rhythm while JARV speaks.
      return speaking ? 0.35 + 0.3 * Math.abs(Math.sin(time * 7.3) * Math.sin(time * 2.9 + 1.1)) : 0;
    };

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const clock = new THREE.Clock();
    const centre = new THREE.Vector3();
    let audioLevel = 0;
    let pulse = 0;
    let flowTime = 0;
    let frame = 0;
    const animate = () => {
      frame = window.requestAnimationFrame(animate);
      const current = stateRef.current;
      const active = ACTIVE.includes(current);
      const delta = Math.min(clock.getDelta(), 0.1);
      const time = reducedMotion ? 0 : clock.elapsedTime;
      accent.lerp(new THREE.Color(stateColors[current]), Math.min(delta * 2, 1));

      const level = reducedMotion ? 0 : loudness(clock.elapsedTime, current === 'speaking');
      // Rise fast with the voice, fall back gently between words.
      audioLevel += (level - audioLevel) * Math.min(delta * (level > audioLevel ? 18 : 5), 1);
      const beat = current === 'approval' ? 0.5 + 0.5 * Math.sin(time * 1.4) : active ? 0.5 + 0.5 * Math.sin(time * 3.2) : 0;
      pulse += ((reducedMotion ? 0 : beat) - pulse) * Math.min(delta * 6, 1);
      // The swarm's own clock runs faster while JARV works and faster again while it speaks.
      flowTime += reducedMotion ? 0 : delta * ((active ? 1.3 : 0.8) + audioLevel * 1.8);

      // The whole body travels slowly around the field.
      centre.set(Math.sin(flowTime * 0.12) * 0.35, Math.sin(flowTime * 0.1 + 1.3) * 0.18, 0);
      materials.forEach((material) => {
        material.uniforms.uTime.value = flowTime;
        material.uniforms.uPulse.value = pulse;
        material.uniforms.uAudio.value = audioLevel;
        material.uniforms.uSpread.value = 1 + pulse * 0.08;
        (material.uniforms.uCentre.value as THREE.Vector3).copy(centre);
      });

      renderer.render(scene, camera);
    };
    animate();

    return () => {
      window.cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      unsubscribe();
      source?.disconnect();
      void audioContext?.close();
      body.geometry.dispose();
      drift.geometry.dispose();
      materials.forEach((material) => material.dispose());
      glow.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div ref={mountRef} className="core-canvas" role="img" aria-label={`Intelligence field: a swarm of tens of thousands of lights moving with JARV. Current state: ${state}.`} data-state={state} />;
}
