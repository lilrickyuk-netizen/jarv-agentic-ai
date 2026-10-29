'use client';

import { usePathname } from 'next/navigation';

/** Every dashboard page, grouped the way Richard works: command, company, growth, agents, systems. */
export const SECTIONS: { group: string; links: { href: string; label: string }[] }[] = [
  { group: 'Command', links: [
    { href: '/dashboard', label: 'Command Center' },
    { href: '/dashboard/command', label: 'Missions' },
    { href: '/dashboard/tasks', label: 'Tasks' },
    { href: '/dashboard/approvals', label: 'Approvals' },
    { href: '/dashboard/boundary-reports', label: 'Boundary Reports' },
    { href: '/dashboard/checkpoints', label: 'Checkpoints' },
    { href: '/dashboard/richard-boundary', label: 'Richard Boundary' },
  ] },
  { group: 'Company', links: [
    { href: '/dashboard/company-operations', label: 'Company Operations' },
    { href: '/dashboard/ai-standups', label: 'AI Standups' },
    { href: '/dashboard/live-operations', label: 'Live Operations' },
    { href: '/dashboard/business', label: 'Business' },
    { href: '/dashboard/revenue-operations', label: 'Revenue Operations' },
    { href: '/dashboard/analytics', label: 'Analytics' },
  ] },
  { group: 'Growth', links: [
    { href: '/dashboard/marketing', label: 'Marketing' },
    { href: '/dashboard/content', label: 'Content' },
    { href: '/dashboard/onboarding', label: 'Onboarding' },
    { href: '/dashboard/community', label: 'Community' },
    { href: '/dashboard/partnerships', label: 'Partnerships' },
    { href: '/dashboard/sales', label: 'Sales' },
    { href: '/dashboard/support', label: 'Support' },
  ] },
  { group: 'Agents', links: [
    { href: '/dashboard/agents', label: 'Agents' },
    { href: '/dashboard/swarm', label: 'Swarm' },
    { href: '/dashboard/tools', label: 'Tools' },
    { href: '/dashboard/permissions', label: 'Permissions' },
    { href: '/dashboard/memory', label: 'Memory' },
    { href: '/dashboard/experience', label: 'Experience' },
    { href: '/dashboard/self-evolution', label: 'Self-Evolution' },
  ] },
  { group: 'Systems', links: [
    { href: '/dashboard/workspaces', label: 'Workspaces' },
    { href: '/dashboard/assets', label: 'Assets' },
    { href: '/dashboard/operations', label: 'Operations' },
    { href: '/dashboard/infrastructure', label: 'Infrastructure' },
    { href: '/dashboard/settings', label: 'Settings' },
  ] },
];

export function SectionNav() {
  const pathname = usePathname() ?? '';
  const active = (href: string) => (href === '/dashboard' ? pathname === href : pathname === href || pathname.startsWith(`${href}/`));
  return (
    <nav aria-label="Dashboard sections" className="border-b bg-card/80 backdrop-blur sticky top-0 z-20">
      <div className="max-w-7xl mx-auto px-4 md:px-8 py-2 flex gap-6 overflow-x-auto text-sm">
        <a href="/dashboard" className="font-bold tracking-wider shrink-0 py-1">JARV</a>
        {SECTIONS.map((section) => (
          <div key={section.group} className="flex items-center gap-1 shrink-0">
            <span className="text-[10px] uppercase tracking-widest text-muted-foreground mr-1">{section.group}</span>
            {section.links.filter((l) => l.href !== '/dashboard').map((link) => (
              <a key={link.href} href={link.href} aria-current={active(link.href) ? 'page' : undefined}
                className={`px-2 py-1 rounded whitespace-nowrap ${active(link.href) ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}>
                {link.label}
              </a>
            ))}
          </div>
        ))}
      </div>
    </nav>
  );
}
