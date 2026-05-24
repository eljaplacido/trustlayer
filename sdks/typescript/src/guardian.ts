import type { AgentTraceEvent, PolicyCheckResult } from "./schema.js";
import { resolveApiToken } from "./auth.js";

export interface Verdict {
  decision: PolicyCheckResult;
  rule: string | null;
  reason: string | null;
  policy: string;
}

export interface GuardianClientOptions {
  endpoint?: string;
  policyName?: string;
  apiKey?: string;
  fetch?: typeof fetch;
  timeoutMs?: number;
  failOpen?: boolean;
  onError?: (err: unknown) => void;
}

const DEFAULT_GUARDIAN_ENDPOINT = "http://127.0.0.1:8089/v1/check";
const VALID_DECISIONS: ReadonlySet<PolicyCheckResult> = new Set([
  "PASS",
  "FAIL",
  "ESCALATE",
]);

export class GuardianClient {
  readonly endpoint: string;
  readonly policyName?: string;
  readonly failOpen: boolean;
  private readonly apiKey?: string;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;
  private readonly onError: (err: unknown) => void;

  constructor(opts: GuardianClientOptions = {}) {
    this.endpoint = opts.endpoint ?? DEFAULT_GUARDIAN_ENDPOINT;
    this.policyName = opts.policyName;
    // ADR-007: explicit token wins, else fall back to TRUSTLAYER_API_TOKEN.
    this.apiKey = resolveApiToken(opts.apiKey);
    const f = opts.fetch ?? globalThis.fetch;
    if (!f) {
      throw new Error(
        "GuardianClient: no fetch implementation available. Pass opts.fetch.",
      );
    }
    this.fetchImpl = f;
    this.timeoutMs = opts.timeoutMs ?? 1000;
    this.failOpen = opts.failOpen ?? true;
    this.onError =
      opts.onError ??
      ((err) => {
        console.warn("[trustlayer-guardian] check failed:", err);
      });
  }

  async check(event: AgentTraceEvent, policyName?: string): Promise<Verdict> {
    const body = JSON.stringify({
      event,
      policy_name: policyName ?? this.policyName ?? null,
    });
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const res = await this.fetchImpl(this.endpoint, {
        method: "POST",
        headers: this.headers(),
        body,
        signal: controller.signal,
      });
      if (!res.ok) {
        return this.fallback(`HTTP ${res.status}`);
      }
      const data: unknown = await res.json();
      return this.coerceVerdict(data);
    } catch (err) {
      this.onError(err);
      return this.fallback(err instanceof Error ? err.message : String(err));
    } finally {
      clearTimeout(timer);
    }
  }

  private coerceVerdict(data: unknown): Verdict {
    if (!data || typeof data !== "object") {
      return this.fallback(`unexpected verdict payload type: ${typeof data}`);
    }
    const obj = data as Record<string, unknown>;
    const decision = obj.decision;
    if (typeof decision !== "string" || !VALID_DECISIONS.has(decision as PolicyCheckResult)) {
      return this.fallback(`unexpected verdict decision: ${String(decision)}`);
    }
    return {
      decision: decision as PolicyCheckResult,
      rule: typeof obj.rule === "string" ? obj.rule : null,
      reason: typeof obj.reason === "string" ? obj.reason : null,
      policy: typeof obj.policy === "string" ? obj.policy : "unknown",
    };
  }

  private fallback(detail: string): Verdict {
    return {
      decision: this.failOpen ? "PASS" : "FAIL",
      rule: null,
      reason: `guardian unavailable: ${detail}`,
      policy: "fallback",
    };
  }

  private headers(): Record<string, string> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (this.apiKey) headers["Authorization"] = `Bearer ${this.apiKey}`;
    return headers;
  }
}
