'use client';

export default function SalesPage() {
  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Sales</h1>
          <p className="text-muted-foreground">Sales pipeline, deals, and revenue tracking</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Pipeline</h2>
            <p className="text-muted-foreground">Sales pipeline stages and deal progression.</p>
          </div>
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Leads</h2>
            <p className="text-muted-foreground">Lead management and qualification tracking.</p>
          </div>
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Revenue</h2>
            <p className="text-muted-foreground">Revenue forecasting and deal metrics.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
