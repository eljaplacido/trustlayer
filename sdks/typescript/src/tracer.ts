import { randomUUID } from "node:crypto";

import { TrustLayerClient } from "./client.js";
import type {
  AgentTraceEvent,
  CynefinDomain,
  EventType,
  Metrics,
  PolicyCheckPayload,
  PolicyCheckResult,
  ToolCallPayload,
  ToolResultPayload,
} from "./schema.js";

export interface TracerOptions {
  agentId: string;
  sessionId?: string;
  client?: TrustLayerClient;
  cynefinDomain?: CynefinDomain;
}

export class Tracer {
  readonly agentId: string;
  readonly sessionId: string;
  readonly client: TrustLayerClient;
  cynefinDomain: CynefinDomain;

  constructor(opts: TracerOptions) {
    this.agentId = opts.agentId;
    this.sessionId = opts.sessionId ?? randomUUID();
    this.client = opts.client ?? new TrustLayerClient();
    this.cynefinDomain = opts.cynefinDomain ?? "DISORDER";
  }

  buildEvent(
    eventType: EventType,
    payload: Record<string, unknown> = {},
    metrics: Metrics = {},
    cynefinDomain?: CynefinDomain,
  ): AgentTraceEvent {
    return {
      trace_id: randomUUID(),
      agent_id: this.agentId,
      session_id: this.sessionId,
      timestamp: new Date().toISOString(),
      event_type: eventType,
      cynefin_domain: cynefinDomain ?? this.cynefinDomain,
      payload,
      metrics,
    };
  }

  async emit(
    eventType: EventType,
    payload: Record<string, unknown> = {},
    metrics: Metrics = {},
    cynefinDomain?: CynefinDomain,
  ): Promise<AgentTraceEvent> {
    const event = this.buildEvent(eventType, payload, metrics, cynefinDomain);
    await this.client.emit(event);
    return event;
  }

  async toolCall<T>(
    toolName: string,
    args: Record<string, unknown>,
    fn: () => Promise<T> | T,
  ): Promise<T> {
    const callPayload: ToolCallPayload = { tool_name: toolName, tool_args: args };
    await this.emit("TOOL_CALL", callPayload);
    const start = performance.now();
    try {
      const result = await fn();
      const resultPayload: ToolResultPayload = {
        tool_name: toolName,
        result,
      };
      await this.emit("TOOL_RESULT", resultPayload, {
        latency_ms: performance.now() - start,
      });
      return result;
    } catch (err) {
      const resultPayload: ToolResultPayload = {
        tool_name: toolName,
        error:
          err instanceof Error ? (err.stack ?? err.message) : String(err),
      };
      await this.emit("TOOL_RESULT", resultPayload, {
        latency_ms: performance.now() - start,
      });
      throw err;
    }
  }

  async policyCheck(
    policyName: string,
    action: string,
    result: PolicyCheckResult,
    reason?: string,
  ): Promise<AgentTraceEvent> {
    const payload: PolicyCheckPayload = {
      policy_name: policyName,
      action,
      result,
      reason,
    };
    return this.emit("POLICY_CHECK", payload);
  }
}
