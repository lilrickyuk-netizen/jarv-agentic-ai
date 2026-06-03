'use client';

export default function CommunityPage() {
  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Community</h1>
          <p className="text-muted-foreground">Community management, engagement, and growth</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Community Metrics</h2>
            <p className="text-muted-foreground">Track community size, engagement, and activity.</p>
          </div>
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Moderation</h2>
            <p className="text-muted-foreground">Community moderation and content management.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
