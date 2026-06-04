'use client';

import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';

interface Checkpoint {
  id: string;
  session_id: string;
  checkpoint_name: string;
  checkpoint_type: string;
  is_safe_state: boolean;
  verification_status: string;
  safety_checks_passed: string[];
  safety_warnings: string[];
  can_resume_from: boolean;
  resume_actions_available: string[];
  created_at: string;
}

interface CheckpointStats {
  total_checkpoints: number;
  safe_checkpoints: number;
  unsafe_checkpoints: number;
  resumable_checkpoints: number;
  by_type: Record<string, number>;
  average_safety_checks: number;
}

export default function CheckpointsPage() {
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [stats, setStats] = useState<CheckpointStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    setLoading(true);
    setError(null);

    try {
      const checkpointsResponse = await apiClient.get<Checkpoint[]>('/api/checkpoints/list');
      if (checkpointsResponse.error) {
        setError(checkpointsResponse.error);
      } else if (checkpointsResponse.data) {
        setCheckpoints(checkpointsResponse.data);
      }

      const statsResponse = await apiClient.get<CheckpointStats>('/api/checkpoints/stats');
      if (!statsResponse.error && statsResponse.data) {
        setStats(statsResponse.data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch checkpoints');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Safe Checkpoints</h1>
          <p className="text-muted-foreground">
            State snapshots, safety verification, and resume points
          </p>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
          </div>
        )}

        {error && (
          <div className="bg-destructive/10 border border-destructive text-destructive px-4 py-3 rounded-lg mb-6">
            <p className="font-semibold">Error Loading Checkpoints</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {!loading && stats && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">Total Checkpoints</h3>
              <p className="text-3xl font-bold">{stats.total_checkpoints}</p>
            </div>
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">Safe States</h3>
              <p className="text-3xl font-bold text-green-600">{stats.safe_checkpoints}</p>
            </div>
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">Resumable</h3>
              <p className="text-3xl font-bold text-blue-600">{stats.resumable_checkpoints}</p>
            </div>
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">Avg Safety Checks</h3>
              <p className="text-3xl font-bold">{stats.average_safety_checks.toFixed(1)}</p>
            </div>
          </div>
        )}

        {!loading && !error && checkpoints.length === 0 && (
          <div className="bg-card border rounded-lg p-12 text-center">
            <h3 className="text-xl font-semibold mb-2">No Checkpoints</h3>
            <p className="text-muted-foreground">No safe checkpoints have been created</p>
          </div>
        )}

        {!loading && checkpoints.length > 0 && (
          <div className="space-y-4">
            {checkpoints.map((checkpoint) => (
              <div key={checkpoint.id} className="bg-card border rounded-lg p-6">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <h3 className="text-lg font-semibold">{checkpoint.checkpoint_name}</h3>
                      {checkpoint.is_safe_state && (
                        <span className="px-2 py-1 text-xs rounded bg-green-100 text-green-800">Safe</span>
                      )}
                      {checkpoint.can_resume_from && (
                        <span className="px-2 py-1 text-xs rounded bg-blue-100 text-blue-800">Resumable</span>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground">Type: {checkpoint.checkpoint_type}</p>
                  </div>
                </div>
                {checkpoint.safety_checks_passed.length > 0 && (
                  <div className="mb-2">
                    <p className="text-xs font-medium text-green-700 mb-1">✓ Safety Checks Passed: {checkpoint.safety_checks_passed.length}</p>
                  </div>
                )}
                {checkpoint.safety_warnings.length > 0 && (
                  <div className="mb-2">
                    <p className="text-xs font-medium text-yellow-700 mb-1">⚠ Warnings: {checkpoint.safety_warnings.length}</p>
                  </div>
                )}
                <div className="text-xs text-muted-foreground">
                  {new Date(checkpoint.created_at).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
