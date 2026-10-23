'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { CockpitCore } from '@/components/cockpit-core';
import { VoiceOperator } from '@/components/voice-operator';
import { apiClient, HealthResponse } from '@/lib/api';
import { runMission } from '@/lib/missions';
import { clearTokens, getAccessToken } from '@/lib/auth';

type CockpitState = 'idle' | 'listening' | 'thinking' | 'planning' | 'executing' | 'speaking' | 'approval' | 'completed' | 'failed' | 'recovery';
type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking';

interface Agent {
  name: string;
  role: string;
  category: string;
  required_authority_level: number;
  is_implemented: boolean;
}

interface AgentStats {
  total_required: number;
  total_registered: number;
  implemented: number;
  unimplemented: number;
  completion_percentage: number;
}

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

interface MemoryStats {
  total_memories: number;
  permanent_memories: number;
  temporary_memories: number;
}

interface SwarmRun {
  id: string;
  status: string;
  total_cost_usd: number;
  total_tokens_used: number;
  active_sub_agents: number;
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

export default function CommandCenterPage() {
  const router = useRouter();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentStats, setAgentStats] = useState<AgentStats | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [approvalStats, setApprovalStats] = useState<ApprovalStats | null>(null);
  const [memoryStats, setMemoryStats] = useState<MemoryStats | null>(null);
  const [swarmRuns, setSwarmRuns] = useState<SwarmRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [command, setCommand] = useState('');
  const [commandResult, setCommandResult] = useState<CommandResult | null>(null);
  const [commandError, setCommandError] = useState<string | null>(null);
  const [commandLoading, setCommandLoading] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>('idle');

  const refresh = useCallback(async () => {
    const [healthResponse, agentsResponse, statsResponse, tasksResponse, feedResponse, approvalsResponse, memoryResponse, swarmResponse] = await Promise.all([
      apiClient.checkHealth(),
      apiClient.get<Agent[]>('/api/agents/list'),
      apiClient.get<AgentStats>('/api/agents/stats'),
      apiClient.get<Task[]>('/api/tasks/list'),
      apiClient.get<FeedItem[]>('/api/operations-feed/list?limit=12'),
      apiClient.get<ApprovalStats>('/api/approvals/stats'),
      apiClient.get<MemoryStats>('/api/memory/stats'),
      apiClient.get<SwarmRun[]>('/api/swarm/runs'),
    ]);
    if (healthResponse.data) setHealth(healthResponse.data);
    if (agentsResponse.data) setAgents(agentsResponse.data);
    if (statsResponse.data) setAgentStats(statsResponse.data);
    if (tasksResponse.data) setTasks(tasksResponse.data);
    if (feedResponse.data) setFeed(feedResponse.data);
    if (approvalsResponse.data) setApprovalStats(approvalsResponse.data);
    if (memoryResponse.data) setMemoryStats(memoryResponse.data);
    if (swarmResponse.data) setSwarmRuns(swarmResponse.data);
    const errors = [healthResponse, agentsResponse, statsResponse, tasksResponse, feedResponse, approvalsResponse, memoryResponse, swarmResponse].filter((response) => response.error);
    setRefreshError(errors.length ? errors.map((response) => response.error).join(' · ') : null);
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => void refresh(), 15000);
    return () => window.clearInterval(interval);
  }, [refresh]);

  const sendCommand = async (text: string): Promise<CommandResult | null> => {
    const trimmed = text.trim();
    if (!trimmed) return null;
    setCommandLoading(true);
    setCommandError(null);
    setCommandResult(null);
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
  const activeTasks = tasks.filter((task) => ['running', 'queued', 'recovering', 'needs_continuation', 'pending'].includes(task.status));
  const implementedAgents = agents.filter((agent) => agent.is_implemented);
  const activeSwarmRuns = swarmRuns.filter((run) => run.status === 'running');
  const swarmSpend = swarmRuns.reduce((total, run) => total + (Number.isFinite(run.total_cost_usd) ? run.total_cost_usd : 0), 0);
  const activeSubAgents = swarmRuns.reduce((total, run) => total + (Number.isFinite(run.active_sub_agents) ? run.active_sub_agents : 0), 0);
  const healthOk = health?.status === 'healthy';

  return (
    <main className="cockpit min-h-screen text-[#E5E7EB]">
      <div className="cockpit-grid" aria-hidden="true" />
      <header className="cockpit-header">
        <a href="/dashboard" className="cockpit-brand" aria-label="JARV command center">
          <span className="brand-mark">J</span><span><strong>JARV</strong><small>INTELLIGENCE SYSTEM</small></span>
        </a>
        <div className="header-center"><span className={`status-dot ${healthOk ? 'is-live' : ''}`} />{healthOk ? 'SYSTEM ONLINE' : loading ? 'CONNECTING' : 'BACKEND DEGRADED'}</div>
        <div className="header-actions">
          <span className="header-clock">{health?.timestamp ? new Date(health.timestamp).toLocaleTimeString() : 'LOCAL SESSION'}</span>
          <button className="quiet-button" onClick={() => void refresh()} aria-label="Refresh dashboard data" title="Refresh data">↻</button>
          <button className="quiet-button" onClick={handleLogout}>Sign out</button>
        </div>
      </header>

      <div className="cockpit-layout">
        <nav className="cockpit-nav" aria-label="Main navigation">
          <span className="nav-label">COMMAND</span>
          <a className="nav-link active" href="/dashboard">Overview</a>
          <a className="nav-link" href="/dashboard/command">Missions</a>
          <a className="nav-link" href="/dashboard/agents">Agents</a>
          <a className="nav-link" href="/dashboard/swarm">Swarm</a>
          <a className="nav-link" href="/dashboard/tasks">Tasks</a>
          <span className="nav-label nav-label-spaced">OPERATIONS</span>
          <a className="nav-link" href="/dashboard/live-operations">Live operations</a>
          <a className="nav-link" href="/dashboard/approvals">Approvals</a>
          <a className="nav-link" href="/dashboard/workspaces">Workspaces</a>
          <div className="nav-footer"><span className={`status-dot ${healthOk ? 'is-live' : ''}`} /><span>{health?.service ?? 'API'}<small>{health?.version ? `v${health.version}` : 'STATUS UNKNOWN'}</small></span></div>
        </nav>

        <div className="cockpit-main">
          <section className="cockpit-title-row">
            <div><p className="eyebrow">COMMAND CENTER / 01</p><h1>Good to see you.</h1><p className="title-sub">Your operating picture, live.</p></div>
            <div className="state-readout"><span className={`state-indicator state-${state}`} /><span>{state.toUpperCase()}</span><small>{health?.timestamp ? `Updated ${new Date(health.timestamp).toLocaleTimeString()}` : 'Waiting for system data'}</small></div>
          </section>

          {refreshError && <div className="cockpit-alert" role="status"><strong>Some live data is unavailable.</strong><span>{refreshError}</span></div>}

          <section className="cockpit-grid-main" aria-label="Live system cockpit">
            <article className="cockpit-panel core-panel">
              <div className="panel-heading"><div><p className="eyebrow">JARV CORE</p><h2>Intelligence field</h2></div><span className="panel-index">CORE / 01</span></div>
              <div className="core-visual"><CockpitCore state={state} /><div className="core-readout"><span>OPERATIONAL STATE</span><strong>{state.toUpperCase()}</strong><small>{activeTasks.length ? `${activeTasks.length} active task${activeTasks.length === 1 ? '' : 's'}` : 'No active tasks'}</small></div></div>
              <div className="core-legend"><span><i className="legend-dot cyan" />LIVE SIGNAL</span><span><i className="legend-dot silver" />SYSTEM STATUS</span><span>{loading ? 'SYNCING' : 'SYNC · 15 SEC'}</span></div>
            </article>

            <article className="cockpit-panel mission-panel">
              <div className="panel-heading"><div><p className="eyebrow">MISSION CONTROL</p><h2>Send an instruction</h2></div><a className="text-link" href="/dashboard/command">Mission log ↗</a></div>
              <form className="mission-form" onSubmit={(event) => { event.preventDefault(); void sendCommand(command); }}>
                <label htmlFor="mission-command">What should JARV work on?</label>
                <textarea id="mission-command" value={command} onChange={(event) => setCommand(event.target.value)} placeholder="Describe a task or ask for an operational update" disabled={commandLoading} rows={3} />
                <div className="mission-actions">
                  <button type="submit" className="primary-button" disabled={commandLoading || !command.trim()}>{commandLoading ? 'Working…' : 'Send instruction ↗'}</button>
                </div>
              </form>
              <VoiceOperator onCommand={sendCommand} onStateChange={setVoiceState} />
              {commandError && <p className="inline-error" role="alert">{commandError}</p>}
              {commandResult && <div className={`mission-result result-${commandResult.status}`}>
                <div className="result-heading"><span>{commandResult.status.toUpperCase()}</span>{commandResult.requires_approval && <b>APPROVAL REQUIRED</b>}</div>
                {commandResult.requires_approval && <p className="approval-reason">{commandResult.approval_reason}</p>}
                <p>{commandResult.response_text || commandResult.error || 'Mission accepted.'}</p>
                {!!commandResult.selected_agents?.length && <small>Assigned: {commandResult.selected_agents.join(' · ')}</small>}
              </div>}
            </article>

            <article className="cockpit-panel telemetry-panel">
              <div className="panel-heading"><div><p className="eyebrow">TELEMETRY</p><h2>System pulse</h2></div><span className="panel-index">LIVE DATA</span></div>
              <div className="metric-grid">
                <div className="metric"><span>BACKEND</span><strong className={healthOk ? 'metric-good' : 'metric-dim'}>{health?.status ?? 'UNKNOWN'}</strong><small>{health?.service ?? 'Awaiting health check'}</small></div>
                <div className="metric"><span>REGISTERED AGENTS</span><strong>{agentStats?.total_registered ?? agents.length}<i> / {agentStats?.total_required ?? '—'}</i></strong><small>{agentStats ? `${agentStats.completion_percentage.toFixed(0)}% implemented` : 'Live roster'}</small></div>
                <div className="metric"><span>ACTIVE MISSIONS</span><strong>{activeTasks.length.toString().padStart(2, '0')}</strong><small>pending or in execution</small></div>
                <div className="metric"><span>IMPLEMENTED AGENTS</span><strong>{agentStats?.implemented ?? implementedAgents.length}</strong><small>from registered roster</small></div>
              </div>
              <div className="agent-strip"><div className="strip-title"><span>AGENT ROSTER</span><a href="/dashboard/agents">View all ↗</a></div><div className="agent-list">{agents.slice(0, 7).map((agent) => <div key={agent.name} className="agent-line"><span className={`agent-presence ${agent.is_implemented ? 'present' : ''}`} /><span>{agent.name}</span><small>{agent.is_implemented ? 'READY' : 'UNAVAILABLE'}</small></div>)}</div></div>
            </article>

            <article className="cockpit-panel activity-panel">
              <div className="panel-heading"><div><p className="eyebrow">OPERATIONS STREAM</p><h2>Recent activity</h2></div><a className="text-link" href="/dashboard/live-operations">Full feed ↗</a></div>
              {feed.length ? <ol className="activity-list">{feed.slice(0, 6).map((item) => <li key={item.id} className="activity-item"><span className={`activity-marker severity-${item.severity}`} /><div><div className="activity-top"><strong>{item.title}</strong><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleTimeString()}</time></div><p>{item.message}</p><small>{item.item_type.replace(/_/g, ' ').toUpperCase()}</small></div></li>)}</ol> : <div className="empty-state">{loading ? 'Loading persisted activity…' : 'No persisted activity is available.'}</div>}
            </article>
          </section>

          <section className="signal-grid" aria-label="Execution, approvals, and memory">
            <article className="cockpit-panel signal-panel">
              <div className="panel-heading"><div><p className="eyebrow">SWARM OPERATIONS</p><h2>Distributed execution</h2></div><a className="text-link" href="/dashboard/swarm">Swarm ↗</a></div>
              <div className="signal-numbers"><strong>{activeSwarmRuns.length.toString().padStart(2, '0')}<small> active runs</small></strong><strong>{activeSubAgents.toString().padStart(2, '0')}<small> active sub-agents</small></strong></div>
              <div className="signal-foot">Listed-run spend <b>${swarmSpend.toFixed(4)}</b></div>
            </article>
            <article className="cockpit-panel signal-panel boundary-panel">
              <div className="panel-heading"><div><p className="eyebrow">RICHARD BOUNDARY</p><h2>Approval queue</h2></div><a className="text-link" href="/dashboard/approvals">Review ↗</a></div>
              <div className="signal-numbers"><strong className={approvalStats?.pending_approvals ? 'signal-warning' : ''}>{approvalStats?.pending_approvals ?? '—'}<small> awaiting decision</small></strong></div>
              <div className="signal-foot">{approvalStats ? `${approvalStats.total_approvals} recorded approvals` : 'Approval data unavailable'}</div>
            </article>
            <article className="cockpit-panel signal-panel">
              <div className="panel-heading"><div><p className="eyebrow">PERSISTENT CONTEXT</p><h2>Memory & knowledge</h2></div><a className="text-link" href="/dashboard/memory">Memory ↗</a></div>
              <div className="signal-numbers"><strong>{memoryStats?.total_memories ?? '—'}<small> memory records</small></strong><strong>{memoryStats?.permanent_memories ?? '—'}<small> permanent</small></strong></div>
              <div className="signal-foot"><a href="/dashboard/agents">Versioned agent knowledge is retrieved per agent ↗</a></div>
            </article>
          </section>

          <section className="bottom-rail">
            <div><span className="eyebrow">ACTIVE MISSIONS</span><a href="/dashboard/tasks">Open task board ↗</a></div>
            <div className="mission-chips">{tasks.filter((task) => task.status !== 'completed').slice(0, 3).map((task) => <a className="task-chip" href={`/dashboard/tasks/${task.id}`} key={task.id}><span className={`state-indicator state-${task.status === 'blocked' ? 'approval' : task.status === 'failed' ? 'failed' : 'executing'}`} /><span>{task.title}</span><small>{task.status.toUpperCase()}</small></a>)}{!tasks.some((task) => task.status !== 'completed') && <span className="quiet-empty">No open tasks in the live task list.</span>}</div>
          </section>
        </div>
      </div>
      <footer className="cockpit-footer"><span>JARV / PRIVATE OPERATIONS</span><span>LIVE SOURCES · HEALTH · AGENTS · TASKS · OPERATIONS FEED</span><span>{loading ? 'SYNCING' : 'SESSION ACTIVE'}</span></footer>
    </main>
  );
}
