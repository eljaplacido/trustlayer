import { useEffect, useState } from "react";

import {
  fetchReflection,
  fetchReflections,
  type Reflection,
  type ReflectionMeta,
} from "./api.js";

type ListStatus =
  | { kind: "loading" }
  | { kind: "ok"; metas: ReflectionMeta[] }
  | { kind: "error"; message: string };

type ViewStatus =
  | { kind: "idle" }
  | { kind: "loading"; name: string }
  | { kind: "ok"; reflection: Reflection }
  | { kind: "error"; name: string; message: string };

const REFRESH_MS = 15000;

export function ReflectionsPane() {
  const [list, setList] = useState<ListStatus>({ kind: "loading" });
  const [view, setView] = useState<ViewStatus>({ kind: "idle" });

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    async function tick() {
      try {
        const metas = await fetchReflections(controller.signal);
        if (!cancelled) setList({ kind: "ok", metas });
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

  async function open(name: string) {
    setView({ kind: "loading", name });
    try {
      const reflection = await fetchReflection(name);
      setView({ kind: "ok", reflection });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setView({ kind: "error", name, message });
    }
  }

  if (list.kind === "loading") {
    return <pre style={mutedStyle}>loading…</pre>;
  }
  if (list.kind === "error") {
    return <pre style={errorStyle}>{list.message}</pre>;
  }
  if (list.metas.length === 0) {
    return (
      <pre style={mutedStyle}>
        No reflections yet. Hermes writes them on a reflection pass:{"\n"}
        {"  "}PYTHONPATH=skills python -m hermes.cli --vault obsidian_vault
        ingest traces.jsonl --reflect{"\n"}
        or call the <code>trustlayer_hermes_reflect</code> MCP tool.
      </pre>
    );
  }

  const activeName =
    view.kind === "ok"
      ? view.reflection.name
      : view.kind === "loading" || view.kind === "error"
        ? view.name
        : null;

  return (
    <div style={layoutStyle}>
      <ul style={listStyle}>
        {list.metas.map((m) => (
          <li key={m.name}>
            <button
              type="button"
              style={m.name === activeName ? itemActiveStyle : itemStyle}
              onClick={() => open(m.name)}
            >
              {m.date}
            </button>
          </li>
        ))}
      </ul>
      <div style={viewStyle}>{renderView(view)}</div>
    </div>
  );
}

function renderView(view: ViewStatus) {
  switch (view.kind) {
    case "idle":
      return <pre style={mutedStyle}>Select a reflection date.</pre>;
    case "loading":
      return <pre style={mutedStyle}>loading {view.name}…</pre>;
    case "error":
      return <pre style={errorStyle}>{view.message}</pre>;
    case "ok":
      return <pre style={markdownStyle}>{view.reflection.content}</pre>;
  }
}

const layoutStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "140px 1fr",
  gap: 16,
};

const listStyle: React.CSSProperties = {
  listStyle: "none",
  margin: 0,
  padding: 0,
  display: "flex",
  flexDirection: "column",
  gap: 4,
};

const itemStyle: React.CSSProperties = {
  width: "100%",
  textAlign: "left",
  padding: "6px 8px",
  border: "1px solid #e5e5e5",
  borderRadius: 6,
  background: "#fff",
  cursor: "pointer",
  fontSize: 13,
  fontVariantNumeric: "tabular-nums",
};

const itemActiveStyle: React.CSSProperties = {
  ...itemStyle,
  background: "#f0f4ff",
  borderColor: "#bcd",
};

const viewStyle: React.CSSProperties = {
  minHeight: 80,
};

const markdownStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 12.5,
  lineHeight: 1.5,
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  background: "#fff",
  border: "1px solid #e5e5e5",
  borderRadius: 6,
  padding: 12,
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
