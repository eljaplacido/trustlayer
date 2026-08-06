---
adr: 17
title: Art. 12 Evidence Integrity — Hash-Chained Log and Retention Floor
date: 2026-08-02
status: accepted
accepted: 2026-08-05
---

# ADR-017 — Art. 12 Evidence Integrity: Hash-Chained Log and Retention Floor

## Context

AI Act Art. 12 requires high-risk AI systems to automatically record events
over their lifetime, and Commission guidance on agentic systems reads that
as covering intermediate steps, not just final outputs. Two properties are
demanded of those logs that TrustLayer does not currently provide:

1. **Tamper-evidence.** A log an operator can silently edit is worth
   nothing in an assessment. `grep -i 'sha256|merkle|signature|hash_chain'`
   over `core-rs/src` returns nothing (verified 2026-08-02).
2. **Retention.** ≥6 months for high-risk systems, 24 months for biometric
   and law-enforcement systems, with Art. 18 pushing related documentation
   to 10 years. `EventStore::enforce_retention`
   (`core-rs/src/events.rs:184`) implements a *count* cap that drains the
   oldest events on overflow. A busy agent can therefore destroy evidence
   the regulation requires be kept — a live conformity defect, not a
   missing feature.

A third motivation is commercial: with no harmonised standard cited in the
OJEU, nothing confers presumption of conformity, so demonstration rests on
evidence. Evidence whose integrity can be independently checked is
categorically more valuable than evidence that cannot.

## Decision

### 1. The chain is server-side. The wire envelope does not change.

A client cannot know its position in the log, so it cannot compute a
`prev_hash`. Worse, letting clients supply chain fields would let a
compromised client choose its own position and forge continuity. Chain
state is therefore computed **by the store on append** and never appears
in `AgentTraceEvent`.

This keeps `spec/v0.1/01-wire-format.md` §1.2's closed envelope intact and
avoids a four-SDK change for a property none of the SDKs can honestly
assert. Per §1.7 the only spec change is a new HTTP route — MINOR.

### 2. Chain scope is `agent_id`, not global

Each `agent_id` gets its own independent chain.

Rationale, in priority order:

- **Evidence is assessed per AI system.** `system.yaml`'s
  `integration.agent_id` is the runtime identity of the registered system.
  A per-agent chain is exactly the unit an auditor asks about.
- **Data minimisation (P7).** Handing over system X's evidence with a
  verifiable chain must not require disclosing system Y's events. A global
  chain would make every verification a disclosure of the whole log.
- **Concurrency.** Under the Postgres backend a global chain forces every
  append through one serialised head row. Per-agent chains contend only
  within one agent's stream, which is already naturally ordered.

The cost is that "the whole store is intact" is not a single check but a
per-agent set of checks. `GET /v1/integrity/verify` returns one result per
chain, so this is a reporting detail rather than a capability loss.

### 3. Chain construction

The stored record gains fields that live alongside the event, not inside
it:

```rust
pub struct ChainEntry {
    pub seq: Seq,                 // per-agent, monotonic from 1
    pub agent_id: String,
    pub trace_id: Uuid,
    pub recorded_at: String,      // RFC 3339, store clock, not client clock
    pub prev_hash: EventHash,     // all-zero for seq == 1
    pub hash: EventHash,
}
```

`hash = SHA-256( canonical_json({ seq, agent_id, trace_id, recorded_at,
prev_hash, event }) )`.

Canonicalisation is RFC 8785 (JCS) semantics: UTF-8, lexicographically
sorted object keys, no insignificant whitespace. `serde_json::Map`
already sorts keys when the `preserve_order` feature is off (it is), so
Rust gets this for free; Python and Go verifiers use a documented
`canonical_json()` helper with matching behaviour, covered by shared
fixtures under `spec/v0.1/fixtures/integrity/`.

`recorded_at` uses the **store's** clock deliberately. A client clock is
attacker-controlled and, in a distributed deployment, skewed; the chain
attests to when the store observed the event, which is the claim it can
honestly make.

`EventHash` and `Seq` are newtypes, so a content hash cannot be assigned
where a chain hash is expected.

### 4. Integrity is a sidecar, not a reformat

`events.jsonl` keeps its current shape: one raw `AgentTraceEvent` per
line. Hermes ingest, `examples/.demo_traces.jsonl`, and every existing
reader keep working unchanged.

Chain entries are appended to a parallel `events.jsonl.chain` (one JSON
object per line). Write order is: event line + flush, then chain line +
flush.

**Crash recovery.** On open, if the chain is shorter than the event log,
the missing tail is recomputed and appended with `"recovered": true`. This
is safe because a truncated *tail* is the only shape a crash can produce.
Deletion or mutation anywhere else changes the recomputed hash and
verification fails at the offending `seq` — which is the property we want.
Recovery never rewrites an existing chain entry.

Enabling or disabling integrity therefore changes no reader and no file
format.

### 5. Checkpoints and signing

Every `TRUSTLAYER_INTEGRITY_CHECKPOINT_EVERY` events (default 1000) or
`…_CHECKPOINT_INTERVAL_SECS` (default 3600), whichever comes first, the
store writes a checkpoint to `checkpoints.jsonl`:

```json
{ "agent_id": "...", "seq": 41000, "head_hash": "...",
  "created_at": "...", "public_key": "...", "signature": "..." }
```

The head hash commits to every prior event in that chain, so a checkpoint
is a compact attestation of the whole prefix. Signing uses Ed25519
(`ed25519-dalek`) when `TRUSTLAYER_SIGNING_KEY` is configured (file path
or hex); unsigned checkpoints are still emitted otherwise, since an
externally-archived unsigned checkpoint still pins the prefix.

Merkle inclusion proofs are **deferred**. Proving one event's membership
by chain replay is O(n) but n is per-agent and current volumes make this
irrelevant. Revisit in Phase 9 if a customer needs sublinear proofs.

### 6. Routes (additive, MINOR per spec §1.7)

- `GET /v1/integrity/checkpoints?agent_id=…` — checkpoints plus the
  public key, so an auditor can verify offline.
- `GET /v1/integrity/verify?agent_id=…` — recompute and report
  `{ ok, chains: [{ agent_id, verified_through_seq, first_bad_seq,
  reason }] }`.
- `GET /v1/events` gains an optional `after_seq` cursor. This is required
  by ADR-018's streaming evidence engine and is only well-defined because
  `seq` now exists — the two decisions are deliberately co-designed.
- `GET /v1/events/chained?agent_id=…&after_seq=…&limit=…` — events with
  their `seq` and `hash` **alongside** each event, never inside it.

*Revised during implementation (2026-08-05).* This originally put the
chain metadata into the `GET /v1/events` response, which would have made
one route return two different body shapes depending on whether a query
parameter was present. Every client would then have to handle both, and
the shipped dashboard and four SDKs would break the moment the envelope
form was returned. A dedicated `/v1/events/chained` keeps one shape per
route and leaves the v0.1 array response untouched.

`after_seq` requires `agent_id` and returns `400` without it. Chain
positions are scoped per agent (§2), so a cursor with no agent names no
position; silently returning a differently-scoped page would make a
paging evidence consumer skip events without knowing it.

A backend that maintains no chain answers **`501`, not `500`**: the
request was well-formed and the server is healthy, it simply cannot make
the attestation. A `500` reads as a transient fault worth retrying, when
in fact the deployment must be reconfigured.

The normative definition of all of this is `spec/v0.1/05-http-api.md`
§5.12, including the hash and signature preimages, so an auditor can
verify without running this implementation.

### 7. Retention: a floor that outranks the cap

`TRUSTLAYER_EVENT_RETENTION_MAX` keeps its name but changes meaning from
a hard cap to a **soft target**. A new
`TRUSTLAYER_RETENTION_MIN_DAYS` (default **180**; operators of biometric
or law-enforcement systems set 730) defines a floor.

Eviction rules:

1. An event younger than the floor is **never** evictable.
2. When the soft target is exceeded, evictable events are **archived**,
   not deleted: they are appended to a single `events.archive.jsonl`.

   *Revised during implementation (2026-08-02).* This originally
   specified numbered segments carrying their chain segment with them.
   Two changes, both discovered while building it:

   - **One archive file, not numbered segments.** A segment name would
     have to encode a `seq` range, but `seq` is per-`agent_id` (§2) while
     an evicted prefix spans agents, so no single range names a segment
     correctly. A single append-only archive avoids the problem and makes
     cross-boundary verification a plain lookup.
   - **Chain entries are retained in full, never archived.** The chain
     *is* the tamper-evidence record. Keeping it whole means the append
     path always has an agent's head available without reading the
     archive, and verification runs from genesis with no boundary to
     reconstruct. The cost is ~250 bytes per event held in memory —
     roughly 10% of retaining the events themselves — documented on
     `EventStore`. Deployments where that matters use the `postgres`
     backend.

   Verification reads archived events back from `events.archive.jsonl`,
   so an event moved out of the live log is still covered by the chain
   that commits to it (test:
   `archived_events_still_verify_against_the_chain`).
3. If the target is exceeded and nothing is evictable, the store keeps
   growing and emits a loud error plus metrics
   (`trustlayer_retention_floor_blocked_total`,
   `trustlayer_retention_archived_total`). Disk pressure becomes a visible
   operator problem; evidence loss never becomes a silent one.

`with_retention(Some(n))` gains a doc note that it is now a target, and a
companion `with_retention_floor(Duration)`.

This is a behaviour change for existing `TRUSTLAYER_EVENT_RETENTION_MAX`
users — archiving instead of deleting — and is strictly safer. It is
called out in `CHANGELOG.md` and `docs/SCALING.md`.

### 7b. Checkpoint signing (implementation notes, 2026-08-05)

Two deviations from §5 as written, both recorded rather than quietly
absorbed:

- **`ed25519-dalek` is a non-optional dependency**, not gated behind the
  `server` feature. Checkpointing is a property of the *store*, which is
  not server-gated; cfg-gating the signature would give one store two
  checkpoint formats depending on build flags, and a checkpoint whose
  shape depends on how the binary was compiled is not an audit artifact.
- **Key generation is deliberately not implemented.** A key minted by
  the same process that writes the log is a key an operator can silently
  re-mint after rewriting history. Generation belongs in the deployment's
  existing key management; `docs/SCALING.md` carries the one-liner. The
  loader refuses a group- or world-readable key file, because a signing
  key anyone on the box can read provides no assurance and failing loudly
  beats emitting checkpoints that only look authoritative.

A checkpoint is also written on graceful shutdown. An agent that stops
900 appends into a 1000-append interval would otherwise leave its most
recent — often most interesting — evidence uncommitted.

### 8. Postgres parity

`trace_events` gains `chain_seq BIGINT`, `prev_hash BYTEA`, `hash BYTEA`,
`recorded_at TIMESTAMPTZ`, with a `chain_heads(agent_id, seq, head_hash)`
table. Appends take `SELECT … FOR UPDATE` on the agent's head row inside
the insert transaction. `append_batch` computes the whole batch's chain
under one lock acquisition, so batching amortises the serialisation cost.
Migration `0002_integrity_chain.sql`; existing rows are backfilled with
`chain_seq NULL` and reported by `verify` as `unchained` — honest about
what predates the feature rather than fabricating a chain over it.

*Deferred during implementation (2026-08-05).* Not built. The Postgres
backend answers every integrity route with `501`, which is accurate: it
maintains no chain. The reason for deferring rather than shipping it is
that CI has no database, so the SQL above could only be merged untested —
and untested SQL sitting behind an Art. 12 tamper-evidence claim is worse
than a backend that says plainly it cannot attest. Deployments needing
both horizontal scale and Art. 12 integrity should run the JSONL backend
until this lands; the gap is stated in `docs/CURRENT_STATUS.md` and
`CHANGELOG.md` rather than left for a user to discover.

## Consequences

- **No wire-format change.** The v0.1 envelope, all four SDKs, and every
  existing JSONL reader are untouched. Only additive routes and response
  fields.
- Integrity is **opt-out-able but on by default** for file-backed stores
  (`TRUSTLAYER_INTEGRITY=off` disables). In-memory stores skip it.
- Per-append cost is one SHA-256 over a serialisation the store already
  produces for the JSONL write — budgeted at ≤50 µs, asserted by a
  benchmark-style test.
- New Rust dependencies: `sha2` and (optionally, behind the existing
  `server` feature) `ed25519-dalek`. Both are small, widely audited, and
  pass `cargo audit`.
- Events predating the feature are reported as `unchained`, never as
  verified.
- Archive files accumulate. `docs/SCALING.md` documents cold-storage
  rotation as an operator responsibility, with the 10-year Art. 18
  horizon called out.
- **Limits stated in-product:** the chain proves the log has not been
  altered *since the store recorded it*. It says nothing about whether the
  emitting agent told the truth. Attestation of the emitter is out of
  scope and is not implied anywhere in the UI or the audit package.
