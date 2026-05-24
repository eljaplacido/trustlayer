//! Policy hot-reload watcher (ADR-009).
//!
//! Spawn one [`spawn_watcher`] per running guardian. It watches the policy
//! file for modify/create events, debounces them to 200 ms, re-parses the
//! file, and — on success — calls
//! [`crate::guardian::CynepicGuardian::replace_policy`]. Parse failures are
//! logged at WARN and leave the live policy untouched, matching the rest
//! of the sidecar's "never take down the host" posture.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use notify::{Event, EventKind, RecursiveMode, Watcher};
use tokio::sync::mpsc;
use tracing::{info, warn};

use crate::guardian::CynepicGuardian;
use crate::policy::Policy;

const DEBOUNCE: Duration = Duration::from_millis(200);

/// Arm a filesystem watcher on `path` and spawn the reload loop. The
/// watcher is registered **synchronously before this function returns**, so
/// any file change after the call is guaranteed to be observed (no
/// post-spawn race with the test or operator's next write).
///
/// Filesystem events arrive on a `tokio::mpsc::channel`; after each event
/// the loop sleeps [`DEBOUNCE`] and then drains every pending event before
/// attempting one reload. This collapses bursts (editors that rename-then-
/// create on save) into a single parse.
///
/// Returns the join handle for the reload-loop task. The watcher itself is
/// owned by the task and lives as long as it does.
pub fn spawn_watcher(path: PathBuf, guardian: Arc<CynepicGuardian>) -> tokio::task::JoinHandle<()> {
    let (tx, rx) = mpsc::channel::<Event>(16);

    let watcher_result = notify::recommended_watcher(move |res: notify::Result<Event>| {
        if let Ok(event) = res {
            // Best-effort: a closed receiver means the loop task is gone.
            let _ = tx.blocking_send(event);
        }
    });

    let mut watcher = match watcher_result {
        Ok(w) => w,
        Err(e) => {
            warn!("policy watcher failed to start: {e}");
            return tokio::spawn(async {});
        }
    };

    if let Err(e) = watcher.watch(&path, RecursiveMode::NonRecursive) {
        warn!("policy watcher failed to watch {}: {e}", path.display());
        return tokio::spawn(async {});
    }

    info!(
        "policy watcher started on {} (hot-reload enabled, ADR-009)",
        path.display()
    );

    tokio::spawn(reload_loop(path, guardian, rx, watcher))
}

async fn reload_loop(
    path: PathBuf,
    guardian: Arc<CynepicGuardian>,
    mut rx: mpsc::Receiver<Event>,
    // Owned here for the lifetime of the loop — the notify watcher tears
    // down its background thread + closes the channel sender on drop.
    _watcher: notify::RecommendedWatcher,
) {
    while let Some(first) = rx.recv().await {
        if !is_reload_signal(&first) {
            continue;
        }
        // Debounce: sleep, then drain anything queued in the meantime.
        tokio::time::sleep(DEBOUNCE).await;
        while let Ok(_extra) = rx.try_recv() {}

        match Policy::from_path(&path) {
            Ok(new_policy) => {
                let n = new_policy.name.clone();
                let count = new_policy.rules.len();
                guardian.replace_policy(new_policy);
                info!("policy reloaded: name={n} rules={count}");
            }
            Err(e) => {
                warn!(
                    "policy reload from {} failed; keeping current policy: {e}",
                    path.display()
                );
            }
        }
    }
}

/// Filter the kinds of filesystem events that should kick off a reload.
/// We ignore access-only events to keep the noise floor low; everything
/// else (create, modify, remove + recreate) re-reads the path.
fn is_reload_signal(event: &Event) -> bool {
    matches!(
        event.kind,
        EventKind::Create(_) | EventKind::Modify(_) | EventKind::Remove(_) | EventKind::Any
    )
}
