import { useEffect, useState } from "react";

import { fetchEvents, fetchSessions } from "./api.js";

interface OverviewData {
  totalEvents: number;
  totalSessions: number;
  activeAgents: string[];
  policyResults: { pass: number; fail: number; escalate: number };
  eventTypes: Record<string, number>;
}

type Status =
  | { kind: "loading" }
  | { kind: "ok"; data: OverviewData }
  | { kind: "error"; message: string };

const REFRESH_MS = 8000;

export function OverviewPane() {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    async function tick() {
      try {
        const [events, sessions] = await Promise.all([
          fetchEvents({ limit: 200 }, controller.signal),
          fetchSessions(controller.signal),
        ]);

        const agents = [...new Set(events.map((e) => e.agent_id))];
        const policyResults = { pass: 0, fail: 0, escalate: 0 };
        const eventTypes: Record<string, number> = {};
        for (const e of events) {
          eventTypes[e.event_type] = (eventTypes[e.event_type] ?? 0) + 1;
          if (e.event_type === "POLICY_CHECK" && e.payload) {
            const r = String(e.payload.result ?? "").toUpperCase();
            if (r === "PASS") policyResults.pass++;
            else if (r === "FAIL") policyResults.fail++;
            else if (r === "ESCALATE") policyResults.escalate++;
          }
        }

        const data: OverviewData = {
          totalEvents: events.length,
          totalSessions: sessions.length,
          activeAgents: agents,
          policyResults,
          eventTypes,
        };
        if (!cancelled) setStatus({ kind: "ok", data });
      } catch (err) {
        if (cancelled || controller.signal.aborted) return;
        setStatus({ kind: "error", message: err instanceof Error ? err.message : String(err) });
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

  if (status.kind === "loading")
    return <pre style={mutedStyle}>loading overview…</pre>;
  if (status.kind === "error")
    return <pre style={errorStyle}>{status.message}</pre>;

  const { data } = status;
  const policyTotal = data.policyResults.pass + data.policyResults.fail + data.policyResults.escalate;

  return (
    <div>
      <div style={kpiRow}>
        <Kpi label="Events" value={data.totalEvents} color="#1565c0" />
        <Kpi label="Sessions" value={data.totalSessions} color="#2e7d32" />
        <Kpi label="Agents" value={data.activeAgents.length} color="#6a1b9a" />
        <Kpi
          label="Policy Pass Rate"
          value={policyTotal > 0 ? `${Math.round((data.policyResults.pass / policyTotal) * 100)}%` : "n/a"}
          color={
            data.policyResults.fail > 0 ? "#d32f2f" : data.policyResults.escalate > 0 ? "#ed6c02" : "#2e7d32"
          }
        />
      </div>

      <div style={barSection}>
        <h4 style={sectionTitle}>Events by Type</h4>
        <div style={barRow}>
          {Object.entries(data.eventTypes)
            .sort((a, b) => b[1] - a[1])
            .map(([type, count]) => (
              <Bar key={type} label={type.replace(/_/g, " ")} value={count} max={data.totalEvents} />
            ))}
        </div>
      </div>

      <div style={agentList}>
        <h4 style={sectionTitle}>Registered Agents</h4>
        {data.activeAgents.map((agent) => (
          <span key={agent} style={agentBadge}>
            {agent}
          </span>
        ))}
      </div>
    </div>
  );
}

function Kpi(props: { label: string; value: string | number; color: string }) {
  return (
    <div style={kpiBox}>
      <div style={{ ...kpiValue, color: props.color }}>{props.value}</div>
      <div style={kpiLabel}>{props.label}</div>
    </div>
  );
}

function Bar(props: { label: string; value: number; max: number }) {
  const pct = props.max > 0 ? (props.value / props.max) * 100 : 0;
  return (
    <div style={barContainer}>
      <div style={barLabel}>
        <span>{props.label}</span>
        <span style={{ fontWeight: 600, minWidth: 32, textAlign: "right" }}>{props.value}</span>
      </div>
      <div style={barTrack}>
        <div
          style={{
            ...barFill,
            width: `${Math.max(pct, 2)}%`,
            background: pct > 50 ? "#1565c0" : pct > 20 ? "#2e7d32" : "#ed6c02",
          }}
        />
      </div>
    </div>
  );
}

// -- styles

const kpiRow: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
  gap: 12,
  marginBottom: 20,
};
const kpiBox: React.CSSProperties = {
  textAlign: "center",
  background: "#fff",
  border: "1px solid #e5e5e5",
  borderRadius: 8,
  padding: "14px 10px",
};
const kpiValue: React.CSSProperties = { fontSize: 28, fontWeight: 700, fontVariantNumeric: "tabular-nums" };
const kpiLabel: React.CSSProperties = { fontSize: 11, color: "#666", textTransform: "uppercase", marginTop: 2 };

const sectionTitle: React.CSSProperties = { margin: "0 0 8px 0", fontSize: 14, fontWeight: 600 };

const barSection: React.CSSProperties = { marginBottom: 20 };
const barRow: React.CSSProperties = { display: "flex", flexDirection: "column", gap: 6 };
const barContainer: React.CSSProperties = {};
const barLabel: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  fontSize: 12,
  marginBottom: 2,
};
const barTrack: React.CSSProperties = { height: 8, background: "#eee", borderRadius: 4 };
const barFill: React.CSSProperties = { height: "100%", borderRadius: 4, transition: "width 0.3s ease" };

const agentList: React.CSSProperties = { display: "flex", gap: 8, flexWrap: "wrap" };
const agentBadge: React.CSSProperties = {
  display: "inline-block",
  padding: "4px 10px",
  borderRadius: 999,
  fontSize: 11,
  background: "#f0f4ff",
  border: "1px solid #d0d8f0",
  fontFamily: "monospace",
};

const mutedStyle: React.CSSProperties = { color: "#666", fontSize: 13 };
const errorStyle: React.CSSProperties = {
  color: "#a33", background: "#fff5f5", border: "1px solid #fcc",
  padding: 12, borderRadius: 6, whiteSpace: "pre-wrap", fontSize: 13,
};
