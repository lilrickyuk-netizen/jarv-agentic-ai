'use client';

import { Loading, Note, Panel, Pill, Stat, useLoad } from '@/components/ops/ui';

interface Overview {
  levels: { level: number; name: string; meaning: string; agents: number; tools: number }[];
  agents: { name: string; category: string; authority: number; tools: number; implemented: boolean }[];
  tools: { total: number; always_approval: string[]; conditional_approval: string[] };
  hard_boundaries: { key: string; title: string }[];
  command_gates: string[];
  sub_agent_rule: string;
  voice_rule: string;
}

export default function PermissionsPage() {
  const { data, error, loading } = useLoad<Overview>('/api/permissions/overview');
  return (
    <div className="min-h-screen bg-background p-6 md:p-8">
      <div className="max-w-7xl mx-auto space-y-6">
        <div>
          <h1 className="text-3xl md:text-4xl font-bold mb-1">Permissions</h1>
          <p className="text-muted-foreground">The authority model JARV enforces, read live from its registries and safety rules</p>
        </div>
        {loading && <Loading />}
        <Note error={error} />
        {data && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Stat label="Agents" value={data.agents.length} />
              <Stat label="Tools" value={data.tools.total} />
              <Stat label="Always need approval" value={data.tools.always_approval.length} />
              <Stat label="Hard boundaries" value={data.hard_boundaries.length} />
            </div>
            <Panel title="Authority levels" eyebrow="LEVELS">
              <table className="w-full text-sm">
                <thead><tr className="text-left text-muted-foreground"><th className="py-1">Level</th><th>What it allows</th><th>Agents</th><th>Tools</th></tr></thead>
                <tbody>{data.levels.map((l) => (
                  <tr key={l.level} className="border-t align-top">
                    <td className="py-1.5 whitespace-nowrap font-medium">{l.level}</td><td>{l.meaning}</td><td>{l.agents}</td><td>{l.tools}</td>
                  </tr>
                ))}</tbody>
              </table>
            </Panel>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <Panel title="Hard boundaries: JARV pauses and asks you" eyebrow="RICHARD ONLY">
                <ul className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-1 text-sm">
                  {data.hard_boundaries.map((b) => <li key={b.key}>• {b.title}</li>)}
                </ul>
                <p className="text-xs text-muted-foreground mt-3">Only the blocked action pauses; safe work carries on and JARV resumes from its checkpoint when you decide. {data.voice_rule}</p>
              </Panel>
              <Panel title="Mission approval gates" eyebrow="COMMAND CENTER">
                <p className="text-sm text-muted-foreground mb-2">A command that does any of these waits on the Approvals page before it starts:</p>
                <div className="flex flex-wrap gap-2">{data.command_gates.map((g) => <Pill key={g} tone="warn">{g}</Pill>)}</div>
                <p className="text-sm mt-4">{data.sub_agent_rule}</p>
              </Panel>
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <Panel title="Agents by authority" eyebrow="AGENTS">
                <ul className="divide-y text-sm max-h-[480px] overflow-auto">{data.agents.map((a) => (
                  <li key={a.name} className="py-1.5 flex items-center gap-2">
                    <Pill tone="info">L{a.authority}</Pill><span className="flex-1">{a.name}</span>
                    <span className="text-xs text-muted-foreground">{a.category} · {a.tools} tools</span>
                  </li>
                ))}</ul>
              </Panel>
              <Panel title="Tools that wait for approval" eyebrow="TOOLS">
                <p className="text-sm font-medium mb-1">Always</p>
                <div className="flex flex-wrap gap-1 mb-4">{data.tools.always_approval.map((t) => <Pill key={t} tone="bad">{t}</Pill>)}</div>
                <p className="text-sm font-medium mb-1">When they would cross a limit (budget, binding commitment, sending without a rule)</p>
                <div className="flex flex-wrap gap-1">{data.tools.conditional_approval.map((t) => <Pill key={t} tone="warn">{t}</Pill>)}</div>
              </Panel>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
