import { z } from "zod";

export const EventType = z.enum([
  "AGENT_START",
  "TOOL_CALL",
  "TOOL_RESULT",
  "LLM_CALL",
  "POLICY_CHECK",
  "HUMAN_ESCALATION",
  "AGENT_END",
]);
export type EventType = z.infer<typeof EventType>;

export const CynefinDomain = z.enum([
  "CLEAR",
  "COMPLICATED",
  "COMPLEX",
  "CHAOTIC",
  "DISORDER",
]);
export type CynefinDomain = z.infer<typeof CynefinDomain>;

export const PolicyCheckResult = z.enum(["PASS", "FAIL", "ESCALATE"]);
export type PolicyCheckResult = z.infer<typeof PolicyCheckResult>;

export const Metrics = z
  .object({
    latency_ms: z.number().optional(),
    cost_usd: z.number().optional(),
    tokens_prompt: z.number().int().optional(),
    tokens_completion: z.number().int().optional(),
  })
  .passthrough();
export type Metrics = z.infer<typeof Metrics>;

export const ToolCallPayload = z.object({
  tool_name: z.string(),
  tool_args: z.record(z.unknown()).default({}),
});
export type ToolCallPayload = z.infer<typeof ToolCallPayload>;

export const ToolResultPayload = z.object({
  tool_name: z.string(),
  result: z.unknown().optional(),
  error: z.string().optional(),
});
export type ToolResultPayload = z.infer<typeof ToolResultPayload>;

export const LlmCallPayload = z.object({
  model: z.string(),
  prompt: z.string().optional(),
  completion: z.string().optional(),
});
export type LlmCallPayload = z.infer<typeof LlmCallPayload>;

export const PolicyCheckPayload = z.object({
  policy_name: z.string(),
  action: z.string(),
  result: PolicyCheckResult,
  reason: z.string().optional(),
});
export type PolicyCheckPayload = z.infer<typeof PolicyCheckPayload>;

export const AgentTraceEvent = z
  .object({
    trace_id: z.string().uuid(),
    agent_id: z.string(),
    session_id: z.string(),
    timestamp: z.string().datetime({ offset: true }),
    event_type: EventType,
    cynefin_domain: CynefinDomain.default("DISORDER"),
    payload: z.record(z.unknown()).default({}),
    metrics: Metrics.default({}),
  })
  .strict();
export type AgentTraceEvent = z.infer<typeof AgentTraceEvent>;
