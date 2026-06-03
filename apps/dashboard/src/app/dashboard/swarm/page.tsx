'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api';

interface SwarmRun {
  id: string;
  workspace_id: string;
  status: string;
  max_sub_agents: number;
  active_sub_agents: number;
  completed_sub_agents: number;
  failed_sub_agents: number;
  total_tokens_used: number;
  total_cost_usd: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export default function SwarmPage() {
  const router = useRouter();
  const [swarmRuns, setSwarmRuns] = useState<SwarmRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await apiClient.get<SwarmRun[]>('/swarm/runs');

      if (response.error) {
        setError(response.error);
      } else if (response.data) {
        setSwarmRuns(response.data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch swarm data');
    } finally {
      setLoading(false);
    }
  };

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      pending: 'bg-gray-100 text-gray-800',
      running: 'bg-blue-100 text-blue-800',
      completed: 'bg-green-100 text-green-800',
      failed: 'bg-red-100 text-red-800',
      cancelled: 'bg-yellow-100 text-yellow-800',
      paused: 'bg-orange-100 text-orange-800',
    };
    return colors[status] || 'bg-gray-100 text-gray-800';
  };

  const activeRuns = swarmRuns.filter(r => r.status === 'running');
  const completedRuns = swarmRuns.filter(r => r.status === 'completed');
  const failedRuns = swarmRuns.filter(r => r.status === 'failed');
  const totalSubAgents = swarmRuns.reduce((sum, r) => sum + r.active_sub_agents, 0);
  const totalTokens = swarmRuns.reduce((sum, r) => sum + r.total_tokens_used, 0);
  const totalCost = swarmRuns.reduce((sum, r) => sum + r.total_cost_usd, 0);

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Swarm System</h1>
          <p className="text-muted-foreground">
            Parallel agent execution and sub-agent management
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
            <p className="font-semibold">Error Loading Swarm Data</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {/* Statistics Cards */}
        {!loading && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Swarm Runs
              </h3>
              <p className="text-3xl font-bold">{swarmRuns.length}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Active Runs
              </h3>
              <p className="text-3xl font-bold text-blue-600">{activeRuns.length}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Sub-Agents
              </h3>
              <p className="text-3xl font-bold text-purple-600">{totalSubAgents}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Completed Runs
              </h3>
              <p className="text-3xl font-bold text-green-600">{completedRuns.length}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Tokens
              </h3>
              <p className="text-3xl font-bold">{totalTokens.toLocaleString()}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Cost
              </h3>
              <p className="text-3xl font-bold">${totalCost.toFixed(4)}</p>
            </div>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && swarmRuns.length === 0 && (
          <div className="bg-card border rounded-lg p-12 text-center">
            <h3 className="text-xl font-semibold mb-2">No Swarm Runs</h3>
            <p className="text-muted-foreground mb-4">
              No swarm executions have been created yet
            </p>
            <p className="text-sm text-muted-foreground">
              Swarm runs enable parallel execution of multiple sub-agents for complex tasks
            </p>
          </div>
        )}

        {/* Swarm Runs List */}
        {!loading && swarmRuns.length > 0 && (
          <div className="space-y-4">
            {swarmRuns.map((run) => (
              <div
                key={run.id}
                className="bg-card border rounded-lg p-6 hover:border-primary transition-colors"
              >
                {/* Header */}
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h3 className="text-lg font-semibold mb-1">
                      Swarm Run {run.id.substring(0, 8)}
                    </h3>
                    <p className="text-sm text-muted-foreground">
                      Workspace: {run.workspace_id.substring(0, 8)}...
                    </p>
                  </div>
                  <span className={`px-3 py-1 text-sm rounded ${getStatusColor(run.status)}`}>
                    {run.status}
                  </span>
                </div>

                {/* Stats Grid */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                  <div>
                    <p className="text-xs text-muted-foreground">Active Sub-Agents</p>
                    <p className="text-lg font-semibold">
                      {run.active_sub_agents}/{run.max_sub_agents}
                    </p>
                    {run.max_sub_agents > 0 && (
                      <div className="w-full bg-gray-200 rounded-full h-1.5 mt-1">
                        <div
                          className="bg-blue-600 h-1.5 rounded-full"
                          style={{
                            width: `${(run.active_sub_agents / run.max_sub_agents) * 100}%`,
                          }}
                        ></div>
                      </div>
                    )}
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">Completed</p>
                    <p className="text-lg font-semibold text-green-600">
                      {run.completed_sub_agents}
                    </p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">Failed</p>
                    <p className="text-lg font-semibold text-red-600">
                      {run.failed_sub_agents}
                    </p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">Tokens Used</p>
                    <p className="text-lg font-semibold">
                      {run.total_tokens_used.toLocaleString()}
                    </p>
                  </div>
                </div>

                {/* Cost */}
                <div className="flex items-center justify-between pt-4 border-t">
                  <div className="text-sm">
                    <span className="text-muted-foreground">Cost: </span>
                    <span className="font-semibold">${run.total_cost_usd.toFixed(6)}</span>
                  </div>
                  <div className="text-sm text-muted-foreground">
                    Created {new Date(run.created_at).toLocaleDateString()}
                  </div>
                </div>

                {/* Timestamps */}
                {(run.started_at || run.completed_at) && (
                  <div className="mt-2 text-xs text-muted-foreground space-y-1">
                    {run.started_at && (
                      <div>Started: {new Date(run.started_at).toLocaleString()}</div>
                    )}
                    {run.completed_at && (
                      <div>Completed: {new Date(run.completed_at).toLocaleString()}</div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Results Count */}
        {!loading && swarmRuns.length > 0 && (
          <div className="mt-6 text-center text-sm text-muted-foreground">
            Showing {swarmRuns.length} swarm run{swarmRuns.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </div>
  );
}
