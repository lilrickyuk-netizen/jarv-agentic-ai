'use client';

import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';

interface Standup {
  id: string;
  workspace_id: string;
  agent_id: string | null;
  standup_date: string;
  yesterday_accomplishments: string[];
  today_plans: string[];
  blockers: string[];
  needs_help_with: string[] | null;
  tasks_completed: number;
  tasks_in_progress: number;
  tasks_planned: number;
  mood: string | null;
  confidence_level: number | null;
  created_at: string;
  updated_at: string;
}

interface StandupStats {
  total_standups: number;
  standups_today: number;
  total_accomplishments: number;
  total_blockers: number;
  total_tasks_completed: number;
  total_tasks_in_progress: number;
  average_confidence: number;
  agents_reporting: number;
  common_blockers: string[];
}

interface DailySummary {
  standup_date: string;
  total_standups: number;
  total_accomplishments: number;
  total_blockers: number;
  tasks_completed: number;
  tasks_in_progress: number;
  average_confidence: number;
}

export default function AIStandupsPage() {
  const [standups, setStandups] = useState<Standup[]>([]);
  const [stats, setStats] = useState<StandupStats | null>(null);
  const [dailySummaries, setDailySummaries] = useState<DailySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasBlockersOnly, setHasBlockersOnly] = useState(false);
  const [selectedDate, setSelectedDate] = useState<string>('all');

  useEffect(() => {
    fetchData();
  }, [hasBlockersOnly, selectedDate]);

  const fetchData = async () => {
    setLoading(true);
    setError(null);

    try {
      // Fetch standups
      const params = new URLSearchParams();
      if (hasBlockersOnly) {
        params.append('has_blockers', 'true');
      }
      if (selectedDate !== 'all') {
        params.append('start_date', selectedDate);
        params.append('end_date', selectedDate);
      }

      const standupsResponse = await apiClient.get<Standup[]>(
        `/standups/list?${params.toString()}`
      );

      if (standupsResponse.error) {
        setError(standupsResponse.error);
      } else if (standupsResponse.data) {
        setStandups(standupsResponse.data);
      }

      // Fetch stats
      const statsResponse = await apiClient.get<StandupStats>('/standups/stats');
      if (!statsResponse.error && statsResponse.data) {
        setStats(statsResponse.data);
      }

      // Fetch daily summaries
      const summariesResponse = await apiClient.get<DailySummary[]>('/standups/daily-summary');
      if (!summariesResponse.error && summariesResponse.data) {
        setDailySummaries(summariesResponse.data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch standup data');
    } finally {
      setLoading(false);
    }
  };

  const getMoodEmoji = (mood: string | null) => {
    const moods: Record<string, string> = {
      excellent: '🚀',
      good: '😊',
      neutral: '😐',
      concerned: '😟',
      blocked: '🚫',
    };
    return mood ? moods[mood] || '📊' : '📊';
  };

  const getConfidenceColor = (confidence: number | null) => {
    if (!confidence) return 'text-gray-600';
    if (confidence >= 0.8) return 'text-green-600';
    if (confidence >= 0.6) return 'text-blue-600';
    if (confidence >= 0.4) return 'text-yellow-600';
    return 'text-red-600';
  };

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">AI Team Standups</h1>
          <p className="text-muted-foreground">
            Daily updates, accomplishments, plans, and blockers from AI agents
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
            <p className="font-semibold">Error Loading Standup Data</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {/* Statistics Cards */}
        {!loading && stats && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Standups
              </h3>
              <p className="text-3xl font-bold">{stats.total_standups}</p>
              <p className="text-xs text-green-600 mt-1">{stats.standups_today} today</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Agents Reporting
              </h3>
              <p className="text-3xl font-bold text-blue-600">{stats.agents_reporting}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Tasks Completed
              </h3>
              <p className="text-3xl font-bold text-green-600">{stats.total_tasks_completed}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {stats.total_tasks_in_progress} in progress
              </p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Average Confidence
              </h3>
              <p className={`text-3xl font-bold ${getConfidenceColor(stats.average_confidence)}`}>
                {Math.round(stats.average_confidence * 100)}%
              </p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Accomplishments
              </h3>
              <p className="text-3xl font-bold">{stats.total_accomplishments}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Active Blockers
              </h3>
              <p className="text-3xl font-bold text-red-600">{stats.total_blockers}</p>
            </div>
          </div>
        )}

        {/* Common Blockers */}
        {!loading && stats && stats.common_blockers.length > 0 && (
          <div className="bg-card border rounded-lg p-6 mb-8">
            <h2 className="text-2xl font-bold mb-4">Common Blockers</h2>
            <div className="space-y-2">
              {stats.common_blockers.map((blocker, idx) => (
                <div key={idx} className="flex items-center gap-3 p-3 bg-red-50 border border-red-200 rounded-md">
                  <span className="text-red-600 text-xl">🚫</span>
                  <span className="text-sm text-red-800">{blocker}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Daily Trend */}
        {!loading && dailySummaries.length > 0 && (
          <div className="bg-card border rounded-lg p-6 mb-8">
            <h2 className="text-2xl font-bold mb-4">7-Day Trend</h2>
            <div className="space-y-3">
              {dailySummaries.map((summary) => (
                <div key={summary.standup_date} className="flex items-center justify-between p-4 bg-muted rounded-lg">
                  <div className="flex-1">
                    <p className="font-medium">{new Date(summary.standup_date).toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' })}</p>
                    <div className="flex gap-4 mt-1 text-sm text-muted-foreground">
                      <span>{summary.total_standups} standups</span>
                      <span>{summary.total_accomplishments} accomplishments</span>
                      {summary.total_blockers > 0 && (
                        <span className="text-red-600">{summary.total_blockers} blockers</span>
                      )}
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-sm text-muted-foreground">Confidence</p>
                    <p className={`text-xl font-bold ${getConfidenceColor(summary.average_confidence)}`}>
                      {Math.round(summary.average_confidence * 100)}%
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Filters */}
        {!loading && (
          <div className="flex flex-col md:flex-row gap-4 mb-6">
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={hasBlockersOnly}
                  onChange={(e) => setHasBlockersOnly(e.target.checked)}
                  className="w-4 h-4"
                />
                <span className="text-sm">Show blockers only</span>
              </label>
            </div>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && standups.length === 0 && (
          <div className="bg-card border rounded-lg p-12 text-center">
            <h3 className="text-xl font-semibold mb-2">No Standups Found</h3>
            <p className="text-muted-foreground">
              {hasBlockersOnly || selectedDate !== 'all'
                ? 'No standups match the selected filters'
                : 'No AI standups have been recorded yet'}
            </p>
          </div>
        )}

        {/* Standups List */}
        {!loading && standups.length > 0 && (
          <div className="space-y-6">
            {standups.map((standup) => (
              <div
                key={standup.id}
                className="bg-card border rounded-lg p-6 hover:border-primary transition-colors"
              >
                {/* Header */}
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-2xl">{getMoodEmoji(standup.mood)}</span>
                      <h3 className="text-lg font-semibold">
                        {new Date(standup.standup_date).toLocaleDateString('en-US', {
                          weekday: 'long',
                          year: 'numeric',
                          month: 'long',
                          day: 'numeric'
                        })}
                      </h3>
                    </div>
                    {standup.agent_id && (
                      <p className="text-sm text-muted-foreground">Agent ID: {standup.agent_id.substring(0, 8)}...</p>
                    )}
                  </div>
                  <div className="text-right">
                    {standup.confidence_level !== null && (
                      <div>
                        <p className="text-xs text-muted-foreground">Confidence</p>
                        <p className={`text-2xl font-bold ${getConfidenceColor(standup.confidence_level)}`}>
                          {Math.round(standup.confidence_level * 100)}%
                        </p>
                      </div>
                    )}
                  </div>
                </div>

                {/* Task Stats */}
                <div className="grid grid-cols-3 gap-4 mb-4 pb-4 border-b">
                  <div>
                    <p className="text-xs text-muted-foreground">Completed</p>
                    <p className="text-xl font-semibold text-green-600">{standup.tasks_completed}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">In Progress</p>
                    <p className="text-xl font-semibold text-blue-600">{standup.tasks_in_progress}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Planned</p>
                    <p className="text-xl font-semibold text-gray-600">{standup.tasks_planned}</p>
                  </div>
                </div>

                {/* Yesterday's Accomplishments */}
                {standup.yesterday_accomplishments.length > 0 && (
                  <div className="mb-4">
                    <h4 className="text-sm font-semibold mb-2 text-green-700">✅ Yesterday's Accomplishments</h4>
                    <ul className="space-y-1">
                      {standup.yesterday_accomplishments.map((item, idx) => (
                        <li key={idx} className="text-sm text-muted-foreground flex items-start gap-2">
                          <span className="text-green-600 mt-1">•</span>
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Today's Plans */}
                {standup.today_plans.length > 0 && (
                  <div className="mb-4">
                    <h4 className="text-sm font-semibold mb-2 text-blue-700">📋 Today's Plans</h4>
                    <ul className="space-y-1">
                      {standup.today_plans.map((item, idx) => (
                        <li key={idx} className="text-sm text-muted-foreground flex items-start gap-2">
                          <span className="text-blue-600 mt-1">•</span>
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Blockers */}
                {standup.blockers.length > 0 && (
                  <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md">
                    <h4 className="text-sm font-semibold mb-2 text-red-700">🚫 Blockers</h4>
                    <ul className="space-y-1">
                      {standup.blockers.map((item, idx) => (
                        <li key={idx} className="text-sm text-red-800 flex items-start gap-2">
                          <span className="text-red-600 mt-1">•</span>
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Needs Help With */}
                {standup.needs_help_with && standup.needs_help_with.length > 0 && (
                  <div className="p-3 bg-yellow-50 border border-yellow-200 rounded-md">
                    <h4 className="text-sm font-semibold mb-2 text-yellow-700">🤝 Needs Help With</h4>
                    <ul className="space-y-1">
                      {standup.needs_help_with.map((item, idx) => (
                        <li key={idx} className="text-sm text-yellow-800 flex items-start gap-2">
                          <span className="text-yellow-600 mt-1">•</span>
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ))}</div>
        )}

        {/* Results Count */}
        {!loading && standups.length > 0 && (
          <div className="mt-6 text-center text-sm text-muted-foreground">
            Showing {standups.length} standup{standups.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </div>
  );
}
