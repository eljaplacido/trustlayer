//! Integration test for the ADR-009 policy hot-reload watcher.
//!
//! Spawns the watcher against a tempfile, mutates the policy on disk, and
//! asserts that subsequent `evaluate()` calls reflect the new rules. A
//! second case writes garbage to confirm the watcher keeps the old policy
//! when parsing fails.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use trustlayer_core::policy_watch::spawn_watcher;
use trustlayer_core::{
    AgentTraceEvent, CynefinDomain, CynepicGuardian, Decision, EventType, MatchSpec, Policy,
    PolicyRule,
};

fn unique_path(stem: &str) -> PathBuf {
    let mut p = std::env::temp_dir();
    p.push(format!(
        "trustlayer-policy-watch-{}-{}.json",
        stem,
        uuid::Uuid::new_v4()
    ));
    p
}

fn write_policy(path: &PathBuf, rules: Vec<PolicyRule>, name: &str) {
    let policy = Policy {
        name: name.to_string(),
        rules,
    };
    let json = serde_json::to_string_pretty(&policy).expect("serialize policy");
    std::fs::write(path, json).expect("write policy");
}

fn calc_rule(decision: Decision, name: &str) -> PolicyRule {
    PolicyRule {
        name: name.to_string(),
        selector: MatchSpec {
            tool_name: Some("calc".into()),
            ..Default::default()
        },
        decision,
        reason: None,
    }
}

fn calc_event() -> AgentTraceEvent {
    use chrono::Utc;
    let mut payload = serde_json::Map::new();
    payload.insert("tool_name".into(), serde_json::json!("calc"));
    AgentTraceEvent {
        trace_id: uuid::Uuid::nil(),
        agent_id: "a".into(),
        session_id: "s".into(),
        timestamp: Utc::now(),
        event_type: EventType::ToolCall,
        cynefin_domain: CynefinDomain::Clear,
        payload,
        metrics: Default::default(),
    }
}

/// Spin until the predicate is true or the timeout elapses. Returns true on
/// success. Used because filesystem-event timing varies across kernels and
/// we don't want to flake on a fixed sleep.
async fn wait_until<F>(deadline: Duration, mut check: F) -> bool
where
    F: FnMut() -> bool,
{
    let start = std::time::Instant::now();
    while start.elapsed() < deadline {
        if check() {
            return true;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    false
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn watcher_picks_up_policy_changes() {
    let path = unique_path("change");
    write_policy(&path, vec![calc_rule(Decision::Pass, "allow_calc")], "v1");

    let guardian = Arc::new(CynepicGuardian::new(Policy::from_path(&path).unwrap()));
    let _handle = spawn_watcher(path.clone(), guardian.clone());

    // Initial: PASS (because "allow_calc" decides PASS).
    assert_eq!(guardian.evaluate(&calc_event()).decision, Decision::Pass);

    // Flip the rule's decision to FAIL.
    write_policy(&path, vec![calc_rule(Decision::Fail, "block_calc")], "v2");

    // Allow plenty of headroom for filesystem-event propagation + debounce.
    let observed = wait_until(Duration::from_secs(5), || {
        guardian.evaluate(&calc_event()).decision == Decision::Fail
    })
    .await;
    assert!(observed, "policy reload was not observed within 5s");

    let _ = std::fs::remove_file(&path);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn bad_policy_keeps_old_one() {
    let path = unique_path("bad");
    write_policy(&path, vec![calc_rule(Decision::Fail, "block_calc")], "v1");

    let guardian = Arc::new(CynepicGuardian::new(Policy::from_path(&path).unwrap()));
    let _handle = spawn_watcher(path.clone(), guardian.clone());

    assert_eq!(guardian.evaluate(&calc_event()).decision, Decision::Fail);

    // Garbage that won't parse as a Policy.
    std::fs::write(&path, b"not a policy").expect("write garbage");

    // Old policy must persist. Wait long enough that a successful reload
    // would have happened, then re-check.
    tokio::time::sleep(Duration::from_millis(800)).await;
    assert_eq!(
        guardian.evaluate(&calc_event()).decision,
        Decision::Fail,
        "garbage policy should not have replaced the live one"
    );

    let _ = std::fs::remove_file(&path);
}

#[test]
fn replace_policy_is_synchronous_and_visible() {
    let g = CynepicGuardian::new(Policy {
        name: "v1".into(),
        rules: vec![calc_rule(Decision::Pass, "allow")],
    });
    assert_eq!(g.evaluate(&calc_event()).decision, Decision::Pass);

    g.replace_policy(Policy {
        name: "v2".into(),
        rules: vec![calc_rule(Decision::Fail, "block")],
    });
    let verdict = g.evaluate(&calc_event());
    assert_eq!(verdict.decision, Decision::Fail);
    assert_eq!(verdict.policy, "v2");
}
