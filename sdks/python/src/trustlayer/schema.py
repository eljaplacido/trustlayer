"""Pydantic models for the TrustLayer trace schema.

Mirrors ``docs/SCHEMA.md``. Any change to the wire format must be made here
first, then propagated to ``sdks/typescript/src/schema.ts``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class EventType(str, Enum):
    AGENT_START = "AGENT_START"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    LLM_CALL = "LLM_CALL"
    POLICY_CHECK = "POLICY_CHECK"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
    AGENT_END = "AGENT_END"


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
    return datetime.now(timezone.utc)


class AgentTraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: UUID = Field(default_factory=uuid4)
    agent_id: str
    session_id: str
    timestamp: datetime = Field(default_factory=_utcnow)
    event_type: EventType
    cynefin_domain: CynefinDomain = CynefinDomain.DISORDER
    payload: dict[str, Any] = Field(default_factory=dict)
    metrics: Metrics = Field(default_factory=Metrics)
