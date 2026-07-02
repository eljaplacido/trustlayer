//! Postgres-backed [`TraceStore`] for durable, horizontally-scalable trace
//! storage (ADR-015).
//!
//! The JSONL [`EventStore`](crate::events::EventStore) is the zero-dependency
//! default and is perfect for single-node dev / small deployments. When you
//! need many guardian replicas in front of one shared trace store — or
//! retention/queries beyond what a flat file gives you — point the sidecar at
//! Postgres with `TRUSTLAYER_DATABASE_URL` (requires the `postgres` build
//! feature). The schema is created on connect, so there is no separate
//! migration step for the happy path; `migrations/0001_trace_events.sql`
//! documents the same DDL for teams that manage schema out-of-band.
//!
//! Design parity with the JSONL backend:
//! * Idempotent on `trace_id` (`INSERT ... ON CONFLICT DO NOTHING`).
//! * Chronological ordering via a monotonic `seq` (`BIGSERIAL`).
//! * `limit` selects the most-recent N, returned oldest-first.

use async_trait::async_trait;
use sqlx::postgres::{PgPoolOptions, PgRow};
use sqlx::{QueryBuilder, Row};

use crate::error::{Error, Result};
use crate::events::{EventFilter, SessionSummary, TraceStore};
use crate::schema::AgentTraceEvent;

/// Durable trace store backed by a Postgres connection pool.
#[derive(Clone)]
pub struct PostgresStore {
    pool: sqlx::PgPool,
}

const SCHEMA_DDL: &str = r#"
CREATE TABLE IF NOT EXISTS trace_events (
    seq        BIGSERIAL PRIMARY KEY,
    trace_id   UUID        NOT NULL UNIQUE,
    agent_id   TEXT        NOT NULL,
    session_id TEXT        NOT NULL,
    ts         TIMESTAMPTZ NOT NULL,
    event_type TEXT        NOT NULL,
    body       JSONB       NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trace_events_agent_session
    ON trace_events (agent_id, session_id, seq);
CREATE INDEX IF NOT EXISTS idx_trace_events_type ON trace_events (event_type);
"#;

impl PostgresStore {
    /// Connect to `database_url`, create a pool, and ensure the schema exists.
    ///
    /// `max_connections` bounds the pool; pass `None` for the default (10).
    pub async fn connect(database_url: &str, max_connections: Option<u32>) -> Result<Self> {
        let pool = PgPoolOptions::new()
            .max_connections(max_connections.unwrap_or(10))
            .connect(database_url)
            .await
            .map_err(|e| Error::Storage(format!("connect: {e}")))?;
        // Split on ';' so the multi-statement DDL runs on backends that reject
        // multi-statement simple queries through the prepared protocol.
        for stmt in SCHEMA_DDL.split(';') {
            let stmt = stmt.trim();
            if stmt.is_empty() {
                continue;
            }
            sqlx::query(stmt)
                .execute(&pool)
                .await
                .map_err(|e| Error::Storage(format!("schema: {e}")))?;
        }
        Ok(Self { pool })
    }

    /// Build a [`PostgresStore`] from an existing pool (tests / embedding).
    pub fn from_pool(pool: sqlx::PgPool) -> Self {
        Self { pool }
    }

    fn event_type_str(event: &AgentTraceEvent) -> Result<String> {
        let v = serde_json::to_value(event.event_type).map_err(Error::InvalidEvent)?;
        v.as_str()
            .map(str::to_string)
            .ok_or_else(|| Error::Storage("event_type did not serialise to a string".into()))
    }

    fn row_to_event(row: &PgRow) -> Result<AgentTraceEvent> {
        let body: serde_json::Value = row
            .try_get("body")
            .map_err(|e| Error::Storage(format!("read body: {e}")))?;
        serde_json::from_value(body).map_err(Error::InvalidEvent)
    }
}

#[async_trait]
impl TraceStore for PostgresStore {
    async fn append_batch(&self, events: Vec<AgentTraceEvent>) -> Result<usize> {
        let mut stored = 0usize;
        let mut tx = self
            .pool
            .begin()
            .await
            .map_err(|e| Error::Storage(format!("begin: {e}")))?;
        for event in events {
            let event_type = Self::event_type_str(&event)?;
            let body = serde_json::to_value(&event).map_err(Error::InvalidEvent)?;
            let result = sqlx::query(
                "INSERT INTO trace_events (trace_id, agent_id, session_id, ts, event_type, body) \
                 VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (trace_id) DO NOTHING",
            )
            .bind(event.trace_id)
            .bind(&event.agent_id)
            .bind(&event.session_id)
            .bind(event.timestamp)
            .bind(&event_type)
            .bind(sqlx::types::Json(body))
            .execute(&mut *tx)
            .await
            .map_err(|e| Error::Storage(format!("insert: {e}")))?;
            stored += result.rows_affected() as usize;
        }
        tx.commit()
            .await
            .map_err(|e| Error::Storage(format!("commit: {e}")))?;
        Ok(stored)
    }

    async fn list_events(&self, filter: &EventFilter) -> Result<Vec<AgentTraceEvent>> {
        let mut qb: QueryBuilder<sqlx::Postgres> =
            QueryBuilder::new("SELECT body FROM trace_events");
        let mut first = true;
        let mut push_where = |qb: &mut QueryBuilder<sqlx::Postgres>| {
            qb.push(if first { " WHERE " } else { " AND " });
            first = false;
        };
        if let Some(agent) = filter.agent_id.as_deref() {
            push_where(&mut qb);
            qb.push("agent_id = ").push_bind(agent.to_string());
        }
        if let Some(session) = filter.session_id.as_deref() {
            push_where(&mut qb);
            qb.push("session_id = ").push_bind(session.to_string());
        }
        if let Some(et) = filter.event_type {
            let s = serde_json::to_value(et)
                .map_err(Error::InvalidEvent)?
                .as_str()
                .map(str::to_string)
                .ok_or_else(|| Error::Storage("event_type not a string".into()))?;
            push_where(&mut qb);
            qb.push("event_type = ").push_bind(s);
        }

        // `limit` means "most recent N": fetch DESC then re-sort ASC so callers
        // always see chronological order (matches the JSONL backend).
        let reversed = filter.limit.is_some();
        qb.push(if reversed {
            " ORDER BY seq DESC"
        } else {
            " ORDER BY seq ASC"
        });
        if let Some(n) = filter.limit {
            qb.push(" LIMIT ").push_bind(n as i64);
        }

        let rows = qb
            .build()
            .fetch_all(&self.pool)
            .await
            .map_err(|e| Error::Storage(format!("list_events: {e}")))?;
        let mut events = rows
            .iter()
            .map(Self::row_to_event)
            .collect::<Result<Vec<_>>>()?;
        if reversed {
            events.reverse();
        }
        Ok(events)
    }

    async fn list_sessions(&self) -> Result<Vec<SessionSummary>> {
        let rows = sqlx::query(
            "SELECT agent_id, session_id, COUNT(*) AS cnt, \
             MIN(ts) AS first_seen, MAX(ts) AS last_seen \
             FROM trace_events GROUP BY agent_id, session_id ORDER BY MAX(ts) DESC",
        )
        .fetch_all(&self.pool)
        .await
        .map_err(|e| Error::Storage(format!("list_sessions: {e}")))?;

        rows.iter()
            .map(|row| {
                let first: chrono::DateTime<chrono::Utc> = row
                    .try_get("first_seen")
                    .map_err(|e| Error::Storage(format!("first_seen: {e}")))?;
                let last: chrono::DateTime<chrono::Utc> = row
                    .try_get("last_seen")
                    .map_err(|e| Error::Storage(format!("last_seen: {e}")))?;
                let cnt: i64 = row
                    .try_get("cnt")
                    .map_err(|e| Error::Storage(format!("cnt: {e}")))?;
                Ok(SessionSummary {
                    agent_id: row
                        .try_get("agent_id")
                        .map_err(|e| Error::Storage(format!("agent_id: {e}")))?,
                    session_id: row
                        .try_get("session_id")
                        .map_err(|e| Error::Storage(format!("session_id: {e}")))?,
                    event_count: cnt.max(0) as usize,
                    first_seen: first.to_rfc3339(),
                    last_seen: last.to_rfc3339(),
                })
            })
            .collect()
    }

    async fn get_session(&self, agent_id: &str, session_id: &str) -> Result<Vec<AgentTraceEvent>> {
        let rows = sqlx::query(
            "SELECT body FROM trace_events WHERE agent_id = $1 AND session_id = $2 ORDER BY seq ASC",
        )
        .bind(agent_id)
        .bind(session_id)
        .fetch_all(&self.pool)
        .await
        .map_err(|e| Error::Storage(format!("get_session: {e}")))?;
        rows.iter().map(Self::row_to_event).collect()
    }
}
