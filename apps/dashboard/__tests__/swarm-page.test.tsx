/**
 * The Swarm page with a real mission team as the backend sends it (costs as decimal strings, tokens by model): it
 * renders without crashing and shows the run, its lead and each specialist with its package, paths and report.
 * The API client is replaced by recorded backend answers; the page is real.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import SwarmPage from '@/app/dashboard/swarm/page';

const mockRun = {
  id: '11111111-2222-3333-4444-555555555555', workspace_id: 'w', lead_agent_id: 'l', lead_agent_name: 'orchestrator',
  parent_task_id: null, swarm_purpose: 'Mission team: Carry on building MYCO from Phase 0', status: 'running',
  max_sub_agents: 2, active_sub_agents: 1, completed_sub_agents: 1, failed_sub_agents: 0, total_tasks_completed: 1,
  total_tokens_used: { 'gpt-6-luna': 1200, other: 300 }, total_cost: '0.0123', timeout_seconds: 14400,
  started_at: '2026-11-04T16:20:00Z', completed_at: null,
  metadata: { approach: 'Backend and docs in parallel.', task_id: 't' },
};
const mockTeam = [
  { id: 'a', swarm_run_id: mockRun.id, agent_template: 'documentation', task_description: '', status: 'working',
    authority_level: 4, allowed_tools: [], assigned_tasks: [], completed_tasks: 0, failed_tasks: 0,
    tokens_used: { 'gpt-6-luna': 300 }, cost_estimate: '0', output: null, timeout_seconds: 14400,
    spawned_at: '2026-11-04T16:20:01Z', dissolved_at: null, metadata: { package: 'P2', owns: ['docs/'] } },
  { id: 'b', swarm_run_id: mockRun.id, agent_template: 'coding_agent', task_description: '', status: 'dissolved',
    authority_level: 4, allowed_tools: [], assigned_tasks: [], completed_tasks: 1, failed_tasks: 0,
    tokens_used: { 'gpt-6-luna': 900 }, cost_estimate: 0.0101,
    output: { success: true, summary: 'Workspace skeleton in apps/api.', steps: 12, tool_calls: 14 },
    timeout_seconds: 14400, spawned_at: '2026-11-04T16:20:01Z', dissolved_at: '2026-11-04T16:30:00Z',
    metadata: { package: 'P1', owns: ['apps/api/'] } },
];

jest.mock('@/lib/api', () => ({
  apiClient: {
    get: jest.fn(async (path: string) => ({
      status: 200, data: path.startsWith('/api/swarm/sub-agents') ? mockTeam : [mockRun],
    })),
  },
}));

it('shows a running mission team and each specialist without crashing on real data', async () => {
  render(<SwarmPage />);
  expect(await screen.findByText('Mission team: Carry on building MYCO from Phase 0')).toBeInTheDocument();
  expect(screen.getByText('Lead: orchestrator · Backend and docs in parallel.')).toBeInTheDocument();
  expect(screen.getAllByText('$0.0123').length).toBeGreaterThan(0);
  expect(screen.getAllByText('1,500').length).toBeGreaterThan(0);
  const members = await screen.findAllByTestId('sub-agent');
  expect(members).toHaveLength(2);
  expect(members[0]).toHaveTextContent('P1 · coding agent');
  expect(members[0]).toHaveTextContent('finished');
  expect(members[0]).toHaveTextContent('Owns: apps/api/');
  expect(members[0]).toHaveTextContent('12 steps · 14 tool calls');
  expect(members[0]).toHaveTextContent('Workspace skeleton in apps/api.');
  expect(members[1]).toHaveTextContent('P2 · documentation');
  fireEvent.click(screen.getByRole('button', { expanded: true }));
  await waitFor(() => expect(screen.queryAllByTestId('sub-agent')).toHaveLength(0));
});
