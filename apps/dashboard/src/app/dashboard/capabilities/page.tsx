'use client';

import { useMemo, useState } from 'react';
import { Empty, Loading, Note, Panel, Pill, Stat, inputClass, useLoad } from '@/components/ops/ui';

interface Pack {
  pack: string;
  title: string;
  publisher: string;
  repo: string;
  commit: string;
  licence: string;
  skills: string[];
  blocked: string[];
}

interface Inventory {
  packs: Pack[];
  departments: { role: string; title: string; skills: string[] }[];
  skills_total: number;
  skills_usable: number;
  engine: { lead_model: string; worker_model: string; workers_at_once: number; video_skill: string; creative_check_max_usd: number };
  registries: { tools: number; agents: number };
  upgrades: { when: string; what: string }[];
}

const model = (name: string) => name.replace('claude-', '').replace(/-/g, ' ');

/** What JAI has, read live from its code: the same inventory it answers from when asked what it can do. */
export default function CapabilitiesPage() {
  const { data, error, loading } = useLoad<Inventory>('/api/capabilities');
  const [search, setSearch] = useState('');
  const term = search.trim().toLowerCase();
  const departments = useMemo(() => (data?.departments ?? [])
    .map((d) => ({ ...d, skills: term ? d.skills.filter((s) => s.includes(term)) : d.skills }))
    .filter((d) => !term || d.skills.length > 0 || d.title.toLowerCase().includes(term)), [data, term]);

  return (
    <div className="min-h-screen bg-background p-6 md:p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        <div>
          <h1 className="text-3xl md:text-4xl font-bold mb-1">Capabilities</h1>
          <p className="text-muted-foreground">Every skill, department, tool and upgrade JAI has, read from its code just now.</p>
        </div>
        {loading ? <Loading /> : error ? <Note error={error} /> : data && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <Stat label="Usable skills" value={data.skills_usable} hint={`${data.skills_total} installed`} />
              <Stat label="Skill packs" value={data.packs.length} />
              <Stat label="Tools" value={data.registries.tools || '—'} />
              <Stat label="Agents" value={data.registries.agents || '—'} />
              <Stat label="Workers at once" value={data.engine.workers_at_once} hint={`on ${model(data.engine.worker_model)}`} />
            </div>

            <Panel title="How missions run" eyebrow="Engine">
              <ul className="text-sm space-y-1">
                <li>The specialist leading a mission runs on <b>{model(data.engine.lead_model)}</b>; its workers run on <b>{model(data.engine.worker_model)}</b>, up to {data.engine.workers_at_once} at once.</li>
                <li>New video work runs on the <b>{data.engine.video_skill}</b> skill, then an independent creative check (up to ${data.engine.creative_check_max_usd.toFixed(0)}).</li>
              </ul>
            </Panel>

            <Panel title="Skill packs" eyebrow="Sources">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs text-muted-foreground">
                    <tr><th className="py-2 pr-4">Pack</th><th className="py-2 pr-4">From</th><th className="py-2 pr-4">Licence</th><th className="py-2 pr-4">Version</th><th className="py-2">Skills</th></tr>
                  </thead>
                  <tbody>
                    {data.packs.map((p) => (
                      <tr key={p.pack} className="border-t align-top">
                        <td className="py-2 pr-4 font-medium">{p.title}</td>
                        <td className="py-2 pr-4"><a className="underline" href={`https://github.com/${p.repo}`} target="_blank" rel="noreferrer">{p.publisher}</a></td>
                        <td className="py-2 pr-4"><Pill tone="muted">{p.licence}</Pill></td>
                        <td className="py-2 pr-4 font-mono text-xs">{p.commit}</td>
                        <td className="py-2">{p.skills.length}{p.blocked.length > 0 && <span className="text-xs text-amber-600"> ({p.blocked.length} blocked by AgentShield)</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>

            <Panel title="Each department's skills" eyebrow="Departments"
              actions={<input aria-label="Search skills" placeholder="Search skills" className={inputClass} value={search} onChange={(e) => setSearch(e.target.value)} />}>
              {departments.length === 0 ? <Empty title="No skill matches that search" /> : (
                <div className="grid md:grid-cols-2 gap-4">
                  {departments.map((d) => (
                    <div key={d.role} className="border rounded-md p-3">
                      <p className="font-medium text-sm mb-2">{d.title} <span className="text-muted-foreground">({d.skills.length})</span></p>
                      <div className="flex flex-wrap gap-1">{d.skills.map((s) => <Pill key={s} tone="info">{s}</Pill>)}</div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>

            <Panel title="Upgrades in the last 30 days" eyebrow="History">
              {data.upgrades.length === 0 ? <Empty title="The upgrade history is not readable here" /> : (
                <ul className="text-sm space-y-2">
                  {data.upgrades.map((u, i) => (
                    <li key={`${u.when}-${i}`} className="flex gap-3"><span className="font-mono text-xs text-muted-foreground shrink-0 pt-0.5">{u.when.slice(0, 10)}</span><span>{u.what}</span></li>
                  ))}
                </ul>
              )}
            </Panel>
          </>
        )}
      </div>
    </div>
  );
}
