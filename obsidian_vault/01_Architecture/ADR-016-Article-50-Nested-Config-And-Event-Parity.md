---
adr: 16
title: Article 50 Nested Config And Cross-SDK Event Parity
date: 2026-07-28
status: accepted
---

# ADR-016 — Article 50 Nested Config And Cross-SDK Event Parity

## Context

Phase 7 introduced EU AI Act Article 50 transparency support:

- `DISCLOSURE_SHOWN` and `CONTENT_MARKED` event types on the wire contract
- nested `article_50.disclosure_config` / `article_50.marking_config` in
  `compliance/schemas/system.schema.json`
- readiness checks in `compliance/src/readiness_scanner.py`

Two gaps blocked a green release gate:

1. The Go SDK `validEventTypes` map lagged Python, TypeScript, and Rust, so
   W4 conformance rejected the new event types.
2. The readiness scanner initially expected flat `article_50` fields while the
   normative system schema and `compliance/examples/system.yaml` use nested
   `disclosure_config` / `marking_config` objects.

## Decision

1. **Schema wins.** The readiness scanner reads nested
   `disclosure_config` / `marking_config` and keeps a flat-field fallback only
   for transitional local registries.
2. **Cross-language parity.** Go gains `EventDisclosureShown` and
   `EventContentMarked` constants, `validEventTypes` entries, and round-trip
   tests matching the other SDKs and `core-rs`.
3. **Compliance is part of the local gate.** `scripts/verify.sh` runs ruff,
   mypy, and pytest for `compliance/`; CI already has a compliance job and is
   aligned to the same scoped paths.

## Consequences

- System registries should follow the nested example shape.
- Flat `article_50` keys remain accepted temporarily; new registries must not
  rely on them.
- Adding further Article 50 fields requires simultaneous schema, scanner,
  fixture, and multi-language event updates when the wire contract changes.

## Alternatives Considered

- Flatten the JSON schema to match the first scanner draft — rejected; the
  nested shape already matches control catalogs and example registries.
- Leave Go without the new event types until a later release — rejected; W4
  conformance requires full SDK parity.
