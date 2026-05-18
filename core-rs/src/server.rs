//! Axum router + handlers for the `trustlayer-guardian` HTTP sidecar.
//!
//! Pulled out of the binary so integration tests in `core-rs/tests/` can
//! exercise the routes through `tower::ServiceExt::oneshot` without binding
//! a TCP port.

use std::sync::Arc;

use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::{Deserialize, Serialize};
use tower_http::cors::{Any, CorsLayer};

use crate::events::{EventFilter, EventStore};
use crate::guardian::{CynepicGuardian, Verdict};
use crate::schema::AgentTraceEvent;

#[derive(Clone)]
pub struct AppState {
    pub guardian: Arc<CynepicGuardian>,
    pub events: Arc<EventStore>,
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
    limit: Option<usize>,
}

#[derive(Serialize)]
struct IngestResponse {
    stored: usize,
}

/// Build the Axum router used by both the binary and the integration tests.
pub fn build_router(state: AppState) -> Router {
    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);
    Router::new()
        .route("/v1/check", post(check_handler))
        .route("/v1/events", post(ingest_handler).get(list_events_handler))
        .route("/v1/sessions", get(list_sessions_handler))
        .route("/v1/sessions/:agent_id/:session_id", get(get_session_handler))
        .route("/healthz", get(|| async { "ok" }))
        .layer(cors)
        .with_state(state)
}

async fn check_handler(
    State(state): State<AppState>,
    Json(req): Json<CheckRequest>,
) -> impl IntoResponse {
    let verdict: Verdict = state.guardian.evaluate(&req.event);
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
    match state.events.append_batch(events) {
        Ok(stored) => (StatusCode::OK, Json(IngestResponse { stored })).into_response(),
        Err(err) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({"error": err.to_string()})),
        )
            .into_response(),
    }
}

async fn list_events_handler(
    State(state): State<AppState>,
    Query(q): Query<ListEventsQuery>,
) -> impl IntoResponse {
    let filter = EventFilter {
        agent_id: q.agent_id,
        session_id: q.session_id,
        limit: q.limit,
    };
    let events = state.events.list_events(&filter);
    (StatusCode::OK, Json(events))
}

async fn list_sessions_handler(State(state): State<AppState>) -> impl IntoResponse {
    let sessions = state.events.list_sessions();
    (StatusCode::OK, Json(sessions))
}

async fn get_session_handler(
    State(state): State<AppState>,
    Path((agent_id, session_id)): Path<(String, String)>,
) -> impl IntoResponse {
    let events = state.events.get_session(&agent_id, &session_id);
    (StatusCode::OK, Json(events))
}
