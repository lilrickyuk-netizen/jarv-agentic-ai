'use client';

import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';

interface Asset {
  id: string;
  workspace_id: string;
  asset_name: string;
  asset_type: string;
  category: string | null;
  description: string | null;
  file_size: number | null;
  mime_type: string | null;
  is_active: boolean;
  is_public: boolean;
  license_type: string | null;
  download_count: number;
  view_count: number;
  tags: string[];
  created_at: string;
}

interface AssetStats {
  total_assets: number;
  active_assets: number;
  by_type: Record<string, number>;
  total_downloads: number;
  total_views: number;
}

export default function AssetsPage() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [stats, setStats] = useState<AssetStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    setLoading(true);
    setError(null);

    try {
      const assetsResponse = await apiClient.get<Asset[]>('/assets/list');
      if (assetsResponse.error) {
        setError(assetsResponse.error);
      } else if (assetsResponse.data) {
        setAssets(assetsResponse.data);
      }

      const statsResponse = await apiClient.get<AssetStats>('/assets/stats');
      if (!statsResponse.error && statsResponse.data) {
        setStats(statsResponse.data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch assets');
    } finally {
      setLoading(false);
    }
  };

  const formatFileSize = (bytes: number | null) => {
    if (!bytes) return 'N/A';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
  };

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Digital Assets</h1>
          <p className="text-muted-foreground">Asset management, licensing, and usage tracking</p>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
          </div>
        )}

        {error && (
          <div className="bg-destructive/10 border border-destructive text-destructive px-4 py-3 rounded-lg mb-6">
            <p className="font-semibold">Error Loading Assets</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {!loading && stats && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">Total Assets</h3>
              <p className="text-3xl font-bold">{stats.total_assets}</p>
            </div>
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">Active</h3>
              <p className="text-3xl font-bold text-green-600">{stats.active_assets}</p>
            </div>
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">Downloads</h3>
              <p className="text-3xl font-bold text-blue-600">{stats.total_downloads}</p>
            </div>
            <div className="bg-card border rounded-lg p-6">
              <h3 className="text-sm font-medium text-muted-foreground mb-2">Views</h3>
              <p className="text-3xl font-bold text-purple-600">{stats.total_views}</p>
            </div>
          </div>
        )}

        {!loading && !error && assets.length === 0 && (
          <div className="bg-card border rounded-lg p-12 text-center">
            <h3 className="text-xl font-semibold mb-2">No Assets</h3>
            <p className="text-muted-foreground">No digital assets have been uploaded</p>
          </div>
        )}

        {!loading && assets.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {assets.map((asset) => (
              <div key={asset.id} className="bg-card border rounded-lg p-6">
                <div className="flex items-start justify-between mb-3">
                  <h3 className="font-semibold">{asset.asset_name}</h3>
                  {asset.is_public && (
                    <span className="px-2 py-1 text-xs rounded bg-blue-100 text-blue-800">Public</span>
                  )}
                </div>
                <p className="text-sm text-muted-foreground mb-2">{asset.asset_type}</p>
                {asset.description && (
                  <p className="text-sm text-muted-foreground mb-3 line-clamp-2">{asset.description}</p>
                )}
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <p className="text-muted-foreground">Size</p>
                    <p className="font-medium">{formatFileSize(asset.file_size)}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Downloads</p>
                    <p className="font-medium">{asset.download_count}</p>
                  </div>
                </div>
                {asset.tags.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1">
                    {asset.tags.slice(0, 3).map((tag, idx) => (
                      <span key={idx} className="px-2 py-0.5 text-xs rounded-full bg-muted">
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
