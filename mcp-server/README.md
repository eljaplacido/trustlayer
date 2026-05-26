# trustlayer-mcp

MCP server that bridges the TrustLayer SDK, the `cynepic-guardian`
policy engine, and the Hermes memory subagent to any MCP-aware
client (Claude Code, MCP Inspector, agentic frameworks). Apache-2.0.

- **Transports:** stdio (default) and SSE (HTTP)
- **Tools:** 5, each a pure-function handler wrapping an SDK call
- **Requires:** Python 3.11+

See the root [README](../README.md) for the full architecture and
[ADR-006](../obsidian_vault/01_Architecture/ADR-006-Phase-5-Dashboard-MCP.md)
for the design.

## Tools

| MCP tool | Wraps |
|---|---|
| `trustlayer_emit_event` | `trustlayer.TrustLayerClient.emit` |
| `trustlayer_guardian_check` | `trustlayer.GuardianClient.check` |
| `trustlayer_hermes_ingest` | `hermes.HermesAgent.ingest[_jsonl]` |
| `trustlayer_hermes_get_session` | `hermes.HermesAgent.session_events` |
| `trustlayer_hermes_reflect` | `hermes.HermesAgent.reflect` |

Each handler is a pure function in
[`src/trustlayer_mcp/tools.py`](./src/trustlayer_mcp/tools.py) that
takes a Pydantic input model and returns a JSON-serialisable dict.
[`src/trustlayer_mcp/server.py`](./src/trustlayer_mcp/server.py) is a
thin `@mcp.tool()` wrapper plus the transport selector. The pure-
handler split keeps `pytest` cases transport-free.

## Install

```bash
# From the repo root, editable:
pip install -e sdks/python
pip install -e mcp-server[dev]
```

When `trustlayer-mcp` is on PyPI (pre-1.0 release pending), the
end-user install will be `pip install trustlayer-mcp`.

## Run

### Stdio (default)

```bash
trustlayer-mcp                    # FastMCP stdio transport
python -m trustlayer_mcp.server   # equivalent
```

This is what MCP IDE plugins and Claude Code launch as a subprocess.
Every MCP client supports stdio; pick this unless you need remote
access.

### SSE (HTTP)

```bash
TRUSTLAYER_MCP_TRANSPORT=sse \
TRUSTLAYER_MCP_BIND=127.0.0.1:8090 \
trustlayer-mcp
```

Pick SSE when:

- A remote agent needs to reach the server over HTTP (Tailscale,
  a reverse proxy, a separate pod).
- You want to share one MCP server across multiple Claude Code
  sessions on the same host.

Unknown values of `TRUSTLAYER_MCP_TRANSPORT` fall back to stdio
with a warning log.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `TRUSTLAYER_MCP_TRANSPORT` | `stdio` | `stdio` or `sse`. |
| `TRUSTLAYER_MCP_BIND` | `127.0.0.1:8090` | SSE bind address (`host:port`). Empty host = `127.0.0.1`; non-integer port = default port. |
| `TRUSTLAYER_API_TOKEN` | _(unset)_ | Bearer token used by the underlying SDK clients when they hit the sidecar. |

The MCP server picks up `TRUSTLAYER_API_TOKEN` transparently because
the Python SDK's `TrustLayerClient` and `GuardianClient` fall back to
the same env var (see [ADR-007](../obsidian_vault/01_Architecture/ADR-007-Auth-Bearer-Token.md)).
No MCP-server-side code change is needed when you turn auth on.

## Register with Claude Code

### Stdio (recommended)

```jsonc
// ~/.claude/settings.json (user-global) or .claude/settings.json (repo-local)
{
  "mcpServers": {
    "trustlayer": {
      "command": "trustlayer-mcp"
    }
  }
}
```

### SSE (remote)

```jsonc
{
  "mcpServers": {
    "trustlayer": {
      "url": "http://127.0.0.1:8090/sse"
    }
  }
}
```

Once registered, Claude Code lists the five tools and can call them
directly during a session.

## Tests

```bash
cd mcp-server
PYTHONPATH=src:../sdks/python/src:../skills pytest
```

- `tests/test_tools.py` — 12 cases exercising each handler with a
  mocked `TrustLayerClient` / `GuardianClient` and a tmpdir vault for
  Hermes.
- `tests/test_server.py` — 9 cases on `resolve_transport()`, the pure
  helper that maps the env to a `TransportConfig`. Every branch is
  covered without spinning a real server.

## Layout

```
mcp-server/
├── pyproject.toml
├── src/
│   └── trustlayer_mcp/
│       ├── server.py        FastMCP wrapper + transport resolver + main()
│       └── tools.py         Pure handlers (testable without MCP transport)
└── tests/
    ├── test_tools.py        Handler unit tests
    └── test_server.py       Transport resolver unit tests
```

## Links

- [Root README](../README.md) — full architecture, deployment, KPI playbook.
- [v0.1 specification](../spec/v0.1/) — the citable protocol.
- [ADR-006](../obsidian_vault/01_Architecture/ADR-006-Phase-5-Dashboard-MCP.md) — design (Python, stdio-first, pure handlers).
- [Contributing](../CONTRIBUTING.md).
