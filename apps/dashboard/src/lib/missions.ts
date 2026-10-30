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
  execution_time: number;
  tokens_used: number;
  approval_reason?: string | null;
  error?: string | null;
  finished: boolean;
  dispatch_mode?: string | null;
  attempts?: number;
  heartbeat_at?: string | null;
  events?: MissionEvent[];
}

const POLL_MS = 1200;
// Generous: long builds and multi-agent missions are normal. The mission keeps
// running on the server if the page stops following it.
const FOLLOW_LIMIT_MS = 30 * 60 * 1000;

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
      return { ...mission, response_text: 'JARV is still working on this mission. Its result will appear in the mission history.' };
    }
    await sleep(POLL_MS, options.signal);
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

export async function retryMission(taskId: string): Promise<MissionResult | null> {
  const res = await apiClient.post<MissionResult>(`/api/command/tasks/${taskId}/retry`);
  if (res.error) throw new Error(res.error);
  return res.data ?? null;
}
