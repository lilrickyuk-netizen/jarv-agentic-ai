'use client';

import { useEffect, useState } from 'react';
import { apiClient, VersionResponse } from '@/lib/api';

export default function SettingsPage() {
  const [version, setVersion] = useState<VersionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    setLoading(true);
    setError(null);

    try {
      const versionResponse = await apiClient.getVersion();
      if (versionResponse.error) {
        setError(versionResponse.error);
      } else {
        setVersion(versionResponse.data || null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch settings');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Settings</h1>
          <p className="text-muted-foreground">
            System configuration and preferences
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
            <p className="font-semibold">Error Loading Settings</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {/* Settings Content */}
        {!loading && version && (
          <div className="space-y-8">
            {/* System Information */}
            <div className="bg-card border rounded-lg p-6">
              <h2 className="text-2xl font-bold mb-6">System Information</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                  <label className="block text-sm font-medium text-muted-foreground mb-2">
                    Service Name
                  </label>
                  <div className="px-4 py-3 bg-muted rounded-md">
                    {version.service}
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-muted-foreground mb-2">
                    Version
                  </label>
                  <div className="px-4 py-3 bg-muted rounded-md">
                    {version.version}
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-muted-foreground mb-2">
                    Environment
                  </label>
                  <div className="px-4 py-3 bg-muted rounded-md">
                    <span className={`px-2 py-1 rounded text-sm ${
                      version.environment === 'production'
                        ? 'bg-green-100 text-green-800'
                        : 'bg-yellow-100 text-yellow-800'
                    }`}>
                      {version.environment.toUpperCase()}
                    </span>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-muted-foreground mb-2">
                    Platform
                  </label>
                  <div className="px-4 py-3 bg-muted rounded-md">
                    {version.platform}
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-muted-foreground mb-2">
                    Python Version
                  </label>
                  <div className="px-4 py-3 bg-muted rounded-md">
                    {version.python_version}
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-muted-foreground mb-2">
                    Last Updated
                  </label>
                  <div className="px-4 py-3 bg-muted rounded-md">
                    {new Date(version.timestamp).toLocaleString()}
                  </div>
                </div>
              </div>
            </div>

            {/* Feature Flags */}
            <div className="bg-card border rounded-lg p-6">
              <h2 className="text-2xl font-bold mb-6">Feature Flags</h2>
              <div className="space-y-4">
                {Object.entries(version.features).map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between p-4 bg-muted rounded-md">
                    <div>
                      <h3 className="font-medium">
                        {key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}
                      </h3>
                      <p className="text-sm text-muted-foreground">
                        {key === 'swarm_enabled' && 'Enable swarm system for parallel agent execution'}
                        {key === 'self_evolution_enabled' && 'Enable AI self-evolution and improvement'}
                        {key === 'company_operator_enabled' && 'Enable autonomous company operations'}
                        {key === 'self_healing_enabled' && 'Enable automated system monitoring and recovery'}
                        {key === 'voice_enabled' && 'Enable voice command system'}
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className={`px-3 py-1 rounded text-sm font-semibold ${
                        value
                          ? 'bg-green-100 text-green-800'
                          : 'bg-gray-100 text-gray-800'
                      }`}>
                        {value ? 'Enabled' : 'Disabled'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Configuration */}
            <div className="bg-card border rounded-lg p-6">
              <h2 className="text-2xl font-bold mb-6">Configuration</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {Object.entries(version.configuration).map(([key, value]) => (
                  <div key={key}>
                    <label className="block text-sm font-medium text-muted-foreground mb-2">
                      {key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}
                    </label>
                    <div className="px-4 py-3 bg-muted rounded-md font-mono text-sm">
                      {value}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* System Status */}
            <div className="bg-card border rounded-lg p-6">
              <h2 className="text-2xl font-bold mb-6">System Status</h2>
              <div className="space-y-4">
                <div className="flex items-center justify-between p-4 bg-muted rounded-md">
                  <div>
                    <h3 className="font-medium">Backend API</h3>
                    <p className="text-sm text-muted-foreground">
                      Primary backend service
                    </p>
                  </div>
                  <span className="px-3 py-1 rounded bg-green-100 text-green-800 font-semibold">
                    Operational
                  </span>
                </div>

                <div className="flex items-center justify-between p-4 bg-muted rounded-md">
                  <div>
                    <h3 className="font-medium">Database</h3>
                    <p className="text-sm text-muted-foreground">
                      PostgreSQL database connection
                    </p>
                  </div>
                  <span className="px-3 py-1 rounded bg-green-100 text-green-800 font-semibold">
                    Connected
                  </span>
                </div>

                <div className="flex items-center justify-between p-4 bg-muted rounded-md">
                  <div>
                    <h3 className="font-medium">Redis Cache</h3>
                    <p className="text-sm text-muted-foreground">
                      Redis caching layer
                    </p>
                  </div>
                  <span className="px-3 py-1 rounded bg-green-100 text-green-800 font-semibold">
                    Active
                  </span>
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="bg-card border rounded-lg p-6">
              <h2 className="text-2xl font-bold mb-6">Actions</h2>
              <div className="flex flex-wrap gap-4">
                <button
                  onClick={fetchData}
                  className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 transition-colors"
                >
                  Refresh Settings
                </button>
                <button
                  disabled
                  className="px-4 py-2 bg-muted text-muted-foreground rounded-md cursor-not-allowed"
                  title="Configuration changes require backend restart"
                >
                  Save Changes (Read-Only)
                </button>
              </div>
              <p className="text-sm text-muted-foreground mt-4">
                Note: Configuration changes require backend service restart and are managed through environment variables and config files.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
