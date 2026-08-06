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

use trustlayer_core::policy_watch::spawn_watcher;
use trustlayer_core::{
    build_router, AppState, CheckpointPolicy, CheckpointSigner, CynepicGuardian, EventStore,
    IngestRateLimit, Policy, ServerMetrics, TraceStore, DEFAULT_RETENTION_FLOOR_DAYS,
};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
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

    // Retention cap for the JSONL backend (Postgres relies on DB-side
    // retention / partitioning). Unset = unbounded.
    let retention = std::env::var("TRUSTLAYER_EVENT_RETENTION_MAX")
        .ok()
        .and_then(|s| s.parse::<usize>().ok())
        .filter(|n| *n > 0);

    // Minimum age before an event may leave the live log (ADR-017 §7).
    // Art. 12 requires >= 6 months for high-risk systems and 24 months for
    // biometric / law-enforcement ones, so the default is 180 days and
    // operators raise it. Setting 0 disables the floor explicitly.
    let retention_floor = match std::env::var("TRUSTLAYER_RETENTION_MIN_DAYS") {
        Ok(raw) => match raw.trim().parse::<i64>() {
            Ok(0) => None,
            Ok(days) if days > 0 => Some(chrono::Duration::days(days)),
            _ => {
                warn!(
                    "TRUSTLAYER_RETENTION_MIN_DAYS={raw:?} is not a non-negative \
                     integer; falling back to the {DEFAULT_RETENTION_FLOOR_DAYS}-day default"
                );
                Some(chrono::Duration::days(DEFAULT_RETENTION_FLOOR_DAYS))
            }
        },
        Err(_) => Some(chrono::Duration::days(DEFAULT_RETENTION_FLOOR_DAYS)),
    };

    // Backend selection: a non-empty TRUSTLAYER_DATABASE_URL chooses Postgres
    // (requires the `postgres` build feature); otherwise JSONL / in-memory.
    let pg_dsn = std::env::var("TRUSTLAYER_DATABASE_URL")
        .ok()
        .filter(|s| !s.is_empty());

    // Kept alongside the trait object so shutdown can commit a final
    // checkpoint — `TraceStore` is deliberately read-shaped and exposes no
    // way to force one.
    let jsonl_store: Option<Arc<EventStore>>;

    let events: Arc<dyn TraceStore> = if let Some(dsn) = pg_dsn {
        #[cfg(feature = "postgres")]
        {
            let pool_max = std::env::var("TRUSTLAYER_DB_MAX_CONNECTIONS")
                .ok()
                .and_then(|s| s.parse::<u32>().ok());
            info!(
                "Event store: Postgres (TRUSTLAYER_DATABASE_URL set, max_connections={})",
                pool_max.unwrap_or(10)
            );
            // Postgres checkpoints on its own schedule inside the backend;
            // there is no local EventStore to close out at shutdown.
            jsonl_store = None;
            Arc::new(trustlayer_core::PostgresStore::connect(&dsn, pool_max).await?)
        }
        #[cfg(not(feature = "postgres"))]
        {
            let _ = dsn;
            return Err("TRUSTLAYER_DATABASE_URL is set but this binary was built \
                 without the `postgres` feature. Rebuild with \
                 `cargo build --release --features server,postgres`."
                .into());
        }
    } else {
        let store = match std::env::var("TRUSTLAYER_EVENTS_PATH") {
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
        match retention {
            Some(n) => info!(
                "Event retention: target ~{n} live events; overflow is archived, never deleted"
            ),
            None => info!("Event retention: unbounded"),
        }
        match retention_floor {
            Some(d) => info!(
                "Retention floor: {} days — events younger than this are never evicted (Art. 12)",
                d.num_days()
            ),
            None => warn!(
                "Retention floor DISABLED (TRUSTLAYER_RETENTION_MIN_DAYS=0). \
                 A count target can now evict recent evidence; this is not \
                 appropriate for a store holding high-risk system logs."
            ),
        }

        // ADR-017 §5: commitments to the chain head. A key that is set but
        // unusable is fatal — degrading silently to unsigned would let a
        // deployment believe it is signing when it is not.
        let signer = CheckpointSigner::from_env()?;
        let checkpoint_policy = CheckpointPolicy::from_env();
        match (&signer, checkpoint_policy.is_disabled()) {
            (_, true) => warn!(
                "Chain checkpoints DISABLED. The chain still detects edits, but \
                 nothing commits its head outside this process, so a rebuilt log \
                 cannot be distinguished from an original one."
            ),
            (Some(s), false) => info!(
                "Chain checkpoints: signed with Ed25519 public key {}. \
                 Publish this key to auditors out of band.",
                s.public_key_hex()
            ),
            (None, false) => warn!(
                "Chain checkpoints: UNSIGNED (TRUSTLAYER_SIGNING_KEY not set). \
                 Archive them off-box for them to mean anything."
            ),
        }

        let store = Arc::new(
            store
                .with_retention(retention)
                .with_retention_floor(retention_floor)
                .with_checkpoint_policy(checkpoint_policy)
                .with_signer(signer),
        );
        for anomaly in store.chain_anomalies() {
            warn!("Event log integrity: {anomaly}");
        }
        jsonl_store = Some(store.clone());
        store
    };

    let vault_path = std::env::var("TRUSTLAYER_VAULT_PATH")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("obsidian_vault"));
    info!("Reflection vault: {}", vault_path.display());

    let api_token = match std::env::var("TRUSTLAYER_API_TOKEN") {
        Ok(s) if !s.is_empty() => {
            info!("Auth: bearer-token required (TRUSTLAYER_API_TOKEN set)");
            Some(Arc::new(s))
        }
        _ => {
            warn!("Auth: open — TRUSTLAYER_API_TOKEN not set.");
            None
        }
    };
    let auth_enabled = api_token.is_some();

    let guardian = Arc::new(CynepicGuardian::new(policy));

    // ADR-009: policy hot-reload (opt-out via TRUSTLAYER_POLICY_RELOAD=false).
    let reload_enabled = std::env::var("TRUSTLAYER_POLICY_RELOAD")
        .map(|v| !v.eq_ignore_ascii_case("false"))
        .unwrap_or(true);
    if reload_enabled {
        let _watcher = spawn_watcher(policy_path.clone(), guardian.clone());
        // Handle deliberately dropped — the task lives until the process
        // exits or the runtime shuts down.
    } else {
        info!("policy hot-reload disabled (TRUSTLAYER_POLICY_RELOAD=false)");
    }

    let ingest_rate_limit = Arc::new(IngestRateLimit::from_env());
    match ingest_rate_limit.limit_per_sec() {
        Some(n) => info!("Ingest rate-limit: {n} req/s on POST /v1/events"),
        None => info!("Ingest rate-limit: unlimited (TRUSTLAYER_INGEST_RATE_LIMIT_PER_SEC unset)"),
    }

    let state = AppState {
        guardian,
        events,
        vault_path: Arc::new(vault_path),
        api_token,
        metrics: Arc::new(ServerMetrics::new()),
        ingest_rate_limit,
    };

    let app = build_router(state);

    let bind: SocketAddr = std::env::var("TRUSTLAYER_BIND")
        .unwrap_or_else(|_| "127.0.0.1:8089".to_string())
        .parse()?;

    // Refuse to expose an unauthenticated server on a non-loopback interface.
    // Without a token, anyone who can reach the port can read every trace and
    // adjudicate against any policy. Set TRUSTLAYER_API_TOKEN, or explicitly
    // opt out with TRUSTLAYER_ALLOW_INSECURE=true (e.g. behind your own mTLS
    // proxy or an isolated network).
    let allow_insecure = std::env::var("TRUSTLAYER_ALLOW_INSECURE")
        .map(|v| v.eq_ignore_ascii_case("true"))
        .unwrap_or(false);
    if !auth_enabled && !bind.ip().is_loopback() && !allow_insecure {
        return Err(format!(
            "refusing to bind {bind}: no TRUSTLAYER_API_TOKEN set and the address is \
             not loopback. Set a token to require auth, or set \
             TRUSTLAYER_ALLOW_INSECURE=true to override."
        )
        .into());
    }
    if !auth_enabled && bind.ip().is_loopback() {
        warn!("Auth open — bound to loopback {bind}; safe for local dev only.");
    }

    let listener = TcpListener::bind(bind).await?;
    info!("trustlayer-guardian listening on http://{bind}");
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;

    // Commit a final checkpoint over whatever arrived since the last one. An
    // agent that stops 900 appends into a 1000-append interval would otherwise
    // leave its most recent — often most interesting — evidence uncommitted.
    if let Some(store) = jsonl_store {
        match store.force_checkpoints() {
            Ok(written) if !written.is_empty() => {
                info!("committed {} closing checkpoint(s)", written.len());
            }
            Ok(_) => {}
            // Loud, but never fatal: the events are already durable, and
            // exiting non-zero here would make a clean shutdown look failed.
            Err(err) => warn!("could not commit closing checkpoints: {err}"),
        }
    }
    Ok(())
}

async fn shutdown_signal() {
    let _ = tokio::signal::ctrl_c().await;
    info!("shutdown signal received; draining");
}
