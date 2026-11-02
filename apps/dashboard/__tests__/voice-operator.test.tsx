/**
 * Voice panel: one live conversation with JARV. The push-to-talk, hands-free and Voicebox controls are gone
 * (the self-hosted Voicebox never answered in time); the panel shows Talk with JARV, whether it is ready,
 * and that approvals are never taken by voice. The API client is replaced; the components are real.
 */
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { spokenSummary, VoiceOperator } from '@/components/voice-operator';

let mockProviders: Record<string, unknown> | null = null;

jest.mock('@/lib/api', () => ({
  apiClient: {
    get: jest.fn(async (path: string) => (path === '/api/voice/providers' && mockProviders
      ? { status: 200, data: mockProviders } : { status: 404, error: 'Voice status is unavailable.' })),
    post: jest.fn(),
  },
}));

describe('VoiceOperator', () => {
  it('offers the live conversation and nothing else', async () => {
    mockProviders = { live: { ready: true, backend: 'openai' } };
    render(<VoiceOperator onMission={jest.fn()} onStateChange={jest.fn()} />);
    expect(await screen.findByText(/search its memory and read your workspaces/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Talk with JARV' })).toBeEnabled();
    expect(screen.queryByText(/Push to talk/)).not.toBeInTheDocument();
    expect(screen.queryByText(/hands-free/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Voicebox/)).not.toBeInTheDocument();
    expect(screen.getByText(/Approvals are never taken by voice/)).toBeInTheDocument();
  });

  it('says what to set up when live conversation is unavailable', async () => {
    mockProviders = { live: { ready: false, setup: 'Live conversation uses OpenAI Realtime: set OPENAI_API_KEY' } };
    render(<VoiceOperator onMission={jest.fn()} onStateChange={jest.fn()} />);
    expect((await screen.findAllByText(/set OPENAI_API_KEY/)).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Talk with JARV' })).toBeDisabled();
  });
});

describe('spokenSummary', () => {
  it('keeps short replies and trims long ones to whole sentences', () => {
    expect(spokenSummary('All good.')).toBe('All good.');
    const long = 'First finding is fine. '.repeat(30);
    const spoken = spokenSummary(long, 60);
    expect(spoken.endsWith('The full result is on screen.')).toBe(true);
    expect(spoken.length).toBeLessThan(100);
    expect(spokenSummary('## Result\n**Done** `ok`')).toBe('Result Done ok');
  });
});
