//! Axum router + handlers for the `trustlayer-guardian` HTTP sidecar.
//!
//! Pulled out of the binary so integration tests in `core-rs/tests/` can
//! exercise the routes through `tower::ServiceExt::oneshot` without binding
//! a TCP port.

use std::path::PathBuf;
use std::sync::Arc;

use axum::extract::{Path, Query, State};
use axum::http::{header, StatusCode};
use axum::middleware;
use axum::response::IntoResponse;
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::{Deserialize, Serialize};
use tower_http::cors::{Any, CorsLayer};

use crate::auth::require_token;
use crate::events::{EventFilter, TraceStore};
use crate::guardian::{CynepicGuardian, Verdict};
use crate::integrity::Seq;
use crate::metrics::{track_requests, ServerMetrics};
use crate::rate_limit::{rate_limit, IngestRateLimit};
use crate::reflections;
use crate::schema::{AgentTraceEvent, EventType};

#[derive(Clone)]
pub struct AppState {
    pub guardian: Arc<CynepicGuardian>,
    /// Trace store backend — JSONL [`EventStore`](crate::events::EventStore) by
    /// default, or [`PostgresStore`](crate::pg_store::PostgresStore) when built
    /// with the `postgres` feature and given a `TRUSTLAYER_DATABASE_URL`.
    pub events: Arc<dyn TraceStore>,
    /// Obsidian vault root — reflection notes live under `05_Reflections/`.
    pub vault_path: Arc<PathBuf>,
    /// Optional shared bearer token (ADR-007). `None` = open; `Some(_)` =
    /// every route except `/healthz` requires `Authorization: Bearer ...`.
    pub api_token: Option<Arc<String>>,
    /// Prometheus metrics registry + handles (Slice 3).
    pub metrics: Arc<ServerMetrics>,
    /// Per-second rate limiter applied to `POST /v1/events` (Slice 3).
    /// Constructed with `IngestRateLimit::new(None)` to disable.
    pub ingest_rate_limit: Arc<IngestRateLimit>,
}

#[derive(Deserialize)]
struct CheckRequest {
    event: AgentTraceEvent,
    #[serde(default)]
    #[allow(dead_code)] // reserved for multi-policy support
    policy_name: Option<String>,
}

/// Accepts either a single event or an array on `POST /v1/events`.
#[derive(Deserialize)]
#[serde(untagged)]
enum EventBody {
    Single(Box<AgentTraceEvent>),
    Batch(Vec<AgentTraceEvent>),
}

#[derive(Deserialize, Default)]
struct ListEventsQuery {
    agent_id: Option<String>,
    session_id: Option<String>,
    event_type: Option<EventType>,
    limit: Option<usize>,
    after_seq: Option<u64>,
}

/// Query for `GET /v1/events/chained` (ADR-017 §6).
#[derive(Deserialize)]
struct ChainPageQuery {
    agent_id: String,
    after_seq: Option<u64>,
    limit: Option<usize>,
}

/// Query for the `/v1/integrity/*` routes.
#[derive(Deserialize, Default)]
struct IntegrityQuery {
    agent_id: Option<String>,
}

#[derive(Serialize)]
struct IngestResponse {
    stored: usize,
}

/// Response for `GET /v1/integrity/verify`.
#[derive(Serialize)]
struct VerifyResponse {
    /// True only when every chain in `chains` verified.
    ok: bool,
    chains: Vec<crate::integrity::ChainVerification>,
}

/// Response for `GET /v1/integrity/checkpoints`.
#[derive(Serialize)]
struct CheckpointsResponse {
    checkpoints: Vec<crate::checkpoint::Checkpoint>,
    /// Number of checkpoints carrying a signature this server could verify
    /// against the key they embed.
    ///
    /// Reported separately from the count so a client can see at a glance that
    /// a stored checkpoint has stopped verifying. **This does not establish
    /// authenticity**: the key travels in the same response as the signature,
    /// so an auditor must compare it against a key received out of band. Said
    /// plainly here because a UI that renders this as a green tick would be
    /// making a claim the data cannot support.
    verified_signatures: usize,
    /// Checkpoints that claim a signature which does not hold. Any non-zero
    /// value is a finding, not a warning.
    invalid_signatures: usize,
}

/// Build the Axum router used by both the binary and the integration tests.
///
/// `/healthz` and `/metrics` are mounted **outside** the auth middleware so
/// liveness probes and Prometheus scrapers work even with
/// `TRUSTLAYER_API_TOKEN` set (ADR-007 + Slice 3).
pub fn build_router(state: AppState) -> Router {
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    // POST/GET /v1/events share a route in axum, but only the POST should
    // be rate-limited. We split them so the limiter applies asymmetrically.
    let ingest_only = Router::new()
        .route("/v1/events", post(ingest_handler))
        .route_layer(middleware::from_fn_with_state(state.clone(), rate_limit));

    let protected = ingest_only
        .merge(
            Router::new()
                .route("/v1/check", post(check_handler))
                .route("/v1/events", get(list_events_handler))
                .route("/v1/events/chained", get(chain_page_handler))
                .route("/v1/integrity/verify", get(integrity_verify_handler))
                .route(
                    "/v1/integrity/checkpoints",
                    get(integrity_checkpoints_handler),
                )
                .route("/v1/sessions", get(list_sessions_handler))
                .route(
                    "/v1/sessions/:agent_id/:session_id",
                    get(get_session_handler),
                )
                .route("/v1/reflections", get(list_reflections_handler))
                .route("/v1/reflections/:name", get(get_reflection_handler)),
        )
        .route_layer(middleware::from_fn_with_state(state.clone(), require_token));

    Router::new()
        .merge(protected)
        .route("/healthz", get(|| async { "ok" }))
        .route("/metrics", get(metrics_handler))
        // The request-tracking middleware runs for *every* route — including
        // /healthz and /metrics — so the dashboards can see scrape volume.
        .route_layer(middleware::from_fn_with_state(
            state.clone(),
            track_requests,
        ))
        .layer(cors)
        .with_state(state)
}

async fn check_handler(
    State(state): State<AppState>,
    Json(req): Json<CheckRequest>,
) -> impl IntoResponse {
    let timer = state.metrics.check_duration_seconds.start_timer();
    let verdict: Verdict = state.guardian.evaluate(&req.event);
    timer.observe_duration();
    state.metrics.record_decision(verdict.decision);
    (StatusCode::OK, Json(verdict))
}

async fn ingest_handler(
    State(state): State<AppState>,
    Json(body): Json<EventBody>,
) -> impl IntoResponse {
    let events: Vec<AgentTraceEvent> = match body {
        EventBody::Single(e) => vec![*e],
        EventBody::Batch(v) => v,
    };
    match state.events.append_batch(events).await {
        Ok(stored) => {
            state.metrics.events_ingested_total.inc_by(stored as u64);
            (StatusCode::OK, Json(IngestResponse { stored })).into_response()
        }
        Err(err) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": err.to_string()})),
        )
            .into_response(),
    }
}

async fn metrics_handler(State(state): State<AppState>) -> impl IntoResponse {
    // Pull the store's own counters at scrape time; the store is the authority
    // on its retention state, and mirroring it into a second counter would
    // drift the moment either side restarts.
    if let Some(stats) = state.events.evidence_stats().await {
        state.metrics.observe_evidence(stats);
    }
    let body = state.metrics.render();
    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "text/plain; version=0.0.4")],
        body,
    )
}

async fn list_events_handler(
    State(state): State<AppState>,
    Query(q): Query<ListEventsQuery>,
) -> impl IntoResponse {
    // Chain sequence numbers are scoped per agent (ADR-017 §2), so a cursor
    // without an agent names no position. Rejecting beats silently returning
    // a differently-scoped page: a paging evidence consumer would skip events
    // and never know it.
    if q.after_seq.is_some() && q.agent_id.is_none() {
        return bad_request("after_seq requires agent_id: chain positions are scoped per agent");
    }

    let filter = EventFilter {
        agent_id: q.agent_id,
        session_id: q.session_id,
        event_type: q.event_type,
        limit: q.limit,
        after_seq: q.after_seq.map(Seq::new),
    };
    match state.events.list_events(&filter).await {
        Ok(events) => (StatusCode::OK, Json(events)).into_response(),
        Err(err) => store_error(err),
    }
}

/// `GET /v1/events/chained` — events with the chain metadata committing to
/// them, paged by chain position.
///
/// A separate route rather than a new shape on `GET /v1/events`: making one
/// route return two different response bodies depending on a query parameter
/// would break every client that has to handle both.
async fn chain_page_handler(
    State(state): State<AppState>,
    Query(q): Query<ChainPageQuery>,
) -> impl IntoResponse {
    match state
        .events
        .chain_page(&q.agent_id, q.after_seq.map(Seq::new), q.limit)
        .await
    {
        Ok(page) => (StatusCode::OK, Json(page)).into_response(),
        Err(err) => integrity_error(err),
    }
}

/// `GET /v1/integrity/verify` — recompute chains and report divergences.
async fn integrity_verify_handler(
    State(state): State<AppState>,
    Query(q): Query<IntegrityQuery>,
) -> impl IntoResponse {
    match state.events.verify_chains(q.agent_id.as_deref()).await {
        Ok(chains) => {
            let ok = chains.iter().all(|c| c.ok());
            (StatusCode::OK, Json(VerifyResponse { ok, chains })).into_response()
        }
        Err(err) => integrity_error(err),
    }
}

/// `GET /v1/integrity/checkpoints` — the signed commitments to chain heads.
async fn integrity_checkpoints_handler(
    State(state): State<AppState>,
    Query(q): Query<IntegrityQuery>,
) -> impl IntoResponse {
    match state.events.checkpoints(q.agent_id.as_deref()).await {
        Ok(checkpoints) => {
            let mut verified_signatures = 0usize;
            let mut invalid_signatures = 0usize;
            for checkpoint in &checkpoints {
                match crate::checkpoint::verify_checkpoint(checkpoint) {
                    Ok(true) => verified_signatures += 1,
                    // Unsigned: a fact about the checkpoint, not a failure.
                    Ok(false) => {}
                    Err(_) => invalid_signatures += 1,
                }
            }
            (
                StatusCode::OK,
                Json(CheckpointsResponse {
                    checkpoints,
                    verified_signatures,
                    invalid_signatures,
                }),
            )
                .into_response()
        }
        Err(err) => integrity_error(err),
    }
}

fn bad_request(message: &str) -> axum::response::Response {
    (
        StatusCode::BAD_REQUEST,
        Json(serde_json::json!({"error": message})),
    )
        .into_response()
}

/// Map an integrity failure to a response.
///
/// A backend that keeps no chain is a **501**, not a 500: the request was
/// well-formed and the server is working correctly, it just cannot make the
/// attestation asked of it. Returning 500 would read as a transient fault an
/// evidence consumer should retry, when in fact it must reconfigure.
fn integrity_error(err: crate::error::Error) -> axum::response::Response {
    let status = match err {
        crate::error::Error::Integrity(_) => StatusCode::NOT_IMPLEMENTED,
        _ => StatusCode::INTERNAL_SERVER_ERROR,
    };
    (status, Json(serde_json::json!({"error": err.to_string()}))).into_response()
}

async fn list_sessions_handler(State(state): State<AppState>) -> impl IntoResponse {
    match state.events.list_sessions().await {
        Ok(sessions) => (StatusCode::OK, Json(sessions)).into_response(),
        Err(err) => store_error(err),
    }
}

async fn get_session_handler(
    State(state): State<AppState>,
    Path((agent_id, session_id)): Path<(String, String)>,
) -> impl IntoResponse {
    match state.events.get_session(&agent_id, &session_id).await {
        Ok(events) => (StatusCode::OK, Json(events)).into_response(),
        Err(err) => store_error(err),
    }
}

/// Map a trace-store backend failure to a 500 with a JSON error body.
fn store_error(err: crate::error::Error) -> axum::response::Response {
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(serde_json::json!({"error": err.to_string()})),
    )
        .into_response()
}

async fn list_reflections_handler(State(state): State<AppState>) -> impl IntoResponse {
    match reflections::list(state.vault_path.as_ref()) {
        Ok(metas) => (StatusCode::OK, Json(metas)).into_response(),
        Err(err) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": err.to_string()})),
        )
            .into_response(),
    }
}

async fn get_reflection_handler(
    State(state): State<AppState>,
    Path(name): Path<String>,
) -> impl IntoResponse {
    if !reflections::is_safe_name(&name) {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error": "invalid reflection name"})),
        )
            .into_response();
    }
    match reflections::read(state.vault_path.as_ref(), &name) {
        Ok(Some(reflection)) => (StatusCode::OK, Json(reflection)).into_response(),
        Ok(None) => (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({"error": "reflection not found"})),
        )
            .into_response(),
        Err(err) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": err.to_string()})),
        )
            .into_response(),
    }
}
