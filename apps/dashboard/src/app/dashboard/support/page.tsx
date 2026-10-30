'use client';

import { FormEvent, useState } from 'react';
import { Button, Empty, Field, inputClass, Loading, Note, Panel, Pill, Stat, useAction, useLoad, when } from '@/components/ops/ui';
import { WorkspacePage } from '@/components/ops/workspace';

interface TicketMessage {
  kind: string;
  at: string;
  body?: string;
  generated_by?: string;
  confidence?: number;
}

interface Ticket {
  id: string;
  number: string;
  subject: string;
  description: string;
  customer: string | null;
  email: string | null;
  category: string;
  priority: string;
  severity: string;
  status: string;
  messages: TicketMessage[];
  last_draft: TicketMessage | null;
  escalation_task_id: string | null;
  source: string | null;
  created_at: string | null;
}

interface Feedback {
  period_days: number;
  tickets: number;
  community_messages: number;
  by_category: Record<string, number>;
  by_status: Record<string, number>;
  sentiment: Record<string, number>;
  top_terms: [string, number][];
  bugs: { number: string; subject: string; severity: string }[];
}

interface EmailStatus {
  sending: boolean;
  reading: boolean;
  missing_for_sending: string[];
  missing_for_reading: string[];
}

function TicketDetail({ workspaceId, ticket, onChange }: { workspaceId: string; ticket: Ticket; onChange: () => void }) {
  const action = useAction<Record<string, unknown>>();
  const [reply, setReply] = useState(ticket.last_draft?.body ?? '');
  const base = `/api/support/${workspaceId}/tickets/${ticket.id}`;

  const draft = async () => {
    const result = await action.run(`${base}/draft-reply`, { tone: 'friendly' }, 'Reply drafted from the FAQ and product facts');
    if (result && typeof result.body === 'string') setReply(result.body);
    onChange();
  };
  const send = async () => {
    if (!window.confirm(`Send this reply to ${ticket.email ?? 'the customer'}?`)) return;
    if (await action.run(`${base}/reply`, { reply_content: reply }, 'Reply sent')) onChange();
  };

  return (
    <Panel title={`${ticket.number}: ${ticket.subject}`} eyebrow="TICKET">
      <div className="flex flex-wrap gap-2 mb-3">
        <Pill>{ticket.status}</Pill><Pill tone="info">{ticket.category}</Pill><Pill>{ticket.priority}</Pill>
        {ticket.escalation_task_id && <a className="text-xs underline" href={`/dashboard/tasks/${ticket.escalation_task_id}`}>Escalated to engineering ↗</a>}
      </div>
      <p className="text-sm text-muted-foreground mb-1">{ticket.customer ?? 'Customer'} {ticket.email ? `<${ticket.email}>` : ''} · {when(ticket.created_at)}</p>
      <p className="text-sm whitespace-pre-wrap mb-4">{ticket.description}</p>
      {ticket.messages.filter((m) => m.kind !== 'draft').length > 0 && (
        <ul className="text-sm space-y-2 mb-4">
          {ticket.messages.filter((m) => m.kind !== 'draft').map((m, i) => (
            <li key={i} className="border-l-2 pl-3"><span className="text-xs text-muted-foreground">{m.kind} · {when(m.at)}</span><p className="whitespace-pre-wrap">{m.body}</p></li>
          ))}
        </ul>
      )}
      <Field label="Reply" hint="Draft a reply, edit it, then send">
        <textarea className={`${inputClass} min-h-[160px]`} value={reply} onChange={(e) => setReply(e.target.value)} />
      </Field>
      {ticket.last_draft && (
        <p className="text-xs text-muted-foreground mt-1">
          Draft by {ticket.last_draft.generated_by}{ticket.last_draft.confidence !== undefined ? `, confidence ${Math.round(ticket.last_draft.confidence * 100)}%` : ''}
        </p>
      )}
      <div className="flex gap-2 mt-3">
        <Button kind="secondary" onClick={draft} disabled={action.busy}>Draft reply</Button>
        <Button onClick={send} disabled={action.busy || !reply.trim() || !ticket.email}>Send reply</Button>
      </div>
      {!ticket.email && <p className="text-xs text-muted-foreground mt-2">No customer email on this ticket, so it cannot be sent.</p>}
      <Note error={action.error} notice={action.notice} />
    </Panel>
  );
}

function Inbox({ workspaceId }: { workspaceId: string }) {
  const [status, setStatus] = useState('');
  const tickets = useLoad<Ticket[]>(`/api/support/${workspaceId}/tickets${status ? `?status=${status}` : ''}`);
  const feedback = useLoad<Feedback>(`/api/support/${workspaceId}/feedback?days=30`);
  const email = useLoad<EmailStatus>('/api/support/email/status');
  const create = useAction<Ticket>();
  const sync = useAction<{ read: number; tickets: unknown[] }>();
  const [selected, setSelected] = useState<string | null>(null);
  const [subject, setSubject] = useState('');
  const [description, setDescription] = useState('');
  const [customerEmail, setCustomerEmail] = useState('');

  const refresh = async () => {
    await tickets.reload();
    await feedback.reload();
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const created = await create.run(`/api/support/${workspaceId}/tickets`,
      { subject, description, customer_email: customerEmail || undefined }, 'Ticket created and categorised');
    if (created) {
      setSubject('');
      setDescription('');
      setCustomerEmail('');
      setSelected(created.id);
      await refresh();
    }
  };
  const syncInbox = async () => {
    const result = await sync.run(`/api/support/${workspaceId}/inbox/sync`);
    if (result) {
      sync.clear();
      await refresh();
    }
  };

  const f = feedback.data;
  const current = tickets.data?.find((t) => t.id === selected) ?? null;
  return (
    <div className="space-y-6">
      {f && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Stat label="Tickets (30 days)" value={f.tickets} />
          <Stat label="Unanswered" value={(f.by_status.new ?? 0) + (f.by_status.open ?? 0) + (f.by_status.escalated ?? 0)} tone={(f.by_status.new ?? 0) > 0 ? 'warn' : 'default'} />
          <Stat label="Bugs reported" value={f.bugs.length} tone={f.bugs.length ? 'bad' : 'default'} />
          <Stat label="Negative sentiment" value={f.sentiment.negative ?? 0} hint={f.top_terms.slice(0, 4).map(([t]) => t).join(', ') || undefined} />
        </div>
      )}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Panel title="Inbox" eyebrow="SUPPORT"
          actions={<>
            <select aria-label="Status" className="rounded-md border bg-background px-2 py-1 text-sm" value={status} onChange={(e) => setStatus(e.target.value)}>
              {['', 'new', 'open', 'escalated', 'waiting_customer', 'resolved', 'closed'].map((s) => <option key={s} value={s}>{s || 'all'}</option>)}
            </select>
            <Button kind="secondary" onClick={syncInbox} disabled={sync.busy || !email.data?.reading}>Read email</Button>
          </>}>
          {email.data && !email.data.reading && (
            <p className="text-xs text-muted-foreground mb-3">Email inbox not connected (set {email.data.missing_for_reading.join(', ')}).</p>
          )}
          <Note error={sync.error} />
          {tickets.loading ? <Loading /> : tickets.error ? <Note error={tickets.error} /> : (tickets.data?.length ?? 0) === 0 ? (
            <Empty title="No tickets" />
          ) : (
            <ul className="divide-y border rounded-md">
              {tickets.data!.map((t) => (
                <li key={t.id}>
                  <button type="button" onClick={() => setSelected(t.id)} aria-pressed={selected === t.id}
                    className={`w-full text-left p-3 flex flex-wrap gap-2 items-center ${selected === t.id ? 'bg-muted' : 'hover:bg-muted/50'}`}>
                    <span className="text-xs text-muted-foreground">{t.number}</span>
                    <span className="font-medium flex-1 min-w-[160px]">{t.subject}</span>
                    <Pill tone="info">{t.category}</Pill><Pill>{t.priority}</Pill><Pill>{t.status}</Pill>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <form onSubmit={submit} className="border-t pt-4 mt-4 space-y-3" aria-label="New ticket">
            <Field label="Subject"><input required minLength={3} className={inputClass} value={subject} onChange={(e) => setSubject(e.target.value)} /></Field>
            <Field label="What the customer said"><textarea required minLength={3} className={`${inputClass} min-h-[72px]`} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
            <Field label="Customer email"><input type="email" className={inputClass} value={customerEmail} onChange={(e) => setCustomerEmail(e.target.value)} /></Field>
            <Button type="submit" disabled={create.busy}>Create ticket</Button>
            <Note error={create.error} notice={create.notice} />
          </form>
        </Panel>
        {current ? <TicketDetail key={current.id} workspaceId={workspaceId} ticket={current} onChange={refresh} /> : (
          <Panel title="Ticket" eyebrow="DETAIL"><Empty title="Choose a ticket">Draft, edit and send replies here. Sending is your approval for that message.</Empty></Panel>
        )}
      </div>
    </div>
  );
}

export default function SupportPage() {
  return (
    <WorkspacePage title="Support" subtitle="The persisted support inbox: categorised tickets, FAQ-grounded replies, bug escalation to engineering">
      {(workspaceId) => <Inbox key={workspaceId} workspaceId={workspaceId} />}
    </WorkspacePage>
  );
}
