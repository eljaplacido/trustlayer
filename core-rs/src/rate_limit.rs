//! Per-route rate limit on `POST /v1/events` (Slice 3).
//!
//! In-house token-bucket-per-second. Trades a few atomics for a tower
//! crate dependency and a 429 response with `Retry-After: 1`, which is
//! what every other HTTP ingest API does.
//!
//! Configured by the operator via `TRUSTLAYER_INGEST_RATE_LIMIT_PER_SEC`:
//! - unset / `0` → no limit (default; matches the open-by-default UX).
//! - positive integer → at most N successful ingest requests per second
//!   per sidecar process.
//!
//! Sliding-window precision is "one second"; the implementation tolerates
//! the textbook race at the second boundary because the slack is bounded
//! to a small multi-allow and we're rate-limiting humans/agents, not
//! cryptographic timing.

use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use axum::body::Body;
use axum::extract::State;
use axum::http::{header, Request, StatusCode};
use axum::middleware::Next;
use axum::response::{IntoResponse, Response};

use crate::server::AppState;

#[derive(Debug)]
pub struct IngestRateLimit {
    /// Allowed requests per second. `None` disables the limiter.
    limit: Option<u32>,
    window_start_sec: AtomicU64,
    count: AtomicU32,
}

impl IngestRateLimit {
    /// Construct a limiter that allows `limit` requests per second.
    /// Passing `None` (or `Some(0)`) disables the limiter entirely.
    pub fn new(limit: Option<u32>) -> Self {
        Self {
            limit: limit.filter(|n| *n > 0),
            window_start_sec: AtomicU64::new(now_seconds()),
            count: AtomicU32::new(0),
        }
    }

    pub fn from_env() -> Self {
        let limit = std::env::var("TRUSTLAYER_INGEST_RATE_LIMIT_PER_SEC")
            .ok()
            .and_then(|s| s.parse::<u32>().ok());
        Self::new(limit)
    }

    pub fn limit_per_sec(&self) -> Option<u32> {
        self.limit
    }

    /// Returns `Ok` if the request is allowed; `Err` carries the
    /// `Retry-After` hint (always 1 second under this design).
    fn try_acquire(&self) -> Result<(), u64> {
        let Some(max) = self.limit else {
            return Ok(());
        };
        let now_sec = now_seconds();
        let last = self.window_start_sec.load(Ordering::Acquire);
        if now_sec != last
            && self
                .window_start_sec
                .compare_exchange(last, now_sec, Ordering::AcqRel, Ordering::Acquire)
                .is_ok()
        {
            self.count.store(0, Ordering::Release);
        }
        let next = self.count.fetch_add(1, Ordering::AcqRel) + 1;
        if next <= max {
            Ok(())
        } else {
            Err(1)
        }
    }
}

fn now_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/// Axum middleware. Apply only to the routes that need it (e.g.
/// `POST /v1/events`) — applying it globally would also clamp reads.
pub async fn rate_limit(
    State(state): State<AppState>,
    request: Request<Body>,
    next: Next,
) -> Response {
    match state.ingest_rate_limit.try_acquire() {
        Ok(()) => next.run(request).await,
        Err(retry_after_sec) => (
            StatusCode::TOO_MANY_REQUESTS,
            [(header::RETRY_AFTER, retry_after_sec.to_string())],
            "rate limit exceeded\n",
        )
            .into_response(),
    }
}

/// Convenience constructor used by `AppState`-builders / tests.
pub fn shared(limit: Option<u32>) -> Arc<IngestRateLimit> {
    Arc::new(IngestRateLimit::new(limit))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unlimited_when_disabled() {
        let r = IngestRateLimit::new(None);
        for _ in 0..1000 {
            r.try_acquire().expect("unlimited");
        }
    }

    #[test]
    fn rejects_when_over_per_second_limit() {
        let r = IngestRateLimit::new(Some(3));
        r.try_acquire().unwrap();
        r.try_acquire().unwrap();
        r.try_acquire().unwrap();
        assert!(r.try_acquire().is_err());
    }

    #[test]
    fn zero_limit_is_treated_as_disabled() {
        let r = IngestRateLimit::new(Some(0));
        assert!(r.limit_per_sec().is_none());
        for _ in 0..100 {
            r.try_acquire().unwrap();
        }
    }
}
