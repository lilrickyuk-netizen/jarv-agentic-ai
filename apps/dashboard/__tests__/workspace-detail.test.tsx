/**
 * Workspace page: opening a workspace from the list shows its details and folder, saves a new folder when the
 * workspace was moved, archives it and restores it. The API client is replaced; the page is real.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import WorkspaceDetailPage from '@/app/dashboard/workspaces/[id]/page';

const WS = '11111111-2222-3333-4444-555555555555';
const calls: { method: string; path: string; body?: unknown }[] = [];
let current: Record<string, unknown>;

jest.mock('next/navigation', () => ({
  useParams: () => ({ id: '11111111-2222-3333-4444-555555555555' }),
  useRouter: () => ({ push: jest.fn() }),
}));

jest.mock('@/lib/api', () => ({
  apiClient: {
    get: jest.fn(async (path: string) => { calls.push({ method: 'GET', path }); return { status: 200, data: { ...current } }; }),
    patch: jest.fn(async (path: string, body: Record<string, unknown>) => {
      calls.push({ method: 'PATCH', path, body });
      if (body.folder === 'C:\\Users\\lilri\\Elsewhere') return { status: 400, error: "'C:\\Users\\lilri\\Elsewhere' is not an existing folder that JARV can see" };
      if (body.folder) current = { ...current, folder: body.folder };
      if (body.is_archived === false) current = { ...current, is_archived: false, is_active: true };
      return { status: 200, data: { ...current } };
    }),
    delete: jest.fn(async (path: string) => {
      calls.push({ method: 'DELETE', path });
      current = { ...current, is_archived: true, is_active: false };
      return { status: 200, data: { archived: true } };
    }),
  },
}));

beforeEach(() => {
  calls.length = 0;
  current = {
    id: WS, name: 'MYCO', description: 'Registered workspace', slug: 'myco', is_active: true, is_archived: false,
    workspace_type: 'project', authority_level: 2, max_subagents: 10, active_subagent_count: 0, swarm_enabled: true,
    company_mode_enabled: false, company_name: null, total_tasks: 4, completed_tasks: 3, total_tokens_used: 12000,
    created_at: '2026-10-29T10:00:00Z', updated_at: '2026-10-30T10:00:00Z',
    folder: 'C:\\Users\\lilri\\OneDrive\\Desktop\\MYCO',
  };
});

describe('WorkspaceDetailPage', () => {
  it('shows the workspace and moves it to a new folder', async () => {
    render(<WorkspaceDetailPage />);
    expect(await screen.findByRole('heading', { name: 'MYCO' })).toBeInTheDocument();
    expect(calls[0]).toEqual({ method: 'GET', path: `/api/workspaces/${WS}` });
    const input = screen.getByLabelText('Folder on your computer');
    expect(input).toHaveValue('C:\\Users\\lilri\\OneDrive\\Desktop\\MYCO');

    fireEvent.change(input, { target: { value: 'C:\\Users\\lilri\\Elsewhere' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save folder' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('is not an existing folder');

    fireEvent.change(input, { target: { value: 'C:\\Users\\lilri\\Projects\\MYCO' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save folder' }));
    expect(await screen.findByText('JARV now works in C:\\Users\\lilri\\Projects\\MYCO.')).toBeInTheDocument();
    expect(calls).toContainEqual({ method: 'PATCH', path: `/api/workspaces/${WS}`, body: { folder: 'C:\\Users\\lilri\\Projects\\MYCO' } });
  });

  it('archives the workspace and restores it', async () => {
    render(<WorkspaceDetailPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Archive workspace' }));
    await waitFor(() => expect(calls).toContainEqual({ method: 'DELETE', path: `/api/workspaces/${WS}` }));
    fireEvent.click(await screen.findByRole('button', { name: 'Restore workspace' }));
    await waitFor(() => expect(calls).toContainEqual({ method: 'PATCH', path: `/api/workspaces/${WS}`,
      body: { is_archived: false, is_active: true } }));
    expect(await screen.findByRole('button', { name: 'Archive workspace' })).toBeInTheDocument();
  });
});
