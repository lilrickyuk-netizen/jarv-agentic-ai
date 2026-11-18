'use client';

import { useEffect, useRef, useState } from 'react';

/** How often new shooting stars cross the sky, and how many each time. */
export const SHOOTING_EVERY_MS = 30_000;
const PER_VOLLEY = 2;
const FIRST_AFTER_MS = 2_500;
const SHOOTING_LIFE_MS = 1_800;

export interface ShootingStar {
  id: number;
  top: number;   // % of the viewport height where it starts
  left: number;  // % of the viewport width where it starts
  angle: number; // degrees below the horizontal it travels
  length: number; // px of its trail
}

/** A volley of shooting stars at new random places on the sky. */
export function volley(start: number, random: () => number = Math.random): ShootingStar[] {
  return Array.from({ length: PER_VOLLEY }, (_, i) => ({
    id: start + i,
    top: Math.round(random() * 55),
    left: Math.round(10 + random() * 75),
    angle: Math.round(18 + random() * 30),
    length: Math.round(140 + random() * 160),
  }));
}

function drawStars(canvas: HTMLCanvasElement) {
  const context = canvas.getContext('2d');
  if (!context) return;
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const width = window.innerWidth;
  const height = window.innerHeight;
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, width, height);
  const count = Math.round((width * height) / 2600);
  for (let i = 0; i < count; i += 1) {
    const size = Math.random() < 0.92 ? Math.random() * 0.9 + 0.25 : Math.random() * 1.1 + 1;
    context.globalAlpha = Math.random() * 0.65 + 0.25;
    context.fillStyle = Math.random() < 0.85 ? '#ffffff' : '#bfe6ff';
    context.beginPath();
    context.arc(Math.random() * width, Math.random() * height, size, 0, Math.PI * 2);
    context.fill();
  }
  context.globalAlpha = 1;
}

/**
 * The sky behind every page: black with stars, and shooting stars crossing it at new places every 30 seconds.
 * It sits behind everything, the intelligence field included, and never takes a click. With reduced motion on,
 * the stars stay and nothing moves.
 */
export function StarrySky() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [shooting, setShooting] = useState<ShootingStar[]>([]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas) drawStars(canvas);
    let resizeTimer = 0;
    const onResize = () => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => canvasRef.current && drawStars(canvasRef.current), 200);
    };
    window.addEventListener('resize', onResize);

    const still = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let next = 0;
    const timers: number[] = [];
    const launch = () => {
      const stars = volley(next);
      next += stars.length;
      setShooting((now) => [...now, ...stars]);
      timers.push(window.setTimeout(() => {
        setShooting((now) => now.filter((s) => !stars.some((t) => t.id === s.id)));
      }, SHOOTING_LIFE_MS + 400));
    };
    let every = 0;
    if (!still) {
      timers.push(window.setTimeout(launch, FIRST_AFTER_MS));
      every = window.setInterval(launch, SHOOTING_EVERY_MS);
    }
    return () => {
      window.removeEventListener('resize', onResize);
      window.clearTimeout(resizeTimer);
      window.clearInterval(every);
      timers.forEach((t) => window.clearTimeout(t));
    };
  }, []);

  return (
    <div className="starry-sky" aria-hidden="true" data-testid="starry-sky">
      <canvas ref={canvasRef} className="starry-sky-stars" />
      {shooting.map((star) => (
        <span
          key={star.id}
          className="shooting-star"
          data-testid="shooting-star"
          style={{
            top: `${star.top}%`,
            left: `${star.left}%`,
            width: `${star.length}px`,
            ['--angle' as string]: `${star.angle}deg`,
          }}
        />
      ))}
    </div>
  );
}
