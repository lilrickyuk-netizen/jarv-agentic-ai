/**
 * The browser side of Talk with JAI on Pipecat (Wave 2b): one WebSocket to JAI's voice service. Richard's
 * microphone goes up as 16 kHz mono PCM16; JAI's voice comes back as 24 kHz mono PCM16 and is played as it
 * arrives, stopping at once when he talks over it. Text messages are small JSON objects (what was said on both
 * sides, the cards JAI puts on screen, the actions it takes, and why a conversation ended).
 */
export const MIC_RATE = 16000;
export const VOICE_RATE = 24000;
/**
 * Audio held in hand before JAI starts speaking (and after any gap in arrival). JAI's voice arrives in pieces of a
 * few hundredths of a second, sent at the pace they play; without a little in hand, every piece that arrives a
 * moment late leaves a pause, dozens of times a second, which made the voice sound choppy.
 */
export const JITTER_SECONDS = 0.25;

/** When the next piece of JAI's voice should start: straight after the previous one, or, if playback has run dry,
 * a quarter of a second from now so the pieces that follow have room to arrive. */
export function nextStart(now: number, queuedUntil: number): number {
  return queuedUntil > now ? queuedUntil : now + JITTER_SECONDS;
}

export type PipecatMessage =
  | { type: 'ready'; engine?: string; model?: string }
  | { type: 'you'; text: string }
  | { type: 'jai'; text: string }
  | { type: 'interrupt' }
  | { type: 'card'; card: Record<string, unknown> }
  | { type: 'action'; name: string; label: string; error?: string | null; task_id?: string | null;
      intent?: string | null; resumed?: boolean | null }
  | { type: 'stop'; reason?: string | null };

export interface PipecatHandlers {
  onMessage: (message: PipecatMessage) => void;
  onSpeaking: (speaking: boolean) => void;
  onClosed: (reason: string | null) => void;
}

/** Float samples at any rate to 16-bit PCM at `toRate` (averaging the samples each output sample covers). */
export function toPcm16(input: Float32Array, fromRate: number, toRate: number = MIC_RATE): Int16Array {
  const ratio = fromRate / toRate;
  const length = Math.floor(input.length / ratio);
  const out = new Int16Array(length);
  for (let i = 0; i < length; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.max(start + 1, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end && j < input.length; j += 1) sum += input[j];
    const sample = Math.max(-1, Math.min(1, sum / (end - start)));
    out[i] = sample < 0 ? Math.round(sample * 0x8000) : Math.round(sample * 0x7fff);
  }
  return out;
}

/** 16-bit little-endian PCM to float samples for playback. */
export function fromPcm16(data: ArrayBuffer): Float32Array {
  const view = new DataView(data);
  const out = new Float32Array(Math.floor(data.byteLength / 2));
  for (let i = 0; i < out.length; i += 1) out[i] = view.getInt16(i * 2, true) / 0x8000;
  return out;
}

/** Parse one text message from the voice service; anything unreadable is ignored. */
export function parseMessage(raw: string): PipecatMessage | null {
  try {
    const value = JSON.parse(raw) as { type?: unknown };
    return value && typeof value.type === 'string' ? (value as PipecatMessage) : null;
  } catch {
    return null;
  }
}

/** The voice service's address with Richard's sign-in token; a path alone is taken as on this host. */
export function voiceUrl(base: string, token: string, location: { protocol: string; host: string } = window.location): string {
  const resolved = /^wss?:\/\//.test(base) ? base : `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${base}`;
  const url = new URL(resolved);
  url.searchParams.set('token', token);
  return url.toString();
}

// Captures the microphone in 20 ms frames (runs on the audio thread).
const CAPTURE_WORKLET = `
class JaiCapture extends AudioWorkletProcessor {
  constructor() { super(); this.buffer = []; this.size = Math.round(sampleRate / 50); }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel) {
      for (let i = 0; i < channel.length; i += 1) this.buffer.push(channel[i]);
      while (this.buffer.length >= this.size) this.port.postMessage(new Float32Array(this.buffer.splice(0, this.size)));
    }
    return true;
  }
}
registerProcessor('jai-capture', JaiCapture);
`;

export class PipecatVoice {
  private socket: WebSocket | null = null;
  private micStream: MediaStream | null = null;
  private micContext: AudioContext | null = null;
  private playContext: AudioContext | null = null;
  private playing: AudioBufferSourceNode[] = [];
  private nextTime = 0;
  private speaking = false;
  private speakingTimer: number | null = null;
  private closedByUs = false;
  private destination: MediaStreamAudioDestinationNode | null = null;
  /** JAI's voice as a stream, so the intelligence field moves with it. */
  voiceStream: MediaStream | null = null;

  constructor(private readonly handlers: PipecatHandlers) {}

  /** Open the conversation; resolves when the voice service says it is ready, rejects if it cannot start. */
  async connect(url: string, timeoutMs = 10000): Promise<void> {
    const mic = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    this.micStream = mic;
    const playContext = new AudioContext({ sampleRate: VOICE_RATE });
    this.playContext = playContext;
    this.destination = playContext.createMediaStreamDestination();
    this.voiceStream = this.destination.stream;

    await new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(url);
      socket.binaryType = 'arraybuffer';
      this.socket = socket;
      let ready = false;
      const timer = window.setTimeout(() => {
        if (!ready) { reject(new Error("JAI's voice service did not answer in time.")); socket.close(); }
      }, timeoutMs);
      socket.onmessage = (event) => {
        if (typeof event.data !== 'string') { this.play(event.data as ArrayBuffer); return; }
        const message = parseMessage(String(event.data));
        if (!message) return;
        if (message.type === 'ready' && !ready) { ready = true; window.clearTimeout(timer); resolve(); }
        if (message.type === 'interrupt') this.silence();
        if (message.type === 'stop' && !ready) { window.clearTimeout(timer); reject(new Error(message.reason || "JAI's voice could not start.")); }
        this.handlers.onMessage(message);
      };
      socket.onerror = () => { if (!ready) { window.clearTimeout(timer); reject(new Error("JAI's voice service could not be reached.")); } };
      socket.onclose = (event) => {
        window.clearTimeout(timer);
        if (!ready) { reject(new Error(event.reason || "JAI's voice service could not be reached.")); return; }
        if (!this.closedByUs) this.handlers.onClosed(event.reason || 'The conversation connection was lost.');
        this.release();
      };
    });
    await this.startMicrophone(mic);
  }

  private async startMicrophone(mic: MediaStream) {
    const context = new AudioContext();
    this.micContext = context;
    const url = URL.createObjectURL(new Blob([CAPTURE_WORKLET], { type: 'application/javascript' }));
    try {
      await context.audioWorklet.addModule(url);
    } finally {
      URL.revokeObjectURL(url);
    }
    const node = new AudioWorkletNode(context, 'jai-capture');
    node.port.onmessage = (event: MessageEvent<Float32Array>) => {
      if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(toPcm16(event.data, context.sampleRate).buffer as ArrayBuffer);
    };
    context.createMediaStreamSource(mic).connect(node);
  }

  private play(data: ArrayBuffer) {
    const context = this.playContext;
    if (!context || data.byteLength < 2) return;
    const samples = fromPcm16(data);
    const buffer = context.createBuffer(1, samples.length, VOICE_RATE);
    buffer.getChannelData(0).set(samples);
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    if (this.destination) source.connect(this.destination);
    const at = nextStart(context.currentTime, this.nextTime);
    source.start(at);
    this.nextTime = at + buffer.duration;
    this.playing.push(source);
    source.onended = () => { this.playing = this.playing.filter((s) => s !== source); };
    this.setSpeaking(true);
    if (this.speakingTimer !== null) window.clearTimeout(this.speakingTimer);
    this.speakingTimer = window.setTimeout(() => this.setSpeaking(false),
      Math.max(0, (this.nextTime - context.currentTime) * 1000) + 150);
  }

  /** Richard talked over JAI: stop its voice at once. */
  silence() {
    this.playing.forEach((source) => { try { source.stop(); } catch { /* already ended */ } });
    this.playing = [];
    this.nextTime = 0;
    this.setSpeaking(false);
  }

  private setSpeaking(value: boolean) {
    if (this.speaking === value) return;
    this.speaking = value;
    this.handlers.onSpeaking(value);
  }

  /** A message for JAI to answer: a mission's outcome, or new activity (`update`: reported, never acted on). */
  note(text: string, update = false) {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify({ type: 'note', text, update }));
  }

  get open() {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  stop() {
    this.closedByUs = true;
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify({ type: 'stop' }));
    this.socket?.close();
    this.release();
  }

  private release() {
    this.silence();
    if (this.speakingTimer !== null) window.clearTimeout(this.speakingTimer);
    this.micStream?.getTracks().forEach((track) => track.stop());
    this.micStream = null;
    void this.micContext?.close().catch(() => undefined);
    void this.playContext?.close().catch(() => undefined);
    this.micContext = null;
    this.playContext = null;
    this.voiceStream = null;
    this.destination = null;
    this.socket = null;
  }
}
