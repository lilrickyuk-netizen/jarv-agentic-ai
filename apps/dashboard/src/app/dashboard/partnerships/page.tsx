'use client';

import { FormEvent, useState } from 'react';
import { DraftsPanel } from '@/components/ops/drafts';
import { PARTNER_STAGES, Partner, Pipeline } from '@/components/ops/pipeline';
import { Button, Empty, Field, inputClass, Loading, money, Note, Panel, Pill, Stat, useAction, useLoad } from '@/components/ops/ui';
import { WorkspacePage } from '@/components/ops/workspace';

function PartnersPanel({ workspaceId }: { workspaceId: string }) {
  const pipeline = useLoad<Pipeline>(`/api/business/${workspaceId}/pipeline`);
  const action = useAction<Partner>();
  const shortlist = useAction<{ partners: Partner[] }>();
  const [candidates, setCandidates] = useState('');
  const [partnerType, setPartnerType] = useState('technology');

  const move = async (partner: Partner, status: string) => {
    if (status === 'active' && !window.confirm(`Mark ${partner.name} active? That records an agreement in force.`)) return;
    if (await action.run(`/api/business/${workspaceId}/partners/${partner.id}`, { status },
      `${partner.name} is now ${status.replace('_', ' ')}`)) {
      await pipeline.reload();
    }
  };

  const score = async (event: FormEvent) => {
    event.preventDefault();
    const list = candidates.split('\n').map((line) => line.trim()).filter(Boolean).map((line) => {
      const [name, url, ...notes] = line.split('|').map((part) => part.trim());
      return { name, url: url || undefined, notes: notes.join(' ') || undefined, type: partnerType };
    });
    if (list.length === 0) return;
    if (await shortlist.run(`/api/business/${workspaceId}/partners/shortlist`, { partner_type: partnerType, candidates: list },
      `${list.length} candidate(s) scored and added to the shortlist`)) {
      setCandidates('');
      await pipeline.reload();
    }
  };

  const p = pipeline.data;
  return (
    <>
      {p && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Stat label="Partners" value={p.partners.length} />
          <Stat label="Active" value={p.partners_by_status.active ?? 0} tone="good" />
          <Stat label="In discussion" value={(p.partners_by_status.in_discussion ?? 0) + (p.partners_by_status.negotiating ?? 0) + (p.partners_by_status.proposal ?? 0)} />
          <Stat label="Shortlisted" value={p.partners_by_status.shortlisted ?? 0} />
        </div>
      )}
      <Panel title="Partner pipeline" eyebrow="PARTNERSHIPS">
        {pipeline.loading ? <Loading /> : pipeline.error ? <Note error={pipeline.error} /> : p && p.partners.length === 0 ? (
          <Empty title="No partners yet">Score candidates below to start a shortlist.</Empty>
        ) : p && (
          <ul className="divide-y border rounded-md">
            {[...p.partners].sort((a, b) => (b.score ?? 0) - (a.score ?? 0)).map((partner) => (
              <li key={partner.id} className="p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{partner.name}</span>
                  <span className="text-xs text-muted-foreground">{partner.type}</span>
                  <Pill>{partner.status.replace('_', ' ')}</Pill>
                  {partner.score !== null && <Pill tone="info">score {partner.score}</Pill>}
                  {!partner.verified && <Pill tone="warn">suggested, verify</Pill>}
                  <span className="text-xs text-muted-foreground">{money(partner.estimated_value)}</span>
                  <span className="flex-1" />
                  <select aria-label={`Move ${partner.name}`} className="rounded-md border bg-background px-2 py-1 text-xs"
                    value={partner.status} disabled={action.busy} onChange={(e) => move(partner, e.target.value)}>
                    {PARTNER_STAGES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
                  </select>
                </div>
                {partner.reasons && partner.reasons.length > 0 && <p className="text-xs text-muted-foreground mt-1">{partner.reasons.join('; ')}</p>}
              </li>
            ))}
          </ul>
        )}
        <Note error={action.error} notice={action.notice} />
        <form onSubmit={score} className="border-t pt-4 mt-4 space-y-3" aria-label="Score partner candidates">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <Field label="Partner type">
              <select className={inputClass} value={partnerType} onChange={(e) => setPartnerType(e.target.value)}>
                {['technology', 'integration', 'reseller', 'agency', 'content', 'community', 'distribution'].map((t) => <option key={t}>{t}</option>)}
              </select>
            </Field>
            <div className="md:col-span-3">
              <Field label="Candidates, one per line: name | url | notes">
                <textarea className={`${inputClass} min-h-[84px]`} value={candidates} onChange={(e) => setCandidates(e.target.value)}
                  placeholder="Acme Payments | https://acme.example | Stripe alternative used by makers" />
              </Field>
            </div>
          </div>
          <Button type="submit" disabled={shortlist.busy}>{shortlist.busy ? 'Scoring…' : 'Score and shortlist'}</Button>
          <Note error={shortlist.error} notice={shortlist.notice} />
        </form>
      </Panel>
    </>
  );
}

export default function PartnershipsPage() {
  return (
    <WorkspacePage title="Partnerships" subtitle="Candidates scored against the product's stack and audience, the partner pipeline, and outreach drafts">
      {(workspaceId) => (
        <div className="space-y-6" key={workspaceId}>
          <PartnersPanel workspaceId={workspaceId} />
          <DraftsPanel workspaceId={workspaceId} group="partnership" title="Partnership drafts"
            hint="Outreach, meeting briefs, proposals and summaries. Agreements are binding commitments: only you make a partner active." />
        </div>
      )}
    </WorkspacePage>
  );
}
