'use client';

import { useEffect, useState } from 'react';

export default function AnalyticsPage() {
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(false);
  }, []);

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Analytics</h1>
          <p className="text-muted-foreground">System analytics, metrics, and performance insights</p>
        </div>

        {!loading && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <div className="bg-card border rounded-lg p-6">
              <h2 className="text-xl font-bold mb-4">System Performance</h2>
              <p className="text-muted-foreground">Track system performance metrics, uptime, and response times across all services.</p>
            </div>
            <div className="bg-card border rounded-lg p-6">
              <h2 className="text-xl font-bold mb-4">Usage Analytics</h2>
              <p className="text-muted-foreground">Monitor agent usage, task execution patterns, and resource utilization.</p>
            </div>
            <div className="bg-card border rounded-lg p-6">
              <h2 className="text-xl font-bold mb-4">Cost Analysis</h2>
              <p className="text-muted-foreground">Track AI token usage, compute costs, and budget allocation across workspaces.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
