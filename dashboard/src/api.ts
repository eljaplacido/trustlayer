export interface AgentTraceEvent {
  trace_id: string;
  agent_id: string;
  session_id: string;
  timestamp: string;
  event_type: string;
  cynefin_domain?: string;
  payload?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
}

const DEFAULT_BASE = "http://127.0.0.1:8089";

function baseUrl(): string {
  const fromEnv = import.meta.env.VITE_TRUSTLAYER_BASE_URL as
    | string
    | undefined;
  return fromEnv ?? DEFAULT_BASE;
}

export async function fetchEvents(
  filters: { agent_id?: string; session_id?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<AgentTraceEvent[]> {
  const params = new URLSearchParams();
  if (filters.agent_id) params.set("agent_id", filters.agent_id);
  if (filters.session_id) params.set("session_id", filters.session_id);
  if (filters.limit !== undefined)
    params.set("limit", String(filters.limit));
  const qs = params.toString();
  const url = `${baseUrl()}/v1/events${qs ? `?${qs}` : ""}`;
  const res = await fetch(url, { signal });
  if (!res.ok) {
    throw new Error(`GET ${url} -> HTTP ${res.status}`);
  }
  return (await res.json()) as AgentTraceEvent[];
}
