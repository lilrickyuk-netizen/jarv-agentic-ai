'use client';

import { FormEvent, useState } from 'react';
import { Button, Empty, Field, inputClass, Loading, money, Note, Panel, percent, Pill, Stat, useAction, useLoad } from '@/components/ops/ui';
import { WorkspacePage } from '@/components/ops/workspace';

interface Revenue {
  source: string;
  period_days: number;
  gross: number;
  refunds: number;
  fees?: number;
  net: number;
  payments: number;
  daily: Record<string, number>;
  by_product?: Record<string, number>;
  currency: string;
  has_data?: boolean;
}

interface Subscriptions {
  source: string;
  active: number;
  mrr: number;
  new: number;
  cancelled: number;
  churn_rate: number | null;
  arpu: number | null;
}

interface FailedPayments {
  source: string;
  count: number;
  amount: number;
  items: { id?: string; invoice?: string; customer: string | null; amount: number; date?: string; reason?: string | null }[];
}

interface Funnel {
  stages: { stage: string; value: number; kpi: string }[];
  conversion: { from: string; to: string; rate: number | null }[];
  missing: string[];
  overall: number | null;
}

interface Metrics {
  revenue: Revenue;
  subscriptions: Subscriptions;
  failed_payments: FailedPayments;
  conversion: Funnel;
}

interface Status {
  stripe: string;
  webhook: string;
  analytics: string;
  setup: string[];
}

interface LoopResult {
  summary: string;
  findings: string[];
  next_actions: string[];
  kpis_recorded: string[];
}

const EVENTS = ['payment', 'refund', 'subscription_started', 'subscription_cancelled', 'failed_payment', 'dispute'];

function DailyBars({ daily, currency }: { daily: Record<string, number>; currency: string }) {
  const entries = Object.entries(daily);
  if (entries.length === 0) return <Empty title="No payments in this period" />;
  const max = Math.max(...entries.map(([, v]) => v), 1);
  return (
    <div className="flex items-end gap-1 h-32" role="img" aria-label="Daily revenue">
      {entries.map(([day, value]) => (
        <div key={day} className="flex-1 min-w-[6px] bg-primary/80 rounded-t" style={{ height: `${Math.max(4, (value / max) * 100)}%` }}
          title={`${day}: ${money(value, currency)}`} />
      ))}
    </div>
  );
}

function RevenueBoard({ workspaceId }: { workspaceId: string }) {
  const [days, setDays] = useState(30);
  const metrics = useLoad<Metrics>(`/api/revenue/${workspaceId}/metrics?days=${days}`);
  const status = useLoad<Status>('/api/revenue/status');
  const loop = useAction<LoopResult>();
  const record = useAction<{ id: string }>();
  const [result, setResult] = useState<LoopResult | null>(null);
  const [event, setEvent] = useState('payment');
  const [amount, setAmount] = useState('');
  const [customer, setCustomer] = useState('');
  const [billing, setBilling] = useState('month');

  const runLoop = async () => {
    const outcome = await loop.run(`/api/revenue/${workspaceId}/loop?days=${days}`);
    if (outcome) {
      setResult(outcome);
      await metrics.reload();
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const body: Record<string, unknown> = { event, amount: Number(amount), customer_id: customer || undefined };
    if (event.startsWith('subscription')) body.interval = billing;
    if (await record.run(`/api/revenue/${workspaceId}/events`, body, 'Recorded')) {
      setAmount('');
      await metrics.reload();
    }
  };

  const m = metrics.data;
  const currency = m?.revenue.currency ?? 'USD';
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm">Period{' '}
          <select aria-label="Period" className="rounded-md border bg-background px-2 py-1 text-sm ml-1" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 30, 90, 365].map((d) => <option key={d} value={d}>last {d} days</option>)}
          </select>
        </label>
        {m && <Pill tone="info">source: {m.revenue.source}</Pill>}
        <span className="flex-1" />
        <Button onClick={runLoop} disabled={loop.busy}>{loop.busy ? 'Running…' : 'Run revenue loop'}</Button>
      </div>
      <Note error={loop.error} />
      {result && (
        <Panel title="Revenue loop" eyebrow="JUST RAN">
          <p className="text-sm mb-2">{result.summary}</p>
          {result.findings.length > 0 && <ul className="list-disc ml-5 text-sm text-amber-700 dark:text-amber-400">{result.findings.map((f) => <li key={f}>{f}</li>)}</ul>}
          {result.next_actions.length > 0 && <><p className="text-sm font-medium mt-3">Next actions</p><ul className="list-disc ml-5 text-sm">{result.next_actions.map((a) => <li key={a}>{a}</li>)}</ul></>}
          <p className="text-xs text-muted-foreground mt-2">Recorded as KPIs: {result.kpis_recorded.join(', ')}</p>
        </Panel>
      )}
      {metrics.loading ? <Loading /> : metrics.error ? <Note error={metrics.error} /> : m && (
        <>
          {m.revenue.source === 'recorded' && !m.revenue.has_data && !(m.subscriptions as Subscriptions & { has_data?: boolean }).has_data && (
            <Empty title="No revenue recorded yet">Connect Stripe (settings below) or record sales here; every figure on this page is measured, never estimated.</Empty>
          )}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            <Stat label={`Net revenue (${days}d)`} value={money(m.revenue.net, currency)} hint={`gross ${money(m.revenue.gross, currency)}`} />
            <Stat label="Refunds" value={money(m.revenue.refunds, currency)} tone={m.revenue.refunds > 0 ? 'warn' : 'default'} />
            <Stat label="MRR" value={money(m.subscriptions.mrr, currency)} />
            <Stat label="Active subscriptions" value={m.subscriptions.active} hint={`+${m.subscriptions.new} / −${m.subscriptions.cancelled}`} />
            <Stat label="Churn" value={percent(m.subscriptions.churn_rate)} tone={(m.subscriptions.churn_rate ?? 0) > 0.05 ? 'bad' : 'default'} />
            <Stat label="Failed payments" value={m.failed_payments.count} hint={money(m.failed_payments.amount, currency)} tone={m.failed_payments.count ? 'bad' : 'default'} />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Panel title="Daily revenue" eyebrow="PAYMENTS"><DailyBars daily={m.revenue.daily} currency={currency} /></Panel>
            <Panel title="Conversion funnel" eyebrow="FROM KPIS">
              {m.conversion.stages.length === 0 ? <Empty title="Funnel not measured yet">Record visitors, signups and paying customers as KPIs, or connect analytics.</Empty> : (
                <ul className="space-y-2 text-sm">
                  {m.conversion.stages.map((s, i) => (
                    <li key={s.stage} className="flex justify-between">
                      <span className="capitalize">{s.stage}</span>
                      <span>{s.value.toLocaleString()}{i > 0 && m.conversion.conversion[i - 1] ? ` (${percent(m.conversion.conversion[i - 1].rate)})` : ''}</span>
                    </li>
                  ))}
                  <li className="flex justify-between border-t pt-2 font-medium"><span>Overall</span><span>{percent(m.conversion.overall, 2)}</span></li>
                </ul>
              )}
              {m.conversion.missing.length > 0 && <p className="text-xs text-muted-foreground mt-3">Not measured: {m.conversion.missing.join(', ')}</p>}
            </Panel>
          </div>
          {m.failed_payments.items.length > 0 && (
            <Panel title="Failed payments" eyebrow="RECOVERY">
              <table className="w-full text-sm">
                <thead><tr className="text-left text-muted-foreground"><th className="py-1">Customer</th><th>Amount</th><th>Date</th><th>Reason</th></tr></thead>
                <tbody>{m.failed_payments.items.map((f, i) => (
                  <tr key={f.id ?? f.invoice ?? i} className="border-t"><td className="py-1.5">{f.customer ?? '—'}</td><td>{money(f.amount, currency)}</td><td>{f.date ?? '—'}</td><td>{f.reason ?? '—'}</td></tr>
                ))}</tbody>
              </table>
            </Panel>
          )}
        </>
      )}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Panel title="Record a revenue event" eyebrow="MANUAL ENTRY">
          <form onSubmit={submit} className="grid grid-cols-2 gap-3" aria-label="Record revenue event">
            <Field label="Event">
              <select className={inputClass} value={event} onChange={(e) => setEvent(e.target.value)}>
                {EVENTS.map((ev) => <option key={ev} value={ev}>{ev.replace('_', ' ')}</option>)}
              </select>
            </Field>
            <Field label="Amount"><input required type="number" min="0" step="0.01" className={inputClass} value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
            <Field label="Customer id"><input className={inputClass} value={customer} onChange={(e) => setCustomer(e.target.value)} /></Field>
            {event.startsWith('subscription') && (
              <Field label="Billing">
                <select className={inputClass} value={billing} onChange={(e) => setBilling(e.target.value)}>
                  <option value="month">monthly</option><option value="year">yearly</option>
                </select>
              </Field>
            )}
            <div className="col-span-2"><Button type="submit" disabled={record.busy}>Record</Button><Note error={record.error} notice={record.notice} /></div>
          </form>
        </Panel>
        <Panel title="Connections" eyebrow="SOURCES">
          {status.data ? (
            <>
              <ul className="text-sm space-y-1 mb-3">
                <li>Stripe: <Pill tone={status.data.stripe === 'connected' ? 'good' : 'muted'}>{status.data.stripe.replace(/_/g, ' ')}</Pill></li>
                <li>Stripe webhook: <Pill tone={status.data.webhook === 'enabled' ? 'good' : 'muted'}>{status.data.webhook.replace(/_/g, ' ')}</Pill></li>
                <li>Analytics: <Pill tone={status.data.analytics === 'plausible' ? 'good' : 'muted'}>{status.data.analytics}</Pill></li>
              </ul>
              <ul className="list-disc ml-5 text-xs text-muted-foreground space-y-1">
                {status.data.setup.map((s) => <li key={s}>{s.replace('{workspace_id}', workspaceId)}</li>)}
              </ul>
            </>
          ) : <Loading />}
        </Panel>
      </div>
    </div>
  );
}

export default function RevenueOperationsPage() {
  return (
    <WorkspacePage title="Revenue Operations" subtitle="Revenue, MRR, churn, failed payments and conversion, from Stripe or recorded sales; nothing here moves money">
      {(workspaceId) => <RevenueBoard key={workspaceId} workspaceId={workspaceId} />}
    </WorkspacePage>
  );
}
