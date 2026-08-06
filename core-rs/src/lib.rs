//! TrustLayer Core — Rust implementation of the policy / guardian layer.
//!
//! Mirrors the wire schema from `docs/SCHEMA.md` (see [`schema`]) and ships a
//! deterministic [`guardian::CynepicGuardian`] that turns a stream of agent
//! events into [`guardian::Verdict`]s.
//!
//! No `unwrap()`s on production paths — see `CLAUDE.md`.

#[cfg(feature = "server")]
pub mod auth;
pub mod checkpoint;
pub mod error;
pub mod events;
#[cfg(feature = "python")]
pub mod ffi;
pub mod guardian;
pub mod integrity;
#[cfg(feature = "server")]
pub mod metrics;
#[cfg(feature = "postgres")]
pub mod pg_store;
pub mod policy;
#[cfg(feature = "server")]
pub mod policy_watch;
#[cfg(feature = "server")]
pub mod rate_limit;
pub mod reflections;
pub mod schema;
#[cfg(feature = "server")]
pub mod server;

pub use checkpoint::{
    verify_checkpoint, Checkpoint, CheckpointPolicy, CheckpointSigner, DEFAULT_CHECKPOINT_EVERY,
    DEFAULT_CHECKPOINT_INTERVAL_SECS,
};
pub use error::{Error, Result};
pub use events::{
    ChainPage, ChainedEvent, EventFilter, EventStore, RetentionStats, SessionSummary, TraceStore,
    DEFAULT_RETENTION_FLOOR_DAYS,
};
pub use guardian::{CynepicGuardian, Verdict};
pub use integrity::{ChainEntry, ChainVerification, EventHash, Seq};
#[cfg(feature = "server")]
pub use metrics::ServerMetrics;
#[cfg(feature = "postgres")]
pub use pg_store::PostgresStore;
pub use policy::{MatchSpec, Policy, PolicyRule};
#[cfg(feature = "server")]
pub use rate_limit::IngestRateLimit;
pub use reflections::{Reflection, ReflectionMeta};
pub use schema::{AgentTraceEvent, CynefinDomain, Decision, EventType, Metrics};
#[cfg(feature = "server")]
pub use server::{build_router, AppState};
