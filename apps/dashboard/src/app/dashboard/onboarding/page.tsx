'use client';

import { DraftsPanel } from '@/components/ops/drafts';
import { Empty, Loading, Note, Panel, Pill, useLoad } from '@/components/ops/ui';
import { WorkspacePage } from '@/components/ops/workspace';

interface Flow {
  id: string;
  name: string;
  type: string;
  audience: string | null;
  total_steps: number;
  version: number;
  active: boolean;
}

interface Friction {
  period_days: number;
  flows: Flow[];
  tickets_considered: number;
  findings: { severity: string; source: string; finding: string }[];
  measured: boolean;
  next_step: string;
}

function FrictionPanel({ workspaceId }: { workspaceId: string }) {
  const { data, error, loading } = useLoad<Friction>(`/api/business/${workspaceId}/onboarding/friction?days=30`);
  return (
    <Panel title="Activation friction (last 30 days)" eyebrow="MEASURED">
      {loading ? <Loading /> : error ? <Note error={error} /> : data && (
        <>
          <p className="text-sm text-muted-foreground mb-3">
            {data.flows.length} onboarding flow(s), {data.tickets_considered} support ticket(s) considered. {data.next_step}.
          </p>
          {data.findings.length === 0 ? <Empty title="No friction found" /> : (
            <ul className="space-y-2">
              {data.findings.map((f, i) => (
                <li key={i} className="flex gap-3 items-start">
                  <Pill>{f.severity}</Pill>
                  <span className="text-sm"><span className="text-muted-foreground">{f.source}:</span> {f.finding}</span>
                </li>
              ))}
            </ul>
          )}
          {data.flows.length > 0 && (
            <table className="w-full text-sm mt-4">
              <thead><tr className="text-left text-muted-foreground"><th className="py-1">Flow</th><th>Audience</th><th>Steps</th><th>Version</th><th>State</th></tr></thead>
              <tbody>
                {data.flows.map((f) => (
                  <tr key={f.id} className="border-t">
                    <td className="py-1.5">{f.name}</td><td>{f.audience ?? '—'}</td><td>{f.total_steps}</td><td>v{f.version}</td>
                    <td><Pill>{f.active ? 'active' : 'draft'}</Pill></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </Panel>
  );
}

export default function OnboardingPage() {
  return (
    <WorkspacePage title="Onboarding" subtitle="Where new users get stuck, and the flows, checklists and tours that get them to value">
      {(workspaceId) => (
        <div className="space-y-6" key={workspaceId}>
          <FrictionPanel workspaceId={workspaceId} />
          <DraftsPanel workspaceId={workspaceId} group="onboarding" title="Onboarding drafts"
            hint="Setup checklists come from the project's real scripts; product tours from its real pages." />
        </div>
      )}
    </WorkspacePage>
  );
}
