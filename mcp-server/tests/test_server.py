"""Tests for the MCP transport resolver (Slice 3).

`resolve_transport` is the pure decision boundary between the env and
`mcp.run(...)`. Drive every branch here so we can swap transports
without spinning the server.
"""

from __future__ import annotations

from trustlayer_mcp.server import (
    DEFAULT_SSE_HOST,
    DEFAULT_SSE_PORT,
    TransportConfig,
    resolve_transport,
)


def test_defaults_to_stdio() -> None:
    cfg = resolve_transport(env={})
    assert cfg == TransportConfig(transport="stdio")


def test_explicit_stdio_is_stdio() -> None:
    cfg = resolve_transport(env={"TRUSTLAYER_MCP_TRANSPORT": "stdio"})
    assert cfg.transport == "stdio"
    assert cfg.host is None and cfg.port is None


def test_sse_uses_default_bind_when_unset() -> None:
    cfg = resolve_transport(env={"TRUSTLAYER_MCP_TRANSPORT": "sse"})
    assert cfg.transport == "sse"
    assert cfg.host == DEFAULT_SSE_HOST
    assert cfg.port == DEFAULT_SSE_PORT


def test_sse_parses_host_port() -> None:
    cfg = resolve_transport(
        env={
            "TRUSTLAYER_MCP_TRANSPORT": "sse",
            "TRUSTLAYER_MCP_BIND": "0.0.0.0:9123",
        }
    )
    assert cfg == TransportConfig(transport="sse", host="0.0.0.0", port=9123)


def test_sse_uses_default_host_when_only_port_given() -> None:
    # An empty host before ':' is treated as the default host.
    cfg = resolve_transport(
        env={
            "TRUSTLAYER_MCP_TRANSPORT": "sse",
            "TRUSTLAYER_MCP_BIND": ":9000",
        }
    )
    assert cfg.host == DEFAULT_SSE_HOST
    assert cfg.port == 9000


def test_sse_falls_back_to_default_port_on_non_int() -> None:
    cfg = resolve_transport(
        env={
            "TRUSTLAYER_MCP_TRANSPORT": "sse",
            "TRUSTLAYER_MCP_BIND": "127.0.0.1:not-a-port",
        }
    )
    assert cfg.transport == "sse"
    assert cfg.host == "127.0.0.1"
    assert cfg.port == DEFAULT_SSE_PORT


def test_sse_missing_colon_uses_defaults() -> None:
    cfg = resolve_transport(
        env={
            "TRUSTLAYER_MCP_TRANSPORT": "sse",
            "TRUSTLAYER_MCP_BIND": "127.0.0.1",
        }
    )
    assert cfg.host == DEFAULT_SSE_HOST
    assert cfg.port == DEFAULT_SSE_PORT


def test_unknown_transport_falls_back_to_stdio() -> None:
    cfg = resolve_transport(env={"TRUSTLAYER_MCP_TRANSPORT": "ipv6-frob"})
    assert cfg.transport == "stdio"


def test_value_is_case_insensitive_and_trimmed() -> None:
    cfg = resolve_transport(env={"TRUSTLAYER_MCP_TRANSPORT": "  SSE "})
    assert cfg.transport == "sse"
