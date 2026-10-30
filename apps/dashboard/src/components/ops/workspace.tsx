'use client';

import { ReactNode, useEffect, useState } from 'react';
import { Empty, Loading, useLoad } from '@/components/ops/ui';

export interface WorkspaceSummary {
  id: string;
  name: string;
  slug: string;
  type: string;
  is_active: boolean;
  company_mode: boolean;
  company_name: string | null;
  has_folder: boolean;
}

const STORAGE_KEY = 'jarv.workspace';

function remembered(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function remember(id: string) {
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    // Storage can be unavailable (private mode); the choice then lasts for this page only.
  }
}

/** The signed-in operator's workspaces and the one chosen for business pages (remembered per browser). */
export function useWorkspace() {
  const { data, error, loading } = useLoad<WorkspaceSummary[]>('/api/workspaces/mine');
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);

  useEffect(() => {
    if (!data || data.length === 0) return;
    const saved = remembered();
    const pick = data.find((w) => w.id === saved) ?? data.find((w) => w.company_mode) ?? data[0];
    setWorkspaceId((current) => (current && data.some((w) => w.id === current) ? current : pick.id));
  }, [data]);

  const choose = (id: string) => {
    setWorkspaceId(id);
    remember(id);
  };

  return { workspaces: data ?? [], workspaceId, choose, error, loading,
           workspace: (data ?? []).find((w) => w.id === workspaceId) ?? null };
}

/** Standard frame for a workspace-scoped page: heading, workspace picker, and the page body once one is chosen. */
export function WorkspacePage({ title, subtitle, children }: {
  title: string; subtitle: string; children: (workspaceId: string) => ReactNode;
}) {
  const { workspaces, workspaceId, choose, error, loading } = useWorkspace();
  return (
    <div className="min-h-screen bg-background p-6 md:p-8">
      <div className="max-w-7xl mx-auto">
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4 mb-6">
          <div>
            <h1 className="text-3xl md:text-4xl font-bold mb-1">{title}</h1>
            <p className="text-muted-foreground">{subtitle}</p>
          </div>
          {workspaces.length > 0 && (
            <label className="text-sm">
              <span className="block text-xs font-medium text-muted-foreground mb-1">Workspace</span>
              <select aria-label="Workspace" className="rounded-md border bg-background px-3 py-1.5 text-sm min-w-[220px]"
                value={workspaceId ?? ''} onChange={(event) => choose(event.target.value)}>
                {workspaces.map((w) => <option key={w.id} value={w.id}>{w.company_name || w.name}</option>)}
              </select>
            </label>
          )}
        </div>
        {loading && <Loading label="Loading workspaces" />}
        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
        {!loading && !error && workspaces.length === 0 && (
          <Empty title="No workspace yet">
            Register a project on the <a className="underline" href="/dashboard/workspaces">Workspaces</a> page or give JARV a
            mission on the <a className="underline" href="/dashboard/command">Command</a> page; its workspace appears here.
          </Empty>
        )}
        {workspaceId && children(workspaceId)}
      </div>
    </div>
  );
}
