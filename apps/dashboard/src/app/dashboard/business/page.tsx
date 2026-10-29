'use client';

import { FormEvent, useState } from 'react';
import { DraftsPanel } from '@/components/ops/drafts';
import { Button, Empty, Field, inputClass, Loading, Note, Panel, Pill, Stat, useAction, useLoad } from '@/components/ops/ui';
import { WorkspacePage } from '@/components/ops/workspace';

interface Kpi {
  id: string;
  name: string;
  category: string | null;
  value: number;
  unit: string | null;
  target: number | null;
  target_met: boolean | null;
  period_start: string;
  previous: number | null;
  change: number | null;
}

interface Overview {
  operating_plan: { name: string; status: string; version: number; completion_percentage: number; objectives: unknown;
                    objectives_completed: number; objectives_total: number; end_date: string } | null;
  latest_daily_loop: { date: string; status: string; summary: string | null; highlights: string[]; concerns: string[] } | null;
  kpis: Kpi[];
  risks: { id: string; title: string; category: string; probability: string; impact: string; score: number; status: string;
           mitigation_strategy: string | null }[];
  decisions: { id: string; title: string; type: string; rationale: string | null; date: string; status: string }[];
  next_best_actions: { priority: number; action: string; reason: string; owner: string; ref: string | null }[];
}

function objectiveText(item: unknown): string {
  if (typeof item === 'string') return item;
  if (item && typeof item === 'object') {
    const o = item as Record<string, unknown>;
    return String(o.title ?? o.objective ?? o.name ?? JSON.stringify(o));
  }
  return String(item);
}

function Board({ workspaceId }: { workspaceId: string }) {
  const overview = useLoad<Overview>(`/api/company-ops/${workspaceId}/overview`);
  const loop = useAction<{ summary: string | null }>();
  const kpi = useAction();
  const [name, setName] = useState('');
  const [value, setValue] = useState('');
  const [target, setTarget] = useState('');
  const [unit, setUnit] = useState('');

  const runLoop = async () => {
    if (await loop.run(`/api/company-ops/${workspaceId}/daily-loop/run`, undefined, 'Daily operating loop finished')) await overview.reload();
  };
  const addKpi = async (event: FormEvent) => {
    event.preventDefault();
    if (await kpi.run(`/api/company-ops/${workspaceId}/kpis`, {
      name, value: Number(value), target: target ? Number(target) : undefined, unit: unit || undefined,
    }, `${name} recorded`)) {
      setName('');
      setValue('');
      setTarget('');
      await overview.reload();
    }
  };

  const o = overview.data;
  const objectives = Array.isArray(o?.operating_plan?.objectives) ? (o!.operating_plan!.objectives as unknown[]) : [];
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm text-muted-foreground">The daily loop measures KPIs, reviews risks and the plan, and sets the next actions.</span>
        <span className="flex-1" />
        <Button onClick={runLoop} disabled={loop.busy}>{loop.busy ? 'Running…' : 'Run daily loop'}</Button>
      </div>
      <Note error={loop.error} notice={loop.notice} />
      {overview.loading ? <Loading /> : overview.error ? <Note error={overview.error} /> : o && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Stat label="Operating plan" value={o.operating_plan ? `${Math.round(o.operating_plan.completion_percentage)}%` : '—'}
              hint={o.operating_plan ? `${o.operating_plan.name} v${o.operating_plan.version}` : 'no active plan'} />
            <Stat label="KPIs tracked" value={o.kpis.length} hint={`${o.kpis.filter((k) => k.target_met).length} on target`} />
            <Stat label="Open risks" value={o.risks.filter((r) => r.status !== 'closed').length} tone={o.risks.some((r) => r.score >= 12) ? 'bad' : 'default'} />
            <Stat label="Last daily loop" value={o.latest_daily_loop?.date ?? '—'} hint={o.latest_daily_loop?.status} />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Panel title="Next best actions" eyebrow="PRIORITISED">
              {o.next_best_actions.length === 0 ? <Empty title="Nothing queued" /> : (
                <ol className="space-y-2 text-sm">
                  {o.next_best_actions.map((a, i) => (
                    <li key={i} className="flex gap-3"><Pill tone={a.priority >= 80 ? 'bad' : a.priority >= 60 ? 'warn' : 'info'}>{a.priority}</Pill>
                      <span><span className="font-medium">{a.action}</span><span className="text-muted-foreground"> · {a.reason} · {a.owner}</span></span></li>
                  ))}
                </ol>
              )}
            </Panel>
            <Panel title="Operating plan" eyebrow="STRATEGY">
              {!o.operating_plan ? <Empty title="No active operating plan">Ask JARV to create one from the Command page.</Empty> : (
                <>
                  <p className="text-sm mb-2"><span className="font-medium">{o.operating_plan.name}</span> · <Pill>{o.operating_plan.status}</Pill> · ends {o.operating_plan.end_date}</p>
                  <div className="h-2 bg-muted rounded"><div className="h-2 bg-primary rounded" style={{ width: `${Math.min(100, o.operating_plan.completion_percentage)}%` }} /></div>
                  <ul className="list-disc ml-5 text-sm mt-3 space-y-1">{objectives.slice(0, 8).map((ob, i) => <li key={i}>{objectiveText(ob)}</li>)}</ul>
                </>
              )}
              {o.latest_daily_loop?.summary && <p className="text-sm text-muted-foreground mt-3">Latest loop: {o.latest_daily_loop.summary}</p>}
            </Panel>
          </div>
          <Panel title="KPIs" eyebrow="MEASURED">
            {o.kpis.length === 0 ? <Empty title="No KPIs yet" /> : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-muted-foreground"><th className="py-1">KPI</th><th>Value</th><th>Target</th><th>Change</th><th>Period</th></tr></thead>
                  <tbody>{o.kpis.map((k) => (
                    <tr key={k.id} className="border-t">
                      <td className="py-1.5">{k.name}</td>
                      <td>{k.value.toLocaleString()}{k.unit ? ` ${k.unit}` : ''}</td>
                      <td>{k.target !== null ? <Pill tone={k.target_met ? 'good' : 'warn'}>{k.target.toLocaleString()}</Pill> : '—'}</td>
                      <td className={k.change === null ? '' : k.change >= 0 ? 'text-green-600' : 'text-red-600'}>{k.change === null ? '—' : `${k.change >= 0 ? '+' : ''}${k.change.toLocaleString()}`}</td>
                      <td className="text-muted-foreground">{k.period_start}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
            <form onSubmit={addKpi} className="grid grid-cols-2 md:grid-cols-5 gap-3 border-t pt-4 mt-4" aria-label="Record KPI">
              <Field label="KPI"><input required minLength={2} className={inputClass} value={name} onChange={(e) => setName(e.target.value)} placeholder="signups" /></Field>
              <Field label="Value"><input required type="number" step="any" className={inputClass} value={value} onChange={(e) => setValue(e.target.value)} /></Field>
              <Field label="Target"><input type="number" step="any" className={inputClass} value={target} onChange={(e) => setTarget(e.target.value)} /></Field>
              <Field label="Unit"><input className={inputClass} value={unit} onChange={(e) => setUnit(e.target.value)} /></Field>
              <div className="flex items-end"><Button type="submit" disabled={kpi.busy}>Record KPI</Button></div>
            </form>
            <Note error={kpi.error} notice={kpi.notice} />
          </Panel>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Panel title="Risk register" eyebrow="RISKS">
              {o.risks.length === 0 ? <Empty title="No risks recorded" /> : (
                <ul className="divide-y text-sm">{o.risks.map((r) => (
                  <li key={r.id} className="py-2"><div className="flex gap-2 items-center"><span className="font-medium flex-1">{r.title}</span><Pill>{r.status}</Pill><Pill tone={r.score >= 12 ? 'bad' : r.score >= 6 ? 'warn' : 'info'}>{r.probability}/{r.impact}</Pill></div>
                    {r.mitigation_strategy && <p className="text-xs text-muted-foreground mt-1">{r.mitigation_strategy}</p>}</li>
                ))}</ul>
              )}
            </Panel>
            <Panel title="Decision log" eyebrow="DECISIONS">
              {o.decisions.length === 0 ? <Empty title="No decisions logged" /> : (
                <ul className="divide-y text-sm">{o.decisions.map((d) => (
                  <li key={d.id} className="py-2"><div className="flex gap-2 items-center"><span className="font-medium flex-1">{d.title}</span><span className="text-xs text-muted-foreground">{d.date}</span></div>
                    {d.rationale && <p className="text-xs text-muted-foreground mt-1">{d.rationale}</p>}</li>
                ))}</ul>
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}

export default function BusinessPage() {
  return (
    <WorkspacePage title="Business" subtitle="The operating plan, KPIs, risks, decisions and next best actions, with offers and pricing reviews from real numbers">
      {(workspaceId) => (
        <div className="space-y-6" key={workspaceId}>
          <Board workspaceId={workspaceId} />
          <DraftsPanel workspaceId={workspaceId} group="revenue" title="Offers and pricing reviews"
            hint="Grounded in measured revenue, subscriptions, KPIs and the pipeline. Price changes and binding offers stay with you." />
        </div>
      )}
    </WorkspacePage>
  );
}
