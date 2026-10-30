/**
 * Repair 14c: the voice panel runs on whichever speech service the voice engine has (not only Voicebox):
 * push-to-talk goes to /api/voice/push-to-talk, the spoken reply is played, a mission started by voice is
 * followed and its result is spoken. The API client, the browser's microphone recorder and audio playback
 * are replaced; the component is real.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { spokenSummary, VoiceOperator } from '@/components/voice-operator';

const mockGets: Record<string, unknown> = {};
const mockPosts: { path: string; body: unknown }[] = [];
const mockUploads: { path: string; form: FormData }[] = [];
let mockTurn: unknown = null;

jest.mock('@/lib/api', () => ({
  apiClient: {
    get: jest.fn(async (path: string) => (path in mockGets ? { data: mockGets[path], status: 200 } : { error: `no ${path}`, status: 404 })),
    post: jest.fn(async (path: string, body?: unknown) => {
      mockPosts.push({ path, body });
      return path === '/api/voice/speak' ? { data: { url: '/api/voice/audio/final', audio_id: 'final' }, status: 200 } : { data: {}, status: 200 };
    }),
    upload: jest.fn(async (path: string, form: FormData) => {
      mockUploads.push({ path, form });
      return { data: mockTurn, status: 200 };
    }),
  },
}));
jest.mock('@/lib/auth', () => ({ getAccessToken: () => 'token-1' }));
jest.mock('@/lib/env', () => ({ env: { wsUrl: 'ws://localhost:8000' } }));

const played: string[] = [];

class FakeRecorder {
  static isTypeSupported = () => true;
  state = 'inactive';
  mimeType = 'audio/webm';
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  start() { this.state = 'recording'; }
  stop() {
    this.state = 'inactive';
    this.ondataavailable?.({ data: new Blob([new Uint8Array(4000)], { type: 'audio/webm' }) });
    this.onstop?.();
  }
}

class FakeAudio {
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public src: string) { played.push(src); }
  async play() { setTimeout(() => this.onended?.(), 0); }
  pause() {}
  removeAttribute() {}
}

beforeEach(() => {
  for (const key of Object.keys(mockGets)) delete mockGets[key];
  mockPosts.length = 0;
  mockUploads.length = 0;
  played.length = 0;
  mockGets['/api/voicebox/wake/status'] = { installed: false, phrase_current: false, phrase: 'JARV, talk to me.', model: 'kws', license: 'Apache-2.0' };
  mockGets['/api/voicebox/status'] = { configured: false, connected: false, profile_configured: false };
  mockGets['/auth/me'] = { is_admin: false };
  (globalThis as unknown as { MediaRecorder: unknown }).MediaRecorder = FakeRecorder;
  (globalThis as unknown as { Audio: unknown }).Audio = FakeAudio;
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: jest.fn(async () => ({ active: true, getTracks: () => [{ stop: jest.fn() }] })) },
  });
  global.fetch = jest.fn(async (url: RequestInfo | URL) => ({ ok: true, blob: async () => new Blob([String(url)]) })) as unknown as typeof fetch;
  URL.createObjectURL = jest.fn((blob: Blob) => `blob:${(blob as Blob).size}`);
  URL.revokeObjectURL = jest.fn();
});

describe('VoiceOperator', () => {
  it('hears a command through the configured speech service, answers aloud and reports the mission result', async () => {
    mockGets['/api/voice/providers'] = {
      speech_to_text: { backend: 'openai', ready: true }, text_to_speech: { backend: 'elevenlabs', ready: true },
      wake_word: { ready: false, phrase: 'JARV, talk to me.' },
    };
    mockTurn = { heard: 'run the backend tests', intent: 'mission', reply: "On it. I've started that as a mission.",
      task_id: 'task-1', status: 'queued', requires_approval: false,
      speech: { url: '/api/voice/audio/abc', audio_id: 'abc' }, speech_note: null };
    const onMission = jest.fn(async () => ({ status: 'completed', response_text: 'Backend tests passed: 582 of 582.', finished: true }));
    render(<VoiceOperator onMission={onMission} onStateChange={jest.fn()} />);
    expect(await screen.findByText('HEARING: OPENAI · SPEAKING: ELEVENLABS')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Start push-to-talk voice instruction' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Finish voice instruction' }));
    await waitFor(() => expect(onMission).toHaveBeenCalledWith('task-1'));
    expect(mockUploads[0].path).toBe('/api/voice/push-to-talk');
    expect((mockUploads[0].form.get('audio') as File).name).toBe('voice-command.webm');
    expect(mockUploads[0].form.get('speak')).toBe('true');
    expect(screen.getByText(/run the backend tests/)).toBeInTheDocument();
    expect((global.fetch as jest.Mock).mock.calls[0][0]).toBe('/api/backend/api/voice/audio/abc');
    await waitFor(() => expect(mockPosts).toContainEqual({ path: '/api/voice/speak', body: { text: 'Backend tests passed: 582 of 582.', language: 'en' } }));
    expect(await screen.findByText('Backend tests passed: 582 of 582.')).toBeInTheDocument();
    await waitFor(() => expect(played.length).toBe(2));
  });

  it('shows the refusal for a spoken approval and starts no mission', async () => {
    mockGets['/api/voice/providers'] = {
      speech_to_text: { backend: 'openai', ready: true }, text_to_speech: { backend: null, ready: false, setup: 'Set ELEVENLABS_API_KEY' },
      wake_word: { ready: false },
    };
    mockTurn = { heard: 'JARV, approve the release', intent: 'approval_refused', task_id: null, speech: null, speech_note: null,
      reply: "I can't take approvals by voice. Approve it on the Approvals page." };
    const onMission = jest.fn();
    render(<VoiceOperator onMission={onMission} onStateChange={jest.fn()} />);
    expect(await screen.findByText(/replies are shown, not spoken/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Start push-to-talk voice instruction' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Finish voice instruction' }));
    expect(await screen.findByText(/can't take approvals by voice/)).toBeInTheDocument();
    expect(mockUploads[0].form.get('speak')).toBe('false');
    expect(onMission).not.toHaveBeenCalled();
    expect(played).toEqual([]);
  });

  it('explains what to set up when no speech service is configured', async () => {
    mockGets['/api/voice/providers'] = {
      speech_to_text: { backend: null, ready: false, setup: 'No speech-to-text backend: set VOICEBOX_BASE_URL or OPENAI_API_KEY.' },
      text_to_speech: { backend: null, ready: false }, wake_word: { ready: false },
    };
    render(<VoiceOperator onMission={jest.fn()} onStateChange={jest.fn()} />);
    expect(await screen.findByText(/No speech-to-text backend/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start push-to-talk voice instruction' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Enable hands-free' })).toBeDisabled();
    await act(async () => undefined);
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
