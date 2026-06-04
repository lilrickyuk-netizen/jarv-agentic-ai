'use client';

import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';

interface Experience {
  id: string;
  agent_id: string;
  session_id: string | null;
  task_id: string | null;
  experience_type: string;
  title: string;
  description: string;
  situation: string;
  action_taken: string;
  result: string;
  outcome: string;
  lesson_learned: string;
  applicable_contexts: string[];
  confidence_score: number;
  times_applied: number;
  success_rate: number | null;
  is_validated: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface ExperienceStats {
  total_experiences: number;
  validated_experiences: number;
  active_experiences: number;
  by_type: Record<string, number>;
  by_outcome: Record<string, number>;
  average_confidence: number;
  average_success_rate: number;
  most_applied_experience_id: string | null;
}

export default function ExperiencePage() {
  const [experiences, setExperiences] = useState<Experience[]>([]);
  const [stats, setStats] = useState<ExperienceStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [outcomeFilter, setOutcomeFilter] = useState<string>('all');
  const [validatedOnly, setValidatedOnly] = useState(false);
  const [activeOnly, setActiveOnly] = useState(true);

  useEffect(() => {
    fetchData();
  }, [typeFilter, outcomeFilter, validatedOnly, activeOnly]);

  const fetchData = async () => {
    setLoading(true);
    setError(null);

    try {
      // Fetch experiences
      const params = new URLSearchParams();
      if (typeFilter !== 'all') {
        params.append('experience_type', typeFilter);
      }
      if (outcomeFilter !== 'all') {
        params.append('outcome', outcomeFilter);
      }
      if (validatedOnly) {
        params.append('is_validated', 'true');
      }
      if (activeOnly) {
        params.append('is_active', 'true');
      }

      const experiencesResponse = await apiClient.get<Experience[]>(
        `/api/experience/list?${params.toString()}`
      );

      if (experiencesResponse.error) {
        setError(experiencesResponse.error);
      } else if (experiencesResponse.data) {
        setExperiences(experiencesResponse.data);
      }

      // Fetch stats
      const statsResponse = await apiClient.get<ExperienceStats>('/api/experience/stats');
      if (!statsResponse.error && statsResponse.data) {
        setStats(statsResponse.data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch experience data');
    } finally {
      setLoading(false);
    }
  };

  const getOutcomeColor = (outcome: string) => {
    const colors: Record<string, string> = {
      success: 'bg-green-100 text-green-800 border-green-200',
      failure: 'bg-red-100 text-red-800 border-red-200',
      partial: 'bg-yellow-100 text-yellow-800 border-yellow-200',
      learning: 'bg-blue-100 text-blue-800 border-blue-200',
    };
    return colors[outcome] || 'bg-gray-100 text-gray-800 border-gray-200';
  };

  const getOutcomeIcon = (outcome: string) => {
    const icons: Record<string, string> = {
      success: '✅',
      failure: '❌',
      partial: '⚠️',
      learning: '📚',
    };
    return icons[outcome] || '📊';
  };

  const getConfidenceColor = (score: number) => {
    if (score >= 0.8) return 'text-green-600 font-bold';
    if (score >= 0.6) return 'text-blue-600 font-semibold';
    if (score >= 0.4) return 'text-yellow-600';
    return 'text-red-600';
  };

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Agent Experience</h1>
          <p className="text-muted-foreground">
            Learning insights, experience records, and continuous improvement tracking
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
            <p className="font-semibold">Error Loading Experience Data</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {/* Statistics Cards */}
        {!loading && stats && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Experiences
              </h3>
              <p className="text-3xl font-bold">{stats.total_experiences}</p>
              <p className="text-xs text-green-600 mt-1">{stats.active_experiences} active</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Validated
              </h3>
              <p className="text-3xl font-bold text-green-600">{stats.validated_experiences}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {Math.round((stats.validated_experiences / stats.total_experiences) * 100)}% validation rate
              </p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Avg Confidence
              </h3>
              <p className={`text-3xl font-bold ${getConfidenceColor(stats.average_confidence)}`}>
                {Math.round(stats.average_confidence * 100)}%
              </p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Success Rate
              </h3>
              <p className="text-3xl font-bold text-blue-600">
                {Math.round(stats.average_success_rate * 100)}%
              </p>
            </div>
          </div>
        )}

        {/* Outcome Distribution */}
        {!loading && stats && Object.keys(stats.by_outcome).length > 0 && (
          <div className="bg-card border rounded-lg p-6 mb-8">
            <h2 className="text-2xl font-bold mb-4">By Outcome</h2>
            <div className="flex flex-wrap gap-3">
              {Object.entries(stats.by_outcome).map(([outcome, count]) => (
                <div
                  key={outcome}
                  className={`px-4 py-2 rounded-lg border ${getOutcomeColor(outcome)}`}
                >
                  <span className="mr-2">{getOutcomeIcon(outcome)}</span>
                  <span className="font-medium">{outcome}</span>
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
                <div key={type} className="bg-muted rounded-lg p-4">
                  <p className="text-sm font-medium mb-1">{type.replace(/_/g, ' ')}</p>
                  <p className="text-2xl font-bold">{count}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Filters */}
        {!loading && (
          <div className="flex flex-col md:flex-row gap-4 mb-6">
            {/* Type Filter */}
            {stats && Object.keys(stats.by_type).length > 0 && (
              <div className="flex-1">
                <label className="block text-sm font-medium mb-2">Experience Type</label>
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

            {/* Outcome Filter */}
            {stats && Object.keys(stats.by_outcome).length > 0 && (
              <div className="flex-1">
                <label className="block text-sm font-medium mb-2">Outcome</label>
                <select
                  value={outcomeFilter}
                  onChange={(e) => setOutcomeFilter(e.target.value)}
                  className="w-full px-3 py-2 border rounded-md bg-card"
                >
                  <option value="all">All Outcomes</option>
                  {Object.keys(stats.by_outcome).map((outcome) => (
                    <option key={outcome} value={outcome}>
                      {outcome}
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
                  checked={validatedOnly}
                  onChange={(e) => setValidatedOnly(e.target.checked)}
                  className="w-4 h-4"
                />
                <span className="text-sm">Validated only</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={activeOnly}
                  onChange={(e) => setActiveOnly(e.target.checked)}
                  className="w-4 h-4"
                />
                <span className="text-sm">Active only</span>
              </label>
            </div>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && experiences.length === 0 && (
          <div className="bg-card border rounded-lg p-12 text-center">
            <h3 className="text-xl font-semibold mb-2">No Experiences Found</h3>
            <p className="text-muted-foreground">
              {typeFilter !== 'all' || outcomeFilter !== 'all' || validatedOnly || !activeOnly
                ? 'No experiences match the selected filters'
                : 'No experiences have been recorded yet'}
            </p>
          </div>
        )}

        {/* Experiences List */}
        {!loading && experiences.length > 0 && (
          <div className="space-y-6">
            {experiences.map((exp) => (
              <div
                key={exp.id}
                className="bg-card border rounded-lg p-6 hover:border-primary transition-colors"
              >
                {/* Header */}
                <div className="flex items-start justify-between mb-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <h3 className="text-xl font-semibold">{exp.title}</h3>
                      <span className={`px-3 py-1 rounded-lg border ${getOutcomeColor(exp.outcome)}`}>
                        {getOutcomeIcon(exp.outcome)} {exp.outcome}
                      </span>
                      {exp.is_validated && (
                        <span className="px-2 py-1 text-xs rounded bg-green-100 text-green-800">
                          Validated
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground mb-1">{exp.description}</p>
                    <p className="text-xs text-muted-foreground">
                      Type: {exp.experience_type.replace(/_/g, ' ')} • Agent: {exp.agent_id.substring(0, 8)}...
                    </p>
                  </div>
                  <div className="text-right ml-4">
                    <p className="text-xs text-muted-foreground">Confidence</p>
                    <p className={`text-2xl font-bold ${getConfidenceColor(exp.confidence_score)}`}>
                      {Math.round(exp.confidence_score * 100)}%
                    </p>
                  </div>
                </div>

                {/* SAR (Situation-Action-Result) */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                  <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                    <p className="text-sm font-semibold text-blue-800 mb-2">Situation</p>
                    <p className="text-sm text-blue-900">{exp.situation}</p>
                  </div>

                  <div className="bg-purple-50 border border-purple-200 rounded-lg p-4">
                    <p className="text-sm font-semibold text-purple-800 mb-2">Action Taken</p>
                    <p className="text-sm text-purple-900">{exp.action_taken}</p>
                  </div>

                  <div className={`border rounded-lg p-4 ${getOutcomeColor(exp.outcome)}`}>
                    <p className="text-sm font-semibold mb-2">Result</p>
                    <p className="text-sm">{exp.result}</p>
                  </div>
                </div>

                {/* Lesson Learned */}
                <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-4">
                  <p className="text-sm font-semibold text-yellow-800 mb-2">💡 Lesson Learned</p>
                  <p className="text-sm text-yellow-900">{exp.lesson_learned}</p>
                </div>

                {/* Applicable Contexts */}
                {exp.applicable_contexts.length > 0 && (
                  <div className="mb-4">
                    <p className="text-sm font-semibold mb-2">Applicable Contexts:</p>
                    <div className="flex flex-wrap gap-2">
                      {exp.applicable_contexts.map((context, idx) => (
                        <span
                          key={idx}
                          className="px-3 py-1 text-xs rounded-full bg-indigo-100 text-indigo-800"
                        >
                          {context}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Stats */}
                <div className="flex items-center justify-between pt-4 border-t">
                  <div className="flex gap-6 text-sm">
                    <div>
                      <span className="text-muted-foreground">Applied: </span>
                      <span className="font-semibold">{exp.times_applied} times</span>
                    </div>
                    {exp.success_rate !== null && (
                      <div>
                        <span className="text-muted-foreground">Success Rate: </span>
                        <span className="font-semibold text-green-600">
                          {Math.round(exp.success_rate * 100)}%
                        </span>
                      </div>
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {new Date(exp.created_at).toLocaleDateString()}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Results Count */}
        {!loading && experiences.length > 0 && (
          <div className="mt-6 text-center text-sm text-muted-foreground">
            Showing {experiences.length} experience{experiences.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </div>
  );
}
