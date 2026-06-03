'use client';

export default function ContentPage() {
  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Content</h1>
          <p className="text-muted-foreground">Content creation, management, and publishing workflows</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Content Library</h2>
            <p className="text-muted-foreground">Manage articles, posts, and content assets.</p>
          </div>
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Publishing Schedule</h2>
            <p className="text-muted-foreground">Content calendar and publishing workflows.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
