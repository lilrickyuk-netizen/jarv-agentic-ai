'use client';

/**
 * The JARVIS orb: Ethan Rogers' particle visualisation from ethanplusai/jarvis (frontend/src/orb.ts), adapted for
 * JAI's Command Center: sized to its panel instead of the window, a transparent background, driven by JAI's own
 * ten states and the live audio of Jay's voice, with reduced-motion support and full cleanup.
 *
 * JAI is Richard's personal, non-commercial system, which this licence allows. The notice below must stay with
 * this file, and the component must not be used in anything sold or offered as a service without a commercial
 * licence from ethanplus.ai.
 *
 * ---------------------------------------------------------------------------------------------------------------
 * JARVIS Voice AI Assistant
 * Copyright (c) 2026 Ethan Rogers
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
 * documentation files (the "Software"), to use, copy, modify, and run the Software for personal, non-commercial
 * purposes, subject to the following conditions:
 * 1. PERSONAL USE: You may use, copy, modify, and run the Software for personal, educational, and non-commercial
 *    purposes without restriction.
 * 2. COMMERCIAL USE PROHIBITED WITHOUT LICENSE: You may NOT use the Software, or any derivative work based on the
 *    Software, for commercial purposes without obtaining a commercial license.
 * 3. ATTRIBUTION: All copies or substantial portions of the Software must include this license notice and the
 *    above copyright notice.
 * 4. COMMERCIAL LICENSING: https://ethanplus.ai
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.
 * ---------------------------------------------------------------------------------------------------------------
 */
import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { getVoiceStream, subscribeVoice } from '@/lib/voice-signal';
import type { FieldState } from '@/components/intelligence-field';

type OrbMode = 'idle' | 'listening' | 'thinking' | 'speaking' | 'compacting';

interface OrbTargets { radius: number; speed: number; bright: number; size: number; lines: number; electrons: number }

/** The orb's own moods (as in JARVIS), and the colour each of JAI's states shows them in. */
export const ORB_MODES: Record<OrbMode, OrbTargets> = {
  idle:       { radius: 28, speed: 0.2,  bright: 0.5,  size: 0.35, lines: 0.15, electrons: 0 },
  listening:  { radius: 22, speed: 0.3,  bright: 0.65, size: 0.4,  lines: 0.4,  electrons: 0 },
  thinking:   { radius: 16, speed: 0.5,  bright: 0.7,  size: 0.3,  lines: 1.0,  electrons: 0.015 },
  speaking:   { radius: 18, speed: 0.2,  bright: 0.7,  size: 0.4,  lines: 0.8,  electrons: 0 },
  compacting: { radius: 12, speed: 0.08, bright: 0.28, size: 0.28, lines: 0.0,  electrons: 0 },
};

/** JAI's ten states on the orb: working states think (with electrons), waiting on Richard holds amber, a failure
 * withdraws in red, a finished task glows green, recovery thinks again in blue. */
export const ORB_FOR_STATE: Record<FieldState, { mode: OrbMode; color: number }> = {
  idle: { mode: 'idle', color: 0x4ca8e8 },
  listening: { mode: 'listening', color: 0x4ca8e8 },
  thinking: { mode: 'thinking', color: 0x6ec4ff },
  planning: { mode: 'thinking', color: 0x6ec4ff },
  executing: { mode: 'thinking', color: 0x5ab8f0 },
  speaking: { mode: 'speaking', color: 0x5ab8f0 },
  approval: { mode: 'listening', color: 0xfbbf24 },
  completed: { mode: 'speaking', color: 0x34d399 },
  failed: { mode: 'compacting', color: 0xfb7185 },
  recovery: { mode: 'thinking', color: 0x4ca8e8 },
};

export function JarvisOrb({ state }: { state: FieldState }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef<FieldState>(state);
  const redrawRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    stateRef.current = state;
    redrawRef.current?.();
  }, [state]);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      mount.dataset.renderState = 'unavailable';
      return;
    }
    mount.dataset.renderState = 'ready';
    let destroyed = false;
    const N = 2000;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(0x000000, 0);
    renderer.domElement.setAttribute('aria-hidden', 'true');
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, 1, 1, 1000);
    camera.position.z = 80;

    // Particles
    const geo = new THREE.BufferGeometry();
    const pos = new Float32Array(N * 3);
    const vel = new Float32Array(N * 3);
    const phase = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      const r = Math.pow(Math.random(), 0.5) * 25;
      pos[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      pos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      pos[i * 3 + 2] = r * Math.cos(phi);
      phase[i] = Math.random() * 1000;
    }
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const mat = new THREE.PointsMaterial({ color: 0x4ca8e8, size: 0.4, transparent: true, opacity: 0.6,
      sizeAttenuation: true, blending: THREE.AdditiveBlending, depthWrite: false });
    const points = new THREE.Points(geo, mat);
    scene.add(points);

    // Connection lines
    const MAX_LINES = 8000;
    const linePos = new Float32Array(MAX_LINES * 6);
    const lineGeo = new THREE.BufferGeometry();
    lineGeo.setAttribute('position', new THREE.BufferAttribute(linePos, 3));
    lineGeo.setDrawRange(0, 0);
    const lineMat = new THREE.LineBasicMaterial({ color: 0x4ca8e8, transparent: true, opacity: 0.0,
      blending: THREE.AdditiveBlending, depthWrite: false });
    const lines = new THREE.LineSegments(lineGeo, lineMat);
    scene.add(lines);

    // Electrons: bright dots that travel along connections
    const MAX_ELECTRONS = 200;
    const electronGeo = new THREE.BufferGeometry();
    const electronPos = new Float32Array(MAX_ELECTRONS * 3);
    electronGeo.setAttribute('position', new THREE.BufferAttribute(electronPos, 3));
    electronGeo.setDrawRange(0, 0);
    const electronMat = new THREE.PointsMaterial({ color: 0xffffff, size: 0.8, transparent: true, opacity: 1.0,
      sizeAttenuation: true, blending: THREE.AdditiveBlending, depthWrite: false });
    const electrons = new THREE.Points(electronGeo, electronMat);
    scene.add(electrons);
    interface Electron { sx: number; sy: number; sz: number; ex: number; ey: number; ez: number; t: number; speed: number }
    const activeElectrons: Electron[] = [];
    let electronSpawnRate = 0;
    let lastElectronSpawn = 0;
    let activeConnections: { x1: number; y1: number; z1: number; x2: number; y2: number; z2: number }[] = [];

    // State
    let currentRadius = 25, currentSpeed = 0.3, currentBright = 0.6, currentSize = 0.4, lineAmount = 0;
    const lineDistance = 8;
    let spinX = 0, spinY = 0, spinZ = 0, transitionEnergy = 0;
    let lastState: FieldState = stateRef.current;
    let cloudZ = 0, cloudZVel = 0;

    // Audio: the live stream of Jay's voice, analysed only (the conversation itself plays it)
    let audioContext: AudioContext | null = null;
    let analyser: AnalyserNode | null = null;
    let source: MediaStreamAudioSourceNode | null = null;
    let freqData = new Uint8Array(new ArrayBuffer(64));
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
        freqData = new Uint8Array(new ArrayBuffer(analyser.frequencyBinCount));
        source = audioContext.createMediaStreamSource(stream);
        source.connect(analyser);
      } catch {
        analyser = null;
      }
    };
    listen();
    const unsubscribe = subscribeVoice(listen);
    let bass = 0, mid = 0;

    const resize = () => {
      const width = Math.max(mount.clientWidth, 1);
      const height = Math.max(mount.clientHeight, 1);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      // Keep the whole orb in view in a tall panel (a phone) as in a wide one.
      camera.position.z = width < height ? 80 * (height / width) * 0.85 : 80;
      camera.updateProjectionMatrix();
    };
    const resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
      resize();
      redrawRef.current?.();
    });
    resizeObserver?.observe(mount);
    resize();

    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    const clock = new THREE.Clock();
    const targetColor = new THREE.Color();

    const frame = (still: boolean) => {
      const t = clock.getElapsedTime();
      const jaiState = stateRef.current;
      const { mode, color } = ORB_FOR_STATE[jaiState];
      const target = ORB_MODES[mode];
      const ease = still ? 1 : 0.02;
      currentRadius += (target.radius - currentRadius) * ease;
      currentSpeed += (target.speed - currentSpeed) * ease;
      currentBright += (target.bright - currentBright) * ease;
      currentSize += (target.size - currentSize) * ease;
      lineAmount += (target.lines - lineAmount) * ease;
      electronSpawnRate += (target.electrons - electronSpawnRate) * ease;

      // The tumble on a change of state
      if (jaiState !== lastState) { transitionEnergy = still ? 0 : 1.0; lastState = jaiState; }
      transitionEnergy *= 0.985;
      if (transitionEnergy > 0.05) {
        spinX += transitionEnergy * 0.012 * Math.sin(t * 1.7);
        spinY += transitionEnergy * 0.015;
        spinZ += transitionEnergy * 0.008 * Math.cos(t * 1.3);
      }

      // Audio
      bass = 0; mid = 0;
      if (analyser && listened && !still) {
        analyser.getByteFrequencyData(freqData);
        let bSum = 0, mSum = 0;
        for (let i = 0; i < 8; i++) bSum += freqData[i];
        for (let i = 8; i < 24; i++) mSum += freqData[i];
        bass = bSum / (8 * 255); mid = mSum / (16 * 255);
      }

      // Depth breathing
      let zTarget = Math.sin(t * 0.12) * 8;
      if (mode === 'thinking') zTarget = Math.sin(t * 0.3) * 15 + Math.sin(t * 0.9) * 6;
      else if (mode === 'speaking') zTarget = Math.sin(t * 0.15) * 6 - bass * 10;
      else if (mode === 'compacting') zTarget = -20 + Math.sin(t * 0.08) * 3;
      if (still) { cloudZ = 0; cloudZVel = 0; } else {
        cloudZVel += (zTarget - cloudZ) * 0.008;
        cloudZVel *= 0.94;
        cloudZ += cloudZVel;
      }
      for (const object of [points, lines, electrons]) {
        object.rotation.set(spinX, spinY, spinZ);
        object.position.z = cloudZ;
      }

      // Particles
      const a = pos;
      if (!still) {
        for (let i = 0; i < N; i++) {
          const i3 = i * 3;
          const x = a[i3], y = a[i3 + 1], z = a[i3 + 2];
          const px = phase[i];
          vel[i3] += Math.sin(t * 0.05 + px) * 0.001 * currentSpeed;
          vel[i3 + 1] += Math.cos(t * 0.06 + px * 1.3) * 0.001 * currentSpeed;
          vel[i3 + 2] += Math.sin(t * 0.055 + px * 0.7) * 0.001 * currentSpeed;
          vel[i3] += Math.sin(t * 0.02 + px * 2.1 + y * 0.1) * 0.0008 * currentSpeed;
          vel[i3 + 1] += Math.cos(t * 0.025 + px * 1.7 + z * 0.1) * 0.0008 * currentSpeed;
          vel[i3 + 2] += Math.sin(t * 0.022 + px * 0.9 + x * 0.1) * 0.0008 * currentSpeed;
          const dist = Math.sqrt(x * x + y * y + z * z) || 0.01;
          const pull = Math.max(0, dist - currentRadius) * 0.002 + 0.0003;
          vel[i3] -= (x / dist) * pull;
          vel[i3 + 1] -= (y / dist) * pull;
          vel[i3 + 2] -= (z / dist) * pull;
          if (bass > 0.05) {
            vel[i3] += (x / dist) * bass * 0.02;
            vel[i3 + 1] += (y / dist) * bass * 0.02;
            vel[i3 + 2] += (z / dist) * bass * 0.02;
          }
          if (mode === 'speaking' && mid > 0.1) {
            const pulse = Math.sin(t * 8 + px);
            vel[i3] += (x / dist) * mid * 0.012 * pulse;
            vel[i3 + 1] += (y / dist) * mid * 0.012 * pulse;
          }
          vel[i3] *= 0.992; vel[i3 + 1] *= 0.992; vel[i3 + 2] *= 0.992;
          a[i3] += vel[i3]; a[i3 + 1] += vel[i3 + 1]; a[i3 + 2] += vel[i3 + 2];
        }
        geo.attributes.position.needsUpdate = true;
      }

      // Lines between nearby particles
      if (lineAmount > 0.01) {
        let lineCount = 0;
        const maxDist = lineDistance * (1 + bass * 0.5);
        const maxDistSq = maxDist * maxDist;
        const step = Math.max(1, Math.floor(N / 600));
        for (let i = 0; i < N && lineCount < MAX_LINES; i += step) {
          const i3 = i * 3;
          const x1 = a[i3], y1 = a[i3 + 1], z1 = a[i3 + 2];
          for (let j = i + step; j < N && lineCount < MAX_LINES; j += step) {
            const j3 = j * 3;
            const dx = a[j3] - x1, dy = a[j3 + 1] - y1, dz = a[j3 + 2] - z1;
            if (dx * dx + dy * dy + dz * dz < maxDistSq) {
              const idx = lineCount * 6;
              linePos[idx] = x1; linePos[idx + 1] = y1; linePos[idx + 2] = z1;
              linePos[idx + 3] = a[j3]; linePos[idx + 4] = a[j3 + 1]; linePos[idx + 5] = a[j3 + 2];
              lineCount++;
            }
          }
        }
        lineGeo.setDrawRange(0, lineCount * 2);
        lineGeo.attributes.position.needsUpdate = true;
        lineMat.opacity = lineAmount * 0.12;
        activeConnections = [];
        for (let c = 0; c < Math.min(lineCount, 500); c++) {
          const ci = c * 6;
          activeConnections.push({ x1: linePos[ci], y1: linePos[ci + 1], z1: linePos[ci + 2],
            x2: linePos[ci + 3], y2: linePos[ci + 4], z2: linePos[ci + 5] });
        }
      } else {
        lineGeo.setDrawRange(0, 0);
        activeConnections = [];
      }

      // Electrons while JAI thinks or works: one every second or so, three at most, two to four seconds each
      if (!still && activeConnections.length > 0 && electronSpawnRate > 0.005) {
        if (activeElectrons.length < 3 && (t - lastElectronSpawn) > 1.0) {
          const conn = activeConnections[Math.floor(Math.random() * activeConnections.length)];
          activeElectrons.push({ sx: conn.x1, sy: conn.y1, sz: conn.z1, ex: conn.x2, ey: conn.y2, ez: conn.z2,
            t: 0, speed: 0.003 + Math.random() * 0.003 });
          lastElectronSpawn = t;
        }
      }
      let alive = 0;
      for (let e = activeElectrons.length - 1; e >= 0; e--) {
        const el = activeElectrons[e];
        if (!still) el.t += el.speed;
        if (el.t >= 1) { activeElectrons.splice(e, 1); continue; }
        const ei = alive * 3;
        electronPos[ei] = el.sx + (el.ex - el.sx) * el.t;
        electronPos[ei + 1] = el.sy + (el.ey - el.sy) * el.t;
        electronPos[ei + 2] = el.sz + (el.ez - el.sz) * el.t;
        alive++;
      }
      electronGeo.setDrawRange(0, alive);
      electronGeo.attributes.position.needsUpdate = true;

      mat.opacity = currentBright + bass * 0.08;
      mat.size = currentSize + bass * 0.05;
      targetColor.setHex(color);
      mat.color.lerp(targetColor, still ? 1 : mode === 'compacting' ? 0.03 : 0.015);
      lineMat.color.lerp(targetColor, still ? 1 : mode === 'compacting' ? 0.03 : 0.015);

      if (!still) {
        camera.position.x = Math.sin(t * 0.02) * 5;
        camera.position.y = Math.cos(t * 0.03) * 3;
      }
      camera.lookAt(0, 0, cloudZ * 0.2);
      renderer.render(scene, camera);
    };

    let raf = 0;
    let running = true;
    const animate = () => {
      if (destroyed || !running) return;
      raf = window.requestAnimationFrame(animate);
      frame(false);
    };
    // Reduced motion: a still orb, redrawn only when JAI's state or the panel size changes.
    redrawRef.current = reducedMotion ? () => frame(true) : null;
    const visibility = () => {
      if (reducedMotion) return;
      if (document.visibilityState === 'hidden') {
        running = false;
        window.cancelAnimationFrame(raf);
      } else if (!running) {
        running = true;
        animate();
      }
    };
    document.addEventListener('visibilitychange', visibility);
    if (reducedMotion) frame(true);
    else animate();

    return () => {
      destroyed = true;
      redrawRef.current = null;
      window.cancelAnimationFrame(raf);
      document.removeEventListener('visibilitychange', visibility);
      resizeObserver?.disconnect();
      unsubscribe();
      source?.disconnect();
      void audioContext?.close();
      [geo, lineGeo, electronGeo].forEach((g) => g.dispose());
      [mat, lineMat, electronMat].forEach((m) => m.dispose());
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return (
    <div ref={mountRef} className="core-canvas" role="img" data-state={state}
      aria-label={`Intelligence field: the JARVIS orb of linked particles, moving with JAI. Current state: ${state}.`} />
  );
}
