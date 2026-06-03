'use client';

export default function InfrastructurePage() {
  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Infrastructure</h1>
          <p className="text-muted-foreground">System infrastructure, resources, and capacity management</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Compute Resources</h2>
            <p className="text-muted-foreground">CPU, memory, and compute capacity utilization.</p>
          </div>
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Storage</h2>
            <p className="text-muted-foreground">Database storage, file storage, and backup status.</p>
          </div>
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Network</h2>
            <p className="text-muted-foreground">Network connectivity, bandwidth, and latency metrics.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
