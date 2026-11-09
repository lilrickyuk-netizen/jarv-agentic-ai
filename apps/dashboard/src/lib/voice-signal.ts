'use client';

import { useSyncExternalStore } from 'react';

export type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking';

/**
 * What Talk with JAI is doing right now, and the audio of JAI's voice, shared with the rest of the dashboard.
 * The conversation lives in the dashboard frame (PersistentVoice), so the Command Center's intelligence field
 * reads it here: its state, and the live voice stream it listens to so it moves with JAI's speech.
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

/**
 * Whether the conversation is on (Command Center redesign, 9 November): the microphone in the chat bar starts and
 * ends it, so the bar needs to know when it is live and to ask the conversation, wherever it is mounted, to toggle.
 */
export type VoicePhase = 'off' | 'connecting' | 'live';
let phase: VoicePhase = 'off';
let phaseReady = false;
let toggler: (() => void) | null = null;

export function setVoicePhase(next: VoicePhase, ready: boolean) {
  if (next === phase && ready === phaseReady) return;
  phase = next;
  phaseReady = ready;
  emit();
}

export function getVoicePhase(): VoicePhase {
  return phase;
}

export function voiceReady(): boolean {
  return phaseReady;
}

/** The conversation registers how to start or end itself; the microphone button calls it. */
export function setVoiceToggle(next: (() => void) | null) {
  toggler = next;
}

export function toggleVoice() {
  toggler?.();
}

export function useVoicePhase(): VoicePhase {
  return useSyncExternalStore(subscribeVoice, getVoicePhase, () => 'off');
}

export function useVoiceReady(): boolean {
  return useSyncExternalStore(subscribeVoice, voiceReady, () => false);
}

/** Clearing the chat from the Command Center also clears what was said in the conversation. */
let clearer: (() => void) | null = null;

export function setVoiceClear(next: (() => void) | null) {
  clearer = next;
}

export function clearVoiceLines() {
  clearer?.();
}
