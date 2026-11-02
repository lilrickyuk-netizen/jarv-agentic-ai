'use client';

import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { usePathname } from 'next/navigation';
import { followMission } from '@/lib/missions';
import { VoiceOperator } from '@/components/voice-operator';

/** Where Talk with JARV is shown: the Command Center's mission panel puts this element where it wants it. */
export const VOICE_SLOT_ID = 'voice-slot';

/**
 * Talk with JARV, kept connected while Richard moves between dashboard pages. It is mounted once in the dashboard
 * frame and its element is moved into the Command Center's slot whenever that page is open; on other pages it is
 * kept, unseen, so the conversation carries on. Moving an element does not restart it, so the call never drops.
 * Nothing is added to any page.
 */
export function PersistentVoice() {
  const pathname = usePathname();
  const [host, setHost] = useState<HTMLDivElement | null>(null);
  const parkingRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setHost(document.createElement('div'));
  }, []);

  useEffect(() => {
    if (!host || !parkingRef.current) return;
    const place = () => {
      const slot = document.getElementById(VOICE_SLOT_ID);
      const target = slot ?? parkingRef.current;
      if (target && host.parentElement !== target) target.appendChild(host);
    };
    place();
    // The page renders after the route changes; place again once its slot exists.
    const observer = new MutationObserver(place);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [host, pathname]);

  return (
    <>
      <div ref={parkingRef} hidden data-testid="voice-parking" />
      {host && createPortal(
        <VoiceOperator onStateChange={() => undefined} onMission={(taskId) => followMission(taskId)} />, host)}
    </>
  );
}
