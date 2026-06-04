'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api';

interface Experience {
  id: string;
  workspace_id: string;
  agent_id: string | null;
  experience_type: string;
  content: string;
  context: Record<string, any>;
  lessons_learned: string[];
  created_at: string;
}

interface Improvement {
  id: string;
  workspace_id: string;
  improvement_type: string;
  description: string;
  status: string;
  priority: number;
  estimated_impact: string;
  proposed_changes: Record<string, any>;
  created_at: string;
  approved_at: string | null;
  implemented_at: string | null;
}

export default function SelfEvolutionPage() {
  const router = useRouter();
  const [experiences, setExperiences] = useState<Experience[]>([]);
  const [improvements, setImprovements] = useState<Improvement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'experiences' | 'improvements'>('improvements');

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    setLoading(true);
    setError(null);

    try {
      // Fetch experiences
      const experiencesResponse = await apiClient.get<Experience[]>('/api/evolution/experiences');
      if (!experiencesResponse.error && experiencesResponse.data) {
        setExperiences(experiencesResponse.data);
      }

      // Fetch improvements
      const improvementsResponse = await apiClient.get<Improvement[]>('/api/evolution/improvements');
      if (!improvementsResponse.error && improvementsResponse.data) {
        setImprovements(improvementsResponse.data);
      }

      if (experiencesResponse.error && improvementsResponse.error) {
        setError('Failed to fetch evolution data');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch evolution data');
    } finally {
      setLoading(false);
    }
  };

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      proposed: 'bg-blue-100 text-blue-800',
      approved: 'bg-green-100 text-green-800',
      rejected: 'bg-red-100 text-red-800',
      implemented: 'bg-purple-100 text-purple-800',
      pending: 'bg-yellow-100 text-yellow-800',
    };
    return colors[status] || 'bg-gray-100 text-gray-800';
  };

  const getPriorityColor = (priority: number) => {
    if (priority >= 8) return 'text-red-600 font-bold';
    if (priority >= 5) return 'text-orange-600 font-semibold';
    return 'text-gray-600';
  };

  const proposedImprovements = improvements.filter(i => i.status === 'proposed');
  const approvedImprovements = improvements.filter(i => i.status === 'approved');
  const implementedImprovements = improvements.filter(i => i.status === 'implemented');

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Self-Evolution System</h1>
          <p className="text-muted-foreground">
            AI system learning, improvement proposals, and evolutionary changes
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
            <p className="font-semibold">Error Loading Evolution Data</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {/* Statistics Cards */}
        {!loading && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Experiences
              </h3>
              <p className="text-3xl font-bold">{experiences.length}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Improvements Proposed
              </h3>
              <p className="text-3xl font-bold text-blue-600">{proposedImprovements.length}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Approved
              </h3>
              <p className="text-3xl font-bold text-green-600">{approvedImprovements.length}</p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Implemented
              </h3>
              <p className="text-3xl font-bold text-purple-600">{implementedImprovements.length}</p>
            </div>
          </div>
        )}

        {/* Tabs */}
        {!loading && (
          <div className="flex gap-2 mb-6">
            <button
              onClick={() => setActiveTab('improvements')}
              className={`px-4 py-2 rounded-md transition-colors ${
                activeTab === 'improvements'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-card border hover:border-primary'
              }`}
            >
              Improvements ({improvements.length})
            </button>
            <button
              onClick={() => setActiveTab('experiences')}
              className={`px-4 py-2 rounded-md transition-colors ${
                activeTab === 'experiences'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-card border hover:border-primary'
              }`}
            >
              Experiences ({experiences.length})
            </button>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && improvements.length === 0 && experiences.length === 0 && (
          <div className="bg-card border rounded-lg p-12 text-center">
            <h3 className="text-xl font-semibold mb-2">No Evolution Data</h3>
            <p className="text-muted-foreground mb-4">
              The self-evolution system has not recorded any experiences or improvements yet
            </p>
            <p className="text-sm text-muted-foreground">
              As the AI system runs and learns, it will propose improvements and record experiences here
            </p>
          </div>
        )}

        {/* Improvements Tab */}
        {!loading && activeTab === 'improvements' && improvements.length > 0 && (
          <div className="space-y-4">
            {improvements.map((improvement) => (
              <div
                key={improvement.id}
                className="bg-card border rounded-lg p-6 hover:border-primary transition-colors"
              >
                {/* Header */}
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <h3 className="text-lg font-semibold">
                        {improvement.improvement_type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                      </h3>
                      <span className={`px-2 py-1 text-xs ${getPriorityColor(improvement.priority)}`}>
                        P{improvement.priority}
                      </span>
                    </div>
                    <p className="text-sm text-muted-foreground">{improvement.description}</p>
                  </div>
                  <span className={`px-3 py-1 text-sm rounded ml-4 ${getStatusColor(improvement.status)}`}>
                    {improvement.status}
                  </span>
                </div>

                {/* Details */}
                <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
                  <div>
                    <p className="text-muted-foreground">Estimated Impact</p>
                    <p className="font-medium">{improvement.estimated_impact}</p>
                  </div>

                  <div>
                    <p className="text-muted-foreground">Proposed</p>
                    <p className="font-medium">{new Date(improvement.created_at).toLocaleDateString()}</p>
                  </div>

                  {improvement.implemented_at && (
                    <div>
                      <p className="text-muted-foreground">Implemented</p>
                      <p className="font-medium">{new Date(improvement.implemented_at).toLocaleDateString()}</p>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Experiences Tab */}
        {!loading && activeTab === 'experiences' && experiences.length > 0 && (
          <div className="space-y-4">
            {experiences.map((experience) => (
              <div
                key={experience.id}
                className="bg-card border rounded-lg p-6 hover:border-primary transition-colors"
              >
                {/* Header */}
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1">
                    <h3 className="text-lg font-semibold mb-2">
                      {experience.experience_type.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
                    </h3>
                    <p className="text-sm text-muted-foreground line-clamp-2">{experience.content}</p>
                  </div>
                  <div className="text-xs text-muted-foreground ml-4">
                    {new Date(experience.created_at).toLocaleDateString()}
                  </div>
                </div>

                {/* Lessons Learned */}
                {experience.lessons_learned && experience.lessons_learned.length > 0 && (
                  <div className="mt-4 pt-4 border-t">
                    <p className="text-sm font-medium mb-2">Lessons Learned:</p>
                    <ul className="space-y-1">
                      {experience.lessons_learned.map((lesson, idx) => (
                        <li key={idx} className="text-sm text-muted-foreground flex items-start gap-2">
                          <span className="text-primary mt-1">•</span>
                          <span>{lesson}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Results Count */}
        {!loading && (
          <div className="mt-6 text-center text-sm text-muted-foreground">
            {activeTab === 'improvements' && improvements.length > 0 && (
              <span>Showing {improvements.length} improvement{improvements.length !== 1 ? 's' : ''}</span>
            )}
            {activeTab === 'experiences' && experiences.length > 0 && (
              <span>Showing {experiences.length} experience{experiences.length !== 1 ? 's' : ''}</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
