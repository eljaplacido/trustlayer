//! Error type for the trustlayer-core library.

use thiserror::Error;

#[derive(Debug, Error)]
pub enum Error {
    #[error("invalid event JSON: {0}")]
    InvalidEvent(#[source] serde_json::Error),

    #[error("invalid policy JSON: {0}")]
    InvalidPolicy(#[source] serde_json::Error),

    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

pub type Result<T> = std::result::Result<T, Error>;
