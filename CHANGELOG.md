# Changelog

All notable changes to the TrustLayer protocol and reference
implementations are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (Phase 8 — EU AI Act compliance depth)

**Slice 8.4 — the evaluator layer (ADR-020, gap G11).** New top-level package
`evaluators/` (`trustlayer_eval`), letting an operator point their own model —
local or cloud — at their traces and ask about them.
- **Pluggable providers**, each spoken to over its own HTTP API with no vendored
  SDK: `null` (the default — refuses every call, so an unconfigured install
  never makes an unexpected network request), `ollama`, `agentcenter`,
  `openai_compat`, and `anthropic`. Selected by `TRUSTLAYER_EVAL_PROVIDER`.
  Residency is **declared by config, never inferred from a URL**; unset is
  `UNKNOWN`, which the egress policy treats as third-country.
- **Grounding contract.** Every finding cites `trace_id`s that must exist in the
  evidence window supplied to the model. A finding that fails is rejected, not
  repaired — one retry carrying the rejection reason, then it is dropped and
  counted in `ungrounded_rejected`. `cited_trace_ids` has `min_length=1` at the
  type level, so an uncited finding is not representable. No configuration
  disables any of this.
- **Egress policy and redaction.** Personal or special-category data bound for a
  third-country provider is refused unless `system.yaml` carries an
  `egress_override` with both a safeguard reference and a named approver — an
  auditable decision rather than a flag. Raw prompts and completions are opt-in;
  redaction records field paths and counts, never values.
- **Seven evaluator roles** — the six in ADR-020 §4 plus `insight_advisor` for
  the dashboard. Prompts are versioned files, hashed into every run record, so a
  prompt edit is visible in provenance.
- **`EvaluatorRun` records** as JSONL under `compliance/runs/`, pinning the
  evidence query *and* a hash of its result so a past finding stays re-checkable
  against a log that has since grown. The hash is order-independent.
- **Advisor pane** in the dashboard: states the provider, model, and residency
  before the operator types, renders per-finding citations, and reports how many
  findings were suppressed as ungrounded.
- **Self-governed (P8).** Evaluator calls emit `AgentTraceEvent`s and are
  policy-checked before dispatch. The guardian client here is `fail_open=False`
  — unlike the SDK bridges, an unreachable guardian refuses the call instead of
  defaulting to PASS, because this is the caller whose purpose is that
  distinction. Emission failures are still logged and swallowed.
- **Cost bounded by construction.** The control judge sees only `INDETERMINATE`
  controls, asserted by a test, so a fan-out regression fails CI rather than a
  customer's bill.
- `./scripts/verify.sh evaluators`, a matching `verify.sh test` block, and a CI
  job. `pip-audit` now covers `evaluators/requirements-release.txt`.
- New `evaluators` agent skill with refusal conditions (ADR-023 §7 symlink).

### Changed

- **`skills/hermes/llm_reflector.py` refactored onto the evaluator provider
  layer** (ADR-020). Hermes no longer carries its own copy of the Ollama wire
  format. Its ADR-013 public API — `summarise_session`, `synthesise`,
  `reflect_narrative`, `last_error`, and the constructor keywords — is
  unchanged, and its 57 existing tests pass **unmodified**; that was the stated
  acceptance test for the refactor.

### Fixed

- **Python SDK emitted `"parent_trace_id": null` for events that had no parent**,
  which every v0.1 collector built before the field rejects outright: the
  envelope is closed (spec §1.2), so an unknown top-level key is a 422 for the
  whole event. The Rust core (`skip_serializing_if`), Go (`omitempty`), and
  TypeScript (optional) all omit it and each states that an emitter which does
  not set the field produces byte-identical v0.1 output; the Python SDK was the
  one that did not keep that promise. Found by a running v0.1 guardian returning
  422 for every event this SDK sent. Go asserted the property in
  `TestParentTraceIDIsOmittedWhenUnset`; the Python suite only ever tested the
  old-wire/new-parser direction, so nothing failed when the bytes changed —
  `test_unset_parent_trace_id_is_not_serialised` now covers it.
- `ruff` is unpinned across the repository and 0.16 stopped reporting `E402`
  for imports gated behind `pytest.importorskip` while 0.15 still does, so the
  Python SDK's lint gate passed or failed depending on which version the machine
  happened to have. Pinned the behaviour with a `per-file-ignores` entry.
- `CONTRIBUTING.md`'s setup instructions could not produce a green
  `verify.sh test`: nothing installed `types-PyYAML`, which Hermes'
  `mypy --strict` gate needs. CI installed it explicitly; the documented local
  path did not.

**Slice 8.0 — event-type lockstep (gap G0).** `compliance/schemas/control.schema.json`
enumerated seven event types while `core-rs` `EventType` had nine, so loading
`article-50-v1.yaml` raised `ValidationError` — the Art. 50 control catalog was
dead code. Fixed across the schema, `spec/v0.1/01-wire-format.md` §1.3 and
§2 ("seven" → "nine"), and `docs/SCHEMA.md`, with payload contracts added for
`DISCLOSURE_SHOWN` and `CONTENT_MARKED`.
- Regression tests: `test_event_type_lockstep.py` parses the Rust enum as the
  source of truth and asserts the spec prose and compliance schema agree;
  `test_control_catalogs.py` loads **every** catalog in `compliance/controls/`.
- `spec/v0.1/fixtures/` is now read by all five implementations (Rust core plus
  the Python, TypeScript and Go SDKs), each asserting strict-envelope parse,
  field preservation, fixed-point round-trip, and rejection of an unknown
  field. A fixture read only by the language that produced it proves nothing
  about interoperability — that omission is what produced G0.

**Slice 8.1 — Art. 12 evidence integrity (ADR-017).**
- **Tamper-evident hash chain**, scoped per `agent_id`, over a canonical
  event serialisation. `Seq` and `EventHash` newtypes make it a type error to
  put a chain hash where a content hash belongs. `recorded_at` is the store's
  clock, never the client's `timestamp`.
- **Signed checkpoints.** Ed25519 commitments to a chain head, written to
  `events.checkpoints.jsonl` every `TRUSTLAYER_INTEGRITY_CHECKPOINT_EVERY`
  appends or `…_INTERVAL_SECS` seconds, plus one on graceful shutdown.
  `TRUSTLAYER_SIGNING_KEY` takes a hex seed or a `chmod 600` file. Key
  *generation* is deliberately not implemented — see `docs/SCALING.md`.
  Unsigned checkpoints are still emitted; archived off-box they still pin the
  prefix.
- **New routes** (additive, MINOR per spec §1.7; normative in
  `spec/v0.1/05-http-api.md` §5.12): `GET /v1/events/chained`,
  `GET /v1/integrity/verify`, `GET /v1/integrity/checkpoints`, and an
  `after_seq` cursor on `GET /v1/events`. A backend with no chain answers
  `501`, not `500` — it is healthy, it just cannot attest.
- **New metrics**: `trustlayer_retention_live_events`,
  `trustlayer_retention_archived_total`,
  `trustlayer_retention_floor_blocked_total`,
  `trustlayer_integrity_checkpoints_total`,
  `trustlayer_integrity_chains_total`.

**Remediation guidance engine (ADR-024).** Scans reported gaps; they now come
with the work that closes them.
- `compliance/remediation/eu-ai-act-v1.yaml` — 21 guidance entries covering
  every check the readiness scanner can emit, plus the EU AI Act control
  catalog. Guidance is **data, not code**: it is validated against
  `remediation.schema.json`, so counsel can review it and a regulation change
  does not require an engineer.
- Each action is classified **technical / documentation / process**. This is
  the point of the feature — the most common way a gap is closed without being
  closed is fixing it in the wrong dimension, and a score cannot tell the
  difference.
- `python -m compliance.src.remediation --readiness r.json [--evidence e.json]`
  emits an ordered plan (Markdown or JSON), sequenced blocking → priority →
  effort, with effort ascending *within* a tier so quick wins cannot jump ahead
  of a blocking gap.
- Every entry carries a legal basis, an owner role, and a verification step —
  all three enforced by tests against the shipped catalog. Another test parses
  `readiness_scanner.py` for `check_id=` literals, so a check cannot ship
  without guidance.
- Findings with no authored guidance are reported as `unguided`, never
  dropped: a shorter plan is not a smaller problem.
- Proposal-only. `artifacts` are suggested paths; nothing is written to a
  user's project (design principle P4).
- `--fail-on-blocking` gates CI. Exit 1 while blocking items remain, 2 when the
  requested framework has no catalog.

**Slice 8.2 — evidence query v2 and assurance tiers (ADR-018, closes G3/G4/G9).**

The report used to answer `satisfied: bool` from a presence check, which
conflated "we wrote it down" with "the runtime proves it" — gap G4, and the
reason two dogfooded projects both scored 100%.

- **Assurance tiers** replace the boolean: `unknown` → `declared` → `evidenced`
  → `verified`. **They are never blended into one number.** There is no
  `satisfaction_rate_percent` in the report and no way to print one; that
  absence is the feature. `--min-assurance evidenced` gates CI on runtime
  evidence rather than declarations.
  - `verified` requires the query to pass, the events to sit in a chain that
    verifies, **and** an independent confirmation. Without the third condition
    it would mean "the system said so and its log was not edited", which is not
    independent of the party being assessed.
  - A **failed** integrity chain pulls a control *down* to `declared`. A broken
    chain does not merely withhold support; it undermines the evidence.
  - A pass over an empty population cannot reach `evidenced`.
- **Four new predicate forms** (G3): `coverage` (the proportion an auditor
  actually asks for), `sequence` (was *every* risky call gated?), `absence`
  (negative assertions), `resolution` (did escalations actually close, and in
  time?). Coverage over an empty population is `INDETERMINATE`, never 100% — a
  system that emitted no risky calls would otherwise look perfectly governed.
- **Role and applicability filtering** (G9). Controls carry `applies_to_roles`,
  `risk_classes`, `applies_from` and `legal_ref`. `article-50-v1.yaml` now
  encodes the Digital Omnibus timeline as *data*: Art. 50(1) live from
  2026-08-02, Art. 50(2) marking deferred to 2026-12-02, and Art. 50(3)/(4)
  marked as **deployer** duties so a provider is no longer scored against them.
- **`payload_filters` is deprecated** but unchanged in meaning; it lowers to
  `where` so there is exactly one code path and a v1 catalog cannot drift from
  a v2 one. Removal target: v0.3.
- `scope` and `window` are in the schema but not yet honoured, and are
  therefore **rejected by validation** rather than ignored. A query silently
  evaluated over a wider set than asked for answers a question nobody posed.

**Predicate operators, in both engines (spec §4.3.1).** Evidence queries needed
"any of these tools" and "longer than this", which deep equality cannot say.
Adding them only to the evidence side would have recreated G0 one layer up — a
control asserting it is enforced by a rule that matches different events — so
they landed in `core-rs/src/predicate.rs` and `compliance/src/predicates.py`
together, behind one normative spec section and one shared conformance table
(`spec/v0.1/fixtures/predicate-cases.json`) that both suites run.
- `$eq $ne $in $nin $gt $gte $lt $lte $exists $contains $prefix $suffix`.
- An object is an operator expression only when **every** key is `$`-prefixed,
  so no existing policy changes meaning. A *mixed* object is rejected at load,
  because `{"$gt": 5, "unit": "ms"}` would otherwise become a predicate that
  can never match — and a rule that never fires is one nobody notices is broken.
- No regex operator, deliberately: a regex over a large event stream on behalf
  of a user-supplied catalog is a denial-of-service primitive.
- `Policy::from_json` now validates predicates and returns
  `Error::InvalidPolicyRule`. The guardian hot path stays a plain boolean.

**Schema gaps found by dogfooding.** `system.schema.json` gains
`agent_trace_data`, `model_io_content` and `credentials_and_secrets` data
classes — an agentic system's most sensitive store is usually its own
telemetry, and the enum had nowhere honest to put it. Additive, so no existing
registry breaks.

**Slice 8.3 (partial) — agentic trust model event types (ADR-019).** Two new
event types, additive and MINOR per spec §1.7. The v0.1 set is now **eleven**.

- **`HUMAN_DECISION`** (spec §2.10) closes the Art. 14 loop. `HUMAN_ESCALATION`
  said a human was asked; nothing said what they answered, so oversight could
  only ever be a presence check. This was not optional to defer: Slice 8.2
  shipped a `resolution` predicate pairing escalations with decisions, and
  until now no SDK could emit the second half — the predicate was expressible
  and unusable.
  - `escalation_trace_id` is REQUIRED rather than inferred from ordering.
    Ordering looks adequate in a test and breaks under concurrency, which is
    the regime agentic systems run in.
  - `reviewer_id` is REQUIRED: Art. 14(4) assigns oversight to identified
    natural persons, and emitters SHOULD use a stable pseudonym rather than a
    name. Absence of a decision is **not** approval.
- **`HARNESS_SNAPSHOT`** (spec §2.11) fingerprints the configuration a session
  ran under — model bindings, tool inventory with `trust_tier`, MCP servers,
  prompt hashes, autonomy limits. An agent's behaviour is set as much by its
  harness as by its code, and none of that appears in a conventional change
  log, so Art. 43 substantial-modification detection had nothing to diff.
  - **Prompt hashes, never prompt text.** A system prompt is a trade secret and
    often carries customer data; a hash proves "this changed" without
    disclosing what it says. A cross-language test enforces this against the
    committed fixture, because fixtures get copied by integrators.
  - Not attestation: it records what the emitter says it was configured with.

Landed across every layer in one commit per the lockstep rule G0 taught —
`core-rs`, all four SDKs, `control.schema.json`, spec §1.3/§2/§6,
`docs/SCHEMA.md`, two Go-generated fixtures, and cross-language assertions.

- **`parent_trace_id`** (spec §1.3) — the only envelope change in Phase 8, and
  the field every derived workflow metric depends on. Optional, and **omitted
  from the wire when unset**, so v0.1 emitters produce byte-identical output;
  the canonical fixture is unchanged byte-for-byte and a test enforces it.
  - Causality is client-side knowledge: only the agent knows which call spawned
    which, and inferring it from arrival order breaks under concurrency —
    exactly the regime agentic systems run in. Emitters MUST NOT invent a value.
  - **Absent means *unknown*, never *no parent*.** Derived metrics report
    `unknown` rather than assume a flat structure; a fabricated zero looks like
    an answer.
  - A dangling reference is not an error — events arrive out of order and a
    parent may lie outside the queried window.

**Still open in ADR-019**, stated rather than left to be discovered: the derived
workflow graph and untrusted-to-privileged flow detection. The `trust_tier`
vocabulary ships in the wire format; the detector that consumes it does not
exist yet.

### Changed (Phase 8)
- **`TRUSTLAYER_EVENT_RETENTION_MAX` no longer deletes.** It was a hard cap
  that evicted the oldest events on overflow, which could destroy logs Art. 12
  requires be kept for six months. It is now a *soft target*: overflow is
  appended to `events.archive.jsonl` and the live log compacted. Strictly
  safer, and no configuration change is required.
- **New retention floor.** `TRUSTLAYER_RETENTION_MIN_DAYS` (default `180`;
  set `730` for biometric / law-enforcement systems) defines a minimum age
  before an event may leave the live log. **It outranks the count target**: if
  honouring the target would evict a younger event, the store keeps it, lets
  the live log grow, and increments
  `trustlayer_retention_floor_blocked_total`. Destroying evidence is a
  conformity failure; an oversized log is an operations problem. `0` disables
  the floor and logs a warning.
- `GET /v1/events` accepts `after_seq`. Its response shape is **unchanged** —
  chain metadata is served from `/v1/events/chained` so no route returns two
  different bodies.
- **Agent skills are now single-source.** `.claude/skills/<name>` are symlinks
  to the canonical `.opencode/skills/<name>` so both harnesses read one file
  and cannot drift (ADR-023 §7). Every skill states its refusal conditions —
  load-bearing, because they are what stops an agent raising a compliance score
  by loosening a check instead of closing the gap.
- The compliance package gains a mypy gate (`disallow_untyped_defs`,
  `disallow_any_generics`, `warn_return_any`, `no_implicit_optional`,
  `strict_equality`). `scripts/verify.sh` now passes `--config-file`
  explicitly: invoked from the repo root, mypy would otherwise find no config
  and run with defaults — a gate switched off without failing.

### Added (community health)

Files a contributor arriving cold looks for and, until now, did not find. The
substance was already written — `CONTRIBUTING.md`, `AGENTS.md`,
`docs/SECURITY.md`, `docs/RELEASE.md`, a specified wire format and a
conformance suite. What was missing was the standard shape that makes it
findable.

- **`CODE_OF_CONDUCT.md`** — Contributor Covenant 2.1. Enforcement routes
  through GitHub private reporting rather than a published address, matching
  `docs/SECURITY.md` so there is one channel to keep working rather than two to
  keep current.
- **Issue templates** for bugs, features and wire-format changes. The
  wire-format form states the obligation up front — five implementations, a
  spec update and a fixture in one change set — because that is the cost
  `CONTRIBUTING.md` asks proposers to weigh before opening a pull request, and
  a form is where they will actually read it. The bug form asks which layer and
  which version first: in a polyglot repository that is the difference between
  a reproducible report and a guess. All of them say not to paste real traces.
- **A pull-request template** carrying the `CONTRIBUTING.md` checklist. A
  checklist nobody sees at the moment of the pull request is a checklist that
  does not run. It asks for the `verify.sh` transcript rather than an assertion
  that it passed — those are different claims, and only one of them is
  checkable.
- **`dependabot.yml`** covering all ten manifests: cargo, gomod, two npm, five
  pip, Docker, and Actions itself. Dependabot is per-manifest, so an ecosystem
  with no entry is simply never checked — the same shape of gap as the audit
  below.
- **README** gains CI, licence, wire-format and SDK badges, a Security section
  pointing at the private reporting route, and concrete suggestions for a first
  contribution. A new SDK is the most self-contained of them: the spec is
  precise enough to implement against and every event type now has a fixture,
  so conformance is largely a matter of passing a suite that already exists.
- **`verify.sh security` now says what is missing.** `cargo-audit` and
  `pip-audit` ship with no language toolchain, so a fresh clone did not have
  them and the documented command failed with a bare `No module named
  pip_audit`. It now checks for both up front and prints the install line, and
  `CONTRIBUTING.md` lists them. It still *fails* — a missing auditor is not a
  passing audit, which is the same shape as everything in the audit below.
- **`test_repo_invariants.py` checks every relative markdown link resolves**
  across all 123 documentation files, and that the community-health files are
  present. Documentation is most of what this repository ships, and a link that
  404s is how it rots first: silently, and only for the reader who followed it.

### Fixed (Phase 8 — gate audit)

An audit of the gates against what the documentation claims they cover. Every
item below is a check that did not cover what a reader would reasonably assume
it covered; none required a behaviour change to fix.

- **Conformance fixtures now exist for all eleven event types**, up from six.
  `AGENT_END`, `HUMAN_ESCALATION`, `LLM_CALL`, `POLICY_CHECK` and `TOOL_RESULT`
  had none, so the strict-envelope, field-preservation, round-trip and
  unknown-field-rejection guarantees that all five implementations assert by
  globbing that directory were being asserted for six of eleven.
  `event-human-escalation-go.json` is pinned to the `escalation_trace_id` the
  human-decision fixture already carried, and a test asserts the pair stays
  joined — Art. 14 effectiveness is measured across that gap.
- **The SDK enums are now in the lockstep test.** The G0 fix pinned the Rust
  `EventType` to the spec prose and to `control.schema.json`, which meant a
  twelfth event type added to those three places passed while the Python,
  TypeScript and Go SDKs stayed behind. They were covered only indirectly, by
  fixture round-trip — which catches a missing type only if someone also
  remembered to add a fixture. Both holes are now asserted directly, and a
  further test requires every event type to be carried by some fixture.
- **`cargo check` now runs for the `python` and `postgres` features.** Both are
  shipped, documented code paths (ADR-014 pyo3, ADR-015 Postgres) that no CI or
  local step compiled. A signature change in `guardian.rs` or `events.rs` broke
  them silently, and the first person to find out was whoever ran maturin or
  pointed `TRUSTLAYER_DATABASE_URL` at a live database.
- **Hermes has a typing gate.** It was the only Python package with no mypy at
  all — and the package ADR-020 refactors `LLMReflector` onto. It already
  passed `--strict` with no findings, so this records the standard the code
  meets rather than imposing a new one. CI also gains the `ruff format --check`
  step it was missing, which `verify.sh` already ran.
- **The compliance package moves to `strict = true`.** A hand-picked flag list
  left the code carrying the EU AI Act claims typed more loosely than the SDKs.
  It too already passed `--strict`.
- **Four of the five agent skills state refusal conditions.** Both
  `.opencode/skills/README.md` and this changelog called them load-bearing —
  "what stops an agent raising a compliance score by loosening a check instead
  of closing the gap" — while only `compliance` had any. scout, plan, build and
  review were twelve lines each. `test_repo_invariants.py` now enforces the
  claim rather than restating it.
- **The `build` skill was gitignored.** Writing the above turned up a third
  instance of the same bug: the Python-artifact rule `build/` is unanchored, so
  it matched `.opencode/skills/build/` too. `SKILL.md` was already tracked and
  so kept working for everyone who had it, while `git add` on that path failed
  and any *new* file in the directory would have been dropped without a word.
  Negated next to the rule that catches it, and asserted with `git check-ignore
  --no-index` — without `--no-index` the check stays silent for tracked files,
  which is exactly what hid it.

### Fixed (Phase 8)
- **The skill symlinks were never actually shared.** `.gitignore` excluded all
  of `.claude/`, so the ADR-023 §7 symlinks existed only on the machine that
  created them — a fresh clone got the OpenCode copies and nothing for Claude
  Code, which is precisely the drift the ADR exists to prevent. `.claude/*` is
  now ignored with `!.claude/skills/` re-included (git cannot re-include a path
  inside an excluded *directory*, hence the glob). Machine-local settings stay
  untracked, and a test asserts it.
- **Metrics pane under-reported requests per route.**
  `trustlayer_requests_total` is labelled `{route,status}`, so one route yields
  one sample per status code. `MetricsPane` *assigned* rather than summed, so a
  route serving both `200` and `429` displayed only the last sample parsed and
  the bars silently disagreed with the total printed above them.
- **`GET /v1/integrity/verify` now documents what it attests.** It verifies the
  chain the running process holds and deliberately does not re-read the store
  per request — that would make an auditor's request a denial-of-service lever
  against ingest. The consequence (an edit made behind a live server is caught
  on the next cold read, not by that server) was encoded in the Rust tests as
  `editing_the_event_log_is_detected_on_reopen`, but stated nowhere an operator
  or auditor would look. Now normative in `spec/v0.1/05-http-api.md` §5.12.3
  and in the README.
- `compliance/tests/test_repo_invariants.py` guards the repo-wide claims no
  single package owns: skill symlinks are tracked as symlinks (mode `120000`),
  machine-local `.claude` files are not tracked, every ADR declares a status,
  the Phase 8 ADR index is complete, the spelled-out event-type count in the
  spec matches the Rust enum, every committed fixture is documented, and the
  shared predicate table is read by *both* the Rust and Python suites.

### Deferred (Phase 8)
- **Postgres integrity parity.** The `postgres` backend answers the integrity
  routes with `501` rather than a chain it does not maintain. Shipping
  untested SQL behind an Art. 12 tamper-evidence claim would be worse than
  saying plainly that it is not implemented; CI has no database.
- Merkle inclusion proofs (chain replay suffices at current volumes) and
  runtime trust-envelope enforcement — both Phase 9.

### Added (Phase 6 — Production hardening, ADR-015)
- **Pluggable trace store.** New object-safe `TraceStore` trait; the HTTP
  sidecar now holds `Arc<dyn TraceStore>` so the same routes serve any
  backend. No wire-format or HTTP-API change.
- **Postgres backend** (`postgres` build feature). Durable, horizontally
  scalable: run N stateless guardian replicas against one database
  (`docker compose -f docker-compose.yml -f docker-compose.postgres.yml up
  --scale guardian=3`). Schema auto-created on connect;
  `core-rs/migrations/0001_trace_events.sql` documents the DDL. Selected at
  runtime with `TRUSTLAYER_DATABASE_URL`. Verified end-to-end against a live
  Postgres (append/dedup/filter/limit/sessions/get-session).
- **JSONL retention.** `TRUSTLAYER_EVENT_RETENTION_MAX` caps the log and
  compacts the file on overflow (amortised O(1) appends). Unset = unbounded
  (unchanged default).
- **Secure-by-default bind guard.** The guardian refuses to start on a
  non-loopback address without `TRUSTLAYER_API_TOKEN`, unless
  `TRUSTLAYER_ALLOW_INSECURE=true`. Loopback dev stays zero-config.
- `docs/SCALING.md` — operator guide for backend choice, replicas, retention,
  and the security checklist.

### Changed
- Docker image builds with `--features server,postgres` by default (one image
  serves either backend); override with `--build-arg FEATURES=server`.
- `.gitignore` now covers the default `events.jsonl` runtime log.

### Tests
- Rust: **88** default (+2 JSONL retention) and **+3** opt-in Postgres
  integration tests (`TRUSTLAYER_TEST_DATABASE_URL`), all green. `cargo fmt`
  + `clippy -D warnings` clean for both `server` and `server,postgres`.
- Dashboard visually verified end-to-end against the live API (Playwright):
  all four panes render real data, zero console errors.

## [0.1.0] — 2026-05-30

### Added (Phase 1 — Specifications & Scaffolding)
- Monorepo structure (`core-rs`, `sdks`, `skills`, `obsidian_vault`).
- Canonical trace schema (`docs/SCHEMA.md`) with `AgentTraceEvent`
  envelope and seven event types.
- Architectural blueprint (`docs/ARCHITECTURE.md`).
- Agentic guidelines (`CLAUDE.md`).

### Added (Phase 2 — Developer Wedge)
- Python SDK (`trustlayer-sdk`): Pydantic v2 schema, httpx client,
  `Tracer` with `tool_call` context manager and `instrument_tool`
  decorator. 27 pytest cases.
- TypeScript SDK (`@trustlayer/sdk`): Zod schema, fetch client,
  `Tracer`, `wrapTool` helper. 27 vitest cases.
- Both SDKs swallow transport failures so instrumentation cannot break
  the host agent.
- ADR-001 — SDK Wedge.

### Added (Phase 3 — Hermes Memory Agent)
- Schema-typed ingestion accepting `AgentTraceEvent`, `dict`, and
  JSON-string inputs.
- Per-session Markdown notes in `obsidian_vault/03_Memory_Traces/`.
- `DeterministicReflector` with structural summaries.
- `ReflectionEngine` Protocol for future LLM-backed reflection.
- CLI: `python -m hermes.cli --vault <vault> ingest <jsonl> [--reflect]`.
- 18 pytest cases. ADR-002.

### Added (Phase 3.5 — Token / Memory Optimisation)
- Payload truncation (`max_payload_chars`, default 2 000).
- JSONL sidecar persistence (`<vault>/.hermes_state/`).
- Bounded LRU cache (`max_cached_sessions`, default 256).
- `SessionSummary.compact_text()` for LLM-friendly prompts.
- 15 new pytest cases (33 Hermes tests total). ADR-003.

### Added (Phase 4 — Rust Core)
- Rust serde mirror of `AgentTraceEvent` with `deny_unknown_fields`.
- CSL policy parser with named rules and `MatchSpec` selectors.
- `cynepic-guardian` evaluator: ordered rule walk, first-match-wins,
  Cynefin-aware CHAOTIC default escalation.
- Axum HTTP sidecar (`trustlayer-guardian`):
  `POST /v1/check`, `GET /healthz`, graceful shutdown.
- Python `GuardianClient` with fail-open default. 8 new pytest cases
  (23 Python tests total).
- Default policy (`core-rs/policies/default.json`).
- 19 Rust tests (15 unit + 4 cross-language). ADR-004.

### Added (Phase 4.5 — SDK Guardian Parity)
- TypeScript `GuardianClient` + `Tracer.check()` (11 new vitest cases,
  27 TypeScript tests total).
- Python `Tracer.check()` helper combining guardian call + `POLICY_CHECK`
  event. 4 new pytest cases (27 Python tests total).

### Added (Phase 4.6 — Code-Graph Sense-Making)
- `skills/hermes/code_graph.py` — `CodeGraphImporter` reads generic
  JSON graph and emits Obsidian notes into `06_Code_Graph/`.
- CLI: `python -m hermes.cli import-code-graph --gitnexus-root <path>`.
- 11 new pytest cases (44 Hermes tests total). ADR-005.

### Added (Phase 5 — Dashboard & MCP Server)
- Trace-store API on `trustlayer-guardian`:
  `POST /v1/events`, `GET /v1/events` (filtered),
  `GET /v1/sessions`, `GET /v1/sessions/:agent/:session`,
  `GET /v1/reflections`, `GET /v1/reflections/:name`.
- `EventStore`: append-only JSONL, idempotent on `trace_id`,
  replay on open, permissive CORS.
- Dashboard (React + Vite, 4 panes): Traces, Sessions, Reflections,
  Policy. Each pane has loading/error/empty states.
- MCP server (Python, FastMCP stdio): 5 tools wrapping SDK + Guardian +
  Hermes. Transport-free handlers, 12 pytest cases.
- 47 Rust tests (31 lib unit + 4 cross-language + 12 HTTP integration).
  ADR-006.

### Added (Production Readiness)
- `LICENSE` file (Apache 2.0).
- `CONTRIBUTING.md` with development guide, code style, and PR checklist.
- `CHANGELOG.md` (this file).
- CI/CD workflow (GitHub Actions): test, lint, typecheck, and build
  across all layers (Rust, Python, TypeScript, Go, Hermes, MCP, Dashboard).
- `docs/VERSIONING.md` — SemVer policy for wire format and per-package.
- `docs/RELEASE.md` — release process and checklist.

### Added (Phase 6 Slice 2 — Protocol Hardening)
- ADR-007 — bearer-token auth (`core-rs/src/auth.rs`, `TRUSTLAYER_API_TOKEN`).
- ADR-008 — `MatchSpec` payload predicates with dotted-path resolution
  (`core-rs/src/policy.rs::resolve_path`).
- ADR-009 — policy hot-reload via `notify` file watcher and `ArcSwap`
  (`core-rs/src/policy_watch.rs`).

### Added (Phase 6 Slice 3 — Surface Completeness)
- Prometheus `/metrics` endpoint (`core-rs/src/metrics.rs`).
- Ingest rate limiter on `POST /v1/events` (`core-rs/src/rate_limit.rs`).
- MCP server SSE transport alongside stdio.
- Dashboard component tests (React Testing Library, 19 new cases).

### Added (Phase 6 Slice 4a — Formal Spec)
- `spec/v0.1/` — six RFC-2119 normative documents (wire format, event
  types, Cynefin, policy language, HTTP API, conformance).
- `spec/v0.1/fixtures/` — conformant event fixtures.
- ADR-010 — formal spec layout.

### Added (Phase 6 Slice 4b — Go SDK)
- `sdks/go/trustlayer/` — Go SDK mirroring the Python/TS contract.
  31 Go tests (schema + client + guardian + tracer).
- Conformance fixture: `spec/v0.1/fixtures/event-canonical-go.json`.
- ADR-011 — Go SDK design.

### Added (Phase 6 Slice 4c — OpenTelemetry)
- `trustlayer.otel.OTelExporter` — bridges `AgentTraceEvent` to OTel spans.
  16 new pytest cases.
- ADR-012 — OpenTelemetry integration.

### Added (Phase 6 Slice 4d — LLM-Backed Reflection)
- `skills/hermes/llm_reflector.py` — `LLMReflector` calls Ollama (or any
  OpenAI-compatible endpoint) to produce narrative reflections from
  session summaries. Best-effort: falls back to deterministic when the
  LLM is down. 12 new pytest cases.
- ADR-013 — LLM-backed reflection.

### Added (Phase 6 Slice 4e — pyo3 FFI)
- `core-rs/src/ffi.rs` — Python native extension via `pyo3` (`python`
  feature). Exposes `trustlayer_native.TrustLayerGuardian` with JSON-
  string I/O for in-process policy evaluation without HTTP overhead.
  Buildable with `maturin develop --features python`.
- ADR-014 — pyo3 FFI embedding.

### Added (Phase 6 Slice 4f — Deployment)
- `Dockerfile` — multi-stage build for the guardian sidecar.
- `docker/Dockerfile.dashboard` — nginx-served SPA.
- `docker/Dockerfile.hermes` — Hermes reflection loop.
- `docker-compose.yml` — self-hosted quickstart with guardian, dashboard,
  and optional Hermes profile.

### Fixed (Release Hardening — 2026-06-22)
- Dashboard `ReflectionsPane`: removed `aria-label` on date buttons so
  accessible name matches visible text; component tests now pass cleanly.
- Hermes CLI: fixed `_build_reflector` return type (`object` →
  `ReflectionEngine`) for mypy compliance.
- Hermes package: added `py.typed` marker so downstream packages (MCP
  server) type-check cleanly.
- All lint/type/fmt gates verified green across the full matrix.

[0.1.0]: https://github.com/trustlayer/trustlayer/releases/tag/v0.1.0
