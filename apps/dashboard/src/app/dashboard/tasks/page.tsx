'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api';

interface Task {
  id: string;
  title: string;
  description: string | null;
  task_type: string;
  workspace_id: string;
  assigned_agent_id: string | null;
  status: string;
  priority: number;
  started_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  execution_duration_seconds: number | null;
  tokens_used: number;
  retry_count: number;
  created_at: string;
  updated_at: string;
}

interface TaskStats {
  total_tasks: number;
  pending_tasks: number;
  in_progress_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  total_tokens_used: number;
}

export default function TasksPage() {
  const router = useRouter();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [stats, setStats] = useState<TaskStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('all');

  useEffect(() => {
    fetchData();
  }, [statusFilter]);

  const fetchData = async () => {
    setLoading(true);
    setError(null);

    try {
      // Fetch tasks
      const params = new URLSearchParams();
      if (statusFilter !== 'all') {
        params.append('status', statusFilter);
      }

      const tasksResponse = await apiClient.get<Task[]>(
        `/tasks/list?${params.toString()}`
      );

      if (tasksResponse.error) {
        setError(tasksResponse.error);
      } else if (tasksResponse.data) {
        setTasks(tasksResponse.data);
      }

      // Fetch stats
      const statsResponse = await apiClient.get<TaskStats>('/tasks/stats');
      if (!statsResponse.error && statsResponse.data) {
        setStats(statsResponse.data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch tasks');
    } finally {
      setLoading(false);
    }
  };

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      pending: 'bg-gray-100 text-gray-800',
      in_progress: 'bg-blue-100 text-blue-800',
      completed: 'bg-green-100 text-green-800',
      failed: 'bg-red-100 text-red-800',
      paused: 'bg-yellow-100 text-yellow-800',
      cancelled: 'bg-gray-100 text-gray-800',
    };
    return colors[status] || 'bg-gray-100 text-gray-800';
  };

  const getPriorityColor = (priority: number) => {
    if (priority >= 8) return 'text-red-600 font-bold';
    if (priority >= 5) return 'text-orange-600 font-semibold';
    return 'text-gray-600';
  };

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return 'N/A';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;

    if (hours > 0) return `${hours}h ${minutes}m`;
    if (minutes > 0) return `${minutes}m ${secs}s`;
    return `${secs}s`;
  };

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Tasks</h1>
          <p className="text-muted-foreground">
            Monitor and manage all tasks across workspaces
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
            <p className="font-semibold">Error Loading Tasks</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {/* Statistics Cards */}
        {!loading && stats && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-8">
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Tasks
              </h3>
              <p className="text-3xl font-bold">{stats.total_tasks}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                In Progress
              </h3>
              <p className="text-3xl font-bold text-blue-600">{stats.in_progress_tasks}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Completed
              </h3>
              <p className="text-3xl font-bold text-green-600">{stats.completed_tasks}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Pending
              </h3>
              <p className="text-3xl font-bold text-gray-600">{stats.pending_tasks}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Failed
              </h3>
              <p className="text-3xl font-bold text-red-600">{stats.failed_tasks}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Tokens
              </h3>
              <p className="text-3xl font-bold">{stats.total_tokens_used.toLocaleString()}</p>
            </div>
          </div>
        )}

        {/* Filter Tabs */}
        {!loading && (
          <div className="flex gap-2 mb-6 overflow-x-auto">
            <button
              onClick={() => setStatusFilter('all')}
              className={`px-4 py-2 rounded-md whitespace-nowrap transition-colors ${
                statusFilter === 'all'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-card border hover:border-primary'
              }`}
            >
              All ({stats?.total_tasks || 0})
            </button>
            <button
              onClick={() => setStatusFilter('in_progress')}
              className={`px-4 py-2 rounded-md whitespace-nowrap transition-colors ${
                statusFilter === 'in_progress'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-card border hover:border-primary'
              }`}
            >
              In Progress ({stats?.in_progress_tasks || 0})
            </button>
            <button
              onClick={() => setStatusFilter('pending')}
              className={`px-4 py-2 rounded-md whitespace-nowrap transition-colors ${
                statusFilter === 'pending'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-card border hover:border-primary'
              }`}
            >
              Pending ({stats?.pending_tasks || 0})
            </button>
            <button
              onClick={() => setStatusFilter('completed')}
              className={`px-4 py-2 rounded-md whitespace-nowrap transition-colors ${
                statusFilter === 'completed'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-card border hover:border-primary'
              }`}
            >
              Completed ({stats?.completed_tasks || 0})
            </button>
            <button
              onClick={() => setStatusFilter('failed')}
              className={`px-4 py-2 rounded-md whitespace-nowrap transition-colors ${
                statusFilter === 'failed'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-card border hover:border-primary'
              }`}
            >
              Failed ({stats?.failed_tasks || 0})
            </button>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && tasks.length === 0 && (
          <div className="bg-card border rounded-lg p-12 text-center">
            <h3 className="text-xl font-semibold mb-2">No Tasks Found</h3>
            <p className="text-muted-foreground">
              {statusFilter !== 'all'
                ? `No ${statusFilter} tasks found`
                : 'No tasks have been created yet'}
            </p>
          </div>
        )}

        {/* Tasks List */}
        {!loading && tasks.length > 0 && (
          <div className="space-y-4">
            {tasks.map((task) => (
              <div
                key={task.id}
                className="bg-card border rounded-lg p-6 hover:border-primary transition-colors cursor-pointer"
                onClick={() => router.push(`/dashboard/tasks/${task.id}`)}
              >
                {/* Header */}
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1">
                    <h3 className="text-lg font-semibold mb-1">{task.title}</h3>
                    {task.description && (
                      <p className="text-sm text-muted-foreground line-clamp-2">
                        {task.description}
                      </p>
                    )}
                  </div>
                  <div className="flex gap-2 ml-4">
                    <span className={`px-2 py-1 text-xs rounded ${getStatusColor(task.status)}`}>
                      {task.status}
                    </span>
                    <span className={`px-2 py-1 text-xs ${getPriorityColor(task.priority)}`}>
                      P{task.priority}
                    </span>
                  </div>
                </div>

                {/* Stats Grid */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                  <div>
                    <p className="text-muted-foreground text-xs">Type</p>
                    <p className="font-medium">{task.task_type}</p>
                  </div>

                  <div>
                    <p className="text-muted-foreground text-xs">Duration</p>
                    <p className="font-medium">
                      {formatDuration(task.execution_duration_seconds)}
                    </p>
                  </div>

                  <div>
                    <p className="text-muted-foreground text-xs">Tokens</p>
                    <p className="font-medium">{task.tokens_used.toLocaleString()}</p>
                  </div>

                  <div>
                    <p className="text-muted-foreground text-xs">Retries</p>
                    <p className="font-medium">{task.retry_count}</p>
                  </div>
                </div>

                {/* Footer */}
                <div className="mt-4 pt-4 border-t flex items-center justify-between text-xs text-muted-foreground">
                  <div>
                    Created {new Date(task.created_at).toLocaleDateString()} at{' '}
                    {new Date(task.created_at).toLocaleTimeString()}
                  </div>
                  {task.completed_at && (
                    <div>
                      Completed {new Date(task.completed_at).toLocaleDateString()}
                    </div>
                  )}
                  {task.failed_at && (
                    <div className="text-red-600">
                      Failed {new Date(task.failed_at).toLocaleDateString()}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Results Count */}
        {!loading && tasks.length > 0 && (
          <div className="mt-6 text-center text-sm text-muted-foreground">
            Showing {tasks.length} task{tasks.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </div>
  );
}
