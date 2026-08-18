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

export function baseUrl(): string {
  const fromEnv = import.meta.env.VITE_TRUSTLAYER_BASE_URL as
    | string
    | undefined;
  return fromEnv ?? DEFAULT_BASE;
}

/**
 * ADR-007: bearer token sourced from VITE_TRUSTLAYER_API_TOKEN at build
 * time. Returns undefined when unset so we don't send an empty header.
 */
export function apiToken(): string | undefined {
  const raw = import.meta.env.VITE_TRUSTLAYER_API_TOKEN as
    | string
    | undefined;
  return raw && raw.length > 0 ? raw : undefined;
}

function authHeaders(): Record<string, string> | undefined {
  const token = apiToken();
  return token ? { Authorization: `Bearer ${token}` } : undefined;
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

/**
 * ADR-020: the evaluator service. Separate from the trace store because the
 * dashboard is a static bundle — it cannot hold a provider credential, so the
 * only place a model endpoint is configured is server-side, which is also what
 * keeps the egress policy enforceable.
 */
export function evaluatorBaseUrl(): string {
  const fromEnv = import.meta.env.VITE_TRUSTLAYER_EVAL_URL as
    | string
    | undefined;
  return fromEnv ?? "http://127.0.0.1:8091";
}

export interface AdvisorHealth {
  status: string;
  provider: string;
  model: string;
  residency: string;
  available: boolean;
  guardian_enabled: boolean;
}

export interface AdvisorModels {
  provider: string;
  current: string;
  models: string[];
}

export interface AdvisorFinding {
  claim: string;
  cited_trace_ids: string[];
  confidence: string;
  severity: string;
  human_review_required: boolean;
  remediation?: string | null;
}

export interface AdvisorRun {
  run_id: string;
  role: string;
  provider: string;
  model: string;
  duration_ms: number;
  findings: AdvisorFinding[];
  ungrounded_rejected: number;
  narrative?: string | null;
  evidence_window: { event_count: number; result_hash: string };
}

export interface AdvisorReply {
  run: AdvisorRun;
  provider: string;
  model: string;
  residency: string;
  fell_back: boolean;
}

export async function fetchAdvisorHealth(
  signal?: AbortSignal,
): Promise<AdvisorHealth> {
  return getJson<AdvisorHealth>(`${evaluatorBaseUrl()}/health`, signal);
}

export async function fetchAdvisorModels(
  signal?: AbortSignal,
): Promise<AdvisorModels> {
  return getJson<AdvisorModels>(`${evaluatorBaseUrl()}/v1/models`, signal);
}

export async function askAdvisor(
  question: string,
  filters: { agent_id?: string; session_id?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<AdvisorReply> {
  const url = `${evaluatorBaseUrl()}/v1/advisor/chat`;
  const res = await fetch(url, {
    method: "POST",
    signal,
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ question, ...filters }),
  });
  if (!res.ok) {
    // The service distinguishes refusals from failures, and the operator needs
    // to see which: 451 is an egress refusal, 403 a policy denial. Surfacing
    // them as a generic error would hide the governance decision that is the
    // whole point of routing the call through this service.
    let detail = "";
    try {
      const body = (await res.json()) as { detail?: unknown };
      detail = typeof body.detail === "string" ? body.detail : "";
    } catch {
      detail = "";
    }
    const prefix =
      res.status === 451
        ? "Refused by egress policy"
        : res.status === 403
          ? "Refused by guardian policy"
          : `HTTP ${res.status}`;
    throw new Error(detail ? `${prefix}: ${detail}` : prefix);
  }
  return (await res.json()) as AdvisorReply;
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal, headers: authHeaders() });
  if (!res.ok) {
    let detail = "";
    try {
      const text = await res.text();
      detail = text.trim();
    } catch {
      detail = "";
    }
    const suffix = detail ? `: ${detail}` : "";
    throw new Error(`GET ${url} -> HTTP ${res.status}${suffix}`);
  }
  return (await res.json()) as T;
}
