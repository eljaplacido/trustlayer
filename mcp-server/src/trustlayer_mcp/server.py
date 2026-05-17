"""FastMCP server entry point for TrustLayer.

Run via ``trustlayer-mcp`` (installed by pyproject) or ``python -m
trustlayer_mcp.server``. Communicates over stdio so MCP-aware clients (Claude
Code, Inspector, etc.) can register the server with a single command.

The actual tool logic lives in :mod:`trustlayer_mcp.tools` so it can be unit-
tested without the MCP transport in the way.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .tools import (
    EmitEventInput,
    GuardianCheckInput,
    HermesGetSessionInput,
    HermesIngestInput,
    HermesReflectInput,
    emit_event,
    guardian_check,
    hermes_get_session,
    hermes_ingest,
    hermes_reflect,
)

mcp = FastMCP("trustlayer")


@mcp.tool()
def trustlayer_emit_event(input: EmitEventInput) -> dict[str, Any]:
    """Emit an AgentTraceEvent through the TrustLayer ingest client."""
    return emit_event(input)


@mcp.tool()
def trustlayer_guardian_check(input: GuardianCheckInput) -> dict[str, Any]:
    """Forward an event to the cynepic-guardian and return the PASS/FAIL/ESCALATE verdict."""
    return guardian_check(input)


@mcp.tool()
def trustlayer_hermes_ingest(input: HermesIngestInput) -> dict[str, Any]:
    """Ingest trace events into a Hermes vault and optionally trigger a reflection."""
    return hermes_ingest(input)


@mcp.tool()
def trustlayer_hermes_get_session(input: HermesGetSessionInput) -> dict[str, Any]:
    """Read back the event list for one (agent_id, session_id) from a Hermes vault."""
    return hermes_get_session(input)


@mcp.tool()
def trustlayer_hermes_reflect(input: HermesReflectInput) -> dict[str, Any]:
    """Run a reflection pass across all known sessions in a Hermes vault."""
    return hermes_reflect(input)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
