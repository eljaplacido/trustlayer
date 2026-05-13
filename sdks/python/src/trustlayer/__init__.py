"""TrustLayer Python SDK.

Lightweight client for emitting agent trace events conforming to
``docs/SCHEMA.md`` to a TrustLayer collector endpoint.
"""

from .client import TrustLayerClient
from .guardian import GuardianClient, Verdict
from .instrumentation import instrument_tool
from .schema import (
    AgentTraceEvent,
    CynefinDomain,
    EventType,
    LlmCallPayload,
    Metrics,
    PolicyCheckPayload,
    PolicyCheckResult,
    ToolCallPayload,
    ToolResultPayload,
)
from .tracer import Tracer

__all__ = [
    "AgentTraceEvent",
    "CynefinDomain",
    "EventType",
    "GuardianClient",
    "LlmCallPayload",
    "Metrics",
    "PolicyCheckPayload",
    "PolicyCheckResult",
    "ToolCallPayload",
    "ToolResultPayload",
    "Tracer",
    "TrustLayerClient",
    "Verdict",
    "instrument_tool",
]

__version__ = "0.1.0"
