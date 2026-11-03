'use client';

import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { getVoiceStream, subscribeVoice } from '@/lib/voice-signal';

type CoreState = 'idle' | 'listening' | 'thinking' | 'planning' | 'executing' | 'speaking' | 'approval' | 'completed' | 'failed' | 'recovery';

// Blue in every normal state; only waiting on Richard (amber) and a failure (red) change it, as warnings.
const stateColors: Record<CoreState, number> = {
  idle: 0x2f7bff,
  listening: 0x3b8cff,
  thinking: 0x2a6cf0,
  planning: 0x3a7dff,
  executing: 0x3d8bff,
  speaking: 0x4a9bff,
  approval: 0xfbbf24,
  completed: 0x3b82f6,
  failed: 0xfb7185,
  recovery: 0x2f7bff,
};

const ACTIVE: CoreState[] = ['listening', 'thinking', 'planning', 'executing', 'speaking'];

/** How big the ball is in each state: it gathers small when thinking or waiting, opens up when working and speaking. */
const stateRadius: Record<CoreState, number> = {
  idle: 0.95, listening: 1.1, thinking: 0.7, planning: 0.85, executing: 1.3, speaking: 1.55,
  approval: 0.75, completed: 1.15, failed: 0.8, recovery: 0.9,
};

/** The swarm's size: thousands of lights moving as one. */
export const SWARM_LIGHTS = 90000;

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
 * Every light is moved on the graphics card, and every one follows the same rules, so the swarm moves as one
 * coordinated body: it gathers into a small ball or opens into a big one together (uRadius, set from JAI's state
 * and voice), turns as one with the inner lights wheeling a little faster than the outer, and carries rings of light
 * and colour that travel outward through it in step. JAI's voice (uAudio) swells the ball and sends faster rings
 * through it with every word.
 */
const SWARM_VERTEX = `
  attribute vec3 aHome;
  attribute float aSize;
  attribute float aPhase;
  uniform float uTime;
  uniform float uPixelRatio;
  uniform float uPulse;
  uniform float uAudio;
  uniform float uRadius;
  // Phases advanced smoothly on the CPU (speed changes never make the lights jump).
  uniform float uSpin;
  uniform float uRing;
  uniform float uBeat;
  uniform float uHue;
  uniform float uTalk;
  uniform vec3 uCentre;
  uniform vec3 uColor;
  uniform float uSpectrum;
  varying float vAlpha;
  varying vec3 vColor;

  // Blues only: deep blue through electric blue to pale blue.
  vec3 spectrum(float t) {
    return mix(vec3(0.10, 0.30, 1.00), vec3(0.55, 0.80, 1.00), 0.5 + 0.5 * cos(6.28318 * t));
  }

  // While JAI talks: greens, from deep emerald to bright lime, flowing through the swarm.
  vec3 talking(float t) {
    return mix(vec3(0.05, 0.72, 0.32), vec3(0.55, 1.00, 0.45), 0.5 + 0.5 * cos(6.28318 * t));
  }

  mat3 turn(vec3 axis, float angle) {
    axis = normalize(axis);
    float s = sin(angle), c = cos(angle), o = 1.0 - c;
    return mat3(o * axis.x * axis.x + c, o * axis.x * axis.y - axis.z * s, o * axis.z * axis.x + axis.y * s,
                o * axis.x * axis.y + axis.z * s, o * axis.y * axis.y + c, o * axis.y * axis.z - axis.x * s,
                o * axis.z * axis.x - axis.y * s, o * axis.y * axis.z + axis.x * s, o * axis.z * axis.z + c);
  }

  void main() {
    float rad = length(aHome);
    // One turn for all, the inner lights a little faster: the body wheels like a single flock.
    vec3 axis = vec3(0.25 * sin(uTime * 0.13), 1.0, 0.25 * cos(uTime * 0.11));
    float angle = uSpin + (1.0 - rad) * 0.9 * sin(uTime * 0.25);
    vec3 p = turn(axis, angle) * aHome;

    // Rings travelling outward through the body, in step; faster and deeper while JAI speaks.
    float ring = sin(rad * 9.0 - uRing);
    p *= uRadius * (1.0 + ring * (0.035 + uAudio * 0.07));
    p += uCentre;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);

    // Brightness pulses with the same rings and one shared heartbeat; a light shimmer keeps it alive.
    float glowRing = 0.5 + 0.5 * ring;
    // Every light stays on: the rings and heartbeat only lift them brighter still.
    float heartbeat = 0.9 + 0.1 * pow(0.5 + 0.5 * sin(uBeat), 3.0);
    float shimmer = 0.94 + 0.06 * sin(uTime * 3.0 + aPhase);
    vAlpha = (0.85 + glowRing * (0.35 + uAudio * 0.6)) * heartbeat * shimmer * (1.0 + uPulse * 0.15);

    // Colour rings move outward with the light.
    float hue = rad * 0.6 - uHue + glowRing * 0.1;
    vec3 calm = mix(uColor, spectrum(hue), clamp(uSpectrum + uAudio * 0.6, 0.0, 1.0));
    vColor = mix(calm, talking(hue * 1.5 + rad * 0.4), uTalk);

    gl_PointSize = aSize * uPixelRatio * (1.1 + glowRing * 0.45 + uAudio * 0.8) * (16.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;

const SWARM_FRAGMENT = `
  uniform sampler2D uMap;
  uniform float uWhite;
  uniform float uGain;
  varying float vAlpha;
  varying vec3 vColor;
  void main() {
    float a = pow(texture2D(uMap, gl_PointCoord).a, 0.8);
    float light = a * vAlpha * uGain;
    gl_FragColor = vec4(mix(vColor, vec3(1.0), uWhite) * light, min(1.0, a * vAlpha));
  }
`;

/** Homes for the lights, filling a ball of radius 1, a little denser towards the middle. */
function swarmGeometry(count: number) {
  const homes = new Float32Array(count * 3);
  const sizes = new Float32Array(count);
  const phases = new Float32Array(count);
  for (let i = 0; i < count; i += 1) {
    const u = Math.random() * 2 - 1;
    const angle = Math.random() * Math.PI * 2;
    const ring = Math.sqrt(1 - u * u);
    const distance = Math.pow(Math.random(), 0.45);
    homes[i * 3] = Math.cos(angle) * ring * distance;
    homes[i * 3 + 1] = u * distance;
    homes[i * 3 + 2] = Math.sin(angle) * ring * distance;
    sizes[i] = 0.55 + Math.random() * 0.6 + (Math.random() < 0.015 ? 1.6 : 0);
    phases[i] = Math.random() * Math.PI * 2;
  }
  const geometry = new THREE.BufferGeometry();
  // Positions are computed on the graphics card from aHome; three.js still needs a position attribute.
  geometry.setAttribute('position', new THREE.BufferAttribute(homes, 3));
  geometry.setAttribute('aHome', new THREE.BufferAttribute(homes, 3));
  geometry.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1));
  geometry.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1));
  geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 4);
  return geometry;
}

function swarmMaterial(map: THREE.Texture, color: THREE.Color, options: { white: number; spectrum: number }) {
  return new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uPixelRatio: { value: 1 },
      uPulse: { value: 0 },
      uAudio: { value: 0 },
      uRadius: { value: 1 },
      uSpin: { value: 0 },
      uRing: { value: 0 },
      uBeat: { value: 0 },
      uHue: { value: 0 },
      uTalk: { value: 0 },
      uCentre: { value: new THREE.Vector3() },
      uColor: { value: color },
      uSpectrum: { value: options.spectrum },
      uMap: { value: map },
      uWhite: { value: options.white },
      uGain: { value: 1.6 },
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

    const bodyMaterial = swarmMaterial(glow, accent, { white: 0.18, spectrum: 0.5 });
    const body = new THREE.Points(swarmGeometry(SWARM_LIGHTS), bodyMaterial);
    scene.add(body);
    const materials = [bodyMaterial];
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

    // JAI's voice: an analyser on the live voice stream gives the loudness the swarm moves with.
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
      // No analysable stream (the browser blocked it): a speech-like rhythm while JAI speaks.
      return speaking ? 0.35 + 0.3 * Math.abs(Math.sin(time * 7.3) * Math.sin(time * 2.9 + 1.1)) : 0;
    };

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const clock = new THREE.Clock();
    const centre = new THREE.Vector3();
    let audioLevel = 0;
    let radius = stateRadius[stateRef.current];
    let pulse = 0;
    let flowTime = 0;
    let spin = 0;
    let ringPhase = 0;
    let beatPhase = 0;
    let huePhase = 0;
    let talk = 0;
    let frame = 0;
    const animate = () => {
      frame = window.requestAnimationFrame(animate);
      const current = stateRef.current;
      const active = ACTIVE.includes(current);
      const delta = Math.min(clock.getDelta(), 0.1);
      const time = reducedMotion ? 0 : clock.elapsedTime;
      accent.lerp(new THREE.Color(stateColors[current]), Math.min(delta * 2, 1));

      const level = reducedMotion ? 0 : loudness(clock.elapsedTime, current === 'speaking');
      // Follow the voice smoothly: rise over about a third of a second, settle over about a second.
      audioLevel += (level - audioLevel) * Math.min(delta * (level > audioLevel ? 3.5 : 1.2), 1);
      const beat = current === 'approval' ? 0.5 + 0.5 * Math.sin(time * 1.4) : active ? 0.5 + 0.5 * Math.sin(time * 3.2) : 0;
      pulse += ((reducedMotion ? 0 : beat) - pulse) * Math.min(delta * 6, 1);
      // The swarm's own clock runs faster while JAI works and faster again while it speaks.
      flowTime += reducedMotion ? 0 : delta * ((active ? 0.9 : 0.6) + audioLevel * 0.35);

      if (!reducedMotion) {
        // Each motion advances at its own pace; the voice raises the pace gently, never in a jump.
        spin += delta * (0.3 + audioLevel * 0.15);
        ringPhase += delta * (2.0 + audioLevel * 1.6);
        beatPhase += delta * (1.2 + audioLevel * 0.8);
        huePhase += delta * (0.05 + audioLevel * 0.06 + talk * 0.12);
      }
      // Colour changes while JAI talks: it fades into the talking colours over about a second and back to blue after.
      const talkTarget = !reducedMotion && current === 'speaking' ? 0.65 + audioLevel * 0.35 : 0;
      talk += (talkTarget - talk) * Math.min(delta * 1.4, 1);
      // The whole body travels slowly around the field.
      centre.set(Math.sin(flowTime * 0.12) * 0.25, Math.sin(flowTime * 0.1 + 1.3) * 0.12, 0);
      // The whole swarm gathers or opens together, smoothly, and swells with each word JAI says.
      const targetRadius = stateRadius[current] + audioLevel * 0.4 + pulse * 0.05;
      radius += (targetRadius - radius) * Math.min(delta * (targetRadius > radius ? 1.5 : 0.9), 1);
      materials.forEach((material) => {
        material.uniforms.uTime.value = flowTime;
        material.uniforms.uPulse.value = pulse;
        material.uniforms.uAudio.value = audioLevel;
        material.uniforms.uRadius.value = radius;
        material.uniforms.uSpin.value = spin;
        material.uniforms.uRing.value = ringPhase;
        material.uniforms.uBeat.value = beatPhase;
        material.uniforms.uHue.value = huePhase;
        material.uniforms.uTalk.value = talk;
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
      materials.forEach((material) => material.dispose());
      glow.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div ref={mountRef} className="core-canvas" role="img" aria-label={`Intelligence field: a swarm of 90,000 lights moving together with JAI. Current state: ${state}.`} data-state={state} />;
}
