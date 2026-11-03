import { timeoutFor } from '@/lib/backend-timeout';

describe('timeoutFor', () => {
  it("gives Talk with JAI's tools time for the reasoning core to answer", () => {
    expect(timeoutFor('api/voice/live/tool')).toBe(90000);
    expect(timeoutFor('api/voicebox/generate/abc/status')).toBe(600000);
    expect(timeoutFor('api/tasks/stats')).toBe(30000);
  });
});
