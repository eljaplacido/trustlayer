"""FastMCP server entry point for TrustLayer.

Run via ``trustlayer-mcp`` (installed by pyproject) or ``python -m
trustlayer_mcp.server``. The transport is selectable so remote agents can
reach the server when stdio doesn't fit the deployment.

The actual tool logic lives in :mod:`trustlayer_mcp.tools` so it can be unit-
tested without the MCP transport in the way.

Transports
----------
Selected by ``TRUSTLAYER_MCP_TRANSPORT`` (default ``stdio``):

- ``stdio``  — every MCP client supports it; the historical default.
- ``sse``    — Server-Sent Events over HTTP. Binds to
  ``TRUSTLAYER_MCP_BIND`` (default ``127.0.0.1:8090``).

Unknown values fall back to stdio with a warning, so a typo in the env
never bricks the server.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
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

logger = logging.getLogger("trustlayer.mcp")

DEFAULT_SSE_HOST = "127.0.0.1"
DEFAULT_SSE_PORT = 8090

mcp = FastMCP("trustlayer")


@dataclass(frozen=True)
class TransportConfig:
    """Resolved MCP transport selection."""

    transport: str  # "stdio" | "sse"
    host: str | None = None  # only populated for sse
    port: int | None = None  # only populated for sse


def resolve_transport(env: dict[str, str] | None = None) -> TransportConfig:
    """Pure helper: pick a transport from environment variables.

    Separated out so tests can drive every branch without touching real
    env vars or spinning a real server.
    """
    env = env if env is not None else dict(os.environ)
    raw = (env.get("TRUSTLAYER_MCP_TRANSPORT") or "stdio").strip().lower()
    if raw == "stdio":
        return TransportConfig(transport="stdio")
    if raw == "sse":
        host, port = _parse_bind(env.get("TRUSTLAYER_MCP_BIND"))
        return TransportConfig(transport="sse", host=host, port=port)
    logger.warning(
        "unknown TRUSTLAYER_MCP_TRANSPORT=%r; falling back to stdio",
        raw,
    )
    return TransportConfig(transport="stdio")


def _parse_bind(value: str | None) -> tuple[str, int]:
    """Parse a ``host:port`` bind string, falling back to the defaults."""
    if not value:
        return DEFAULT_SSE_HOST, DEFAULT_SSE_PORT
    if ":" not in value:
        logger.warning(
            "TRUSTLAYER_MCP_BIND=%r missing ':port'; using default %s:%d",
            value,
            DEFAULT_SSE_HOST,
            DEFAULT_SSE_PORT,
        )
        return DEFAULT_SSE_HOST, DEFAULT_SSE_PORT
    host, _, port_str = value.rpartition(":")
    try:
        port = int(port_str)
    except ValueError:
        logger.warning(
            "TRUSTLAYER_MCP_BIND=%r has non-integer port; using default port %d",
            value,
            DEFAULT_SSE_PORT,
        )
        return host or DEFAULT_SSE_HOST, DEFAULT_SSE_PORT
    return host or DEFAULT_SSE_HOST, port


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
    config = resolve_transport()
    if config.transport == "sse":
        # FastMCP reads `settings.host`/`settings.port` for its SSE binding.
        assert config.host is not None and config.port is not None
        mcp.settings.host = config.host
        mcp.settings.port = config.port
        logger.info(
            "trustlayer-mcp serving SSE on http://%s:%d",
            config.host,
            config.port,
        )
        mcp.run(transport="sse")
    else:
        logger.info("trustlayer-mcp serving over stdio")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
