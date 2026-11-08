'use client';

import { useEffect, useState } from 'react';
import { CockpitCore } from '@/components/cockpit-core';
import { IntelligenceField, type FieldState } from '@/components/intelligence-field';

export type FieldStyle = 'network' | 'swarm';
const KEY = 'jai.field-style';

function remembered(): FieldStyle {
  try {
    return window.localStorage.getItem(KEY) === 'swarm' ? 'swarm' : 'network';
  } catch {
    return 'network';
  }
}

/**
 * The Command Center's intelligence field: the network field (Upgrade 8) by default, or the earlier swarm of
 * lights. Richard's choice is remembered in this browser; both are driven by the same state and voice.
 */
export function CoreField({ state }: { state: FieldState }) {
  const [style, setStyle] = useState<FieldStyle>('network');

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
      {style === 'network' ? <IntelligenceField state={state} /> : <CockpitCore state={state} />}
      <div className="field-switch" role="group" aria-label="Intelligence field style">
        <button type="button" aria-pressed={style === 'network'} onClick={() => choose('network')}>Network</button>
        <button type="button" aria-pressed={style === 'swarm'} onClick={() => choose('swarm')}>Swarm</button>
      </div>
    </>
  );
}
