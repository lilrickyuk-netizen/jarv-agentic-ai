'use client';

import { FormEvent, useState } from 'react';
import { DraftsPanel } from '@/components/ops/drafts';
import { Button, Empty, Field, inputClass, Loading, Note, Panel, Pill, useAction, useLoad, when } from '@/components/ops/ui';
import { WorkspacePage } from '@/components/ops/workspace';

interface Message {
  id: string;
  title: string | null;
  channel: string;
  content: string;
  author: string;
  status: string;
  is_moderated: boolean;
  moderation_notes: string | null;
  url: string | null;
  created_at: string | null;
}

interface Moderation {
  decision: string;
  reasons: string[];
}

const STATUSES = ['', 'new', 'approved', 'flagged', 'hidden'];

function Inbox({ workspaceId }: { workspaceId: string }) {
  const [status, setStatus] = useState('new');
  const query = status ? `?status=${status}&limit=100` : '?limit=100';
  const messages = useLoad<Message[]>(`/api/business/${workspaceId}/community/messages${query}`);
  const moderate = useAction<Moderation>();
  const add = useAction<Message>();
  const [author, setAuthor] = useState('');
  const [channel, setChannel] = useState('forum');
  const [content, setContent] = useState('');

  const runModeration = async (id: string) => {
    const result = await moderate.run(`/api/business/${workspaceId}/community/messages/${id}/moderate`);
    if (result) {
      await messages.reload();
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const created = await add.run(`/api/business/${workspaceId}/community/messages`,
      { author_name: author, channel, content }, 'Message added to the inbox');
    if (created) {
      setContent('');
      await messages.reload();
    }
  };

  return (
    <Panel title="Community inbox" eyebrow="MODERATION"
      actions={
        <select aria-label="Status" className="rounded-md border bg-background px-2 py-1 text-sm" value={status}
          onChange={(e) => setStatus(e.target.value)}>
          {STATUSES.map((s) => <option key={s} value={s}>{s || 'all'}</option>)}
        </select>
      }>
      <p className="text-sm text-muted-foreground mb-4">
        Moderation follows the workspace&apos;s community rule plus spam and abuse signals: approve, flag or hide. Nothing is ever deleted.
      </p>
      {messages.loading ? <Loading /> : messages.error ? <Note error={messages.error} /> :
        (messages.data?.length ?? 0) === 0 ? <Empty title={`No ${status || ''} messages`} /> : (
          <ul className="divide-y border rounded-md mb-4">
            {messages.data!.map((m) => (
              <li key={m.id} className="p-3">
                <div className="flex flex-wrap items-center gap-2 mb-1">
                  <span className="font-medium">{m.author}</span>
                  <span className="text-xs text-muted-foreground">{m.channel} · {when(m.created_at)}</span>
                  <Pill>{m.status}</Pill>
                  <span className="flex-1" />
                  {!m.is_moderated && <Button kind="secondary" disabled={moderate.busy} onClick={() => runModeration(m.id)}>Moderate</Button>}
                </div>
                {m.title && <p className="text-sm font-medium">{m.title}</p>}
                <p className="text-sm whitespace-pre-wrap">{m.content}</p>
                {m.moderation_notes && <p className="text-xs text-muted-foreground mt-1">Moderation: {m.moderation_notes}</p>}
              </li>
            ))}
          </ul>
        )}
      <Note error={moderate.error} />
      <form onSubmit={submit} className="grid grid-cols-1 md:grid-cols-4 gap-3 border-t pt-4" aria-label="Add community message">
        <Field label="Author"><input required className={inputClass} value={author} onChange={(e) => setAuthor(e.target.value)} /></Field>
        <Field label="Channel">
          <select className={inputClass} value={channel} onChange={(e) => setChannel(e.target.value)}>
            {['forum', 'discord', 'github', 'slack', 'reddit', 'email', 'google_play', 'reviews'].map((c) => <option key={c}>{c}</option>)}
          </select>
        </Field>
        <Field label="Message"><input required className={inputClass} value={content} onChange={(e) => setContent(e.target.value)} /></Field>
        <div className="flex items-end"><Button type="submit" disabled={add.busy}>Add to inbox</Button></div>
        <div className="md:col-span-4"><Note error={add.error} notice={add.notice} /></div>
      </form>
    </Panel>
  );
}

export default function CommunityPage() {
  return (
    <WorkspacePage title="Community" subtitle="The community inbox, rule-based moderation, and replies and updates drafted from real changes">
      {(workspaceId) => (
        <div className="space-y-6" key={workspaceId}>
          <Inbox workspaceId={workspaceId} />
          <DraftsPanel workspaceId={workspaceId} group="community" title="Community drafts"
            hint="Replies, announcements and updates. Posting publicly from your accounts stays with you." />
        </div>
      )}
    </WorkspacePage>
  );
}
