'use client';

import { useCallback, useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';
import { followMission, type MissionResult } from '@/lib/missions';
import { VoiceOperator } from '@/components/voice-operator';

type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking';

interface HistoryItem { task_id: string; command: string; status: string; created_at: string; folder?: string | null }

const IN_FLIGHT = new Set(['running', 'queued', 'recovering', 'needs_continuation', 'waiting_on_approval']);
const POLL_MS = 4000;

/** "12s ago", "4 min ago": how long since a time, for a person glancing at the screen. */
export function ago(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return 'not yet';
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  return `${Math.round(seconds / 3600)} h ago`;
}

/**
 * Always on screen, on every dashboard page: the mission JARV is working on (what it did last and when it was
 * last heard from) and Talk with JARV. It lives in the dashboard frame, so moving between pages never ends the
 * conversation or loses the mission, and after a full reload both come back from JARV's own records.
 */
export function LiveMissionDock() {
  const [mission, setMission] = useState<MissionResult | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [talkOpen, setTalkOpen] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>('idle');
  const [, setTick] = useState(0);

  const refresh = useCallback(async () => {
    const history = await apiClient.get<HistoryItem[]>('/api/command/history?limit=10');
    if (history.error || !history.data) {
      setLoadError(history.error || 'Mission status is unavailable.');
      return;
    }
    setLoadError(null);
    // The mission being worked on; otherwise the latest one, so its outcome stays visible.
    const pick = history.data.find((item) => IN_FLIGHT.has(item.status)) ?? history.data[0];
    if (!pick) {
      setMission(null);
      return;
    }
    const detail = await apiClient.get<MissionResult>(`/api/command/tasks/${pick.task_id}`);
    if (detail.data) setMission(detail.data);
  }, []);

  useEffect(() => {
    void refresh();
    const poll = window.setInterval(() => void refresh(), POLL_MS);
    const clock = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => {
      window.clearInterval(poll);
      window.clearInterval(clock);
    };
  }, [refresh]);

  const working = mission ? IN_FLIGHT.has(mission.status) : false;
  const latest = mission?.events?.length ? mission.events[mission.events.length - 1] : null;
  const recent = mission?.events?.slice(-4).reverse() ?? [];

  return (
    <aside aria-label="Live mission and Talk with JARV" data-testid="live-mission-dock"
      className="fixed bottom-4 right-4 z-50 w-[min(26rem,calc(100vw-2rem))] rounded-xl border border-white/10 bg-[#0b1220]/95 text-[#E5E7EB] shadow-2xl backdrop-blur">
      <div className="p-3 space-y-2 text-sm">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[10px] tracking-widest text-cyan-300">
            {working ? 'MISSION IN PROGRESS' : mission ? 'LATEST MISSION' : 'NO MISSION YET'}
          </span>
          {mission && <span data-testid="dock-status"
            className={`rounded px-2 py-0.5 text-[11px] font-semibold ${working ? 'bg-cyan-500/20 text-cyan-200'
              : mission.status === 'completed' ? 'bg-emerald-500/20 text-emerald-200' : 'bg-amber-500/20 text-amber-200'}`}>
            {mission.status.replace(/_/g, ' ').toUpperCase()}</span>}
        </div>
        {loadError && <p className="text-amber-300 text-xs">{loadError}</p>}
        {mission && <>
          <p className="font-medium leading-snug" title={mission.command}>{mission.command.slice(0, 110)}{mission.command.length > 110 ? '…' : ''}</p>
          <p className="text-xs text-gray-400" data-testid="dock-identity">
            Mission {mission.task_id.slice(0, 8)}{mission.folder ? ` · ${mission.folder}` : ''}
            {working && <> · last heard from <b data-testid="dock-heartbeat">{ago(mission.heartbeat_at)}</b></>}
          </p>
          {latest && <p className="text-xs" data-testid="dock-latest">
            <span className="text-gray-400">{new Date(latest.at).toLocaleTimeString()} </span>
            <b>{latest.title}</b>{latest.message ? `: ${latest.message.slice(0, 140)}` : ''}</p>}
          {recent.length > 1 && <ol className="text-[11px] text-gray-400 space-y-0.5 border-l border-white/10 pl-2">
            {recent.slice(1).map((event, index) => <li key={`${event.at}-${index}`}>
              {new Date(event.at).toLocaleTimeString()} {event.title}</li>)}
          </ol>}
          {!working && mission.response_text && <p className="text-xs text-gray-300 max-h-24 overflow-y-auto whitespace-pre-wrap">
            {mission.response_text.slice(0, 600)}</p>}
        </>}
        <div className="flex gap-2 pt-1">
          <a href="/dashboard/command" className="rounded border border-white/15 px-2 py-1 text-xs hover:bg-white/10">Open missions</a>
          <a href="/dashboard/approvals" className="rounded border border-white/15 px-2 py-1 text-xs hover:bg-white/10">Approvals</a>
          <button type="button" onClick={() => setTalkOpen((open) => !open)} aria-expanded={talkOpen}
            className="ml-auto rounded bg-cyan-500/20 px-2 py-1 text-xs text-cyan-100 hover:bg-cyan-500/30">
            {talkOpen ? 'Hide conversation' : voiceState === 'idle' ? 'Talk with JARV' : `Talk with JARV · ${voiceState}`}
          </button>
        </div>
        {/* Always mounted, only hidden: hiding the panel or changing page never ends the conversation. */}
        <div hidden={!talkOpen} data-testid="dock-voice">
          <VoiceOperator onStateChange={setVoiceState} onMission={async (taskId) => {
            const followed = await followMission(taskId, { onUpdate: setMission });
            setMission(followed);
            return followed;
          }} />
        </div>
      </div>
    </aside>
  );
}
