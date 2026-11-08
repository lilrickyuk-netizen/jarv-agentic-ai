'use client';

import { useEffect, useState } from 'react';
import { CockpitCore } from '@/components/cockpit-core';
import { IntelligenceField, type FieldState } from '@/components/intelligence-field';
import { JarvisOrb } from '@/components/jarvis-orb';

export type FieldStyle = 'jarvis' | 'network' | 'swarm';
const KEY = 'jai.field-style';

function remembered(): FieldStyle {
  try {
    const saved = window.localStorage.getItem(KEY);
    return saved === 'swarm' || saved === 'network' ? saved : 'jarvis';
  } catch {
    return 'jarvis';
  }
}

/**
 * The Command Center's intelligence field: the JARVIS orb by default, or the network field or the earlier swarm of
 * lights. Richard's choice is remembered in this browser; all three are driven by the same state and voice.
 */
export function CoreField({ state }: { state: FieldState }) {
  const [style, setStyle] = useState<FieldStyle>('jarvis');

  useEffect(() => {
    setStyle(remembered());
  }, []);

  const choose = (next: FieldStyle) => {
    setStyle(next);
    try {
      window.localStorage.setItem(KEY, next);
    } catch {
      // Private windows can refuse storage; the choice still holds for this visit.
    }
  };

  return (
    <>
      {style === 'jarvis' ? <JarvisOrb state={state} />
        : style === 'network' ? <IntelligenceField state={state} /> : <CockpitCore state={state} />}
      <div className="field-switch" role="group" aria-label="Intelligence field style">
        <button type="button" aria-pressed={style === 'jarvis'} onClick={() => choose('jarvis')}>JARVIS</button>
        <button type="button" aria-pressed={style === 'network'} onClick={() => choose('network')}>Network</button>
        <button type="button" aria-pressed={style === 'swarm'} onClick={() => choose('swarm')}>Swarm</button>
      </div>
    </>
  );
}
