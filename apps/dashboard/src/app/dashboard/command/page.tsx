'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api';

interface CommandResponse {
  task_id: string;
  command: string;
  status: string;
  requires_approval: boolean;
  response_text: string;
  plan_steps: string[];
  selected_agents: string[];
  provider: string | null;
  model: string | null;
  execution_time: number;
  tokens_used: number;
  approval_reason?: string | null;
  error?: string | null;
}

interface HistoryItem {
  task_id: string;
  command: string;
  status: string;
  response_text: string | null;
  selected_agents: string[];
  created_at: string;
  completed_at: string | null;
  error: string | null;
}

export default function CommandPage() {
  const router = useRouter();
  const [command, setCommand] = useState('');
  const [result, setResult] = useState<CommandResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [info, setInfo] = useState<{ provider: string; model: string } | null>(null);
  const [listening, setListening] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(false);
  const recognitionRef = useRef<any>(null);

  const loadHistory = async () => {
    const res = await apiClient.get<HistoryItem[]>('/api/command/history?limit=15');
    if (!res.error && res.data) setHistory(res.data);
  };

  useEffect(() => {
    // Active provider/model (no secrets)
    apiClient.get<{ provider: string; model: string }>('/api/command/info').then((res) => {
      if (!res.error && res.data) setInfo(res.data);
    });
    loadHistory();
    if (typeof window !== 'undefined') {
      const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      setVoiceSupported(Boolean(SR));
    }
  }, []);

  const runCommand = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiClient.post<CommandResponse>('/api/command/execute', {
        command: trimmed,
      });
      if (res.error) {
        setError(res.error);
      } else if (res.data) {
        setResult(res.data);
        loadHistory();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Command failed');
    } finally {
      setLoading(false);
    }
  };

  const startVoice = () => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) return;
    const recognition = new SR();
    recognitionRef.current = recognition;
    recognition.lang = 'en-US';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript as string;
      setCommand(transcript); // transcript inserted into box for user to confirm/submit
    };
    recognition.onerror = (event: any) => {
      setError(`Voice input error: ${event.error}. Use text input instead.`);
      setListening(false);
    };
    recognition.onend = () => setListening(false);
    setListening(true);
    recognition.start();
  };

  const statusColor = (status: string) => {
    if (status === 'completed' || status === 'approved') return 'bg-green-100 text-green-800';
    if (status === 'running' || status === 'pending') return 'bg-blue-100 text-blue-800';
    if (status === 'partial') return 'bg-orange-100 text-orange-800';
    if (status === 'needs_continuation') return 'bg-purple-100 text-purple-800';
    if (status === 'resuming') return 'bg-blue-100 text-blue-800';
    if (status === 'blocked' || status === 'waiting_on_approval') return 'bg-yellow-100 text-yellow-800';
    if (status === 'failed' || status === 'rejected' || status === 'cancelled') return 'bg-red-100 text-red-800';
    return 'bg-gray-100 text-gray-800';
  };

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-5xl mx-auto">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-4xl font-bold mb-2">Command</h1>
            <p className="text-muted-foreground">
              Type or speak a command. JARV plans with Claude, selects agents, and executes.
            </p>
          </div>
          <button
            onClick={() => router.push('/dashboard')}
            className="text-sm text-primary hover:underline"
          >
            ← Command Center
          </button>
        </div>

        {/* Provider / model display */}
        <div className="mb-4 text-xs text-muted-foreground">
          Provider: <span className="font-semibold">{info?.provider ?? '—'}</span> · Model:{' '}
          <span className="font-semibold">{info?.model ?? '—'}</span> ·{' '}
          {voiceSupported ? 'Voice + text enabled' : 'Text input (voice not supported in this browser)'}
        </div>

        {/* Command input */}
        <div className="bg-card border rounded-lg p-6 mb-6">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              runCommand(command);
            }}
          >
            <textarea
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder="e.g. JARV, inspect system status and tell me whether all services are healthy. Do not modify files."
              rows={3}
              disabled={loading}
              className="w-full px-4 py-3 border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-primary resize-y"
            />
            <div className="mt-3 flex items-center gap-2">
              <button
                type="submit"
                disabled={loading || !command.trim()}
                className="px-6 py-2 bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50"
              >
                {loading ? 'Running…' : 'Send Command'}
              </button>
              {voiceSupported && (
                <button
                  type="button"
                  onClick={startVoice}
                  disabled={loading || listening}
                  className={`px-4 py-2 rounded-md border ${
                    listening
                      ? 'bg-red-600 text-white border-red-600 animate-pulse'
                      : 'hover:border-primary hover:bg-primary/5'
                  }`}
                >
                  {listening ? '● Listening…' : '🎤 Speak'}
                </button>
              )}
              {loading && (
                <span className="text-sm text-muted-foreground flex items-center gap-2">
                  <span className="inline-block animate-spin rounded-full h-4 w-4 border-b-2 border-primary"></span>
                  JARV is planning and executing…
                </span>
              )}
            </div>
          </form>
        </div>

        {/* Error display */}
        {error && (
          <div className="mb-6 bg-destructive/10 border border-destructive text-destructive px-4 py-3 rounded-lg">
            <p className="font-semibold">Error</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {/* Result */}
        {result && (
          <div className="bg-card border rounded-lg p-6 mb-6">
            <div className="flex items-center justify-between mb-3">
              <span className={`px-2 py-1 text-xs rounded font-semibold ${statusColor(result.status)}`}>
                {result.status.toUpperCase()}
              </span>
              <span className="text-xs text-muted-foreground">
                {result.provider}/{result.model} · {result.execution_time}s · {result.tokens_used} tokens
              </span>
            </div>

            {result.requires_approval && (
              <div className="mb-4 bg-yellow-50 border border-yellow-300 text-yellow-900 px-4 py-3 rounded-lg">
                <p className="font-semibold">Approval required</p>
                <p className="text-sm">{result.approval_reason}</p>
                <button
                  onClick={() => router.push('/dashboard/approvals')}
                  className="mt-2 text-sm underline"
                >
                  Go to Approvals →
                </button>
              </div>
            )}

            <pre className="text-sm whitespace-pre-wrap font-sans mb-4">{result.response_text}</pre>

            {result.selected_agents.length > 0 && (
              <div className="mb-3">
                <p className="text-xs text-muted-foreground mb-1">Selected agents</p>
                <div className="flex flex-wrap gap-2">
                  {result.selected_agents.map((a) => (
                    <span key={a} className="px-2 py-1 text-xs rounded bg-blue-100 text-blue-800">
                      {a}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {result.plan_steps.length > 0 && (
              <div>
                <p className="text-xs text-muted-foreground mb-1">Plan steps</p>
                <ol className="list-decimal list-inside text-sm space-y-1">
                  {result.plan_steps.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ol>
              </div>
            )}

            <div className="mt-4 text-xs">
              <button onClick={() => router.push('/dashboard/tasks')} className="text-primary hover:underline">
                View task on Tasks page →
              </button>
            </div>
          </div>
        )}

        {/* History */}
        <div className="bg-card border rounded-lg p-6">
          <h2 className="text-xl font-bold mb-4">Recent Commands</h2>
          {history.length === 0 ? (
            <p className="text-sm text-muted-foreground">No commands run yet.</p>
          ) : (
            <div className="space-y-2">
              {history.map((h) => (
                <div key={h.task_id} className="border rounded-md p-3 flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{h.command}</p>
                    <p className="text-xs text-muted-foreground">
                      {new Date(h.created_at).toLocaleString()}
                      {h.selected_agents.length > 0 && ` · ${h.selected_agents.length} agents`}
                    </p>
                  </div>
                  <span className={`px-2 py-1 text-xs rounded font-semibold shrink-0 ${statusColor(h.status)}`}>
                    {h.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
