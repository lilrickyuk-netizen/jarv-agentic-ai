'use client';

export default function BusinessPage() {
  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Business</h1>
          <p className="text-muted-foreground">Business workflows, strategy, and operations</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Strategic Planning</h2>
            <p className="text-muted-foreground">Business strategy, goals, and strategic initiatives.</p>
          </div>
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Performance</h2>
            <p className="text-muted-foreground">Business metrics, KPIs, and performance tracking.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
