import { useEffect, useState } from "react";

import { fetchEvents, type AgentTraceEvent } from "./api.js";

type Status =
  | { kind: "loading" }
  | { kind: "ok"; events: AgentTraceEvent[] }
  | { kind: "error"; message: string };

const REFRESH_MS = 5000;

export function TracesPane() {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    async function tick() {
      try {
        const events = await fetchEvents(
          { limit: 50 },
          controller.signal,
        );
        if (!cancelled) setStatus({ kind: "ok", events });
      } catch (err) {
        if (cancelled || controller.signal.aborted) return;
        const message = err instanceof Error ? err.message : String(err);
        setStatus({ kind: "error", message });
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

  if (status.kind === "loading") {
    return <pre style={mutedStyle}>loading…</pre>;
  }
  if (status.kind === "error") {
    return (
      <pre style={errorStyle}>
        Could not reach the TrustLayer sidecar:{"\n"}
        {status.message}
        {"\n\n"}
        Set <code>VITE_TRUSTLAYER_BASE_URL</code> if it's not at{" "}
        <code>http://127.0.0.1:8089</code>.
      </pre>
    );
  }
  if (status.events.length === 0) {
    return (
      <pre style={mutedStyle}>
        No events yet. POST an AgentTraceEvent to{" "}
        <code>/v1/events</code> on the sidecar.
      </pre>
    );
  }

  return (
    <table style={tableStyle}>
      <thead>
        <tr>
          <th style={thStyle}>time</th>
          <th style={thStyle}>agent</th>
          <th style={thStyle}>session</th>
          <th style={thStyle}>event</th>
          <th style={thStyle}>tool / payload hint</th>
        </tr>
      </thead>
      <tbody>
        {status.events.map((e) => (
          <tr key={e.trace_id}>
            <td style={tdStyle}>{formatTs(e.timestamp)}</td>
            <td style={tdStyle}>{e.agent_id}</td>
            <td style={tdStyle}>{shorten(e.session_id)}</td>
            <td style={tdStyle}>
              <code>{e.event_type}</code>
            </td>
            <td style={tdStyle}>{payloadHint(e.payload)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function formatTs(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString();
  } catch {
    return iso;
  }
}

function shorten(s: string): string {
  return s.length > 12 ? `${s.slice(0, 8)}…` : s;
}

function payloadHint(payload: Record<string, unknown> | undefined): string {
  if (!payload) return "";
  if (typeof payload.tool_name === "string") return payload.tool_name;
  if (typeof payload.policy_name === "string")
    return `policy:${payload.policy_name}`;
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

const tdStyle: React.CSSProperties = {
  borderBottom: "1px solid #f0f0f0",
  padding: "6px 8px",
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
