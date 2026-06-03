'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api';

interface FeedItem {
  id: string;
  workspace_id: string;
  item_type: string;
  severity: string;
  title: string;
  message: string;
  related_agent_id: string | null;
  related_task_id: string | null;
  is_read: boolean;
  is_archived: boolean;
  requires_action: boolean;
  action_taken: string | null;
  action_taken_at: string | null;
  action_taken_by: string | null;
  created_at: string;
  updated_at: string;
}

interface FeedStats {
  total_items: number;
  unread_items: number;
  requires_action_items: number;
  by_severity: Record<string, number>;
  by_type: Record<string, number>;
  recent_activity_count: number;
}

export default function LiveOperationsFeedPage() {
  const router = useRouter();
  const [feedItems, setFeedItems] = useState<FeedItem[]>([]);
  const [stats, setStats] = useState<FeedStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [showUnreadOnly, setShowUnreadOnly] = useState(false);
  const [showActionRequired, setShowActionRequired] = useState(false);

  useEffect(() => {
    fetchData();
  }, [severityFilter, typeFilter, showUnreadOnly, showActionRequired]);

  const fetchData = async () => {
    setLoading(true);
    setError(null);

    try {
      // Fetch feed items
      const params = new URLSearchParams();
      if (severityFilter !== 'all') {
        params.append('severity', severityFilter);
      }
      if (typeFilter !== 'all') {
        params.append('item_type', typeFilter);
      }
      if (showUnreadOnly) {
        params.append('is_read', 'false');
      }
      if (showActionRequired) {
        params.append('requires_action', 'true');
      }

      const feedResponse = await apiClient.get<FeedItem[]>(
        `/operations-feed/list?${params.toString()}`
      );

      if (feedResponse.error) {
        setError(feedResponse.error);
      } else if (feedResponse.data) {
        setFeedItems(feedResponse.data);
      }

      // Fetch stats
      const statsResponse = await apiClient.get<FeedStats>('/operations-feed/stats');
      if (!statsResponse.error && statsResponse.data) {
        setStats(statsResponse.data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch operations feed');
    } finally {
      setLoading(false);
    }
  };

  const getSeverityColor = (severity: string) => {
    const colors: Record<string, string> = {
      critical: 'bg-red-100 text-red-800 border-red-200',
      error: 'bg-red-50 text-red-700 border-red-100',
      warning: 'bg-yellow-100 text-yellow-800 border-yellow-200',
      info: 'bg-blue-100 text-blue-800 border-blue-200',
      success: 'bg-green-100 text-green-800 border-green-200',
    };
    return colors[severity] || 'bg-gray-100 text-gray-800 border-gray-200';
  };

  const getSeverityIcon = (severity: string) => {
    const icons: Record<string, string> = {
      critical: '🔴',
      error: '❌',
      warning: '⚠️',
      info: 'ℹ️',
      success: '✅',
    };
    return icons[severity] || '📋';
  };

  const getTypeIcon = (type: string) => {
    const icons: Record<string, string> = {
      agent_action: '🤖',
      task_update: '📋',
      system_event: '⚙️',
      error_occurred: '❌',
      alert: '🚨',
      notification: '🔔',
      deployment: '🚀',
      security: '🔒',
    };
    return icons[type] || '📊';
  };

  const formatTimeAgo = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);

    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  };

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Live Operations Feed</h1>
          <p className="text-muted-foreground">
            Real-time updates, events, and alerts from all system operations
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
            <p className="font-semibold">Error Loading Operations Feed</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {/* Statistics Cards */}
        {!loading && stats && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Items
              </h3>
              <p className="text-3xl font-bold">{stats.total_items}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {stats.recent_activity_count} in last 24h
              </p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Unread Items
              </h3>
              <p className="text-3xl font-bold text-blue-600">{stats.unread_items}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Requires Action
              </h3>
              <p className="text-3xl font-bold text-red-600">{stats.requires_action_items}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Activity Rate
              </h3>
              <p className="text-3xl font-bold text-green-600">
                {Math.round((stats.recent_activity_count / stats.total_items) * 100)}%
              </p>
              <p className="text-xs text-muted-foreground mt-1">24h activity</p>
            </div>
          </div>
        )}

        {/* Severity Distribution */}
        {!loading && stats && Object.keys(stats.by_severity).length > 0 && (
          <div className="bg-card border rounded-lg p-6 mb-8">
            <h2 className="text-2xl font-bold mb-4">By Severity</h2>
            <div className="flex flex-wrap gap-3">
              {Object.entries(stats.by_severity).map(([severity, count]) => (
                <div
                  key={severity}
                  className={`px-4 py-2 rounded-lg border ${getSeverityColor(severity)}`}
                >
                  <span className="mr-2">{getSeverityIcon(severity)}</span>
                  <span className="font-medium">{severity}</span>
                  <span className="ml-2 font-bold">{count}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Type Distribution */}
        {!loading && stats && Object.keys(stats.by_type).length > 0 && (
          <div className="bg-card border rounded-lg p-6 mb-8">
            <h2 className="text-2xl font-bold mb-4">By Type</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {Object.entries(stats.by_type).map(([type, count]) => (
                <div
                  key={type}
                  className="px-4 py-3 rounded-lg bg-muted border hover:border-primary transition-colors"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span>{getTypeIcon(type)}</span>
                    <span className="text-sm font-medium">{type.replace(/_/g, ' ')}</span>
                  </div>
                  <p className="text-2xl font-bold">{count}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Filters */}
        {!loading && (
          <div className="flex flex-col md:flex-row gap-4 mb-6">
            {/* Severity Filter */}
            {stats && Object.keys(stats.by_severity).length > 0 && (
              <div className="flex-1">
                <label className="block text-sm font-medium mb-2">Severity</label>
                <select
                  value={severityFilter}
                  onChange={(e) => setSeverityFilter(e.target.value)}
                  className="w-full px-3 py-2 border rounded-md bg-card"
                >
                  <option value="all">All Severities</option>
                  {Object.keys(stats.by_severity).map((severity) => (
                    <option key={severity} value={severity}>
                      {severity}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Type Filter */}
            {stats && Object.keys(stats.by_type).length > 0 && (
              <div className="flex-1">
                <label className="block text-sm font-medium mb-2">Type</label>
                <select
                  value={typeFilter}
                  onChange={(e) => setTypeFilter(e.target.value)}
                  className="w-full px-3 py-2 border rounded-md bg-card"
                >
                  <option value="all">All Types</option>
                  {Object.keys(stats.by_type).map((type) => (
                    <option key={type} value={type}>
                      {type.replace(/_/g, ' ')}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Quick Filters */}
            <div className="flex flex-col gap-2 justify-end">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={showUnreadOnly}
                  onChange={(e) => setShowUnreadOnly(e.target.checked)}
                  className="w-4 h-4"
                />
                <span className="text-sm">Unread only</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={showActionRequired}
                  onChange={(e) => setShowActionRequired(e.target.checked)}
                  className="w-4 h-4"
                />
                <span className="text-sm">Requires action</span>
              </label>
            </div>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && feedItems.length === 0 && (
          <div className="bg-card border rounded-lg p-12 text-center">
            <h3 className="text-xl font-semibold mb-2">No Operations Found</h3>
            <p className="text-muted-foreground">
              {severityFilter !== 'all' || typeFilter !== 'all' || showUnreadOnly || showActionRequired
                ? 'No operations match the selected filters'
                : 'No operations have been recorded yet'}
            </p>
          </div>
        )}

        {/* Feed Items List */}
        {!loading && feedItems.length > 0 && (
          <div className="space-y-3">
            {feedItems.map((item) => (
              <div
                key={item.id}
                className={`bg-card border rounded-lg p-5 hover:border-primary transition-colors ${
                  !item.is_read ? 'border-l-4 border-l-blue-500' : ''
                } ${item.requires_action ? 'border-r-4 border-r-red-500' : ''}`}
              >
                {/* Header */}
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-start gap-3 flex-1">
                    <span className="text-2xl">{getTypeIcon(item.item_type)}</span>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <h3 className="font-semibold text-lg">{item.title}</h3>
                        {!item.is_read && (
                          <span className="px-2 py-0.5 text-xs rounded bg-blue-100 text-blue-800">
                            NEW
                          </span>
                        )}
                        {item.requires_action && (
                          <span className="px-2 py-0.5 text-xs rounded bg-red-100 text-red-800">
                            ACTION REQUIRED
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-muted-foreground mb-2">{item.message}</p>
                      <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                        <span>Type: {item.item_type.replace(/_/g, ' ')}</span>
                        {item.related_agent_id && (
                          <span>Agent: {item.related_agent_id.substring(0, 8)}...</span>
                        )}
                        {item.related_task_id && (
                          <span>Task: {item.related_task_id.substring(0, 8)}...</span>
                        )}
                        <span>{formatTimeAgo(item.created_at)}</span>
                      </div>
                    </div>
                  </div>
                  <div className={`px-3 py-1.5 rounded-lg text-sm border ${getSeverityColor(item.severity)}`}>
                    <span className="mr-1">{getSeverityIcon(item.severity)}</span>
                    <span className="font-medium">{item.severity}</span>
                  </div>
                </div>

                {/* Action Taken */}
                {item.action_taken && (
                  <div className="mt-3 pt-3 border-t bg-green-50 -mx-5 -mb-5 px-5 py-3 rounded-b-lg">
                    <p className="text-sm font-medium text-green-800 mb-1">✓ Action Taken</p>
                    <p className="text-sm text-green-700">{item.action_taken}</p>
                    {item.action_taken_at && (
                      <p className="text-xs text-green-600 mt-1">
                        {new Date(item.action_taken_at).toLocaleString()}
                      </p>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Results Count */}
        {!loading && feedItems.length > 0 && (
          <div className="mt-6 text-center text-sm text-muted-foreground">
            Showing {feedItems.length} operation{feedItems.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </div>
  );
}
