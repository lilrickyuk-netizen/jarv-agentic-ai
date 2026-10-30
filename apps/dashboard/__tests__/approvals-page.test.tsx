/**
 * Approvals page: every decision JARV is waiting on is shown here, including actions paused by the Richard
 * Boundary chain (which used to appear only on the Richard Boundary page), and approving one records the
 * decision against its boundary report. The API client is replaced by recorded responses; the page is real.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import ApprovalsPage from '@/app/dashboard/approvals/page';

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
      return { data: { status: 'approved' }, status: 200 };
    }),
  },
}));

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));

beforeEach(() => {
  for (const key of Object.keys(mockResponses)) delete mockResponses[key];
  mockPosts.length = 0;
  mockResponses['/api/approvals/command-blocks'] = [];
  mockResponses['/api/approvals/list'] = [];
  mockResponses['/api/approvals/stats'] = { total_approvals: 0, pending_approvals: 0, approved_approvals: 0,
    rejected_approvals: 0, executed_approvals: 0, expired_approvals: 0, by_type: {}, average_response_time_minutes: 0 };
});

describe('ApprovalsPage', () => {
  it('shows a paused boundary action and records the decision on its report', async () => {
    mockResponses['/api/richard/pending'] = [{
      approval_id: 'appr-1', action_description: 'git -c core.filemode=false init -b main',
      boundary_type: 'approval_required_command', boundary_report_id: 'report-1', task_id: 'task-1',
      expires_at: '2026-11-02T23:24:13Z', created_at: '2026-10-30T23:23:56Z',
    }];
    render(<ApprovalsPage />);
    expect(await screen.findByText('git -c core.filemode=false init -b main')).toBeInTheDocument();
    expect(screen.queryByText(/No actions are currently blocked/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(mockPosts).toContainEqual({ path: '/api/richard/reports/report-1/decision',
      body: { approve: true, reason: 'Approved from the approvals page' } }));
  });

  it('says nothing is waiting only when there is nothing to decide', async () => {
    mockResponses['/api/richard/pending'] = [];
    render(<ApprovalsPage />);
    expect(await screen.findByText(/No actions are currently blocked/)).toBeInTheDocument();
  });
});
