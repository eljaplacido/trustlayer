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
use chrono::{DateTime, Duration, Utc};
use serde::Serialize;

use crate::error::{Error, Result};
use crate::integrity::{verify_chain, ChainEntry, ChainVerification};
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
    /// Per-`agent_id` hash chains (ADR-017). Complete: entries are retained
    /// even after their events are archived, because the chain *is* the
    /// tamper-evidence record. At roughly 250 bytes per entry this is ~10% of
    /// the cost of retaining the events themselves; deployments where that
    /// matters should use the `postgres` backend.
    chains: HashMap<String, Vec<ChainEntry>>,
    chain_file: Option<File>,
    archive_file: Option<File>,
    /// When the store observed each event, parallel to `events` and drained
    /// with it. Store time, never the client's `timestamp` — see
    /// [`EventStore::index_existing`].
    recorded_at: Vec<DateTime<Utc>>,
    /// Events moved to the archive, and eviction attempts refused by the
    /// retention floor. Surfaced via [`EventStore::retention_stats`].
    archived_total: u64,
    floor_blocked_total: u64,
    /// Chain problems observed while opening the log. Surfaced to operators
    /// rather than silently repaired — see [`EventStore::chain_anomalies`].
    anomalies: Vec<String>,
}

impl Inner {
    fn empty() -> Self {
        Inner {
            events: Vec::new(),
            by_trace: HashMap::new(),
            by_session: HashMap::new(),
            file: None,
            chains: HashMap::new(),
            chain_file: None,
            archive_file: None,
            recorded_at: Vec::new(),
            archived_total: 0,
            floor_blocked_total: 0,
            anomalies: Vec::new(),
        }
    }
}

/// Retention counters, for operators and for `GET /metrics`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct RetentionStats {
    /// Events moved to `events.archive.jsonl` over this process's lifetime.
    pub archived_total: u64,
    /// Eviction attempts refused because the events were younger than the
    /// retention floor. A rising value means the live log is growing past its
    /// target and the operator needs more disk or a shorter floor — never
    /// that evidence was dropped.
    pub floor_blocked_total: u64,
    /// Events currently in the live log.
    pub live_events: usize,
}

/// Thread-safe, append-only event store.
pub struct EventStore {
    inner: Mutex<Inner>,
    path: Option<PathBuf>,
    /// Soft target for the number of *live* events. `None` = unbounded
    /// (default). Overflow archives rather than deletes — see
    /// [`EventStore::with_retention`].
    retention: Option<usize>,
    /// Whether to maintain the tamper-evident chain (ADR-017). On by default
    /// for file-backed stores, off for in-memory ones.
    integrity: bool,
    /// Minimum age before an event may be evicted from the live log. Outranks
    /// [`EventStore::retention`] — see [`EventStore::with_retention_floor`].
    retention_floor: Option<Duration>,
}

/// Art. 12 default: high-risk system logs must be retained for at least six
/// months. Operators of biometric or law-enforcement systems raise this to 24
/// months via `TRUSTLAYER_RETENTION_MIN_DAYS`.
pub const DEFAULT_RETENTION_FLOOR_DAYS: i64 = 180;

impl EventStore {
    /// In-memory only. No persistence; useful for tests and ephemeral demos.
    ///
    /// Integrity chaining is **off** by default here: an in-memory log has
    /// nothing to tamper with across a restart. Enable it with
    /// [`EventStore::with_integrity`] to exercise the chain in tests.
    pub fn in_memory() -> Self {
        Self {
            inner: Mutex::new(Inner::empty()),
            path: None,
            retention: None,
            integrity: false,
            retention_floor: Some(Duration::days(DEFAULT_RETENTION_FLOOR_DAYS)),
        }
    }

    /// Set a soft target for the number of live events. `Some(n)` keeps
    /// roughly the most recent `n` in the live log; `None` is unbounded.
    ///
    /// Overflow **archives** the oldest events to `events.archive.jsonl`
    /// rather than deleting them: EU AI Act Art. 12 requires high-risk system
    /// logs to be retained (≥6 months, 24 for biometric / law enforcement),
    /// so a count cap must never be able to destroy evidence. Disk pressure
    /// becomes a visible operator problem instead — see `docs/SCALING.md`.
    ///
    /// For high-volume workloads prefer the `postgres` backend.
    pub fn with_retention(mut self, max_events: Option<usize>) -> Self {
        self.retention = max_events.filter(|n| *n > 0);
        self
    }

    /// Enable or disable the tamper-evident chain (ADR-017).
    pub fn with_integrity(mut self, enabled: bool) -> Self {
        self.integrity = enabled;
        self
    }

    /// Set the minimum age an event must reach before it may be evicted from
    /// the live log. Defaults to [`DEFAULT_RETENTION_FLOOR_DAYS`].
    ///
    /// **The floor outranks the count target.** If honouring the target would
    /// mean evicting an event younger than the floor, the store keeps the
    /// event and lets the live log grow past its target, incrementing
    /// `floor_blocked_total`. Art. 12 makes destroying a six-month-old log a
    /// conformity failure, whereas an oversized log is an operations problem —
    /// so when the two conflict, storage loses.
    ///
    /// `None` disables the floor. That is appropriate for development and for
    /// tests, and is not appropriate for a store holding high-risk system
    /// evidence.
    pub fn with_retention_floor(mut self, floor: Option<Duration>) -> Self {
        self.retention_floor = floor;
        self
    }

    /// Current retention counters.
    pub fn retention_stats(&self) -> RetentionStats {
        let inner = self.inner.lock().expect("event store mutex poisoned");
        RetentionStats {
            archived_total: inner.archived_total,
            floor_blocked_total: inner.floor_blocked_total,
            live_events: inner.events.len(),
        }
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
        let mut inner = Inner::empty();
        if path.exists() {
            let reader = BufReader::new(File::open(&path)?);
            for line in reader.lines() {
                let line = line?;
                if line.trim().is_empty() {
                    continue;
                }
                let event: AgentTraceEvent =
                    serde_json::from_str(&line).map_err(Error::InvalidEvent)?;
                // Provisional: the true observation time lives in the chain,
                // which has not been read yet. `restore_recorded_at` below
                // replaces this with the recorded value where one exists.
                let provisional = event.timestamp;
                Self::index_existing(&mut inner, event, provisional);
            }
        }

        let chain_path = Self::chain_path_for(&path);
        if chain_path.exists() {
            let reader = BufReader::new(File::open(&chain_path)?);
            for line in reader.lines() {
                let line = line?;
                if line.trim().is_empty() {
                    continue;
                }
                let entry: ChainEntry = serde_json::from_str(&line)
                    .map_err(|e| Error::Integrity(format!("malformed chain entry: {e}")))?;
                inner
                    .chains
                    .entry(entry.agent_id.clone())
                    .or_default()
                    .push(entry);
            }
        }
        inner.chain_file = Some(
            OpenOptions::new()
                .create(true)
                .append(true)
                .open(&chain_path)?,
        );
        Self::recover_chain_tails(&mut inner)?;
        Self::restore_recorded_at(&mut inner);

        inner.file = Some(OpenOptions::new().create(true).append(true).open(&path)?);
        Ok(Self {
            inner: Mutex::new(inner),
            path: Some(path),
            retention: None,
            integrity: true,
            retention_floor: Some(Duration::days(DEFAULT_RETENTION_FLOOR_DAYS)),
        })
    }

    fn chain_path_for(path: &Path) -> PathBuf {
        let mut name = path.as_os_str().to_os_string();
        name.push(".chain");
        PathBuf::from(name)
    }

    fn archive_path_for(path: &Path) -> PathBuf {
        path.with_extension("archive.jsonl")
    }

    /// Rebuild chain entries for events whose entry never made it to disk.
    ///
    /// The append path writes the event line, flushes, then writes the chain
    /// line, so a crash between the two leaves the chain a strict prefix of
    /// the event log. That is the *only* shape a crash can produce, so
    /// recovery appends the missing tail and nothing else.
    ///
    /// A chain that disagrees with the log in any other way — a `trace_id`
    /// mismatch, or more entries than events — is left exactly as found and
    /// reported as an anomaly. Silently rewriting it would destroy the
    /// evidence that something is wrong, which is the one thing this module
    /// exists to preserve.
    ///
    /// Recovered entries are marked `recovered: true` and stamped with the
    /// recovery time, because the original `recorded_at` is genuinely lost.
    /// They are persisted immediately so the hash is stable across restarts.
    /// Replace the provisional replay timestamps with the observation times
    /// recorded in the chain.
    ///
    /// Events with no chain entry keep their provisional value. That is the
    /// honest fallback: a log written with integrity disabled has no record
    /// of when the store saw each event, so the retention floor falls back to
    /// the client's timestamp and the operator is relying on the emitter.
    fn restore_recorded_at(inner: &mut Inner) {
        let mut updates: Vec<(usize, DateTime<Utc>)> = Vec::new();
        for entries in inner.chains.values() {
            for entry in entries {
                let Some(&idx) = inner.by_trace.get(&entry.trace_id) else {
                    continue;
                };
                if let Ok(observed) = DateTime::parse_from_rfc3339(&entry.recorded_at) {
                    updates.push((idx, observed.with_timezone(&Utc)));
                }
            }
        }
        for (idx, observed) in updates {
            if let Some(slot) = inner.recorded_at.get_mut(idx) {
                *slot = observed;
            }
        }
    }

    fn recover_chain_tails(inner: &mut Inner) -> Result<()> {
        let mut per_agent: HashMap<String, Vec<AgentTraceEvent>> = HashMap::new();
        for event in &inner.events {
            per_agent
                .entry(event.agent_id.clone())
                .or_default()
                .push(event.clone());
        }

        let mut agents: Vec<String> = per_agent.keys().cloned().collect();
        agents.sort();

        let mut recovered_lines: Vec<String> = Vec::new();
        for agent in agents {
            let Some(events) = per_agent.get(&agent) else {
                continue;
            };
            let existing = inner.chains.entry(agent.clone()).or_default();

            let misaligned = existing.len() > events.len()
                || existing
                    .iter()
                    .zip(events.iter())
                    .any(|(entry, event)| entry.trace_id != event.trace_id);
            if misaligned {
                inner.anomalies.push(format!(
                    "agent {agent:?}: chain does not align with the event log \
                     ({} entries, {} events); left untouched for verification to report",
                    existing.len(),
                    events.len()
                ));
                continue;
            }

            let recorded_at = Utc::now().to_rfc3339();
            for event in events.iter().skip(existing.len()) {
                let mut entry = ChainEntry::next(existing.last(), event, &recorded_at)?;
                entry.recovered = true;
                recovered_lines.push(serde_json::to_string(&entry).map_err(Error::InvalidEvent)?);
                existing.push(entry);
            }
        }

        if !recovered_lines.is_empty() {
            inner.anomalies.push(format!(
                "recovered {} chain entr{} after an unclean shutdown",
                recovered_lines.len(),
                if recovered_lines.len() == 1 {
                    "y"
                } else {
                    "ies"
                }
            ));
            if let Some(file) = inner.chain_file.as_mut() {
                for line in &recovered_lines {
                    writeln!(file, "{line}")?;
                }
                file.flush()?;
            }
        }
        Ok(())
    }

    /// Path of the underlying JSONL file, if persistent.
    pub fn path(&self) -> Option<&Path> {
        self.path.as_deref()
    }

    /// Chain problems observed when the log was opened, if any.
    ///
    /// Returned rather than logged so the caller decides how loudly to
    /// surface them; the guardian binary prints them at startup.
    pub fn chain_anomalies(&self) -> Vec<String> {
        let inner = self.inner.lock().expect("event store mutex poisoned");
        inner.anomalies.clone()
    }

    /// Recompute every agent's chain and report the first divergence in each.
    ///
    /// Archived events are read back from `events.archive.jsonl` so the check
    /// spans the archive boundary — an event moved out of the live log is
    /// still covered by the chain that commits to it.
    pub fn verify_chains(&self) -> Result<Vec<ChainVerification>> {
        let mut events: HashMap<uuid::Uuid, AgentTraceEvent> = HashMap::new();
        if let Some(archive) = self.path.as_deref().map(Self::archive_path_for) {
            if archive.exists() {
                let reader = BufReader::new(File::open(&archive)?);
                for line in reader.lines() {
                    let line = line?;
                    if line.trim().is_empty() {
                        continue;
                    }
                    let event: AgentTraceEvent =
                        serde_json::from_str(&line).map_err(Error::InvalidEvent)?;
                    events.insert(event.trace_id, event);
                }
            }
        }

        let inner = self.inner.lock().expect("event store mutex poisoned");
        for event in &inner.events {
            events.insert(event.trace_id, event.clone());
        }

        let mut agents: Vec<&String> = inner.chains.keys().collect();
        agents.sort();
        Ok(agents
            .into_iter()
            .map(|agent| {
                let entries = inner.chains.get(agent).map(Vec::as_slice).unwrap_or(&[]);
                verify_chain(agent, entries, &events)
            })
            .collect())
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
        // Event first, then its chain link: a crash between the two leaves the
        // chain a strict prefix, which `recover_chain_tails` can safely repair.
        // The reverse order would leave an entry with no event, which is
        // indistinguishable from deletion and must stay a hard failure.
        // The store's clock, not the event's `timestamp`: a client clock is
        // attacker-controlled and skewed across a fleet (ADR-017 §3). One
        // reading serves both the chain entry and the retention floor so the
        // two can never disagree about when this event arrived.
        let observed = Utc::now();
        if self.integrity {
            Self::append_chain_entry(&mut inner, &event, observed)?;
        }
        Self::index_existing(&mut inner, event, observed);
        self.enforce_retention(&mut inner)?;
        Ok(true)
    }

    /// Link one event into its agent's chain and persist the entry.
    fn append_chain_entry(
        inner: &mut Inner,
        event: &AgentTraceEvent,
        observed: DateTime<Utc>,
    ) -> Result<()> {
        let recorded_at = observed.to_rfc3339();
        let entry = {
            let prev = inner.chains.get(&event.agent_id).and_then(|c| c.last());
            ChainEntry::next(prev, event, &recorded_at)?
        };
        if let Some(file) = inner.chain_file.as_mut() {
            let line = serde_json::to_string(&entry).map_err(Error::InvalidEvent)?;
            writeln!(file, "{line}")?;
            file.flush()?;
        }
        inner
            .chains
            .entry(event.agent_id.clone())
            .or_default()
            .push(entry);
        Ok(())
    }

    /// Move the oldest events out of the live log once it overruns the
    /// retention target.
    ///
    /// **Archives, never deletes.** Art. 12 requires high-risk system logs to
    /// be retained for at least six months (24 for biometric and law
    /// enforcement), so a count-based target must not be able to destroy
    /// evidence. Overflowing events are appended to `events.archive.jsonl`
    /// before the live log is compacted; their chain entries stay in memory
    /// and on disk, so `verify_chains` still spans the boundary.
    ///
    /// Triggered lazily — only past `max + max/4` — so the O(n) index rebuild
    /// and file compaction amortise to O(1) per append in steady state.
    /// No-op when retention is unset.
    fn enforce_retention(&self, inner: &mut Inner) -> Result<()> {
        let Some(max) = self.retention else {
            return Ok(());
        };
        let slack = (max / 4).max(1);
        if inner.events.len() <= max + slack {
            return Ok(());
        }
        let wanted = inner.events.len() - max;

        // The floor outranks the target: walk the front of the log and stop at
        // the first event too young to evict. Because `recorded_at` is
        // non-decreasing (it is stamped on append), the first young event ends
        // the evictable prefix.
        let evictable = match self.retention_floor {
            Some(floor) => {
                let cutoff = Utc::now() - floor;
                inner
                    .recorded_at
                    .iter()
                    .take(wanted)
                    .take_while(|recorded| **recorded < cutoff)
                    .count()
            }
            None => wanted,
        };

        if evictable < wanted {
            // Not an error: the store is correctly refusing to destroy
            // evidence. It is a signal that disk needs attention.
            inner.floor_blocked_total += (wanted - evictable) as u64;
        }
        if evictable == 0 {
            return Ok(());
        }

        let evicted: Vec<AgentTraceEvent> = inner.events.drain(0..evictable).collect();
        inner.recorded_at.drain(0..evictable);

        // Archive before compacting: if the process dies between the two, the
        // events exist in both files, which dedupe on `trace_id` resolves.
        // Compacting first would risk losing them outright.
        self.archive_events(inner, &evicted)?;
        inner.archived_total += evicted.len() as u64;

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

    /// Append evicted events to the archive log.
    ///
    /// In-memory stores have nowhere to archive to; for them eviction is a
    /// genuine drop, which is why in-memory stores are documented as
    /// unsuitable for Art. 12 evidence.
    fn archive_events(&self, inner: &mut Inner, evicted: &[AgentTraceEvent]) -> Result<()> {
        if evicted.is_empty() {
            return Ok(());
        }
        let Some(path) = self.path.as_ref() else {
            return Ok(());
        };
        if inner.archive_file.is_none() {
            let archive = Self::archive_path_for(path);
            inner.archive_file = Some(
                OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(&archive)?,
            );
        }
        if let Some(file) = inner.archive_file.as_mut() {
            for event in evicted {
                let line = serde_json::to_string(event).map_err(Error::InvalidEvent)?;
                writeln!(file, "{line}")?;
            }
            file.flush()?;
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

    /// Index an event and record when the store observed it.
    ///
    /// `recorded_at` is kept in a vector parallel to `events` (drained in
    /// lockstep) rather than derived from `event.timestamp`, because the
    /// event timestamp is client-supplied: an emitter that back-dated its
    /// events could otherwise force the retention floor to evict evidence
    /// early. Store time is the only clock the floor can trust.
    fn index_existing(inner: &mut Inner, event: AgentTraceEvent, recorded_at: DateTime<Utc>) {
        if inner.by_trace.contains_key(&event.trace_id) {
            return;
        }
        let idx = inner.events.len();
        let key = (event.agent_id.clone(), event.session_id.clone());
        let trace_id = event.trace_id;
        inner.events.push(event);
        inner.recorded_at.push(recorded_at);
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
        // The floor is disabled here so the count target is what is under
        // test; `retention_floor_blocks_eviction_of_recent_events` covers the
        // default behaviour.
        let store = EventStore::in_memory()
            .with_retention(Some(4))
            .with_retention_floor(None);
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
            .with_retention(Some(3))
            .with_retention_floor(None);
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

    // --- Integrity chain (ADR-017) ---------------------------------------

    fn trace(n: u32) -> String {
        format!("{n:08x}-0000-4000-8000-000000000000")
    }

    #[test]
    fn jsonl_store_chains_appended_events() {
        let tmp = tempdir();
        let path = tmp.join("events.jsonl");
        let store = EventStore::open_jsonl(&path).expect("open");
        store.append(sample_event(&trace(1), "a", "s")).unwrap();
        store.append(sample_event(&trace(2), "a", "s")).unwrap();

        let results = store.verify_chains().expect("verify");

        assert_eq!(results.len(), 1);
        assert!(results[0].ok(), "{:?}", results[0]);
        assert_eq!(results[0].entries_checked, 2);
        assert!(EventStore::chain_path_for(&path).exists());
    }

    #[test]
    fn chain_survives_reopen() {
        let tmp = tempdir();
        let path = tmp.join("events.jsonl");
        {
            let store = EventStore::open_jsonl(&path).expect("open");
            store.append(sample_event(&trace(1), "a", "s")).unwrap();
            store.append(sample_event(&trace(2), "a", "s")).unwrap();
        }
        let reopened = EventStore::open_jsonl(&path).expect("reopen");
        reopened.append(sample_event(&trace(3), "a", "s")).unwrap();

        let results = reopened.verify_chains().expect("verify");

        assert!(results[0].ok(), "{:?}", results[0]);
        assert_eq!(results[0].entries_checked, 3);
        assert!(
            reopened.chain_anomalies().is_empty(),
            "clean reopen reported anomalies: {:?}",
            reopened.chain_anomalies()
        );
    }

    #[test]
    fn editing_the_event_log_is_detected_on_reopen() {
        let tmp = tempdir();
        let path = tmp.join("events.jsonl");
        {
            let store = EventStore::open_jsonl(&path).expect("open");
            for i in 1..=3 {
                store.append(sample_event(&trace(i), "a", "s")).unwrap();
            }
        }

        // Rewrite the middle line — the exact move a tamper-evident log exists
        // to catch.
        let text = std::fs::read_to_string(&path).expect("read log");
        let mut lines: Vec<String> = text.lines().map(str::to_string).collect();
        lines[1] = lines[1].replace("\"calc\"", "\"evil\"");
        std::fs::write(&path, format!("{}\n", lines.join("\n"))).expect("write log");

        let reopened = EventStore::open_jsonl(&path).expect("reopen");
        let results = reopened.verify_chains().expect("verify");

        assert!(!results[0].ok(), "tampering went undetected");
        assert_eq!(results[0].first_bad_seq.map(|s| s.get()), Some(2));
    }

    #[test]
    fn deleting_an_event_line_is_detected_on_reopen() {
        let tmp = tempdir();
        let path = tmp.join("events.jsonl");
        {
            let store = EventStore::open_jsonl(&path).expect("open");
            for i in 1..=3 {
                store.append(sample_event(&trace(i), "a", "s")).unwrap();
            }
        }

        let text = std::fs::read_to_string(&path).expect("read log");
        let kept: Vec<&str> = text
            .lines()
            .enumerate()
            .filter(|(i, _)| *i != 1)
            .map(|(_, l)| l)
            .collect();
        std::fs::write(&path, format!("{}\n", kept.join("\n"))).expect("write log");

        let reopened = EventStore::open_jsonl(&path).expect("reopen");

        // The surviving chain no longer aligns with the log, so recovery
        // refuses to touch it and says so.
        assert!(
            !reopened.chain_anomalies().is_empty(),
            "a misaligned chain must be reported, not silently repaired"
        );
        let results = reopened.verify_chains().expect("verify");
        assert!(!results[0].ok(), "deletion went undetected");
    }

    #[test]
    fn truncated_chain_tail_is_recovered_on_reopen() {
        let tmp = tempdir();
        let path = tmp.join("events.jsonl");
        {
            let store = EventStore::open_jsonl(&path).expect("open");
            for i in 1..=3 {
                store.append(sample_event(&trace(i), "a", "s")).unwrap();
            }
        }

        // Simulate a crash between the event write and the chain write.
        let chain_path = EventStore::chain_path_for(&path);
        let text = std::fs::read_to_string(&chain_path).expect("read chain");
        let kept: Vec<&str> = text.lines().take(2).collect();
        std::fs::write(&chain_path, format!("{}\n", kept.join("\n"))).expect("write chain");

        let reopened = EventStore::open_jsonl(&path).expect("reopen");

        let anomalies = reopened.chain_anomalies();
        assert!(
            anomalies.iter().any(|a| a.contains("recovered")),
            "recovery should be reported: {anomalies:?}"
        );
        let results = reopened.verify_chains().expect("verify");
        assert!(results[0].ok(), "{:?}", results[0]);
        assert_eq!(results[0].entries_checked, 3);
    }

    #[test]
    fn recovered_entries_are_stable_across_restarts() {
        // Recovery stamps a fresh `recorded_at`, so it must persist what it
        // built — otherwise every restart would produce a different hash.
        let tmp = tempdir();
        let path = tmp.join("events.jsonl");
        {
            let store = EventStore::open_jsonl(&path).expect("open");
            for i in 1..=3 {
                store.append(sample_event(&trace(i), "a", "s")).unwrap();
            }
        }
        let chain_path = EventStore::chain_path_for(&path);
        let text = std::fs::read_to_string(&chain_path).expect("read chain");
        std::fs::write(
            &chain_path,
            format!("{}\n", text.lines().next().unwrap_or_default()),
        )
        .expect("truncate chain");

        let first = EventStore::open_jsonl(&path).expect("first reopen");
        assert!(first.verify_chains().expect("verify")[0].ok());
        let after_recovery = std::fs::read_to_string(&chain_path).expect("read chain");
        drop(first);

        let second = EventStore::open_jsonl(&path).expect("second reopen");
        assert!(second.verify_chains().expect("verify")[0].ok());
        assert_eq!(
            std::fs::read_to_string(&chain_path).expect("read chain"),
            after_recovery,
            "a second clean reopen must not rewrite the chain"
        );
    }

    #[test]
    fn chains_are_independent_across_agents() {
        let tmp = tempdir();
        let path = tmp.join("events.jsonl");
        let store = EventStore::open_jsonl(&path).expect("open");
        store.append(sample_event(&trace(1), "a", "s")).unwrap();
        store.append(sample_event(&trace(2), "b", "s")).unwrap();
        store.append(sample_event(&trace(3), "a", "s")).unwrap();

        let results = store.verify_chains().expect("verify");

        assert_eq!(results.len(), 2);
        assert!(results.iter().all(|r| r.ok()), "{results:?}");
        let a = results.iter().find(|r| r.agent_id == "a").expect("agent a");
        let b = results.iter().find(|r| r.agent_id == "b").expect("agent b");
        assert_eq!(a.entries_checked, 2);
        assert_eq!(b.entries_checked, 1);
    }

    #[test]
    fn retention_archives_instead_of_deleting() {
        let tmp = tempdir();
        let path = tmp.join("events.jsonl");
        let store = EventStore::open_jsonl(&path)
            .unwrap()
            .with_retention(Some(3))
            .with_retention_floor(None);
        for i in 1..=30 {
            store.append(sample_event(&trace(i), "a", "s")).unwrap();
        }

        let archive = EventStore::archive_path_for(&path);
        assert!(archive.exists(), "overflow must be archived, not dropped");

        let archived = std::fs::read_to_string(&archive).expect("read archive");
        let live = store.list_events(&EventFilter::default());
        assert_eq!(
            archived.lines().count() + live.len(),
            30,
            "every event must survive somewhere"
        );
    }

    #[test]
    fn archived_events_still_verify_against_the_chain() {
        // The chain commits to events that are no longer in the live log;
        // verification must read them back from the archive.
        let tmp = tempdir();
        let path = tmp.join("events.jsonl");
        let store = EventStore::open_jsonl(&path)
            .unwrap()
            .with_retention(Some(3))
            .with_retention_floor(None);
        for i in 1..=30 {
            store.append(sample_event(&trace(i), "a", "s")).unwrap();
        }

        let results = store.verify_chains().expect("verify");

        assert!(results[0].ok(), "{:?}", results[0]);
        assert_eq!(results[0].entries_checked, 30);
    }

    // --- Retention floor (ADR-017 §7) ------------------------------------

    #[test]
    fn retention_floor_blocks_eviction_of_recent_events() {
        // The default floor is 180 days, so a count target must not be able to
        // evict evidence written moments ago. This is the G1 conformity fix:
        // before it, this loop silently destroyed 26 events.
        let tmp = tempdir();
        let path = tmp.join("events.jsonl");
        let store = EventStore::open_jsonl(&path)
            .unwrap()
            .with_retention(Some(3));
        for i in 1..=30 {
            store.append(sample_event(&trace(i), "a", "s")).unwrap();
        }

        let stats = store.retention_stats();

        assert_eq!(stats.archived_total, 0, "nothing should have been evicted");
        assert_eq!(stats.live_events, 30, "every event must still be live");
        assert!(
            stats.floor_blocked_total > 0,
            "the refusal must be counted so operators can see the log growing"
        );
        assert!(!EventStore::archive_path_for(&path).exists());
    }

    #[test]
    fn retention_floor_permits_eviction_once_events_age_past_it() {
        // A zero-length floor means every event is immediately old enough,
        // which isolates the age comparison from the count target.
        let tmp = tempdir();
        let path = tmp.join("events.jsonl");
        let store = EventStore::open_jsonl(&path)
            .unwrap()
            .with_retention(Some(3))
            .with_retention_floor(Some(Duration::zero()));
        for i in 1..=30 {
            store.append(sample_event(&trace(i), "a", "s")).unwrap();
        }

        let stats = store.retention_stats();

        assert!(stats.archived_total > 0, "aged events should be archivable");
        assert_eq!(stats.floor_blocked_total, 0);
        assert!(store.verify_chains().expect("verify")[0].ok());
    }

    #[test]
    fn retention_floor_uses_store_time_not_client_timestamps() {
        // An emitter that back-dates its events must not be able to force
        // early eviction; the floor reads the store's observation time.
        let tmp = tempdir();
        let path = tmp.join("events.jsonl");
        let store = EventStore::open_jsonl(&path)
            .unwrap()
            .with_retention(Some(3));
        for i in 1..=30 {
            let mut event = sample_event(&trace(i), "a", "s");
            event.timestamp = "2001-01-01T00:00:00+00:00"
                .parse()
                .expect("ancient timestamp");
            store.append(event).unwrap();
        }

        let stats = store.retention_stats();

        assert_eq!(
            stats.archived_total, 0,
            "back-dated client timestamps must not defeat the floor"
        );
        assert_eq!(stats.live_events, 30);
    }

    #[test]
    fn in_memory_store_skips_chaining_by_default() {
        let store = EventStore::in_memory();
        store.append(sample_event(&trace(1), "a", "s")).unwrap();
        assert!(store.verify_chains().expect("verify").is_empty());
    }

    #[test]
    fn in_memory_store_can_opt_into_chaining() {
        let store = EventStore::in_memory().with_integrity(true);
        store.append(sample_event(&trace(1), "a", "s")).unwrap();
        store.append(sample_event(&trace(2), "a", "s")).unwrap();

        let results = store.verify_chains().expect("verify");

        assert_eq!(results.len(), 1);
        assert!(results[0].ok(), "{:?}", results[0]);
    }
}
