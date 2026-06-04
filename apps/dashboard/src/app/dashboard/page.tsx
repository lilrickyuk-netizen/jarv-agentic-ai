'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiClient, HealthResponse, VersionResponse } from '@/lib/api';
import { clearTokens, getAccessToken } from '@/lib/auth';

interface Agent {
  name: string;
  role: string;
  category: string;
  description: string;
  required_authority_level: number;
  is_implemented: boolean;
}

interface AgentStats {
  total_required: number;
  total_registered: number;
  implemented: number;
  unimplemented: number;
  completion_percentage: number;
  by_category: Record<string, Record<string, number>>;
}

interface CommandResult {
  command_text: string;
  response_text: string;
  execution_time: number;
  success: boolean;
  error?: string | null;
}

export default function CommandCenterPage() {
  const router = useRouter();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [version, setVersion] = useState<VersionResponse | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentStats, setAgentStats] = useState<AgentStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Command console state (text + voice command control)
  const [command, setCommand] = useState('');
  const [commandResult, setCommandResult] = useState<CommandResult | null>(null);
  const [commandLoading, setCommandLoading] = useState(false);
  const [commandError, setCommandError] = useState<string | null>(null);
  const [listening, setListening] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(false);

  useEffect(() => {
    // Browser-native speech recognition is the local-first voice path.
    // If unavailable, the console falls back to text-only input.
    if (typeof window !== 'undefined') {
      const SR =
        (window as any).SpeechRecognition ||
        (window as any).webkitSpeechRecognition;
      setVoiceSupported(Boolean(SR));
    }
  }, []);

  const sendCommand = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    setCommandLoading(true);
    setCommandError(null);
    setCommandResult(null);
    try {
      const response = await apiClient.post<CommandResult>(
        '/api/voice/command/text',
        { command: trimmed, language: 'en-US' }
      );
      if (response.error) {
        setCommandError(response.error);
      } else if (response.data) {
        setCommandResult(response.data);
      }
    } catch (err) {
      setCommandError(
        err instanceof Error ? err.message : 'Failed to send command'
      );
    } finally {
      setCommandLoading(false);
    }
  };

  const startVoice = () => {
    if (typeof window === 'undefined') return;
    const SR =
      (window as any).SpeechRecognition ||
      (window as any).webkitSpeechRecognition;
    if (!SR) return;
    const recognition = new SR();
    recognition.lang = 'en-US';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript as string;
      setCommand(transcript);
      sendCommand(transcript);
    };
    recognition.onerror = (event: any) => {
      setCommandError(`Voice input error: ${event.error}. Use text input instead.`);
      setListening(false);
    };
    recognition.onend = () => setListening(false);
    setListening(true);
    recognition.start();
  };

  const handleLogout = async () => {
    try {
      const accessToken = getAccessToken();
      if (accessToken) {
        await apiClient.post('/auth/logout', { access_token: accessToken });
      }
    } catch (err) {
      console.error('Logout error:', err);
    } finally {
      clearTokens();
      router.push('/login');
    }
  };

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError(null);

      // Fetch health
      const healthResponse = await apiClient.checkHealth();
      if (healthResponse.error) {
        setError(healthResponse.error);
      } else {
        setHealth(healthResponse.data || null);
      }

      // Fetch version
      const versionResponse = await apiClient.getVersion();
      if (!versionResponse.error) {
        setVersion(versionResponse.data || null);
      }

      // Fetch agents
      const agentsResponse = await apiClient.get<Agent[]>('/api/agents/list');
      if (!agentsResponse.error && agentsResponse.data) {
        setAgents(agentsResponse.data);
      }

      // Fetch agent stats
      const statsResponse = await apiClient.get<AgentStats>('/api/agents/stats');
      if (!statsResponse.error && statsResponse.data) {
        setAgentStats(statsResponse.data);
      }

      setLoading(false);
    };

    fetchData();
  }, []);

  const activeAgents = agents.filter(a => a.is_implemented);
  const pendingAgents = agents.filter(a => !a.is_implemented);

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-4xl font-bold mb-2">JARV Command Center</h1>
            <p className="text-muted-foreground">
              Monitor and control your autonomous AI system
            </p>
          </div>
          <button
            onClick={handleLogout}
            className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-md transition-colors"
          >
            Logout
          </button>
        </div>

        {/* Command Console — type or speak a command to JARV */}
        <div className="bg-card border rounded-lg p-6 mb-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-2xl font-bold">Command JARV</h2>
            <span className="text-xs text-muted-foreground">
              {voiceSupported
                ? 'Voice + text enabled'
                : 'Text input (voice not supported in this browser)'}
            </span>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              sendCommand(command);
            }}
            className="flex gap-2"
          >
            <input
              type="text"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder="Type a command, e.g. 'Create a launch plan and check system readiness'"
              disabled={commandLoading}
              className="flex-1 px-4 py-3 border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-primary"
            />
            {voiceSupported && (
              <button
                type="button"
                onClick={startVoice}
                disabled={commandLoading || listening}
                title="Speak a command"
                className={`px-4 py-3 rounded-md border transition-colors ${
                  listening
                    ? 'bg-red-600 text-white border-red-600 animate-pulse'
                    : 'hover:border-primary hover:bg-primary/5'
                }`}
              >
                {listening ? '● Listening' : '🎤 Speak'}
              </button>
            )}
            <button
              type="submit"
              disabled={commandLoading || !command.trim()}
              className="px-6 py-3 bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {commandLoading ? 'Sending…' : 'Send'}
            </button>
          </form>

          {commandError && (
            <div className="mt-4 bg-destructive/10 border border-destructive text-destructive px-4 py-3 rounded-lg">
              <p className="text-sm">{commandError}</p>
            </div>
          )}

          {commandResult && (
            <div className="mt-4 border rounded-lg p-4 bg-background">
              <div className="flex items-center justify-between mb-2">
                <span
                  className={`px-2 py-1 text-xs rounded font-semibold ${
                    commandResult.success
                      ? 'bg-green-100 text-green-800'
                      : 'bg-orange-100 text-orange-800'
                  }`}
                >
                  {commandResult.success ? 'JARV responded' : 'Completed with issues'}
                </span>
                <span className="text-xs text-muted-foreground">
                  {commandResult.execution_time.toFixed(2)}s
                </span>
              </div>
              <p className="text-sm text-muted-foreground mb-1">
                Command: {commandResult.command_text}
              </p>
              <pre className="text-sm whitespace-pre-wrap font-sans mt-2">
                {commandResult.response_text}
              </pre>
            </div>
          )}
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
            <p className="font-semibold">Backend Connection Error</p>
            <p className="text-sm">{error}</p>
            <p className="text-sm mt-2">
              Make sure the backend API is running at {process.env.NEXT_PUBLIC_API_URL}
            </p>
          </div>
        )}

        {/* System Health Cards */}
        {!loading && health && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Backend Status
              </h3>
              <p className="text-2xl font-bold text-green-600">{health.status}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Service
              </h3>
              <p className="text-2xl font-bold">{health.service}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Version
              </h3>
              <p className="text-2xl font-bold">{health.version}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Last Updated
              </h3>
              <p className="text-2xl font-bold">
                {new Date(health.timestamp).toLocaleTimeString()}
              </p>
            </div>
          </div>
        )}

        {/* Agent Statistics */}
        {!loading && agentStats && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Agents
              </h3>
              <p className="text-3xl font-bold">{agentStats.total_registered}</p>
              <p className="text-sm text-muted-foreground mt-1">
                of {agentStats.total_required} required
              </p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Implemented
              </h3>
              <p className="text-3xl font-bold text-green-600">{agentStats.implemented}</p>
              <p className="text-sm text-muted-foreground mt-1">
                {agentStats.completion_percentage.toFixed(1)}% complete
              </p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Active Agents
              </h3>
              <p className="text-3xl font-bold text-blue-600">{activeAgents.length}</p>
              <p className="text-sm text-muted-foreground mt-1">
                currently operational
              </p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Pending
              </h3>
              <p className="text-3xl font-bold text-orange-600">{agentStats.unimplemented}</p>
              <p className="text-sm text-muted-foreground mt-1">
                awaiting implementation
              </p>
            </div>
          </div>
        )}

        {/* Active Agents */}
        {!loading && activeAgents.length > 0 && (
          <div className="bg-card border rounded-lg p-6 mb-8">
            <h2 className="text-2xl font-bold mb-4">Active Agents</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {activeAgents.slice(0, 9).map((agent) => (
                <div key={agent.name} className="border rounded-lg p-4 hover:border-primary transition-colors">
                  <div className="flex items-start justify-between mb-2">
                    <h3 className="font-semibold">{agent.name}</h3>
                    <span className="px-2 py-1 text-xs rounded bg-green-100 text-green-800">
                      Active
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground mb-2">{agent.role}</p>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">{agent.category}</span>
                    <span className="text-muted-foreground">Level {agent.required_authority_level}</span>
                  </div>
                </div>
              ))}
            </div>
            {activeAgents.length > 9 && (
              <div className="mt-4 text-center">
                <button
                  onClick={() => router.push('/dashboard/agents')}
                  className="text-sm text-primary hover:underline"
                >
                  View all {activeAgents.length} active agents →
                </button>
              </div>
            )}
          </div>
        )}

        {/* Features Status */}
        {!loading && version && (
          <div className="bg-card border rounded-lg p-6 mb-8">
            <h2 className="text-2xl font-bold mb-4">System Features</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {Object.entries(version.features).map(([key, value]) => (
                <div key={key} className="flex items-center justify-between">
                  <span className="text-sm">
                    {key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}
                  </span>
                  <span
                    className={`px-2 py-1 rounded text-xs font-semibold ${
                      value
                        ? 'bg-green-100 text-green-800'
                        : 'bg-gray-100 text-gray-800'
                    }`}
                  >
                    {value ? 'Enabled' : 'Disabled'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* System Configuration */}
        {!loading && version && (
          <div className="bg-card border rounded-lg p-6 mb-8">
            <h2 className="text-2xl font-bold mb-4">System Configuration</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <p className="text-sm text-muted-foreground">Environment</p>
                <p className="font-semibold">{version.environment}</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Platform</p>
                <p className="font-semibold">{version.platform}</p>
              </div>
              <div>
                <p className="text-sm text-muted-foreground">Python Version</p>
                <p className="font-semibold">{version.python_version.split(' ')[0]}</p>
              </div>
              {Object.entries(version.configuration).map(([key, value]) => (
                <div key={key}>
                  <p className="text-sm text-muted-foreground">
                    {key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}
                  </p>
                  <p className="font-semibold">{value}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Quick Actions */}
        <div className="bg-card border rounded-lg p-6">
          <h2 className="text-2xl font-bold mb-4">Quick Actions</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <button
              onClick={() => router.push('/dashboard/workspaces')}
              className="p-4 border rounded-lg hover:border-primary hover:bg-primary/5 transition-colors text-left"
            >
              <h3 className="font-semibold mb-1">Workspaces</h3>
              <p className="text-sm text-muted-foreground">Manage workspaces</p>
            </button>
            <button
              onClick={() => router.push('/dashboard/agents')}
              className="p-4 border rounded-lg hover:border-primary hover:bg-primary/5 transition-colors text-left"
            >
              <h3 className="font-semibold mb-1">Agents</h3>
              <p className="text-sm text-muted-foreground">View all agents</p>
            </button>
            <button
              onClick={() => router.push('/dashboard/tasks')}
              className="p-4 border rounded-lg hover:border-primary hover:bg-primary/5 transition-colors text-left"
            >
              <h3 className="font-semibold mb-1">Tasks</h3>
              <p className="text-sm text-muted-foreground">Manage tasks</p>
            </button>
            <button
              onClick={() => router.push('/dashboard/operations')}
              className="p-4 border rounded-lg hover:border-primary hover:bg-primary/5 transition-colors text-left"
            >
              <h3 className="font-semibold mb-1">Operations</h3>
              <p className="text-sm text-muted-foreground">Live operations feed</p>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
