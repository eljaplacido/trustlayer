"""Pydantic models for the TrustLayer trace schema.

Mirrors ``docs/SCHEMA.md``. Any change to the wire format must be made here
first, then propagated to ``sdks/typescript/src/schema.ts``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_serializer
from pydantic_core.core_schema import SerializerFunctionWrapHandler


class EventType(str, Enum):
    AGENT_START = "AGENT_START"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    LLM_CALL = "LLM_CALL"
    POLICY_CHECK = "POLICY_CHECK"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
    AGENT_END = "AGENT_END"
    DISCLOSURE_SHOWN = "DISCLOSURE_SHOWN"
    CONTENT_MARKED = "CONTENT_MARKED"
    HUMAN_DECISION = "HUMAN_DECISION"
    HARNESS_SNAPSHOT = "HARNESS_SNAPSHOT"


class CynefinDomain(str, Enum):
    CLEAR = "CLEAR"
    COMPLICATED = "COMPLICATED"
    COMPLEX = "COMPLEX"
    CHAOTIC = "CHAOTIC"
    DISORDER = "DISORDER"


class PolicyCheckResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ESCALATE = "ESCALATE"


class Metrics(BaseModel):
    model_config = ConfigDict(extra="allow")

    latency_ms: float | None = None
    cost_usd: float | None = None
    tokens_prompt: int | None = None
    tokens_completion: int | None = None


class ToolCallPayload(BaseModel):
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)


class ToolResultPayload(BaseModel):
    tool_name: str
    result: Any | None = None
    error: str | None = None


class LlmCallPayload(BaseModel):
    model: str
    prompt: str | None = None
    completion: str | None = None


class PolicyCheckPayload(BaseModel):
    policy_name: str
    action: str
    result: PolicyCheckResult
    reason: str | None = None


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AgentTraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: UUID = Field(default_factory=uuid4)
    agent_id: str
    session_id: str
    timestamp: datetime = Field(default_factory=_utcnow)
    event_type: EventType
    #: Causal parent — the `trace_id` of the event that caused this one
    #: (ADR-019). Optional and absent by default.
    #:
    #: Causality is client-side knowledge: only the agent knows which call
    #: spawned which. Inferring it from arrival order breaks under
    #: concurrency, which is the regime agentic systems operate in, so it is
    #: carried explicitly or not at all.
    parent_trace_id: UUID | None = None
    cynefin_domain: CynefinDomain = CynefinDomain.DISORDER
    payload: dict[str, Any] = Field(default_factory=dict)
    metrics: Metrics = Field(default_factory=Metrics)

    @model_serializer(mode="wrap")
    def _omit_absent_parent(self, handler: SerializerFunctionWrapHandler) -> Any:
        """Drop ``parent_trace_id`` from the wire when it was never set.

        The envelope is closed (spec §1.2): a receiver MUST reject an event
        carrying an unknown top-level field. So an emitter that serialises
        ``"parent_trace_id": null`` is rejected outright by every collector
        built before the field existed, which turns what §1.7 classifies as a
        MINOR addition into a hard break for anyone who has not redeployed.

        The Rust core avoids this with ``skip_serializing_if``, Go with
        ``omitempty``, and TypeScript by leaving the key ``undefined``; each
        states that an emitter which does not set the field produces
        byte-identical output to v0.1. This makes the Python SDK keep the same
        promise, at the model rather than in one caller, so the guarantee
        holds for anyone who serialises an event themselves.
        """
        data = handler(self)
        if isinstance(data, dict) and data.get("parent_trace_id") is None:
            data.pop("parent_trace_id", None)
        return data
