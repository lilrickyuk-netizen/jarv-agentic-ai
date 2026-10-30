'use client';

import { useState } from 'react';
import { Empty, Loading, money, Note, Panel, percent, Pill, Stat, useLoad } from '@/components/ops/ui';
import { WorkspacePage } from '@/components/ops/workspace';

interface Overview {
  period_days: number;
  missions: { total: number; by_status: Record<string, number>; success_rate: number | null; average_seconds: number | null;
              tokens: number; per_day: Record<string, { created: number; completed: number; failed: number }> };
  tools: { runs: number; failed: number; approval_pauses: number; average_ms: number | null;
           top: { tool: string; runs: number; failed: number }[]; by_agent: Record<string, number> };
  cost: { items?: { item: string; monthly: number; source: string }[]; monthly_total?: number; budget?: number | null;
          remaining?: number | null; within_budget?: boolean | null; notes?: string[]; error?: string };
}

interface Traffic {
  source: string;
  visitors?: number | null;
  visits?: number | null;
  pageviews?: number | null;
  bounce_rate?: number | null;
  visit_duration?: number | null;
  top_pages?: { page: string | null; visitors: number | null; pageviews: number | null }[];
  kpis?: { name: string; value: number; unit: string | null; period_start: string }[];
}

function MissionBars({ perDay }: { perDay: Overview['missions']['per_day'] }) {
  const days = Object.entries(perDay);
  if (days.length === 0) return <Empty title="No missions in this period" />;
  const max = Math.max(...days.map(([, d]) => Math.max(d.created, d.completed + d.failed)), 1);
  return (
    <div>
      <div className="flex items-end gap-1 h-32" role="img" aria-label="Missions per day">
        {days.map(([day, d]) => (
          <div key={day} className="flex-1 min-w-[6px] flex flex-col justify-end h-full" title={`${day}: ${d.created} created, ${d.completed} completed, ${d.failed} failed`}>
            <div className="bg-red-500/80" style={{ height: `${(d.failed / max) * 100}%` }} />
            <div className="bg-primary/80 rounded-t" style={{ height: `${(d.completed / max) * 100}%` }} />
          </div>
        ))}
      </div>
      <p className="text-xs text-muted-foreground mt-2">Completed (blue) and failed (red) per day.</p>
    </div>
  );
}

function Board({ workspaceId }: { workspaceId: string }) {
  const [days, setDays] = useState(30);
  const data = useLoad<Overview>(`/api/analytics/${workspaceId}/overview?days=${days}`);
  const traffic = useLoad<Traffic>(`/api/revenue/${workspaceId}/analytics?days=${days}`);
  const o = data.data;
  const t = traffic.data;
  return (
    <div className="space-y-6">
      <label className="text-sm">Period{' '}
        <select aria-label="Period" className="rounded-md border bg-background px-2 py-1 text-sm ml-1" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[7, 30, 90].map((d) => <option key={d} value={d}>last {d} days</option>)}
        </select>
      </label>
      {data.loading ? <Loading /> : data.error ? <Note error={data.error} /> : o && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            <Stat label="Missions" value={o.missions.total} />
            <Stat label="Success rate" value={percent(o.missions.success_rate, 0)} tone={(o.missions.success_rate ?? 1) < 0.7 ? 'warn' : 'good'} />
            <Stat label="Average mission" value={o.missions.average_seconds !== null ? `${Math.round(o.missions.average_seconds)}s` : '—'} />
            <Stat label="Tokens" value={o.missions.tokens.toLocaleString()} />
            <Stat label="Tool runs" value={o.tools.runs} hint={`${o.tools.failed} failed`} tone={o.tools.failed ? 'warn' : 'default'} />
            <Stat label="Approval pauses" value={o.tools.approval_pauses} />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Panel title="Missions per day" eyebrow="THROUGHPUT">
              <MissionBars perDay={o.missions.per_day} />
              <div className="flex flex-wrap gap-2 mt-3">
                {Object.entries(o.missions.by_status).map(([s, n]) => <Pill key={s}>{`${s} ${n}`}</Pill>)}
              </div>
            </Panel>
            <Panel title="Most used tools" eyebrow="TOOL RUNS">
              {o.tools.top.length === 0 ? <Empty title="No tool runs in this period" /> : (
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-muted-foreground"><th className="py-1">Tool</th><th>Runs</th><th>Failed</th></tr></thead>
                  <tbody>{o.tools.top.map((r) => (
                    <tr key={r.tool} className="border-t"><td className="py-1">{r.tool}</td><td>{r.runs}</td><td className={r.failed ? 'text-red-600' : ''}>{r.failed}</td></tr>
                  ))}</tbody>
                </table>
              )}
              {Object.keys(o.tools.by_agent).length > 0 && (
                <p className="text-xs text-muted-foreground mt-3">By agent: {Object.entries(o.tools.by_agent).map(([a, n]) => `${a} ${n}`).join(' · ')}</p>
              )}
            </Panel>
          </div>
          <Panel title="Monthly cost" eyebrow="BUDGET">
            {o.cost.error ? <Note error={o.cost.error} /> : (
              <>
                <div className="grid grid-cols-3 gap-4 mb-3">
                  <Stat label="Estimated monthly" value={money(o.cost.monthly_total ?? 0)} />
                  <Stat label="Approved budget" value={o.cost.budget ? money(o.cost.budget) : 'not set'} />
                  <Stat label="Remaining" value={o.cost.remaining !== null && o.cost.remaining !== undefined ? money(o.cost.remaining) : '—'}
                    tone={o.cost.within_budget === false ? 'bad' : 'default'} />
                </div>
                {(o.cost.items ?? []).length > 0 && (
                  <ul className="text-sm divide-y">{o.cost.items!.map((i) => (
                    <li key={i.item} className="py-1 flex justify-between"><span>{i.item} <span className="text-xs text-muted-foreground">({i.source})</span></span><span>{money(i.monthly)}</span></li>
                  ))}</ul>
                )}
                {(o.cost.notes ?? []).map((n) => <p key={n} className="text-xs text-muted-foreground mt-2">{n}</p>)}
              </>
            )}
          </Panel>
        </>
      )}
      <Panel title="Product traffic" eyebrow="ANALYTICS">
        {traffic.loading ? <Loading /> : traffic.error ? <Note error={traffic.error} /> : t && (t.source === 'plausible' ? (
          <>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-4">
              <Stat label="Visitors" value={(t.visitors ?? 0).toLocaleString()} />
              <Stat label="Visits" value={(t.visits ?? 0).toLocaleString()} />
              <Stat label="Page views" value={(t.pageviews ?? 0).toLocaleString()} />
              <Stat label="Bounce rate" value={t.bounce_rate !== null && t.bounce_rate !== undefined ? `${t.bounce_rate}%` : '—'} />
              <Stat label="Visit duration" value={t.visit_duration !== null && t.visit_duration !== undefined ? `${t.visit_duration}s` : '—'} />
            </div>
            <ul className="text-sm divide-y">{(t.top_pages ?? []).map((p) => (
              <li key={p.page ?? ''} className="py-1 flex justify-between"><span>{p.page}</span><span>{p.visitors} visitors</span></li>
            ))}</ul>
          </>
        ) : (
          <>
            <p className="text-sm text-muted-foreground mb-3">Analytics not connected: set PLAUSIBLE_API_KEY and PLAUSIBLE_SITE_ID. Traffic KPIs recorded for this workspace:</p>
            {(t.kpis ?? []).length === 0 ? <Empty title="No traffic KPIs recorded" /> : (
              <ul className="text-sm divide-y">{t.kpis!.map((k) => (
                <li key={k.name} className="py-1 flex justify-between"><span>{k.name}</span><span>{k.value.toLocaleString()}{k.unit ? ` ${k.unit}` : ''} <span className="text-xs text-muted-foreground">({k.period_start})</span></span></li>
              ))}</ul>
            )}
          </>
        ))}
      </Panel>
    </div>
  );
}

export default function AnalyticsPage() {
  return (
    <WorkspacePage title="Analytics" subtitle="How JARV is performing here: missions, tools, cost against budget, and the product's own traffic">
      {(workspaceId) => <Board key={workspaceId} workspaceId={workspaceId} />}
    </WorkspacePage>
  );
}
