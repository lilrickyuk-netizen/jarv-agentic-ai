'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

// Alias route: "Company Operations" is the designed page at /company-operations.
// This redirect keeps the shorter /company path reachable instead of 404ing.
export default function CompanyAliasPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/dashboard/company-operations');
  }, [router]);
  return (
    <div className="min-h-screen flex items-center justify-center">
      <p className="text-sm text-muted-foreground">Redirecting to Company Operations…</p>
    </div>
  );
}
