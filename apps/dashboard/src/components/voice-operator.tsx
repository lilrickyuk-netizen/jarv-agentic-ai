'use client';

import { useEffect, useRef, useState } from 'react';
import { apiClient } from '@/lib/api';
import { getAccessToken } from '@/lib/auth';
import { env } from '@/lib/env';

type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking';

/** /api/voice/transcribe: what was heard, and the command after the wake phrase when it was said. */
type WakeCheck = { text: string; command: string; wake_heard: boolean };

interface VoicePart { backend?: string | null; ready: boolean; setup?: string | null; phrase?: string }

export interface VoiceProviders {
  speech_to_text: VoicePart;
  text_to_speech: VoicePart;
  wake_word: VoicePart;
}

interface VoiceboxStatus {
  configured: boolean;
  connected: boolean;
  profile_configured: boolean;
}

interface WakeModelStatus {
  installed: boolean;
  phrase_current: boolean;
  phrase: string;
  model: string;
  license: string;
}

interface Speech { url: string; audio_id: string }

/** One spoken turn as the voice engine answers it (POST /api/voice/push-to-talk or /command/text). */
export interface VoiceTurn {
  heard: string;
  intent: 'mission' | 'status' | 'cancel' | 'approval_refused' | 'wake' | string;
  reply: string;
  task_id: string | null;
  status?: string;
  requires_approval?: boolean;
  speech: Speech | null;
  speech_note: string | null;
}

export interface MissionReport { status: string; response_text: string; finished?: boolean; requires_approval?: boolean }

interface Props {
  /** Follow a mission started by voice (shown in the Command Center) and resolve with its final state. */
  onMission: (taskId: string) => Promise<MissionReport | null>;
  onStateChange: (state: VoiceState) => void;
}

/** The part of a long result worth saying aloud; the full text stays on screen. */
export function spokenSummary(text: string, limit = 400): string {
  const clean = text.replace(/[#*_`>|]/g, ' ').replace(/\s+/g, ' ').trim();
  if (clean.length <= limit) return clean;
  const sentences = clean.match(/[^.!?]+[.!?]+/g) ?? [clean];
  let out = '';
  for (const sentence of sentences) {
    if ((out + sentence).length > limit) break;
    out += sentence;
  }
  return `${(out || clean.slice(0, limit)).trim()} The full result is on screen.`;
}

function resampleAudio(samples: Float32Array, sourceRate: number, targetRate: number): Float32Array {
  if (sourceRate === targetRate) return new Float32Array(samples);
  const ratio = sourceRate / targetRate;
  const output = new Float32Array(Math.floor(samples.length / ratio));
  for (let outputIndex = 0; outputIndex < output.length; outputIndex += 1) {
    const sourceStart = Math.floor(outputIndex * ratio);
    const sourceEnd = Math.min(Math.floor((outputIndex + 1) * ratio), samples.length);
    let total = 0;
    for (let sourceIndex = sourceStart; sourceIndex < sourceEnd; sourceIndex += 1) total += samples[sourceIndex];
    output[outputIndex] = total / Math.max(sourceEnd - sourceStart, 1);
  }
  return output;
}

function pcmToWav(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeString = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index += 1) view.setUint8(offset + index, value.charCodeAt(index));
  };
  writeString(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, 'data');
  view.setUint32(40, samples.length * 2, true);
  for (let index = 0; index < samples.length; index += 1) {
    const value = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(44 + index * 2, value < 0 ? value * 32768 : value * 32767, true);
  }
  return new Blob([buffer], { type: 'audio/wav' });
}

function mergeAudioFrames(frames: Float32Array[]): Float32Array {
  const totalSamples = frames.reduce((total, frame) => total + frame.length, 0);
  const merged = new Float32Array(totalSamples);
  let offset = 0;
  frames.forEach((frame) => {
    merged.set(frame, offset);
    offset += frame.length;
  });
  return merged;
}

function parseSocketUrl(): string {
  const localBrowser = ['localhost', '127.0.0.1'].includes(window.location.hostname);
  const socketBase = localBrowser ? env.wsUrl : window.location.origin;
  const url = new URL('/api/voicebox/wake', socketBase);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}

export function VoiceOperator({ onMission, onStateChange }: Props) {
  const [providers, setProviders] = useState<VoiceProviders | null>(null);
  const [providersError, setProvidersError] = useState<string | null>(null);
  const [voicebox, setVoicebox] = useState<VoiceboxStatus | null>(null);
  const [wakeModel, setWakeModel] = useState<WakeModelStatus | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [handsFree, setHandsFree] = useState(false);
  const handsFreeRef = useRef(false);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [speechActive, setSpeechActive] = useState(false);
  const [message, setMessage] = useState('');
  const [heard, setHeard] = useState('');
  const onMissionRef = useRef(onMission);
  const onStateChangeRef = useRef(onStateChange);
  const providersRef = useRef<VoiceProviders | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const wakeSocketRef = useRef<WebSocket | null>(null);
  const wakeProbeFramesRef = useRef<Float32Array[]>([]);
  const wakeProbeActiveRef = useRef(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const captureChunksRef = useRef<Blob[]>([]);
  const preRollRef = useRef<Float32Array[]>([]);
  const pcmCommandRef = useRef<Float32Array[]>([]);
  const pcmCaptureRef = useRef(false);
  const captureTimerRef = useRef<number | null>(null);
  const lastVoiceAtRef = useRef(0);
  const recordingRef = useRef(false);
  const processingRef = useRef(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const speechAbortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);

  onMissionRef.current = onMission;
  onStateChangeRef.current = onStateChange;
  providersRef.current = providers;

  const setVoiceState = (state: VoiceState) => onStateChangeRef.current(state);
  const hearingReady = Boolean(providers?.speech_to_text.ready);
  const speakingReady = Boolean(providers?.text_to_speech.ready);
  const wakeReady = Boolean(wakeModel?.installed && wakeModel.phrase_current);
  // Ambient speech is only transcribed to look for the wake phrase when recognition runs on JARV's own server.
  const localHearing = providers?.speech_to_text.backend === 'voicebox';

  const loadStatus = async () => {
    const [providerResponse, wakeResponse, voiceboxResponse, userResponse] = await Promise.all([
      apiClient.get<VoiceProviders>('/api/voice/providers'),
      apiClient.get<WakeModelStatus>('/api/voicebox/wake/status'),
      apiClient.get<VoiceboxStatus>('/api/voicebox/status'),
      apiClient.get<{ is_admin?: boolean }>('/auth/me'),
    ]);
    if (providerResponse.data) {
      setProviders(providerResponse.data);
      setProvidersError(null);
    } else {
      setProvidersError(providerResponse.error || 'Voice status is unavailable.');
    }
    if (wakeResponse.data) setWakeModel(wakeResponse.data);
    if (voiceboxResponse.data) setVoicebox(voiceboxResponse.data);
    if (userResponse.data) setIsAdmin(Boolean(userResponse.data.is_admin));
  };

  useEffect(() => {
    mountedRef.current = true;
    void loadStatus();
    return () => {
      mountedRef.current = false;
      void stopHandsFree(false);
      stopSpeech();
    };
  }, []);

  const stopSpeech = () => {
    speechAbortRef.current?.abort();
    speechAbortRef.current = null;
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.removeAttribute('src');
      audioRef.current = null;
    }
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
    setSpeechActive(false);
  };

  /** Play speech the voice engine stored for this operator (GET /api/voice/audio/{id}). */
  const play = async (speech: Speech) => {
    stopSpeech();
    const abortController = new AbortController();
    speechAbortRef.current = abortController;
    setSpeechActive(true);
    const token = getAccessToken();
    try {
      const response = await fetch(`/api/backend${speech.url}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: abortController.signal,
      });
      if (!response.ok) throw new Error('The spoken reply could not be retrieved.');
      const audioUrl = URL.createObjectURL(await response.blob());
      audioUrlRef.current = audioUrl;
      const audio = new Audio(audioUrl);
      audioRef.current = audio;
      setVoiceState('speaking');
      await audio.play();
      await new Promise<void>((resolve, reject) => {
        audio.onended = () => resolve();
        audio.onerror = () => reject(new Error('The spoken reply could not be played.'));
      });
    } catch (error) {
      if (!abortController.signal.aborted) setMessage(error instanceof Error ? error.message : 'Spoken reply failed.');
    } finally {
      if (speechAbortRef.current === abortController) speechAbortRef.current = null;
      audioRef.current = null;
      if (audioUrlRef.current) {
        URL.revokeObjectURL(audioUrlRef.current);
        audioUrlRef.current = null;
      }
      setSpeechActive(false);
      if (mountedRef.current) setVoiceState(handsFreeRef.current ? 'listening' : 'idle');
    }
  };

  /** Say a line with whichever speech service is configured; the text stays on screen either way. */
  const speak = async (text: string) => {
    if (!providersRef.current?.text_to_speech.ready || !text.trim()) return;
    const generated = await apiClient.post<Speech>('/api/voice/speak', { text: text.slice(0, 4000), language: 'en' });
    if (generated.error || !generated.data?.url) {
      setMessage(generated.error || 'The reply could not be spoken.');
      return;
    }
    await play(generated.data);
  };

  /** Report back when a mission started by voice finishes or pauses. */
  const followAndReport = async (taskId: string) => {
    try {
      const final = await onMissionRef.current(taskId);
      if (!final || !mountedRef.current) return;
      const text = final.requires_approval || final.status === 'waiting_on_approval' || final.status === 'blocked'
        ? 'That mission is paused for your approval. Approve it on the Approvals page and I will carry on.'
        : final.response_text;
      if (!text) return;
      setMessage(text);
      await speak(spokenSummary(text));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'The mission could not be followed.');
    }
  };

  const handleTurn = async (turn: VoiceTurn) => {
    setHeard(turn.heard);
    setMessage(turn.reply);
    if (turn.speech) await play(turn.speech);
    else if (turn.speech_note && speakingReady) setMessage(`${turn.reply} (${turn.speech_note})`);
    if (turn.intent === 'mission' && turn.task_id && !turn.requires_approval) void followAndReport(turn.task_id);
    if (turn.intent === 'wake' && handsFreeRef.current && !recordingRef.current) startPcmCapture();
  };

  const finishCapture = () => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === 'inactive') return;
    recorder.stop();
  };

  const finishPcmCapture = () => {
    if (!pcmCaptureRef.current) return;
    pcmCaptureRef.current = false;
    recordingRef.current = false;
    setRecording(false);
    if (captureTimerRef.current) window.clearTimeout(captureTimerRef.current);
    captureTimerRef.current = null;
    const chunks = pcmCommandRef.current;
    pcmCommandRef.current = [];
    const totalSamples = chunks.reduce((total, chunk) => total + chunk.length, 0);
    if (totalSamples < 16000 * 0.35) {
      setVoiceState(handsFreeRef.current ? 'listening' : 'idle');
      return;
    }
    void processCapture(pcmToWav(mergeAudioFrames(chunks), 16000), 'voice-command.wav');
  };

  const startPcmCapture = () => {
    if (recordingRef.current || processingRef.current) return;
    pcmCaptureRef.current = true;
    recordingRef.current = true;
    wakeProbeActiveRef.current = false;
    wakeProbeFramesRef.current = [];
    pcmCommandRef.current = preRollRef.current;
    preRollRef.current = [];
    lastVoiceAtRef.current = Date.now();
    setRecording(true);
    setMessage('Listening for your instruction…');
    setVoiceState('listening');
    captureTimerRef.current = window.setTimeout(finishPcmCapture, 30000);
  };

  const startCapture = (stream: MediaStream) => {
    if (recordingRef.current || processingRef.current) return;
    const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus']
      .find((type) => MediaRecorder.isTypeSupported(type));
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    captureChunksRef.current = [];
    recorder.ondataavailable = (event) => {
      if (event.data.size) captureChunksRef.current.push(event.data);
    };
    recorder.onstop = () => {
      recordingRef.current = false;
      recorderRef.current = null;
      setRecording(false);
      if (!handsFreeRef.current) {
        mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
        mediaStreamRef.current = null;
      }
      if (captureTimerRef.current) window.clearTimeout(captureTimerRef.current);
      captureTimerRef.current = null;
      const type = recorder.mimeType || 'audio/webm';
      const blob = new Blob(captureChunksRef.current, { type });
      captureChunksRef.current = [];
      if (blob.size < 1500) {
        setMessage('That was too short to hear. Hold on a moment longer and try again.');
        setVoiceState(handsFreeRef.current ? 'listening' : 'idle');
        return;
      }
      void processCapture(blob, type.includes('ogg') ? 'voice-command.ogg' : 'voice-command.webm');
    };
    recorder.start(250);
    recorderRef.current = recorder;
    recordingRef.current = true;
    setRecording(true);
    setMessage('Listening… press Finish when you are done.');
    setVoiceState('listening');
    captureTimerRef.current = window.setTimeout(finishCapture, 30000);
  };

  /** Recording in; transcript, the action taken and the spoken reply out (POST /api/voice/push-to-talk). */
  const processCapture = async (blob: Blob, filename: string) => {
    processingRef.current = true;
    setBusy(true);
    setVoiceState('thinking');
    setMessage('Working out what you said…');
    try {
      const form = new FormData();
      form.append('audio', new File([blob], filename, { type: blob.type || 'audio/webm' }));
      form.append('language', 'en');
      form.append('speak', speakingReady ? 'true' : 'false');
      const turn = await apiClient.upload<VoiceTurn>('/api/voice/push-to-talk', form);
      if (turn.error || !turn.data) throw new Error(turn.error || 'No speech was recognized.');
      processingRef.current = false;
      setBusy(false);
      await handleTurn(turn.data);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Voice command failed.');
    } finally {
      processingRef.current = false;
      setBusy(false);
      if (mountedRef.current && !recordingRef.current && !audioRef.current) setVoiceState(handsFreeRef.current ? 'listening' : 'idle');
    }
  };

  /** Without a wake event, a burst of speech is checked for the wake phrase on JARV's own speech service. */
  const processWakePhrase = async (frames: Float32Array[]) => {
    if (processingRef.current || recordingRef.current || !handsFreeRef.current || !localHearing) return;
    const samples = mergeAudioFrames(frames);
    if (samples.length < 16000 * 0.35) return;
    processingRef.current = true;
    setBusy(true);
    setVoiceState('thinking');
    try {
      const form = new FormData();
      form.append('audio', new File([pcmToWav(samples, 16000)], 'wake-check.wav', { type: 'audio/wav' }));
      form.append('language', 'en');
      // The backend finds the wake phrase, including the ways speech recognisers write "JARV".
      const transcription = await apiClient.upload<WakeCheck>('/api/voice/transcribe', form);
      if (transcription.error) {
        setMessage(transcription.error);
        return;
      }
      const heard = transcription.data;
      if (!heard?.wake_heard) {
        const said = heard?.text?.trim();
        if (said) setMessage(`Heard “${said}”. Start with “${wakeModel?.phrase || 'JARV, talk to me.'}”`);
        return;
      }
      const command = (heard.command || '').trim();
      processingRef.current = false;
      setBusy(false);
      if (!command) {
        await speak("I'm listening.");
        startPcmCapture();
        return;
      }
      const turn = await apiClient.post<VoiceTurn>('/api/voice/command/text', { command, speak: speakingReady });
      if (turn.error || !turn.data) throw new Error(turn.error || 'The command could not be sent.');
      await handleTurn(turn.data);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Wake phrase check failed.');
    } finally {
      processingRef.current = false;
      setBusy(false);
      if (mountedRef.current && !recordingRef.current && !audioRef.current) setVoiceState(handsFreeRef.current ? 'listening' : 'idle');
    }
  };

  const ensureMicrophone = async () => {
    if (mediaStreamRef.current?.active) return mediaStreamRef.current;
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    mediaStreamRef.current = stream;
    return stream;
  };

  const startHandsFree = async () => {
    if (!hearingReady) {
      setMessage(providers?.speech_to_text.setup || 'Set up speech recognition before enabling hands-free mode.');
      return;
    }
    if (!wakeModel?.installed) {
      setMessage('Install the local wake-word model before enabling hands-free mode.');
      return;
    }
    if (!wakeModel.phrase_current) {
      setMessage('Update the local wake phrase to “JARV, talk to me” before enabling hands-free mode.');
      return;
    }
    setBusy(true);
    setMessage('Requesting microphone access…');
    let context: AudioContext | null = null;
    try {
      const stream = await ensureMicrophone();
      const ticketResponse = await apiClient.post<{ ticket: string }>('/api/voicebox/wake/ticket');
      if (ticketResponse.error || !ticketResponse.data?.ticket) throw new Error(ticketResponse.error || 'Wake session could not be created.');
      context = new AudioContext({ sampleRate: 16000 });
      await context.resume();
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(4096, 1, 1);
      const socket = new WebSocket(parseSocketUrl(), ['jarv-wake', `ticket.${ticketResponse.data.ticket}`]);
      socket.binaryType = 'arraybuffer';
      wakeSocketRef.current = socket;
      socket.onmessage = async (event) => {
        try {
          const payload = JSON.parse(String(event.data)) as { type?: string };
          if (payload.type === 'ready') {
            handsFreeRef.current = true;
            setHandsFree(true);
            setMessage(`Hands-free is on. Say “${wakeModel?.phrase || 'JARV, talk to me.'}”`);
            setVoiceState('listening');
            setBusy(false);
          } else if (payload.type === 'wake') {
            if (recordingRef.current || processingRef.current) return;
            if (audioRef.current) stopSpeech();
            wakeProbeActiveRef.current = false;
            wakeProbeFramesRef.current = [];
            setMessage('Wake phrase heard.');
            await speak("I'm listening.");
            preRollRef.current = [];
            startPcmCapture();
          }
        } catch {
          setMessage('Wake detector returned an invalid event.');
        }
      };
      socket.onerror = () => setMessage('The local wake detector connection failed.');
      socket.onclose = () => {
        if (handsFreeRef.current) void stopHandsFree();
      };
      processor.onaudioprocess = (event) => {
        const input = event.inputBuffer.getChannelData(0);
        const samples = resampleAudio(input, context?.sampleRate ?? 16000, 16000);
        let energy = 0;
        for (let index = 0; index < samples.length; index += 1) energy += samples[index] * samples[index];
        const rms = Math.sqrt(energy / Math.max(samples.length, 1));
        if (handsFreeRef.current && !pcmCaptureRef.current) {
          preRollRef.current.push(samples);
          let retainedSamples = preRollRef.current.reduce((total, chunk) => total + chunk.length, 0);
          while (preRollRef.current.length > 1 && retainedSamples > 16000 * 1.5) {
            retainedSamples -= preRollRef.current.shift()?.length ?? 0;
          }
          if (!processingRef.current && localHearing) {
            if (rms > 0.018) {
              lastVoiceAtRef.current = Date.now();
              if (!wakeProbeActiveRef.current) {
                wakeProbeActiveRef.current = true;
                wakeProbeFramesRef.current = preRollRef.current.slice(0, -1);
              }
            }
            if (wakeProbeActiveRef.current) {
              wakeProbeFramesRef.current.push(samples);
              const probeLength = wakeProbeFramesRef.current.reduce((total, frame) => total + frame.length, 0);
              if (Date.now() - lastVoiceAtRef.current > 1300 || probeLength >= 16000 * 12) {
                const frames = wakeProbeFramesRef.current;
                wakeProbeFramesRef.current = [];
                wakeProbeActiveRef.current = false;
                preRollRef.current = [];
                void processWakePhrase(frames);
              }
            }
          }
        }
        if (pcmCaptureRef.current) {
          pcmCommandRef.current.push(samples);
          if (rms > 0.018) lastVoiceAtRef.current = Date.now();
          else if (Date.now() - lastVoiceAtRef.current > 1300) finishPcmCapture();
        }
        if (socket.readyState === WebSocket.OPEN) socket.send(samples.buffer);
      };
      source.connect(processor);
      processor.connect(context.destination);
      sourceRef.current = source;
      processorRef.current = processor;
      audioContextRef.current = context;
    } catch (error) {
      if (context) await context.close().catch(() => undefined);
      if (!handsFreeRef.current) {
        mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
        mediaStreamRef.current = null;
      }
      setBusy(false);
      setMessage(error instanceof Error ? error.message : 'Hands-free mode could not start.');
    }
  };

  const stopHandsFree = async (updateState = true) => {
    handsFreeRef.current = false;
    wakeProbeActiveRef.current = false;
    wakeProbeFramesRef.current = [];
    if (pcmCaptureRef.current) {
      if (updateState) finishPcmCapture();
      else {
        pcmCaptureRef.current = false;
        recordingRef.current = false;
        pcmCommandRef.current = [];
      }
    }
    wakeSocketRef.current?.close(1000, 'Operator disabled wake detection');
    wakeSocketRef.current = null;
    processorRef.current?.disconnect();
    processorRef.current = null;
    sourceRef.current?.disconnect();
    sourceRef.current = null;
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop();
    if (captureTimerRef.current) window.clearTimeout(captureTimerRef.current);
    captureTimerRef.current = null;
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
    const context = audioContextRef.current;
    audioContextRef.current = null;
    if (context && context.state !== 'closed') await context.close().catch(() => undefined);
    setHandsFree(false);
    if (updateState && mountedRef.current) setVoiceState('idle');
  };

  const installWakeModel = async () => {
    setBusy(true);
    setMessage('Preparing and validating the local wake phrase…');
    const response = await apiClient.post<WakeModelStatus>('/api/voicebox/wake/model/install');
    setBusy(false);
    if (response.error) {
      setMessage(response.error);
      return;
    }
    if (response.data) setWakeModel(response.data);
    setMessage(`Wake phrase “${response.data?.phrase || 'JARV, talk to me.'}” is ready.`);
    await loadStatus();
  };

  const provisionVoice = async () => {
    setBusy(true);
    setMessage('Creating JARV’s speech profile on Voicebox…');
    const response = await apiClient.post<{ profile_id: string; voice: string }>('/api/voicebox/profile/provision');
    setBusy(false);
    if (response.error) {
      setMessage(response.error);
      return;
    }
    await loadStatus();
    setMessage('JARV’s Voicebox speech profile is ready.');
  };

  const startPushToTalk = async () => {
    if (!hearingReady) {
      setMessage(providers?.speech_to_text.setup || 'Speech recognition is not set up.');
      return;
    }
    try {
      startCapture(await ensureMicrophone());
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Microphone access was denied.');
    }
  };

  const backendLabel = (part: VoicePart | undefined) => (part?.ready ? part.backend ?? 'ready' : 'not set up');

  return (
    <section className="voice-operator" aria-label="Voice interaction">
      <div className="voice-operator-main">
        <div className="voice-state"><span className={`voice-dot ${handsFree ? 'voice-dot-live' : ''}`} />
          <span>{handsFree ? 'HANDS-FREE READY' : recording ? 'CAPTURING COMMAND' : busy ? 'PROCESSING VOICE' : 'VOICE CONTROL'}</span>
          <small>{providers === null
            ? providersError ? 'VOICE UNAVAILABLE' : 'CHECKING VOICE'
            : hearingReady ? `HEARING: ${backendLabel(providers.speech_to_text).toUpperCase()} · SPEAKING: ${backendLabel(providers.text_to_speech).toUpperCase()}` : 'VOICE NOT SET UP'}</small>
        </div>
        <div className="voice-controls">
          {!handsFree && <button type="button" className="voice-ptt" onClick={recording ? finishCapture : startPushToTalk} disabled={(busy && !recording) || !hearingReady} aria-label={recording ? 'Finish voice instruction' : 'Start push-to-talk voice instruction'}>{recording ? 'Finish' : 'Push to talk'}</button>}
          {handsFree
            ? <button type="button" className="voice-toggle voice-toggle-on" onClick={() => void stopHandsFree()}>Disable hands-free</button>
            : <button type="button" className="voice-toggle" onClick={() => void startHandsFree()} disabled={busy || !hearingReady || !wakeReady}>Enable hands-free</button>}
          {isAdmin && !wakeModel?.installed && <button type="button" className="voice-install" onClick={() => void installWakeModel()} disabled={busy}>Install wake model</button>}
          {isAdmin && wakeModel?.installed && !wakeModel.phrase_current && <button type="button" className="voice-install" onClick={() => void installWakeModel()} disabled={busy || handsFree}>Update wake phrase</button>}
          {isAdmin && voicebox?.connected && !voicebox.profile_configured && <button type="button" className="voice-install" onClick={() => void provisionVoice()} disabled={busy}>Set up Voicebox voice</button>}
          {speechActive && <button type="button" className="voice-interrupt" onClick={stopSpeech}>Interrupt speech</button>}
        </div>
      </div>
      <div className="voice-operator-details" role="status">
        <span>{providers === null
          ? providersError ?? 'Checking voice services…'
          : hearingReady
            ? speakingReady ? 'Voice ready: speak a command and JARV answers aloud' : `Voice ready; replies are shown, not spoken. ${providers.text_to_speech.setup ?? ''}`
            : providers.speech_to_text.setup ?? 'Speech recognition is not set up.'}</span>
        <span>{wakeModel?.installed
          ? wakeModel.phrase_current ? `Wake phrase: “${wakeModel.phrase}”` : 'Wake phrase update required'
          : wakeModel === null ? 'Checking the local wake phrase…' : 'Wake phrase model not installed'}</span>
        <span>Approvals are never taken by voice: approve on the Approvals page.</span>
        {handsFree && <span>The wake phrase is detected on JARV&apos;s own server. {localHearing ? 'Speech is also transcribed there.' : `Only what you say after the wake phrase is sent to ${providers?.speech_to_text.backend ?? 'the speech service'}.`}</span>}
      </div>
      {heard && <p className="voice-message"><strong>Heard:</strong> {heard}</p>}
      {message && <p className="voice-message" aria-live="polite">{message}</p>}
    </section>
  );
}
