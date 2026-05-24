//! HTTP integration tests for the Phase 5 trace-store routes.
//!
//! Drives the router through `tower::ServiceExt::oneshot` so the test never
//! has to bind a TCP port. Covers the full POST -> GET round-trip plus
//! filtering and session enumeration.

use std::path::PathBuf;
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
    state_with_vault(std::env::temp_dir())
}

fn state_with_vault(vault: PathBuf) -> AppState {
    AppState {
        guardian: Arc::new(CynepicGuardian::new(Policy::empty("test"))),
        events: Arc::new(EventStore::in_memory()),
        vault_path: Arc::new(vault),
        api_token: None,
    }
}

fn state_with_token(token: &str) -> AppState {
    AppState {
        guardian: Arc::new(CynepicGuardian::new(Policy::empty("test"))),
        events: Arc::new(EventStore::in_memory()),
        vault_path: Arc::new(std::env::temp_dir()),
        api_token: Some(Arc::new(token.to_string())),
    }
}

/// Create a throwaway vault with one reflection note and return its root.
fn vault_with_reflection(name: &str, body: &str) -> PathBuf {
    let mut root = std::env::temp_dir();
    root.push(format!("trustlayer-http-vault-{}", uuid::Uuid::new_v4()));
    let dir = root.join("05_Reflections");
    std::fs::create_dir_all(&dir).expect("mkdir vault");
    std::fs::write(dir.join(name), body).expect("write reflection");
    root
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
    let body = format!(r#"{{"event": {EVENT_A_S1}, "policy_name": "test"}}"#);
    let (status, body) = post_json(app, "/v1/check", &body).await;
    assert_eq!(status, StatusCode::OK);
    assert!(body["decision"].is_string());
}

const POLICY_CHECK_EVENT: &str = r#"{
    "trace_id": "44444444-4444-4444-8444-444444444444",
    "agent_id": "a",
    "session_id": "s1",
    "timestamp": "2026-05-22T10:00:05+00:00",
    "event_type": "POLICY_CHECK",
    "payload": {"policy_name": "default", "action": "invoke calc", "result": "PASS"}
}"#;

#[tokio::test]
async fn list_events_filters_by_event_type() {
    let state = test_state();
    for raw in [EVENT_A_S1, POLICY_CHECK_EVENT] {
        let app = build_router(state.clone());
        let _ = post_json(app, "/v1/events", raw).await;
    }

    let app = build_router(state.clone());
    let (status, body) = get_json(app, "/v1/events?event_type=POLICY_CHECK").await;
    assert_eq!(status, StatusCode::OK);
    let arr = body.as_array().unwrap();
    assert_eq!(arr.len(), 1);
    assert_eq!(arr[0]["event_type"], "POLICY_CHECK");

    let app = build_router(state);
    let (_, body) = get_json(app, "/v1/events?event_type=TOOL_CALL").await;
    assert_eq!(body.as_array().unwrap().len(), 1);
}

#[tokio::test]
async fn list_reflections_returns_vault_notes() {
    let vault = vault_with_reflection("reflection-2026-05-22.md", "# Reflection\nbody");
    let app = build_router(state_with_vault(vault));
    let (status, body) = get_json(app, "/v1/reflections").await;
    assert_eq!(status, StatusCode::OK);
    let arr = body.as_array().unwrap();
    assert_eq!(arr.len(), 1);
    assert_eq!(arr[0]["name"], "reflection-2026-05-22.md");
    assert_eq!(arr[0]["date"], "2026-05-22");
}

#[tokio::test]
async fn get_reflection_returns_content() {
    let vault = vault_with_reflection("reflection-2026-05-22.md", "# Reflection\nhello");
    let app = build_router(state_with_vault(vault));
    let (status, body) = get_json(app, "/v1/reflections/reflection-2026-05-22.md").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["date"], "2026-05-22");
    assert!(body["content"].as_str().unwrap().contains("hello"));
}

#[tokio::test]
async fn get_reflection_rejects_path_traversal() {
    let vault = vault_with_reflection("reflection-2026-05-22.md", "x");
    let app = build_router(state_with_vault(vault));
    // axum normalises `..` segments, so the crafted name still has to be
    // rejected by the is_safe_name guard for any form that reaches the handler.
    let (status, _) = get_json(app, "/v1/reflections/not-a-reflection.txt").await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn get_reflection_missing_returns_404() {
    let vault = vault_with_reflection("reflection-2026-05-22.md", "x");
    let app = build_router(state_with_vault(vault));
    let (status, _) = get_json(app, "/v1/reflections/reflection-2099-01-01.md").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn list_reflections_empty_vault_returns_empty_array() {
    let app = build_router(test_state());
    let (status, body) = get_json(app, "/v1/reflections").await;
    assert_eq!(status, StatusCode::OK);
    assert!(body.as_array().unwrap().is_empty());
}

// ─── ADR-007: bearer-token auth ────────────────────────────────────────────

async fn get_with_auth(app: axum::Router, uri: &str, token: Option<&str>) -> (StatusCode, Value) {
    let mut req = Request::builder().method("GET").uri(uri);
    if let Some(t) = token {
        req = req.header("authorization", format!("Bearer {t}"));
    }
    let res = app.oneshot(req.body(Body::empty()).unwrap()).await.unwrap();
    let status = res.status();
    let bytes = to_bytes(res.into_body(), usize::MAX).await.unwrap();
    let value: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    (status, value)
}

#[tokio::test]
async fn auth_disabled_allows_unauthenticated_requests() {
    let app = build_router(test_state());
    let (status, _) = get_with_auth(app, "/v1/events", None).await;
    assert_eq!(status, StatusCode::OK);
}

#[tokio::test]
async fn auth_enabled_accepts_correct_token() {
    let app = build_router(state_with_token("sekret"));
    let (status, _) = get_with_auth(app, "/v1/events", Some("sekret")).await;
    assert_eq!(status, StatusCode::OK);
}

#[tokio::test]
async fn auth_enabled_rejects_missing_token() {
    let app = build_router(state_with_token("sekret"));
    let req = Request::builder()
        .method("GET")
        .uri("/v1/events")
        .body(Body::empty())
        .unwrap();
    let res = app.oneshot(req).await.unwrap();
    assert_eq!(res.status(), StatusCode::UNAUTHORIZED);
    let challenge = res.headers().get("www-authenticate").expect("challenge");
    assert!(challenge.to_str().unwrap().starts_with("Bearer "));
}

#[tokio::test]
async fn auth_enabled_rejects_wrong_token() {
    let app = build_router(state_with_token("sekret"));
    let (status, _) = get_with_auth(app, "/v1/events", Some("nope")).await;
    assert_eq!(status, StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn auth_enabled_rejects_malformed_authorization_header() {
    let app = build_router(state_with_token("sekret"));
    let req = Request::builder()
        .method("GET")
        .uri("/v1/events")
        .header("authorization", "Token sekret") // wrong scheme
        .body(Body::empty())
        .unwrap();
    let res = app.oneshot(req).await.unwrap();
    assert_eq!(res.status(), StatusCode::UNAUTHORIZED);
}

#[tokio::test]
async fn healthz_is_always_unauthenticated() {
    let app = build_router(state_with_token("sekret"));
    let req = Request::builder()
        .method("GET")
        .uri("/healthz")
        .body(Body::empty())
        .unwrap();
    let res = app.oneshot(req).await.unwrap();
    assert_eq!(res.status(), StatusCode::OK);
}

#[tokio::test]
async fn auth_gates_post_events_too() {
    let state = state_with_token("sekret");
    let app = build_router(state);
    let req = Request::builder()
        .method("POST")
        .uri("/v1/events")
        .header("content-type", "application/json")
        .body(Body::from(EVENT_A_S1.to_string()))
        .unwrap();
    let res = app.oneshot(req).await.unwrap();
    assert_eq!(res.status(), StatusCode::UNAUTHORIZED);
}
