'use client';

import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';
import { VoiceConversation } from '@/components/voice-conversation';

type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking';

interface VoicePart { backend?: string | null; ready: boolean; setup?: string | null }

export interface VoiceProviders {
  /** Live spoken conversation (OpenAI Realtime), connected to JAI's missions, memory and approvals. */
  live?: VoicePart;
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

/**
 * Talking with JAI: one live spoken conversation. JAI hears, answers and acts through its own backend
 * (missions, memory, workspaces and what waits for approval). Approvals are never taken by voice.
 */
export function VoiceOperator({ onMission, onStateChange }: Props) {
  const [providers, setProviders] = useState<VoiceProviders | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    apiClient.get<VoiceProviders>('/api/voice/providers').then((response) => {
      if (!active) return;
      if (response.data) setProviders(response.data);
      else setError(response.error || 'Voice status is unavailable.');
    });
    return () => {
      active = false;
    };
  }, []);

  return (
    <section className="voice-operator" aria-label="Voice interaction">
      <VoiceConversation ready={Boolean(providers?.live?.ready)} setup={providers?.live?.setup ?? error ?? undefined}
        beforeStart={async () => undefined} onMission={onMission} onStateChange={onStateChange} />
      <div className="voice-operator-details" role="status">
        <span>{providers === null
          ? error ?? 'Checking voice…'
          : providers.live?.ready ? 'Talk with JAI: it can check status, start and carry on missions, search its memory and read your workspaces.'
            : providers.live?.setup ?? 'Live conversation is not set up.'}</span>
        <span>Approvals are never taken by voice: approve on the Approvals page.</span>
      </div>
    </section>
  );
}
