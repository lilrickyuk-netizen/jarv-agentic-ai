'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api';

interface Agent { name: string; role: string; authority_level: number; tools: string[]; implemented: boolean; }
interface Detail { department: string; slug: string; purpose: string; agent_count: number; agents: Agent[]; }
interface Tasks { total: number; counts: Record<string, number>; recent: { id: string; title: string; status: string; task_type: string }[]; }
interface Ev { item_type?: string; type?: string; severity?: string; title?: string; message?: string; content?: string; created_at: string | null; }

const badge = (s: string) => {
  const c: Record<string, string> = {
    completed: 'bg-green-100 text-green-800', partial: 'bg-orange-100 text-orange-800',
    failed: 'bg-red-100 text-red-800', blocked: 'bg-yellow-100 text-yellow-800',
    waiting_on_approval: 'bg-yellow-100 text-yellow-800', running: 'bg-blue-100 text-blue-800',
    pending: 'bg-gray-100 text-gray-800',
  };
  return c[s] || 'bg-gray-100 text-gray-800';
};

export default function DepartmentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const slug = params?.slug as string;
  const [detail, setDetail] = useState<Detail | null>(null);
  const [tasks, setTasks] = useState<Tasks | null>(null);
  const [tools, setTools] = useState<string[]>([]);
  const [ops, setOps] = useState<Ev[]>([]);
  const [mem, setMem] = useState<Ev[]>([]);
  const [exp, setExp] = useState<Ev[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    (async () => {
      setLoading(true);
      const d = await apiClient.get<Detail>(`/api/agents/departments/${slug}`);
      if (d.error) { setError(d.error); setLoading(false); return; }
      setDetail(d.data || null);
      const [t, tl, o, m, e] = await Promise.all([
        apiClient.get<Tasks>(`/api/agents/departments/${slug}/tasks`),
        apiClient.get<{ tools: string[] }>(`/api/agents/departments/${slug}/tools`),
        apiClient.get<Ev[]>(`/api/agents/departments/${slug}/operations`),
        apiClient.get<Ev[]>(`/api/agents/departments/${slug}/memory`),
        apiClient.get<Ev[]>(`/api/agents/departments/${slug}/experience`),
      ]);
      if (t.data) setTasks(t.data);
      if (tl.data) setTools(tl.data.tools || []);
      if (o.data) setOps(o.data);
      if (m.data) setMem(m.data);
      if (e.data) setExp(e.data);
      setLoading(false);
    })();
  }, [slug]);

  const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
    <section className="bg-card border rounded-lg p-6">
      <h2 className="text-sm font-medium text-muted-foreground mb-3">{title}</h2>
      {children}
    </section>
  );
  const evList = (items: Ev[], empty: string) => items.length ? (
    <ul className="space-y-1 text-sm">
      {items.map((e, i) => (
        <li key={i} className="border-l-2 border-primary/30 pl-2">
          <span className="font-medium">{e.title || e.type || e.item_type}</span>
          {(e.message || e.content) && <span className="text-muted-foreground"> — {(e.message || e.content || '').slice(0, 120)}</span>}
        </li>
      ))}
    </ul>
  ) : <p className="text-sm text-muted-foreground">{empty}</p>;

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-6xl mx-auto space-y-6">
        <button onClick={() => router.push('/dashboard/departments')} className="text-sm text-muted-foreground hover:text-primary">← All departments</button>
        {loading && <div className="flex justify-center py-12"><div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary" /></div>}
        {error && <div className="bg-destructive/10 border border-destructive text-destructive px-4 py-3 rounded-lg">{error}</div>}
        {!loading && detail && (
          <>
            <div>
              <h1 className="text-3xl font-bold mb-1">{detail.department}</h1>
              <p className="text-muted-foreground">{detail.purpose}</p>
            </div>

            {tasks && (
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
                {Object.entries(tasks.counts).map(([k, v]) => (
                  <div key={k} className="bg-card border rounded-lg p-3 text-center">
                    <div className={`text-xs rounded px-1 ${badge(k)}`}>{k}</div>
                    <div className="text-2xl font-bold mt-1">{v}</div>
                  </div>
                ))}
              </div>
            )}

            <Section title={`Agents (${detail.agent_count})`}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {detail.agents.map((a) => (
                  <div key={a.name} className="border rounded-md p-3">
                    <div className="flex justify-between"><span className="font-medium">{a.name}</span>
                      <span className="text-xs text-muted-foreground">L{a.authority_level} · {a.tools.length} tools</span></div>
                    <p className="text-xs text-muted-foreground">{a.role}</p>
                  </div>
                ))}
              </div>
            </Section>

            <Section title={`Tools available (${tools.length})`}>
              <div className="flex flex-wrap gap-1">
                {tools.length ? tools.map((t) => <span key={t} className="text-[10px] bg-muted px-1.5 py-0.5 rounded font-mono">{t}</span>)
                  : <p className="text-sm text-muted-foreground">No tools listed.</p>}
              </div>
            </Section>

            <Section title="Recent tasks">
              {tasks && tasks.recent.length ? (
                <ul className="space-y-1 text-sm">
                  {tasks.recent.map((t) => (
                    <li key={t.id} className="flex justify-between border-b py-1 cursor-pointer hover:text-primary"
                        onClick={() => router.push(`/dashboard/tasks/${t.id}`)}>
                      <span>{t.title}</span><span className={`text-xs rounded px-1 ${badge(t.status)}`}>{t.status}</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="text-sm text-muted-foreground">No tasks yet for this department.</p>}
            </Section>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <Section title="Operations feed">{evList(ops, 'No operations yet.')}</Section>
              <Section title="Memory">{evList(mem, 'No memory linked yet.')}</Section>
              <Section title="Experience / incidents">{evList(exp, 'No experience records yet.')}</Section>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
