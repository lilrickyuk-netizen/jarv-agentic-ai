/**
 * 18 November: every page sits on a black starry sky, with shooting stars at new places every 30 seconds, behind
 * everything (the intelligence field included). The component is real; time is Jest's.
 */
import { act, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import fs from 'fs';
import path from 'path';
import { SHOOTING_EVERY_MS, StarrySky, volley } from '@/components/starry-sky';

describe('StarrySky', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it('sends shooting stars across the sky every 30 seconds, then clears them', () => {
    render(<StarrySky />);
    expect(screen.getByTestId('starry-sky')).toHaveAttribute('aria-hidden', 'true');
    expect(screen.queryAllByTestId('shooting-star')).toHaveLength(0);
    act(() => { jest.advanceTimersByTime(3000); });
    expect(screen.getAllByTestId('shooting-star').length).toBeGreaterThan(0);
    act(() => { jest.advanceTimersByTime(3000); });
    expect(screen.queryAllByTestId('shooting-star')).toHaveLength(0);
    act(() => { jest.advanceTimersByTime(SHOOTING_EVERY_MS - 5500); });  // just after the next volley, at 30 s
    expect(screen.getAllByTestId('shooting-star').length).toBeGreaterThan(0);
  });

  it('puts each volley somewhere new on the sky', () => {
    // A volley uses 8 random numbers (4 per star), so the stand-in for Math.random never repeats within 16.
    let i = 0;
    const next = () => ((i++ * 0.6180339887) % 1);
    const first = volley(0, next);
    const second = volley(2, next);
    expect(first.map((s) => [s.top, s.left])).not.toEqual(second.map((s) => [s.top, s.left]));
    for (const star of [...first, ...second]) {
      expect(star.top).toBeGreaterThanOrEqual(0);
      expect(star.top).toBeLessThanOrEqual(55);
      expect(star.left).toBeGreaterThanOrEqual(10);
      expect(star.left).toBeLessThanOrEqual(85);
    }
  });

  it('is on every page, behind everything, and the panels and buttons are glass', () => {
    const root = path.join(__dirname, '..', 'src', 'app');
    expect(fs.readFileSync(path.join(root, 'layout.tsx'), 'utf8')).toContain('<StarrySky />');
    const css = fs.readFileSync(path.join(root, 'globals.css'), 'utf8');
    expect(css).toMatch(/\.starry-sky \{ position: fixed; inset: 0; z-index: -1;/);
    expect(css).toContain('html body.jai-theme .cockpit-panel.core-panel');
    expect(css).toMatch(/backdrop-filter: blur\(9px\)/);  // frosted enough that stars behind read as behind
    expect(css).toContain('html body.jai-theme .ov-orb::before');  // the field is solid against the sky
    expect(css).toMatch(/border: 1px solid rgba\(var\(--neon\), \.9\) !important;/);
  });
});
