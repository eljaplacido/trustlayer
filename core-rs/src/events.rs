//! In-memory event store with optional JSONL persistence.
//!
//! Phase 5 read-side: dashboards and humans need to introspect what an agent
//! actually emitted. The guardian sidecar already sees every event during
//! `POST /v1/check`; this module lets us *also* `POST /v1/events` to a
//! durable log and read back filtered slices via `GET /v1/events` and
//! `GET /v1/sessions/:agent/:session`.
//!
//! Design constraints (see [[ADR-006]]):
//! * Append-only JSONL on disk so the format matches the Python SDK's
//!   existing `examples/.demo_traces.jsonl` and the Hermes sidecar.
//! * In-memory `Vec<AgentTraceEvent>` mirror plus a `(agent, session) ->
//!   indices` map for O(1) session lookup.
//! * Idempotent on `trace_id` — re-POSTing an event already in the store is
//!   a no-op (matches Hermes's ingest semantics).
//! * Synchronous locks for the short critical sections — each write is a
//!   single JSON line on local disk (<100µs), well under any runtime
//!   blocking threshold.

use std::collections::HashMap;
use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use async_trait::async_trait;
use serde::Serialize;

use crate::error::{Error, Result};
use crate::schema::{AgentTraceEvent, EventType};

type SessionKey = (String, String);

/// Storage backend for the trace store.
///
/// The HTTP sidecar holds an `Arc<dyn TraceStore>` so the same routes serve
/// any backend. Two implementations ship in-tree:
///
/// * [`EventStore`] — in-memory + append-only JSONL (default; single-node).
/// * `PostgresStore` — durable, horizontally-scalable (feature `postgres`).
///
/// Query methods return [`Result`] because remote backends can fail mid-call;
/// the JSONL backend never errors on reads but conforms to the same contract.
#[async_trait]
pub trait TraceStore: Send + Sync {
    /// Append a batch. Returns the count of newly-stored (non-duplicate) events.
    /// Idempotent on `trace_id`.
    async fn append_batch(&self, events: Vec<AgentTraceEvent>) -> Result<usize>;

    /// Events matching the filter, chronological. `limit` selects the tail.
    async fn list_events(&self, filter: &EventFilter) -> Result<Vec<AgentTraceEvent>>;

    /// One summary per `(agent_id, session_id)`, most-recent first.
    async fn list_sessions(&self) -> Result<Vec<SessionSummary>>;

    /// All events for one session, in insertion order.
    async fn get_session(&self, agent_id: &str, session_id: &str) -> Result<Vec<AgentTraceEvent>>;
}

/// Filters accepted by [`EventStore::list_events`].
#[derive(Debug, Default, Clone)]
pub struct EventFilter {
    pub agent_id: Option<String>,
    pub session_id: Option<String>,
    pub event_type: Option<EventType>,
    pub limit: Option<usize>,
}

/// Summary of one session — what `GET /v1/sessions` returns.
#[derive(Debug, Clone, Serialize)]
pub struct SessionSummary {
    pub agent_id: String,
    pub session_id: String,
    pub event_count: usize,
    pub first_seen: String,
    pub last_seen: String,
}

struct Inner {
    events: Vec<AgentTraceEvent>,
    by_trace: HashMap<uuid::Uuid, usize>,
    by_session: HashMap<SessionKey, Vec<usize>>,
    file: Option<File>,
}

/// Thread-safe, append-only event store.
pub struct EventStore {
    inner: Mutex<Inner>,
    path: Option<PathBuf>,
    /// Optional cap on retained events. `None` = unbounded (default). When set,
    /// the oldest events are evicted (and the JSONL file compacted) once the
    /// in-memory log grows past the cap plus a slack window, so steady-state
    /// appends stay amortised O(1). See [`EventStore::with_retention`].
    retention: Option<usize>,
}

impl EventStore {
    /// In-memory only. No persistence; useful for tests and ephemeral demos.
    pub fn in_memory() -> Self {
        Self {
            inner: Mutex::new(Inner {
                events: Vec::new(),
                by_trace: HashMap::new(),
                by_session: HashMap::new(),
                file: None,
            }),
            path: None,
            retention: None,
        }
    }

    /// Cap the number of retained events. `Some(n)` keeps roughly the most
    /// recent `n`; `None` is unbounded. For high-volume / production workloads
    /// prefer the `postgres` backend — JSONL retention is best-effort
    /// (compaction rewrites the file on overflow). See `docs/SCALING.md`.
    pub fn with_retention(mut self, max_events: Option<usize>) -> Self {
        self.retention = max_events.filter(|n| *n > 0);
        self
    }

    /// Open (or create) an append-only JSONL log and replay existing lines
    /// into the in-memory index. Existing entries are deduped on `trace_id`.
    pub fn open_jsonl(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref().to_path_buf();
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent)?;
            }
        }
        let mut inner = Inner {
            events: Vec::new(),
            by_trace: HashMap::new(),
            by_session: HashMap::new(),
            file: None,
        };
        if path.exists() {
            let reader = BufReader::new(File::open(&path)?);
            for line in reader.lines() {
                let line = line?;
                if line.trim().is_empty() {
                    continue;
                }
                let event: AgentTraceEvent =
                    serde_json::from_str(&line).map_err(Error::InvalidEvent)?;
                Self::index_existing(&mut inner, event);
            }
        }
        let file = OpenOptions::new().create(true).append(true).open(&path)?;
        inner.file = Some(file);
        Ok(Self {
            inner: Mutex::new(inner),
            path: Some(path),
            retention: None,
        })
    }

    /// Path of the underlying JSONL file, if persistent.
    pub fn path(&self) -> Option<&Path> {
        self.path.as_deref()
    }

    /// Append an event. Idempotent on `trace_id`. Returns `true` if this is
    /// the first time we've seen the event, `false` if it was a duplicate.
    pub fn append(&self, event: AgentTraceEvent) -> Result<bool> {
        let mut inner = self.inner.lock().expect("event store mutex poisoned");
        if inner.by_trace.contains_key(&event.trace_id) {
            return Ok(false);
        }
        if let Some(file) = inner.file.as_mut() {
            let line = serde_json::to_string(&event).map_err(Error::InvalidEvent)?;
            writeln!(file, "{line}")?;
            file.flush()?;
        }
        Self::index_existing(&mut inner, event);
        self.enforce_retention(&mut inner)?;
        Ok(true)
    }

    /// Evict the oldest events once the log overruns the retention cap.
    ///
    /// Triggered lazily — only past `max + max/4` — so the O(n) index rebuild
    /// and (for file-backed stores) file compaction amortise to O(1) per
    /// append in steady state. No-op when retention is unset.
    fn enforce_retention(&self, inner: &mut Inner) -> Result<()> {
        let Some(max) = self.retention else {
            return Ok(());
        };
        let slack = (max / 4).max(1);
        if inner.events.len() <= max + slack {
            return Ok(());
        }
        let drop = inner.events.len() - max;
        inner.events.drain(0..drop);

        // Indices are positional, so a front-drain invalidates them all.
        inner.by_trace.clear();
        inner.by_session.clear();
        for (idx, ev) in inner.events.iter().enumerate() {
            inner.by_trace.insert(ev.trace_id, idx);
            inner
                .by_session
                .entry((ev.agent_id.clone(), ev.session_id.clone()))
                .or_default()
                .push(idx);
        }

        // Compact the JSONL file to match the retained window (write-then-rename
        // so a crash mid-compaction never leaves a truncated log).
        if let Some(path) = self.path.as_ref() {
            let tmp = path.with_extension("jsonl.compacting");
            {
                let mut f = File::create(&tmp)?;
                for ev in &inner.events {
                    let line = serde_json::to_string(ev).map_err(Error::InvalidEvent)?;
                    writeln!(f, "{line}")?;
                }
                f.flush()?;
            }
            std::fs::rename(&tmp, path)?;
            inner.file = Some(OpenOptions::new().create(true).append(true).open(path)?);
        }
        Ok(())
    }

    /// Append a batch. Returns the count of newly-stored (non-duplicate) events.
    pub fn append_batch(&self, events: Vec<AgentTraceEvent>) -> Result<usize> {
        let mut written = 0;
        for e in events {
            if self.append(e)? {
                written += 1;
            }
        }
        Ok(written)
    }

    /// Return events matching the filter. Order: chronological (insertion order).
    /// `limit` applies to the tail (most-recent N) when set.
    pub fn list_events(&self, filter: &EventFilter) -> Vec<AgentTraceEvent> {
        let inner = self.inner.lock().expect("event store mutex poisoned");
        let mut out: Vec<AgentTraceEvent> = inner
            .events
            .iter()
            .filter(|e| {
                filter.agent_id.as_deref().is_none_or(|a| e.agent_id == a)
                    && filter
                        .session_id
                        .as_deref()
                        .is_none_or(|s| e.session_id == s)
                    && filter.event_type.is_none_or(|t| e.event_type == t)
            })
            .cloned()
            .collect();
        if let Some(n) = filter.limit {
            if out.len() > n {
                let drop = out.len() - n;
                out.drain(0..drop);
            }
        }
        out
    }

    /// One summary per known `(agent_id, session_id)` pair, sorted by `last_seen`
    /// descending (most-recent first).
    pub fn list_sessions(&self) -> Vec<SessionSummary> {
        let inner = self.inner.lock().expect("event store mutex poisoned");
        let mut summaries: Vec<SessionSummary> = inner
            .by_session
            .iter()
            .filter_map(|(key, indices)| {
                let first = inner.events.get(*indices.first()?)?;
                let last = inner.events.get(*indices.last()?)?;
                Some(SessionSummary {
                    agent_id: key.0.clone(),
                    session_id: key.1.clone(),
                    event_count: indices.len(),
                    first_seen: first.timestamp.to_rfc3339(),
                    last_seen: last.timestamp.to_rfc3339(),
                })
            })
            .collect();
        summaries.sort_by(|a, b| b.last_seen.cmp(&a.last_seen));
        summaries
    }

    /// All events for one session, in insertion order.
    pub fn get_session(&self, agent_id: &str, session_id: &str) -> Vec<AgentTraceEvent> {
        let inner = self.inner.lock().expect("event store mutex poisoned");
        let key = (agent_id.to_string(), session_id.to_string());
        inner
            .by_session
            .get(&key)
            .map(|indices| {
                indices
                    .iter()
                    .filter_map(|i| inner.events.get(*i).cloned())
                    .collect()
            })
            .unwrap_or_default()
    }

    fn index_existing(inner: &mut Inner, event: AgentTraceEvent) {
        if inner.by_trace.contains_key(&event.trace_id) {
            return;
        }
        let idx = inner.events.len();
        let key = (event.agent_id.clone(), event.session_id.clone());
        let trace_id = event.trace_id;
        inner.events.push(event);
        inner.by_trace.insert(trace_id, idx);
        inner.by_session.entry(key).or_default().push(idx);
    }
}

/// The JSONL/in-memory backend satisfies the same async contract as remote
/// backends; its methods complete synchronously (local file I/O is sub-100µs)
/// and never error on reads.
#[async_trait]
impl TraceStore for EventStore {
    async fn append_batch(&self, events: Vec<AgentTraceEvent>) -> Result<usize> {
        EventStore::append_batch(self, events)
    }

    async fn list_events(&self, filter: &EventFilter) -> Result<Vec<AgentTraceEvent>> {
        Ok(EventStore::list_events(self, filter))
    }

    async fn list_sessions(&self) -> Result<Vec<SessionSummary>> {
        Ok(EventStore::list_sessions(self))
    }

    async fn get_session(&self, agent_id: &str, session_id: &str) -> Result<Vec<AgentTraceEvent>> {
        Ok(EventStore::get_session(self, agent_id, session_id))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_event(trace: &str, agent: &str, session: &str) -> AgentTraceEvent {
        let raw = format!(
            r#"{{
                "trace_id": "{trace}",
                "agent_id": "{agent}",
                "session_id": "{session}",
                "timestamp": "2026-05-18T10:00:00+00:00",
                "event_type": "TOOL_CALL",
                "payload": {{"tool_name": "calc"}}
            }}"#
        );
        serde_json::from_str(&raw).expect("parse")
    }

    #[test]
    fn append_then_list_returns_event() {
        let store = EventStore::in_memory();
        let event = sample_event("11111111-1111-4111-8111-111111111111", "a", "s");
        assert!(store.append(event.clone()).expect("append"));
        let listed = store.list_events(&EventFilter::default());
        assert_eq!(listed.len(), 1);
        assert_eq!(listed[0].agent_id, "a");
    }

    #[test]
    fn append_is_idempotent_on_trace_id() {
        let store = EventStore::in_memory();
        let event = sample_event("11111111-1111-4111-8111-111111111111", "a", "s");
        assert!(store.append(event.clone()).expect("first"));
        assert!(!store.append(event).expect("dup"));
        assert_eq!(store.list_events(&EventFilter::default()).len(), 1);
    }

    #[test]
    fn list_events_filters_by_agent_and_session() {
        let store = EventStore::in_memory();
        store
            .append(sample_event(
                "11111111-1111-4111-8111-111111111111",
                "a",
                "s1",
            ))
            .unwrap();
        store
            .append(sample_event(
                "22222222-2222-4222-8222-222222222222",
                "a",
                "s2",
            ))
            .unwrap();
        store
            .append(sample_event(
                "33333333-3333-4333-8333-333333333333",
                "b",
                "s1",
            ))
            .unwrap();
        let agent_a = store.list_events(&EventFilter {
            agent_id: Some("a".into()),
            ..Default::default()
        });
        assert_eq!(agent_a.len(), 2);
        let a_s2 = store.list_events(&EventFilter {
            agent_id: Some("a".into()),
            session_id: Some("s2".into()),
            ..Default::default()
        });
        assert_eq!(a_s2.len(), 1);
        assert_eq!(a_s2[0].session_id, "s2");
    }

    #[test]
    fn list_events_filters_by_event_type() {
        let store = EventStore::in_memory();
        store
            .append(sample_event(
                "11111111-1111-4111-8111-111111111111",
                "a",
                "s",
            ))
            .unwrap();
        let policy_check: AgentTraceEvent = serde_json::from_str(
            r#"{
                "trace_id": "22222222-2222-4222-8222-222222222222",
                "agent_id": "a",
                "session_id": "s",
                "timestamp": "2026-05-22T10:00:00+00:00",
                "event_type": "POLICY_CHECK",
                "payload": {"policy_name": "default", "action": "x", "result": "PASS"}
            }"#,
        )
        .expect("parse");
        store.append(policy_check).unwrap();

        let only_policy = store.list_events(&EventFilter {
            event_type: Some(EventType::PolicyCheck),
            ..Default::default()
        });
        assert_eq!(only_policy.len(), 1);
        assert_eq!(only_policy[0].event_type, EventType::PolicyCheck);
    }

    #[test]
    fn list_events_limit_returns_tail() {
        let store = EventStore::in_memory();
        for i in 0..5u8 {
            let trace = format!("0000000{}-0000-4000-8000-000000000000", i);
            store.append(sample_event(&trace, "a", "s")).unwrap();
        }
        let last_two = store.list_events(&EventFilter {
            limit: Some(2),
            ..Default::default()
        });
        assert_eq!(last_two.len(), 2);
        assert_eq!(
            last_two[0].trace_id.to_string(),
            "00000003-0000-4000-8000-000000000000"
        );
    }

    #[test]
    fn list_sessions_summarises_each_pair() {
        let store = EventStore::in_memory();
        store
            .append(sample_event(
                "11111111-1111-4111-8111-111111111111",
                "a",
                "s1",
            ))
            .unwrap();
        store
            .append(sample_event(
                "22222222-2222-4222-8222-222222222222",
                "a",
                "s1",
            ))
            .unwrap();
        store
            .append(sample_event(
                "33333333-3333-4333-8333-333333333333",
                "b",
                "s2",
            ))
            .unwrap();
        let sessions = store.list_sessions();
        assert_eq!(sessions.len(), 2);
        let a_s1 = sessions.iter().find(|s| s.agent_id == "a").expect("a/s1");
        assert_eq!(a_s1.event_count, 2);
    }

    #[test]
    fn get_session_returns_events_in_order() {
        let store = EventStore::in_memory();
        store
            .append(sample_event(
                "11111111-1111-4111-8111-111111111111",
                "a",
                "s",
            ))
            .unwrap();
        store
            .append(sample_event(
                "22222222-2222-4222-8222-222222222222",
                "a",
                "s",
            ))
            .unwrap();
        let session = store.get_session("a", "s");
        assert_eq!(session.len(), 2);
        assert_eq!(
            session[0].trace_id.to_string(),
            "11111111-1111-4111-8111-111111111111"
        );
    }

    #[test]
    fn jsonl_persistence_round_trips() {
        let tmp = tempdir();
        let path = tmp.join("events.jsonl");
        {
            let store = EventStore::open_jsonl(&path).expect("open");
            store
                .append(sample_event(
                    "11111111-1111-4111-8111-111111111111",
                    "a",
                    "s",
                ))
                .unwrap();
            store
                .append(sample_event(
                    "22222222-2222-4222-8222-222222222222",
                    "a",
                    "s",
                ))
                .unwrap();
        }
        let reopened = EventStore::open_jsonl(&path).expect("reopen");
        let all = reopened.list_events(&EventFilter::default());
        assert_eq!(all.len(), 2);
        // Dedup still holds across the disk boundary.
        assert!(!reopened
            .append(sample_event(
                "11111111-1111-4111-8111-111111111111",
                "a",
                "s",
            ))
            .unwrap());
    }

    #[test]
    fn append_batch_returns_count_of_new_events() {
        let store = EventStore::in_memory();
        let written = store
            .append_batch(vec![
                sample_event("11111111-1111-4111-8111-111111111111", "a", "s"),
                sample_event("22222222-2222-4222-8222-222222222222", "a", "s"),
                sample_event("11111111-1111-4111-8111-111111111111", "a", "s"), // duplicate
            ])
            .unwrap();
        assert_eq!(written, 2);
        assert_eq!(store.list_events(&EventFilter::default()).len(), 2);
    }

    #[test]
    fn retention_caps_in_memory_log() {
        let store = EventStore::in_memory().with_retention(Some(4));
        for i in 0..40u32 {
            let trace = format!("{i:08x}-0000-4000-8000-000000000000");
            store.append(sample_event(&trace, "a", "s")).unwrap();
        }
        // Bounded to max (4) + slack window (max/4 -> 1) at most; oldest evicted.
        let all = store.list_events(&EventFilter::default());
        assert!(all.len() <= 5, "len={}", all.len());
        assert!(all.len() >= 4);
        // The most-recent event survives; the very first was evicted.
        let last = all.last().unwrap();
        assert_eq!(
            last.trace_id.to_string(),
            "00000027-0000-4000-8000-000000000000"
        );
        assert!(store
            .list_events(&EventFilter::default())
            .iter()
            .all(|e| e.trace_id.to_string() != "00000000-0000-4000-8000-000000000000"));
    }

    #[test]
    fn retention_compacts_jsonl_file() {
        let tmp = tempdir();
        let path = tmp.join("events.jsonl");
        let store = EventStore::open_jsonl(&path)
            .unwrap()
            .with_retention(Some(3));
        for i in 0..30u32 {
            let trace = format!("{i:08x}-0000-4000-8000-000000000000");
            store.append(sample_event(&trace, "a", "s")).unwrap();
        }
        // Reopening reads the compacted file — proves on-disk retention held.
        let reopened = EventStore::open_jsonl(&path).unwrap();
        let on_disk = reopened.list_events(&EventFilter::default());
        assert!(on_disk.len() <= 3 + 1, "on-disk len={}", on_disk.len());
        assert!(!path.with_extension("jsonl.compacting").exists());
    }

    fn tempdir() -> PathBuf {
        let mut p = std::env::temp_dir();
        p.push(format!("trustlayer-events-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&p).expect("create tempdir");
        p
    }
}
