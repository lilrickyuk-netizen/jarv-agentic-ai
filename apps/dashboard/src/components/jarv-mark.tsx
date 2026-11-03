'use client';

import { useId } from 'react';

// A small swarm of light around a bright core, held by one orbit: the intelligence field in miniature.
const SWARM: [number, number, number, number][] = [
  [14.84, 23.68, 0.5, 0.74], [12.39, 23.68, 0.49, 0.73], [22.82, 19.04, 0.51, 0.68], [19.93, 14.69, 0.54, 0.57],
  [11.93, 12.37, 0.73, 0.99], [23.05, 19.37, 1.05, 0.61], [21.8, 22.37, 1.02, 0.55], [12.83, 15.38, 0.9, 0.65],
  [13.36, 16.71, 0.59, 0.82], [14.35, 19.61, 0.67, 0.77], [12.45, 19.51, 0.94, 0.58], [8.53, 13.7, 0.82, 0.93],
  [17.19, 12.4, 0.53, 0.68], [18.52, 7.66, 0.56, 0.72], [24.8, 19.54, 0.85, 0.93], [14.21, 26.06, 0.94, 0.78],
  [8.15, 13.13, 1.11, 0.71], [15.08, 13.61, 0.49, 0.84],
];

/** JARV's mark: original artwork, drawn in code. The orbiting light turns slowly unless reduced motion is asked for. */
export function JarvMark({ size = 36, title = 'JARV' }: { size?: number; title?: string }) {
  const id = useId().replace(/:/g, '');
  return (
    <svg className="jarv-mark" width={size} height={size} viewBox="0 0 36 36" {...(title ? { role: 'img', 'aria-label': title } : { 'aria-hidden': true })}>
      <defs>
        <radialGradient id={`${id}-core`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="45%" stopColor="#7cc4ff" />
          <stop offset="100%" stopColor="#2f7bff" stopOpacity="0" />
        </radialGradient>
        <radialGradient id={`${id}-halo`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#2f7bff" stopOpacity="0.45" />
          <stop offset="100%" stopColor="#2f7bff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="18" cy="18" r="17" fill={`url(#${id}-halo)`} />
      <circle cx="18" cy="18" r="16" fill="none" stroke="#3b8cff" strokeWidth="0.9" strokeLinecap="round"
        strokeDasharray="0.1 2.6" opacity="0.85" />
      <g opacity="0.95">
        {SWARM.map(([x, y, r, o], i) => <circle key={i} cx={x} cy={y} r={r} fill={i % 3 === 0 ? '#cfe6ff' : '#5fa8ff'} opacity={o} />)}
      </g>
      <ellipse cx="18" cy="18" rx="14.5" ry="5.4" fill="none" stroke="#4a9bff" strokeWidth="0.8" opacity="0.8"
        transform="rotate(-24 18 18)" />
      <g className="jarv-mark-orbit">
        <circle cx="31.2" cy="12.2" r="1.35" fill="#e8f3ff" />
      </g>
      <circle cx="18" cy="18" r="5.2" fill={`url(#${id}-core)`} />
      <circle cx="18" cy="18" r="1.6" fill="#ffffff" />
    </svg>
  );
}
