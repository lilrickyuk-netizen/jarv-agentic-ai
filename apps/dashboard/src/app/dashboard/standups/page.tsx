'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

// Alias route: "AI Standups" is the designed page at /ai-standups.
// This redirect keeps the shorter /standups path reachable instead of 404ing.
export default function StandupsAliasPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/dashboard/ai-standups');
  }, [router]);
  return (
    <div className="min-h-screen flex items-center justify-center">
      <p className="text-sm text-muted-foreground">Redirecting to AI Standups…</p>
    </div>
  );
}
