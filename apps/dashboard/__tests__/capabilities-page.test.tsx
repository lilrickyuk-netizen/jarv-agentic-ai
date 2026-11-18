/**
 * 18 November: the Capabilities page shows what JAI has, from the backend's live inventory, and every page in the
 * navigation has its icon. The API client is replaced by a recorded response; the page and components are real.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockResponses: Record<string, unknown> = {};

jest.mock('@/lib/api', () => ({
  apiClient: {
    get: jest.fn(async (path: string) => (path in mockResponses
      ? { data: mockResponses[path], status: 200 } : { error: `no recorded response for ${path}`, status: 404 })),
    post: jest.fn(async () => ({ data: {}, status: 200 })),
  },
}));

jest.mock('next/navigation', () => ({ usePathname: () => '/dashboard/capabilities', useRouter: () => ({ push: jest.fn() }) }));

import CapabilitiesPage from '@/app/dashboard/capabilities/page';
import { ICONS, SECTIONS } from '@/components/ops/section-nav';

beforeEach(() => {
  mockResponses['/api/capabilities'] = {
    packs: [{ pack: 'trailofbits', title: 'Trail of Bits Skills', publisher: 'Trail of Bits', repo: 'trailofbits/skills',
              commit: '149d7b2', licence: 'CC-BY-SA-4.0', skills: ['differential-review'], blocked: [] }],
    departments: [{ role: 'security', title: 'Security Engineer', skills: ['differential-review', 'security-review'] },
                  { role: 'marketing', title: 'Marketing Lead', skills: ['copywriting'] }],
    skills_total: 150, skills_usable: 150,
    engine: { lead_model: 'claude-sonnet-5-5', worker_model: 'claude-haiku-5-5', workers_at_once: 20, video_skill: 'brag',
              creative_check_max_usd: 2 },
    registries: { tools: 312, agents: 31 },
    upgrades: [{ when: '2026-11-18T08:57', what: 'Four fixes: the sandbox reaps finished processes' }],
  };
});

describe('Capabilities', () => {
  it('shows the live inventory: packs, departments, the engine and the upgrades', async () => {
    render(<CapabilitiesPage />);
    expect(await screen.findByText('Trail of Bits Skills')).toBeInTheDocument();
    expect(screen.getByText('Security Engineer')).toBeInTheDocument();
    expect(screen.getByText('Four fixes: the sandbox reaps finished processes')).toBeInTheDocument();
    expect(screen.getByText('312')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Search skills'), { target: { value: 'differential' } });
    await waitFor(() => expect(screen.queryByText('Marketing Lead')).not.toBeInTheDocument());
  });

  it('gives every page in the navigation an icon', () => {
    for (const link of SECTIONS.flatMap((s) => s.links)) expect(ICONS[link.href]).toBeDefined();
    expect(SECTIONS.flatMap((s) => s.links).some((l) => l.href === '/dashboard/capabilities')).toBe(true);
  });
});
