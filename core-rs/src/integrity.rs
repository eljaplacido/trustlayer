//! Tamper-evident event chain (ADR-017).
//!
//! EU AI Act Art. 12 requires high-risk AI systems to keep automatic logs
//! over their lifetime. A log an operator can silently edit is worth nothing
//! in an assessment, so every stored event is linked into a hash chain whose
//! head commits to the whole prefix.
//!
//! Three design points, each with a reason:
//!
//! * **The chain is server-side.** A client cannot know its position in the
//!   log, so it cannot compute a `prev_hash`; letting it try would let a
//!   compromised client forge continuity. Nothing here appears in the
//!   `AgentTraceEvent` wire envelope (`spec/v0.1/01-wire-format.md` §1.2).
//! * **The chain is scoped per `agent_id`.** Evidence is assessed per AI
//!   system, so an auditor for system X can verify X without being handed
//!   system Y's events. It also lets independent agents append concurrently.
//! * **`recorded_at` is the store's clock.** A client clock is
//!   attacker-controlled and skewed across a fleet; the chain attests to when
//!   the store observed the event, which is the only claim it can honestly
//!   make.
//!
//! What this proves: the log has not been altered since the store recorded
//! it. What it does not prove: that the emitting agent told the truth.
//! Attestation of the emitter is out of scope.

use std::collections::HashMap;
use std::fmt;

use serde::de::Error as _;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::error::{Error, Result};
use crate::schema::AgentTraceEvent;

/// Position of an entry within one agent's chain. 1-based, contiguous.
///
/// A newtype rather than a bare `u64` so a sequence number cannot be passed
/// where a count or a timestamp is expected.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct Seq(u64);

impl Seq {
    /// The sequence number of the first entry in any chain.
    pub const FIRST: Seq = Seq(1);

    pub const fn new(value: u64) -> Self {
        Seq(value)
    }

    pub const fn get(self) -> u64 {
        self.0
    }

    /// The next position. Saturating: a chain long enough to overflow `u64`
    /// is not a case worth panicking over on a production append path.
    pub const fn next(self) -> Self {
        Seq(self.0.saturating_add(1))
    }
}

impl fmt::Display for Seq {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

/// A SHA-256 digest, serialised as lowercase hex.
///
/// Distinct from any content hash by type, so a chain hash cannot be assigned
/// where an artifact hash belongs.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct EventHash([u8; 32]);

impl EventHash {
    /// The `prev_hash` of the first entry in a chain: 32 zero bytes.
    pub const GENESIS: EventHash = EventHash([0u8; 32]);

    pub const fn as_bytes(&self) -> &[u8; 32] {
        &self.0
    }

    pub fn to_hex(self) -> String {
        let mut out = String::with_capacity(64);
        for byte in self.0 {
            out.push_str(&format!("{byte:02x}"));
        }
        out
    }

    pub fn from_hex(value: &str) -> Result<Self> {
        if value.len() != 64 {
            return Err(Error::Integrity(format!(
                "hash must be 64 hex characters, got {}",
                value.len()
            )));
        }
        let mut bytes = [0u8; 32];
        for (i, chunk) in value.as_bytes().chunks_exact(2).enumerate() {
            let pair = std::str::from_utf8(chunk)
                .map_err(|_| Error::Integrity("hash is not valid UTF-8".into()))?;
            bytes[i] = u8::from_str_radix(pair, 16)
                .map_err(|_| Error::Integrity(format!("hash contains non-hex byte {pair:?}")))?;
        }
        Ok(EventHash(bytes))
    }
}

impl fmt::Display for EventHash {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.to_hex())
    }
}

impl Serialize for EventHash {
    fn serialize<S: Serializer>(&self, serializer: S) -> std::result::Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.to_hex())
    }
}

impl<'de> Deserialize<'de> for EventHash {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> std::result::Result<Self, D::Error> {
        let raw = String::deserialize(deserializer)?;
        EventHash::from_hex(&raw).map_err(D::Error::custom)
    }
}

/// One link in an agent's chain. Stored alongside the event, never inside it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChainEntry {
    pub seq: Seq,
    pub agent_id: String,
    pub trace_id: Uuid,
    /// RFC 3339, from the **store's** clock — not the event's `timestamp`.
    pub recorded_at: String,
    pub prev_hash: EventHash,
    pub hash: EventHash,
    /// Set when this entry was rebuilt during crash recovery rather than
    /// written on the original append path. Recovery only ever appends a
    /// missing tail; see [`crate::events`].
    #[serde(default, skip_serializing_if = "is_false")]
    pub recovered: bool,
}

fn is_false(value: &bool) -> bool {
    !*value
}

/// Canonical byte form of an event for hashing.
///
/// This is exactly `serde_json`'s compact serialisation of
/// [`AgentTraceEvent`]: no insignificant whitespace, and object keys in
/// lexicographic order because `serde_json::Map` is `BTreeMap`-backed (the
/// `preserve_order` feature is deliberately **not** enabled). It is therefore
/// byte-identical to the line written to `events.jsonl`, which is what lets a
/// verifier hash the stored line directly.
///
/// Cross-language verifiers must reproduce this exact form: sorted keys,
/// `,`/`:` separators with no spaces, and shortest-round-trip float
/// formatting. `spec/v0.1/fixtures/` pins examples.
pub fn canonical_event_json(event: &AgentTraceEvent) -> Result<String> {
    serde_json::to_string(event).map_err(Error::InvalidEvent)
}

/// Hash preimage: a canonical JSON object binding the chain position to the
/// event. Building a self-describing object (rather than concatenating
/// fields) removes any ambiguity about where one field ends and the next
/// begins, so no separator-injection is possible via `agent_id`.
fn hash_preimage(
    seq: Seq,
    agent_id: &str,
    trace_id: Uuid,
    recorded_at: &str,
    prev_hash: EventHash,
    event: &AgentTraceEvent,
) -> Result<String> {
    let preimage = serde_json::json!({
        "agent_id": agent_id,
        "event": serde_json::to_value(event).map_err(Error::InvalidEvent)?,
        "prev_hash": prev_hash.to_hex(),
        "recorded_at": recorded_at,
        "seq": seq.get(),
        "trace_id": trace_id.to_string(),
    });
    serde_json::to_string(&preimage).map_err(Error::InvalidEvent)
}

/// Compute the chain hash for one position.
pub fn compute_hash(
    seq: Seq,
    agent_id: &str,
    trace_id: Uuid,
    recorded_at: &str,
    prev_hash: EventHash,
    event: &AgentTraceEvent,
) -> Result<EventHash> {
    let preimage = hash_preimage(seq, agent_id, trace_id, recorded_at, prev_hash, event)?;
    let digest = Sha256::digest(preimage.as_bytes());
    Ok(EventHash(digest.into()))
}

impl ChainEntry {
    /// Build the entry that follows `prev` for `event`.
    ///
    /// `prev` is `None` for the first event of an agent, which starts from
    /// [`Seq::FIRST`] and [`EventHash::GENESIS`].
    pub fn next(
        prev: Option<&ChainEntry>,
        event: &AgentTraceEvent,
        recorded_at: &str,
    ) -> Result<Self> {
        let (seq, prev_hash) = match prev {
            Some(entry) => (entry.seq.next(), entry.hash),
            None => (Seq::FIRST, EventHash::GENESIS),
        };
        let hash = compute_hash(
            seq,
            &event.agent_id,
            event.trace_id,
            recorded_at,
            prev_hash,
            event,
        )?;
        Ok(ChainEntry {
            seq,
            agent_id: event.agent_id.clone(),
            trace_id: event.trace_id,
            recorded_at: recorded_at.to_string(),
            prev_hash,
            hash,
            recovered: false,
        })
    }
}

/// Outcome of verifying one agent's chain.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ChainVerification {
    pub agent_id: String,
    pub entries_checked: usize,
    /// Highest sequence number verified before the first failure (or the end).
    pub verified_through_seq: Option<Seq>,
    /// Position of the first entry that failed, if any.
    pub first_bad_seq: Option<Seq>,
    pub reason: Option<String>,
}

impl ChainVerification {
    pub fn ok(&self) -> bool {
        self.first_bad_seq.is_none()
    }

    fn failed(
        agent_id: &str,
        checked: usize,
        through: Option<Seq>,
        seq: Seq,
        reason: String,
    ) -> Self {
        ChainVerification {
            agent_id: agent_id.to_string(),
            entries_checked: checked,
            verified_through_seq: through,
            first_bad_seq: Some(seq),
            reason: Some(reason),
        }
    }
}

/// Recompute an agent's chain and report the first divergence.
///
/// `events` maps `trace_id` to the stored event. Both inputs are needed: an
/// event deleted from the log while its chain entry survives is caught by the
/// missing lookup, and an entry deleted alongside its event is caught by the
/// sequence gap. Mutating an event in place changes its recomputed hash.
///
/// `entries` must be in chain order; callers hold them that way.
pub fn verify_chain(
    agent_id: &str,
    entries: &[ChainEntry],
    events: &HashMap<Uuid, AgentTraceEvent>,
) -> ChainVerification {
    let mut expected_seq = Seq::FIRST;
    let mut expected_prev = EventHash::GENESIS;
    let mut verified_through: Option<Seq> = None;

    for (index, entry) in entries.iter().enumerate() {
        if entry.agent_id != agent_id {
            return ChainVerification::failed(
                agent_id,
                index,
                verified_through,
                entry.seq,
                format!(
                    "entry belongs to agent {:?}, expected {agent_id:?}",
                    entry.agent_id
                ),
            );
        }
        if entry.seq != expected_seq {
            return ChainVerification::failed(
                agent_id,
                index,
                verified_through,
                entry.seq,
                format!("sequence gap: expected {expected_seq}, found {}", entry.seq),
            );
        }
        if entry.prev_hash != expected_prev {
            return ChainVerification::failed(
                agent_id,
                index,
                verified_through,
                entry.seq,
                "prev_hash does not match the preceding entry".to_string(),
            );
        }

        let Some(event) = events.get(&entry.trace_id) else {
            return ChainVerification::failed(
                agent_id,
                index,
                verified_through,
                entry.seq,
                format!("event {} is missing from the log", entry.trace_id),
            );
        };

        match compute_hash(
            entry.seq,
            &entry.agent_id,
            entry.trace_id,
            &entry.recorded_at,
            entry.prev_hash,
            event,
        ) {
            Ok(recomputed) if recomputed == entry.hash => {}
            Ok(_) => {
                return ChainVerification::failed(
                    agent_id,
                    index,
                    verified_through,
                    entry.seq,
                    "event content does not match the recorded hash".to_string(),
                );
            }
            Err(err) => {
                return ChainVerification::failed(
                    agent_id,
                    index,
                    verified_through,
                    entry.seq,
                    format!("could not recompute hash: {err}"),
                );
            }
        }

        verified_through = Some(entry.seq);
        expected_prev = entry.hash;
        expected_seq = entry.seq.next();
    }

    ChainVerification {
        agent_id: agent_id.to_string(),
        entries_checked: entries.len(),
        verified_through_seq: verified_through,
        first_bad_seq: None,
        reason: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::schema::{CynefinDomain, EventType, Metrics};
    use chrono::{DateTime, Utc};

    fn event(agent: &str, n: u8) -> AgentTraceEvent {
        let mut payload = serde_json::Map::new();
        payload.insert("tool_name".into(), serde_json::json!(format!("tool-{n}")));
        AgentTraceEvent {
            trace_id: Uuid::from_u128(u128::from(n)),
            agent_id: agent.to_string(),
            session_id: "S1".to_string(),
            timestamp: "2026-08-02T10:00:00+00:00"
                .parse::<DateTime<Utc>>()
                .expect("timestamp"),
            event_type: EventType::ToolCall,
            cynefin_domain: CynefinDomain::default(),
            payload,
            metrics: Metrics::default(),
        }
    }

    fn chain(agent: &str, events: &[AgentTraceEvent]) -> Vec<ChainEntry> {
        let mut entries: Vec<ChainEntry> = Vec::new();
        for (i, ev) in events.iter().enumerate() {
            let recorded_at = format!("2026-08-02T10:00:{i:02}+00:00");
            let entry = ChainEntry::next(entries.last(), ev, &recorded_at).expect("build entry");
            assert_eq!(entry.agent_id, agent);
            entries.push(entry);
        }
        entries
    }

    fn index(events: &[AgentTraceEvent]) -> HashMap<Uuid, AgentTraceEvent> {
        events.iter().map(|e| (e.trace_id, e.clone())).collect()
    }

    #[test]
    fn hash_hex_round_trips() {
        let hash = EventHash([0xab; 32]);
        assert_eq!(hash.to_hex().len(), 64);
        assert_eq!(EventHash::from_hex(&hash.to_hex()).expect("parse"), hash);
    }

    #[test]
    fn hash_from_hex_rejects_malformed_input() {
        for bad in ["", "abc", &"z".repeat(64)] {
            assert!(EventHash::from_hex(bad).is_err(), "accepted {bad:?}");
        }
    }

    #[test]
    fn genesis_chain_starts_at_seq_one() {
        let events = vec![event("a", 1)];
        let entries = chain("a", &events);
        assert_eq!(entries[0].seq, Seq::FIRST);
        assert_eq!(entries[0].prev_hash, EventHash::GENESIS);
    }

    #[test]
    fn canonical_form_matches_the_jsonl_line() {
        // The verifier hashes the stored line; if these ever diverge, every
        // chain built from a file would fail to verify.
        let ev = event("a", 1);
        let canonical = canonical_event_json(&ev).expect("canonical");
        let line = serde_json::to_string(&ev).expect("line");
        assert_eq!(canonical, line);
    }

    #[test]
    fn canonical_form_is_stable_across_repeated_serialisation() {
        let ev = event("a", 7);
        let first = canonical_event_json(&ev).expect("first");
        for _ in 0..16 {
            assert_eq!(canonical_event_json(&ev).expect("repeat"), first);
        }
    }

    #[test]
    fn canonical_form_sorts_object_keys() {
        let mut ev = event("a", 1);
        ev.payload.clear();
        ev.payload.insert("zeta".into(), serde_json::json!(1));
        ev.payload.insert("alpha".into(), serde_json::json!(2));
        let canonical = canonical_event_json(&ev).expect("canonical");
        let alpha = canonical.find("alpha").expect("alpha present");
        let zeta = canonical.find("zeta").expect("zeta present");
        assert!(alpha < zeta, "keys are not lexicographically ordered");
    }

    #[test]
    fn intact_chain_verifies() {
        let events = vec![event("a", 1), event("a", 2), event("a", 3)];
        let entries = chain("a", &events);

        let result = verify_chain("a", &entries, &index(&events));

        assert!(result.ok(), "{result:?}");
        assert_eq!(result.entries_checked, 3);
        assert_eq!(result.verified_through_seq, Some(Seq::new(3)));
    }

    #[test]
    fn empty_chain_verifies_vacuously() {
        let result = verify_chain("a", &[], &HashMap::new());
        assert!(result.ok());
        assert_eq!(result.verified_through_seq, None);
    }

    #[test]
    fn mutating_an_event_fails_at_that_position() {
        let events = vec![event("a", 1), event("a", 2), event("a", 3)];
        let entries = chain("a", &events);

        let mut tampered = index(&events);
        tampered
            .get_mut(&events[1].trace_id)
            .expect("event present")
            .payload
            .insert("tool_name".into(), serde_json::json!("evil"));

        let result = verify_chain("a", &entries, &tampered);

        assert!(!result.ok());
        assert_eq!(result.first_bad_seq, Some(Seq::new(2)));
        assert_eq!(result.verified_through_seq, Some(Seq::FIRST));
    }

    #[test]
    fn deleting_an_event_but_keeping_its_entry_is_detected() {
        let events = vec![event("a", 1), event("a", 2), event("a", 3)];
        let entries = chain("a", &events);

        let mut pruned = index(&events);
        pruned.remove(&events[1].trace_id);

        let result = verify_chain("a", &entries, &pruned);

        assert!(!result.ok());
        assert_eq!(result.first_bad_seq, Some(Seq::new(2)));
        assert!(result.reason.unwrap_or_default().contains("missing"));
    }

    #[test]
    fn deleting_an_entry_from_the_middle_is_detected_as_a_gap() {
        let events = vec![event("a", 1), event("a", 2), event("a", 3)];
        let mut entries = chain("a", &events);
        entries.remove(1);

        let result = verify_chain("a", &entries, &index(&events));

        assert!(!result.ok());
        assert_eq!(result.first_bad_seq, Some(Seq::new(3)));
        assert!(result.reason.unwrap_or_default().contains("sequence gap"));
    }

    #[test]
    fn reordering_entries_breaks_the_chain() {
        let events = vec![event("a", 1), event("a", 2), event("a", 3)];
        let mut entries = chain("a", &events);
        entries.swap(1, 2);

        let result = verify_chain("a", &entries, &index(&events));

        assert!(!result.ok());
    }

    #[test]
    fn truncating_the_tail_still_verifies() {
        // A crash can only truncate the tail. That is not tampering, and a
        // short-but-consistent prefix must verify (see events.rs recovery).
        let events = vec![event("a", 1), event("a", 2), event("a", 3)];
        let mut entries = chain("a", &events);
        entries.pop();

        let result = verify_chain("a", &entries, &index(&events));

        assert!(result.ok(), "{result:?}");
        assert_eq!(result.verified_through_seq, Some(Seq::new(2)));
    }

    #[test]
    fn entry_from_another_agent_is_rejected() {
        let events = vec![event("a", 1)];
        let mut entries = chain("a", &events);
        entries[0].agent_id = "b".into();

        let result = verify_chain("a", &entries, &index(&events));

        assert!(!result.ok());
    }

    #[test]
    fn chains_are_independent_per_agent() {
        // Interleaved appends across agents must not affect each other's
        // sequence numbers — this is what allows concurrent appends.
        let a_events = vec![event("a", 1), event("a", 2)];
        let b_events = vec![event("b", 10)];

        let a_entries = chain("a", &a_events);
        let b_entries = chain("b", &b_events);

        assert_eq!(b_entries[0].seq, Seq::FIRST);
        assert!(verify_chain("a", &a_entries, &index(&a_events)).ok());
        assert!(verify_chain("b", &b_entries, &index(&b_events)).ok());
    }

    #[test]
    fn recorded_at_is_bound_into_the_hash() {
        let ev = event("a", 1);
        let one = ChainEntry::next(None, &ev, "2026-08-02T10:00:00+00:00").expect("one");
        let two = ChainEntry::next(None, &ev, "2026-08-02T10:00:01+00:00").expect("two");
        assert_ne!(one.hash, two.hash, "recorded_at must affect the digest");
    }

    #[test]
    fn chain_entry_serde_round_trips() {
        let events = vec![event("a", 1)];
        let entries = chain("a", &events);
        let line = serde_json::to_string(&entries[0]).expect("serialise");
        let back: ChainEntry = serde_json::from_str(&line).expect("deserialise");
        assert_eq!(back, entries[0]);
        assert!(
            !line.contains("recovered"),
            "the recovered flag should be omitted when false"
        );
    }

    #[test]
    fn long_chain_verifies_end_to_end() {
        let events: Vec<AgentTraceEvent> = (1..=200).map(|n| event("a", n as u8)).collect();
        let entries = chain("a", &events);
        let result = verify_chain("a", &entries, &index(&events));
        assert!(result.ok(), "{result:?}");
        assert_eq!(result.verified_through_seq, Some(Seq::new(200)));
    }
}
