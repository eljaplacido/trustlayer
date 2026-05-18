//! HTTP integration tests for the Phase 5 trace-store routes.
//!
//! Drives the router through `tower::ServiceExt::oneshot` so the test never
//! has to bind a TCP port. Covers the full POST -> GET round-trip plus
//! filtering and session enumeration.

use std::sync::Arc;

use axum::body::{to_bytes, Body};
use axum::http::{Request, StatusCode};
use serde_json::Value;
use tower::ServiceExt;

use trustlayer_core::{build_router, AppState, CynepicGuardian, EventStore, Policy};

const EVENT_A_S1: &str = r#"{
    "trace_id": "11111111-1111-4111-8111-111111111111",
    "agent_id": "a",
    "session_id": "s1",
    "timestamp": "2026-05-18T10:00:00+00:00",
    "event_type": "TOOL_CALL",
    "payload": {"tool_name": "calc"}
}"#;

const EVENT_A_S2: &str = r#"{
    "trace_id": "22222222-2222-4222-8222-222222222222",
    "agent_id": "a",
    "session_id": "s2",
    "timestamp": "2026-05-18T10:00:01+00:00",
    "event_type": "TOOL_CALL",
    "payload": {"tool_name": "search"}
}"#;

const EVENT_B_S1: &str = r#"{
    "trace_id": "33333333-3333-4333-8333-333333333333",
    "agent_id": "b",
    "session_id": "s1",
    "timestamp": "2026-05-18T10:00:02+00:00",
    "event_type": "TOOL_CALL",
    "payload": {"tool_name": "summarise"}
}"#;

fn test_state() -> AppState {
    AppState {
        guardian: Arc::new(CynepicGuardian::new(Policy::empty("test"))),
        events: Arc::new(EventStore::in_memory()),
    }
}

async fn post_json(app: axum::Router, uri: &str, body: &str) -> (StatusCode, Value) {
    let req = Request::builder()
        .method("POST")
        .uri(uri)
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .unwrap();
    let res = app.oneshot(req).await.unwrap();
    let status = res.status();
    let bytes = to_bytes(res.into_body(), usize::MAX).await.unwrap();
    let value: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    (status, value)
}

async fn get_json(app: axum::Router, uri: &str) -> (StatusCode, Value) {
    let req = Request::builder()
        .method("GET")
        .uri(uri)
        .body(Body::empty())
        .unwrap();
    let res = app.oneshot(req).await.unwrap();
    let status = res.status();
    let bytes = to_bytes(res.into_body(), usize::MAX).await.unwrap();
    let value: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    (status, value)
}

#[tokio::test]
async fn post_single_event_stores_one() {
    let state = test_state();
    let app = build_router(state.clone());
    let (status, body) = post_json(app, "/v1/events", EVENT_A_S1).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["stored"], 1);
}

#[tokio::test]
async fn post_batch_stores_all_and_dedupes() {
    let state = test_state();
    let batch = format!("[{EVENT_A_S1},{EVENT_A_S2},{EVENT_A_S1}]");
    let app = build_router(state.clone());
    let (status, body) = post_json(app, "/v1/events", &batch).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["stored"], 2, "duplicate trace_id should be deduped");

    let app = build_router(state);
    let (_, list) = get_json(app, "/v1/events").await;
    assert_eq!(list.as_array().unwrap().len(), 2);
}

#[tokio::test]
async fn list_events_filters_by_agent_and_session() {
    let state = test_state();
    for raw in [EVENT_A_S1, EVENT_A_S2, EVENT_B_S1] {
        let app = build_router(state.clone());
        let (status, _) = post_json(app, "/v1/events", raw).await;
        assert_eq!(status, StatusCode::OK);
    }

    let app = build_router(state.clone());
    let (_, body) = get_json(app, "/v1/events?agent_id=a").await;
    assert_eq!(body.as_array().unwrap().len(), 2);

    let app = build_router(state.clone());
    let (_, body) = get_json(app, "/v1/events?agent_id=a&session_id=s2").await;
    let arr = body.as_array().unwrap();
    assert_eq!(arr.len(), 1);
    assert_eq!(arr[0]["session_id"], "s2");

    let app = build_router(state);
    let (_, body) = get_json(app, "/v1/events?limit=1").await;
    assert_eq!(body.as_array().unwrap().len(), 1);
}

#[tokio::test]
async fn list_sessions_returns_per_pair_summary() {
    let state = test_state();
    for raw in [EVENT_A_S1, EVENT_A_S2, EVENT_B_S1] {
        let app = build_router(state.clone());
        let _ = post_json(app, "/v1/events", raw).await;
    }

    let app = build_router(state);
    let (status, body) = get_json(app, "/v1/sessions").await;
    assert_eq!(status, StatusCode::OK);
    let arr = body.as_array().unwrap();
    assert_eq!(arr.len(), 3);
    for s in arr {
        assert!(s["agent_id"].is_string());
        assert!(s["session_id"].is_string());
        assert!(s["event_count"].as_u64().unwrap() >= 1);
        assert!(s["first_seen"].is_string());
        assert!(s["last_seen"].is_string());
    }
}

#[tokio::test]
async fn get_session_returns_only_that_sessions_events() {
    let state = test_state();
    for raw in [EVENT_A_S1, EVENT_A_S2, EVENT_B_S1] {
        let app = build_router(state.clone());
        let _ = post_json(app, "/v1/events", raw).await;
    }

    let app = build_router(state);
    let (status, body) = get_json(app, "/v1/sessions/a/s1").await;
    assert_eq!(status, StatusCode::OK);
    let arr = body.as_array().unwrap();
    assert_eq!(arr.len(), 1);
    assert_eq!(arr[0]["agent_id"], "a");
    assert_eq!(arr[0]["session_id"], "s1");
}

#[tokio::test]
async fn check_route_still_works_after_event_routes_added() {
    let state = test_state();
    let app = build_router(state);
    let body = format!(
        r#"{{"event": {EVENT_A_S1}, "policy_name": "test"}}"#
    );
    let (status, body) = post_json(app, "/v1/check", &body).await;
    assert_eq!(status, StatusCode::OK);
    assert!(body["decision"].is_string());
}
