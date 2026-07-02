//! Integration tests for the Postgres trace-store backend (ADR-015).
//!
//! These talk to a real Postgres, so they are **opt-in**: set
//! `TRUSTLAYER_TEST_DATABASE_URL` to a throwaway database and run
//!
//! ```bash
//! cargo test --features server,postgres --test pg_store
//! ```
//!
//! With the env var unset every test no-ops (prints a skip line) so the
//! default `cargo test` matrix stays hermetic.

#![cfg(feature = "postgres")]

use trustlayer_core::{AgentTraceEvent, EventFilter, PostgresStore, TraceStore};

fn dsn() -> Option<String> {
    std::env::var("TRUSTLAYER_TEST_DATABASE_URL")
        .ok()
        .filter(|s| !s.is_empty())
}

fn event(trace: &str, agent: &str, session: &str, et: &str, ts: &str) -> AgentTraceEvent {
    let raw = format!(
        r#"{{
            "trace_id": "{trace}",
            "agent_id": "{agent}",
            "session_id": "{session}",
            "timestamp": "{ts}",
            "event_type": "{et}",
            "payload": {{"tool_name": "calc"}}
        }}"#
    );
    serde_json::from_str(&raw).expect("parse event")
}

async fn fresh_store() -> PostgresStore {
    let url = dsn().expect("checked by caller");
    let store = PostgresStore::connect(&url, Some(4))
        .await
        .expect("connect to test database");
    // Each test starts from a clean slate.
    let pool = sqlx::PgPool::connect(&url).await.expect("truncate pool");
    sqlx::query("TRUNCATE trace_events")
        .execute(&pool)
        .await
        .expect("truncate");
    store
}

#[tokio::test]
async fn append_dedups_and_lists_chronologically() {
    if dsn().is_none() {
        eprintln!("SKIP: TRUSTLAYER_TEST_DATABASE_URL not set");
        return;
    }
    let store = fresh_store().await;
    let stored = store
        .append_batch(vec![
            event(
                "11111111-1111-4111-8111-111111111111",
                "a",
                "s1",
                "TOOL_CALL",
                "2026-05-18T10:00:00+00:00",
            ),
            event(
                "22222222-2222-4222-8222-222222222222",
                "a",
                "s2",
                "TOOL_CALL",
                "2026-05-18T10:00:01+00:00",
            ),
            event(
                "11111111-1111-4111-8111-111111111111",
                "a",
                "s1",
                "TOOL_CALL",
                "2026-05-18T10:00:00+00:00",
            ),
        ])
        .await
        .expect("append");
    assert_eq!(stored, 2, "duplicate trace_id must be deduped");

    let all = store
        .list_events(&EventFilter::default())
        .await
        .expect("list");
    assert_eq!(all.len(), 2);
    assert_eq!(all[0].session_id, "s1", "chronological order by seq");
    assert_eq!(all[1].session_id, "s2");
}

#[tokio::test]
async fn filters_and_limit_tail() {
    if dsn().is_none() {
        eprintln!("SKIP: TRUSTLAYER_TEST_DATABASE_URL not set");
        return;
    }
    let store = fresh_store().await;
    store
        .append_batch(vec![
            event(
                "aaaaaaaa-0000-4000-8000-000000000001",
                "a",
                "s1",
                "TOOL_CALL",
                "2026-05-18T10:00:00+00:00",
            ),
            event(
                "aaaaaaaa-0000-4000-8000-000000000002",
                "a",
                "s1",
                "POLICY_CHECK",
                "2026-05-18T10:00:01+00:00",
            ),
            event(
                "aaaaaaaa-0000-4000-8000-000000000003",
                "b",
                "s9",
                "TOOL_CALL",
                "2026-05-18T10:00:02+00:00",
            ),
        ])
        .await
        .expect("append");

    let agent_a = store
        .list_events(&EventFilter {
            agent_id: Some("a".into()),
            ..Default::default()
        })
        .await
        .expect("list a");
    assert_eq!(agent_a.len(), 2);

    let only_policy = store
        .list_events(&EventFilter {
            event_type: Some(trustlayer_core::EventType::PolicyCheck),
            ..Default::default()
        })
        .await
        .expect("list policy");
    assert_eq!(only_policy.len(), 1);

    // limit selects most-recent N, returned oldest-first.
    let tail = store
        .list_events(&EventFilter {
            limit: Some(1),
            ..Default::default()
        })
        .await
        .expect("tail");
    assert_eq!(tail.len(), 1);
    assert_eq!(tail[0].agent_id, "b");
}

#[tokio::test]
async fn sessions_summary_and_get_session() {
    if dsn().is_none() {
        eprintln!("SKIP: TRUSTLAYER_TEST_DATABASE_URL not set");
        return;
    }
    let store = fresh_store().await;
    store
        .append_batch(vec![
            event(
                "bbbbbbbb-0000-4000-8000-000000000001",
                "a",
                "s1",
                "TOOL_CALL",
                "2026-05-18T10:00:00+00:00",
            ),
            event(
                "bbbbbbbb-0000-4000-8000-000000000002",
                "a",
                "s1",
                "TOOL_CALL",
                "2026-05-18T10:00:05+00:00",
            ),
            event(
                "bbbbbbbb-0000-4000-8000-000000000003",
                "b",
                "s2",
                "TOOL_CALL",
                "2026-05-18T10:00:10+00:00",
            ),
        ])
        .await
        .expect("append");

    let sessions = store.list_sessions().await.expect("sessions");
    assert_eq!(sessions.len(), 2);
    // Most-recent session (b/s2) first.
    assert_eq!(sessions[0].agent_id, "b");
    let a_s1 = sessions.iter().find(|s| s.agent_id == "a").expect("a/s1");
    assert_eq!(a_s1.event_count, 2);

    let session = store.get_session("a", "s1").await.expect("get_session");
    assert_eq!(session.len(), 2);
    assert_eq!(
        session[0].trace_id.to_string(),
        "bbbbbbbb-0000-4000-8000-000000000001"
    );
}
