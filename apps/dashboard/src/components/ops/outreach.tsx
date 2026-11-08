'use client';

import { useState } from 'react';
import { Button, Empty, Loading, Note, Panel, percent, Pill, Stat, useAction, useLoad, when } from '@/components/ops/ui';

export interface OutreachMessage {
  id: string;
  prospect_id: string;
  step: number;
  send_after_days: number;
  subject: string;
  body: string;
  status: string;
  sent_at: string | null;
  error: string | null;
}

export interface Outreach {
  report: { prospects: number; contacted: number; reply_rate: number; positive_rate: number; opted_out: number;
    by_stage: Record<string, number>; advice: string[] };
  messages: OutreachMessage[];
  needs_before_sending: string[];
}

interface Approval { approved: number; refused: { message_id: string; reason: string }[]; sent_now: string[];
  waiting: number; reason_waiting: string | null }

/**
 * The Sales agent's outreach (Upgrade 6): the campaign's funnel and the outbox. Drafts wait here for Richard; he
 * approves a batch and JAI sends the due ones inside the daily limit, on weekdays in office hours.
 */
export function OutreachPanel({ workspaceId }: { workspaceId: string }) {
  const outreach = useLoad<Outreach>(`/api/business/${workspaceId}/outreach`);
  const action = useAction<Approval>();
  const [chosen, setChosen] = useState<string[]>([]);
  const data = outreach.data;
  const drafts = (data?.messages ?? []).filter((m) => m.status === 'draft');
  const rest = (data?.messages ?? []).filter((m) => m.status !== 'draft');

  const approve = async () => {
    const result = await action.run(`/api/business/${workspaceId}/outreach/approve`, { message_ids: chosen });
    if (result) {
      setChosen([]);
      await outreach.reload();
    }
  };
  const toggle = (id: string) => setChosen((now) => (now.includes(id) ? now.filter((x) => x !== id) : [...now, id]));

  if (outreach.loading) return <Loading label="Loading outreach" />;
  if (outreach.error) return <Note error={outreach.error} />;
  if (!data) return null;
  const r = data.report;
  return (
    <Panel title="Outreach" eyebrow="PROSPECTING">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <Stat label="Prospects" value={r.prospects} />
        <Stat label="Contacted" value={r.contacted} />
        <Stat label="Replied" value={percent(r.reply_rate, 0)} />
        <Stat label="Interested" value={percent(r.positive_rate, 0)} tone={r.positive_rate > 0 ? 'good' : 'default'} />
      </div>
      {data.needs_before_sending.length > 0 && (
        <Note error={`Before anything is sent, set ${data.needs_before_sending.join(' and ')} in the backend settings: every email must say who sends it and from where.`} />
      )}
      {r.advice.length > 0 && <ul className="mb-4 list-disc pl-5 text-sm text-muted-foreground">{r.advice.map((a) => <li key={a}>{a}</li>)}</ul>}
      <h3 className="text-sm font-semibold mb-2">Waiting for your approval</h3>
      {drafts.length === 0 ? <Empty title="No drafts waiting">Ask the sales agent to find and qualify prospects for this product.</Empty> : (
        <ul className="space-y-2">
          {drafts.map((m) => (
            <li key={m.id} className="rounded border p-3">
              <label className="flex items-start gap-2">
                <input type="checkbox" aria-label={`Approve ${m.subject}`} checked={chosen.includes(m.id)} onChange={() => toggle(m.id)} />
                <span className="flex-1">
                  <span className="font-medium">{m.subject}</span>
                  <span className="ml-2 text-xs text-muted-foreground">email {m.step}{m.send_after_days ? `, ${m.send_after_days} days after the last` : ''}</span>
                  <pre className="mt-2 whitespace-pre-wrap text-xs text-muted-foreground">{m.body}</pre>
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
      {drafts.length > 0 && (
        <div className="mt-3 flex items-center gap-3">
          <Button onClick={approve} disabled={action.busy || chosen.length === 0}>Approve and send {chosen.length || ''}</Button>
          <span className="text-xs text-muted-foreground">Sent within the daily limit, weekdays 8am to 5pm; never to an opt-out.</span>
        </div>
      )}
      <Note error={action.error} notice={action.notice} />
      {rest.length > 0 && (
        <div className="mt-5 overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-muted-foreground"><th className="py-1">Email</th><th>Status</th><th>Sent</th></tr></thead>
            <tbody>
              {rest.map((m) => (
                <tr key={m.id} className="border-t">
                  <td className="py-2">{m.subject}{m.error && <p className="text-xs text-red-600">{m.error}</p>}</td>
                  <td><Pill>{m.status}</Pill></td>
                  <td>{m.sent_at ? when(m.sent_at) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
