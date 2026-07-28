import { useEffect, useState } from "react";

interface ComplianceCheck {
  check_id: string;
  check_title: string;
  status: string;
  details: string;
  priority: string;
}

interface SystemCompliance {
  system_id: string;
  system_name: string;
  checks: ComplianceCheck[];
  summary: {
    total_checks: number;
    passed: number;
    failed: number;
    gaps: number;
    readiness_score_percent: number;
  };
}

interface ComplianceReport {
  generated_at: string;
  systems: SystemCompliance[];
  overall_summary: {
    total_systems: number;
    total_controls: number;
    total_passed: number;
    total_failed: number;
    total_gaps: number;
    overall_readiness_percent: number;
  };
}

type Status =
  | { kind: "loading" }
  | { kind: "ok"; report: ComplianceReport }
  | { kind: "error"; message: string };

/** Fetch the compliance report from a JSON file served from public/. */
async function fetchComplianceReport(signal?: AbortSignal): Promise<ComplianceReport> {
  const res = await fetch("/compliance-readiness.json", { signal });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return (await res.json()) as ComplianceReport;
}

export function CompliancePane() {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    async function load() {
      try {
        const report = await fetchComplianceReport(controller.signal);
        if (!cancelled) setStatus({ kind: "ok", report });
      } catch (err) {
        if (cancelled || controller.signal.aborted) return;
        const message = err instanceof Error ? err.message : String(err);
        setStatus({ kind: "error", message });
      }
    }

    load();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, []);

  if (status.kind === "loading") {
    return (
      <pre style={mutedStyle} role="status" aria-live="polite">
        loading compliance report…
      </pre>
    );
  }
  if (status.kind === "error") {
    return <pre style={errorStyle} role="alert">{status.message}</pre>;
  }

  const { report } = status;

  if (report.systems.length === 0) {
    return (
      <pre style={mutedStyle} role="status" aria-live="polite">
        No systems registered. Create a{" "}
        <code>system.yaml</code> in your project root and run{" "}
        <code>compliance-report</code> to populate this pane.
      </pre>
    );
  }

  return (
    <div>
      <div style={summaryBarStyle}>
        <div style={summaryItemStyle}>
          <span style={summaryValueStyle}>
            {report.overall_summary.overall_readiness_percent}%
          </span>
          <span style={summaryLabelStyle}>Overall Readiness</span>
        </div>
        <div style={summaryItemStyle}>
          <span style={summaryValueStyle}>
            {report.overall_summary.total_systems}
          </span>
          <span style={summaryLabelStyle}>Systems</span>
        </div>
        <div style={summaryItemStyle}>
          <span style={{ ...summaryValueStyle, color: "#2e7d32" }}>
            {report.overall_summary.total_passed}
          </span>
          <span style={summaryLabelStyle}>Passed</span>
        </div>
        <div style={summaryItemStyle}>
          <span style={{ ...summaryValueStyle, color: "#d32f2f" }}>
            {report.overall_summary.total_failed}
          </span>
          <span style={summaryLabelStyle}>Failed</span>
        </div>
        <div style={summaryItemStyle}>
          <span style={{ ...summaryValueStyle, color: "#ed6c02" }}>
            {report.overall_summary.total_gaps}
          </span>
          <span style={summaryLabelStyle}>Gaps</span>
        </div>
      </div>

      <p style={{ ...mutedStyle, fontSize: 11, marginTop: 4, marginBottom: 16 }}>
        Generated: {report.generated_at}. Open the generated JSON (
        <code>public/compliance-readiness.json</code>) for the raw data.
      </p>

      {report.systems.map((system) => (
        <section key={system.system_id} style={systemSectionStyle}>
          <h3 style={systemTitleStyle}>
            {system.system_name}{" "}
            <span style={systemScoreStyle}>
              ({system.summary.readiness_score_percent}%)
            </span>
          </h3>

          <div style={progressBarOuterStyle}>
            <div
              style={{
                ...progressBarInnerStyle,
                width: `${system.summary.readiness_score_percent}%`,
                background:
                  system.summary.readiness_score_percent >= 90
                    ? "#2e7d32"
                    : system.summary.readiness_score_percent >= 70
                      ? "#ed6c02"
                      : "#d32f2f",
              }}
            />
          </div>

          <table style={tableStyle} aria-label={`Checks for ${system.system_id}`}>
            <caption style={srOnlyStyle}>Checks for {system.system_id}</caption>
            <thead>
              <tr>
                <th scope="col" style={thStyle}>Status</th>
                <th scope="col" style={thStyle}>Check</th>
                <th scope="col" style={thStyle}>Details</th>
              </tr>
            </thead>
            <tbody>
              {system.checks.map((check) => (
                <tr key={check.check_id}>
                  <td style={tdStyle}>
                    <span style={checkBadgeStyle(check.status)}>
                      {check.status}
                    </span>
                  </td>
                  <td style={tdStyle}>
                    {check.check_title}
                    {check.priority === "critical" && (
                      <span style={priorityBadgeStyle}>critical</span>
                    )}
                    {check.priority === "high" && (
                      <span style={priorityBadgeStyle}>high</span>
                    )}
                  </td>
                  <td style={{ ...tdStyle, fontSize: 12, opacity: 0.7 }}>
                    {check.details}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  );
}

function checkBadgeStyle(status: string): React.CSSProperties {
  const colors: Record<string, string> = {
    PASS: "#2e7d32",
    FAIL: "#d32f2f",
    GAP: "#ed6c02",
    SKIP: "#9e9e9e",
  };
  return {
    display: "inline-block",
    padding: "2px 8px",
    borderRadius: 4,
    fontSize: 11,
    fontWeight: 600,
    color: "#fff",
    background: colors[status] ?? "#9e9e9e",
    minWidth: 40,
    textAlign: "center",
  };
}

const mutedStyle: React.CSSProperties = { color: "#666", fontSize: 13 };
const errorStyle: React.CSSProperties = { color: "#d32f2f", fontSize: 13, whiteSpace: "pre-wrap" };

const summaryBarStyle: React.CSSProperties = {
  display: "flex",
  gap: 24,
  padding: "16px 0",
  borderBottom: "1px solid #e5e5e5",
  marginBottom: 16,
};
const summaryItemStyle: React.CSSProperties = { textAlign: "center" };
const summaryValueStyle: React.CSSProperties = {
  display: "block",
  fontSize: 24,
  fontWeight: 700,
};
const summaryLabelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 11,
  color: "#666",
  textTransform: "uppercase",
};

const systemSectionStyle: React.CSSProperties = {
  marginBottom: 24,
};
const systemTitleStyle: React.CSSProperties = {
  margin: "0 0 8px 0",
  fontSize: 16,
};
const systemScoreStyle: React.CSSProperties = {
  fontSize: 13,
  fontWeight: 400,
  color: "#666",
};

const progressBarOuterStyle: React.CSSProperties = {
  height: 4,
  background: "#e5e5e5",
  borderRadius: 2,
  marginBottom: 12,
};
const progressBarInnerStyle: React.CSSProperties = {
  height: "100%",
  borderRadius: 2,
  transition: "width 0.3s ease",
};

const priorityBadgeStyle: React.CSSProperties = {
  display: "inline-block",
  marginLeft: 6,
  fontSize: 10,
  padding: "1px 4px",
  borderRadius: 2,
  background: "#f5f5f5",
  color: "#666",
};

const tableStyle: React.CSSProperties = { width: "100%", borderCollapse: "collapse" };
const thStyle: React.CSSProperties = {
  textAlign: "left",
  fontSize: 11,
  fontWeight: 600,
  color: "#666",
  padding: "6px 8px",
  borderBottom: "2px solid #e5e5e5",
};
const tdStyle: React.CSSProperties = {
  padding: "6px 8px",
  borderBottom: "1px solid #eee",
  fontSize: 13,
};

const srOnlyStyle: React.CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  overflow: "hidden",
  clip: "rect(0 0 0 0)",
};
