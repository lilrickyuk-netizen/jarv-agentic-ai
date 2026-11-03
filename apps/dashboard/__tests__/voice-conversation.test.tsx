/**
 * Live conversation: the panel gets a short-lived session from JAI's backend, connects the microphone to the
 * realtime voice service over WebRTC, shows both sides of the conversation, runs each action the model asks for
 * through JAI's backend, follows a mission it starts and has the outcome spoken. The API client, the browser's
 * WebRTC connection, microphone and the SDP exchange are replaced; the component is real.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { VoiceConversation } from '@/components/voice-conversation';

const mockPosts: { path: string; body: unknown }[] = [];
const mockFeed: { id: string; title: string; message: string; severity: string; requires_action?: boolean; created_at: string }[] = [];

jest.mock('@/lib/api', () => ({
  apiClient: {
    get: jest.fn(async (path: string) => {
      if (path === '/api/voice/live/history') {
        return { status: 200, data: { turns: [{ who: 'you', text: 'Earlier: keep Phase 0 offline.', at: '2026-11-02T18:00:00' }] } };
      }
      if (path === '/api/operations-feed/list?limit=8') return { status: 200, data: mockFeed };
      return { status: 404, error: `no ${path}` };
    }),
    post: jest.fn(async (path: string, body?: unknown) => {
      mockPosts.push({ path, body });
      if (path === '/api/voice/live/session') {
        return { status: 200, data: { client_secret: 'ek_test', model: 'gpt-realtime', voice: 'cedar',
          calls_url: 'https://api.openai.com/v1/realtime/calls' } };
      }
      if (path === '/api/voice/live/usage') {
        const tokens = (body as { usage?: { total_tokens?: number } })?.usage?.total_tokens ?? 0;
        return { status: 200, data: tokens > 1000000
          ? { stop: true, reason: "Today's AI spending limit is reached ($10.00 of $10.00); the conversation has ended." }
          : { stop: false } };
      }
      if (path === '/api/voice/live/tool') {
        return { status: 200, data: { intent: 'mission', task_id: 'task-7', reply: 'On it.' } };
      }
      return { status: 404, error: `no ${path}` };
    }),
  },
}));

class FakeChannel {
  readyState = 'connecting';
  sent: Record<string, unknown>[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((message: { data: string }) => void) | null = null;
  send(data: string) { this.sent.push(JSON.parse(data)); }
  close() { this.readyState = 'closed'; }
  open() { this.readyState = 'open'; this.onopen?.(); }
  emit(event: Record<string, unknown>) { this.onmessage?.({ data: JSON.stringify(event) }); }
}

let channel: FakeChannel;
const closed: string[] = [];

class FakePeer {
  connectionState = 'new';
  ontrack: ((event: { streams: unknown[] }) => void) | null = null;
  onconnectionstatechange: (() => void) | null = null;
  addTrack = jest.fn();
  getSenders() { return []; }
  createDataChannel(name: string) { expect(name).toBe('oai-events'); channel = new FakeChannel(); return channel; }
  async createOffer() { return { type: 'offer', sdp: 'v=0 offer' }; }
  async setLocalDescription() {}
  async setRemoteDescription(answer: { sdp: string }) { expect(answer.sdp).toBe('v=0 answer'); }
  close() { closed.push('peer'); }
}

const trackStop = jest.fn();

beforeEach(() => {
  mockPosts.length = 0;
  mockFeed.length = 0;
  closed.length = 0;
  trackStop.mockClear();
  (globalThis as unknown as { RTCPeerConnection: unknown }).RTCPeerConnection = FakePeer;
  (globalThis as unknown as { Audio: unknown }).Audio = class { autoplay = false; srcObject: unknown = null; };
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: jest.fn(async () => ({ getAudioTracks: () => [{ stop: trackStop }], getTracks: () => [{ stop: trackStop }] })) },
  });
  global.fetch = jest.fn(async () => ({ ok: true, status: 201, text: async () => 'v=0 answer' })) as unknown as typeof fetch;
});

describe('VoiceConversation', () => {
  it('holds a spoken conversation, runs the actions JAI takes and speaks a mission outcome', async () => {
    const beforeStart = jest.fn(async () => undefined);
    const onStateChange = jest.fn();
    const onMission = jest.fn(async () => ({ status: 'completed', response_text: 'Three changes this week.', finished: true }));
    render(<VoiceConversation ready beforeStart={beforeStart} onMission={onMission} onStateChange={onStateChange} />);

    // The conversation so far comes back from JAI's records before anything is said.
    expect(await screen.findByText('Earlier: keep Phase 0 offline.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Talk with JAI' }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    const [url, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(url).toBe('https://api.openai.com/v1/realtime/calls');
    expect(init.headers.Authorization).toBe('Bearer ek_test');
    expect(init.body).toBe('v=0 offer');
    expect(beforeStart).toHaveBeenCalled();

    act(() => channel.open());
    expect(await screen.findByText('IN CONVERSATION — JUST TALK')).toBeInTheDocument();
    expect(channel.sent[0]).toMatchObject({ type: 'response.create' });

    act(() => {
      channel.emit({ type: 'response.created' });
      channel.emit({ type: 'response.output_audio_transcript.done', transcript: 'Hello Richard, what do you need?' });
      channel.emit({ type: 'response.done' });
      channel.emit({ type: 'input_audio_buffer.speech_started' });
      channel.emit({ type: 'conversation.item.input_audio_transcription.completed', transcript: 'What changed in MYCO this week?' });
      channel.emit({ type: 'response.created' });
      channel.emit({ type: 'response.function_call_arguments.done', call_id: 'call-1', name: 'start_mission',
        arguments: JSON.stringify({ instruction: 'Summarise what changed in MYCO this week', workspace: 'MYCO' }) });
    });
    expect(screen.getByText('Hello Richard, what do you need?')).toBeInTheDocument();
    expect(screen.getByText('What changed in MYCO this week?')).toBeInTheDocument();
    expect(onStateChange).toHaveBeenCalledWith('listening');
    // Both sides are kept, so the next conversation carries on from this one.
    expect(mockPosts).toContainEqual({ path: '/api/voice/live/turn',
      body: { who: 'jarv', text: 'Hello Richard, what do you need?' } });
    expect(mockPosts).toContainEqual({ path: '/api/voice/live/turn',
      body: { who: 'you', text: 'What changed in MYCO this week?' } });

    await waitFor(() => expect(mockPosts).toContainEqual({ path: '/api/voice/live/tool', body: {
      name: 'start_mission', arguments: { instruction: 'Summarise what changed in MYCO this week', workspace: 'MYCO' } } }));
    await waitFor(() => expect(channel.sent).toContainEqual({ type: 'conversation.item.create', item: {
      type: 'function_call_output', call_id: 'call-1', output: JSON.stringify({ intent: 'mission', task_id: 'task-7', reply: 'On it.' }) } }));
    expect(await screen.findByText('Started a mission')).toBeInTheDocument();
    await waitFor(() => expect(onMission).toHaveBeenCalledWith('task-7'));
    const update = () => channel.sent.find((event) => event.type === 'conversation.item.create'
      && JSON.stringify(event).includes('[mission update]'));
    await waitFor(() => expect(update()).toBeDefined());
    expect(JSON.stringify(update())).toContain('Three changes this week.');

    // One reply at a time: the requests made while JAI was answering go out after it finishes.
    const replies = () => channel.sent.filter((event) => event.type === 'response.create').length;
    expect(replies()).toBe(1);
    act(() => channel.emit({ type: 'response.done' }));
    expect(replies()).toBe(2);

    fireEvent.click(screen.getByRole('button', { name: 'End conversation' }));
    expect(closed).toContain('peer');
    expect(trackStop).toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Talk with JAI' })).toBeInTheDocument();
  });

  it('speaks up on its own about important new activity once it has finished speaking', async () => {
    render(<VoiceConversation ready beforeStart={async () => undefined} onMission={async () => null} onStateChange={jest.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Talk with JAI' }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    act(() => channel.open());
    expect(await screen.findByText('IN CONVERSATION — JUST TALK')).toBeInTheDocument();
    mockFeed.push(
      { id: 'f1', title: 'Mission blocked', message: 'git push waits for your approval.', severity: 'warning',
        requires_action: true, created_at: new Date(Date.now() + 60000).toISOString() },
      { id: 'f2', title: 'Heartbeat', message: 'routine', severity: 'info', created_at: new Date(Date.now() + 60000).toISOString() });
    act(() => channel.emit({ type: 'response.done' }));  // the greeting has been spoken
    const told = () => channel.sent.find((event) => event.type === 'conversation.item.create'
      && JSON.stringify(event).includes('New activity in JAI'));
    await waitFor(() => expect(told()).toBeDefined());
    expect(JSON.stringify(told())).toContain('Mission blocked: git push waits for your approval.');
    expect(JSON.stringify(told())).not.toContain('Heartbeat');
    expect(channel.sent.filter((event) => event.type === 'response.create').length).toBe(2);
    // The update is reported, not acted on: its reply may not call tools.
    const reply = channel.sent.filter((event) => event.type === 'response.create').pop() as { response?: { tool_choice?: string } };
    expect(reply.response?.tool_choice).toBe('none');
    fireEvent.click(screen.getByRole('button', { name: 'End conversation' }));
  });

  it('never starts work because an activity update suggested it, only when Richard asks', async () => {
    render(<VoiceConversation ready beforeStart={async () => undefined} onMission={async () => null} onStateChange={jest.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Talk with JAI' }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    act(() => channel.open());
    expect(await screen.findByText('IN CONVERSATION — JUST TALK')).toBeInTheDocument();
    mockFeed.push({ id: 'f9', title: 'Tool: run_command', message: "'syft' is not installed. Install it with uv tool install.",
      severity: 'error', created_at: new Date(Date.now() + 60000).toISOString() });
    act(() => channel.emit({ type: 'response.done' }));
    await waitFor(() => expect(channel.sent.some((e) => JSON.stringify(e).includes('New activity in JAI'))).toBe(true));
    const posted = () => mockPosts.filter((post) => post.path === '/api/voice/live/tool');
    await act(async () => channel.emit({ type: 'response.function_call_arguments.done', name: 'start_mission',
      call_id: 'c1', arguments: JSON.stringify({ instruction: 'Install syft' }) }));
    await waitFor(() => expect(channel.sent.some((e) => JSON.stringify(e).includes('Richard has not asked for this'))).toBe(true));
    expect(posted()).toHaveLength(0);  // nothing reached the backend
    act(() => channel.emit({ type: 'input_audio_buffer.speech_started' }));  // Richard speaks: his request counts
    await act(async () => channel.emit({ type: 'response.function_call_arguments.done', name: 'start_mission',
      call_id: 'c2', arguments: JSON.stringify({ instruction: 'Run the tests' }) }));
    await waitFor(() => expect(posted()).toHaveLength(1));
    fireEvent.click(screen.getByRole('button', { name: 'End conversation' }));
  });

  it('sends each reply\'s usage to the spend meter and ends the conversation at the daily limit', async () => {
    render(<VoiceConversation ready beforeStart={async () => undefined} onMission={async () => null} onStateChange={jest.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Talk with JAI' }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    act(() => channel.open());
    expect(await screen.findByText('IN CONVERSATION — JUST TALK')).toBeInTheDocument();
    await act(async () => channel.emit({ type: 'response.done', response: { usage: { total_tokens: 900 } } }));
    await waitFor(() => expect(mockPosts.some((p) => p.path === '/api/voice/live/usage')).toBe(true));
    expect(screen.getByRole('button', { name: 'End conversation' })).toBeInTheDocument();  // under the limit: carries on
    await act(async () => channel.emit({ type: 'response.done', response: { usage: { total_tokens: 2000000 } } }));
    expect(await screen.findByText(/spending limit is reached/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Talk with JAI' })).toBeInTheDocument();  // the conversation ended
  });

  it('says what to set up when live conversation is unavailable', () => {
    render(<VoiceConversation ready={false} setup="Live conversation uses OpenAI Realtime: set OPENAI_API_KEY"
      beforeStart={jest.fn()} onMission={jest.fn()} onStateChange={jest.fn()} />);
    expect(screen.getByRole('button', { name: 'Talk with JAI' })).toBeDisabled();
    expect(screen.getByText(/set OPENAI_API_KEY/)).toBeInTheDocument();
  });

  it('shows why the connection was refused and releases the microphone', async () => {
    global.fetch = jest.fn(async () => ({ ok: false, status: 401, text: async () => 'invalid client secret' })) as unknown as typeof fetch;
    render(<VoiceConversation ready beforeStart={jest.fn(async () => undefined)} onMission={jest.fn()} onStateChange={jest.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Talk with JAI' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('refused the connection (401): invalid client secret');
    expect(trackStop).toHaveBeenCalled();
  });
});
