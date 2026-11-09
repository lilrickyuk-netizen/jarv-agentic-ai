/**
 * Command Center, 9 November: the agents working now are small markers around the JARVIS orb (their role and what
 * each is doing), not a block, and there is nothing but the orb when no mission is running. The side menu has the
 * services as plain switches.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { WorkingAgents } from '@/components/working-agents';
import { ServiceSwitches } from '@/components/service-switches';

let mockOn = true;
jest.mock('@/lib/api', () => ({
  apiClient: {
    get: jest.fn(async () => ({
      status: 200,
      data: { available: true, memory_available_gb: 5.5, memory_total_gb: 11.5,
        switches: [{ service: 'comfyui', label: 'Image generator', about: 'FLUX', installed: true, on: mockOn, status: 'x' }] },
    })),
    post: jest.fn(async (_path: string, body?: unknown) => {
      mockOn = (body as { on: boolean }).on;
      return { status: 200, data: { on: mockOn } };
    }),
  },
}));

it('shows each working agent with what it is doing, and nothing when no mission runs', () => {
  const { rerender, container } = render(<WorkingAgents missions={[{ task_id: 't', title: 'Investor deck', status: 'running',
    agents: [{ id: 'B1', role: 'Lead Builder', status: 'working', doing: 'writing slides/market.md' },
      { id: 'VER', role: 'Independent Verifier', status: 'planned', doing: null }] }]} />);
  expect(screen.getByText('Lead Builder')).toBeInTheDocument();
  expect(screen.getByText('writing slides/market.md')).toBeInTheDocument();
  expect(screen.getByText('waiting its turn').closest('li')).toHaveClass('is-waiting');
  rerender(<WorkingAgents missions={[]} />);
  expect(container).toBeEmptyDOMElement();
});

it('lists the services in the side menu as switches that work', async () => {
  render(<ServiceSwitches compact />);
  expect(await screen.findByText('5.5 / 11.5 GB')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('switch', { name: 'Image generator on' }));
  await waitFor(() => expect(screen.getByRole('switch', { name: 'Image generator off' })).toBeInTheDocument());
});

it('clearing the chat also clears what was said in the conversation', () => {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { clearVoiceLines, setVoiceClear } = jest.requireActual('@/lib/voice-signal');
  const cleared = jest.fn();
  setVoiceClear(cleared);
  clearVoiceLines();
  expect(cleared).toHaveBeenCalledTimes(1);
  setVoiceClear(null);
  clearVoiceLines();
  expect(cleared).toHaveBeenCalledTimes(1);
});
