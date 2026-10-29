/**
 * Repair 14a: the business, revenue, analytics and permissions pages render backend data and call the backend.
 * The API client is replaced by a router of recorded backend mockResponses; the pages, hooks and components are real.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

const WS = '11111111-1111-1111-1111-111111111111';
const mockResponses: Record<string, unknown> = {};
const mockPosts: { path: string; body: unknown }[] = [];

jest.mock('@/lib/api', () => ({
  apiClient: {
    get: jest.fn(async (path: string) => {
      const key = Object.keys(mockResponses).find((k) => path === k || path.startsWith(`${k}?`));
      return key ? { data: mockResponses[key], status: 200 } : { error: `no recorded response for ${path}`, status: 404 };
    }),
    post: jest.fn(async (path: string, body?: unknown) => {
      mockPosts.push({ path, body });
      return { data: mockResponses[`POST ${path}`] ?? {}, status: 200 };
    }),
  },
}));

jest.mock('next/navigation', () => ({ usePathname: () => '/dashboard/sales', useRouter: () => ({ push: jest.fn(), replace: jest.fn() }) }));

beforeEach(() => {
  for (const key of Object.keys(mockResponses)) delete mockResponses[key];
  mockPosts.length = 0;
  window.localStorage.clear();
  mockResponses['/api/workspaces/mine'] = [{ id: WS, name: 'MYCO', slug: 'myco', type: 'project', is_active: true,
    company_mode: true, company_name: 'MYCO Ltd', has_folder: true }];
});

describe('Revenue Operations', () => {
  it('shows measured revenue and runs the revenue loop', async () => {
    mockResponses[`/api/revenue/${WS}/metrics`] = {
      revenue: { source: 'recorded', period_days: 30, gross: 148, refunds: 9, net: 139, payments: 2,
                 daily: { '2026-10-01': 49, '2026-10-02': 99 }, currency: 'USD', has_data: true },
      subscriptions: { source: 'recorded', active: 2, mrr: 40, new: 3, cancelled: 1, churn_rate: null, arpu: 20 },
      failed_payments: { source: 'recorded', count: 1, amount: 20,
                         items: [{ id: 'f1', customer: 'c4', amount: 20, date: '2026-10-02', reason: 'card_declined' }] },
      conversion: { stages: [{ stage: 'visitors', value: 2000, kpi: 'visitors' }, { stage: 'paying', value: 10, kpi: 'paying_customers' }],
                    conversion: [{ from: 'visitors', to: 'paying', rate: 0.005 }], missing: ['signups', 'activated'], overall: 0.005 },
    };
    mockResponses['/api/revenue/status'] = { stripe: 'disabled_no_key', webhook: 'disabled_no_secret', analytics: 'kpis', setup: ['Set STRIPE_SECRET_KEY'] };
    mockResponses[`POST /api/revenue/${WS}/loop?days=30`] = { summary: 'Revenue 30d net 139.00 USD', findings: ['1 unpaid failed payment(s) worth 20.00'],
      next_actions: ['Draft payment-recovery emails'], kpis_recorded: ['revenue_30d', 'mrr'] };
    const Page = (await import('@/app/dashboard/revenue-operations/page')).default;
    render(<Page />);
    expect(await screen.findByText('card_declined')).toBeInTheDocument();
    expect(screen.getByText('MRR')).toBeInTheDocument();
    expect(screen.getByText('Not measured: signups, activated')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Run revenue loop' }));
    expect(await screen.findByText('Revenue 30d net 139.00 USD')).toBeInTheDocument();
    expect(mockPosts[0].path).toBe(`/api/revenue/${WS}/loop?days=30`);
  });
});

describe('Sales', () => {
  it('lists deals and moves one through the pipeline', async () => {
    mockResponses[`/api/business/${WS}/pipeline`] = {
      deals_by_stage: { qualified: { count: 1, value: 4800 } }, open_pipeline_value: 4800, won_value: 0, win_rate: null,
      partners_by_status: {}, partners: [],
      deals: [{ id: 'd1', title: 'Acme annual plan', stage: 'qualified', value: 4800, notes: null, contact_id: null, expected_close_date: null }],
    };
    mockResponses['/api/business/kinds'] = [{ kind: 'create_prospect_brief', group: 'sales', label: 'Prospect brief', sections: ['Prospect'] }];
    mockResponses[`/api/business/${WS}/drafts`] = { drafts: [] };
    const Page = (await import('@/app/dashboard/sales/page')).default;
    render(<Page />);
    const select = await screen.findByLabelText('Move Acme annual plan');
    fireEvent.change(select, { target: { value: 'proposal' } });
    await waitFor(() => expect(mockPosts).toContainEqual({ path: `/api/business/${WS}/deals`, body: { deal_id: 'd1', stage: 'proposal' } }));
    expect(await screen.findByRole('option', { name: 'Prospect brief' })).toBeInTheDocument();
  });

  it('writes a grounded draft for the chosen kind', async () => {
    mockResponses[`/api/business/${WS}/pipeline`] = { deals_by_stage: {}, open_pipeline_value: 0, won_value: 0, win_rate: null,
      partners_by_status: {}, partners: [], deals: [] };
    mockResponses['/api/business/kinds'] = [{ kind: 'create_sales_script', group: 'sales', label: 'Sales script', sections: ['Opening'] },
      { kind: 'create_post', group: 'marketing', label: 'Post', sections: [] }];
    mockResponses[`/api/business/${WS}/drafts`] = { drafts: [] };
    const Page = (await import('@/app/dashboard/sales/page')).default;
    render(<Page />);
    fireEvent.change(await screen.findByPlaceholderText('e.g. Dark mode is live'), { target: { value: 'Annual plan launch' } });
    fireEvent.click(screen.getByRole('button', { name: 'Write draft' }));
    await waitFor(() => expect(mockPosts.map((p) => p.path)).toContain(`/api/business/${WS}/drafts/create_sales_script`));
    expect(screen.queryByRole('option', { name: 'Post' })).not.toBeInTheDocument();
  });
});

describe('Permissions', () => {
  it('renders the live authority model', async () => {
    mockResponses['/api/permissions/overview'] = {
      levels: [{ level: 7, name: 'LEVEL_7_DEPLOYMENT', meaning: 'Deployment: staging deploys', agents: 2, tools: 9 }],
      agents: [{ name: 'devops', category: 'engineering', authority: 7, tools: 30, implemented: true }],
      tools: { total: 300, always_approval: ['deploy_production_with_boundary'], conditional_approval: ['scale_service_with_budget_boundary'] },
      hard_boundaries: [{ key: 'bank_details', title: 'Entering bank details' }],
      command_gates: ['deploys'], sub_agent_rule: 'A sub-agent never exceeds its lead.', voice_rule: 'Approvals are never taken by voice.',
    };
    const Page = (await import('@/app/dashboard/permissions/page')).default;
    render(<Page />);
    expect(await screen.findByText('• Entering bank details')).toBeInTheDocument();
    expect(screen.getByText('deploy_production_with_boundary')).toBeInTheDocument();
    expect(screen.getByText('Deployment: staging deploys')).toBeInTheDocument();
  });
});

describe('Workspace picker', () => {
  it('explains what to do when the operator has no workspace', async () => {
    mockResponses['/api/workspaces/mine'] = [];
    const Page = (await import('@/app/dashboard/marketing/page')).default;
    render(<Page />);
    expect(await screen.findByText('No workspace yet')).toBeInTheDocument();
  });
});
