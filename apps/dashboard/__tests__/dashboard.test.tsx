/**
 * Basic dashboard component tests
 */
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { extractWakeCommand } from '@/components/voice-operator';

// Mock dashboard page
const MockDashboard = () => {
  return (
    <div>
      <h1>Dashboard</h1>
      <p>Welcome to JARV Dashboard</p>
    </div>
  );
};

describe('Dashboard', () => {
  it('renders dashboard heading', () => {
    render(<MockDashboard />);
    const heading = screen.getByRole('heading', { name: /dashboard/i });
    expect(heading).toBeInTheDocument();
  });

  it('renders welcome message', () => {
    render(<MockDashboard />);
    const message = screen.getByText(/welcome to jarv dashboard/i);
    expect(message).toBeInTheDocument();
  });
});

describe('extractWakeCommand', () => {
  it.each([
    ['JARV, talk to me, check the weather', 'check the weather'],
    ['J-R-V, talk to me, check the weather', 'check the weather'],
    ['Jarve talk to me turn on the lights', 'turn on the lights'],
    ['I think JARV, talk to me, check status', 'check status'],
    ['JARV talk to me.', ''],
  ])('recognizes %s', (transcript, expected) => {
    expect(extractWakeCommand(transcript)).toBe(expected);
  });

  it.each(['Talk to me, check the weather', 'Jarvis, talk to me.', 'Check the weather'])('does not match %s', (transcript) => {
    expect(extractWakeCommand(transcript)).toBeNull();
  });
});
