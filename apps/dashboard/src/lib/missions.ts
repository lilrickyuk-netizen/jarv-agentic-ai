import { apiClient } from '@/lib/api';

export interface MissionEvent {
  at: string;
  title: string;
  message: string;
  severity: string;
}

export interface MissionResult {
  task_id: string;
  command: string;
  status: string;
  requires_approval: boolean;
  response_text: string;
  plan_steps: string[];
  selected_agents: string[];
  provider: string | null;
  model: string | null;
  /** The model each role ran on, when the roles differ (as the engines reported them). */
  models_by_role?: Record<string, string>;
  execution_time: number;
  tokens_used: number;
  approval_reason?: string | null;
  error?: string | null;
  finished: boolean;
  dispatch_mode?: string | null;
  attempts?: number;
  heartbeat_at?: string | null;
  events?: MissionEvent[];
  folder?: string | null;
  archived?: boolean;
  resumable?: boolean;
}

const POLL_MS = 1200;
// After the first ten minutes the card asks every ten seconds: a mission that runs for
// hours (a BRAG video takes one to two) is still followed to its end, without asking
// every second. 18 November: the card stopped following after 30 minutes and showed
// RUNNING for a mission that had finished.
const SLOW_AFTER_MS = 10 * 60 * 1000;
const SLOW_POLL_MS = 10 * 1000;
// A page left open does not ask about one mission for ever; the mission keeps running
// on the server and its result is in the mission history.
const FOLLOW_LIMIT_MS = 24 * 60 * 60 * 1000;

/** How long to wait before asking again, by how long the mission has been followed. */
export function pollDelay(followedMs: number): number {
  return followedMs > SLOW_AFTER_MS ? SLOW_POLL_MS : POLL_MS;
}

export interface RunMissionOptions {
  workspaceId?: string;
  onUpdate?: (mission: MissionResult) => void;
  signal?: AbortSignal;
}

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      window.clearTimeout(timer);
      reject(new DOMException('Stopped following the mission', 'AbortError'));
    });
  });

/** Submit a command and follow the mission until it finishes or pauses for approval. */
export async function runMission(command: string, options: RunMissionOptions = {}): Promise<MissionResult> {
  const submitted = await apiClient.post<MissionResult>('/api/command/execute', {
    command,
    ...(options.workspaceId ? { workspace_id: options.workspaceId } : {}),
  });
  if (submitted.error || !submitted.data) {
    throw new Error(submitted.error || 'The command could not be submitted');
  }
  return followMission(submitted.data, options);
}

/** Follow a submitted mission (by its record or its id) until it finishes or pauses for approval. */
export async function followMission(start: MissionResult | string, options: RunMissionOptions = {}): Promise<MissionResult> {
  let mission: MissionResult;
  if (typeof start === 'string') {
    const first = await apiClient.get<MissionResult>(`/api/command/tasks/${start}`);
    if (first.error || !first.data) throw new Error(first.error || 'The mission could not be found');
    mission = first.data;
  } else {
    mission = start;
  }
  options.onUpdate?.(mission);
  const started = Date.now();
  while (!mission.finished) {
    if (Date.now() - started > FOLLOW_LIMIT_MS) {
      return { ...mission, response_text: 'JAI is still working on this mission. Its result will appear in the mission history.' };
    }
    await sleep(pollDelay(Date.now() - started), options.signal);
    const latest = await apiClient.get<MissionResult>(`/api/command/tasks/${mission.task_id}`);
    if (latest.data) {
      mission = latest.data;
      options.onUpdate?.(mission);
    }
  }
  return mission;
}

export async function cancelMission(taskId: string): Promise<MissionResult | null> {
  const res = await apiClient.post<MissionResult>(`/api/command/tasks/${taskId}/cancel`);
  if (res.error) throw new Error(res.error);
  return res.data ?? null;
}

export async function archiveMission(taskId: string, archived = true): Promise<MissionResult | null> {
  const res = await apiClient.post<MissionResult>(`/api/command/tasks/${taskId}/${archived ? 'archive' : 'unarchive'}`);
  if (res.error) throw new Error(res.error);
  return res.data ?? null;
}

/** Carry on with a paused (needs continuation) or partial mission: the same mission, on JAI's worker. */
export async function resumeMission(taskId: string): Promise<void> {
  const res = await apiClient.post(`/api/tasks/${taskId}/resume`);
  if (res.error) throw new Error(res.error);
}

export async function retryMission(taskId: string): Promise<MissionResult | null> {
  const res = await apiClient.post<MissionResult>(`/api/command/tasks/${taskId}/retry`);
  if (res.error) throw new Error(res.error);
  return res.data ?? null;
}

/** The card's model label: what the mission's engines reported running it, per role when the roles differ. */
export function ranOnLabel(mission: Pick<MissionResult, 'provider' | 'model' | 'models_by_role'>): string {
  if (!mission.model) return 'model not reported yet';
  const roles = Object.entries(mission.models_by_role ?? {});
  if (roles.length > 1) return roles.map(([role, model]) => `${role}: ${model}`).join(' · ');
  return mission.provider ? `${mission.provider}/${mission.model}` : mission.model;
}
