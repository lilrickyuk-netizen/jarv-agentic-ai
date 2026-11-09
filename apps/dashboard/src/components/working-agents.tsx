'use client';

/**
 * The agents working right now, shown as small markers around the JARVIS orb (Command Center, 9 November: "I want
 * to be able to see the agents working, it doesn't need to be a big ugly block"). Each marker is a dot and a tag
 * with the agent's role and what it is doing now, from GET /api/command/working; a working agent pulses, one that
 * is waiting is dimmed, and when nothing is running there is nothing but the orb.
 */
export interface WorkingAgent {
  id: string;
  role: string;
  status: string;
  doing?: string | null;
}

export interface WorkingMission {
  task_id: string;
  title: string;
  status: string;
  agents: WorkingAgent[];
}

// Where the markers sit around the orb: left and right alternately, top to bottom (up to six).
const SPOTS = [
  { side: 'left', top: 16 }, { side: 'right', top: 24 }, { side: 'left', top: 70 },
  { side: 'right', top: 62 }, { side: 'left', top: 43 }, { side: 'right', top: 84 },
] as const;

export function WorkingAgents({ missions }: { missions: WorkingMission[] }) {
  const agents = missions.flatMap((mission) => mission.agents.map((agent) => ({ ...agent, mission: mission.title })))
    .slice(0, SPOTS.length);
  if (!agents.length) return null;
  return (
    <ul className="ov-agents" aria-label="Agents working now">
      {agents.map((agent, index) => {
        const spot = SPOTS[index];
        const working = agent.status === 'working';
        return (
          <li key={`${agent.mission}-${agent.id}`} className={`ov-agent is-${spot.side}${working ? '' : ' is-waiting'}`}
            style={{ top: `${spot.top}%` }} title={agent.mission}>
            <span className="ov-agent-dot" aria-hidden="true" />
            <span className="ov-agent-tag">
              <b>{agent.role}</b>
              <span>{agent.doing || (working ? 'working' : 'waiting its turn')}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export default WorkingAgents;
