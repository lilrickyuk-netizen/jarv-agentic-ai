'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api';

interface Agent {
  name: string;
  role: string;
  category: string;
  description: string;
  required_authority_level: number;
  default_tools: string[];
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

export default function AgentsPage() {
  const router = useRouter();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [stats, setStats] = useState<AgentStats | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [showImplementedOnly, setShowImplementedOnly] = useState(false);

  useEffect(() => {
    fetchData();
  }, [selectedCategory, showImplementedOnly]);

  const fetchData = async () => {
    setLoading(true);
    setError(null);

    try {
      // Fetch agents
      const params = new URLSearchParams();
      if (selectedCategory !== 'all') {
        params.append('category', selectedCategory);
      }
      if (showImplementedOnly) {
        params.append('only_implemented', 'true');
      }

      const agentsResponse = await apiClient.get<Agent[]>(
        `/api/agents/list?${params.toString()}`
      );

      if (agentsResponse.error) {
        setError(agentsResponse.error);
      } else if (agentsResponse.data) {
        setAgents(agentsResponse.data);
      }

      // Fetch stats
      const statsResponse = await apiClient.get<AgentStats>('/api/agents/stats');
      if (!statsResponse.error && statsResponse.data) {
        setStats(statsResponse.data);
      }

      // Fetch categories
      const categoriesResponse = await apiClient.get<string[]>('/api/agents/categories');
      if (!categoriesResponse.error && categoriesResponse.data) {
        setCategories(categoriesResponse.data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch agents');
    } finally {
      setLoading(false);
    }
  };

  const getCategoryColor = (category: string) => {
    const colors: Record<string, string> = {
      core: 'bg-blue-100 text-blue-800',
      development: 'bg-green-100 text-green-800',
      infrastructure: 'bg-purple-100 text-purple-800',
      business: 'bg-orange-100 text-orange-800',
      customer: 'bg-pink-100 text-pink-800',
      financial: 'bg-yellow-100 text-yellow-800',
      specialized: 'bg-gray-100 text-gray-800',
    };
    return colors[category] || 'bg-gray-100 text-gray-800';
  };

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Agents</h1>
          <p className="text-muted-foreground">
            Registry of all AI agents in the JARV system
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
            <p className="font-semibold">Error Loading Agents</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {/* Statistics Cards */}
        {!loading && stats && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Total Registered
              </h3>
              <p className="text-3xl font-bold">{stats.total_registered}</p>
              <p className="text-xs text-muted-foreground mt-1">
                of {stats.total_required} required
              </p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Implemented
              </h3>
              <p className="text-3xl font-bold text-green-600">{stats.implemented}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {stats.completion_percentage.toFixed(1)}% complete
              </p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Unimplemented
              </h3>
              <p className="text-3xl font-bold text-orange-600">{stats.unimplemented}</p>
              <p className="text-xs text-muted-foreground mt-1">
                awaiting implementation
              </p>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Categories
              </h3>
              <p className="text-3xl font-bold">{categories.length}</p>
              <p className="text-xs text-muted-foreground mt-1">
                agent categories
              </p>
            </div>
          </div>
        )}

        {/* Filters */}
        {!loading && (
          <div className="flex flex-col md:flex-row gap-4 mb-6">
            {/* Category Filter */}
            <div className="flex-1">
              <label className="block text-sm font-medium mb-2">Category</label>
              <select
                value={selectedCategory}
                onChange={(e) => setSelectedCategory(e.target.value)}
                className="w-full px-3 py-2 border rounded-md bg-card"
              >
                <option value="all">All Categories</option>
                {categories.map((category) => (
                  <option key={category} value={category}>
                    {category.charAt(0).toUpperCase() + category.slice(1)}
                  </option>
                ))}
              </select>
            </div>

            {/* Implementation Filter */}
            <div className="flex items-end">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={showImplementedOnly}
                  onChange={(e) => setShowImplementedOnly(e.target.checked)}
                  className="w-4 h-4"
                />
                <span className="text-sm">Implemented only</span>
              </label>
            </div>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && agents.length === 0 && (
          <div className="bg-card border rounded-lg p-12 text-center">
            <h3 className="text-xl font-semibold mb-2">No Agents Found</h3>
            <p className="text-muted-foreground">
              {showImplementedOnly || selectedCategory !== 'all'
                ? 'Try adjusting your filters'
                : 'No agents are registered in the system'}
            </p>
          </div>
        )}

        {/* Agents Grid */}
        {!loading && agents.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {agents.map((agent) => (
              <div
                key={agent.name}
                className={`bg-card border rounded-lg p-6 hover:border-primary transition-colors ${
                  !agent.is_implemented ? 'opacity-60' : ''
                }`}
              >
                {/* Header */}
                <div className="flex items-start justify-between mb-3">
                  <h3 className="font-semibold text-lg">{agent.name}</h3>
                  {agent.is_implemented ? (
                    <span className="px-2 py-1 text-xs rounded bg-green-100 text-green-800">
                      Active
                    </span>
                  ) : (
                    <span className="px-2 py-1 text-xs rounded bg-gray-100 text-gray-800">
                      Pending
                    </span>
                  )}
                </div>

                {/* Role */}
                <p className="text-sm text-muted-foreground mb-3">{agent.role}</p>

                {/* Description */}
                <p className="text-sm mb-4 line-clamp-2">{agent.description}</p>

                {/* Metadata */}
                <div className="space-y-2 mb-4">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Category</span>
                    <span className={`px-2 py-1 rounded ${getCategoryColor(agent.category)}`}>
                      {agent.category}
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Authority</span>
                    <span className="font-medium">Level {agent.required_authority_level}</span>
                  </div>

                  {agent.default_tools.length > 0 && (
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-muted-foreground">Tools</span>
                      <span className="font-medium">{agent.default_tools.length} tools</span>
                    </div>
                  )}
                </div>

                {/* Tools (expandable) */}
                {agent.default_tools.length > 0 && (
                  <details className="text-xs">
                    <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                      View default tools
                    </summary>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {agent.default_tools.slice(0, 8).map((tool) => (
                        <span
                          key={tool}
                          className="px-1.5 py-0.5 rounded bg-muted text-muted-foreground"
                        >
                          {tool}
                        </span>
                      ))}
                      {agent.default_tools.length > 8 && (
                        <span className="px-1.5 py-0.5 text-muted-foreground">
                          +{agent.default_tools.length - 8} more
                        </span>
                      )}
                    </div>
                  </details>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Results Count */}
        {!loading && agents.length > 0 && (
          <div className="mt-6 text-center text-sm text-muted-foreground">
            Showing {agents.length} agent{agents.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </div>
  );
}
