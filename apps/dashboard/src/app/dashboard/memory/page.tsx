'use client';

import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';

interface Memory {
  id: string;
  agent_id: string;
  memory_type: string;
  content: string;
  summary: string | null;
  importance_score: number;
  access_count: number;
  last_accessed_at: string | null;
  session_id: string | null;
  task_id: string | null;
  context: Record<string, any> | null;
  expires_at: string | null;
  is_permanent: boolean;
  created_at: string;
  updated_at: string;
}

interface MemoryStats {
  total_memories: number;
  permanent_memories: number;
  temporary_memories: number;
  expired_memories: number;
  by_type: Record<string, number>;
  by_agent: Record<string, number>;
  average_importance: number;
  total_accesses: number;
  most_accessed_memory_id: string | null;
}

export default function MemoryPage() {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [memoryTypeFilter, setMemoryTypeFilter] = useState<string>('all');
  const [permanentFilter, setPermanentFilter] = useState<string>('all');
  const [minImportance, setMinImportance] = useState<number>(0);
  const [includeExpired, setIncludeExpired] = useState(false);

  useEffect(() => {
    fetchData();
  }, [memoryTypeFilter, permanentFilter, minImportance, includeExpired]);

  const fetchData = async () => {
    setLoading(true);
    setError(null);

    try {
      // Fetch memories
      const params = new URLSearchParams();
      if (memoryTypeFilter !== 'all') {
        params.append('memory_type', memoryTypeFilter);
      }
      if (permanentFilter === 'permanent') {
        params.append('is_permanent', 'true');
      } else if (permanentFilter === 'temporary') {
        params.append('is_permanent', 'false');
      }
      if (minImportance > 0) {
        params.append('min_importance', minImportance.toString());
      }
      if (includeExpired) {
        params.append('include_expired', 'true');
      }

      const memoriesResponse = await apiClient.get<Memory[]>(
        `/api/memory/list?${params.toString()}`
      );

      if (memoriesResponse.error) {
        setError(memoriesResponse.error);
      } else if (memoriesResponse.data) {
        setMemories(memoriesResponse.data);
      }

      // Fetch stats
      const statsResponse = await apiClient.get<MemoryStats>('/api/memory/stats');
      if (!statsResponse.error && statsResponse.data) {
        setStats(statsResponse.data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch memory data');
    } finally {
      setLoading(false);
    }
  };

  const getMemoryTypeColor = (type: string) => {
    const colors: Record<string, string> = {
      episodic: 'bg-blue-100 text-blue-800',
      semantic: 'bg-green-100 text-green-800',
      procedural: 'bg-purple-100 text-purple-800',
      working: 'bg-yellow-100 text-yellow-800',
      long_term: 'bg-indigo-100 text-indigo-800',
    };
    return colors[type] || 'bg-gray-100 text-gray-800';
  };

  const getImportanceColor = (score: number) => {
    if (score >= 0.8) return 'text-red-600 font-bold';
    if (score >= 0.6) return 'text-orange-600 font-semibold';
    if (score >= 0.4) return 'text-yellow-600';
    return 'text-gray-600';
  };

  const isExpired = (expiresAt: string | null) => {
    if (!expiresAt) return false;
    return new Date(expiresAt) <= new Date();
  };

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Agent Memory</h1>
          <p className="text-muted-foreground">
            Knowledge retention, context windows, and memory stores across agents
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
            <p className="font-semibold">Error Loading Memory Data</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {/* Statistics Cards */}
        {!loading && stats && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Memories
              </h3>
              <p className="text-3xl font-bold">{stats.total_memories}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {stats.permanent_memories} permanent
              </p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Temporary Memories
              </h3>
              <p className="text-3xl font-bold text-yellow-600">{stats.temporary_memories}</p>
              {stats.expired_memories > 0 && (
                <p className="text-xs text-red-600 mt-1">{stats.expired_memories} expired</p>
              )}
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Average Importance
              </h3>
              <p className={`text-3xl font-bold ${getImportanceColor(stats.average_importance)}`}>
                {Math.round(stats.average_importance * 100)}%
              </p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Accesses
              </h3>
              <p className="text-3xl font-bold text-blue-600">{stats.total_accesses}</p>
            </div>
          </div>
        )}

        {/* Memory Type Distribution */}
        {!loading && stats && Object.keys(stats.by_type).length > 0 && (
          <div className="bg-card border rounded-lg p-6 mb-8">
            <h2 className="text-2xl font-bold mb-4">Memory Type Distribution</h2>
            <div className="flex flex-wrap gap-3">
              {Object.entries(stats.by_type).map(([type, count]) => (
                <div
                  key={type}
                  className={`px-4 py-2 rounded-lg ${getMemoryTypeColor(type)}`}
                >
                  <span className="font-medium">{type.replace(/_/g, ' ')}</span>
                  <span className="ml-2 font-bold">{count}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Filters */}
        {!loading && (
          <div className="flex flex-col md:flex-row gap-4 mb-6">
            {/* Memory Type Filter */}
            {stats && Object.keys(stats.by_type).length > 0 && (
              <div className="flex-1">
                <label className="block text-sm font-medium mb-2">Memory Type</label>
                <select
                  value={memoryTypeFilter}
                  onChange={(e) => setMemoryTypeFilter(e.target.value)}
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

            {/* Permanent Filter */}
            <div className="flex-1">
              <label className="block text-sm font-medium mb-2">Duration</label>
              <select
                value={permanentFilter}
                onChange={(e) => setPermanentFilter(e.target.value)}
                className="w-full px-3 py-2 border rounded-md bg-card"
              >
                <option value="all">All Memories</option>
                <option value="permanent">Permanent Only</option>
                <option value="temporary">Temporary Only</option>
              </select>
            </div>

            {/* Importance Filter */}
            <div className="flex-1">
              <label className="block text-sm font-medium mb-2">Min Importance</label>
              <select
                value={minImportance}
                onChange={(e) => setMinImportance(parseFloat(e.target.value))}
                className="w-full px-3 py-2 border rounded-md bg-card"
              >
                <option value="0">All (0%)</option>
                <option value="0.4">Medium (40%)</option>
                <option value="0.6">High (60%)</option>
                <option value="0.8">Critical (80%)</option>
              </select>
            </div>

            {/* Include Expired */}
            <div className="flex items-end">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={includeExpired}
                  onChange={(e) => setIncludeExpired(e.target.checked)}
                  className="w-4 h-4"
                />
                <span className="text-sm">Include expired</span>
              </label>
            </div>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && memories.length === 0 && (
          <div className="bg-card border rounded-lg p-12 text-center">
            <h3 className="text-xl font-semibold mb-2">No Memories Found</h3>
            <p className="text-muted-foreground">
              {memoryTypeFilter !== 'all' || permanentFilter !== 'all' || minImportance > 0
                ? 'No memories match the selected filters'
                : 'No memories have been stored yet'}
            </p>
          </div>
        )}

        {/* Memories List */}
        {!loading && memories.length > 0 && (
          <div className="space-y-4">
            {memories.map((memory) => (
              <div
                key={memory.id}
                className={`bg-card border rounded-lg p-6 hover:border-primary transition-colors ${
                  isExpired(memory.expires_at) ? 'opacity-60 border-red-300' : ''
                }`}
              >
                {/* Header */}
                <div className="flex items-start justify-between mb-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <span className={`px-2 py-1 text-xs rounded ${getMemoryTypeColor(memory.memory_type)}`}>
                        {memory.memory_type}
                      </span>
                      {memory.is_permanent && (
                        <span className="px-2 py-1 text-xs rounded bg-indigo-100 text-indigo-800">
                          Permanent
                        </span>
                      )}
                      {isExpired(memory.expires_at) && (
                        <span className="px-2 py-1 text-xs rounded bg-red-100 text-red-800">
                          Expired
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground">
                      Agent: {memory.agent_id.substring(0, 8)}...
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-xs text-muted-foreground">Importance</p>
                    <p className={`text-2xl font-bold ${getImportanceColor(memory.importance_score)}`}>
                      {Math.round(memory.importance_score * 100)}%
                    </p>
                  </div>
                </div>

                {/* Summary */}
                {memory.summary && (
                  <div className="mb-3 p-3 bg-muted rounded-md">
                    <p className="text-sm font-medium text-muted-foreground mb-1">Summary</p>
                    <p className="text-sm">{memory.summary}</p>
                  </div>
                )}

                {/* Content */}
                <div className="mb-4">
                  <p className="text-sm font-medium text-muted-foreground mb-2">Content</p>
                  <p className="text-sm line-clamp-3">{memory.content}</p>
                </div>

                {/* Metadata Grid */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4 pb-4 border-t pt-4">
                  <div>
                    <p className="text-xs text-muted-foreground">Access Count</p>
                    <p className="text-lg font-semibold">{memory.access_count}</p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">Last Accessed</p>
                    <p className="text-sm font-medium">
                      {memory.last_accessed_at
                        ? new Date(memory.last_accessed_at).toLocaleDateString()
                        : 'Never'}
                    </p>
                  </div>

                  <div>
                    <p className="text-xs text-muted-foreground">Created</p>
                    <p className="text-sm font-medium">
                      {new Date(memory.created_at).toLocaleDateString()}
                    </p>
                  </div>

                  {memory.expires_at && !memory.is_permanent && (
                    <div>
                      <p className="text-xs text-muted-foreground">Expires</p>
                      <p className={`text-sm font-medium ${isExpired(memory.expires_at) ? 'text-red-600' : ''}`}>
                        {new Date(memory.expires_at).toLocaleDateString()}
                      </p>
                    </div>
                  )}

                  {memory.session_id && (
                    <div>
                      <p className="text-xs text-muted-foreground">Session</p>
                      <p className="text-xs font-mono">{memory.session_id.substring(0, 8)}...</p>
                    </div>
                  )}

                  {memory.task_id && (
                    <div>
                      <p className="text-xs text-muted-foreground">Task</p>
                      <p className="text-xs font-mono">{memory.task_id.substring(0, 8)}...</p>
                    </div>
                  )}
                </div>

                {/* Context */}
                {memory.context && Object.keys(memory.context).length > 0 && (
                  <div className="pt-4 border-t">
                    <p className="text-sm font-medium mb-2">Context</p>
                    <div className="grid grid-cols-2 gap-2">
                      {Object.entries(memory.context).slice(0, 4).map(([key, value]) => (
                        <div key={key} className="bg-muted rounded p-2">
                          <p className="text-xs text-muted-foreground">
                            {key.replace(/_/g, ' ')}
                          </p>
                          <p className="text-sm font-medium truncate">{String(value)}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Results Count */}
        {!loading && memories.length > 0 && (
          <div className="mt-6 text-center text-sm text-muted-foreground">
            Showing {memories.length} memor{memories.length !== 1 ? 'ies' : 'y'}
          </div>
        )}
      </div>
    </div>
  );
}
