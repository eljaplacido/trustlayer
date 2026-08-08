//! Error type for the trustlayer-core library.

use thiserror::Error;

#[derive(Debug, Error)]
pub enum Error {
    #[error("invalid event JSON: {0}")]
    InvalidEvent(#[source] serde_json::Error),

    #[error("invalid policy JSON: {0}")]
    InvalidPolicy(#[source] serde_json::Error),

    /// A policy that parses but contains a predicate that could never behave
    /// as its author intended (ADR-018). Rejected at load rather than silently
    /// never matching.
    #[error("invalid rule {rule:?}: {reason}")]
    InvalidPolicyRule { rule: String, reason: String },

    #[error("io error: {0}")]
    Io(#[from] std::io::Error),

    #[error("storage backend error: {0}")]
    Storage(String),

    /// A malformed or unverifiable entry in the tamper-evident chain
    /// (ADR-017). Distinct from [`Error::Storage`] because an integrity
    /// failure is evidence of a problem with the log itself, not with the
    /// backend serving it.
    #[error("integrity error: {0}")]
    Integrity(String),
}

pub type Result<T> = std::result::Result<T, Error>;
