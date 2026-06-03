'use client';

export default function SupportPage() {
  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Support</h1>
          <p className="text-muted-foreground">Customer support, issue tracking, and resolution management</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Support Tickets</h2>
            <p className="text-muted-foreground">Track and manage customer support requests and issues.</p>
          </div>
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Knowledge Base</h2>
            <p className="text-muted-foreground">Documentation, FAQs, and self-service resources.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
