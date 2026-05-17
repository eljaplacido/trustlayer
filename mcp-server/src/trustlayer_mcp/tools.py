"""Pure tool handlers for the TrustLayer MCP server.

Each handler is a plain function that accepts a typed Pydantic input model and
returns a JSON-serialisable dict. The MCP transport layer in ``server.py``
wires these into ``FastMCP``. Keeping the handlers transport-free means we can
unit-test them directly without spinning up an MCP client/server pair.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from trustlayer import (
    AgentTraceEvent,
    CynefinDomain,
    EventType,
    GuardianClient,
    Metrics,
    TrustLayerClient,
)
from trustlayer.guardian import DEFAULT_GUARDIAN_ENDPOINT


class EmitEventInput(BaseModel):
    agent_id: str
    session_id: str
    event_type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    cynefin_domain: CynefinDomain = CynefinDomain.DISORDER
    metrics: Metrics | None = None
    endpoint: str | None = None


class GuardianCheckInput(BaseModel):
    event: AgentTraceEvent
    policy_name: str | None = None
    endpoint: str = DEFAULT_GUARDIAN_ENDPOINT
    fail_open: bool = True


class HermesIngestInput(BaseModel):
    vault_path: str
    events: list[dict[str, Any]] | None = None
    jsonl_path: str | None = None
    reflect: bool = False


class HermesGetSessionInput(BaseModel):
    vault_path: str
    agent_id: str
    session_id: str


class HermesReflectInput(BaseModel):
    vault_path: str


def emit_event(
    input: EmitEventInput,
    *,
    client_factory: Any = TrustLayerClient,
) -> dict[str, Any]:
    """Build an AgentTraceEvent, send it through the SDK client, return the event."""
    event = AgentTraceEvent(
        agent_id=input.agent_id,
        session_id=input.session_id,
        event_type=input.event_type,
        cynefin_domain=input.cynefin_domain,
        payload=input.payload,
        metrics=input.metrics or Metrics(),
    )
    client = (
        client_factory(endpoint=input.endpoint) if input.endpoint else client_factory()
    )
    try:
        client.emit(event)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    return event.model_dump(mode="json")


def guardian_check(
    input: GuardianCheckInput,
    *,
    client_factory: Any = GuardianClient,
) -> dict[str, Any]:
    """Forward an event to the cynepic-guardian and return the verdict."""
    client = client_factory(
        endpoint=input.endpoint,
        policy_name=input.policy_name,
        fail_open=input.fail_open,
    )
    try:
        verdict = client.check(input.event, policy_name=input.policy_name)
    finally:
        client.close()
    return dict(verdict)


def hermes_ingest(
    input: HermesIngestInput,
    *,
    agent_factory: Any | None = None,
) -> dict[str, Any]:
    """Ingest events (list or JSONL file) into a Hermes vault. Optionally reflect."""
    if (input.events is None) == (input.jsonl_path is None):
        raise ValueError("Provide exactly one of `events` or `jsonl_path`.")
    agent = _build_agent(input.vault_path, agent_factory)
    if input.jsonl_path is not None:
        written = agent.ingest_jsonl(input.jsonl_path)
    else:
        assert input.events is not None
        written = agent.ingest(input.events)
    reflection_path = agent.reflect() if input.reflect else None
    return {
        "notes_written": [str(p) for p in written],
        "reflection_path": str(reflection_path) if reflection_path else None,
    }


def hermes_get_session(input: HermesGetSessionInput) -> dict[str, Any]:
    """Return the chronological event list for one (agent_id, session_id)."""
    agent = _build_agent(input.vault_path, None)
    events = agent.session_events(input.agent_id, input.session_id)
    return {
        "agent_id": input.agent_id,
        "session_id": input.session_id,
        "events": [e.model_dump(mode="json") for e in events],
    }


def hermes_reflect(
    input: HermesReflectInput,
    *,
    agent_factory: Any | None = None,
) -> dict[str, Any]:
    """Trigger a reflection pass across all known sessions in the vault."""
    agent = _build_agent(input.vault_path, agent_factory)
    out_path = agent.reflect()
    return {"reflection_path": str(out_path) if out_path else None}


def _build_agent(vault_path: str, agent_factory: Any | None) -> Any:
    if agent_factory is not None:
        return agent_factory(vault_path=Path(vault_path))
    from hermes.hermes_agent import HermesAgent

    return HermesAgent(vault_path=Path(vault_path))
