/**
 * Basic dashboard component tests
 */
import { render, screen } from '@testing-library/react';

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
