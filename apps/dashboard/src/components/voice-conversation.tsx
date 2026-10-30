'use client';

import { useEffect, useRef, useState } from 'react';
import { apiClient } from '@/lib/api';
import type { MissionReport } from '@/components/voice-operator';

type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking';
type Phase = 'off' | 'connecting' | 'live';

/** POST /api/voice/live/session: a short-lived secret for one OpenAI Realtime conversation. */
export interface LiveSession { client_secret: string; model: string; voice: string; calls_url: string; expires_at?: number }

export interface ConversationLine { who: 'you' | 'jarv' | 'action'; text: string }

interface RealtimeEvent {
  type: string;
  transcript?: string;
  call_id?: string;
  name?: string;
  arguments?: string;
  error?: { message?: string };
}

interface Props {
  ready: boolean;
  setup?: string | null;
  /** Release the microphone from hands-free and stop any reply being played, before the conversation starts. */
  beforeStart: () => Promise<void>;
  onMission: (taskId: string) => Promise<MissionReport | null>;
  onStateChange: (state: VoiceState) => void;
}

const ACTION_LABELS: Record<string, string> = {
  get_status: 'Checked status',
  start_mission: 'Started a mission',
  get_mission: 'Checked a mission',
  cancel_mission: 'Cancelled a mission',
  list_workspaces: 'Listed workspaces',
};

/**
 * A live spoken conversation with JARV (OpenAI Realtime over WebRTC). The microphone streams to the model and
 * its voice plays back; it decides when Richard has finished speaking and stops when he talks over it. Each
 * action it takes is run by JARV's backend as the signed-in operator, and a mission it starts is followed to
 * its end and the outcome spoken.
 */
export function VoiceConversation({ ready, setup, beforeStart, onMission, onStateChange }: Props) {
  const [phase, setPhase] = useState<Phase>('off');
  const [lines, setLines] = useState<ConversationLine[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const peerRef = useRef<RTCPeerConnection | null>(null);
  const channelRef = useRef<RTCDataChannel | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const respondingRef = useRef(false);
  const replyQueuedRef = useRef(false);
  const mountedRef = useRef(true);

  const add = (line: ConversationLine) => setLines((current) => [...current.slice(-11), line]);

  const send = (event: Record<string, unknown>) => {
    const channel = channelRef.current;
    if (channel?.readyState === 'open') channel.send(JSON.stringify(event));
  };

  /** Ask for a reply now, or as soon as the one being spoken finishes (one response at a time). */
  const requestReply = (response?: Record<string, unknown>) => {
    if (respondingRef.current) {
      replyQueuedRef.current = true;
      return;
    }
    respondingRef.current = true;
    send(response ? { type: 'response.create', response } : { type: 'response.create' });
  };

  const stop = () => {
    channelRef.current?.close();
    channelRef.current = null;
    peerRef.current?.getSenders().forEach((sender) => sender.track?.stop());
    peerRef.current?.close();
    peerRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (audioRef.current) audioRef.current.srcObject = null;
    respondingRef.current = false;
    replyQueuedRef.current = false;
    if (mountedRef.current) {
      setPhase('off');
      onStateChange('idle');
    }
  };

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      stop();
    };
    // stop() only touches refs; it is safe to run once on unmount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const followMission = async (taskId: string) => {
    const report = await onMission(taskId);
    if (!report || !channelRef.current) return;
    const outcome = report.requires_approval || report.status === 'waiting_on_approval'
      ? `It is paused waiting for Richard's approval on the Approvals page. ${report.response_text || ''}`
      : `Status ${report.status}. ${report.response_text || ''}`;
    send({ type: 'conversation.item.create', item: { type: 'message', role: 'user', content: [
      { type: 'input_text', text: `[mission update] ${outcome.slice(0, 3000)}` }] } });
    requestReply();
  };

  const runTool = async (event: RealtimeEvent) => {
    const name = event.name || '';
    let args: Record<string, unknown> = {};
    try {
      args = JSON.parse(event.arguments || '{}') as Record<string, unknown>;
    } catch {
      args = {};
    }
    const response = await apiClient.post<Record<string, unknown>>('/api/voice/live/tool', { name, arguments: args });
    const output: Record<string, unknown> = response.error || !response.data
      ? { error: response.error || 'The action failed.' } : response.data;
    add({ who: 'action', text: 'error' in output ? `${ACTION_LABELS[name] ?? name}: ${String(output.error)}`
      : ACTION_LABELS[name] ?? name });
    send({ type: 'conversation.item.create', item: { type: 'function_call_output', call_id: event.call_id,
      output: JSON.stringify(output) } });
    requestReply();
    if (name === 'start_mission' && output.intent === 'mission' && typeof output.task_id === 'string') {
      void followMission(output.task_id);
    }
  };

  const handle = (event: RealtimeEvent) => {
    switch (event.type) {
      case 'input_audio_buffer.speech_started':
        onStateChange('listening');
        break;
      case 'input_audio_buffer.speech_stopped':
        onStateChange('thinking');
        break;
      case 'conversation.item.input_audio_transcription.completed':
        if (event.transcript?.trim()) add({ who: 'you', text: event.transcript.trim() });
        break;
      case 'response.created':
        respondingRef.current = true;
        break;
      case 'output_audio_buffer.started':
        onStateChange('speaking');
        break;
      case 'output_audio_buffer.stopped':
        onStateChange('listening');
        break;
      case 'response.output_audio_transcript.done':
        if (event.transcript?.trim()) add({ who: 'jarv', text: event.transcript.trim() });
        break;
      case 'response.function_call_arguments.done':
        void runTool(event);
        break;
      case 'response.done':
        respondingRef.current = false;
        if (replyQueuedRef.current) {
          replyQueuedRef.current = false;
          requestReply();
        }
        break;
      case 'error':
        respondingRef.current = false;
        setProblem(event.error?.message || 'The conversation service reported an error.');
        break;
      default:
        break;
    }
  };

  const start = async () => {
    setProblem(null);
    setPhase('connecting');
    try {
      await beforeStart();
      const session = await apiClient.post<LiveSession>('/api/voice/live/session');
      if (session.error || !session.data?.client_secret) throw new Error(session.error || 'The conversation could not start.');
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      streamRef.current = stream;
      const peer = new RTCPeerConnection();
      peerRef.current = peer;
      if (!audioRef.current) {
        audioRef.current = new Audio();
        audioRef.current.autoplay = true;
      }
      peer.ontrack = (track) => {
        if (audioRef.current) audioRef.current.srcObject = track.streams[0];
      };
      peer.onconnectionstatechange = () => {
        if (['failed', 'closed'].includes(peer.connectionState) && mountedRef.current && peerRef.current === peer) {
          setProblem('The conversation connection was lost.');
          stop();
        }
      };
      stream.getAudioTracks().forEach((track) => peer.addTrack(track, stream));
      const channel = peer.createDataChannel('oai-events');
      channelRef.current = channel;
      channel.onmessage = (message) => {
        try {
          handle(JSON.parse(String(message.data)) as RealtimeEvent);
        } catch {
          setProblem('The conversation service sent an unreadable event.');
        }
      };
      channel.onopen = () => {
        setPhase('live');
        onStateChange('listening');
        requestReply({ instructions: 'Greet Richard in one short sentence and ask what he needs.' });
      };
      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      const answer = await fetch(session.data.calls_url, {
        method: 'POST',
        body: offer.sdp,
        headers: { Authorization: `Bearer ${session.data.client_secret}`, 'Content-Type': 'application/sdp' },
      });
      if (!answer.ok) throw new Error(`The conversation service refused the connection (${answer.status}): ${(await answer.text()).slice(0, 200)}`);
      await peer.setRemoteDescription({ type: 'answer', sdp: await answer.text() });
    } catch (error) {
      stop();
      setProblem(error instanceof Error ? error.message : 'The conversation could not start.');
    }
  };

  return (
    <div className="voice-live">
      <div className="voice-live-head">
        <span className={`voice-dot ${phase === 'live' ? 'voice-dot-live' : ''}`} />
        <span>{phase === 'live' ? 'IN CONVERSATION — JUST TALK' : phase === 'connecting' ? 'CONNECTING…' : 'CONVERSATION'}</span>
        <div className="voice-controls">
          {phase === 'off'
            ? <button type="button" className="voice-toggle" onClick={() => void start()} disabled={!ready}>Talk with JARV</button>
            : <button type="button" className="voice-toggle voice-toggle-on" onClick={stop}>End conversation</button>}
        </div>
      </div>
      {!ready && <p className="voice-message">{setup || 'Live conversation is not set up.'}</p>}
      {problem && <p className="voice-message" role="alert">{problem}</p>}
      {lines.length > 0 && (
        <ol className="voice-live-lines" aria-live="polite">
          {lines.map((line, index) => (
            <li key={`${index}-${line.who}`} className={`voice-live-${line.who}`}>
              <strong>{line.who === 'you' ? 'You' : line.who === 'jarv' ? 'JARV' : '·'}</strong> {line.text}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
