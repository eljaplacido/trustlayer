---
skill: trustlayer-mcp
status: active
description: MCP server bridging TrustLayer (SDK + guardian + Hermes) to MCP-aware clients
version: 0.2.0
language: Python
entry_point: mcp-server/src/trustlayer_mcp/server.py
transport: stdio | sse
links:
  - "[[../01_Architecture/ADR-006-Phase-5-Dashboard-MCP]]"
---

# trustlayer-mcp

A Python FastMCP server that exposes the TrustLayer runtime to any
MCP-aware client (Claude Code, the MCP Inspector, agent frameworks)
without requiring the per-language SDKs.

## Tools

| MCP tool | Wraps | Purpose |
|---|---|---|
| `trustlayer_emit_event` | `TrustLayerClient.emit` | Emit one `AgentTraceEvent`. |
| `trustlayer_guardian_check` | `GuardianClient.check` | Get a PASS/FAIL/ESCALATE verdict. |
| `trustlayer_hermes_ingest` | `HermesAgent.ingest[_jsonl]` | Ingest events into a vault; optional reflect. |
| `trustlayer_hermes_get_session` | `HermesAgent.session_events` | Read back one session's events. |
| `trustlayer_hermes_reflect` | `HermesAgent.reflect` | Run a reflection pass over a vault. |

## Design

Tool logic lives in `trustlayer_mcp.tools` as pure functions — each
takes a Pydantic input model and returns a JSON-serialisable dict.
`server.py` is a thin `@mcp.tool()` wrapper. This keeps the handlers
testable without the MCP transport: pytest calls them directly with
fake `TrustLayerClient` / `GuardianClient` factories and a tmpdir vault
for Hermes.

## Run

```bash
cd mcp-server
python -m venv .venv && .venv/bin/pip install -e ../sdks/python -e .
.venv/bin/trustlayer-mcp        # FastMCP stdio
```

## Register with Claude Code

```jsonc
// .claude/settings.json
{ "mcpServers": { "trustlayer": { "command": "trustlayer-mcp" } } }
```

## Layout
- `mcp-server/src/trustlayer_mcp/tools.py` — pure, transport-free handlers
- `mcp-server/src/trustlayer_mcp/server.py` — FastMCP wrapper + `main()`
- `mcp-server/tests/test_tools.py` — 12 pytest cases (handlers tested directly)

## Transport (Slice 3)

| Env var | Default | Effect |
|---|---|---|
| `TRUSTLAYER_MCP_TRANSPORT` | `stdio` | `stdio` or `sse`. Unknown values fall back to stdio. |
| `TRUSTLAYER_MCP_BIND` | `127.0.0.1:8090` | `host:port` for the SSE transport. Empty host = `127.0.0.1`; non-integer port = default. |

`resolve_transport()` in `server.py` is the pure decision boundary —
it returns a `TransportConfig` dataclass that tests exercise directly
without spinning a real server. `main()` applies the config and calls
`mcp.run(transport=...)`.

Pick `sse` when:
- A remote agent needs to reach the server over HTTP (Tailscale, a
  reverse proxy, a separate pod).
- You want to share one MCP server across multiple Claude Code
  sessions on the same host.

Stay on `stdio` when:
- The MCP client launches the server as a subprocess (the Claude
  Code default, and how most MCP IDE plugins work).
