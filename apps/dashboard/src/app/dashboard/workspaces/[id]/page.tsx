'use client';

import { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api';

interface WorkspaceDetail {
  id: string;
  name: string;
  description: string | null;
  slug: string;
  is_active: boolean;
  is_archived: boolean;
  workspace_type: string;
  authority_level: number;
  max_subagents: number;
  active_subagent_count: number;
  swarm_enabled: boolean;
  company_mode_enabled: boolean;
  company_name: string | null;
  total_tasks: number;
  completed_tasks: number;
  total_tokens_used: number;
  created_at: string;
  updated_at: string;
  folder: string | null;
}

export default function WorkspaceDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id as string;

  const [workspace, setWorkspace] = useState<WorkspaceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [folder, setFolder] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    const res = await apiClient.get<WorkspaceDetail>(`/api/workspaces/${id}`);
    if (res.error) setError(res.error);
    else if (res.data) {
      setWorkspace(res.data);
      setFolder(res.data.folder ?? '');
    }
    setLoading(false);
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const saveFolder = async () => {
    const value = folder.trim();
    if (!value) return;
    setBusy(true);
    setMessage(null);
    const res = await apiClient.patch<WorkspaceDetail>(`/api/workspaces/${id}`, { folder: value });
    if (res.error) setMessage({ ok: false, text: res.error });
    else if (res.data) {
      setWorkspace(res.data);
      setFolder(res.data.folder ?? '');
      setMessage({ ok: true, text: `JARV now works in ${res.data.folder}.` });
    }
    setBusy(false);
  };

  const archive = async () => {
    setBusy(true);
    setMessage(null);
    const res = await apiClient.delete<{ archived: boolean }>(`/api/workspaces/${id}`);
    if (res.error) setMessage({ ok: false, text: res.error });
    else setMessage({ ok: true, text: 'Archived. Nothing was deleted; you can restore it here.' });
    setBusy(false);
    load();
  };

  const restore = async () => {
    setBusy(true);
    setMessage(null);
    const res = await apiClient.patch<WorkspaceDetail>(`/api/workspaces/${id}`, { is_archived: false, is_active: true });
    if (res.error) setMessage({ ok: false, text: res.error });
    else setMessage({ ok: true, text: 'Restored.' });
    setBusy(false);
    load();
  };

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-4xl mx-auto">
        <button
          onClick={() => router.push('/dashboard/workspaces')}
          className="text-sm text-muted-foreground hover:text-primary mb-4"
        >
          ← Back to workspaces
        </button>

        {loading && (
          <div className="flex items-center justify-center py-12" role="status" aria-label="Loading workspace">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary"></div>
          </div>
        )}

        {error && (
          <div className="bg-destructive/10 border border-destructive text-destructive px-4 py-3 rounded-lg mb-6" role="alert">
            <p className="font-semibold">Error loading workspace</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {!loading && workspace && (
          <div className="space-y-6">
            <div className="flex items-start justify-between">
              <div>
                <h1 className="text-3xl font-bold">{workspace.name}</h1>
                <p className="text-sm text-muted-foreground">{workspace.slug}</p>
                {workspace.description && <p className="mt-2 text-muted-foreground">{workspace.description}</p>}
              </div>
              <span
                className={`px-2 py-1 text-xs rounded ${
                  workspace.is_archived ? 'bg-gray-100 text-gray-800' : 'bg-green-100 text-green-800'
                }`}
              >
                {workspace.is_archived ? 'Archived' : 'Active'}
              </span>
            </div>

            {message && (
              <div
                role={message.ok ? 'status' : 'alert'}
                className={`px-4 py-3 rounded-lg border ${
                  message.ok ? 'bg-green-50 border-green-300 text-green-900' : 'bg-destructive/10 border-destructive text-destructive'
                }`}
              >
                {message.text}
              </div>
            )}

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="bg-card border rounded-lg p-4">
                <p className="text-xs text-muted-foreground">Tasks</p>
                <p className="text-lg font-semibold">{workspace.completed_tasks}/{workspace.total_tasks}</p>
              </div>
              <div className="bg-card border rounded-lg p-4">
                <p className="text-xs text-muted-foreground">Authority</p>
                <p className="text-lg font-semibold">Level {workspace.authority_level}</p>
              </div>
              <div className="bg-card border rounded-lg p-4">
                <p className="text-xs text-muted-foreground">Type</p>
                <p className="text-lg font-semibold">{workspace.workspace_type}</p>
              </div>
              <div className="bg-card border rounded-lg p-4">
                <p className="text-xs text-muted-foreground">Tokens used</p>
                <p className="text-lg font-semibold">{workspace.total_tokens_used.toLocaleString()}</p>
              </div>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h2 className="text-lg font-semibold mb-1">Folder</h2>
              <p className="text-sm text-muted-foreground mb-3">
                JARV only works inside this folder. If you moved the folder, enter its new location. The workspace keeps
                its tasks, memory and history.
              </p>
              <label htmlFor="workspace-folder" className="text-xs text-muted-foreground">Folder on your computer</label>
              <div className="flex gap-2 mt-1">
                <input
                  id="workspace-folder"
                  value={folder}
                  onChange={(event) => setFolder(event.target.value)}
                  placeholder="C:\Users\you\Projects\MyProject"
                  className="flex-1 border rounded px-3 py-2 bg-background font-mono text-sm"
                />
                <button
                  onClick={saveFolder}
                  disabled={busy || !folder.trim() || folder.trim() === (workspace.folder ?? '')}
                  className="px-4 py-2 rounded bg-primary text-primary-foreground disabled:opacity-50"
                >
                  Save folder
                </button>
              </div>
              {!workspace.folder && <p className="text-xs text-muted-foreground mt-2">This workspace has no folder yet.</p>}
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h2 className="text-lg font-semibold mb-1">{workspace.is_archived ? 'Restore' : 'Archive'}</h2>
              <p className="text-sm text-muted-foreground mb-3">
                {workspace.is_archived
                  ? 'Bring this workspace back so JARV can work in it again.'
                  : 'Archiving hides this workspace from JARV. Nothing is deleted, and the folder is left untouched.'}
              </p>
              {workspace.is_archived ? (
                <button onClick={restore} disabled={busy} className="px-4 py-2 rounded border disabled:opacity-50">
                  Restore workspace
                </button>
              ) : (
                <button onClick={archive} disabled={busy}
                  className="px-4 py-2 rounded border border-destructive text-destructive disabled:opacity-50">
                  Archive workspace
                </button>
              )}
            </div>

            <p className="text-xs text-muted-foreground">
              Created {new Date(workspace.created_at).toLocaleString()} · Updated {new Date(workspace.updated_at).toLocaleString()}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
