'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api';

interface Workspace {
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
  self_evolution_enabled: boolean;
  company_mode_enabled: boolean;
  company_name: string | null;
  total_tasks: number;
  completed_tasks: number;
  total_tokens_used: number;
  created_at: string;
  updated_at: string;
}

interface WorkspaceStats {
  total_workspaces: number;
  active_workspaces: number;
  archived_workspaces: number;
  total_tasks_across_all: number;
  total_agents_across_all: number;
  company_mode_workspaces: number;
}

export default function WorkspacesPage() {
  const router = useRouter();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [stats, setStats] = useState<WorkspaceStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | 'active' | 'archived'>('all');

  useEffect(() => {
    fetchData();
  }, [filter]);

  const fetchData = async () => {
    setLoading(true);
    setError(null);

    try {
      // Fetch workspaces
      const params = new URLSearchParams();
      if (filter === 'active') {
        params.append('active_only', 'true');
      } else if (filter === 'archived') {
        params.append('include_archived', 'true');
      }

      const workspacesResponse = await apiClient.get<Workspace[]>(
        `/workspaces/list?${params.toString()}`
      );

      if (workspacesResponse.error) {
        setError(workspacesResponse.error);
      } else if (workspacesResponse.data) {
        setWorkspaces(workspacesResponse.data);
      }

      // Fetch stats
      const statsResponse = await apiClient.get<WorkspaceStats>('/workspaces/stats');
      if (!statsResponse.error && statsResponse.data) {
        setStats(statsResponse.data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch workspaces');
    } finally {
      setLoading(false);
    }
  };

  const getCompletionRate = (completed: number, total: number) => {
    if (total === 0) return 0;
    return Math.round((completed / total) * 100);
  };

  const filteredWorkspaces = workspaces.filter(ws => {
    if (filter === 'active') return ws.is_active && !ws.is_archived;
    if (filter === 'archived') return ws.is_archived;
    return true;
  });

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Workspaces</h1>
          <p className="text-muted-foreground">
            Manage your dynamic project workspaces
          </p>
        </div>

        {/* Loading State */}
        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="bg-destructive/10 border border-destructive text-destructive px-4 py-3 rounded-lg mb-6">
            <p className="font-semibold">Error Loading Workspaces</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {/* Statistics Cards */}
        {!loading && stats && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Workspaces
              </h3>
              <p className="text-3xl font-bold">{stats.total_workspaces}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Active Workspaces
              </h3>
              <p className="text-3xl font-bold text-green-600">{stats.active_workspaces}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Company Mode
              </h3>
              <p className="text-3xl font-bold text-blue-600">{stats.company_mode_workspaces}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Tasks
              </h3>
              <p className="text-3xl font-bold">{stats.total_tasks_across_all}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Agents
              </h3>
              <p className="text-3xl font-bold">{stats.total_agents_across_all}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Archived
              </h3>
              <p className="text-3xl font-bold text-gray-600">{stats.archived_workspaces}</p>
            </div>
          </div>
        )}

        {/* Filter Tabs */}
        {!loading && (
          <div className="flex gap-2 mb-6">
            <button
              onClick={() => setFilter('all')}
              className={`px-4 py-2 rounded-md transition-colors ${
                filter === 'all'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-card border hover:border-primary'
              }`}
            >
              All ({workspaces.length})
            </button>
            <button
              onClick={() => setFilter('active')}
              className={`px-4 py-2 rounded-md transition-colors ${
                filter === 'active'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-card border hover:border-primary'
              }`}
            >
              Active ({stats?.active_workspaces || 0})
            </button>
            <button
              onClick={() => setFilter('archived')}
              className={`px-4 py-2 rounded-md transition-colors ${
                filter === 'archived'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-card border hover:border-primary'
              }`}
            >
              Archived ({stats?.archived_workspaces || 0})
            </button>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && filteredWorkspaces.length === 0 && (
          <div className="bg-card border rounded-lg p-12 text-center">
            <h3 className="text-xl font-semibold mb-2">No Workspaces Found</h3>
            <p className="text-muted-foreground mb-4">
              {filter === 'all'
                ? 'Create your first workspace to get started'
                : `No ${filter} workspaces found`}
            </p>
          </div>
        )}

        {/* Workspaces Grid */}
        {!loading && filteredWorkspaces.length > 0 && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {filteredWorkspaces.map((workspace) => (
              <div
                key={workspace.id}
                className="bg-card border rounded-lg p-6 hover:border-primary transition-colors cursor-pointer"
                onClick={() => router.push(`/dashboard/workspaces/${workspace.id}`)}
              >
                {/* Header */}
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h3 className="text-xl font-semibold mb-1">{workspace.name}</h3>
                    <p className="text-sm text-muted-foreground">{workspace.slug}</p>
                  </div>
                  <div className="flex gap-2">
                    {workspace.is_active && !workspace.is_archived && (
                      <span className="px-2 py-1 text-xs rounded bg-green-100 text-green-800">
                        Active
                      </span>
                    )}
                    {workspace.is_archived && (
                      <span className="px-2 py-1 text-xs rounded bg-gray-100 text-gray-800">
                        Archived
                      </span>
                    )}
                    {workspace.company_mode_enabled && (
                      <span className="px-2 py-1 text-xs rounded bg-blue-100 text-blue-800">
                        Company
                      </span>
                    )}
                  </div>
                </div>

                {/* Description */}
                {workspace.description && (
                  <p className="text-sm text-muted-foreground mb-4">
                    {workspace.description}
                  </p>
                )}

                {/* Stats Grid */}
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div>
                    <p className="text-xs text-muted-foreground">Tasks</p>
                    <p className="text-lg font-semibold">
                      {workspace.completed_tasks}/{workspace.total_tasks}
                    </p>
                    {workspace.total_tasks > 0 && (
                      <div className="w-full bg-gray-200 rounded-full h-1.5 mt-1">
                        <div
                          className="bg-primary h-1.5 rounded-full"
                          style={{
                            width: `${getCompletionRate(
                              workspace.completed_tasks,
                              workspace.total_tasks
                            )}%`,
                          }}
                        ></div>
                      </div>
                    )}
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">Sub-agents</p>
                    <p className="text-lg font-semibold">
                      {workspace.active_subagent_count}/{workspace.max_subagents}
                    </p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">Type</p>
                    <p className="text-sm font-medium">{workspace.workspace_type}</p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">Authority</p>
                    <p className="text-sm font-medium">Level {workspace.authority_level}</p>
                  </div>
                </div>

                {/* Features */}
                <div className="flex gap-2 text-xs">
                  {workspace.swarm_enabled && (
                    <span className="px-2 py-1 rounded bg-purple-100 text-purple-800">
                      Swarm
                    </span>
                  )}
                  {workspace.self_evolution_enabled && (
                    <span className="px-2 py-1 rounded bg-orange-100 text-orange-800">
                      Evolution
                    </span>
                  )}
                </div>

                {/* Footer */}
                <div className="mt-4 pt-4 border-t text-xs text-muted-foreground">
                  Updated {new Date(workspace.updated_at).toLocaleDateString()}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
