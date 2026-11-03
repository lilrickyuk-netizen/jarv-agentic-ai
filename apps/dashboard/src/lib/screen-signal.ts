'use client';

import { useSyncExternalStore } from 'react';

/** One section of what JAI puts on screen: a table (columns and rows), a list (items) or a block of text (code). */
export interface ScreenSection {
  heading?: string;
  columns?: string[];
  rows?: (string | number | null)[][];
  items?: string[];
  code?: string;
}

/** What JAI shows beside the intelligence field: built by JAI's backend from its own records. */
export interface ScreenCard {
  kind: string;
  title: string;
  subtitle?: string;
  link?: string;
  sections: ScreenSection[];
}

let card: ScreenCard | null = null;
const listeners = new Set<() => void>();

export function showCard(next: ScreenCard | null) {
  card = next;
  listeners.forEach((listener) => listener());
}

export function getCard(): ScreenCard | null {
  return card;
}

export function subscribeCard(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useScreenCard(): ScreenCard | null {
  return useSyncExternalStore(subscribeCard, getCard, () => null);
}
