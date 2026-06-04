'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api';

interface Tool {
  name: string;
  description: string;
  category: string;
  required_authority_level: number;
  requires_approval: boolean;
  is_implemented: boolean;
}

interface ToolsListResponse {
  tools: Tool[];
  total: number;
  implemented: number;
  unimplemented: number;
}

interface ToolStats {
  total_required: number;
  total_registered: number;
  implemented: number;
  unimplemented: number;
  completion_percentage: number;
  by_category: Record<string, Record<string, number>>;
}

export default function ToolsPage() {
  const router = useRouter();
  const [toolsData, setToolsData] = useState<ToolsListResponse | null>(null);
  const [stats, setStats] = useState<ToolStats | null>(null);
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
      // Fetch tools
      const params = new URLSearchParams();
      if (selectedCategory !== 'all') {
        params.append('category', selectedCategory);
      }
      if (showImplementedOnly) {
        params.append('only_implemented', 'true');
      }

      const toolsResponse = await apiClient.get<ToolsListResponse>(
        `/api/tools?${params.toString()}`
      );

      if (toolsResponse.error) {
        setError(toolsResponse.error);
      } else if (toolsResponse.data) {
        setToolsData(toolsResponse.data);
      }

      // Fetch stats
      const statsResponse = await apiClient.get<ToolStats>('/api/tools/stats');
      if (!statsResponse.error && statsResponse.data) {
        setStats(statsResponse.data);
      }

      // Fetch categories
      const categoriesResponse = await apiClient.get<{ categories: string[] }>(
        '/api/tools/categories'
      );
      if (!categoriesResponse.error && categoriesResponse.data) {
        setCategories(categoriesResponse.data.categories);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch tools');
    } finally {
      setLoading(false);
    }
  };

  const getCategoryColor = (category: string) => {
    const colors: Record<string, string> = {
      'File Operations': 'bg-blue-100 text-blue-800',
      'Code Operations': 'bg-green-100 text-green-800',
      'System Operations': 'bg-purple-100 text-purple-800',
      'Database Operations': 'bg-orange-100 text-orange-800',
      'Network Operations': 'bg-pink-100 text-pink-800',
      'AI Operations': 'bg-indigo-100 text-indigo-800',
      'Cloud Operations': 'bg-cyan-100 text-cyan-800',
      'DevOps Operations': 'bg-teal-100 text-teal-800',
    };
    return colors[category] || 'bg-gray-100 text-gray-800';
  };

  const getAuthorityColor = (level: number) => {
    if (level >= 8) return 'text-red-600';
    if (level >= 5) return 'text-orange-600';
    if (level >= 3) return 'text-yellow-600';
    return 'text-green-600';
  };

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Tools</h1>
          <p className="text-muted-foreground">
            Registry of all available tools and their capabilities
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
            <p className="font-semibold">Error Loading Tools</p>
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
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">
                Categories
              </h3>
              <p className="text-3xl font-bold">{categories.length}</p>
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
                    {category}
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
        {!loading && !error && toolsData && toolsData.tools.length === 0 && (
          <div className="bg-card border rounded-lg p-12 text-center">
            <h3 className="text-xl font-semibold mb-2">No Tools Found</h3>
            <p className="text-muted-foreground">
              {showImplementedOnly || selectedCategory !== 'all'
                ? 'Try adjusting your filters'
                : 'No tools are registered in the system'}
            </p>
          </div>
        )}

        {/* Tools Grid */}
        {!loading && toolsData && toolsData.tools.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {toolsData.tools.map((tool) => (
              <div
                key={tool.name}
                className={`bg-card border rounded-lg p-6 hover:border-primary transition-colors ${
                  !tool.is_implemented ? 'opacity-60' : ''
                }`}
              >
                {/* Header */}
                <div className="flex items-start justify-between mb-3">
                  <h3 className="font-semibold text-lg flex-1 mr-2">{tool.name}</h3>
                  {tool.is_implemented ? (
                    <span className="px-2 py-1 text-xs rounded bg-green-100 text-green-800 whitespace-nowrap">
                      Active
                    </span>
                  ) : (
                    <span className="px-2 py-1 text-xs rounded bg-gray-100 text-gray-800 whitespace-nowrap">
                      Pending
                    </span>
                  )}
                </div>

                {/* Description */}
                <p className="text-sm text-muted-foreground mb-4 line-clamp-3">
                  {tool.description}
                </p>

                {/* Metadata */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Category</span>
                    <span className={`px-2 py-1 rounded ${getCategoryColor(tool.category)}`}>
                      {tool.category}
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Authority</span>
                    <span className={`font-semibold ${getAuthorityColor(tool.required_authority_level)}`}>
                      Level {tool.required_authority_level}
                    </span>
                  </div>

                  {tool.requires_approval && (
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-muted-foreground">Approval</span>
                      <span className="px-2 py-1 rounded bg-yellow-100 text-yellow-800">
                        Required
                      </span>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Results Count */}
        {!loading && toolsData && toolsData.tools.length > 0 && (
          <div className="mt-6 text-center text-sm text-muted-foreground">
            Showing {toolsData.tools.length} of {toolsData.total} tool
            {toolsData.total !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </div>
  );
}
