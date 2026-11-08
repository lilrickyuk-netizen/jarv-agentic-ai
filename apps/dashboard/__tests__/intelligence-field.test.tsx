import { fireEvent, render, screen } from '@testing-library/react';

// three.js ships as an ES module Jest does not load; the field only needs to find that WebGL is missing here
// (jsdom has none), which is what this stand-in's renderer reports. The network itself is built for real below.
jest.mock('three', () => ({
  WebGLRenderer: function WebGLRenderer() { throw new Error('WebGL is not available'); },
}));
import { CoreField } from '@/components/core-field';
import { FIELD_LOOKS, FIELD_STATES, IntelligenceField, buildNetwork, nodeCount } from '@/components/intelligence-field';

describe('Upgrade 8: the intelligence field', () => {
  it('has its own look for each of JAI\'s ten states, with amber for approval and red for failure', () => {
    expect(FIELD_STATES).toHaveLength(10);
    const looks = FIELD_STATES.map((state) => JSON.stringify(FIELD_LOOKS[state]));
    expect(new Set(looks).size).toBe(10);
    expect(FIELD_LOOKS.approval.color).toBe(0xfbbf24);
    expect(FIELD_LOOKS.failed.color).toBe(0xfb7185);
    expect(FIELD_LOOKS.executing.signals).toBeGreaterThan(FIELD_LOOKS.idle.signals);
    expect(FIELD_LOOKS.planning.order).toBe(1);
    expect(FIELD_LOOKS.approval.inward).toBe(1);
  });

  it('is about 2,000 nodes on a desktop panel and fewer on a phone', () => {
    expect(nodeCount(900, 700)).toBe(2000);
    const phone = nodeCount(360, 300);
    expect(phone).toBeLessThan(2000);
    expect(phone).toBeGreaterThanOrEqual(700);
  });

  it('links each node only to near neighbours, the same shape every time', () => {
    const network = buildNetwork(2000);
    const edges = network.edges.length / 2;
    expect(edges).toBeGreaterThan(2000);
    expect(edges).toBeLessThanOrEqual(2000 * 3);
    const reach = 2.4 / Math.sqrt(2000) + 0.06;
    for (let e = 0; e < edges; e += 97) {
      const a = network.edges[e * 2] * 3;
      const b = network.edges[e * 2 + 1] * 3;
      const d = Math.hypot(network.homes[a] - network.homes[b], network.homes[a + 1] - network.homes[b + 1],
        network.homes[a + 2] - network.homes[b + 2]);
      expect(d).toBeLessThan(reach * 2);
    }
    const linked = network.neighbours.filter((n) => n.length > 0).length;
    expect(linked).toBe(2000); // every node is connected
    expect(Array.from(buildNetwork(2000).edges.slice(0, 50))).toEqual(Array.from(network.edges.slice(0, 50)));
  });

  it('says it cannot draw instead of failing where WebGL is unavailable', () => {
    render(<IntelligenceField state="approval" />);
    const field = screen.getByRole('img', { name: /network of linked nodes.*approval/i });
    expect(field).toHaveAttribute('data-render-state', 'unavailable');
    expect(field).toHaveAttribute('data-state', 'approval');
  });

  it('switches between the network and the earlier swarm and remembers the choice', () => {
    window.localStorage.clear();
    const { unmount } = render(<CoreField state="executing" />);
    expect(screen.getByRole('img', { name: /network of linked nodes/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Swarm' }));
    expect(screen.getByRole('button', { name: 'Swarm' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('img', { name: /swarm of 90,000 lights/i })).toBeInTheDocument();
    expect(window.localStorage.getItem('jai.field-style')).toBe('swarm');
    unmount();
    render(<CoreField state="executing" />);
    expect(screen.getByRole('img', { name: /swarm of 90,000 lights/i })).toBeInTheDocument();
  });
});
