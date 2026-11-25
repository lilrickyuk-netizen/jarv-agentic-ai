import { pollDelay } from '@/lib/missions';

describe('following a mission', () => {
  it('asks every 1.2 seconds at first and every 10 seconds after ten minutes, so long missions are followed to their end', () => {
    expect(pollDelay(0)).toBe(1200);
    expect(pollDelay(9 * 60 * 1000)).toBe(1200);
    expect(pollDelay(11 * 60 * 1000)).toBe(10000);
    expect(pollDelay(3 * 60 * 60 * 1000)).toBe(10000);
  });
});

describe('the card names the model the mission ran on (25 November)', () => {
  it('shows the reported model, each role when they differ, and nothing invented before a run reports', () => {
    const { ranOnLabel } = jest.requireActual('@/lib/missions');
    expect(ranOnLabel({ provider: 'claude', model: 'claude-sonnet-5-5' })).toBe('claude/claude-sonnet-5-5');
    expect(ranOnLabel({ provider: 'claude', model: 'claude-sonnet-5-5',
      models_by_role: { 'Product Designer': 'claude-sonnet-5-5', Verifier: 'claude-haiku-5-5' } }))
      .toBe('Product Designer: claude-sonnet-5-5 · Verifier: claude-haiku-5-5');
    expect(ranOnLabel({ provider: null, model: null })).toBe('model not reported yet');
  });
});
