//! TrustLayer Core — Rust implementation of the policy / guardian layer.
//!
//! Mirrors the wire schema from `docs/SCHEMA.md` (see [`schema`]) and ships a
//! deterministic [`guardian::CynepicGuardian`] that turns a stream of agent
//! events into [`guardian::Verdict`]s.
//!
//! No `unwrap()`s on production paths — see `CLAUDE.md`.

pub mod error;
pub mod guardian;
pub mod policy;
pub mod schema;

pub use error::{Error, Result};
pub use guardian::{CynepicGuardian, Verdict};
pub use policy::{MatchSpec, Policy, PolicyRule};
pub use schema::{AgentTraceEvent, CynefinDomain, Decision, EventType, Metrics};
