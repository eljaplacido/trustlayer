# TrustLayer Dashboard

React + Vite + TypeScript observability UI for TrustLayer. Polls the
[`trustlayer-guardian`](../core-rs/) sidecar over its public HTTP API
and renders four live panes: **Traces**, **Sessions**, **Reflections**,
and **Policy**. Apache-2.0.

- **Stack:** React 18 + Vite 5 + TypeScript strict (`noUncheckedIndexedAccess`)
- **Tests:** 33 vitest cases (14 API client + 19 React Testing Library component tests)
- **Requires:** Node 20+ for development; the built static bundle has no runtime requirements

See the root [README](../README.md) for the full architecture and
[ADR-006](../obsidian_vault/01_Architecture/ADR-006-Phase-5-Dashboard-MCP.md)
for the design.

## Panes

| Pane | What it shows | Endpoint |
|---|---|---|
| **Traces** | Live `AgentTraceEvent` stream, most recent first. Refresh every 5 s. | `GET /v1/events?limit=50` |
| **Sessions** | One row per `(agent_id, session_id)`. Click to drill into the timeline. | `GET /v1/sessions` + `GET /v1/sessions/{agent}/{session}` |
| **Reflections** | Hermes-generated synthesis notes. Click a date to render the markdown. | `GET /v1/reflections` + `GET /v1/reflections/{name}` |
| **Policy** | Recent `POLICY_CHECK` events with colour-coded PASS / FAIL / ESCALATE verdicts. | `GET /v1/events?event_type=POLICY_CHECK&limit=50` |

Every pane handles its own loading / error / empty / loaded states.

## Quickstart

```bash
cd dashboard
npm install

# Point at a local sidecar
npm run dev               # Vite dev server on http://localhost:5173

# Production build
npm run build             # outputs dist/
npm run preview           # serves dist/ for smoke-testing

# Tests
npm test                  # 33 vitest cases
npm run typecheck         # tsc --noEmit, must stay clean
```

A sidecar is needed to see data. The simplest setup:

```bash
# Terminal 1
cd ../core-rs
TRUSTLAYER_VAULT_PATH=../obsidian_vault \
  cargo run --release --features server --bin trustlayer-guardian

# Terminal 2
cd dashboard && npm run dev
```

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `VITE_TRUSTLAYER_BASE_URL` | `http://127.0.0.1:8089` | Sidecar base URL (host only — the dashboard appends `/v1/...`). |
| `VITE_TRUSTLAYER_API_TOKEN` | _(unset)_ | Bearer token (ADR-007). When set, sent as `Authorization: Bearer …` on every request. |

Vite reads these at **build time**. For local development put them in
`.env.local`:

```bash
# dashboard/.env.local
VITE_TRUSTLAYER_BASE_URL=https://trustlayer.internal
VITE_TRUSTLAYER_API_TOKEN=<token>
```

For static-hosted production builds, set them in your CI before
`npm run build`.

The token must match `TRUSTLAYER_API_TOKEN` on the sidecar. Wrong /
missing token → `401` and the panes surface a clear error state.

## Architecture

- [`src/api.ts`](./src/api.ts) — typed wrappers around the trace-store
  HTTP API (`fetchEvents`, `fetchSessions`, `fetchSession`,
  `fetchReflections`, `fetchReflection`). Shared `getJson<T>` helper
  handles URL construction, the auth header, and HTTP-status mapping
  in one place.
- [`src/TracesPane.tsx`](./src/TracesPane.tsx),
  [`src/SessionsPane.tsx`](./src/SessionsPane.tsx),
  [`src/ReflectionsPane.tsx`](./src/ReflectionsPane.tsx),
  [`src/PolicyPane.tsx`](./src/PolicyPane.tsx) — one component per pane.
  Each owns its own polling interval and state machine.
- [`src/App.tsx`](./src/App.tsx) — page shell + section layout.

## Tests

```bash
npm test                  # vitest, 33 cases
```

- `tests/api.test.ts` — 14 cases on the API client. Stubs `fetch`,
  verifies URL construction, filter encoding, path escaping, HTTP
  status propagation, bearer-token wiring.
- `tests/components/*.test.tsx` — 19 React Testing Library cases.
  jsdom environment per-file (`// @vitest-environment jsdom`); the
  api module is mocked via `vi.mock`. Each pane has tests for
  loading, error, empty, loaded, and (where applicable) drill-down
  interaction.

## Beyond the bundled dashboard

The same trace-store API the dashboard reads is open to any
HTTP-capable consumer:

- **Grafana / Datadog / Honeycomb / Tempo:** scrape `/metrics` for
  the four time series (verdict counts, ingest count, latency
  histogram, request counts), or use the
  [Python OTel bridge](../sdks/python/) to ship events directly.
- **Custom dashboards:** consume `/v1/events`, `/v1/sessions`,
  `/v1/reflections` from any client. Bearer-token auth via the
  `Authorization` header.

## Links

- [Root README](../README.md) — architecture, deployment, KPI playbook.
- [v0.1 HTTP API](../spec/v0.1/05-http-api.md) — every route this dashboard depends on.
- [ADR-006](../obsidian_vault/01_Architecture/ADR-006-Phase-5-Dashboard-MCP.md) — Phase 5 design.
- [Contributing](../CONTRIBUTING.md).
