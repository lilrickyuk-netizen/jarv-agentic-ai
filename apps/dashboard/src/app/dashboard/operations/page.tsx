'use client';

import { useEffect, useState } from 'react';
import { apiClient, HealthResponse } from '@/lib/api';

interface FeedItem {
  id: string;
  item_type: string;
  severity: string;
  title: string;
  message: string;
  related_task_id: string | null;
  created_at: string;
}

interface Task {
  id: string;
  title: string;
  task_type: string;
  status: string;
  created_at: string;
  completed_at: string | null;
}

export default function OperationsPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError(null);

      const healthRes = await apiClient.checkHealth();
      if (!healthRes.error) setHealth(healthRes.data || null);

      const feedRes = await apiClient.get<FeedItem[]>('/api/operations-feed/list?limit=25');
      if (feedRes.error) setError(feedRes.error);
      else if (feedRes.data) setFeed(feedRes.data);

      const tasksRes = await apiClient.get<Task[]>('/api/tasks/list');
      if (!tasksRes.error && tasksRes.data) setTasks(tasksRes.data);

      setLoading(false);
    };
    load();
    const interval = setInterval(load, 15000); // live refresh
    return () => clearInterval(interval);
  }, []);

  const severityColor = (s: string) => {
    if (s === 'success') return 'bg-green-100 text-green-800';
    if (s === 'warning') return 'bg-yellow-100 text-yellow-800';
    if (s === 'error') return 'bg-red-100 text-red-800';
    return 'bg-blue-100 text-blue-800';
  };

  const statusColor = (s: string) => {
    if (s === 'completed') return 'bg-green-100 text-green-800';
    if (s === 'running' || s === 'pending') return 'bg-blue-100 text-blue-800';
    if (s === 'blocked') return 'bg-yellow-100 text-yellow-800';
    if (s === 'failed') return 'bg-red-100 text-red-800';
    return 'bg-gray-100 text-gray-800';
  };

  const errors = feed.filter((f) => f.severity === 'error');
  const commandEvents = feed.filter((f) => f.item_type === 'command' || f.item_type === 'agent_execution');

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Operations</h1>
          <p className="text-muted-foreground">Live operations feed, task activity, and system health</p>
        </div>

        {loading && feed.length === 0 && (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
          </div>
        )}

        {error && (
          <div className="bg-destructive/10 border border-destructive text-destructive px-4 py-3 rounded-lg mb-6">
            <p className="font-semibold">Error Loading Operations</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {/* System health + summary cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <div className="bg-card border rounded-lg p-6">
            <h3 className="text-sm font-medium text-muted-foreground mb-2">System Health</h3>
            <p className={`text-2xl font-bold ${health?.status === 'healthy' ? 'text-green-600' : 'text-orange-600'}`}>
              {health?.status ?? 'unknown'}
            </p>
            <p className="text-xs text-muted-foreground mt-1">{health?.service ?? 'backend'}</p>
          </div>
          <div className="bg-card border rounded-lg p-6">
            <h3 className="text-sm font-medium text-muted-foreground mb-2">Recent Operations</h3>
            <p className="text-3xl font-bold">{feed.length}</p>
            <p className="text-xs text-muted-foreground mt-1">feed events</p>
          </div>
          <div className="bg-card border rounded-lg p-6">
            <h3 className="text-sm font-medium text-muted-foreground mb-2">Command/Agent Events</h3>
            <p className="text-3xl font-bold text-blue-600">{commandEvents.length}</p>
            <p className="text-xs text-muted-foreground mt-1">execution events</p>
          </div>
          <div className="bg-card border rounded-lg p-6">
            <h3 className="text-sm font-medium text-muted-foreground mb-2">Errors</h3>
            <p className={`text-3xl font-bold ${errors.length ? 'text-red-600' : 'text-green-600'}`}>
              {errors.length}
            </p>
            <p className="text-xs text-muted-foreground mt-1">in recent feed</p>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Live operations feed */}
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Live Operations Feed</h2>
            {feed.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No operations yet. Run a command from the Command Center to see activity here.
              </p>
            ) : (
              <div className="space-y-2 max-h-[28rem] overflow-y-auto">
                {feed.map((item) => (
                  <div key={item.id} className="border rounded-md p-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className={`px-2 py-0.5 text-xs rounded font-semibold ${severityColor(item.severity)}`}>
                        {item.item_type}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {new Date(item.created_at).toLocaleTimeString()}
                      </span>
                    </div>
                    <p className="text-sm font-medium">{item.title}</p>
                    <p className="text-xs text-muted-foreground truncate">{item.message}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Task activity */}
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Task Activity</h2>
            {tasks.length === 0 ? (
              <p className="text-sm text-muted-foreground">No tasks yet.</p>
            ) : (
              <div className="space-y-2 max-h-[28rem] overflow-y-auto">
                {tasks.map((t) => (
                  <div key={t.id} className="border rounded-md p-3 flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{t.title}</p>
                      <p className="text-xs text-muted-foreground">
                        {t.task_type} · {new Date(t.created_at).toLocaleString()}
                      </p>
                    </div>
                    <span className={`px-2 py-1 text-xs rounded font-semibold shrink-0 ${statusColor(t.status)}`}>
                      {t.status}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Workers / scheduler note */}
        <div className="bg-card border rounded-lg p-6 mt-6">
          <h2 className="text-xl font-bold mb-2">Workers &amp; Scheduler</h2>
          <p className="text-sm text-muted-foreground">
            The worker and scheduler run as separate services. Their activity (task execution,
            scheduled operating loops) is reflected in the Live Operations Feed and Task Activity
            above as events are produced.
          </p>
        </div>
      </div>
    </div>
  );
}
