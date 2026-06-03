'use client';

import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';

interface Approval {
  id: string;
  user_id: string;
  session_id: string;
  approval_type: string;
  action_description: string;
  action_details: Record<string, any>;
  authority_level_required: number;
  status: string;
  approved: boolean | null;
  approved_at: string | null;
  rejected_at: string | null;
  response_message: string | null;
  executed: boolean;
  executed_at: string | null;
  execution_error: string | null;
  expires_at: string | null;
  is_expired: boolean;
  created_at: string;
}

interface ApprovalStats {
  total_approvals: number;
  pending_approvals: number;
  approved_approvals: number;
  rejected_approvals: number;
  executed_approvals: number;
  expired_approvals: number;
  by_type: Record<string, number>;
  average_response_time_minutes: number;
}

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [stats, setStats] = useState<ApprovalStats | null>(null);
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
      const params = new URLSearchParams();
      if (statusFilter !== 'all') {
        params.append('status', statusFilter);
      }

      const approvalsResponse = await apiClient.get<Approval[]>(`/approvals/list?${params.toString()}`);
      if (approvalsResponse.error) {
        setError(approvalsResponse.error);
      } else if (approvalsResponse.data) {
        setApprovals(approvalsResponse.data);
      }

      const statsResponse = await apiClient.get<ApprovalStats>('/approvals/stats');
      if (!statsResponse.error && statsResponse.data) {
        setStats(statsResponse.data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch approvals');
    } finally {
      setLoading(false);
    }
  };

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      pending: 'bg-yellow-100 text-yellow-800',
      approved: 'bg-green-100 text-green-800',
      rejected: 'bg-red-100 text-red-800',
    };
    return colors[status] || 'bg-gray-100 text-gray-800';
  };

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Approvals</h1>
          <p className="text-muted-foreground">
            Action approval requests, authorization workflow, and execution tracking
          </p>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
          </div>
        )}

        {error && (
          <div className="bg-destructive/10 border border-destructive text-destructive px-4 py-3 rounded-lg mb-6">
            <p className="font-semibold">Error Loading Approvals</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {!loading && stats && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">Total Approvals</h3>
              <p className="text-3xl font-bold">{stats.total_approvals}</p>
            </div>
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">Pending</h3>
              <p className="text-3xl font-bold text-yellow-600">{stats.pending_approvals}</p>
            </div>
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">Approved</h3>
              <p className="text-3xl font-bold text-green-600">{stats.approved_approvals}</p>
            </div>
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">Executed</h3>
              <p className="text-3xl font-bold text-blue-600">{stats.executed_approvals}</p>
            </div>
          </div>
        )}

        {!loading && (
          <div className="flex gap-2 mb-6">
            <button
              onClick={() => setStatusFilter('all')}
              className={`px-4 py-2 rounded-md ${statusFilter === 'all' ? 'bg-primary text-primary-foreground' : 'bg-card border'}`}
            >
              All
            </button>
            <button
              onClick={() => setStatusFilter('pending')}
              className={`px-4 py-2 rounded-md ${statusFilter === 'pending' ? 'bg-primary text-primary-foreground' : 'bg-card border'}`}
            >
              Pending
            </button>
            <button
              onClick={() => setStatusFilter('approved')}
              className={`px-4 py-2 rounded-md ${statusFilter === 'approved' ? 'bg-primary text-primary-foreground' : 'bg-card border'}`}
            >
              Approved
            </button>
          </div>
        )}

        {!loading && !error && approvals.length === 0 && (
          <div className="bg-card border rounded-lg p-12 text-center">
            <h3 className="text-xl font-semibold mb-2">No Approvals Found</h3>
            <p className="text-muted-foreground">No approval requests match the selected filters</p>
          </div>
        )}

        {!loading && approvals.length > 0 && (
          <div className="space-y-4">
            {approvals.map((approval) => (
              <div key={approval.id} className="bg-card border rounded-lg p-6">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <h3 className="text-lg font-semibold">{approval.approval_type.replace(/_/g, ' ')}</h3>
                      <span className={`px-2 py-1 text-xs rounded ${getStatusColor(approval.status)}`}>
                        {approval.status}
                      </span>
                      {approval.executed && (
                        <span className="px-2 py-1 text-xs rounded bg-blue-100 text-blue-800">Executed</span>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground">{approval.action_description}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-xs text-muted-foreground">Authority Level</p>
                    <p className="text-2xl font-bold text-red-600">{approval.authority_level_required}</p>
                  </div>
                </div>
                <div className="text-xs text-muted-foreground">
                  Created {new Date(approval.created_at).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        )}

        {!loading && approvals.length > 0 && (
          <div className="mt-6 text-center text-sm text-muted-foreground">
            Showing {approvals.length} approval{approvals.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </div>
  );
}
