'use client';

import { ReactNode, useCallback, useEffect, useRef, useState } from 'react';
import { apiClient } from '@/lib/api';

/** Load JSON from the backend; `path` null means "not ready yet" (for example, no workspace chosen). */
export function useLoad<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(path !== null);
  const latest = useRef(path);

  const reload = useCallback(async () => {
    if (path === null) {
      setData(null);
      setLoading(false);
      return;
    }
    latest.current = path;
    setLoading(true);
    const response = await apiClient.get<T>(path);
    if (latest.current !== path) return;
    if (response.error) {
      setError(response.error);
      setData(null);
    } else {
      setError(null);
      setData(response.data ?? null);
    }
    setLoading(false);
  }, [path]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload };
}

/** Run a POST and report its outcome; `run` resolves to the response data or null on error. */
export function useAction<T = unknown>() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const run = useCallback(async (path: string, body?: unknown, success?: string): Promise<T | null> => {
    setBusy(true);
    setError(null);
    setNotice(null);
    const response = await apiClient.post<T>(path, body);
    setBusy(false);
    if (response.error) {
      setError(response.error);
      return null;
    }
    if (success) setNotice(success);
    return response.data ?? null;
  }, []);

  return { run, busy, error, notice, clear: () => { setError(null); setNotice(null); } };
}

export function Panel({ title, eyebrow, actions, children, className = '' }: {
  title: string; eyebrow?: string; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`bg-card border rounded-lg p-5 ${className}`}>
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          {eyebrow && <p className="text-[11px] font-semibold tracking-widest text-muted-foreground uppercase">{eyebrow}</p>}
          <h2 className="text-lg font-semibold">{title}</h2>
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

export function Stat({ label, value, hint, tone = 'default' }: {
  label: string; value: ReactNode; hint?: string; tone?: 'default' | 'good' | 'warn' | 'bad';
}) {
  const color = { default: '', good: 'text-green-600', warn: 'text-amber-600', bad: 'text-red-600' }[tone];
  return (
    <div className="bg-card border rounded-lg p-4">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
      {hint && <p className="text-xs text-muted-foreground mt-1">{hint}</p>}
    </div>
  );
}

const PILL_TONES: Record<string, string> = {
  good: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
  warn: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  bad: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300',
  info: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  muted: 'bg-muted text-muted-foreground',
};

export function toneFor(value: string | null | undefined): string {
  const v = (value || '').toLowerCase();
  if (['active', 'approved', 'closed_won', 'resolved', 'completed', 'ok', 'healthy', 'positive', 'sent', 'won'].includes(v)) return 'good';
  if (['critical', 'high', 'failed', 'hidden', 'closed_lost', 'negative', 'rejected', 'bad', 'error', 'dispute'].includes(v)) return 'bad';
  if (['medium', 'flagged', 'pending', 'open', 'blocked', 'attention', 'warning', 'proposal', 'negotiation', 'draft', 'escalated', 'waiting_customer', 'needs_approval'].includes(v)) return 'warn';
  if (['new', 'qualified', 'prospecting', 'info', 'planned', 'queued', 'running'].includes(v)) return 'info';
  return 'muted';
}

export function Pill({ children, tone }: { children: ReactNode; tone?: string }) {
  const key = tone ?? (typeof children === 'string' ? toneFor(children) : 'muted');
  return <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${PILL_TONES[key] ?? PILL_TONES.muted}`}>{children}</span>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="border border-dashed rounded-lg p-6 text-center">
      <p className="font-medium">{title}</p>
      {children && <div className="text-sm text-muted-foreground mt-1">{children}</div>}
    </div>
  );
}

export function Note({ error, notice }: { error?: string | null; notice?: string | null }) {
  if (error) return <p role="alert" className="text-sm text-red-600 mt-2">{error}</p>;
  if (notice) return <p role="status" className="text-sm text-green-700 dark:text-green-400 mt-2">{notice}</p>;
  return null;
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return <p className="text-sm text-muted-foreground py-4" aria-busy="true">{label}…</p>;
}

export function Button({ children, onClick, disabled, kind = 'primary', type = 'button' }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean; kind?: 'primary' | 'secondary' | 'danger';
  type?: 'button' | 'submit';
}) {
  const style = {
    primary: 'bg-primary text-primary-foreground hover:opacity-90',
    secondary: 'border bg-background hover:bg-muted',
    danger: 'bg-red-600 text-white hover:bg-red-700',
  }[kind];
  return (
    <button type={type} onClick={onClick} disabled={disabled}
      className={`px-3 py-1.5 rounded-md text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed ${style}`}>
      {children}
    </button>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="block text-xs font-medium text-muted-foreground mb-1">{label}</span>
      {children}
      {hint && <span className="block text-[11px] text-muted-foreground mt-1">{hint}</span>}
    </label>
  );
}

export const inputClass = 'w-full rounded-md border bg-background px-3 py-1.5 text-sm';

export function money(value: number | null | undefined, currency = 'USD'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: 2 }).format(value);
  } catch {
    return `${value.toFixed(2)} ${currency}`;
  }
}

export function percent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return '—';
  return `${(value * 100).toFixed(digits)}%`;
}

export function when(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
