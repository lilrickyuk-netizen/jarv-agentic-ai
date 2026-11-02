/**
 * Command Center: missions run in JARV's worker, not in the page. Leaving the page (for example to approve
 * something) and coming back used to show nothing, so a mission still running looked stopped. The page now
 * picks up the mission that is still running and follows it again. The API client is replaced; the page is real.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import CommandPage from '@/app/dashboard/command/page';

const gets: string[] = [];
const posts: string[] = [];
let polls = 0;

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));

jest.mock('@/lib/api', () => ({
  apiClient: {
    get: jest.fn(async (path: string) => {
      gets.push(path);
      if (path.startsWith('/api/command/history')) {
        return { status: 200, data: [
          { task_id: 'task-7', command: 'Resume the mission', status: 'partial', response_text: null,
            selected_agents: [], created_at: '2026-10-31T02:22:32Z', completed_at: null, error: null, folder: null },
          { task_id: 'task-9', command: 'Continue MYCO Phase 0', status: 'running', response_text: null,
            selected_agents: ['orchestrator'], created_at: '2026-10-31T02:18:03Z', completed_at: null, error: null,
            folder: 'C:\\Users\\lilri\\Projects\\MYCO' },
          { task_id: 'task-8', command: 'Older mission', status: 'completed', response_text: 'Done.',
            selected_agents: [], created_at: '2026-10-31T01:00:00Z', completed_at: '2026-10-31T01:10:00Z', error: null },
        ] };
      }
      if (path === '/api/command/info') return { status: 200, data: { provider: 'openai', model: 'gpt-6-luna' } };
      if (path === '/api/command/tasks/task-7') {
        return { status: 200, data: {
          task_id: 'task-7', command: 'Resume the mission', status: 'partial', requires_approval: false,
          response_text: 'Cannot see the workspace.', plan_steps: [], selected_agents: [], provider: 'openai',
          model: 'gpt-6-luna', execution_time: 4, tokens_used: 10, finished: true, folder: null, archived: false,
          resumable: true } };
      }
      if (path === '/api/command/tasks/task-9') {
        polls += 1;
        const finished = polls > 1;
        return { status: 200, data: {
          task_id: 'task-9', command: 'Continue MYCO Phase 0', status: finished ? 'completed' : 'running',
          requires_approval: false, response_text: finished ? 'Phase 0 exit gate passed.' : '', plan_steps: [],
          selected_agents: ['orchestrator'], provider: 'openai', model: 'gpt-6-luna', execution_time: 300,
          tokens_used: 1000, finished, folder: 'C:\\Users\\lilri\\Projects\\MYCO', archived: false,
          resumable: false } };
      }
      return { status: 404, error: `no ${path}` };
    }),
    post: jest.fn(async (path: string) => {
      posts.push(path);
      return { status: 200, data: {
        task_id: 'task-7', command: 'Resume the mission', status: path.endsWith('/archive') ? 'cancelled' : 'cancelled',
        requires_approval: false, response_text: '', plan_steps: [], selected_agents: [], provider: null, model: null,
        execution_time: 0, tokens_used: 0, finished: true, folder: null, archived: path.endsWith('/archive'),
        resumable: false } };
    }),
  },
}));

beforeEach(() => {
  gets.length = 0;
  posts.length = 0;
  polls = 0;
});

describe('CommandPage', () => {
  it('follows the mission that is still running when the page opens', async () => {
    render(<CommandPage />);
    await waitFor(() => expect(gets).toContain('/api/command/tasks/task-9'));
    expect(gets).not.toContain('/api/command/tasks/task-8');
    expect(await screen.findByText('RUNNING')).toBeInTheDocument();
    expect(await screen.findByText('COMPLETED', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByTestId('mission-identity')).toHaveTextContent('Mission task-9 · C:\\Users\\lilri\\Projects\\MYCO');
  });

  it('opens any mission from the list, shows which it is, and closes and archives it', async () => {
    render(<CommandPage />);
    fireEvent.click(await screen.findByText('Resume the mission'));
    expect(await screen.findByText('Cannot see the workspace.')).toBeInTheDocument();
    expect(screen.getByTestId('mission-identity')).toHaveTextContent('Mission task-7 · no folder');
    fireEvent.click(screen.getByRole('button', { name: 'Close mission' }));
    await waitFor(() => expect(posts).toContain('/api/command/tasks/task-7/cancel'));
    fireEvent.click(await screen.findByRole('button', { name: 'Archive' }));
    await waitFor(() => expect(posts).toContain('/api/command/tasks/task-7/archive'));
    expect(await screen.findByRole('button', { name: 'Unarchive' })).toBeInTheDocument();
  });
});
