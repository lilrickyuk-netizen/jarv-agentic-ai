'use client';

import { FormEvent, useMemo, useState } from 'react';
import { Button, Empty, Field, inputClass, Loading, Note, Panel, Pill, useAction, useLoad, when } from '@/components/ops/ui';

interface DraftKind {
  kind: string;
  group: string;
  label: string;
  sections: string[];
}

export interface Draft {
  id: string;
  type: string;
  group: string;
  kind: string | null;
  title: string;
  status: string;
  body: string | null;
  needs_confirmation?: string[];
  created_at: string | null;
}

interface CreatedDraft {
  id: string;
  title: string;
  needs_confirmation: string[];
  generated_by: string;
}

/**
 * Grounded drafts for one business area: choose a document kind, give the brief, and JARV writes it from the
 * workspace's real facts (README, code, commits, KPIs, records). Gaps come back as [confirm: ...] markers.
 * Nothing here is published or sent.
 */
export function DraftsPanel({ workspaceId, group, title, hint }: {
  workspaceId: string; group: string; title: string; hint?: string;
}) {
  const kinds = useLoad<DraftKind[]>('/api/business/kinds');
  const drafts = useLoad<{ drafts: Draft[] }>(`/api/business/${workspaceId}/drafts?group=${group}&limit=30`);
  const action = useAction<CreatedDraft>();
  const options = useMemo(() => (kinds.data ?? []).filter((k) => k.group === group), [kinds.data, group]);
  const [kind, setKind] = useState('');
  const [topic, setTopic] = useState('');
  const [audience, setAudience] = useState('');
  const [tone, setTone] = useState('');
  const [save, setSave] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const chosen = kind || options[0]?.kind || '';
  const sections = options.find((k) => k.kind === chosen)?.sections ?? [];

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!chosen) return;
    const created = await action.run(`/api/business/${workspaceId}/drafts/${chosen}`, {
      topic: topic || undefined, audience: audience || undefined, tone: tone || undefined, save_to_workspace: save,
    });
    if (created) {
      await drafts.reload();
      setOpen(created.id);
      setTopic('');
    }
  };

  return (
    <Panel title={title} eyebrow="GROUNDED DRAFTS">
      {hint && <p className="text-sm text-muted-foreground mb-4">{hint}</p>}
      {kinds.loading ? <Loading /> : options.length === 0 ? <Empty title="No document kinds for this area" /> : (
        <form onSubmit={submit} className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-5" aria-label={`New ${group} draft`}>
          <Field label="Document">
            <select className={inputClass} value={chosen} onChange={(e) => setKind(e.target.value)}>
              {options.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
            </select>
          </Field>
          <Field label="Brief (topic, goal or announcement)" hint="For example: Dark mode is live">
            <input className={inputClass} value={topic} onChange={(e) => setTopic(e.target.value)} />
          </Field>
          <Field label="Audience" hint="For example: new makers">
            <input className={inputClass} value={audience} onChange={(e) => setAudience(e.target.value)} />
          </Field>
          <Field label="Tone" hint="For example: friendly, technical">
            <input className={inputClass} value={tone} onChange={(e) => setTone(e.target.value)} />
          </Field>
          <div className="md:col-span-4 flex flex-wrap items-center gap-4">
            <Button type="submit" disabled={action.busy || !chosen}>{action.busy ? 'Writing…' : 'Write draft'}</Button>
            <label className="text-sm flex items-center gap-2">
              <input type="checkbox" checked={save} onChange={(e) => setSave(e.target.checked)} />
              Also save to the workspace folder
            </label>
            {sections.length > 0 && <span className="text-xs text-muted-foreground">Sections: {sections.join(' · ')}</span>}
          </div>
          <div className="md:col-span-4"><Note error={action.error} /></div>
        </form>
      )}
      {drafts.loading ? <Loading label="Loading drafts" /> : drafts.error ? <Note error={drafts.error} /> :
        (drafts.data?.drafts.length ?? 0) === 0 ? <Empty title="No drafts yet">Write the first one above.</Empty> : (
          <ul className="divide-y border rounded-md">
            {drafts.data!.drafts.map((d) => (
              <li key={d.id} className="p-3">
                <button type="button" className="w-full text-left flex flex-wrap items-center gap-2"
                  aria-expanded={open === d.id} onClick={() => setOpen(open === d.id ? null : d.id)}>
                  <span className="font-medium flex-1 min-w-[200px]">{d.title}</span>
                  {d.kind && <span className="text-xs text-muted-foreground">{d.kind.replace(/^create_/, '').replace(/_/g, ' ')}</span>}
                  <Pill>{d.status}</Pill>
                  {(d.needs_confirmation?.length ?? 0) > 0 && <Pill tone="warn">{d.needs_confirmation!.length} to confirm</Pill>}
                  <span className="text-xs text-muted-foreground">{when(d.created_at)}</span>
                </button>
                {open === d.id && (
                  <div className="mt-3">
                    {(d.needs_confirmation?.length ?? 0) > 0 && (
                      <p className="text-sm text-amber-700 dark:text-amber-400 mb-2">Confirm before use: {d.needs_confirmation!.join('; ')}</p>
                    )}
                    <pre className="whitespace-pre-wrap text-sm bg-muted/50 rounded-md p-3 max-h-[480px] overflow-auto">{d.body || '(no body)'}</pre>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
    </Panel>
  );
}
