/**
 * Every v0.1 conformance fixture MUST parse under this SDK's strict envelope.
 *
 * `spec/v0.1/fixtures/` holds deterministic artifacts that every conforming
 * implementation has to accept (spec §6.2). The reference Rust core globs the
 * directory from `core-rs/tests/cross_language.rs`; Phase 8's engineering
 * contract (`docs/PHASE-8-DESIGN.md` §5.3) extends that rule to all four SDKs,
 * because a fixture only proves cross-language parity if more than one
 * language reads it.
 *
 * Globbing rather than naming files means a fixture added to the spec is
 * covered here the moment it is committed.
 */
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { AgentTraceEvent } from "../src/schema.js";

const FIXTURE_DIR = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "..",
  "spec",
  "v0.1",
  "fixtures",
);

const FIXTURES = readdirSync(FIXTURE_DIR)
  .filter((name) => name.startsWith("event-") && name.endsWith(".json"))
  .sort();

function readFixture(name: string): unknown {
  return JSON.parse(readFileSync(join(FIXTURE_DIR, name), "utf-8"));
}

describe("v0.1 conformance fixtures", () => {
  it("finds fixtures to check", () => {
    // Guard the glob itself — a bad path would silently skip every case below.
    expect(FIXTURES.length).toBeGreaterThan(0);
  });

  it.each(FIXTURES)("%s parses under the strict envelope", (name) => {
    const parsed = AgentTraceEvent.parse(readFixture(name));

    expect(parsed.agent_id).toBeTruthy();
    expect(parsed.session_id).toBeTruthy();
  });

  it.each(FIXTURES)("%s preserves every envelope field", (name) => {
    const raw = readFixture(name) as Record<string, unknown>;
    const parsed = AgentTraceEvent.parse(raw);

    expect(parsed.trace_id).toBe(raw.trace_id);
    expect(parsed.agent_id).toBe(raw.agent_id);
    expect(parsed.session_id).toBe(raw.session_id);
    expect(parsed.event_type).toBe(raw.event_type);
    expect(parsed.cynefin_domain).toBe(raw.cynefin_domain);
    expect(parsed.payload).toEqual(raw.payload);
  });

  it.each(FIXTURES)("%s round-trips to a fixed point", (name) => {
    // Parse -> serialise -> parse must be stable, or the fixture cannot be
    // cited across spec versions as evidence of wire-format parity.
    const once = AgentTraceEvent.parse(readFixture(name));
    const twice = AgentTraceEvent.parse(JSON.parse(JSON.stringify(once)));

    expect(twice).toEqual(once);
  });

  it.each(FIXTURES)("%s rejects an unknown envelope field", (name) => {
    // W1 strictness (spec §6.2). The positive cases above pass just as well
    // under a lenient parser, so without this the suite would not actually
    // prove strictness.
    const raw = readFixture(name) as Record<string, unknown>;
    raw.definitely_not_in_v0_1 = true;

    expect(() => AgentTraceEvent.parse(raw)).toThrow();
  });
});
