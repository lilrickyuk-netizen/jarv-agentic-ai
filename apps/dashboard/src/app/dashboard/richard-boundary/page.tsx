'use client';

/**
 * Richard Boundary Operator — operational control surface (Repair 10).
 *
 * Every value on this page comes from the real authenticated backend API
 * (/api/richard/*). There is no static demo data, no hardcoded count, and no
 * fake approval/resume state: approve/reject/resume buttons call the real
 * endpoints and the page re-fetches the persisted result.
 */

import { useCallback, useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';

interface BoundaryReportSummary {
  id: string;
  boundary_type: string;
  severity: string;
  title: string;
  attempted_action: string;
  was_blocked: boolean;
  action_taken: string;
  resolution: string | null;
  workspace_id: string | null;
  task_id: string | null;
  session_id: string;
  approval_id: string | null;
  created_at: string | null;
}

interface PendingDecision {
  approval_id: string;
  approval_type: string;
  action_description: string;
  boundary_type: string | null;
  boundary_report_id: string | null;
  workspace_id: string | null;
  task_id: string | null;
  session_id: string;
  status?: string;
  expires_at?: string | null;
  created_at: string | null;
}

interface BoundaryCase {
  report: BoundaryReportSummary;
  description: string;
  boundary_type: string;
  severity: string;
  authority_level_required: number;
  authority_level_available: number;
  safe_work_continuing: string[];
  workflow_state: string;
  pending_approval: Record<string, any> | null;
  richard_decision: Record<string, any> | null;
  approval_window: Record<string, any> | null;
  checkpoint: Record<string, any> | null;
  resume_history: Record<string, any>[];
}

interface AuditEntry {
  id: string;
  action: string;
  action_category: string;
  actor_type: string;
  description: string;
  target_type: string | null;
  target_id: string | null;
  success: boolean;
  created_at: string | null;
}

export default function RichardBoundaryPage() {
  const [reports, setReports] = useState<BoundaryReportSummary[]>([]);
  const [pending, setPending] = useState<PendingDecision[]>([]);
  const [selected, setSelected] = useState<BoundaryCase | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState<string | null>(null);
  const [actionResult, setActionResult] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [reportsRes, pendingRes] = await Promise.all([
        apiClient.get<BoundaryReportSummary[]>('/api/richard/reports?limit=50'),
        apiClient.get<PendingDecision[]>('/api/richard/pending'),
      ]);
      if (reportsRes.error) {
        setError(reportsRes.error);
      } else {
        setReports(reportsRes.data || []);
      }
      if (!pendingRes.error) {
        setPending(pendingRes.data || []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load boundary data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const openCase = async (reportId: string) => {
    setActionResult(null);
    const [caseRes, auditRes] = await Promise.all([
      apiClient.get<BoundaryCase>(`/api/richard/reports/${reportId}`),
      apiClient.get<{ entries: AuditEntry[] }>(`/api/richard/reports/${reportId}/audit`),
    ]);
    if (caseRes.error) {
      setError(caseRes.error);
      return;
    }
    setSelected(caseRes.data || null);
    setAudit(auditRes.data?.entries || []);
  };

  const decide = async (reportId: string, approve: boolean) => {
    setActing(reportId + (approve ? 'approve' : 'reject'));
    setActionResult(null);
    const res = await apiClient.post(`/api/richard/reports/${reportId}/decision`, {
      approve,
      reason: `${approve ? 'Approved' : 'Rejected'} from Richard Boundary control surface`,
    });
    setActionResult(res.error ? `Decision failed: ${res.error}` : `Decision recorded: ${approve ? 'approved' : 'rejected'}`);
    setActing(null);
    await fetchData();
    await openCase(reportId);
  };

  const resume = async (reportId: string) => {
    setActing(reportId + 'resume');
    setActionResult(null);
    const res = await apiClient.post<{ status?: string; reason?: string }>(
      `/api/richard/reports/${reportId}/resume`, {});
    setActionResult(res.error
      ? `Resume refused: ${res.error}`
      : `Resume result: ${res.data?.status || 'unknown'}`);
    setActing(null);
    await fetchData();
    await openCase(reportId);
  };

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-4xl font-bold mb-2">Richard Boundary Operator</h1>
            <p className="text-muted-foreground">
              Hard-boundary pauses, approvals, checkpoints and resumes — live backend data
            </p>
          </div>
          <button onClick={fetchData} className="px-4 py-2 border rounded-lg hover:bg-muted">
            Refresh
          </button>
        </div>

        {error && (
          <div className="mb-6 bg-destructive/10 border border-destructive rounded-lg p-4 text-destructive">
            {error}
          </div>
        )}
        {actionResult && (
          <div className="mb-6 bg-muted border rounded-lg p-4">{actionResult}</div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="space-y-6">
            <div className="bg-card border rounded-lg p-6">
              <h2 className="text-2xl font-bold mb-4">
                Pending decisions {loading ? '' : `(${pending.length})`}
              </h2>
              {loading ? (
                <p className="text-muted-foreground">Loading…</p>
              ) : pending.length === 0 ? (
                <p className="text-muted-foreground">
                  No boundary actions are waiting for your decision.
                </p>
              ) : (
                <div className="space-y-3">
                  {pending.map((p) => (
                    <div key={p.approval_id} className="bg-muted rounded-lg p-4">
                      <div className="font-semibold">{p.action_description}</div>
                      <div className="text-sm text-muted-foreground mt-1">
                        boundary: {p.boundary_type || p.approval_type}
                        {p.expires_at ? ` · expires ${new Date(p.expires_at).toLocaleString()}` : ''}
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">
                        workspace {p.workspace_id || '—'} · task {p.task_id || '—'}
                      </div>
                      {p.boundary_report_id && (
                        <button
                          onClick={() => openCase(p.boundary_report_id!)}
                          className="mt-2 text-sm underline"
                        >
                          Open case
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h2 className="text-2xl font-bold mb-4">
                Boundary reports {loading ? '' : `(${reports.length})`}
              </h2>
              {loading ? (
                <p className="text-muted-foreground">Loading…</p>
              ) : reports.length === 0 ? (
                <p className="text-muted-foreground">No boundary reports recorded yet.</p>
              ) : (
                <div className="space-y-2">
                  {reports.map((r) => (
                    <button
                      key={r.id}
                      onClick={() => openCase(r.id)}
                      className="w-full text-left bg-muted rounded-lg p-3 hover:bg-muted/70"
                    >
                      <div className="flex justify-between">
                        <span className="font-medium">{r.title}</span>
                        <span className="text-xs px-2 py-1 rounded bg-background border">
                          {r.resolution || 'open'}
                        </span>
                      </div>
                      <div className="text-sm text-muted-foreground mt-1">
                        {r.boundary_type} · severity {r.severity} ·{' '}
                        {r.created_at ? new Date(r.created_at).toLocaleString() : ''}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-2xl font-bold mb-4">Case detail</h2>
            {!selected ? (
              <p className="text-muted-foreground">Select a report to see its full chain.</p>
            ) : (
              <div className="space-y-4">
                <div>
                  <div className="font-semibold text-lg">{selected.report.title}</div>
                  <div className="text-sm text-muted-foreground">{selected.description}</div>
                </div>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div>State: <span className="font-medium">{selected.workflow_state}</span></div>
                  <div>Risk: <span className="font-medium">{selected.severity}</span></div>
                  <div>Boundary: {selected.boundary_type}</div>
                  <div>
                    Authority: needs {selected.authority_level_required}, has{' '}
                    {selected.authority_level_available}
                  </div>
                  <div>Workspace: {selected.report.workspace_id || '—'}</div>
                  <div>Task: {selected.report.task_id || '—'}</div>
                  <div>Checkpoint: {selected.checkpoint?.id || '—'}</div>
                  <div>
                    Approval expires:{' '}
                    {selected.pending_approval?.expires_at
                      ? new Date(selected.pending_approval.expires_at).toLocaleString()
                      : '—'}
                  </div>
                </div>

                {selected.safe_work_continuing.length > 0 && (
                  <div className="text-sm">
                    <span className="font-medium">Safe work continuing:</span>{' '}
                    {selected.safe_work_continuing.join(', ')}
                  </div>
                )}

                {selected.pending_approval?.status === 'pending' && (
                  <div className="flex gap-3">
                    <button
                      onClick={() => decide(selected.report.id, true)}
                      disabled={acting !== null}
                      className="px-4 py-2 rounded-lg bg-green-600 text-white disabled:opacity-50"
                    >
                      {acting === selected.report.id + 'approve' ? 'Approving…' : 'Approve'}
                    </button>
                    <button
                      onClick={() => decide(selected.report.id, false)}
                      disabled={acting !== null}
                      className="px-4 py-2 rounded-lg bg-red-600 text-white disabled:opacity-50"
                    >
                      {acting === selected.report.id + 'reject' ? 'Rejecting…' : 'Reject'}
                    </button>
                  </div>
                )}

                {selected.richard_decision && (
                  <div className="text-sm">
                    Decision: <span className="font-medium">{selected.richard_decision.decision}</span>
                    {selected.richard_decision.decided_at
                      ? ` at ${new Date(selected.richard_decision.decided_at).toLocaleString()}`
                      : ''}
                  </div>
                )}

                {selected.richard_decision?.decision === 'approved' &&
                  selected.resume_history.length === 0 && (
                    <button
                      onClick={() => resume(selected.report.id)}
                      disabled={acting !== null}
                      className="px-4 py-2 rounded-lg bg-blue-600 text-white disabled:opacity-50"
                    >
                      {acting === selected.report.id + 'resume'
                        ? 'Resuming…'
                        : 'Resume from checkpoint'}
                    </button>
                  )}

                {selected.resume_history.length > 0 && (
                  <div className="text-sm">
                    <div className="font-medium mb-1">Resume history</div>
                    {selected.resume_history.map((r) => (
                      <div key={r.id} className="text-muted-foreground">
                        {r.action_type} — {r.success ? 'succeeded' : 'failed'}
                        {r.executed_at ? ` (${new Date(r.executed_at).toLocaleString()})` : ''}
                      </div>
                    ))}
                  </div>
                )}

                <div>
                  <div className="font-medium mb-2">Audit trail ({audit.length})</div>
                  {audit.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No audit entries returned.</p>
                  ) : (
                    <div className="space-y-1 max-h-64 overflow-y-auto text-sm">
                      {audit.map((a) => (
                        <div key={a.id} className="border-b pb-1">
                          <span className={a.success ? 'text-green-600' : 'text-red-600'}>
                            {a.action}
                          </span>{' '}
                          <span className="text-muted-foreground">{a.description}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
