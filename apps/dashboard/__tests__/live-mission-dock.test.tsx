/**
 * Always-on mission status and conversation. Leaving the dashboard page reloaded the whole site (plain links), which
 * ended Talk with JARV and left the mission panel blank, so Richard could not tell what the mission was doing. The
 * dock lives in the dashboard frame: it shows the mission being worked on (status, when JARV was last heard from,
 * what it did last) on every page, keeps the conversation mounted, and links inside the dashboard no longer reload.
 * The API client and Next's router are replaced; the components are real.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import DashboardLayout from '@/app/dashboard/layout';
import { ago, LiveMissionDock } from '@/components/live-mission-dock';

const mockPush = jest.fn();
const mockNow = Date.now();

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: mockPush }), usePathname: () => '/dashboard/approvals' }));
jest.mock('@/lib/auth', () => ({ isAuthenticated: () => true }));

jest.mock('@/lib/api', () => ({
  apiClient: {
    get: jest.fn(async (path: string) => {
      if (path.startsWith('/api/command/history')) {
        return { status: 200, data: [
          { task_id: 'old-mission-1', command: 'Old Phase 0', status: 'cancelled', created_at: '2026-10-30T19:31:00Z' },
          { task_id: '8ca4f55a-a222', command: 'Start mission: finish the MYCO Phase 0 correction.', status: 'running',
            created_at: '2026-11-02T18:08:43Z', folder: 'C:\\Users\\lilri\\Projects\\MYCO' },
        ] };
      }
      if (path === '/api/command/tasks/8ca4f55a-a222') {
        return { status: 200, data: {
          task_id: '8ca4f55a-a222', command: 'Start mission: finish the MYCO Phase 0 correction.', status: 'running',
          requires_approval: false, response_text: 'Paused: the AI provider stopped answering (old note).',
          plan_steps: [], selected_agents: [], provider: 'openai', model: 'gpt-6-luna', execution_time: 0, tokens_used: 0,
          finished: false, folder: 'C:\\Users\\lilri\\Projects\\MYCO', heartbeat_at: new Date(mockNow - 3000).toISOString(),
          events: [
            { at: '2026-11-02T18:58:57Z', title: 'Tool: write_file', message: 'wrote 150 bytes (created)', severity: 'info' },
            { at: '2026-11-02T18:59:25Z', title: 'Tool: run_command', message: 'exit=0, 55 bytes stdout', severity: 'info' },
          ] } };
      }
      if (path === '/api/voice/providers') return { status: 200, data: { live: { ready: true } } };
      return { status: 404, error: `no ${path}` };
    }),
    post: jest.fn(async () => ({ status: 200, data: {} })),
  },
}));

describe('LiveMissionDock', () => {
  it('shows the mission being worked on, not the latest or an old note, with what it did last', async () => {
    render(<LiveMissionDock />);
    expect(await screen.findByText('MISSION IN PROGRESS')).toBeInTheDocument();
    expect(screen.getByTestId('dock-status')).toHaveTextContent('RUNNING');
    expect(screen.getByTestId('dock-identity')).toHaveTextContent('Mission 8ca4f55a · C:\\Users\\lilri\\Projects\\MYCO');
    expect(screen.getByTestId('dock-heartbeat').textContent).toMatch(/^\d+s ago$/);
    expect(screen.getByTestId('dock-latest')).toHaveTextContent('Tool: run_command: exit=0, 55 bytes stdout');
    // A running mission's old pause note is not shown as if it were current.
    expect(screen.queryByText(/old note/)).not.toBeInTheDocument();
  });

  it('keeps Talk with JARV mounted when the panel is hidden', async () => {
    render(<LiveMissionDock />);
    const voice = screen.getByTestId('dock-voice');
    expect(voice).not.toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Talk with JARV' }));
    expect(voice).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Hide conversation' }));
    expect(voice).not.toBeVisible();
    expect(voice).toBeInTheDocument();
  });

  it('says how long ago JARV was last heard from', () => {
    expect(ago(new Date(mockNow - 12000).toISOString(), mockNow)).toBe('12s ago');
    expect(ago(new Date(mockNow - 240000).toISOString(), mockNow)).toBe('4 min ago');
    expect(ago(null, mockNow)).toBe('not yet');
  });
});

describe('DashboardLayout', () => {
  it('changes page without reloading and shows the dock on every page', async () => {
    mockPush.mockClear();
    render(<DashboardLayout><a href="/dashboard/approvals">Approvals page</a><a href="#elsewhere">Elsewhere</a></DashboardLayout>);
    await waitFor(() => expect(screen.getByTestId('live-mission-dock')).toBeInTheDocument());
    const inside = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
    screen.getByText('Approvals page').dispatchEvent(inside);
    expect(inside.defaultPrevented).toBe(true);
    expect(mockPush).toHaveBeenCalledWith('/dashboard/approvals');
    const outside = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
    screen.getByText('Elsewhere').dispatchEvent(outside);
    expect(mockPush).toHaveBeenCalledTimes(1);
  });
});
