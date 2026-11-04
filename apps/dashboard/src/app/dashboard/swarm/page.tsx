'use client';

/**
 * The Swarm page: every swarm run (a mission's team, or a swarm started by hand) with its lead agent and each
 * sub-agent: its role, its work package, the paths it owns, its status, steps, tool calls, cost and its report.
 * Real data from GET /api/swarm/runs and GET /api/swarm/sub-agents; refreshed every 10 seconds while a run is active.
 */
import { useCallback, useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';

interface SwarmRun {
  id: string;
  workspace_id: string;
  lead_agent_name: string;
  swarm_purpose: string;
  status: string;
  max_sub_agents: number;
  active_sub_agents: number;
  completed_sub_agents: number;
  failed_sub_agents: number;
  total_tokens_used: Record<string, number> | number | null;
  total_cost: number | string | null;
  started_at: string | null;
  completed_at: string | null;
  metadata: Record<string, unknown> | null;
}

interface SubAgent {
  id: string;
  swarm_run_id: string;
  agent_template: string;
  status: string;
  authority_level: number;
  tokens_used: Record<string, number> | null;
  cost_estimate: number | string | null;
  output: Record<string, unknown> | null;
  spawned_at: string | null;
  dissolved_at: string | null;
  metadata: Record<string, unknown> | null;
}

const num = (value: unknown): number => {
  const n = typeof value === 'number' ? value : parseFloat(String(value ?? 0));
  return Number.isFinite(n) ? n : 0;
};

const tokens = (value: unknown): number =>
  value && typeof value === 'object'
    ? Object.values(value as Record<string, unknown>).reduce<number>((sum, v) => sum + num(v), 0)
    : num(value);

const when = (value: string | null | undefined): string => {
  if (!value) return '';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString();
};

const text = (value: unknown): string => (typeof value === 'string' ? value : '');

const STATUS: Record<string, string> = {
  initializing: 'bg-gray-100 text-gray-800',
  spawning: 'bg-gray-100 text-gray-800',
  running: 'bg-blue-100 text-blue-800',
  working: 'bg-blue-100 text-blue-800',
  completed: 'bg-green-100 text-green-800',
  dissolved: 'bg-gray-200 text-gray-800',
  failed: 'bg-red-100 text-red-800',
  timed_out: 'bg-red-100 text-red-800',
  cancelled: 'bg-yellow-100 text-yellow-800',
  paused: 'bg-orange-100 text-orange-800',
};

function Badge({ status }: { status: string }) {
  return <span className={`px-2 py-0.5 text-xs rounded ${STATUS[status] || 'bg-gray-100 text-gray-800'}`}>{status}</span>;
}

function Member({ agent }: { agent: SubAgent }) {
  const meta = agent.metadata || {};
  const out = agent.output || {};
  const owns = Array.isArray(meta.owns) ? (meta.owns as unknown[]).map(String) : [];
  const finished = agent.status === 'dissolved' || agent.status === 'completed' || agent.status === 'failed';
  const outcome = finished ? (out.success === true ? 'finished' : 'stopped') : null;
  return (
    <li className="border rounded-md p-3" data-testid="sub-agent">
      <div className="flex items-center justify-between gap-2">
        <p className="font-medium">
          {text(meta.package) ? `${text(meta.package)} · ` : ''}{agent.agent_template.replace(/_/g, ' ')}
        </p>
        <div className="flex items-center gap-2">
          {outcome && <span className={`text-xs ${outcome === 'finished' ? 'text-green-600' : 'text-red-600'}`}>{outcome}</span>}
          <Badge status={agent.status} />
        </div>
      </div>
      {owns.length > 0 && <p className="text-xs text-muted-foreground mt-1">Owns: {owns.join(', ')}</p>}
      <p className="text-xs text-muted-foreground mt-1">
        Authority {agent.authority_level} · {num(out.steps)} steps · {num(out.tool_calls)} tool calls ·{' '}
        {tokens(agent.tokens_used).toLocaleString()} tokens · ${num(agent.cost_estimate).toFixed(4)}
      </p>
      {text(out.summary) && <p className="text-sm mt-2 whitespace-pre-wrap line-clamp-4">{text(out.summary)}</p>}
    </li>
  );
}

export default function SwarmPage() {
  const [runs, setRuns] = useState<SwarmRun[]>([]);
  const [members, setMembers] = useState<Record<string, SubAgent[]>>({});
  const [open, setOpen] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const response = await apiClient.get<SwarmRun[]>('/api/swarm/runs');
    if (response.error) {
      setError(response.error);
    } else {
      setError(null);
      const list = Array.isArray(response.data) ? response.data : [];
      list.sort((a, b) => (b.started_at || '').localeCompare(a.started_at || ''));
      setRuns(list);
      setOpen((current) => current ?? list[0]?.id ?? null);
    }
    setLoading(false);
  }, []);

  const loadMembers = useCallback(async (runId: string) => {
    const response = await apiClient.get<SubAgent[]>(`/api/swarm/sub-agents?swarm_run_id=${encodeURIComponent(runId)}`);
    if (!response.error && Array.isArray(response.data)) {
      const list = [...response.data].sort((a, b) =>
        text(a.metadata?.package).localeCompare(text(b.metadata?.package)) || (a.spawned_at || '').localeCompare(b.spawned_at || ''));
      setMembers((current) => ({ ...current, [runId]: list }));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (open) loadMembers(open);
  }, [open, loadMembers]);

  const active = runs.some((r) => r.status === 'running' || r.status === 'initializing');
  useEffect(() => {
    if (!active) return undefined;
    const timer = setInterval(() => {
      load();
      if (open) loadMembers(open);
    }, 10000);
    return () => clearInterval(timer);
  }, [active, open, load, loadMembers]);

  const totalAgents = runs.reduce((sum, r) => sum + num(r.active_sub_agents), 0);
  const totalTokens = runs.reduce((sum, r) => sum + tokens(r.total_tokens_used), 0);
  const totalCost = runs.reduce((sum, r) => sum + num(r.total_cost), 0);
  const stats: [string, string, string][] = [
    ['Swarm runs', String(runs.length), ''],
    ['Active runs', String(runs.filter((r) => r.status === 'running').length), 'text-blue-600'],
    ['Sub-agents working', String(totalAgents), 'text-purple-600'],
    ['Completed runs', String(runs.filter((r) => r.status === 'completed').length), 'text-green-600'],
    ['Tokens', totalTokens.toLocaleString(), ''],
    ['Cost', `$${totalCost.toFixed(4)}`, ''],
  ];

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Swarm System</h1>
          <p className="text-muted-foreground">Each mission&apos;s team: the lead agent and the specialist sub-agents it spawned</p>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary" />
          </div>
        )}

        {error && (
          <div className="bg-destructive/10 border border-destructive text-destructive px-4 py-3 rounded-lg mb-6">
            <p className="font-semibold">Error loading swarm data</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {!loading && (
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
            {stats.map(([label, value, colour]) => (
              <div key={label} className="bg-card border rounded-lg p-6">
                <h3 className="text-sm font-medium text-muted-foreground mb-2">{label}</h3>
                <p className={`text-3xl font-bold ${colour}`}>{value}</p>
              </div>
            ))}
          </div>
        )}

        {!loading && !error && runs.length === 0 && (
          <div className="bg-card border rounded-lg p-12 text-center">
            <h3 className="text-xl font-semibold mb-2">No swarm runs yet</h3>
            <p className="text-muted-foreground">A mission with separate parts is planned into work packages and run by a team here.</p>
          </div>
        )}

        <div className="space-y-4">
          {runs.map((run) => {
            const meta = run.metadata || {};
            const isOpen = open === run.id;
            const team = members[run.id] || [];
            return (
              <div key={run.id} className="bg-card border rounded-lg p-6" data-testid="swarm-run">
                <button type="button" className="w-full text-left" onClick={() => setOpen(isOpen ? null : run.id)}
                        aria-expanded={isOpen}>
                  <div className="flex items-start justify-between gap-4 mb-3">
                    <div className="min-w-0">
                      <h3 className="text-lg font-semibold mb-1 truncate">{run.swarm_purpose || `Swarm run ${run.id.slice(0, 8)}`}</h3>
                      <p className="text-sm text-muted-foreground">
                        Lead: {run.lead_agent_name || 'unknown'}
                        {text(meta.approach) ? ` · ${text(meta.approach)}` : ''}
                      </p>
                    </div>
                    <Badge status={run.status} />
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-sm">
                    <div><p className="text-xs text-muted-foreground">Working</p><p className="font-semibold">{num(run.active_sub_agents)}/{num(run.max_sub_agents)}</p></div>
                    <div><p className="text-xs text-muted-foreground">Finished</p><p className="font-semibold text-green-600">{num(run.completed_sub_agents)}</p></div>
                    <div><p className="text-xs text-muted-foreground">Stopped</p><p className="font-semibold text-red-600">{num(run.failed_sub_agents)}</p></div>
                    <div><p className="text-xs text-muted-foreground">Tokens</p><p className="font-semibold">{tokens(run.total_tokens_used).toLocaleString()}</p></div>
                    <div><p className="text-xs text-muted-foreground">Cost</p><p className="font-semibold">${num(run.total_cost).toFixed(4)}</p></div>
                  </div>
                  <p className="text-xs text-muted-foreground mt-3">
                    {when(run.started_at) && `Started ${when(run.started_at)}`}
                    {when(run.completed_at) && ` · Finished ${when(run.completed_at)}`}
                  </p>
                </button>
                {isOpen && (
                  <ul className="mt-4 space-y-2">
                    {team.length === 0 && <li className="text-sm text-muted-foreground">Loading the team…</li>}
                    {team.map((agent) => <Member key={agent.id} agent={agent} />)}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
