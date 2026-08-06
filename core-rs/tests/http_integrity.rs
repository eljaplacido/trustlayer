//! HTTP integration tests for the Art. 12 integrity routes (ADR-017 §6).
//!
//! Drives the router through `tower::ServiceExt::oneshot` so the test never
//! has to bind a TCP port, matching `http_events.rs`.
//!
//! These cover the surface an auditor actually touches: paging a chain,
//! verifying it, reading checkpoints, and — most importantly — that a
//! *tampered* log is reported as tampered over HTTP rather than only in the
//! library. A verification route that cannot fail in an integration test is
//! not evidence of anything.

use std::sync::Arc;

use axum::body::{to_bytes, Body};
use axum::http::{Request, StatusCode};
use serde_json::Value;
use tower::ServiceExt;

use trustlayer_core::{
    build_router, AppState, CheckpointPolicy, CheckpointSigner, CynepicGuardian, EventStore,
    IngestRateLimit, Policy, ServerMetrics,
};

/// A fixed seed so signatures are reproducible across runs. Test-only.
const SEED: &str = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60";

fn event(trace: &str, agent: &str, session: &str) -> String {
    format!(
        r#"{{
            "trace_id": "{trace}",
            "agent_id": "{agent}",
            "session_id": "{session}",
            "timestamp": "2026-08-05T10:00:00+00:00",
            "event_type": "TOOL_CALL",
            "payload": {{"tool_name": "calc"}}
        }}"#
    )
}

fn trace(n: u32) -> String {
    format!("{n:08x}-0000-4000-8000-000000000000")
}

fn state_with(store: EventStore) -> AppState {
    AppState {
        guardian: Arc::new(CynepicGuardian::new(Policy::empty("test"))),
        events: Arc::new(store),
        vault_path: Arc::new(std::env::temp_dir()),
        api_token: None,
        metrics: Arc::new(ServerMetrics::new()),
        ingest_rate_limit: Arc::new(IngestRateLimit::new(None)),
    }
}

/// A chained in-memory store that checkpoints on every append.
fn chained_state() -> AppState {
    state_with(
        EventStore::in_memory()
            .with_integrity(true)
            .with_checkpoint_policy(CheckpointPolicy {
                every_events: Some(1),
                interval_secs: None,
            })
            .with_signer(Some(CheckpointSigner::from_hex(SEED).expect("seed"))),
    )
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

/// Ingest `count` events for `agent` through the HTTP surface.
async fn seed_events(state: &AppState, agent: &str, count: u32) {
    for i in 1..=count {
        let (status, _) = post_json(
            build_router(state.clone()),
            "/v1/events",
            &event(&trace(i), agent, "s1"),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
    }
}

// --- GET /v1/events/chained ------------------------------------------------

#[tokio::test]
async fn chained_returns_events_with_their_chain_positions() {
    let state = chained_state();
    seed_events(&state, "a", 3).await;

    let (status, body) = get_json(build_router(state), "/v1/events/chained?agent_id=a").await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["agent_id"], "a");
    let events = body["events"].as_array().expect("events array");
    assert_eq!(events.len(), 3);
    assert_eq!(events[0]["seq"], 1);
    assert_eq!(body["head_seq"], 3);
    // Chain metadata sits alongside the event, never inside the v0.1 envelope.
    assert!(events[0]["event"]["trace_id"].is_string());
    assert!(events[0]["event"]["seq"].is_null());
    assert_eq!(events[0]["hash"].as_str().expect("hash").len(), 64);
}

#[tokio::test]
async fn chained_pages_through_the_whole_chain() {
    let state = chained_state();
    seed_events(&state, "a", 5).await;

    let mut seen = Vec::new();
    let mut uri = "/v1/events/chained?agent_id=a&limit=2".to_string();
    loop {
        let (status, body) = get_json(build_router(state.clone()), &uri).await;
        assert_eq!(status, StatusCode::OK);
        for e in body["events"].as_array().expect("events") {
            seen.push(e["seq"].as_u64().expect("seq"));
        }
        match body["next_after_seq"].as_u64() {
            Some(next) => uri = format!("/v1/events/chained?agent_id=a&limit=2&after_seq={next}"),
            None => break,
        }
    }

    assert_eq!(seen, vec![1, 2, 3, 4, 5]);
}

#[tokio::test]
async fn chained_requires_an_agent_id() {
    // agent_id is not optional: chain positions are scoped per agent, so a
    // page without one names no chain.
    let state = chained_state();
    let (status, _) = get_json(build_router(state), "/v1/events/chained").await;

    assert_eq!(status, StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn chained_is_501_when_the_backend_keeps_no_chain() {
    // Not 500: the request is fine and the server is healthy, it simply
    // cannot attest. A 500 would read as a transient fault worth retrying.
    let state = state_with(EventStore::in_memory());
    seed_events(&state, "a", 1).await;

    let (status, body) = get_json(build_router(state), "/v1/events/chained?agent_id=a").await;

    assert_eq!(status, StatusCode::NOT_IMPLEMENTED);
    assert!(body["error"].as_str().expect("error").contains("integrity"));
}

// --- GET /v1/events?after_seq= ---------------------------------------------

#[tokio::test]
async fn list_events_accepts_an_after_seq_cursor() {
    let state = chained_state();
    seed_events(&state, "a", 5).await;

    let (status, body) = get_json(build_router(state), "/v1/events?agent_id=a&after_seq=3").await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(body.as_array().expect("array").len(), 2);
}

#[tokio::test]
async fn after_seq_without_agent_id_is_rejected() {
    let state = chained_state();
    seed_events(&state, "a", 2).await;

    let (status, body) = get_json(build_router(state), "/v1/events?after_seq=1").await;

    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert!(body["error"]
        .as_str()
        .expect("error")
        .contains("requires agent_id"));
}

#[tokio::test]
async fn list_events_without_a_cursor_keeps_its_v0_1_shape() {
    // The response is a bare array, unchanged from v0.1. Every existing SDK
    // and the dashboard depend on this; adding a cursor must not reshape it.
    let state = chained_state();
    seed_events(&state, "a", 2).await;

    let (status, body) = get_json(build_router(state), "/v1/events").await;

    assert_eq!(status, StatusCode::OK);
    assert!(body.is_array(), "response must stay a bare array: {body}");
}

// --- GET /v1/integrity/verify ----------------------------------------------

#[tokio::test]
async fn verify_reports_ok_for_an_intact_chain() {
    let state = chained_state();
    seed_events(&state, "a", 3).await;

    let (status, body) = get_json(build_router(state), "/v1/integrity/verify").await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["ok"], true);
    let chains = body["chains"].as_array().expect("chains");
    assert_eq!(chains.len(), 1);
    assert_eq!(chains[0]["agent_id"], "a");
    assert_eq!(chains[0]["verified_through_seq"], 3);
    assert!(chains[0]["first_bad_seq"].is_null());
}

#[tokio::test]
async fn verify_can_be_scoped_to_one_agent() {
    // P7 data minimisation: verifying system X must not disclose system Y.
    let state = chained_state();
    seed_events(&state, "a", 2).await;
    let (status, _) = post_json(
        build_router(state.clone()),
        "/v1/events",
        &event(&trace(99), "b", "s1"),
    )
    .await;
    assert_eq!(status, StatusCode::OK);

    let (status, body) = get_json(build_router(state), "/v1/integrity/verify?agent_id=a").await;

    assert_eq!(status, StatusCode::OK);
    let chains = body["chains"].as_array().expect("chains");
    assert_eq!(chains.len(), 1);
    assert_eq!(chains[0]["agent_id"], "a");
}

#[tokio::test]
async fn verify_detects_a_tampered_log_over_http() {
    // The test that makes the route worth having. A file-backed store is
    // edited underneath the server, reopened, and verification must fail at
    // the edited position.
    let mut dir = std::env::temp_dir();
    dir.push(format!(
        "trustlayer-http-integrity-{}",
        uuid::Uuid::new_v4()
    ));
    std::fs::create_dir_all(&dir).expect("mkdir");
    let path = dir.join("events.jsonl");

    {
        let state = state_with(EventStore::open_jsonl(&path).expect("open"));
        seed_events(&state, "a", 3).await;
    }

    // Rewrite the second line's payload, leaving the chain untouched.
    let contents = std::fs::read_to_string(&path).expect("read");
    let mut lines: Vec<String> = contents.lines().map(str::to_string).collect();
    lines[1] = lines[1].replace(r#""tool_name":"calc""#, r#""tool_name":"evil""#);
    assert!(
        lines[1].contains("evil"),
        "the edit did not apply: {}",
        lines[1]
    );
    std::fs::write(&path, format!("{}\n", lines.join("\n"))).expect("write");

    let state = state_with(EventStore::open_jsonl(&path).expect("reopen"));
    let (status, body) = get_json(build_router(state), "/v1/integrity/verify").await;

    assert_eq!(
        status,
        StatusCode::OK,
        "a tampered log is still a valid response"
    );
    assert_eq!(body["ok"], false, "tampering must be reported: {body}");
    assert_eq!(body["chains"][0]["first_bad_seq"], 2);
}

#[tokio::test]
async fn verify_is_501_when_the_backend_keeps_no_chain() {
    let state = state_with(EventStore::in_memory());
    let (status, _) = get_json(build_router(state), "/v1/integrity/verify").await;

    assert_eq!(status, StatusCode::NOT_IMPLEMENTED);
}

// --- GET /v1/integrity/checkpoints -----------------------------------------

#[tokio::test]
async fn checkpoints_are_listed_with_a_verified_signature_count() {
    let state = chained_state();
    seed_events(&state, "a", 2).await;

    let (status, body) = get_json(build_router(state), "/v1/integrity/checkpoints").await;

    assert_eq!(status, StatusCode::OK);
    let checkpoints = body["checkpoints"].as_array().expect("checkpoints");
    assert_eq!(checkpoints.len(), 2);
    assert_eq!(body["verified_signatures"], 2);
    assert_eq!(body["invalid_signatures"], 0);
    assert_eq!(
        checkpoints[0]["public_key"].as_str().expect("key").len(),
        64
    );
    assert_eq!(
        checkpoints[0]["signature"].as_str().expect("sig").len(),
        128
    );
}

#[tokio::test]
async fn unsigned_checkpoints_are_listed_but_not_counted_as_verified() {
    // "Unsigned" and "signed but broken" must never be conflated.
    let state = state_with(
        EventStore::in_memory()
            .with_integrity(true)
            .with_checkpoint_policy(CheckpointPolicy {
                every_events: Some(1),
                interval_secs: None,
            }),
    );
    seed_events(&state, "a", 1).await;

    let (status, body) = get_json(build_router(state), "/v1/integrity/checkpoints").await;

    assert_eq!(status, StatusCode::OK);
    assert_eq!(body["checkpoints"].as_array().expect("array").len(), 1);
    assert_eq!(body["verified_signatures"], 0);
    assert_eq!(body["invalid_signatures"], 0);
    assert!(body["checkpoints"][0]["signature"].is_null());
}

#[tokio::test]
async fn checkpoints_can_be_scoped_to_one_agent() {
    let state = chained_state();
    seed_events(&state, "a", 1).await;
    post_json(
        build_router(state.clone()),
        "/v1/events",
        &event(&trace(99), "b", "s1"),
    )
    .await;

    let (status, body) =
        get_json(build_router(state), "/v1/integrity/checkpoints?agent_id=b").await;

    assert_eq!(status, StatusCode::OK);
    let checkpoints = body["checkpoints"].as_array().expect("checkpoints");
    assert_eq!(checkpoints.len(), 1);
    assert_eq!(checkpoints[0]["agent_id"], "b");
}

#[tokio::test]
async fn checkpoints_is_501_when_the_backend_keeps_no_chain() {
    let state = state_with(EventStore::in_memory());
    let (status, _) = get_json(build_router(state), "/v1/integrity/checkpoints").await;

    assert_eq!(status, StatusCode::NOT_IMPLEMENTED);
}

// --- Metrics ---------------------------------------------------------------

#[tokio::test]
async fn evidence_gauges_are_exported_and_reflect_the_store() {
    let state = chained_state();
    seed_events(&state, "a", 3).await;

    let req = Request::builder()
        .method("GET")
        .uri("/metrics")
        .body(Body::empty())
        .unwrap();
    let res = build_router(state).oneshot(req).await.unwrap();
    assert_eq!(res.status(), StatusCode::OK);
    let bytes = to_bytes(res.into_body(), usize::MAX).await.unwrap();
    let body = String::from_utf8(bytes.to_vec()).expect("utf-8");

    for name in [
        "trustlayer_retention_live_events",
        "trustlayer_retention_archived_total",
        "trustlayer_retention_floor_blocked_total",
        "trustlayer_integrity_checkpoints_total",
        "trustlayer_integrity_chains_total",
    ] {
        assert!(body.contains(name), "{name} missing from /metrics");
    }
    // Values are refreshed from the store at scrape time, not hard-coded.
    assert!(
        body.contains("trustlayer_retention_live_events 3"),
        "gauge was not refreshed from the store: {body}"
    );
    assert!(body.contains("trustlayer_integrity_chains_total 1"));
}

#[tokio::test]
async fn metrics_still_serve_when_the_store_tracks_nothing() {
    // A scrape must never fail because the backend has no counters, or the
    // operator loses the signals that would explain why.
    let state = state_with(EventStore::in_memory());
    let req = Request::builder()
        .method("GET")
        .uri("/metrics")
        .body(Body::empty())
        .unwrap();
    let res = build_router(state).oneshot(req).await.unwrap();

    assert_eq!(res.status(), StatusCode::OK);
}

// --- Auth ------------------------------------------------------------------

#[tokio::test]
async fn integrity_routes_are_behind_the_bearer_token() {
    // Evidence routes disclose an agent's whole history; they must not be
    // reachable when the deployment has set a token (ADR-007).
    let mut state = chained_state();
    state.api_token = Some(Arc::new("secret".into()));

    for uri in [
        "/v1/integrity/verify",
        "/v1/integrity/checkpoints",
        "/v1/events/chained?agent_id=a",
    ] {
        let (status, _) = get_json(build_router(state.clone()), uri).await;
        assert_eq!(status, StatusCode::UNAUTHORIZED, "{uri} was reachable");
    }
}
