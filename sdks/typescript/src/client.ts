import type { AgentTraceEvent } from "./schema.js";
import { resolveApiToken } from "./auth.js";

export interface TrustLayerClientOptions {
  endpoint?: string;
  apiKey?: string;
  fetch?: typeof fetch;
  timeoutMs?: number;
  onError?: (err: unknown) => void;
}

const DEFAULT_ENDPOINT = "http://localhost:8080/v1/events";

export class TrustLayerClient {
  readonly endpoint: string;
  private readonly apiKey?: string;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;
  private readonly onError: (err: unknown) => void;

  constructor(opts: TrustLayerClientOptions = {}) {
    this.endpoint = opts.endpoint ?? DEFAULT_ENDPOINT;
    // ADR-007: explicit token wins, else fall back to TRUSTLAYER_API_TOKEN.
    this.apiKey = resolveApiToken(opts.apiKey);
    const f = opts.fetch ?? globalThis.fetch;
    if (!f) {
      throw new Error(
        "TrustLayerClient: no fetch implementation available. Pass opts.fetch.",
      );
    }
    this.fetchImpl = f;
    this.timeoutMs = opts.timeoutMs ?? 5000;
    this.onError =
      opts.onError ??
      ((err) => {
        console.warn("[trustlayer] emit failed:", err);
      });
  }

  async emit(event: AgentTraceEvent): Promise<void> {
    await this.send(JSON.stringify(event));
  }

  async emitBatch(events: AgentTraceEvent[]): Promise<void> {
    await this.send(JSON.stringify(events));
  }

  private async send(body: string): Promise<void> {
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
        this.onError(new Error(`HTTP ${res.status}`));
      }
    } catch (err) {
      this.onError(err);
    } finally {
      clearTimeout(timer);
    }
  }

  private headers(): Record<string, string> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (this.apiKey) headers["Authorization"] = `Bearer ${this.apiKey}`;
    return headers;
  }
}
