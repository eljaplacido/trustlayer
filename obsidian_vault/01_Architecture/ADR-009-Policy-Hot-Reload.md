---
adr: 009
status: accepted
date: 2026-05-24
tags: [architecture, phase-6, policy, guardian, operations]
supersedes: []
extends: ["[[ADR-004-Cynepic-Guardian-Policy-Engine]]", "[[ADR-008-MatchSpec-Payload-Predicates]]"]
---

# ADR-009 — Policy hot-reload via file watch

## Context

`trustlayer-guardian` loads its policy once at startup from
`TRUSTLAYER_POLICY` and caches it in `CynepicGuardian` for the rest of
the process lifetime. Operators who want to change a rule today must
restart the sidecar — which drops the in-memory event store cache
(replayed from JSONL, but still a non-zero cost) and ripples through
liveness probes, dashboards, and any active SSE connection a future
transport adds.

The audit flagged this as a production-hardening blocker. A policy edit
is the most common operational change against the protocol; it should
not require a restart.

## Decision

Watch the policy file. On modification, parse the new policy; on
success, atomically swap it into the guardian; on failure, log and
keep the old policy.

### Atomic swap

`CynepicGuardian` already owns its `Policy` by value. Replace that with
an `arc_swap::ArcSwap<Policy>` (single dependency, no async runtime, no
locks on the read path). The hot path —
`CynepicGuardian::evaluate(&event)` — does one `ArcSwap::load()` which
is wait-free and amortises to a single relaxed atomic load. No
measurable change in tail latency on a microbench.

`AppState.guardian` stays `Arc<CynepicGuardian>`. The guardian itself
owns the swap; callers see no API change.

### Watcher

Use the `notify` crate's `RecommendedWatcher` (debounced via
`notify-debouncer-mini`'s shape — implemented inline with a 200 ms
debounce so we don't pull in a second crate). The watcher runs as a
detached `tokio::task` spawned from `main()`, lives for the process
lifetime, and is dropped at shutdown when the binary terminates.

Watch behaviour:

- Watch the **file**, not the parent directory. Tools that rename-then-
  unlink the old file (the standard atomic-write pattern) emit a
  `Remove` event followed by a `Create`; we handle both by re-opening
  the path on every event rather than tracking inodes.
- On any modify/create event, sleep the debounce window, then attempt
  `Policy::from_path(...)`. If the parse succeeds and the resulting
  policy's `name` matches (or is unconstrained — see below), call
  `guardian.replace_policy(new)`.
- If the parse fails, emit `tracing::warn!` with the error and
  **keep the current policy in place.** This is the same posture as
  the rest of the sidecar: failures must not take down the host.
- `name` mismatch: log at `info!` but still accept. The policy name is
  metadata, not identity. Tightening this later is non-breaking.

### Configuration

- `TRUSTLAYER_POLICY_RELOAD` env var, default `"true"`. Set to `"false"`
  to disable the watcher entirely (useful for ephemeral test sidecars).
- No new tuning knobs. The debounce, the watcher kind, and the failure
  posture are deliberate and don't need to be configurable for v0.

### Telemetry

Single `info!` line on every successful reload:
`"policy reloaded: name=<n> rules=<count>"`. Failed reloads emit a
`warn!`. That's it — operators who want richer audit can scrape the
log; richer telemetry can land in the `/metrics` follow-up
(Slice 3 item).

### What we are *not* doing

- **No SIGHUP handler.** File-watch is strictly more useful — it
  handles `kubectl rollout`, `terraform apply`, and `vim :w` equally.
- **No `POST /v1/policy` endpoint.** That would belong on a separate
  control-plane port and require auth that the slice 2 ADR-007 model
  doesn't fully cover. Re-evaluate in slice 3 if the audit pushes
  for it.
- **No per-rule rollback.** A bad policy in atomically replaces a good
  one — but only after it parses, which catches malformed JSON,
  unknown decisions, etc. Semantic mistakes (rule blocks a legitimate
  call) are an ops problem, not a hot-reload problem.
- **No hot-reload of `TRUSTLAYER_API_TOKEN`** (per ADR-007). Token
  rotation stays "stop, change env, restart" until a future ADR.

## Implementation sketch

- Crate adds:
    - `arc-swap = "1"` (always-on; tiny, no_std-friendly).
    - `notify = "6"` (gated behind `feature = "server"`).
- `core-rs/src/guardian.rs` — `policy: ArcSwap<Policy>`; new
  `replace_policy(&self, Policy)` method (`self.policy.store(Arc::new(p))`).
  `policy()` returns an `arc_swap::Guard` (or `Arc<Policy>`) instead
  of `&Policy`; cross-language test updates if any.
- `core-rs/src/policy_watch.rs` (new, `cfg(feature = "server")`) —
  `spawn_watcher(path: PathBuf, guardian: Arc<CynepicGuardian>)`.
- `core-rs/src/bin/guardian.rs` — call `spawn_watcher(...)` after
  startup unless `TRUSTLAYER_POLICY_RELOAD=false`.
- Tests:
    - Unit: `replace_policy` makes the next `evaluate()` see the new
      policy (no races on a single thread).
    - Integration (`tests/policy_watch.rs`): write a starting policy
      to a tempdir, spawn the watcher, await a debounce, write a new
      policy that flips a decision, send a `POST /v1/check`, assert
      the verdict reflects the new policy. Bad-parse case: write
      garbage, assert the old policy still serves.

## Consequences

- **+** Operational change cost drops from "restart" to "git push +
  config-sync".
- **+** The CSL becomes the actual control surface, in line with the
  ADR-004 vision and ADR-008's payload predicates.
- **+** Wait-free read path — `ArcSwap::load()` is faster than the
  current owned-by-value `&Policy` in the multi-threaded Axum hot
  path (we get rid of a clone-on-write hazard we didn't have yet,
  but would have, the first time someone tried this without atomics).
- **−** Adds `arc-swap` + `notify` to the dep tree. Both are small,
  audited, widely used. Acceptable.
- **−** Bad-policy detection happens at parse time only — a
  semantically wrong policy (blocks a legitimate tool) reloads
  cleanly. That's correct posture: we are a policy engine, not a
  policy *linter*.

## Follow-ups
- A `cynepic-guardian lint` subcommand that runs the policy against
  a corpus of recorded events and flags rules that newly fire or stop
  firing. Pairs naturally with ADR-008's payload predicates.
- `POST /v1/policy` admin endpoint behind ADR-007 auth, only if the
  file-watch story turns out to be insufficient for any real
  deployment.
- Multi-policy support (the existing `policy_name` field on
  `/v1/check` is already there in spirit; hot-reload would generalise
  to a *directory* watch).
