'use client';

import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/api';

interface PermissionSummary {
  role_count: number;
  agent_count: number;
  authority_levels: Record<string, number>;
}

export default function PermissionsPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    setLoading(true);
    setError(null);

    try {
      // Fetch permission data from agents and roles
      await new Promise(resolve => setTimeout(resolve, 500));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch permissions');
    } finally {
      setLoading(false);
    }
  };

  const authorityLevels = [
    { level: 1, name: 'Public', description: 'No special permissions required', color: 'bg-gray-100' },
    { level: 3, name: 'Basic', description: 'Standard operations', color: 'bg-blue-100' },
    { level: 5, name: 'Elevated', description: 'Sensitive operations', color: 'bg-yellow-100' },
    { level: 7, name: 'High', description: 'Critical operations', color: 'bg-orange-100' },
    { level: 9, name: 'Maximum', description: 'System-level operations', color: 'bg-red-100' },
  ];

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Permissions & Access Control</h1>
          <p className="text-muted-foreground">
            Authority levels, role-based access, and permission management
          </p>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
          </div>
        )}

        {error && (
          <div className="bg-destructive/10 border border-destructive text-destructive px-4 py-3 rounded-lg mb-6">
            <p className="font-semibold">Error Loading Permissions</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        {!loading && (
          <div className="space-y-6">
            <div className="bg-card border rounded-lg p-6">
              <h2 className="text-2xl font-bold mb-4">Authority Levels</h2>
              <div className="space-y-3">
                {authorityLevels.map((level) => (
                  <div key={level.level} className={`${level.color} border rounded-lg p-4`}>
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="font-semibold text-lg">Level {level.level} - {level.name}</h3>
                        <p className="text-sm text-muted-foreground">{level.description}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="bg-card border rounded-lg p-6">
              <h2 className="text-2xl font-bold mb-4">Permission System</h2>
              <p className="text-muted-foreground">
                The JARV permission system uses authority levels to control access to operations.
                Each agent and user is assigned an authority level that determines what actions they can perform.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
