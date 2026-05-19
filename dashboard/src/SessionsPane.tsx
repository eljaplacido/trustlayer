import { Fragment, useEffect, useState } from "react";

import {
  fetchSession,
  fetchSessions,
  type AgentTraceEvent,
  type SessionSummary,
} from "./api.js";

type ListStatus =
  | { kind: "loading" }
  | { kind: "ok"; sessions: SessionSummary[] }
  | { kind: "error"; message: string };

type DrillStatus =
  | { kind: "loading"; key: string }
  | { kind: "ok"; key: string; events: AgentTraceEvent[] }
  | { kind: "error"; key: string; message: string };

const REFRESH_MS = 5000;

function sessionKey(agentId: string, sessionId: string): string {
  return `${agentId}::${sessionId}`;
}

export function SessionsPane() {
  const [list, setList] = useState<ListStatus>({ kind: "loading" });
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [drill, setDrill] = useState<DrillStatus | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    async function tick() {
      try {
        const sessions = await fetchSessions(controller.signal);
        if (!cancelled) setList({ kind: "ok", sessions });
      } catch (err) {
        if (cancelled || controller.signal.aborted) return;
        const message = err instanceof Error ? err.message : String(err);
        setList({ kind: "error", message });
      }
    }

    tick();
    const id = setInterval(tick, REFRESH_MS);
    return () => {
      cancelled = true;
      controller.abort();
      clearInterval(id);
    };
  }, []);

  async function toggleSession(agentId: string, sessionId: string) {
    const key = sessionKey(agentId, sessionId);
    if (openKey === key) {
      setOpenKey(null);
      setDrill(null);
      return;
    }
    setOpenKey(key);
    setDrill({ kind: "loading", key });
    try {
      const events = await fetchSession(agentId, sessionId);
      setDrill({ kind: "ok", key, events });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setDrill({ kind: "error", key, message });
    }
  }

  if (list.kind === "loading") {
    return <pre style={mutedStyle}>loading…</pre>;
  }
  if (list.kind === "error") {
    return <pre style={errorStyle}>{list.message}</pre>;
  }
  if (list.sessions.length === 0) {
    return (
      <pre style={mutedStyle}>
        No sessions yet. POST trace events to <code>/v1/events</code> on
        the sidecar.
      </pre>
    );
  }

  return (
    <table style={tableStyle}>
      <thead>
        <tr>
          <th style={thStyle}>agent</th>
          <th style={thStyle}>session</th>
          <th style={thNumStyle}>events</th>
          <th style={thStyle}>first seen</th>
          <th style={thStyle}>last seen</th>
        </tr>
      </thead>
      <tbody>
        {list.sessions.map((s) => {
          const key = sessionKey(s.agent_id, s.session_id);
          const isOpen = openKey === key;
          return (
            <Fragment key={key}>
              <tr
                style={isOpen ? rowOpenStyle : rowStyle}
                onClick={() => toggleSession(s.agent_id, s.session_id)}
              >
                <td style={tdStyle}>{s.agent_id}</td>
                <td style={tdStyle}>
                  <code>{s.session_id}</code>
                </td>
                <td style={tdNumStyle}>{s.event_count}</td>
                <td style={tdStyle}>{formatTs(s.first_seen)}</td>
                <td style={tdStyle}>{formatTs(s.last_seen)}</td>
              </tr>
              {isOpen && drill?.key === key ? (
                <tr>
                  <td colSpan={5} style={drillCellStyle}>
                    {renderDrill(drill)}
                  </td>
                </tr>
              ) : null}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}

function renderDrill(drill: DrillStatus) {
  if (drill.kind === "loading") {
    return <pre style={mutedStyle}>loading session…</pre>;
  }
  if (drill.kind === "error") {
    return <pre style={errorStyle}>{drill.message}</pre>;
  }
  if (drill.events.length === 0) {
    return <pre style={mutedStyle}>(no events)</pre>;
  }
  return (
    <ol style={timelineStyle}>
      {drill.events.map((e) => (
        <li key={e.trace_id} style={timelineItemStyle}>
          <span style={timelineTsStyle}>{formatTs(e.timestamp)}</span>
          <code style={timelineTypeStyle}>{e.event_type}</code>
          <span style={timelineHintStyle}>{payloadHint(e.payload)}</span>
        </li>
      ))}
    </ol>
  );
}

function formatTs(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso;
  }
}

function payloadHint(payload: Record<string, unknown> | undefined): string {
  if (!payload) return "";
  if (typeof payload.tool_name === "string") return payload.tool_name;
  if (typeof payload.policy_name === "string")
    return `policy:${payload.policy_name}`;
  if (typeof payload.result === "string") return `result:${payload.result}`;
  if (typeof payload.model === "string") return `model:${payload.model}`;
  return Object.keys(payload).join(",");
}

const tableStyle: React.CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: 13,
};

const thStyle: React.CSSProperties = {
  textAlign: "left",
  borderBottom: "1px solid #ddd",
  padding: "6px 8px",
  fontWeight: 600,
};

const thNumStyle: React.CSSProperties = {
  ...thStyle,
  textAlign: "right",
};

const tdStyle: React.CSSProperties = {
  borderBottom: "1px solid #f0f0f0",
  padding: "6px 8px",
};

const tdNumStyle: React.CSSProperties = {
  ...tdStyle,
  textAlign: "right",
  fontVariantNumeric: "tabular-nums",
};

const rowStyle: React.CSSProperties = {
  cursor: "pointer",
};

const rowOpenStyle: React.CSSProperties = {
  cursor: "pointer",
  background: "#f0f4ff",
};

const drillCellStyle: React.CSSProperties = {
  padding: "12px 16px",
  background: "#fafbff",
  borderBottom: "1px solid #f0f0f0",
};

const timelineStyle: React.CSSProperties = {
  margin: 0,
  paddingLeft: 20,
  display: "flex",
  flexDirection: "column",
  gap: 4,
};

const timelineItemStyle: React.CSSProperties = {
  fontSize: 13,
};

const timelineTsStyle: React.CSSProperties = {
  display: "inline-block",
  width: 90,
  color: "#666",
  fontVariantNumeric: "tabular-nums",
};

const timelineTypeStyle: React.CSSProperties = {
  display: "inline-block",
  minWidth: 120,
  marginRight: 8,
};

const timelineHintStyle: React.CSSProperties = {
  color: "#444",
};

const mutedStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 13,
  color: "#666",
  whiteSpace: "pre-wrap",
};

const errorStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 13,
  color: "#a33",
  background: "#fff5f5",
  border: "1px solid #fcc",
  padding: 12,
  borderRadius: 6,
  whiteSpace: "pre-wrap",
};
