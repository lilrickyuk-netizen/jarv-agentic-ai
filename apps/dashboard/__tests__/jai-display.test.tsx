/**
 * Wave 2a: what JAI puts on screen while talking. The voice's show_on_screen tool returns a card built from JAI's
 * own records; the dashboard shows it beside the intelligence field until Richard closes it.
 */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { JaiDisplay } from '@/components/jai-display';
import { showCard } from '@/lib/screen-signal';

describe('JaiDisplay', () => {
  afterEach(() => act(() => showCard(null)));

  it('shows nothing until JAI puts something on screen', () => {
    const { container } = render(<JaiDisplay />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a mission's requirements, files and failures, and closes", () => {
    render(<JaiDisplay />);
    act(() => showCard({ kind: 'mission', title: 'Verify that MYCO Phase 0 conforms',
      subtitle: 'running · independent check · check step 7 of 35',
      sections: [
        { heading: 'Requirements (1 of 2 done)', columns: ['', 'Status', 'Requirement'],
          rows: [['R1', 'done', 'Python pinned to 3.14.7'], ['R2', 'open', 'Licence inventory present']] },
        { heading: 'Files changed (1)', items: ['Taskfile.yml'] },
        { heading: 'Recent failures', columns: ['Tool', 'Target', 'Why'], rows: [['run_command', 'task format', 'exit=201']] },
      ] }));
    expect(screen.getByRole('region', { name: /JAI is showing: Verify that MYCO Phase 0/ })).toBeInTheDocument();
    expect(screen.getByText('check step 7 of 35', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('Licence inventory present')).toBeInTheDocument();
    expect(screen.getByText('done')).toHaveAttribute('data-status', 'done');
    expect(screen.getByText('Taskfile.yml')).toBeInTheDocument();
    expect(screen.getByText('exit=201')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
  });

  it('shows a file as text and links approvals to their page', () => {
    render(<JaiDisplay />);
    act(() => showCard({ kind: 'file', title: 'Taskfile.yml', sections: [{ code: 'version: "3"\ntasks:\n  sbom:' }] }));
    expect(screen.getByText(/tasks:/)).toBeInTheDocument();
    act(() => showCard({ kind: 'approvals', title: 'Waiting for your approval (1)', link: '/dashboard/approvals',
      sections: [{ items: ['git push origin main'] }] }));
    expect(screen.queryByText(/tasks:/)).not.toBeInTheDocument();  // the new card replaces the old
    expect(screen.getByRole('link', { name: 'Open ↗' })).toHaveAttribute('href', '/dashboard/approvals');
  });
});
