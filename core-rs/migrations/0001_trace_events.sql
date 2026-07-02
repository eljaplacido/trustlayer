-- TrustLayer trace-store schema for the Postgres backend (ADR-015).
--
-- The guardian creates this schema automatically on connect, so you only need
-- this file if you manage database schema out-of-band (e.g. with sqlx-cli,
-- Flyway, or Liquibase). It is idempotent and safe to re-run.

CREATE TABLE IF NOT EXISTS trace_events (
    seq        BIGSERIAL   PRIMARY KEY,
    trace_id   UUID        NOT NULL UNIQUE,
    agent_id   TEXT        NOT NULL,
    session_id TEXT        NOT NULL,
    ts         TIMESTAMPTZ NOT NULL,
    event_type TEXT        NOT NULL,
    body       JSONB       NOT NULL
);

-- Session drill-down (GET /v1/sessions/:agent/:session) and per-agent filters.
CREATE INDEX IF NOT EXISTS idx_trace_events_agent_session
    ON trace_events (agent_id, session_id, seq);

-- event_type filter on GET /v1/events (e.g. the dashboard Policy pane).
CREATE INDEX IF NOT EXISTS idx_trace_events_type ON trace_events (event_type);
