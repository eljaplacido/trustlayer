//! `trustlayer-guardian` — HTTP sidecar exposing `cynepic-guardian` and a
//! Phase 5 trace-store read API.
//!
//! Listens on `TRUSTLAYER_BIND` (default `127.0.0.1:8089`). Loads its policy
//! from `TRUSTLAYER_POLICY` (default `./policies/default.json`). Persists
//! ingested events to JSONL at `TRUSTLAYER_EVENTS_PATH` (default
//! `./events.jsonl`; set to `""` to run in-memory only).
//!
//! ```text
//! POST /v1/check
//!   { "event": <AgentTraceEvent>, "policy_name": "default" }
//! -> 200 { "decision": "PASS" | "FAIL" | "ESCALATE", "rule": ..., "reason": ..., "policy": ... }
//!
//! POST /v1/events                                       (single event OR array)
//! -> 200 { "stored": N }
//!
//! GET /v1/events?agent_id=&session_id=&event_type=&limit=N   (list)
//! GET /v1/sessions                                      (per-(agent,session) summary)
//! GET /v1/sessions/:agent_id/:session_id                (one session)
//! GET /v1/reflections                                   (Hermes reflection notes)
//! GET /v1/reflections/:name                             (one reflection note)
//! GET /healthz                                          (liveness)
//! ```
//!
//! Reflection notes are read from `TRUSTLAYER_VAULT_PATH` (default
//! `./obsidian_vault`); generation stays Hermes's job.

use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;

use tokio::net::TcpListener;
use tracing::{info, warn};
use tracing_subscriber::EnvFilter;

use trustlayer_core::{build_router, AppState, CynepicGuardian, EventStore, Policy};

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

    let events_store = match std::env::var("TRUSTLAYER_EVENTS_PATH") {
        Ok(s) if s.is_empty() => {
            info!("Event store: in-memory (TRUSTLAYER_EVENTS_PATH=\"\")");
            EventStore::in_memory()
        }
        Ok(s) => {
            let p = PathBuf::from(s);
            info!("Event store: JSONL at {}", p.display());
            EventStore::open_jsonl(&p)?
        }
        Err(_) => {
            let p = PathBuf::from("events.jsonl");
            info!("Event store: JSONL at {} (default)", p.display());
            EventStore::open_jsonl(&p)?
        }
    };

    let vault_path = std::env::var("TRUSTLAYER_VAULT_PATH")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("obsidian_vault"));
    info!("Reflection vault: {}", vault_path.display());

    let state = AppState {
        guardian: Arc::new(CynepicGuardian::new(policy)),
        events: Arc::new(events_store),
        vault_path: Arc::new(vault_path),
    };

    let app = build_router(state);

    let bind: SocketAddr = std::env::var("TRUSTLAYER_BIND")
        .unwrap_or_else(|_| "127.0.0.1:8089".to_string())
        .parse()?;

    let listener = TcpListener::bind(bind).await?;
    info!("trustlayer-guardian listening on http://{bind}");
    axum::serve(listener, app).with_graceful_shutdown(shutdown_signal()).await?;
    Ok(())
}

async fn shutdown_signal() {
    let _ = tokio::signal::ctrl_c().await;
    info!("shutdown signal received; draining");
}
