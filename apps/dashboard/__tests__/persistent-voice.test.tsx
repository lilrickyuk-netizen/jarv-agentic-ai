/**
 * Moving between dashboard pages reloaded the whole site (plain links), which ended Talk with JAI. Links inside the
 * dashboard now change page without reloading, and the conversation is mounted once in the dashboard frame: it is
 * shown in the Command Center's own slot and kept, unseen, on other pages, without restarting. Nothing is added to
 * any page. Next's router and the voice panel are replaced; the frame and PersistentVoice are real.
 */
import { act, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import DashboardLayout from '@/app/dashboard/layout';
import { PersistentVoice, VOICE_SLOT_ID } from '@/components/persistent-voice';

const mockPush = jest.fn();
let mockMounts = 0;

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: mockPush }), usePathname: () => '/dashboard' }));
jest.mock('@/lib/auth', () => ({ isAuthenticated: () => true }));
jest.mock('@/lib/missions', () => ({ followMission: jest.fn() }));
jest.mock('@/components/voice-operator', () => {
  const React = jest.requireActual('react');
  return {
    VoiceOperator: () => {
      React.useEffect(() => { mockMounts += 1; }, []);
      return React.createElement('button', { type: 'button' }, 'Talk with JAI');
    },
  };
});

function Page({ withSlot }: { withSlot: boolean }) {
  return withSlot ? <section data-testid="command-center"><div id={VOICE_SLOT_ID} /></section> : <section>Approvals</section>;
}

beforeEach(() => {
  mockMounts = 0;
  mockPush.mockClear();
});

describe('PersistentVoice', () => {
  it('shows Talk with JAI in the Command Center slot and keeps it connected on other pages', async () => {
    const { rerender } = render(<><Page withSlot /><PersistentVoice /></>);
    await waitFor(() => expect(screen.getByTestId('command-center')).toContainElement(screen.getByRole('button', { name: 'Talk with JAI' })));

    rerender(<><Page withSlot={false} /><PersistentVoice /></>);
    await waitFor(() => expect(screen.getByTestId('voice-parking')).toContainElement(
      screen.getByRole('button', { name: 'Talk with JAI', hidden: true })));
    expect(screen.queryByRole('button', { name: 'Talk with JAI' })).not.toBeInTheDocument();  // nothing new on screen

    rerender(<><Page withSlot /><PersistentVoice /></>);
    await waitFor(() => expect(screen.getByTestId('command-center')).toContainElement(screen.getByRole('button', { name: 'Talk with JAI' })));
    expect(mockMounts).toBe(1);  // moved, never restarted: the conversation does not drop
  });
});

describe('DashboardLayout', () => {
  it('changes page without reloading', async () => {
    render(<DashboardLayout><a href="/dashboard/approvals">Approvals page</a><a href="#elsewhere">Elsewhere</a></DashboardLayout>);
    await waitFor(() => expect(screen.getByText('Approvals page')).toBeInTheDocument());
    const inside = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
    act(() => { screen.getByText('Approvals page').dispatchEvent(inside); });
    expect(inside.defaultPrevented).toBe(true);
    expect(mockPush).toHaveBeenCalledWith('/dashboard/approvals');
    const outside = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 });
    act(() => { screen.getByText('Elsewhere').dispatchEvent(outside); });
    expect(mockPush).toHaveBeenCalledTimes(1);
  });
});
