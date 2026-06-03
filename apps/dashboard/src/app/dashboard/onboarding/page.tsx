'use client';

export default function OnboardingPage() {
  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-4xl font-bold mb-2">Onboarding</h1>
          <p className="text-muted-foreground">User onboarding workflows and success tracking</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Onboarding Flows</h2>
            <p className="text-muted-foreground">Manage onboarding sequences and user activation.</p>
          </div>
          <div className="bg-card border rounded-lg p-6">
            <h2 className="text-xl font-bold mb-4">Success Metrics</h2>
            <p className="text-muted-foreground">Track activation rates and onboarding completion.</p>
          </div>
        </div>
      </div>
    </div>
  );
}
