import { useEffect, useRef, useState } from "react";
import {
  askAdvisor,
  fetchAdvisorHealth,
  fetchAdvisorModels,
  type AdvisorHealth,
  type AdvisorReply,
  type AdvisorRun,
} from "./api.js";

interface Turn {
  id: number;
  question: string;
  reply?: AdvisorReply;
  error?: string;
  pending: boolean;
}

type HealthState =
  | { kind: "loading" }
  | { kind: "ok"; health: AdvisorHealth; models: string[] }
  | { kind: "error"; message: string };

/**
 * Bring-your-own-model chat over the trace store (ADR-020).
 *
 * The pane deliberately renders the *run record*, not just the prose: which
 * model answered, how many events it was shown, and how many of its findings
 * were suppressed as ungrounded. A grounded finding is one whose citations
 * check out — not one that is known to be correct — so the pane never presents
 * an answer without the provenance needed to judge it.
 */
export function AdvisorPane() {
  const [health, setHealth] = useState<HealthState>({ kind: "loading" });
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const nextId = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetchAdvisorHealth(controller.signal),
      fetchAdvisorModels(controller.signal).catch(() => ({
        provider: "",
        current: "",
        models: [] as string[],
      })),
    ])
      .then(([h, m]) => setHealth({ kind: "ok", health: h, models: m.models }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setHealth({
          kind: "error",
          message: err instanceof Error ? err.message : String(err),
        });
      });
    return () => controller.abort();
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed) return;

    const id = nextId.current++;
    setTurns((prev) => [...prev, { id, question: trimmed, pending: true }]);
    setQuestion("");

    try {
      const reply = await askAdvisor(trimmed);
      setTurns((prev) =>
        prev.map((t) => (t.id === id ? { ...t, reply, pending: false } : t)),
      );
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setTurns((prev) =>
        prev.map((t) => (t.id === id ? { ...t, error: message, pending: false } : t)),
      );
    }
  }

  if (health.kind === "loading") {
    return <p>Checking the evaluator service…</p>;
  }

  if (health.kind === "error") {
    return (
      <div>
        <p style={{ color: "#a00" }}>
          Evaluator service unreachable: {health.message}
        </p>
        <p style={paleStyle}>
          Start it with <code>trustlayer-eval-serve</code>, and set{" "}
          <code>TRUSTLAYER_EVAL_PROVIDER</code> to choose a model. Deterministic
          panes are unaffected.
        </p>
      </div>
    );
  }

  const configured = health.health.provider !== "null";

  return (
    <div>
      <ProviderBanner health={health.health} models={health.models} />

      {!configured && (
        <p style={{ ...paleStyle, marginTop: 12 }}>
          No provider is configured, so no model will be called. Set{" "}
          <code>TRUSTLAYER_EVAL_PROVIDER</code> to <code>agentcenter</code>,{" "}
          <code>ollama</code>, <code>openai_compat</code>, or{" "}
          <code>anthropic</code> to enable this pane.
        </p>
      )}

      <ol style={{ listStyle: "none", padding: 0, margin: "16px 0 0" }}>
        {turns.map((turn) => (
          <li key={turn.id} style={{ marginBottom: 20 }}>
            <p style={{ margin: "0 0 6px", fontWeight: 600 }}>{turn.question}</p>
            {turn.pending && (
              <p aria-live="polite" style={paleStyle}>
                Asking {health.health.model}…
              </p>
            )}
            {turn.error && (
              <p aria-live="polite" style={{ color: "#a00", margin: 0 }}>
                {turn.error}
              </p>
            )}
            {turn.reply && <RunView run={turn.reply.run} reply={turn.reply} />}
          </li>
        ))}
      </ol>

      <form onSubmit={submit} style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <label htmlFor="advisor-question" style={srOnlyStyle}>
          Ask about these insights
        </label>
        <input
          id="advisor-question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask about these traces, or ask for a fix…"
          disabled={!configured}
          style={{ flex: 1, padding: "8px 10px", fontSize: 14 }}
        />
        <button type="submit" disabled={!configured || !question.trim()}>
          Ask
        </button>
      </form>
    </div>
  );
}

function ProviderBanner(props: { health: AdvisorHealth; models: string[] }) {
  const { health, models } = props;
  // Residency is stated in the UI, not just enforced in the backend: an
  // operator deciding whether to paste sensitive context into the box needs to
  // know where the answer is computed before they type it.
  const local = health.residency === "local";
  return (
    <div style={bannerStyle}>
      <span>
        <strong>{health.provider}</strong> · {health.model}
      </span>
      <span
        style={{
          padding: "2px 8px",
          borderRadius: 4,
          background: local ? "#e6f4ea" : "#fdecea",
          color: local ? "#1e4620" : "#611a15",
        }}
      >
        {local ? "local inference" : `residency: ${health.residency}`}
      </span>
      <span style={paleStyle}>
        {health.guardian_enabled
          ? "guardian-checked"
          : "guardian off — calls are not policy-checked"}
      </span>
      {models.length > 0 && (
        <span style={paleStyle}>{models.length} models available</span>
      )}
    </div>
  );
}

function RunView(props: { run: AdvisorRun; reply: AdvisorReply }) {
  const { run, reply } = props;
  return (
    <div style={{ borderLeft: "3px solid #d0d0d0", paddingLeft: 12 }}>
      {reply.fell_back && (
        <p style={{ ...paleStyle, margin: "0 0 6px" }}>
          agentcenter was unreachable; answered by Ollama directly, so this run
          was not recorded in agentcenter&apos;s KPI store.
        </p>
      )}

      {run.narrative && <p style={{ margin: "0 0 10px" }}>{run.narrative}</p>}

      {run.findings.length === 0 && !run.narrative && (
        <p style={paleStyle}>
          No grounded findings. The evidence did not support a claim.
        </p>
      )}

      {run.findings.map((finding, i) => (
        <div key={i} style={findingStyle}>
          <p style={{ margin: "0 0 4px" }}>{finding.claim}</p>
          {finding.remediation && (
            <pre style={remediationStyle}>{finding.remediation}</pre>
          )}
          <p style={{ ...paleStyle, margin: 0 }}>
            {/* Text, not colour alone — a severity a screen reader cannot
                announce is not a severity. */}
            severity {finding.severity} · confidence {finding.confidence} ·{" "}
            {finding.cited_trace_ids.length} cited event
            {finding.cited_trace_ids.length === 1 ? "" : "s"}
            {finding.human_review_required && " · needs human review"}
          </p>
          <details>
            <summary style={paleStyle}>Citations</summary>
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {finding.cited_trace_ids.map((id) => (
                <li key={id}>
                  <code style={{ fontSize: 12 }}>{id}</code>
                </li>
              ))}
            </ul>
          </details>
        </div>
      ))}

      <p style={{ ...paleStyle, marginTop: 8 }}>
        {run.model} · {run.evidence_window.event_count} events in window ·{" "}
        {Math.round(run.duration_ms)} ms
        {run.ungrounded_rejected > 0 && (
          <>
            {" "}
            ·{" "}
            <strong>
              {run.ungrounded_rejected} finding
              {run.ungrounded_rejected === 1 ? "" : "s"} suppressed as ungrounded
            </strong>
          </>
        )}
      </p>
    </div>
  );
}

const bannerStyle: React.CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 12,
  alignItems: "center",
  fontSize: 13,
};

const paleStyle: React.CSSProperties = { opacity: 0.7, fontSize: 13 };

const findingStyle: React.CSSProperties = {
  border: "1px solid #e5e5e5",
  borderRadius: 6,
  padding: 10,
  marginBottom: 8,
  background: "#fff",
};

const remediationStyle: React.CSSProperties = {
  background: "#f6f8fa",
  padding: 8,
  borderRadius: 4,
  overflowX: "auto",
  fontSize: 12,
  margin: "0 0 6px",
};

const srOnlyStyle: React.CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  overflow: "hidden",
  clip: "rect(0 0 0 0)",
  whiteSpace: "nowrap",
};
