'use client';

export default function PartnershipsPage() {
  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Partnerships</h1>
          <p className="text-muted-foreground">Partnership management, integrations, and collaborations</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Active Partnerships</h2>
            <p className="text-muted-foreground">Manage strategic partnerships and collaborations.</p>
          </div>
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Integration Status</h2>
            <p className="text-muted-foreground">Track partnership integrations and API connections.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
