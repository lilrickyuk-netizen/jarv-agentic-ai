'use client';

import { usePathname } from 'next/navigation';
import type { LucideIcon } from 'lucide-react';
import {
  Activity, ChartColumn, Bot, Briefcase, Building2, Cog, Flag, FolderKanban, GraduationCap, Handshake, ImageIcon,
  KeyRound, LayoutDashboard, LifeBuoy, ListChecks, Megaphone, MessagesSquare, Network, PenLine, PoundSterling,
  Puzzle, Rocket, Server, Settings, ShieldAlert, ShieldCheck, Sparkles, Brain, Target, UserCheck, UserPlus, Users,
  Wrench,
} from 'lucide-react';
import { JarvMark } from '@/components/jarv-mark';

/** Each page's icon (Lucide, ISC licence: the icon set shadcn/ui uses), shared by the cockpit and the section bar. */
export const ICONS: Record<string, LucideIcon> = {
  '/dashboard': LayoutDashboard,
  '/dashboard/command': Rocket,
  '/dashboard/tasks': ListChecks,
  '/dashboard/approvals': ShieldCheck,
  '/dashboard/boundary-reports': ShieldAlert,
  '/dashboard/checkpoints': Flag,
  '/dashboard/richard-boundary': UserCheck,
  '/dashboard/company-operations': Building2,
  '/dashboard/ai-standups': MessagesSquare,
  '/dashboard/live-operations': Activity,
  '/dashboard/business': Briefcase,
  '/dashboard/revenue-operations': PoundSterling,
  '/dashboard/analytics': ChartColumn,
  '/dashboard/marketing': Megaphone,
  '/dashboard/content': PenLine,
  '/dashboard/onboarding': UserPlus,
  '/dashboard/community': Users,
  '/dashboard/partnerships': Handshake,
  '/dashboard/sales': Target,
  '/dashboard/support': LifeBuoy,
  '/dashboard/agents': Bot,
  '/dashboard/capabilities': Puzzle,
  '/dashboard/swarm': Network,
  '/dashboard/tools': Wrench,
  '/dashboard/permissions': KeyRound,
  '/dashboard/memory': Brain,
  '/dashboard/experience': GraduationCap,
  '/dashboard/self-evolution': Sparkles,
  '/dashboard/workspaces': FolderKanban,
  '/dashboard/assets': ImageIcon,
  '/dashboard/operations': Cog,
  '/dashboard/infrastructure': Server,
  '/dashboard/settings': Settings,
};

/** A page's icon, or nothing for a page without one. */
export function NavIcon({ href, size = 14 }: { href: string; size?: number }) {
  const Icon = ICONS[href];
  return Icon ? <Icon size={size} aria-hidden="true" className="shrink-0" /> : null;
}

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
    { href: '/dashboard/capabilities', label: 'Capabilities' },
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
        <a href="/dashboard" className="font-bold tracking-wider shrink-0 py-1 inline-flex items-center gap-2"><JarvMark size={22} title="" />JAI</a>
        {SECTIONS.map((section) => (
          <div key={section.group} className="flex items-center gap-1 shrink-0">
            <span className="text-[10px] uppercase tracking-widest text-muted-foreground mr-1">{section.group}</span>
            {section.links.filter((l) => l.href !== '/dashboard').map((link) => (
              <a key={link.href} href={link.href} aria-current={active(link.href) ? 'page' : undefined}
                className={`px-2 py-1 rounded whitespace-nowrap inline-flex items-center gap-1.5 ${active(link.href) ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}>
                <NavIcon href={link.href} />{link.label}
              </a>
            ))}
          </div>
        ))}
      </div>
    </nav>
  );
}
