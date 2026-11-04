/**
 * The Command Center's switches for JAI's heavy services: they show what is on, and a click asks the backend to
 * start or stop that one service. The API client is replaced by recorded backend answers; the component is real.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { ServiceSwitches } from '@/components/service-switches';

const mockPosts: { path: string; body: unknown }[] = [];
let mockOn = false;

jest.mock('@/lib/api', () => ({
  apiClient: {
    get: jest.fn(async () => ({
      status: 200,
      data: {
        available: true, memory_available_gb: 5.1, memory_total_gb: 10.4,
        switches: [
          { service: 'comfyui', label: 'Image generator', about: 'FLUX.1-schnell on the GPU', installed: true, on: mockOn, status: 'x' },
          { service: 'docling', label: 'Document reader', about: 'Docling', installed: false, on: false, status: 'not installed' },
        ],
      },
    })),
    post: jest.fn(async (path: string, body?: unknown) => {
      mockPosts.push({ path, body });
      mockOn = (body as { on: boolean }).on;
      return { status: 200, data: { on: mockOn } };
    }),
  },
}));

beforeEach(() => {
  mockPosts.length = 0;
  mockOn = false;
});

it('switches the image generator on with one click and shows the memory free', async () => {
  render(<ServiceSwitches />);
  const toggle = await screen.findByRole('switch', { name: 'Image generator off' });
  expect(screen.getByText('5.1 GB free of 10.4 GB')).toBeInTheDocument();
  fireEvent.click(toggle);
  await waitFor(() => expect(screen.getByRole('switch', { name: 'Image generator on' })).toBeInTheDocument());
  expect(mockPosts).toEqual([{ path: '/api/operations/switches/comfyui', body: { on: true } }]);
  expect(screen.getByRole('switch', { name: 'Document reader off' })).toBeDisabled();
  expect(screen.getByText('Not installed on this computer')).toBeInTheDocument();
});
