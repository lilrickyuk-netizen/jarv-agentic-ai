"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { SectionNav } from "@/components/ops/section-nav";
import { LiveMissionDock } from "@/components/live-mission-dock";
import { isAuthenticated } from "@/lib/auth";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [authChecked, setAuthChecked] = useState(false);

  // Links inside the dashboard change page without reloading it, so the live mission and the conversation
  // with JARV carry on across pages (a plain link reloaded everything and ended the conversation).
  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = (event.target as HTMLElement | null)?.closest?.("a");
      if (!link || link.target || link.hasAttribute("download")) return;
      const href = link.getAttribute("href") || "";
      if (!href.startsWith("/dashboard")) return;
      event.preventDefault();
      router.push(href);
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, [router]);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.push("/login");
    } else {
      setAuthChecked(true);
    }
  }, [router]);

  if (!authChecked) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 dark:border-gray-100"></div>
          <p className="mt-4 text-sm text-gray-600 dark:text-gray-400">
            Loading...
          </p>
        </div>
      </div>
    );
  }

  // The Command Center has its own cockpit navigation; every other page gets the section bar.
  return (
    <>
      {pathname !== "/dashboard" && <SectionNav />}
      {children}
      <LiveMissionDock />
    </>
  );
}
