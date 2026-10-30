'use client';

import { useCallback, useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';

interface Check {
  ok: boolean;
  latency_ms: number;
  error?: string;
  [key: string]: unknown;
}

interface Health {
  healthy: boolean;
  failing: string[];
  checks: Record<string, Check>;
  checked_at: string;
}

interface Disk {
  mount: string;
  percent: number;
  free_gb: number;
  total_gb: number;
}

interface Server {
  cpu_percent: number;
  cpu_count: number;
  load_average: number[] | null;
  memory_percent: number;
  memory_total_gb: number;
  memory_available_gb: number;
  disks: Disk[];
  database: { size_bytes?: number; connections?: Record<string, number>; max_connections?: number;
    longest_active_query_seconds?: number; dialect?: string };
}

interface Container {
  id: string;
  name: string;
  service: string;
  state: string;
  status: string;
  health: string | null;
  image: string;
  restartable: boolean;
}

interface Containers {
  available: boolean;
  reason?: string;
  containers: Container[];
}

interface Backup {
  id: string;
  file: string;
  status: string;
  size_bytes: number | null;
  verified: boolean;
  error: string | null;
  reason: string | null;
  started_at: string | null;
  expires_at: string | null;
}

const REFRESH_MS = 15000;

function formatBytes(value: number | null | undefined): string {
  if (!value) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function Meter({ label, percent, detail }: { label: string; percent: number; detail: string }) {
  const tone = percent >= 90 ? 'bg-red-500' : percent >= 75 ? 'bg-amber-500' : 'bg-emerald-500';
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span>{label}</span>
        <span className="font-mono">{percent.toFixed(1)}%</span>
      </div>
      <div className="h-2 rounded bg-muted overflow-hidden">
        <div className={`h-full ${tone}`} style={{ width: `${Math.min(100, Math.max(0, percent))}%` }} />
      </div>
      <p className="text-xs text-muted-foreground mt-1">{detail}</p>
    </div>
  );
}

function StatusDot({ good }: { good: boolean }) {
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${good ? 'bg-emerald-500' : 'bg-red-500'}`} />;
}

export default function InfrastructurePage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [server, setServer] = useState<Server | null>(null);
  const [containers, setContainers] = useState<Containers | null>(null);
  const [backups, setBackups] = useState<Backup[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [restartTarget, setRestartTarget] = useState<string | null>(null);
  const [restartReason, setRestartReason] = useState('');

  const load = useCallback(async () => {
    const [h, s, c, b] = await Promise.all([
      apiClient.get<Health>('/api/operations/health'),
      apiClient.get<Server>('/api/operations/server'),
      apiClient.get<Containers>('/api/operations/containers'),
      apiClient.get<{ backups: Backup[] }>('/api/operations/backups'),
    ]);
    const failed = [h, s, c, b].find((r) => r.error);
    setError(failed?.error ?? null);
    if (h.data) setHealth(h.data);
    if (s.data) setServer(s.data);
    if (c.data) setContainers(c.data);
    if (b.data) setBackups(b.data.backups);
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  const backupNow = async () => {
    setBusy('backup');
    setNotice(null);
    const result = await apiClient.post<Backup & { verification: { verified: boolean } }>(
      '/api/operations/backups', { reason: 'manual backup from the dashboard' });
    setBusy(null);
    await load();
    if (result.error) setError(result.error);
    else if (result.data) {
      setNotice(`Backup ${result.data.file} created (${formatBytes(result.data.size_bytes)}), `
        + (result.data.verification.verified ? 'verified.' : 'verification FAILED.'));
    }
  };

  const restart = async (service: string) => {
    if (restartReason.trim().length < 5) {
      setError('Give a reason of at least 5 characters for the restart.');
      return;
    }
    setBusy(service);
    setNotice(null);
    const result = await apiClient.post<{ containers: string[] }>(
      `/api/operations/services/${encodeURIComponent(service)}/restart`, { reason: restartReason.trim() });
    setBusy(null);
    setRestartTarget(null);
    setRestartReason('');
    await load();
    if (result.error) setError(result.error);
    else setNotice(`Restarted ${service}: ${result.data?.containers.join(', ')}`);
  };

  const database = server?.database;

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-4xl font-bold mb-2">Infrastructure</h1>
            <p className="text-muted-foreground">
              Live health of JARV&apos;s services, the server, containers, and database backups.
              {health && ` Checked ${new Date(health.checked_at).toLocaleTimeString()}.`}
            </p>
          </div>
          <button
            onClick={load}
            className="px-4 py-2 rounded-md border bg-card hover:bg-muted text-sm"
          >
            Refresh
          </button>
        </div>

        {error && <div className="border border-red-500/50 bg-red-500/10 rounded-lg p-4 text-sm">{error}</div>}
        {notice && <div className="border border-emerald-500/50 bg-emerald-500/10 rounded-lg p-4 text-sm">{notice}</div>}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <section className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
              {health && <StatusDot good={health.healthy} />} Services
            </h2>
            {!health && <p className="text-muted-foreground text-sm">Loading…</p>}
            <ul className="space-y-2">
              {health && Object.entries(health.checks).map(([name, check]) => (
                <li key={name} className="flex items-start justify-between gap-3 text-sm">
                  <span className="flex items-center gap-2 capitalize"><StatusDot good={check.ok} />{name}</span>
                  <span className="text-right text-muted-foreground font-mono text-xs">
                    {check.ok ? `${check.latency_ms} ms` : check.error}
                  </span>
                </li>
              ))}
            </ul>
          </section>

          <section className="bg-card border rounded-lg p-6 space-y-4">
            <h2 className="text-xl font-bold">Server</h2>
            {!server && <p className="text-muted-foreground text-sm">Loading…</p>}
            {server && (
              <>
                <Meter label="CPU" percent={server.cpu_percent}
                  detail={`${server.cpu_count} cores${server.load_average
                    ? ` · load ${server.load_average.map((l) => l.toFixed(2)).join(' / ')}` : ''}`} />
                <Meter label="Memory" percent={server.memory_percent}
                  detail={`${server.memory_available_gb} GB free of ${server.memory_total_gb} GB`} />
                {server.disks.map((disk) => (
                  <Meter key={disk.mount} label={`Disk ${disk.mount}`} percent={disk.percent}
                    detail={`${disk.free_gb} GB free of ${disk.total_gb} GB`} />
                ))}
              </>
            )}
          </section>

          <section className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Database</h2>
            {!database && <p className="text-muted-foreground text-sm">Loading…</p>}
            {database && (
              <dl className="grid grid-cols-2 gap-y-2 text-sm">
                {database.size_bytes !== undefined && (<><dt className="text-muted-foreground">Size</dt>
                  <dd className="font-mono">{formatBytes(database.size_bytes)}</dd></>)}
                {database.connections && (<><dt className="text-muted-foreground">Connections</dt>
                  <dd className="font-mono">
                    {Object.values(database.connections).reduce((a, b) => a + b, 0)} / {database.max_connections}
                  </dd></>)}
                {database.longest_active_query_seconds !== undefined && (<>
                  <dt className="text-muted-foreground">Longest query</dt>
                  <dd className="font-mono">{database.longest_active_query_seconds}s</dd></>)}
                {database.dialect && (<><dt className="text-muted-foreground">Engine</dt>
                  <dd className="font-mono">{database.dialect}</dd></>)}
              </dl>
            )}
          </section>
        </div>

        <section className="bg-card border rounded-lg p-6">
          <h2 className="text-xl font-bold mb-4">Containers</h2>
          {containers && !containers.available && (
            <p className="text-sm text-muted-foreground">{containers.reason}</p>
          )}
          {containers?.available && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-muted-foreground border-b">
                  <tr><th className="py-2">Service</th><th>State</th><th>Status</th><th>Image</th><th /></tr>
                </thead>
                <tbody>
                  {containers.containers.map((c) => {
                    const good = c.state === 'running' && c.health !== 'unhealthy';
                    return (
                      <tr key={c.id} className="border-b last:border-0 align-top">
                        <td className="py-2 font-medium"><span className="flex items-center gap-2">
                          <StatusDot good={good} />{c.service}</span></td>
                        <td>{c.state}{c.health ? ` (${c.health})` : ''}</td>
                        <td className="text-muted-foreground">{c.status}</td>
                        <td className="font-mono text-xs">{c.image}</td>
                        <td className="text-right">
                          {c.restartable && restartTarget !== c.service && (
                            <button onClick={() => { setRestartTarget(c.service); setRestartReason(''); }}
                              className="px-3 py-1 rounded border hover:bg-muted">Restart</button>
                          )}
                          {c.restartable && restartTarget === c.service && (
                            <span className="flex gap-2 justify-end items-center">
                              <span className="text-xs text-muted-foreground">Reason</span>
                              <input value={restartReason} onChange={(e) => setRestartReason(e.target.value)}
                                aria-label={`Reason for restarting ${c.service}`} title="Reason for the restart"
                                className="px-2 py-1 rounded border bg-background w-48" />
                              <button disabled={busy === c.service} onClick={() => restart(c.service)}
                                className="px-3 py-1 rounded bg-primary text-primary-foreground disabled:opacity-50">
                                {busy === c.service ? 'Restarting…' : 'Confirm'}
                              </button>
                              <button onClick={() => setRestartTarget(null)}
                                className="px-3 py-1 rounded border hover:bg-muted">Cancel</button>
                            </span>
                          )}
                          {!c.restartable && <span className="text-xs text-muted-foreground">manual only</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="bg-card border rounded-lg p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-bold">Backups</h2>
            <button onClick={backupNow} disabled={busy === 'backup'}
              className="px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm disabled:opacity-50">
              {busy === 'backup' ? 'Backing up…' : 'Back up now'}
            </button>
          </div>
          {backups.length === 0 && (
            <p className="text-sm text-muted-foreground">No backups recorded yet. Scheduled backups run daily.</p>
          )}
          {backups.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-muted-foreground border-b">
                  <tr><th className="py-2">File</th><th>Taken</th><th>Size</th><th>Verified</th><th>Expires</th></tr>
                </thead>
                <tbody>
                  {backups.map((b) => (
                    <tr key={b.id} className="border-b last:border-0">
                      <td className="py-2 font-mono text-xs">{b.file}{b.error && (
                        <span className="block text-red-500 font-sans">{b.error}</span>)}</td>
                      <td>{b.started_at ? new Date(b.started_at).toLocaleString() : '—'}</td>
                      <td>{formatBytes(b.size_bytes)}</td>
                      <td><span className="flex items-center gap-2"><StatusDot good={b.verified} />
                        {b.verified ? 'yes' : b.status}</span></td>
                      <td>{b.expires_at ? new Date(b.expires_at).toLocaleDateString() : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
