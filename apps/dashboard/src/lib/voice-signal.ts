'use client';

import { useSyncExternalStore } from 'react';

export type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking';

/**
 * What Talk with JARV is doing right now, and the audio of JARV's voice, shared with the rest of the dashboard.
 * The conversation lives in the dashboard frame (PersistentVoice), so the Command Center's intelligence field
 * reads it here: its state, and the live voice stream it listens to so it moves with JARV's speech.
 */
let state: VoiceState = 'idle';
let stream: MediaStream | null = null;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

export function setVoiceState(next: VoiceState) {
  if (next === state) return;
  state = next;
  emit();
}

export function setVoiceStream(next: MediaStream | null) {
  if (next === stream) return;
  stream = next;
  emit();
}

export function getVoiceState(): VoiceState {
  return state;
}

export function getVoiceStream(): MediaStream | null {
  return stream;
}

export function subscribeVoice(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useVoiceState(): VoiceState {
  return useSyncExternalStore(subscribeVoice, getVoiceState, () => 'idle');
}
