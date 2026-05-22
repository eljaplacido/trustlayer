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

export interface SessionSummary {
  agent_id: string;
  session_id: string;
  event_count: number;
  first_seen: string;
  last_seen: string;
}

export interface ReflectionMeta {
  name: string;
  date: string;
}

export interface Reflection {
  name: string;
  date: string;
  content: string;
}

export async function fetchEvents(
  filters: {
    agent_id?: string;
    session_id?: string;
    event_type?: string;
    limit?: number;
  } = {},
  signal?: AbortSignal,
): Promise<AgentTraceEvent[]> {
  const params = new URLSearchParams();
  if (filters.agent_id) params.set("agent_id", filters.agent_id);
  if (filters.session_id) params.set("session_id", filters.session_id);
  if (filters.event_type) params.set("event_type", filters.event_type);
  if (filters.limit !== undefined)
    params.set("limit", String(filters.limit));
  const qs = params.toString();
  const url = `${baseUrl()}/v1/events${qs ? `?${qs}` : ""}`;
  return getJson<AgentTraceEvent[]>(url, signal);
}

export async function fetchSessions(
  signal?: AbortSignal,
): Promise<SessionSummary[]> {
  return getJson<SessionSummary[]>(`${baseUrl()}/v1/sessions`, signal);
}

export async function fetchSession(
  agentId: string,
  sessionId: string,
  signal?: AbortSignal,
): Promise<AgentTraceEvent[]> {
  const url = `${baseUrl()}/v1/sessions/${encodeURIComponent(agentId)}/${encodeURIComponent(sessionId)}`;
  return getJson<AgentTraceEvent[]>(url, signal);
}

export async function fetchReflections(
  signal?: AbortSignal,
): Promise<ReflectionMeta[]> {
  return getJson<ReflectionMeta[]>(`${baseUrl()}/v1/reflections`, signal);
}

export async function fetchReflection(
  name: string,
  signal?: AbortSignal,
): Promise<Reflection> {
  const url = `${baseUrl()}/v1/reflections/${encodeURIComponent(name)}`;
  return getJson<Reflection>(url, signal);
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal });
  if (!res.ok) {
    throw new Error(`GET ${url} -> HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}
