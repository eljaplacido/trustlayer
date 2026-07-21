import { useEffect, useState } from "react";

import { apiToken, baseUrl } from "./api.js";

interface MetricSample {
  name: string;
  labels: Record<string, string>;
  value: number;
}

type Status =
  | { kind: "loading" }
  | { kind: "ok"; metrics: MetricSample[] }
  | { kind: "error"; message: string };

const REFRESH_MS = 10000;

/** Parse Prometheus text format into MetricSample[] */
function parsePromText(text: string): MetricSample[] {
  const samples: MetricSample[] = [];

  for (const line of text.split("\n")) {
    if (line.startsWith("#")) continue;
    const m = line.match(/^(\w+)(\{.*?\})?\s+([0-9.e+\-]+)/);
    if (!m) continue;
    const name = m[1] ?? "";
    const labelsRaw = m[2] ?? "";
    const value = parseFloat(m[3] ?? "0");
    const labels: Record<string, string> = {};

    if (labelsRaw.length > 0) {
      const inner = labelsRaw.slice(1, -1);
      for (const pair of inner.split(",")) {
        const eq = pair.indexOf("=");
        if (eq < 0) continue;
        const k = pair.slice(0, eq).trim();
        const v = pair.slice(eq + 1).replace(/^"(.*)"$/, "$1").trim();
        labels[k] = v;
      }
    }

    // Merge: if same metric name + same labels, sum (histogram buckets/le)
    const existing = samples.find(
      (s) => s.name === name && JSON.stringify(s.labels) === JSON.stringify(labels),
    );
    if (existing) {
      existing.value += value;
    } else {
      samples.push({ name, labels, value });
    }
  }
  return samples;
}

export function MetricsPane() {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    async function tick() {
      try {
        const headers: Record<string, string> = {};
        const token = apiToken();
        if (token) headers["Authorization"] = `Bearer ${token}`;

        const res = await fetch(`${baseUrl()}/metrics`, { signal: controller.signal, headers });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const text = await res.text();
        const metrics = parsePromText(text);
        if (!cancelled) setStatus({ kind: "ok", metrics });
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
    return <pre style={mutedStyle}>loading metrics…</pre>;
  if (status.kind === "error")
    return <pre style={errorStyle}>{status.message}</pre>;

  const { metrics } = status;
  const eventsIngested = metrics.find((m) => m.name === "trustlayer_events_ingested_total")?.value ?? 0;
  const checkByDecision: Record<string, number> = {};
  for (const m of metrics) {
    if (m.name === "trustlayer_check_total" && m.labels.decision) {
      checkByDecision[m.labels.decision] = (checkByDecision[m.labels.decision] ?? 0) + m.value;
    }
  }
  const requestsByRoute: Record<string, number> = {};
  let totalRequests = 0;
  for (const m of metrics) {
    if (m.name === "trustlayer_requests_total" && m.labels.route) {
      requestsByRoute[m.labels.route] = m.value;
      totalRequests += m.value;
    }
  }

  const latencyBuckets = metrics.filter((m): m is MetricSample & { labels: { le: string } } => m.name === "trustlayer_check_duration_seconds_bucket" && !!m.labels.le);
  const maxLatencyBucket = latencyBuckets.length > 0
    ? Math.max(...latencyBuckets.map((m) => parseFloat(m.labels.le)), 1)
    : 1;

  return (
    <div>
      <div style={kpiRow}>
        <MiniKpi label="Events Ingested" value={eventsIngested} color="#1565c0" />
        <MiniKpi label="Total Requests" value={totalRequests} color="#2e7d32" />
        <MiniKpi
          label="Policy PASS"
          value={checkByDecision["PASS"] ?? 0}
          color="#2e7d32"
        />
        <MiniKpi
          label="Policy FAIL"
          value={checkByDecision["FAIL"] ?? 0}
          color="#d32f2f"
        />
      </div>

      <div style={section}>
        <h4 style={sectionTitle}>Requests by Route</h4>
        {Object.entries(requestsByRoute).sort((a, b) => b[1] - a[1]).map(([route, count]) => (
          <Bar key={route} label={route} value={count} max={totalRequests} />
        ))}
      </div>

      {latencyBuckets.length > 0 && (
        <div style={section}>
          <h4 style={sectionTitle}>Check Latency Distribution</h4>
          <div style={{ display: "flex", gap: 2, alignItems: "flex-end", height: 80 }}>
            {latencyBuckets.map((b) => {
              const maxVal = latencyBuckets[latencyBuckets.length - 1]?.value ?? 1;
              const h = b.value > 0 ? Math.max((b.value / maxVal) * 100, 4) : 0;
              const le = parseFloat(b.labels.le);
              return (
                <div
                  key={b.labels.le}
                  title={`<=${le}s: ${b.value}`}
                  style={{
                    flex: 1,
                    height: `${h}%`,
                    background: le <= 0.01 ? "#2e7d32" : le <= 0.1 ? "#1565c0" : "#ed6c02",
                    borderRadius: "2px 2px 0 0",
                    minWidth: 8,
                    transition: "height 0.3s ease",
                  }}
                />
              );
            })}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "#888", marginTop: 4 }}>
            <span>&le;0.005s</span>
            <span>&le;{maxLatencyBucket}s</span>
          </div>
        </div>
      )}

      <div style={{ marginTop: 12, fontSize: 10, color: "#aaa", fontFamily: "monospace" }}>
        Raw Prometheus metrics fetched from <code>/metrics</code> every {REFRESH_MS / 1000}s
      </div>
    </div>
  );
}

function MiniKpi(props: { label: string; value: number; color: string }) {
  return (
    <div style={miniKpiBox}>
      <div style={{ ...miniKpiValue, color: props.color }}>{props.value}</div>
      <div style={miniKpiLabel}>{props.label}</div>
    </div>
  );
}

function Bar(props: { label: string; value: number; max: number }) {
  const pct = props.max > 0 ? (props.value / props.max) * 100 : 0;
  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 1 }}>
        <code style={{ fontSize: 10 }}>{props.label}</code>
        <span style={{ fontWeight: 600 }}>{props.value}</span>
      </div>
      <div style={{ height: 6, background: "#eee", borderRadius: 3 }}>
        <div style={{ height: "100%", width: `${Math.max(pct, 1)}%`, background: "#1565c0", borderRadius: 3, transition: "width 0.3s ease" }} />
      </div>
    </div>
  );
}

const kpiRow: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(100px, 1fr))", gap: 8, marginBottom: 16 };
const miniKpiBox: React.CSSProperties = { textAlign: "center", background: "#fff", border: "1px solid #e5e5e5", borderRadius: 8, padding: "10px 6px" };
const miniKpiValue: React.CSSProperties = { fontSize: 22, fontWeight: 700, fontVariantNumeric: "tabular-nums" };
const miniKpiLabel: React.CSSProperties = { fontSize: 10, color: "#666", textTransform: "uppercase", marginTop: 2 };
const section: React.CSSProperties = { marginBottom: 16 };
const sectionTitle: React.CSSProperties = { margin: "0 0 6px 0", fontSize: 13, fontWeight: 600 };
const mutedStyle: React.CSSProperties = { color: "#666", fontSize: 13 };
const errorStyle: React.CSSProperties = { color: "#a33", background: "#fff5f5", border: "1px solid #fcc", padding: 12, borderRadius: 6, whiteSpace: "pre-wrap", fontSize: 13 };
