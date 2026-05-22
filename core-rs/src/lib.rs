//! TrustLayer Core — Rust implementation of the policy / guardian layer.
//!
//! Mirrors the wire schema from `docs/SCHEMA.md` (see [`schema`]) and ships a
//! deterministic [`guardian::CynepicGuardian`] that turns a stream of agent
//! events into [`guardian::Verdict`]s.
//!
//! No `unwrap()`s on production paths — see `CLAUDE.md`.

pub mod error;
pub mod events;
pub mod guardian;
pub mod policy;
pub mod reflections;
pub mod schema;
#[cfg(feature = "server")]
pub mod server;

pub use error::{Error, Result};
pub use events::{EventFilter, EventStore, SessionSummary};
pub use guardian::{CynepicGuardian, Verdict};
pub use policy::{MatchSpec, Policy, PolicyRule};
pub use reflections::{Reflection, ReflectionMeta};
pub use schema::{AgentTraceEvent, CynefinDomain, Decision, EventType, Metrics};
#[cfg(feature = "server")]
pub use server::{build_router, AppState};
