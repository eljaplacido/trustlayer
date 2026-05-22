import { useEffect, useState } from "react";

import { fetchEvents, type AgentTraceEvent } from "./api.js";

type Status =
  | { kind: "loading" }
  | { kind: "ok"; events: AgentTraceEvent[] }
  | { kind: "error"; message: string };

const REFRESH_MS = 5000;

export function PolicyPane() {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    async function tick() {
      try {
        const events = await fetchEvents(
          { event_type: "POLICY_CHECK", limit: 50 },
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
    return <pre style={errorStyle}>{status.message}</pre>;
  }
  if (status.events.length === 0) {
    return (
      <pre style={mutedStyle}>
        No policy checks yet. They appear when an agent calls{" "}
        <code>Tracer.check()</code> or emits a <code>POLICY_CHECK</code>{" "}
        event.
      </pre>
    );
  }

  return (
    <table style={tableStyle}>
      <thead>
        <tr>
          <th style={thStyle}>time</th>
          <th style={thStyle}>agent</th>
          <th style={thStyle}>verdict</th>
          <th style={thStyle}>action</th>
          <th style={thStyle}>reason</th>
        </tr>
      </thead>
      <tbody>
        {status.events.map((e) => {
          const p = e.payload ?? {};
          const result = String(p.result ?? "");
          return (
            <tr key={e.trace_id}>
              <td style={tdStyle}>{formatTs(e.timestamp)}</td>
              <td style={tdStyle}>{e.agent_id}</td>
              <td style={tdStyle}>
                <span style={verdictStyle(result)}>{result || "—"}</span>
              </td>
              <td style={tdStyle}>{strOr(p.action)}</td>
              <td style={tdStyle}>{strOr(p.reason)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function strOr(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function formatTs(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso;
  }
}

function verdictStyle(result: string): React.CSSProperties {
  const palette: Record<string, { bg: string; fg: string }> = {
    PASS: { bg: "#e6f6ec", fg: "#1a7f37" },
    FAIL: { bg: "#fdecec", fg: "#b3261e" },
    ESCALATE: { bg: "#fff4e0", fg: "#9a6700" },
  };
  const c = palette[result] ?? { bg: "#eee", fg: "#555" };
  return {
    display: "inline-block",
    padding: "2px 8px",
    borderRadius: 999,
    fontSize: 12,
    fontWeight: 600,
    background: c.bg,
    color: c.fg,
  };
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
