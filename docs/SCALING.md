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
| `TRUSTLAYER_EVENT_RETENTION_MAX` | unset (unbounded) | **Soft target** for live events; overflow is archived, never deleted |

```bash
TRUSTLAYER_EVENTS_PATH=/var/lib/trustlayer/events.jsonl \
TRUSTLAYER_EVENT_RETENTION_MAX=1000000 \
trustlayer-guardian
```

> **Behaviour change in Phase 8.** `TRUSTLAYER_EVENT_RETENTION_MAX` used to
> be a hard cap that *deleted* the oldest events on overflow. It is now a
> soft target: overflow is appended to `events.archive.jsonl` and the live
> log is compacted. Nothing is destroyed. See the retention floor below for
> why, and "Evidence retention and integrity" for how disk grows.

## Evidence retention and integrity (Art. 12)

EU AI Act Art. 12 requires high-risk AI system logs to be retained — at
least 6 months, 24 for biometric and law-enforcement systems — and to be
tamper-evident. Design: [ADR-017]. Protocol: `spec/v0.1/05-http-api.md` §5.12.

| Env var | Default | Meaning |
|---|---|---|
| `TRUSTLAYER_RETENTION_MIN_DAYS` | `180` | Minimum age before an event may leave the live log. `0` disables (dev only) |
| `TRUSTLAYER_INTEGRITY_CHECKPOINT_EVERY` | `1000` | Appends between chain checkpoints. `0` disables the count trigger |
| `TRUSTLAYER_INTEGRITY_CHECKPOINT_INTERVAL_SECS` | `3600` | Seconds between checkpoints. `0` disables the time trigger |
| `TRUSTLAYER_SIGNING_KEY` | unset | Ed25519 seed (hex) or path to a file holding one. Unset ⇒ unsigned checkpoints |

**The floor outranks the target.** If honouring
`TRUSTLAYER_EVENT_RETENTION_MAX` would evict an event younger than the
floor, the store keeps the event and lets the live log grow, incrementing
`trustlayer_retention_floor_blocked_total`. Destroying a six-month-old log
is a conformity failure; an oversized log is an operations problem. When
the two conflict, storage loses.

Operators of biometric or law-enforcement systems set
`TRUSTLAYER_RETENTION_MIN_DAYS=730`.

### Generating a signing key

The guardian deliberately **cannot generate keys**. A key minted by the
same process that writes the log is a key an operator can silently re-mint
after rewriting history, so generation belongs in whatever key management
you already trust.

```bash
umask 077
head -c 32 /dev/urandom | od -An -tx1 -v | tr -d ' \n' > /etc/trustlayer/signing.key
chmod 600 /etc/trustlayer/signing.key
TRUSTLAYER_SIGNING_KEY=/etc/trustlayer/signing.key trustlayer-guardian
```

The guardian refuses a group- or world-readable key file, and logs the
**public** key at startup. Publish that public key to auditors out of band
— a key handed over in the same response as the signatures it verifies
proves nothing.

`TRUSTLAYER_SIGNING_KEY` also accepts the hex seed inline, which is
convenient and worse: an environment variable is readable from
`/proc/<pid>/environ`, appears in container inspection output, and is
routinely captured by process supervisors and crash reporters. **Prefer the
file path** in anything but a scratch environment.

Anyone who can write to `events.checkpoints.jsonl` can append a checkpoint
signed with a key of their own choosing, and the server will report it as
having a valid signature — because the key travels with the signature. That
is why `verified_signatures` is documented as internal consistency, not
authenticity, and why an auditor must hold the public key independently.
Protect the checkpoint file with the same file permissions as the log.

Unsigned checkpoints are still emitted when no key is set. An unsigned
checkpoint archived off-box (WORM bucket, a commit in another repository,
mailed to an auditor) still pins the prefix; it just moves the trust
anchor to wherever that copy lives.

### Files on disk

| File | Grows | Rotation |
|---|---|---|
| `events.jsonl` | bounded by the retention target *or* the floor, whichever is larger | compacted automatically |
| `events.jsonl.chain` | **unbounded**, ~250 B/event | never rotated — the chain *is* the evidence |
| `events.archive.jsonl` | unbounded | your responsibility (see below) |
| `events.checkpoints.jsonl` | ~200 B per checkpoint | negligible |

Chain entries are retained in full and never archived: keeping them whole
means verification runs from genesis with no boundary to reconstruct, and
the append path always has an agent's head available. At ~250 B/event
that is roughly 10% of retaining the events themselves. If that matters at
your volume, use the Postgres backend.

**Archive rotation is an operator responsibility.** Move
`events.archive.jsonl` to cold storage on your own schedule. Art. 18 pushes
related documentation retention to **10 years**, so plan the archive tier
for that horizon, not for six months. Verification reads the archive back
when present, so a moved archive means archived positions are reported as
holes (`archived_in_range`) rather than verified — keep it mounted when
running an audit.

### Alerting

- `trustlayer_retention_floor_blocked_total` rising ⇒ add disk or shorten
  the floor. **Never** interpret it as data loss; it is the store refusing
  to lose data.
- `trustlayer_integrity_checkpoints_total` flat while events flow ⇒
  checkpointing is disabled or wedged.
- Run `GET /v1/integrity/verify` on a schedule and alert on `ok: false`.

[ADR-017]: ../obsidian_vault/01_Architecture/ADR-017-Evidence-Integrity-Hash-Chain-Retention.md

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
5. **Scrape `/metrics`** (Prometheus) for request, verdict, latency, and
   retention/integrity series.
6. **Set `TRUSTLAYER_SIGNING_KEY`** if you intend to claim tamper-evident
   logging, and keep the file `chmod 600`. The integrity routes disclose an
   agent's whole history, so they sit behind the bearer token.

## Capacity notes

- A single guardian handles policy checks in ~100 µs (in-memory eval); the
  bottleneck under load is trace ingest, which the Postgres backend offloads
  to the database.
- For very high ingest, batch events into the `POST /v1/events` array form
  and raise `TRUSTLAYER_DB_MAX_CONNECTIONS`.
- For retention at scale on Postgres, use native partitioning by `ts` and
  drop old partitions, or a scheduled `DELETE FROM trace_events WHERE ts < …`.
