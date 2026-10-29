'use client';

import { FormEvent, useState } from 'react';
import { DraftsPanel } from '@/components/ops/drafts';
import { DEAL_STAGES, Deal, Pipeline } from '@/components/ops/pipeline';
import { Button, Empty, Field, inputClass, Loading, money, Note, Panel, percent, Pill, Stat, useAction, useLoad } from '@/components/ops/ui';
import { WorkspacePage } from '@/components/ops/workspace';

function DealsPanel({ workspaceId }: { workspaceId: string }) {
  const pipeline = useLoad<Pipeline>(`/api/business/${workspaceId}/pipeline`);
  const action = useAction<Deal>();
  const [title, setTitle] = useState('');
  const [company, setCompany] = useState('');
  const [value, setValue] = useState('');
  const [stage, setStage] = useState('prospecting');

  const move = async (deal: Deal, next: string) => {
    if (await action.run(`/api/business/${workspaceId}/deals`, { deal_id: deal.id, stage: next }, `${deal.title} moved to ${next.replace('_', ' ')}`)) {
      await pipeline.reload();
    }
  };

  const create = async (event: FormEvent) => {
    event.preventDefault();
    const created = await action.run(`/api/business/${workspaceId}/deals`, {
      title, company: company || undefined, stage, value: value ? Number(value) : undefined,
    }, 'Deal added');
    if (created) {
      setTitle('');
      setCompany('');
      setValue('');
      await pipeline.reload();
    }
  };

  const p = pipeline.data;
  return (
    <>
      {pipeline.loading ? <Loading /> : pipeline.error ? <Note error={pipeline.error} /> : p && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Stat label="Open pipeline" value={money(p.open_pipeline_value)} />
          <Stat label="Won" value={money(p.won_value)} tone="good" />
          <Stat label="Win rate" value={percent(p.win_rate, 0)} hint="closed deals" />
          <Stat label="Deals" value={p.deals.length} />
        </div>
      )}
      <Panel title="Deals" eyebrow="CRM PIPELINE">
        {p && p.deals.length === 0 && <Empty title="No deals yet">Add the first one below, or ask the sales agent to qualify a lead.</Empty>}
        {p && p.deals.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-muted-foreground"><th className="py-1">Deal</th><th>Stage</th><th>Value</th><th>Expected close</th><th>Move to</th></tr></thead>
              <tbody>
                {p.deals.map((d) => (
                  <tr key={d.id} className="border-t align-top">
                    <td className="py-2"><p className="font-medium">{d.title}</p>{d.notes && <p className="text-xs text-muted-foreground">{d.notes}</p>}</td>
                    <td><Pill>{d.stage.replace('_', ' ')}</Pill></td>
                    <td>{money(d.value)}</td>
                    <td>{d.expected_close_date ?? '—'}</td>
                    <td>
                      <select aria-label={`Move ${d.title}`} className="rounded-md border bg-background px-2 py-1 text-xs" value={d.stage}
                        disabled={action.busy} onChange={(e) => move(d, e.target.value)}>
                        {DEAL_STAGES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <form onSubmit={create} className="grid grid-cols-1 md:grid-cols-5 gap-3 border-t pt-4 mt-4" aria-label="Add deal">
          <Field label="Deal"><input required className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
          <Field label="Company"><input className={inputClass} value={company} onChange={(e) => setCompany(e.target.value)} /></Field>
          <Field label="Value"><input type="number" min="0" step="0.01" className={inputClass} value={value} onChange={(e) => setValue(e.target.value)} /></Field>
          <Field label="Stage">
            <select className={inputClass} value={stage} onChange={(e) => setStage(e.target.value)}>
              {DEAL_STAGES.slice(0, 4).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </Field>
          <div className="flex items-end"><Button type="submit" disabled={action.busy}>Add deal</Button></div>
        </form>
        <Note error={action.error} notice={action.notice} />
      </Panel>
    </>
  );
}

export default function SalesPage() {
  return (
    <WorkspacePage title="Sales" subtitle="The deal pipeline and sales material grounded in the product's real facts">
      {(workspaceId) => (
        <div className="space-y-6" key={workspaceId}>
          <DealsPanel workspaceId={workspaceId} />
          <DraftsPanel workspaceId={workspaceId} group="sales" title="Sales drafts"
            hint="Prospect briefs, scripts, follow-up sequences and summaries. Binding commercial commitments stay with you." />
        </div>
      )}
    </WorkspacePage>
  );
}
