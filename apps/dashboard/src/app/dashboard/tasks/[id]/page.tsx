'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api';

interface TaskEvent {
  kind: string;
  title: string;
  detail: string | null;
  severity: string | null;
  success: boolean | null;
  required_approval: boolean | null;
  created_at: string | null;
}

interface TaskDetail {
  id: string;
  title: string;
  command: string;
  description: string | null;
  task_type: string;
  workspace_id: string;
  assigned_agent_id: string | null;
  status: string;
  priority: number;
  requires_approval: boolean;
  approval_status: string;
  response_text: string | null;
  selected_agents: string[];
  plan_steps: string[];
  provider: string | null;
  model: string | null;
  tool_calls: Record<string, unknown>[];
  verification: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  error_message: string | null;
  execution_logs: Record<string, unknown>[] | null;
  context: Record<string, unknown> | null;
  started_at: string | null;
  completed_at: string | null;
  failed_at: string | null;
  execution_duration_seconds: number | null;
  tokens_used: number;
  retry_count: number;
  created_at: string;
  updated_at: string;
  audit_events: TaskEvent[];
  operation_events: TaskEvent[];
}

const statusColor = (status: string) => {
  const c: Record<string, string> = {
    pending: 'bg-gray-100 text-gray-800',
    running: 'bg-blue-100 text-blue-800',
    in_progress: 'bg-blue-100 text-blue-800',
    completed: 'bg-green-100 text-green-800',
    approved: 'bg-green-100 text-green-800',
    failed: 'bg-red-100 text-red-800',
    blocked: 'bg-yellow-100 text-yellow-800',
    cancelled: 'bg-gray-200 text-gray-700',
  };
  return c[status] || 'bg-gray-100 text-gray-800';
};

export default function TaskDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id as string;

  const [task, setTask] = useState<TaskDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [acting, setActing] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const fetchTask = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    const res = await apiClient.get<TaskDetail>(`/api/tasks/${id}`);
    if (res.error) setError(res.error);
    else if (res.data) setTask(res.data);
    setLoading(false);
  }, [id]);

  useEffect(() => {
    fetchTask();
  }, [fetchTask]);

  const decide = async (action: 'approve' | 'reject') => {
    setActing(true);
    setActionMsg(null);
    const res = await apiClient.post(
      `/api/approvals/command-blocks/${id}/${action}`,
      { note: `${action} from task detail` }
    );
    if (res.error) setActionMsg(`Error: ${res.error}`);
    else setActionMsg(action === 'approve' ? 'Action confirmed.' : 'Action cancelled.');
    setActing(false);
    fetchTask();
  };

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-5xl mx-auto">
        <button
          onClick={() => router.push('/dashboard/tasks')}
          className="text-sm text-muted-foreground hover:text-primary mb-4"
        >
          ← Back to tasks
        </button>

        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary"></div>
          </div>
        )}

        {error && (
          <div className="bg-destructive/10 border border-destructive text-destructive px-4 py-3 rounded-lg mb-6">
            <p className="font-semibold">Error loading task</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {!loading && task && (
          <div className="space-y-6">
            {/* Header */}
            <div className="flex items-start justify-between gap-4">
              <div>
                <h1 className="text-2xl font-bold mb-1">Task Detail</h1>
                <p className="text-xs text-muted-foreground font-mono">{task.id}</p>
              </div>
              <span className={`px-3 py-1 text-sm rounded ${statusColor(task.status)}`}>
                {task.status}
              </span>
            </div>

            {/* Command */}
            <section className="bg-card border rounded-lg p-6">
              <h2 className="text-sm font-medium text-muted-foreground mb-2">Command</h2>
              <p className="whitespace-pre-wrap">{task.command}</p>
            </section>

            {/* Approval gate */}
            {(task.requires_approval || task.status === 'blocked') && (
              <section className="bg-yellow-50 border border-yellow-300 rounded-lg p-6">
                <h2 className="font-semibold text-yellow-900 mb-1">
                  Richard Boundary — approval {task.approval_status}
                </h2>
                <p className="text-sm text-yellow-800 mb-4">
                  {String((task.context as Record<string, unknown>)?.safety_reason ||
                    'This action is paused at a hard boundary and needs your decision.')}
                </p>
                {task.status === 'blocked' && (
                  <div className="flex gap-3">
                    <button
                      disabled={acting}
                      onClick={() => decide('approve')}
                      className="px-4 py-2 rounded-md bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
                    >
                      Confirm (approve)
                    </button>
                    <button
                      disabled={acting}
                      onClick={() => decide('reject')}
                      className="px-4 py-2 rounded-md bg-red-600 text-white hover:bg-red-700 disabled:opacity-50"
                    >
                      Cancel (reject)
                    </button>
                  </div>
                )}
                {actionMsg && <p className="text-sm mt-3 font-medium">{actionMsg}</p>}
              </section>
            )}

            {/* Result */}
            {task.response_text && (
              <section className="bg-card border rounded-lg p-6">
                <h2 className="text-sm font-medium text-muted-foreground mb-2">Result</h2>
                <pre className="whitespace-pre-wrap text-sm font-sans">{task.response_text}</pre>
              </section>
            )}

            {/* Error */}
            {task.error_message && (
              <section className="bg-destructive/10 border border-destructive rounded-lg p-6">
                <h2 className="text-sm font-medium text-destructive mb-2">Error</h2>
                <pre className="whitespace-pre-wrap text-sm text-destructive">{task.error_message}</pre>
              </section>
            )}

            {/* Meta grid */}
            <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                ['Provider', task.provider || '—'],
                ['Model', task.model || '—'],
                ['Tokens', task.tokens_used.toLocaleString()],
                ['Type', task.task_type],
                ['Duration', task.execution_duration_seconds != null ? `${task.execution_duration_seconds}s` : '—'],
                ['Retries', String(task.retry_count)],
                ['Created', new Date(task.created_at).toLocaleString()],
                ['Updated', new Date(task.updated_at).toLocaleString()],
              ].map(([label, value]) => (
                <div key={label} className="bg-card border rounded-lg p-4">
                  <p className="text-xs text-muted-foreground">{label}</p>
                  <p className="font-medium text-sm break-words">{value}</p>
                </div>
              ))}
            </section>

            {/* Selected agents */}
            <section className="bg-card border rounded-lg p-6">
              <h2 className="text-sm font-medium text-muted-foreground mb-3">Selected agents</h2>
              {task.selected_agents.length ? (
                <div className="flex flex-wrap gap-2">
                  {task.selected_agents.map((a) => (
                    <span key={a} className="px-2 py-1 text-xs rounded bg-primary/10 text-primary">
                      {a}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">No agents recorded.</p>
              )}
            </section>

            {/* Verification (QA) */}
            {task.verification && (
              <section className={`border rounded-lg p-6 ${task.verification.passed ? 'bg-green-50 border-green-300' : 'bg-red-50 border-red-300'}`}>
                <h2 className="text-sm font-medium mb-2">
                  QA Verification — {task.verification.passed ? 'PASSED' : 'FAILED'}
                </h2>
                <p className="text-sm">
                  Verifier: <span className="font-mono">{String(task.verification.verifier)}</span>
                  {' · '}confidence {String(task.verification.confidence_score)}
                  {' · '}{String(task.verification.tests_passed)} passed / {String(task.verification.tests_failed)} failed
                </p>
                <p className="text-sm text-muted-foreground mt-1">{String(task.verification.reasoning)}</p>
              </section>
            )}

            {/* Tool calls */}
            <section className="bg-card border rounded-lg p-6">
              <h2 className="text-sm font-medium text-muted-foreground mb-3">
                Tool calls ({task.tool_calls.length})
              </h2>
              {task.tool_calls.length ? (
                <ul className="space-y-2">
                  {task.tool_calls.map((t, i) => (
                    <li key={i} className="text-sm border-l-2 border-primary/40 pl-3">
                      <span className="font-mono font-medium">{String(t.tool)}</span>
                      {t.success === false && <span className="ml-2 text-xs text-red-600">failed</span>}
                      {t.authorized === false && <span className="ml-2 text-xs text-yellow-700">not authorized</span>}
                      <span className="ml-2 text-xs text-muted-foreground">L{String(t.authority_level)}</span>
                      {t.summary != null && <p className="text-muted-foreground text-xs">{String(t.summary)}</p>}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">No tool calls recorded for this task.</p>
              )}
            </section>

            {/* Plan steps */}
            {task.plan_steps.length > 0 && (
              <section className="bg-card border rounded-lg p-6">
                <h2 className="text-sm font-medium text-muted-foreground mb-3">Execution plan</h2>
                <ol className="list-decimal list-inside space-y-1 text-sm">
                  {task.plan_steps.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ol>
              </section>
            )}

            {/* Operation events */}
            <section className="bg-card border rounded-lg p-6">
              <h2 className="text-sm font-medium text-muted-foreground mb-3">Operations feed (this task)</h2>
              {task.operation_events.length ? (
                <ul className="space-y-2">
                  {task.operation_events.map((e, i) => (
                    <li key={i} className="text-sm border-l-2 border-primary/40 pl-3">
                      <span className="font-medium">{e.title}</span>
                      {e.severity && <span className="ml-2 text-xs text-muted-foreground">[{e.severity}]</span>}
                      {e.detail && <p className="text-muted-foreground text-xs">{e.detail}</p>}
                      {e.created_at && (
                        <p className="text-[10px] text-muted-foreground">
                          {new Date(e.created_at).toLocaleString()}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">No operation events.</p>
              )}
            </section>

            {/* Audit events */}
            <section className="bg-card border rounded-lg p-6">
              <h2 className="text-sm font-medium text-muted-foreground mb-3">Audit trail (this task)</h2>
              {task.audit_events.length ? (
                <ul className="space-y-2">
                  {task.audit_events.map((e, i) => (
                    <li key={i} className="text-sm border-l-2 border-muted pl-3">
                      <span className="font-medium">{e.title}</span>
                      {e.required_approval && (
                        <span className="ml-2 text-xs text-yellow-700">approval-gated</span>
                      )}
                      {e.success === false && <span className="ml-2 text-xs text-red-600">failed</span>}
                      {e.detail && <p className="text-muted-foreground text-xs">{e.detail}</p>}
                      {e.created_at && (
                        <p className="text-[10px] text-muted-foreground">
                          {new Date(e.created_at).toLocaleString()}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">No audit events.</p>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
