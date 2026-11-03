/**
 * Talk with JAI on Pipecat (Wave 2b): the panel asks JAI's backend which voice to use, opens one WebSocket to
 * JAI's voice service with Richard's sign-in token, streams his microphone up as 16 kHz PCM16, plays JAI's
 * 24 kHz voice as it arrives (stopping at once when he talks over it), shows both sides, puts cards on screen,
 * follows a mission JAI starts and tells JAI how it ended. If the voice service cannot be reached it falls back
 * to the Realtime voice. The API client, WebSocket, microphone and Web Audio are replaced; the code is real.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { VoiceConversation } from '@/components/voice-conversation';
import { JITTER_SECONDS, fromPcm16, nextStart, parseMessage, toPcm16, voiceUrl } from '@/lib/pipecat-voice';
import { getCard, showCard } from '@/lib/screen-signal';

const mockPosts: { path: string; body: unknown }[] = [];
let mockEngine: Record<string, unknown> | null = { engine: 'pipecat', url: 'ws://localhost:8765/ws', fallback: 'realtime' };

jest.mock('@/lib/api', () => ({
  apiClient: {
    get: jest.fn(async (path: string) => {
      if (path === '/api/voice/live/history') return { status: 200, data: { turns: [] } };
      if (path === '/api/voice/live/engine') return mockEngine ? { status: 200, data: mockEngine } : { status: 502, error: 'down' };
      if (path === '/api/operations-feed/list?limit=8') return { status: 200, data: [] };
      return { status: 404, error: `no ${path}` };
    }),
    post: jest.fn(async (path: string, body?: unknown) => {
      mockPosts.push({ path, body });
      if (path === '/api/voice/live/session') {
        return { status: 200, data: { client_secret: 'ek_test', model: 'gpt-realtime', voice: 'cedar',
          calls_url: 'https://api.openai.com/v1/realtime/calls' } };
      }
      return { status: 404, error: `no ${path}` };
    }),
  },
}));

class FakeSocket {
  static last: FakeSocket | null = null;
  static OPEN = 1;
  static refuse = false;
  readyState = 0;
  binaryType = 'blob';
  sent: unknown[] = [];
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((event: { reason: string }) => void) | null = null;
  constructor(public url: string) {
    FakeSocket.last = this;
    setTimeout(() => {
      if (FakeSocket.refuse) { this.onerror?.(); this.onclose?.({ reason: '' }); return; }
      this.readyState = 1;
      this.text({ type: 'ready', engine: 'pipecat', model: 'gpt-6-luna' });
    }, 0);
  }
  send(data: unknown) { this.sent.push(typeof data === 'string' ? JSON.parse(data) : data); }
  close() { this.readyState = 3; }
  text(message: Record<string, unknown>) { this.onmessage?.({ data: JSON.stringify(message) }); }
  audio(bytes: number) { this.onmessage?.({ data: new ArrayBuffer(bytes) }); }
}

const started: { at: number; stopped: boolean }[] = [];

class FakeAudioContext {
  currentTime = 0;
  sampleRate: number;
  destination = {};
  audioWorklet = { addModule: jest.fn(async () => undefined) };
  constructor(options?: { sampleRate?: number }) { this.sampleRate = options?.sampleRate ?? 48000; }
  createMediaStreamDestination() { return { stream: { id: 'jai-voice' } }; }
  createMediaStreamSource() { return { connect: jest.fn() }; }
  createBuffer(_channels: number, length: number, rate: number) {
    const data = new Float32Array(length);
    return { duration: length / rate, getChannelData: () => data };
  }
  createBufferSource() {
    const entry = { at: 0, stopped: false };
    return { buffer: null, connect: jest.fn(), onended: null,
      start: (at: number) => { entry.at = at; started.push(entry); }, stop: () => { entry.stopped = true; } };
  }
  close = jest.fn(async () => undefined);
}

class FakeWorkletNode { port: { onmessage: ((event: { data: Float32Array }) => void) | null } = { onmessage: null }; static last: FakeWorkletNode | null = null;
  constructor() { FakeWorkletNode.last = this; } }

const trackStop = jest.fn();

beforeEach(() => {
  mockPosts.length = 0;
  started.length = 0;
  FakeSocket.refuse = false;
  mockEngine = { engine: 'pipecat', url: 'ws://localhost:8765/ws', fallback: 'realtime' };
  window.localStorage.setItem('access_token', 'tok-richard');
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = FakeSocket;
  (globalThis as unknown as { AudioContext: unknown }).AudioContext = FakeAudioContext;
  (globalThis as unknown as { AudioWorkletNode: unknown }).AudioWorkletNode = FakeWorkletNode;
  URL.createObjectURL = jest.fn(() => 'blob:jai-capture');
  URL.revokeObjectURL = jest.fn();
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: jest.fn(async () => ({ getAudioTracks: () => [{ stop: trackStop }], getTracks: () => [{ stop: trackStop }] })) },
  });
  global.fetch = jest.fn(async () => ({ ok: true, status: 201, text: async () => 'v=0 answer' })) as unknown as typeof fetch;
  showCard(null);
});

describe('Pipecat voice helpers', () => {
  it('turns the microphone into 16 kHz PCM16 and JAI\'s voice back into samples', () => {
    const pcm = toPcm16(new Float32Array([1, 1, 1, -1, -1, -1, 0, 0, 0]), 48000, 16000);
    expect(Array.from(pcm)).toEqual([32767, -32768, 0]);
    const bytes = new Int16Array([16384, -16384]).buffer;
    expect(Array.from(fromPcm16(bytes))).toEqual([0.5, -0.5]);
    expect(parseMessage('{"type":"jai","text":"Done."}')).toEqual({ type: 'jai', text: 'Done.' });
    expect(parseMessage('nonsense')).toBeNull();
    expect(voiceUrl('ws://localhost:8765/ws', 'a b')).toBe('ws://localhost:8765/ws?token=a+b');
    expect(voiceUrl('/voice/ws', 't', { protocol: 'https:', host: 'jai.example' })).toBe('wss://jai.example/voice/ws?token=t');
  });

  it('plays JAI\'s voice back to back, keeping a quarter of a second in hand so it never stutters', () => {
    expect(nextStart(10, 0)).toBe(10 + JITTER_SECONDS);       // starting to speak: a little in hand first
    expect(nextStart(10, 10.4)).toBe(10.4);                   // the next piece follows with no gap
    expect(nextStart(10, 9.99)).toBe(10 + JITTER_SECONDS);    // ran dry: build the buffer again, never a click
  });
});

describe('VoiceConversation on Pipecat', () => {
  it('talks through JAI\'s voice service, shows both sides, plays and stops its voice and follows a mission', async () => {
    const onStateChange = jest.fn();
    const onMission = jest.fn(async () => ({ status: 'completed', response_text: 'Phase 0 verified.', finished: true }));
    render(<VoiceConversation ready beforeStart={async () => undefined} onMission={onMission} onStateChange={onStateChange} />);
    fireEvent.click(screen.getByRole('button', { name: 'Talk with JAI' }));
    expect(await screen.findByText('IN CONVERSATION — JUST TALK')).toBeInTheDocument();
    expect(screen.getByText('PIPECAT')).toBeInTheDocument();
    const socket = FakeSocket.last as FakeSocket;
    expect(socket.url).toBe('ws://localhost:8765/ws?token=tok-richard');
    expect(mockPosts.find((p) => p.path === '/api/voice/live/session')).toBeUndefined();  // no Realtime session

    // The microphone goes up as binary PCM.
    await waitFor(() => expect(FakeWorkletNode.last?.port.onmessage).toBeTruthy());
    act(() => FakeWorkletNode.last?.port.onmessage?.({ data: new Float32Array(960) }));
    expect(socket.sent.some((item) => Object.prototype.toString.call(item) === '[object ArrayBuffer]'
      && (item as ArrayBuffer).byteLength === 640)).toBe(true);

    act(() => {
      socket.text({ type: 'you', text: 'Is Phase 0 done?' });
      socket.audio(4800);
      socket.text({ type: 'jai', text: 'Not yet. Let me check.' });
      socket.text({ type: 'card', card: { kind: 'mission', title: 'Phase 0' } });
    });
    expect(screen.getByText('Is Phase 0 done?')).toBeInTheDocument();
    expect(screen.getByText('Not yet. Let me check.')).toBeInTheDocument();
    expect(onStateChange).toHaveBeenCalledWith('speaking');
    expect((getCard() as { title?: string } | null)?.title).toBe('Phase 0');
    // The voice service keeps the history itself: the panel does not post the turns again.
    expect(mockPosts.find((p) => p.path === '/api/voice/live/turn')).toBeUndefined();

    act(() => socket.text({ type: 'interrupt' }));
    expect(started.every((source) => source.stopped)).toBe(true);

    act(() => socket.text({ type: 'action', name: 'start_mission', label: 'Started a mission', intent: 'mission', task_id: 'task-9' }));
    expect(screen.getByText('Started a mission')).toBeInTheDocument();
    await waitFor(() => expect(onMission).toHaveBeenCalledWith('task-9'));
    await waitFor(() => expect(socket.sent).toContainEqual({ type: 'note', update: false,
      text: '[mission update] Status completed. Phase 0 verified.' }));

    fireEvent.click(screen.getByRole('button', { name: 'End conversation' }));
    expect(socket.sent).toContainEqual({ type: 'stop' });
    expect(trackStop).toHaveBeenCalled();
  });

  it('says why when the voice service ends the conversation at the spending limit', async () => {
    render(<VoiceConversation ready beforeStart={async () => undefined} onMission={async () => null} onStateChange={jest.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Talk with JAI' }));
    await screen.findByText('IN CONVERSATION — JUST TALK');
    act(() => {
      (FakeSocket.last as FakeSocket).text({ type: 'stop', reason: "Today's AI spending limit is reached ($10.00 of $10.00)." });
      (FakeSocket.last as FakeSocket).onclose?.({ reason: '' });
    });
    expect(await screen.findByRole('alert')).toHaveTextContent("Today's AI spending limit is reached");
    expect(screen.getByRole('button', { name: 'Talk with JAI' })).toBeInTheDocument();
  });

  it('falls back to the Realtime voice when JAI\'s voice service cannot be reached', async () => {
    FakeSocket.refuse = true;
    (globalThis as unknown as { RTCPeerConnection: unknown }).RTCPeerConnection = class {
      connectionState = 'new'; ontrack = null; onconnectionstatechange = null; addTrack = jest.fn();
      getSenders() { return []; }
      createDataChannel() { return { readyState: 'connecting', send: jest.fn(), close: jest.fn(), onopen: null, onmessage: null }; }
      async createOffer() { return { type: 'offer', sdp: 'v=0 offer' }; }
      async setLocalDescription() {}
      async setRemoteDescription() {}
      close() {}
    };
    (globalThis as unknown as { Audio: unknown }).Audio = class { autoplay = false; srcObject: unknown = null; };
    render(<VoiceConversation ready beforeStart={async () => undefined} onMission={async () => null} onStateChange={jest.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Talk with JAI' }));
    await waitFor(() => expect(mockPosts.find((p) => p.path === '/api/voice/live/session')).toBeDefined());
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('https://api.openai.com/v1/realtime/calls', expect.anything()));
  });
});
