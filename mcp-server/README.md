# trustlayer-mcp

Phase 5 — MCP server that bridges TrustLayer's SDK, `cynepic-guardian` policy
engine, and Hermes memory subagent to any MCP-aware client (Claude Code,
the MCP Inspector, etc.).

## Exposed tools

| Tool                              | Wraps                                   |
| --------------------------------- | --------------------------------------- |
| `trustlayer_emit_event`           | `trustlayer.TrustLayerClient.emit`      |
| `trustlayer_guardian_check`       | `trustlayer.GuardianClient.check`       |
| `trustlayer_hermes_ingest`        | `hermes.HermesAgent.ingest[_jsonl]`     |
| `trustlayer_hermes_get_session`   | `hermes.HermesAgent.session_events`     |
| `trustlayer_hermes_reflect`       | `hermes.HermesAgent.reflect`            |

## Install (editable, dev)

```bash
# From repo root:
pip install -e sdks/python
pip install -e mcp-server[dev]
```

## Run (stdio)

```bash
trustlayer-mcp                    # FastMCP stdio transport
python -m trustlayer_mcp.server   # equivalent
```

## Register with Claude Code

```jsonc
// ~/.claude/settings.json (or .claude/settings.json in this repo)
{
  "mcpServers": {
    "trustlayer": {
      "command": "trustlayer-mcp"
    }
  }
}
```

## Tests

```bash
cd mcp-server && pytest
```

Handler tests in `tests/test_tools.py` exercise each tool's pure handler
without going through the MCP transport, mocking only the external HTTP
clients (`TrustLayerClient`, `GuardianClient`) and using a tmpdir vault for
Hermes.

## Architecture notes

See [ADR-006](../obsidian_vault/01_Architecture/ADR-006-Phase-5-Dashboard-MCP.md)
for why the MCP server is Python (Hermes is Python-only; Python SDK is the
most mature) and the choice of FastMCP stdio over SSE for v1.
