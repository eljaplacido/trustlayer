//! `trustlayer-guardian` — tiny HTTP sidecar exposing `cynepic-guardian`.
//!
//! Listens on `TRUSTLAYER_BIND` (default `127.0.0.1:8089`). Loads its policy
//! from `TRUSTLAYER_POLICY` (default `./policies/default.json`).
//!
//! ```text
//! POST /v1/check
//!   { "event": <AgentTraceEvent>, "policy_name": "default" }
//! -> 200 { "decision": "PASS" | "FAIL" | "ESCALATE", "rule": ..., "reason": ..., "policy": ... }
//!
//! GET /healthz -> 200 "ok"
//! ```

use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::Deserialize;
use tokio::net::TcpListener;
use tracing::{info, warn};
use tracing_subscriber::EnvFilter;

use trustlayer_core::{AgentTraceEvent, CynepicGuardian, Policy, Verdict};

#[derive(Deserialize)]
struct CheckRequest {
    event: AgentTraceEvent,
    #[serde(default)]
    #[allow(dead_code)] // reserved for multi-policy support
    policy_name: Option<String>,
}

#[derive(Clone)]
struct AppState {
    guardian: Arc<CynepicGuardian>,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")))
        .init();

    let policy_path = std::env::var("TRUSTLAYER_POLICY")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("policies/default.json"));
    let policy = Policy::from_path(&policy_path).map_err(|e| {
        warn!("Failed to load policy from {}: {e}", policy_path.display());
        e
    })?;
    info!(
        "Loaded policy '{}' with {} rules from {}",
        policy.name,
        policy.rules.len(),
        policy_path.display()
    );

    let state = AppState {
        guardian: Arc::new(CynepicGuardian::new(policy)),
    };

    let app = Router::new()
        .route("/v1/check", post(check_handler))
        .route("/healthz", get(|| async { "ok" }))
        .with_state(state);

    let bind: SocketAddr = std::env::var("TRUSTLAYER_BIND")
        .unwrap_or_else(|_| "127.0.0.1:8089".to_string())
        .parse()?;

    let listener = TcpListener::bind(bind).await?;
    info!("trustlayer-guardian listening on http://{bind}");
    axum::serve(listener, app).with_graceful_shutdown(shutdown_signal()).await?;
    Ok(())
}

async fn check_handler(
    State(state): State<AppState>,
    Json(req): Json<CheckRequest>,
) -> impl IntoResponse {
    let verdict: Verdict = state.guardian.evaluate(&req.event);
    (StatusCode::OK, Json(verdict))
}

async fn shutdown_signal() {
    let _ = tokio::signal::ctrl_c().await;
    info!("shutdown signal received; draining");
}
