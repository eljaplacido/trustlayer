# Scaling & Production Deployment

TrustLayer ships two trace-store backends behind one `TraceStore` interface
([ADR-015](../obsidian_vault/01_Architecture/ADR-015-Pluggable-Trace-Store-Postgres.md)).
The HTTP contract (`spec/v0.1`) is identical on both — you choose a backend
with environment variables, not code.

## Pick a backend

| | JSONL (default) | Postgres (`postgres` feature) |
|---|---|---|
| Setup | none | a Postgres database |
| Persistence | append-only file | durable, transactional |
| Replicas | **single node** | **many** stateless replicas, one DB |
| Retention | best-effort cap + compaction | DB-side (partition / cron `DELETE`) |
| Query | linear scan in memory | indexed SQL |
| Best for | local dev, demos, small single-node | production, HA, high volume |

## JSONL backend (default)

No configuration needed. Tune two knobs:

| Env var | Default | Meaning |
|---|---|---|
| `TRUSTLAYER_EVENTS_PATH` | `events.jsonl` | File path; set to `""` for in-memory only |
| `TRUSTLAYER_EVENT_RETENTION_MAX` | unset (unbounded) | Keep ~N most-recent events; oldest evicted and the file compacted on overflow |

```bash
TRUSTLAYER_EVENTS_PATH=/var/lib/trustlayer/events.jsonl \
TRUSTLAYER_EVENT_RETENTION_MAX=1000000 \
trustlayer-guardian
```

## Postgres backend (horizontal scale)

Build with the feature and point the guardian at a database:

```bash
cargo build --release --features server,postgres --bin trustlayer-guardian

TRUSTLAYER_DATABASE_URL=postgres://user:pass@db-host:5432/trustlayer \
trustlayer-guardian
```

The schema is created automatically on first connect (idempotent). For
out-of-band schema management, apply `core-rs/migrations/0001_trace_events.sql`
yourself.

| Env var | Default | Meaning |
|---|---|---|
| `TRUSTLAYER_DATABASE_URL` | unset | `postgres://…` DSN. Set = use Postgres; empty = JSONL |
| `TRUSTLAYER_DB_MAX_CONNECTIONS` | `10` | Pool size per guardian process |

> A DSN set against a binary built **without** the `postgres` feature is a
> hard startup error — never a silent fallback to JSONL.

### Multiple replicas behind a load balancer

The guardian is stateless once the trace store is external, so scale out:

```bash
docker compose -f docker-compose.yml -f docker-compose.postgres.yml \
  up --scale guardian=3
```

Put your load balancer / reverse proxy in front of the guardian replicas.
Policy hot-reload (ADR-009) still works per-replica; mount the same policy
file (or bake it into the image) so every replica adjudicates identically.

## Security checklist (any backend)

1. **Set `TRUSTLAYER_API_TOKEN`.** When set, every route except `/healthz`
   and `/metrics` requires `Authorization: Bearer <token>` (ADR-007).
2. The guardian **refuses to bind a non-loopback address without a token.**
   Override only behind your own mTLS/proxy with `TRUSTLAYER_ALLOW_INSECURE=true`.
3. **Rate-limit ingest** with `TRUSTLAYER_INGEST_RATE_LIMIT_PER_SEC`.
4. **Terminate TLS** at a reverse proxy (nginx, Caddy, a cloud LB).
5. **Scrape `/metrics`** (Prometheus) for request, verdict, and latency
   series.

## Capacity notes

- A single guardian handles policy checks in ~100 µs (in-memory eval); the
  bottleneck under load is trace ingest, which the Postgres backend offloads
  to the database.
- For very high ingest, batch events into the `POST /v1/events` array form
  and raise `TRUSTLAYER_DB_MAX_CONNECTIONS`.
- For retention at scale on Postgres, use native partitioning by `ts` and
  drop old partitions, or a scheduled `DELETE FROM trace_events WHERE ts < …`.
