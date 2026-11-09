'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { JarvisOrb } from '@/components/jarvis-orb';
import { JarvMark } from '@/components/jarv-mark';
import { JaiDisplay } from '@/components/jai-display';
import { ServiceSwitches } from '@/components/service-switches';
import { apiClient, HealthResponse } from '@/lib/api';
import { followMission, runMission } from '@/lib/missions';
import { VOICE_SLOT_ID } from '@/components/persistent-voice';
import { WorkingAgents, type WorkingMission } from '@/components/working-agents';
import { clearTokens, getAccessToken } from '@/lib/auth';
import { clearVoiceLines, toggleVoice, useVoicePhase, useVoiceReady, useVoiceState } from '@/lib/voice-signal';

type CockpitState = 'idle' | 'listening' | 'thinking' | 'planning' | 'executing' | 'speaking' | 'approval' | 'completed' | 'failed' | 'recovery';
type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking';

interface FeedItem {
  id: string;
  item_type: string;
  severity: string;
  title: string;
  message: string;
  related_task_id: string | null;
  created_at: string;
}

interface Task {
  id: string;
  title: string;
  task_type: string;
  status: string;
  created_at: string;
  completed_at: string | null;
}

interface ApprovalStats {
  pending_approvals: number;
  total_approvals: number;
}

interface CommandResult {
  task_id: string;
  command: string;
  status: string;
  requires_approval: boolean;
  response_text: string;
  plan_steps: string[];
  selected_agents: string[];
  provider: string | null;
  model: string | null;
  execution_time: number;
  tokens_used: number;
  approval_reason?: string | null;
  error?: string | null;
}

function deriveState(input: {
  loadingCommand: boolean;
  listening: boolean;
  result: CommandResult | null;
  tasks: Task[];
  feed: FeedItem[];
  pendingApprovals: number | null;
  voiceState: VoiceState;
}): CockpitState {
  if (input.voiceState !== 'idle') return input.voiceState;
  if (input.listening) return 'listening';
  if (input.loadingCommand) return 'thinking';
  if (input.result?.requires_approval || input.result?.status === 'blocked' || (input.pendingApprovals ?? 0) > 0) return 'approval';
  if (input.result?.status === 'failed') return 'failed';
  if (input.tasks.some((task) => ['running', 'in_progress', 'executing'].includes(task.status))) return 'executing';
  if (input.result?.status === 'planning') return 'planning';
  if (input.result?.status === 'speaking') return 'speaking';
  if (input.feed[0]?.severity === 'error') return 'recovery';
  if (input.result?.status === 'completed') return 'completed';
  return 'idle';
}

const IN_FLIGHT = new Set(['running', 'queued', 'recovering', 'needs_continuation', 'waiting_on_approval']);

export default function CommandCenterPage() {
  const router = useRouter();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [approvalStats, setApprovalStats] = useState<ApprovalStats | null>(null);
  const [working, setWorking] = useState<WorkingMission[]>([]);
  const [model, setModel] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [command, setCommand] = useState('');
  const [sent, setSent] = useState<string | null>(null);
  const [commandResult, setCommandResult] = useState<CommandResult | null>(null);
  const [commandError, setCommandError] = useState<string | null>(null);
  const [commandLoading, setCommandLoading] = useState(false);
  const [clock, setClock] = useState('');
  // The chat is hidden unless Richard opens it (9 November); a reply while it is closed lights the chat button.
  const [chatOpen, setChatOpen] = useState(false);
  const [unseen, setUnseen] = useState(false);
  // Talk with JAI is kept connected by the dashboard frame (PersistentVoice) and shown in the chat dock's slot; the
  // microphone in the chat bar starts and ends it, and its state reaches the orb.
  const voiceState: VoiceState = useVoiceState();
  const voicePhase = useVoicePhase();
  const voiceReady = useVoiceReady();

  const refresh = useCallback(async () => {
    const [healthResponse, tasksResponse, feedResponse, approvalsResponse, workingResponse] = await Promise.all([
      apiClient.checkHealth(),
      apiClient.get<Task[]>('/api/tasks/list'),
      apiClient.get<FeedItem[]>('/api/operations-feed/list?limit=12'),
      apiClient.get<ApprovalStats>('/api/approvals/stats'),
      apiClient.get<WorkingMission[]>('/api/command/working'),
    ]);
    if (healthResponse.data) setHealth(healthResponse.data);
    if (tasksResponse.data) setTasks(tasksResponse.data);
    if (feedResponse.data) setFeed(feedResponse.data);
    if (approvalsResponse.data) setApprovalStats(approvalsResponse.data);
    if (workingResponse.data) setWorking(workingResponse.data);
    const errors = [healthResponse, tasksResponse, feedResponse, approvalsResponse].filter((response) => response.error);
    setRefreshError(errors.length ? errors.map((response) => response.error).join(' · ') : null);
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => void refresh(), 8000);
    return () => window.clearInterval(interval);
  }, [refresh]);

  useEffect(() => {
    void apiClient.get<{ model?: string }>('/api/command/info').then((info) => setModel(info.data?.model ?? null));
    const tick = () => setClock(new Date().toLocaleTimeString('en-GB'));
    tick();
    const interval = window.setInterval(tick, 1000);
    return () => window.clearInterval(interval);
  }, []);

  // Coming back to this page (or reloading it) picks up the mission JAI is working on: missions run in JAI's
  // worker, not in this page.
  useEffect(() => {
    const stop = new AbortController();
    void (async () => {
      const history = await apiClient.get<{ task_id: string; status: string; command: string }[]>('/api/command/history?limit=10');
      const current = history.data?.find((item) => IN_FLIGHT.has(item.status));
      if (!current || stop.signal.aborted) return;
      setSent(current.command);
      try {
        const mission = await followMission(current.task_id, { onUpdate: setCommandResult, signal: stop.signal });
        setCommandResult(mission);
      } catch {
        // Stopped following (left the page); the mission carries on in JAI.
      }
    })();
    return () => stop.abort();
  }, []);

  const sendCommand = async (text: string): Promise<CommandResult | null> => {
    const trimmed = text.trim();
    if (!trimmed) return null;
    setCommandLoading(true);
    setCommandError(null);
    setCommandResult(null);
    setSent(trimmed);
    setCommand('');
    try {
      const mission = await runMission(trimmed, { onUpdate: setCommandResult });
      setCommandResult(mission);
      void refresh();
      return mission;
    } catch (error) {
      setCommandError(error instanceof Error ? error.message : 'Command could not be sent');
    } finally {
      setCommandLoading(false);
    }
    return null;
  };

  const handleLogout = async () => {
    try {
      const accessToken = getAccessToken();
      if (accessToken) await apiClient.post('/auth/logout', { access_token: accessToken });
    } finally {
      clearTokens();
      router.push('/login');
    }
  };

  const state = deriveState({ loadingCommand: commandLoading, listening: voiceState === 'listening', result: commandResult, tasks, feed, pendingApprovals: approvalStats?.pending_approvals ?? null, voiceState });
  const healthOk = health?.status === 'healthy';
  const current = working[0];
  const waiting = approvalStats?.pending_approvals ?? 0;
  const reply = commandError || commandResult?.response_text || commandResult?.error || (commandResult ? 'Mission accepted.' : null);
  useEffect(() => {
    if (reply && !chatOpen) setUnseen(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reply]);
  const openChat = (open: boolean) => {
    setChatOpen(open);
    if (open) setUnseen(false);
  };
  const clearChat = () => {
    setSent(null);
    setCommandResult(null);
    setCommandError(null);
    clearVoiceLines();
  };
  const statusLine = current ? `${state.toUpperCase()} · ${current.title}` : state === 'idle' ? null : state.toUpperCase();

  return (
    <main className="jai-overview">
      <aside className="ov-side" aria-label="Main navigation">
        <a href="/dashboard" className="ov-brand" aria-label="JAI command center">
          <JarvMark size={30} /><span><strong>JAI</strong><small>INTELLIGENCE SYSTEM</small></span>
        </a>
        <nav>
          <span className="side-label">COMMAND</span>
          <a className="ov-link is-active" href="/dashboard">Overview</a>
          <a className="ov-link" href="/dashboard/command">Missions</a>
          <a className="ov-link" href="/dashboard/agents">Agents</a>
          <a className="ov-link" href="/dashboard/swarm">Swarm</a>
          <a className="ov-link" href="/dashboard/tasks">Tasks</a>
          <span className="side-label">OPERATIONS</span>
          <a className="ov-link" href="/dashboard/live-operations">Live operations</a>
          <a className="ov-link" href="/dashboard/approvals">Approvals{waiting > 0 && <b className="ov-count">{waiting}</b>}</a>
          <a className="ov-link" href="/dashboard/workspaces">Workspaces</a>
          <span className="side-label">COMPANY</span>
          <a className="ov-link" href="/dashboard/company-operations">Company</a>
          <a className="ov-link" href="/dashboard/business">Business</a>
          <a className="ov-link" href="/dashboard/revenue-operations">Revenue</a>
          <a className="ov-link" href="/dashboard/support">Support</a>
          <a className="ov-link" href="/dashboard/marketing">Growth</a>
          <a className="ov-link" href="/dashboard/infrastructure">Infrastructure</a>
        </nav>
        <ServiceSwitches compact />
        <div className="ov-health"><span className={`ov-dot${healthOk ? ' is-live' : ''}`} />{healthOk ? 'All systems online' : loading ? 'Connecting' : 'Backend degraded'}<small>{health?.version ? `v${health.version}` : ''}</small></div>
      </aside>

      <section className="ov-main">
        <header className="ov-top">
          <div className="ov-crumbs">Command / <b>Overview</b></div>
          <div className="ov-actions">
            {waiting > 0 && <a className="ov-chip is-warn" href="/dashboard/approvals">{waiting} waiting for you</a>}
            {model && <span className="ov-chip"><span className="ov-dot is-live" />{model.replace('claude-', '').replace(/-/g, ' ')}</span>}
            <span className="ov-chip ov-mono">{clock}</span>
            <button className="ov-btn" onClick={() => void refresh()} aria-label="Refresh dashboard data">Refresh</button>
            <button className="ov-btn" onClick={handleLogout}>Sign out</button>
          </div>
        </header>

        <div className="ov-stage">
          <div className="ov-orb" aria-label="JAI's intelligence field">
            <JarvisOrb state={state} />
            <WorkingAgents missions={working} />
          </div>
          {statusLine && <p className="ov-status">{statusLine}</p>}
          {refreshError && <p className="ov-alert" role="status">Some live data is unavailable: {refreshError}</p>}
          <div className="ov-screen"><JaiDisplay /></div>
        </div>

        <footer className="ov-dock">
          {/* Kept mounted while closed, so a live conversation carries on unseen. */}
          <div className="ov-chat" hidden={!chatOpen} aria-label="Chat with JAI">
            <div className="ov-chat-head">
              <button type="button" className="ov-text-btn" onClick={clearChat}>Clear</button>
              <button type="button" className="ov-text-btn" onClick={() => openChat(false)} aria-label="Close the chat">×</button>
            </div>
            <div className="ov-lines" aria-live="polite">
              {sent && <p><span>›</span>{sent}</p>}
              {reply && <p className={`is-jai${commandResult?.requires_approval ? ' is-warn' : ''}`}><span>›</span>{commandResult?.requires_approval ? `${commandResult.approval_reason ?? 'Approval needed'} ` : ''}{reply}</p>}
              <div id={VOICE_SLOT_ID} className="ov-voice" />
            </div>
          </div>
          <form className="ov-composer" onSubmit={(event) => { event.preventDefault(); void sendCommand(command); }}>
            <textarea aria-label="Message JAI" value={command} rows={1} disabled={commandLoading}
              onChange={(event) => setCommand(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void sendCommand(command); } }} />
            <button type="button" className={`ov-icon ov-chat-btn${chatOpen ? ' is-open' : ''}${unseen ? ' has-new' : ''}`}
              onClick={() => openChat(!chatOpen)} aria-pressed={chatOpen} aria-label={chatOpen ? 'Hide the chat' : 'Show the chat'}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" /></svg>
            </button>
            <button type="button" className={`ov-icon ov-mic${voicePhase !== 'off' ? ' is-live' : ''}`} onClick={toggleVoice}
              disabled={!voiceReady && voicePhase === 'off'} aria-pressed={voicePhase !== 'off'}
              aria-label={voicePhase === 'off' ? 'Talk with JAI' : 'End conversation'}>
              <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
            </button>
            <button type="submit" className="ov-icon ov-send" disabled={commandLoading || !command.trim()} aria-label="Send">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7" /></svg>
            </button>
          </form>
        </footer>
      </section>
    </main>
  );
}
