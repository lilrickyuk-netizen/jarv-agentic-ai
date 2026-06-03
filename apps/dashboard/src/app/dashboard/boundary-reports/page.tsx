'use client';

import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';

interface BoundaryReport {
  id: string;
  session_id: string;
  agent_id: string;
  report_type: string;
  severity: string;
  title: string;
  description: string;
  boundary_type: string;
  attempted_action: string;
  authority_level_required: number;
  authority_level_available: number;
  was_blocked: boolean;
  action_taken: string;
  approval_requested: boolean;
  created_at: string;
}

interface BoundaryReportStats {
  total_reports: number;
  blocked_actions: number;
  by_severity: Record<string, number>;
  by_type: Record<string, number>;
  approval_request_rate: number;
}

export default function BoundaryReportsPage() {
  const [reports, setReports] = useState<BoundaryReport[]>([]);
  const [stats, setStats] = useState<BoundaryReportStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    setLoading(true);
    setError(null);

    try {
      const reportsResponse = await apiClient.get<BoundaryReport[]>('/boundary-reports/list');
      if (reportsResponse.error) {
        setError(reportsResponse.error);
      } else if (reportsResponse.data) {
        setReports(reportsResponse.data);
      }

      const statsResponse = await apiClient.get<BoundaryReportStats>('/boundary-reports/stats');
      if (!statsResponse.error && statsResponse.data) {
        setStats(statsResponse.data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch boundary reports');
    } finally {
      setLoading(false);
    }
  };

  const getSeverityColor = (severity: string) => {
    const colors: Record<string, string> = {
      critical: 'bg-red-100 text-red-800',
      high: 'bg-orange-100 text-orange-800',
      medium: 'bg-yellow-100 text-yellow-800',
      low: 'bg-blue-100 text-blue-800',
    };
    return colors[severity] || 'bg-gray-100 text-gray-800';
  };

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Boundary Reports</h1>
          <p className="text-muted-foreground">
            Boundary violations, access attempts, and security incident tracking
          </p>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
          </div>
        )}

        {error && (
          <div className="bg-destructive/10 border border-destructive text-destructive px-4 py-3 rounded-lg mb-6">
            <p className="font-semibold">Error Loading Boundary Reports</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {!loading && stats && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">Total Reports</h3>
              <p className="text-3xl font-bold">{stats.total_reports}</p>
            </div>
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">Blocked Actions</h3>
              <p className="text-3xl font-bold text-red-600">{stats.blocked_actions}</p>
            </div>
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">Approval Rate</h3>
              <p className="text-3xl font-bold text-yellow-600">{Math.round(stats.approval_request_rate * 100)}%</p>
            </div>
          </div>
        )}

        {!loading && !error && reports.length === 0 && (
          <div className="bg-card border rounded-lg p-12 text-center">
            <h3 className="text-xl font-semibold mb-2">No Boundary Reports</h3>
            <p className="text-muted-foreground">No boundary violations have been recorded</p>
          </div>
        )}

        {!loading && reports.length > 0 && (
          <div className="space-y-4">
            {reports.map((report) => (
              <div key={report.id} className="bg-card border rounded-lg p-6">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <h3 className="text-lg font-semibold">{report.title}</h3>
                      <span className={`px-2 py-1 text-xs rounded ${getSeverityColor(report.severity)}`}>
                        {report.severity}
                      </span>
                      {report.was_blocked && (
                        <span className="px-2 py-1 text-xs rounded bg-red-100 text-red-800">Blocked</span>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground mb-2">{report.description}</p>
                    <p className="text-xs text-muted-foreground">Type: {report.boundary_type}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-xs text-muted-foreground">Authority Gap</p>
                    <p className="text-xl font-bold text-red-600">
                      {report.authority_level_required - report.authority_level_available}
                    </p>
                  </div>
                </div>
                <div className="pt-4 border-t text-xs text-muted-foreground">
                  {new Date(report.created_at).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
