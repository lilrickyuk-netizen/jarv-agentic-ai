import { pollDelay } from '@/lib/missions';

describe('following a mission', () => {
  it('asks every 1.2 seconds at first and every 10 seconds after ten minutes, so long missions are followed to their end', () => {
    expect(pollDelay(0)).toBe(1200);
    expect(pollDelay(9 * 60 * 1000)).toBe(1200);
    expect(pollDelay(11 * 60 * 1000)).toBe(10000);
    expect(pollDelay(3 * 60 * 60 * 1000)).toBe(10000);
  });
});
