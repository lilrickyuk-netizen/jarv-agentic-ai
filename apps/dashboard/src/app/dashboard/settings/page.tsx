'use client';

import { useState } from 'react';
import { Button, Loading, Note, Panel, Pill, Stat, useAction, useLoad, when } from '@/components/ops/ui';

interface Check { ok: boolean; detail: string | null; at: string | null }

interface Service {
  key: string; name: string; group: string; enables: string; configured: boolean;
  settings: string[]; optional_settings: string[]; missing: string[]; example_values: string[];
  setup: string | null; flag: string | null; flag_on: boolean | null;
  checkable: boolean; check_note: string | null; last_check: Check | null;
}

interface VoicePart { backend?: string | null; ready: boolean; setup?: string | null; phrase?: string }

interface Overview {
  system: { service: string; version: string; environment: string; python_version: string; platform: string; checked_at: string };
  readiness: { ready: boolean; database: { status: string; error?: string }; redis: { status: string; redis_version?: string; error?: string } };
  features: Record<string, boolean>;
  limits: Record<string, number | null>;
  safety: { audit_logging: boolean; boundary_reporting: boolean; note: string };
  routing: { order: { provider: string; configured: boolean }[]; primary: string | null; default_model: string; openai_model: string | null; note: string | null };
  services: Service[];
  voice: { speech_to_text: VoicePart; text_to_speech: VoicePart; wake_word: VoicePart; commands: { ready: boolean; route: string } };
  notifications: { name: string; status: string; message: string | null }[];
}

interface CheckResult { service: string; ok: boolean; detail: string; at: string }
interface NotifyResult { ok: boolean; sent: boolean; summary: string }

const LABELS: Record<string, string> = {
  swarm: 'Swarm', self_evolution: 'Self-evolution', company_operator: 'Company operator', self_healing: 'Self-healing', voice: 'Voice',
  default_authority_level: 'Default authority level', max_subagents_per_workspace: 'Sub-agents per workspace',
  max_subagents_global: 'Sub-agents in total', monthly_budget: 'Monthly budget (USD)', log_retention_days: 'Log retention (days)',
};

function ServiceRow({ service, result, onCheck, busy }: {
  service: Service; result?: CheckResult; onCheck: (key: string) => void; busy: boolean;
}) {
  const check: Check | null = result ? { ok: result.ok, detail: result.detail, at: result.at } : service.last_check;
  return (
    <li className="py-3" data-testid={`service-${service.key}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{service.name}</span>
        {service.configured ? <Pill tone="good">configured</Pill> : <Pill tone="muted">not set up</Pill>}
        {check && <Pill tone={check.ok ? 'good' : 'bad'}>{check.ok ? 'check passed' : 'check failed'}</Pill>}
        <span className="ml-auto">
          {service.checkable && (
            <Button kind="secondary" disabled={busy} onClick={() => onCheck(service.key)}>{busy ? 'Checking…' : 'Check'}</Button>
          )}
        </span>
      </div>
      <p className="text-sm text-muted-foreground mt-1">{service.enables}</p>
      {check && <p className={`text-xs mt-1 ${check.ok ? 'text-green-700 dark:text-green-400' : 'text-red-600'}`}>{check.detail} · {when(check.at)}</p>}
      {!service.configured && (
        <div className="text-xs mt-2 space-y-1">
          {service.setup && <p>{service.setup}</p>}
          {service.missing.length > 0 && <p className="text-muted-foreground">Missing: <code>{service.missing.join(', ')}</code></p>}
          {service.flag && !service.flag_on && <p className="text-muted-foreground">Switched off: <code>{service.flag}</code></p>}
        </div>
      )}
      {service.example_values.length > 0 && (
        <p className="text-xs text-amber-700 dark:text-amber-400 mt-1">Still the example value from the template, so treated as unset: <code>{service.example_values.join(', ')}</code></p>
      )}
      {service.configured && !service.checkable && service.check_note && <p className="text-xs text-muted-foreground mt-1">{service.check_note}</p>}
    </li>
  );
}

export default function SettingsPage() {
  const { data, error, loading, reload } = useLoad<Overview>('/api/settings/overview');
  const checkAction = useAction<CheckResult>();
  const notifyAction = useAction<NotifyResult>();
  const [checking, setChecking] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, CheckResult>>({});
  const [notified, setNotified] = useState<NotifyResult | null>(null);

  const runCheck = async (key: string) => {
    setChecking(key);
    const result = await checkAction.run(`/api/settings/services/${key}/check`);
    setChecking(null);
    if (result) setResults((r) => ({ ...r, [key]: result }));
  };

  const sendTest = async (target: string) => {
    setNotified(null);
    const result = await notifyAction.run('/api/integrations/notify', {
      target, dry_run: false, message: 'Test notification from JARV Settings. If you can read this, notifications reach you.',
    });
    if (result) setNotified(result);
  };

  const groups = data ? Array.from(new Set(data.services.map((s) => s.group))) : [];
  const configuredCount = data ? data.services.filter((s) => s.configured).length : 0;

  return (
    <div className="min-h-screen bg-background p-6 md:p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-3xl md:text-4xl font-bold mb-1">Settings</h1>
            <p className="text-muted-foreground">What JARV is connected to, read live. Values are set in the server&apos;s environment and never shown here.</p>
          </div>
          <Button kind="secondary" onClick={() => void reload()} disabled={loading}>Refresh</Button>
        </div>
        {loading && !data && <Loading />}
        <Note error={error} />
        {data && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Stat label="Database" value={data.readiness.database.status} tone={data.readiness.database.status === 'healthy' ? 'good' : 'bad'}
                hint={data.readiness.database.error} />
              <Stat label="Redis" value={data.readiness.redis.status} tone={data.readiness.redis.status === 'healthy' ? 'good' : 'bad'}
                hint={data.readiness.redis.redis_version ? `version ${data.readiness.redis.redis_version}` : data.readiness.redis.error} />
              <Stat label="Primary model provider" value={data.routing.primary ?? 'none'} tone={data.routing.primary ? 'good' : 'bad'}
                hint={data.routing.default_model} />
              <Stat label="Services configured" value={`${configuredCount} of ${data.services.length}`} />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <Panel title="Model failover order" eyebrow="AI ROUTING">
                <ol className="space-y-1 text-sm">
                  {data.routing.order.map((o, i) => (
                    <li key={o.provider} className="flex items-center gap-2">
                      <span className="text-muted-foreground w-5">{i + 1}.</span><span className="font-medium">{o.provider}</span>
                      {o.configured ? <Pill tone="good">key set</Pill> : <Pill tone="muted">skipped: no key</Pill>}
                    </li>
                  ))}
                </ol>
                <p className="text-xs text-muted-foreground mt-3">Set by <code>PROVIDER_ORDER</code>. A provider that is out of credit, rate limited or down hands the mission to the next one.</p>
                <Note error={data.routing.note} />
              </Panel>
              <Panel title="Voice" eyebrow="VOICE">
                <ul className="space-y-2 text-sm">
                  {([['Speech to text', data.voice.speech_to_text], ['Text to speech', data.voice.text_to_speech], ['Wake word', data.voice.wake_word]] as [string, VoicePart][]).map(([label, part]) => (
                    <li key={label}>
                      <div className="flex items-center gap-2"><span className="font-medium">{label}</span>
                        {part.ready ? <Pill tone="good">{part.backend ?? 'ready'}</Pill> : <Pill tone="muted">not set up</Pill>}
                        {label === 'Wake word' && part.phrase && <span className="text-xs text-muted-foreground">“{part.phrase}”</span>}
                      </div>
                      {!part.ready && part.setup && <p className="text-xs text-muted-foreground mt-0.5">{part.setup}</p>}
                    </li>
                  ))}
                </ul>
                <p className="text-xs text-muted-foreground mt-3">Spoken commands become Command Center missions with the same approval gate. Approvals are never taken by voice.</p>
              </Panel>
            </div>

            {groups.map((group) => (
              <Panel key={group} title={group} eyebrow="SERVICES">
                <ul className="divide-y">
                  {data.services.filter((s) => s.group === group).map((s) => (
                    <ServiceRow key={s.key} service={s} result={results[s.key]} onCheck={(k) => void runCheck(k)} busy={checking === s.key} />
                  ))}
                </ul>
                {group === 'Notifications' && (
                  <div className="mt-3 border-t pt-3">
                    <p className="text-sm mb-2">Send yourself a test notification:</p>
                    <div className="flex flex-wrap gap-2">
                      {data.notifications.filter((n) => n.name !== 'local_mock').map((n) => (
                        <Button key={n.name} kind="secondary" disabled={notifyAction.busy || n.status !== 'enabled'} onClick={() => void sendTest(n.name)}>
                          {n.name === 'email_smtp' ? 'Send test email' : 'Send test webhook'}
                        </Button>
                      ))}
                    </div>
                    {notified && <Note error={notified.sent ? null : notified.summary} notice={notified.sent ? notified.summary : null} />}
                    <Note error={notifyAction.error} />
                  </div>
                )}
              </Panel>
            ))}
            <Note error={checkAction.error} />

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <Panel title="Feature switches" eyebrow="FEATURES">
                <ul className="space-y-1 text-sm">{Object.entries(data.features).map(([k, v]) => (
                  <li key={k} className="flex justify-between"><span>{LABELS[k] ?? k}</span>{v ? <Pill tone="good">on</Pill> : <Pill tone="muted">off</Pill>}</li>
                ))}</ul>
              </Panel>
              <Panel title="Limits" eyebrow="LIMITS">
                <ul className="space-y-1 text-sm">{Object.entries(data.limits).map(([k, v]) => (
                  <li key={k} className="flex justify-between"><span>{LABELS[k] ?? k}</span><span className="font-medium">{v ?? 'not set'}</span></li>
                ))}</ul>
              </Panel>
              <Panel title="Safety" eyebrow="LOCKED">
                <ul className="space-y-1 text-sm">
                  <li className="flex justify-between"><span>Audit logging</span><Pill tone={data.safety.audit_logging ? 'good' : 'bad'}>{data.safety.audit_logging ? 'on' : 'off'}</Pill></li>
                  <li className="flex justify-between"><span>Boundary reports</span><Pill tone={data.safety.boundary_reporting ? 'good' : 'bad'}>{data.safety.boundary_reporting ? 'on' : 'off'}</Pill></li>
                </ul>
                <p className="text-xs text-muted-foreground mt-3">{data.safety.note}</p>
              </Panel>
            </div>

            <Panel title="System" eyebrow="SYSTEM">
              <dl className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
                <div><dt className="text-muted-foreground text-xs">Version</dt><dd className="font-medium">{data.system.version}</dd></div>
                <div><dt className="text-muted-foreground text-xs">Environment</dt><dd><Pill tone={data.system.environment === 'production' ? 'good' : 'warn'}>{data.system.environment}</Pill></dd></div>
                <div><dt className="text-muted-foreground text-xs">Python</dt><dd className="font-medium">{data.system.python_version}</dd></div>
                <div className="md:col-span-2"><dt className="text-muted-foreground text-xs">Platform</dt><dd className="font-mono text-xs">{data.system.platform}</dd></div>
                <div><dt className="text-muted-foreground text-xs">Read at</dt><dd>{when(data.system.checked_at)}</dd></div>
              </dl>
              <p className="text-xs text-muted-foreground mt-3">To change a setting, edit the server&apos;s <code>.env.production</code> and restart the backend and worker (<code>docker compose -f docker-compose.prod.yml up -d backend worker</code>).</p>
            </Panel>
          </>
        )}
      </div>
    </div>
  );
}
