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
export const SWARM_LIGHTS = 18000;
export const DRIFT_LIGHTS = 5000;

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
 * Every light is moved on the graphics card. Each has a home in a soft cloud; the whole cloud turns, stretches,
 * breathes and travels around the field as one body, while each light flows along a shared current, so neighbours
 * move together like a murmuration. JARV's voice (uAudio) makes the swarm surge outward, swirl, pulse brighter and
 * run through its colours faster.
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
  uniform vec3 uCentre;
  uniform vec3 uColor;
  uniform float uSpectrum;
  varying float vAlpha;
  varying vec3 vColor;

  vec3 spectrum(float t) {
    return vec3(0.45, 0.62, 0.85) + vec3(0.40, 0.33, 0.20) * cos(6.28318 * (t + vec3(0.55, 0.40, 0.30)));
  }

  mat3 turn(vec3 axis, float angle) {
    axis = normalize(axis);
    float s = sin(angle), c = cos(angle), o = 1.0 - c;
    return mat3(o * axis.x * axis.x + c, o * axis.x * axis.y - axis.z * s, o * axis.z * axis.x + axis.y * s,
                o * axis.x * axis.y + axis.z * s, o * axis.y * axis.y + c, o * axis.y * axis.z - axis.x * s,
                o * axis.z * axis.x - axis.y * s, o * axis.y * axis.z + axis.x * s, o * axis.z * axis.z + c);
  }

  void main() {
    float t = uTime * uFlow;
    vec3 p = aHome * uSpread;

    // The body changes shape as it moves: stretching, folding and breathing as one.
    p.x *= 1.0 + 0.38 * sin(t * 0.31);
    p.y *= 1.0 + 0.30 * sin(t * 0.27 + 1.7);
    p.z *= 1.0 + 0.25 * sin(t * 0.23 + 3.1);
    p = turn(vec3(sin(t * 0.11), 1.0, cos(t * 0.13)), t * 0.35) * p;

    // A shared current: neighbouring lights get almost the same push, so they flow together.
    vec3 current = vec3(
      sin(p.y * 1.7 + t * 0.9) + sin(p.z * 2.3 - t * 0.6),
      sin(p.z * 1.9 + t * 0.8) + sin(p.x * 2.1 + t * 0.7),
      sin(p.x * 1.5 - t * 0.7) + sin(p.y * 2.5 + t * 0.5));
    p += current * (0.16 + uAudio * 0.28);

    // JARV's voice: the swarm surges out with each word and swirls.
    float surge = uAudio * (0.18 + 0.22 * sin(uTime * 9.0 + aPhase * 2.0));
    p *= 1.0 + surge;
    p = turn(vec3(0.0, 1.0, 0.0), uAudio * 0.5 * sin(uTime * 2.0 + length(p) * 2.2)) * p;

    p += uCentre;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);

    float wave = 0.5 + 0.5 * sin(dot(aHome, vec3(0.6, 0.8, 0.2)) * 6.0 - uTime * (1.4 + uAudio * 7.0));
    float twinkle = 0.5 + 0.5 * sin(uTime * (1.8 + uAudio * 6.0) + aPhase);
    float core = 1.0 - smoothstep(0.0, 1.0, length(aHome));
    vAlpha = min(1.0, twinkle * (0.35 + core * 0.45 + wave * (0.45 + uAudio * 1.3)));

    float hue = aPhase * 0.159 + uTime * (0.04 + uAudio * 0.35) + aHome.y * 0.25 + wave * 0.3;
    vColor = mix(uColor, spectrum(hue), clamp(uSpectrum + uAudio * 0.6, 0.0, 1.0));

    gl_PointSize = aSize * uPixelRatio * (1.0 + uPulse * 0.3 + uAudio * 0.9 + wave * uAudio * 0.7) * (16.0 / -mv.z);
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
    sizes[i] = 0.5 + Math.random() * 1.1 + (Math.random() < 0.03 ? 2.2 : 0);
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

function swarmMaterial(map: THREE.Texture, color: THREE.Color, options: { white: number; spectrum: number; flow: number }) {
  return new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uPixelRatio: { value: 1 },
      uPulse: { value: 0 },
      uAudio: { value: 0 },
      uSpread: { value: 1 },
      uFlow: { value: options.flow },
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

    // A faint light the swarm carries with it, so it reads as one being, not scattered dots.
    const haloMaterial = new THREE.SpriteMaterial({ map: glow, color: accent, transparent: true, opacity: 0.32, blending: THREE.AdditiveBlending, depthWrite: false });
    const halo = new THREE.Sprite(haloMaterial);
    halo.scale.setScalar(4.6);
    scene.add(halo);

    const bodyMaterial = swarmMaterial(glow, accent, { white: 0.25, spectrum: 0.45, flow: 1 });
    const body = new THREE.Points(swarmGeometry(SWARM_LIGHTS, 1.5), bodyMaterial);
    scene.add(body);
    // Lights at the edge that trail the body more loosely, a little slower.
    const driftMaterial = swarmMaterial(glow, accent, { white: 0.1, spectrum: 0.65, flow: 0.8 });
    const drift = new THREE.Points(swarmGeometry(DRIFT_LIGHTS, 2.4), driftMaterial);
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
      haloMaterial.color.copy(accent);

      const level = reducedMotion ? 0 : loudness(clock.elapsedTime, current === 'speaking');
      // Rise fast with the voice, fall back gently between words.
      audioLevel += (level - audioLevel) * Math.min(delta * (level > audioLevel ? 18 : 5), 1);
      const beat = current === 'approval' ? 0.5 + 0.5 * Math.sin(time * 1.4) : active ? 0.5 + 0.5 * Math.sin(time * 3.2) : 0;
      pulse += ((reducedMotion ? 0 : beat) - pulse) * Math.min(delta * 6, 1);
      // The swarm's own clock runs faster while JARV works and faster again while it speaks.
      flowTime += reducedMotion ? 0 : delta * ((active ? 1.3 : 0.8) + audioLevel * 1.8);

      // The whole body travels slowly around the field.
      centre.set(Math.sin(flowTime * 0.21) * 0.7, Math.sin(flowTime * 0.17 + 1.3) * 0.32, Math.sin(flowTime * 0.13) * 0.4);
      materials.forEach((material) => {
        material.uniforms.uTime.value = flowTime;
        material.uniforms.uPulse.value = pulse;
        material.uniforms.uAudio.value = audioLevel;
        material.uniforms.uSpread.value = 1 + pulse * 0.06;
        (material.uniforms.uCentre.value as THREE.Vector3).copy(centre);
      });
      halo.position.copy(centre);
      haloMaterial.opacity = Math.min(1, 0.3 + pulse * 0.12 + audioLevel * 0.4);
      halo.scale.setScalar(4.6 + pulse * 0.3 + audioLevel * 1.4);

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
      haloMaterial.dispose();
      glow.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div ref={mountRef} className="core-canvas" role="img" aria-label={`Intelligence field: a swarm of light that moves with JARV. Current state: ${state}.`} data-state={state} />;
}
