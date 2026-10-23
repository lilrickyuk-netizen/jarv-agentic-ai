'use client';

import { useEffect, useRef, useState } from 'react';
import { apiClient } from '@/lib/api';
import { getAccessToken } from '@/lib/auth';
import { env } from '@/lib/env';

type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking';

interface VoiceboxStatus {
  configured: boolean;
  connected: boolean;
  profile_configured: boolean;
  wake_word: string;
}

interface WakeModelStatus {
  installed: boolean;
  phrase_current: boolean;
  phrase: string;
  model: string;
  license: string;
}

interface VoiceCommandResult {
  response_text?: string;
  status?: string;
  requires_approval?: boolean;
}

interface Props {
  onCommand: (text: string) => Promise<VoiceCommandResult | null>;
  onStateChange: (state: VoiceState) => void;
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

export function extractWakeCommand(text: string): string | null {
  const phrase = /\b(?:jarv|j[\s-]*a[\s-]*r[\s-]*v|j[\s-]*r[\s-]*v|jarve)\b[\s,.;:!?-]*talk\s+to\s+me\b[\s,.;:!?-]*/i;
  const match = text.match(phrase);
  return match ? text.slice((match.index ?? 0) + match[0].length).trim() : null;
}

export function VoiceOperator({ onCommand, onStateChange }: Props) {
  const [voicebox, setVoicebox] = useState<VoiceboxStatus | null>(null);
  const [wakeModel, setWakeModel] = useState<WakeModelStatus | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [handsFree, setHandsFree] = useState(false);
  const handsFreeRef = useRef(false);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [speechActive, setSpeechActive] = useState(false);
  const [message, setMessage] = useState('');
  const onCommandRef = useRef(onCommand);
  const onStateChangeRef = useRef(onStateChange);
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
  const generationIdRef = useRef<string | null>(null);
  const speechAbortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);

  onCommandRef.current = onCommand;
  onStateChangeRef.current = onStateChange;

  const setVoiceState = (state: VoiceState) => onStateChangeRef.current(state);

  const loadStatus = async () => {
    const [voiceResponse, wakeResponse, userResponse] = await Promise.all([
      apiClient.get<VoiceboxStatus>('/api/voicebox/status'),
      apiClient.get<WakeModelStatus>('/api/voicebox/wake/status'),
      apiClient.get<{ is_admin?: boolean }>('/auth/me'),
    ]);
    if (voiceResponse.data) setVoicebox(voiceResponse.data);
    if (wakeResponse.data) setWakeModel(wakeResponse.data);
    if (userResponse.data) setIsAdmin(Boolean(userResponse.data.is_admin));
  };

  useEffect(() => {
    mountedRef.current = true;
    void loadStatus();
    return () => {
      mountedRef.current = false;
      void stopHandsFree(false);
      void stopSpeech();
    };
  }, []);

  const stopSpeech = async () => {
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
    const generationId = generationIdRef.current;
    generationIdRef.current = null;
    if (generationId) await apiClient.post(`/api/voicebox/generate/${generationId}/cancel`).catch(() => undefined);
    setSpeechActive(false);
  };

  const speak = async (text: string) => {
    if (!voicebox?.connected || !voicebox.profile_configured || !text.trim()) return;
    setBusy(true);
    setSpeechActive(true);
    setVoiceState('thinking');
    const generation = await apiClient.post<{ id: string }>('/api/voicebox/speak', { text: text.slice(0, 4000), language: 'en' });
    if (generation.error || !generation.data?.id) {
      setMessage(generation.error || 'Voicebox did not start speech generation.');
      setBusy(false);
      setSpeechActive(false);
      return;
    }

    const generationId = generation.data.id;
    generationIdRef.current = generationId;
    const abortController = new AbortController();
    speechAbortRef.current = abortController;
    const token = getAccessToken();
    try {
      const response = await fetch(`/api/backend/api/voicebox/generate/${generationId}/status`, {
        headers: { Accept: 'text/event-stream', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        signal: abortController.signal,
      });
      if (!response.ok || !response.body) throw new Error('Voicebox status stream is unavailable.');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let pending = '';
      let completed = false;
      while (!completed) {
        const { value, done } = await reader.read();
        if (done) throw new Error('Voicebox status stream ended before speech completed.');
        pending += decoder.decode(value, { stream: true });
        const blocks = pending.split('\n\n');
        pending = blocks.pop() || '';
        for (const block of blocks) {
          const dataLine = block.split('\n').find((line) => line.startsWith('data:'));
          if (!dataLine) continue;
          const payload = JSON.parse(dataLine.slice(5).trim()) as { status?: string; error?: string };
          if (payload.status === 'failed' || payload.status === 'not_found') throw new Error(payload.error || 'Voicebox speech generation failed.');
          if (payload.status === 'completed') completed = true;
        }
      }
      const audioResponse = await fetch(`/api/backend/api/voicebox/audio/${generationId}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: abortController.signal,
      });
      if (!audioResponse.ok) throw new Error('Generated audio could not be retrieved.');
      const audioUrl = URL.createObjectURL(await audioResponse.blob());
      audioUrlRef.current = audioUrl;
      const audio = new Audio(audioUrl);
      audioRef.current = audio;
      setVoiceState('speaking');
      await audio.play();
      await new Promise<void>((resolve, reject) => {
        audio.onended = () => resolve();
        audio.onerror = () => reject(new Error('Generated audio could not be played.'));
      });
    } catch (error) {
      if (!abortController.signal.aborted) setMessage(error instanceof Error ? error.message : 'Spoken response failed.');
    } finally {
      if (generationIdRef.current === generationId) generationIdRef.current = null;
      if (speechAbortRef.current === abortController) speechAbortRef.current = null;
      if (audioRef.current) audioRef.current = null;
      if (audioUrlRef.current) {
        URL.revokeObjectURL(audioUrlRef.current);
        audioUrlRef.current = null;
      }
      setSpeechActive(false);
      setBusy(false);
      if (mountedRef.current) setVoiceState(handsFreeRef.current ? 'listening' : 'idle');
    }
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
    const chunks = pcmCommandRef.current;
    pcmCommandRef.current = [];
    const totalSamples = chunks.reduce((total, chunk) => total + chunk.length, 0);
    if (totalSamples < 16000 * 0.35) {
      setVoiceState(handsFreeRef.current ? 'listening' : 'idle');
      return;
    }
    const samples = new Float32Array(totalSamples);
    let offset = 0;
    chunks.forEach((chunk) => {
      samples.set(chunk, offset);
      offset += chunk.length;
    });
    void processCapture(pcmToWav(samples, 16000), 'voice-command.wav');
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
    setMessage('Wake phrase detected. Listening for your instruction…');
    setVoiceState('listening');
    captureTimerRef.current = window.setTimeout(finishPcmCapture, 30000);
  };

  const startCapture = (stream: MediaStream) => {
    if (recordingRef.current || processingRef.current) return;
    const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus']
      .find((type) => MediaRecorder.isTypeSupported(type));
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    captureChunksRef.current = [];
    lastVoiceAtRef.current = Date.now();
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
      const blob = new Blob(captureChunksRef.current, { type: recorder.mimeType || 'audio/webm' });
      captureChunksRef.current = [];
      if (blob.size < 1500) {
        processingRef.current = false;
        setVoiceState(handsFree ? 'listening' : 'idle');
        return;
      }
      void processCapture(blob);
    };
    recorder.start(250);
    recorderRef.current = recorder;
    recordingRef.current = true;
    setRecording(true);
    setMessage('Listening for your instruction…');
    setVoiceState('listening');
    captureTimerRef.current = window.setTimeout(finishCapture, 30000);
  };

  const processCapture = async (blob: Blob, filename = 'voice-command.webm') => {
    processingRef.current = true;
    setBusy(true);
    setVoiceState('thinking');
    try {
      const form = new FormData();
      form.append('file', new File([blob], filename, { type: blob.type || 'audio/webm' }));
      form.append('language', 'en');
      const transcription = await apiClient.upload<{ text: string }>('/api/voicebox/transcribe', form);
      if (transcription.error || !transcription.data?.text) throw new Error(transcription.error || 'No speech was recognized.');
      const command = extractWakeCommand(transcription.data.text)
        ?? transcription.data.text.replace(/^\s*jarv[, ]+talk to me[\s,.;:!?-]*/i, '').trim();
      if (!command) throw new Error('Wake phrase detected, but no instruction was heard.');
      setMessage(`Heard: ${command}`);
      const result = await onCommandRef.current(command);
      if (result?.response_text) await speak(result.response_text);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Voice command failed.');
    } finally {
      processingRef.current = false;
      setBusy(false);
      if (mountedRef.current) setVoiceState(handsFreeRef.current ? 'listening' : 'idle');
    }
  };

  const processWakePhrase = async (frames: Float32Array[]) => {
    if (processingRef.current || recordingRef.current || !handsFreeRef.current) return;
    const samples = mergeAudioFrames(frames);
    if (samples.length < 16000 * 0.35) return;

    processingRef.current = true;
    setBusy(true);
    setVoiceState('thinking');
    setMessage('Checking speech locally…');
    let listenForInstruction = false;
    try {
      const form = new FormData();
      form.append('file', new File([pcmToWav(samples, 16000)], 'wake-check.wav', { type: 'audio/wav' }));
      form.append('language', 'en');
      const transcription = await apiClient.upload<{ text: string }>('/api/voicebox/transcribe', form);
      if (transcription.error) {
        const detail = transcription.error.toLowerCase();
        setMessage(detail.includes('whisper') && detail.includes('download')
          ? 'Local speech recognition is starting. Say the wake phrase again shortly.'
          : transcription.error);
        return;
      }
      const transcript = transcription.data?.text?.trim();
      if (!transcript) return;
      const command = extractWakeCommand(transcript);
      if (command === null) {
        const wakeCue = /talk|jarv|j[\s-]*r[\s-]*v/i.test(transcript);
        setMessage(wakeCue
          ? `Heard “${transcript.slice(0, 120)}”; wake phrase not recognized.`
          : 'Speech heard, but the wake phrase was not recognized.');
        return;
      }
      if (!command) {
        listenForInstruction = true;
        setMessage('Wake phrase detected. Responding…');
        await speak("I'm listening.");
        return;
      }
      setMessage(`Heard: ${command}`);
      const result = await onCommandRef.current(command);
      if (result?.response_text) await speak(result.response_text);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Local wake recognition failed.');
    } finally {
      processingRef.current = false;
      setBusy(false);
      if (listenForInstruction && handsFreeRef.current) {
        startPcmCapture();
      } else if (mountedRef.current) {
        setVoiceState(handsFreeRef.current ? 'listening' : 'idle');
      }
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
    if (!voicebox?.connected || !voicebox.profile_configured) {
      setMessage('Voicebox must be connected with a speech profile before hands-free mode can start.');
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
      const wsUrl = parseSocketUrl();
      const socket = new WebSocket(wsUrl, ['jarv-wake', `ticket.${ticketResponse.data.ticket}`]);
      socket.binaryType = 'arraybuffer';
      wakeSocketRef.current = socket;
      socket.onmessage = async (event) => {
        try {
          const payload = JSON.parse(String(event.data)) as { type?: string };
          if (payload.type === 'wake') {
            if (recordingRef.current || processingRef.current) return;
            if (audioRef.current || generationIdRef.current) await stopSpeech();
            wakeProbeActiveRef.current = false;
            wakeProbeFramesRef.current = [];
            setMessage('Wake phrase detected. Responding…');
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
          if (!processingRef.current) {
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
        if (socket.readyState !== WebSocket.OPEN) return;
        socket.send(samples.buffer);
      };
      source.connect(processor);
      processor.connect(context.destination);
      socket.addEventListener('message', (event) => {
        if (typeof event.data === 'string' && event.data.includes('"ready"')) {
          handsFreeRef.current = true;
          setHandsFree(true);
          setMessage(`Wake phrase ready. Say “${wakeModel?.phrase || 'JARV, talk to me.'}”.`);
          setVoiceState('listening');
          setBusy(false);
        }
      }, { once: true });
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
  };

  const provisionVoice = async () => {
    setBusy(true);
    setMessage('Creating JARV’s local speech profile…');
    const response = await apiClient.post<{ profile_id: string; voice: string }>('/api/voicebox/profile/provision');
    setBusy(false);
    if (response.error) {
      setMessage(response.error);
      return;
    }
    await loadStatus();
    setMessage('JARV’s British male speech profile is ready.');
  };

  const startPushToTalk = async () => {
    if (!voicebox?.connected) {
      setMessage('Voicebox is not connected. Configure the local speech service before using voice input.');
      return;
    }
    try {
      const stream = await ensureMicrophone();
      startCapture(stream);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Microphone access was denied.');
    }
  };

  return (
    <section className="voice-operator" aria-label="Voice interaction">
      <div className="voice-operator-main">
        <div className="voice-state"><span className={`voice-dot ${handsFree ? 'voice-dot-live' : ''}`} />
          <span>{handsFree ? 'HANDS-FREE READY' : recording ? 'CAPTURING COMMAND' : busy ? 'PROCESSING VOICE' : 'VOICE CONTROL'}</span>
          <small>{voicebox === null
            ? 'CONNECTING TO VOICEBOX'
            : voicebox.connected && voicebox.profile_configured ? 'VOICEBOX ONLINE' : 'VOICEBOX UNAVAILABLE'}</small>
        </div>
        <div className="voice-controls">
          {!handsFree && <button type="button" className="voice-ptt" onClick={recording ? finishCapture : startPushToTalk} disabled={busy || !voicebox?.connected} aria-label={recording ? 'Finish voice instruction' : 'Start push-to-talk voice instruction'}>{recording ? 'Finish' : 'Push to talk'}</button>}
          {handsFree
            ? <button type="button" className="voice-toggle voice-toggle-on" onClick={() => void stopHandsFree()}>Disable hands-free</button>
            : <button type="button" className="voice-toggle" onClick={() => void startHandsFree()} disabled={busy || !voicebox?.connected || !voicebox.profile_configured || !wakeModel?.installed || !wakeModel.phrase_current}>Enable hands-free</button>}
          {isAdmin && !wakeModel?.installed && <button type="button" className="voice-install" onClick={() => void installWakeModel()} disabled={busy}>Install wake model</button>}
          {isAdmin && wakeModel?.installed && !wakeModel.phrase_current && <button type="button" className="voice-install" onClick={() => void installWakeModel()} disabled={busy || handsFree}>Update wake phrase</button>}
          {isAdmin && voicebox?.connected && !voicebox.profile_configured && <button type="button" className="voice-install" onClick={() => void provisionVoice()} disabled={busy}>Set up JARV voice</button>}
          {speechActive && <button type="button" className="voice-interrupt" onClick={() => void stopSpeech()}>Interrupt speech</button>}
        </div>
      </div>
      <div className="voice-operator-details" role="status">
        <span>{voicebox === null
          ? 'Checking the local speech service…'
          : voicebox.connected && voicebox.profile_configured
            ? 'Local speech service ready'
            : voicebox.configured
              ? 'Voicebox is unreachable or has no speech profile'
              : 'Set VOICEBOX_BASE_URL and VOICEBOX_PROFILE_ID to enable speech'}</span>
        <span>{wakeModel?.installed
          ? wakeModel.phrase_current ? `Wake phrase: “${wakeModel.phrase}”` : 'Wake phrase update required'
          : wakeModel === null ? 'Checking the local wake phrase…' : 'Wake phrase model not installed'}</span>
        {handsFree && <span>Wake detection and speech recognition run on your self-hosted JARV services. Temporary clips are deleted after processing; wake-cue transcripts appear briefly on screen and are not saved.</span>}
      </div>
      {message && <p className="voice-message" aria-live="polite">{message}</p>}
    </section>
  );
}
