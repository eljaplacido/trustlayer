//! Prometheus metrics for the `trustlayer-guardian` sidecar (Slice 3).
//!
//! The metrics live behind an [`Arc<Metrics>`] on [`crate::server::AppState`]
//! so handlers can update them lock-free (`IntCounter` and friends are
//! internally atomic). A single text-format exposition is served from
//! `GET /metrics` — outside the auth middleware, like `/healthz`, because
//! observability scrapers are deployment-tier signals rather than user
//! traffic.
//!
//! Time series exposed:
//! - `trustlayer_requests_total{route, status}` — HTTP request count.
//! - `trustlayer_check_total{decision}` — `/v1/check` verdict count by
//!   PASS / FAIL / ESCALATE.
//! - `trustlayer_events_ingested_total` — cumulative count of *newly
//!   stored* events through `POST /v1/events` (deduped on `trace_id`).
//! - `trustlayer_check_duration_seconds` — `/v1/check` latency histogram
//!   (default buckets, microseconds-to-seconds bracket).

use axum::body::Body;
use axum::extract::{MatchedPath, State};
use axum::http::Request;
use axum::middleware::Next;
use axum::response::Response;
use prometheus::{
    Histogram, HistogramOpts, IntCounter, IntCounterVec, Opts, Registry, TextEncoder,
};

use crate::schema::Decision;
use crate::server::AppState;

#[derive(Clone)]
pub struct ServerMetrics {
    pub registry: Registry,
    pub requests_total: IntCounterVec,
    pub check_total: IntCounterVec,
    pub events_ingested_total: IntCounter,
    pub check_duration_seconds: Histogram,
}

impl ServerMetrics {
    pub fn new() -> Self {
        let registry = Registry::new();

        let requests_total = IntCounterVec::new(
            Opts::new(
                "trustlayer_requests_total",
                "Count of HTTP requests handled by the sidecar.",
            ),
            &["route", "status"],
        )
        .expect("requests_total construction");
        let check_total = IntCounterVec::new(
            Opts::new(
                "trustlayer_check_total",
                "Count of policy verdicts emitted by /v1/check, by decision.",
            ),
            &["decision"],
        )
        .expect("check_total construction");
        let events_ingested_total = IntCounter::new(
            "trustlayer_events_ingested_total",
            "Cumulative count of newly-stored events accepted by POST /v1/events.",
        )
        .expect("events_ingested_total construction");
        let check_duration_seconds = Histogram::with_opts(HistogramOpts::new(
            "trustlayer_check_duration_seconds",
            "Latency of /v1/check evaluation, in seconds.",
        ))
        .expect("check_duration_seconds construction");

        registry
            .register(Box::new(requests_total.clone()))
            .expect("register requests_total");
        registry
            .register(Box::new(check_total.clone()))
            .expect("register check_total");
        registry
            .register(Box::new(events_ingested_total.clone()))
            .expect("register events_ingested_total");
        registry
            .register(Box::new(check_duration_seconds.clone()))
            .expect("register check_duration_seconds");

        // Pre-touch every label combination we'll ever emit so the family
        // appears in `/metrics` from process start — otherwise scrapers see
        // the counter "vanish" until the first request, which is confusing
        // when wiring up dashboards.
        for d in ["PASS", "FAIL", "ESCALATE"] {
            check_total.with_label_values(&[d]).inc_by(0);
        }

        Self {
            registry,
            requests_total,
            check_total,
            events_ingested_total,
            check_duration_seconds,
        }
    }

    pub fn record_decision(&self, decision: Decision) {
        let label = match decision {
            Decision::Pass => "PASS",
            Decision::Fail => "FAIL",
            Decision::Escalate => "ESCALATE",
        };
        self.check_total.with_label_values(&[label]).inc();
    }

    pub fn render(&self) -> String {
        let mfs = self.registry.gather();
        let mut buf = String::new();
        let encoder = TextEncoder::new();
        if let Err(err) = encoder.encode_utf8(&mfs, &mut buf) {
            return format!("# metrics encode error: {err}\n");
        }
        buf
    }
}

impl Default for ServerMetrics {
    fn default() -> Self {
        Self::new()
    }
}

/// Axum middleware that increments `trustlayer_requests_total{route, status}`
/// on every request. The `route` label is the matched router template (e.g.
/// `/v1/sessions/:agent_id/:session_id`), **not** the literal URI — that
/// keeps cardinality bounded.
pub async fn track_requests(
    State(state): State<AppState>,
    matched: Option<MatchedPath>,
    request: Request<Body>,
    next: Next,
) -> Response {
    let route = matched
        .as_ref()
        .map(|m| m.as_str())
        .unwrap_or("<unmatched>")
        .to_string();
    let response = next.run(request).await;
    let status = response.status().as_u16().to_string();
    state
        .metrics
        .requests_total
        .with_label_values(&[&route, &status])
        .inc();
    response
}
