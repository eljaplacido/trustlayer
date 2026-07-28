import { appendFileSync, mkdirSync } from "node:fs";
import { basename, join } from "node:path";
import type { Plugin } from "@opencode-ai/plugin";

type SessionRoute = { agent: string; model: string };

export default (async ({ directory }) => {
  const sessions = new Map<string, SessionRoute>();
  const logPath = join(directory, ".routekit", "opencode.jsonl");

  const log = (event: Record<string, unknown>) => {
    mkdirSync(join(directory, ".routekit"), { recursive: true });
    appendFileSync(logPath, `${JSON.stringify(event)}\n`);
  };

  return {
    "chat.params": async (input) => {
      const model = input.model as { providerID?: string; id?: string; modelID?: string };
      const modelName = [model.providerID, model.id ?? model.modelID].filter(Boolean).join("/") || "unknown";
      const route = { agent: input.agent, model: modelName };
      sessions.set(input.sessionID, route);
      log({
        ts: Date.now() / 1000,
        project: basename(directory),
        model: route.model,
        context: route.agent,
        complexity: "developer-workflow",
        confidence: 1,
        explored: false,
      });
    },
    "tool.execute.after": async (input, output) => {
      if (input.tool !== "bash") return;
      const command = String(input.args?.command ?? "");
      if (!/\b(pytest|vitest|jest|ruff|mypy|eslint|tsc|build|test|check)\b/i.test(command)) return;

      const exitCode = typeof output.metadata?.exitCode === "number"
        ? output.metadata.exitCode
        : Number((output.output.match(/exit code:\s*(\d+)/i) ?? [])[1]);
      if (!Number.isInteger(exitCode)) return;

      const route = sessions.get(input.sessionID);
      if (!route) return;
      log({
        ts: Date.now() / 1000,
        project: basename(directory),
        model: route.model,
        context: route.agent,
        ok: exitCode === 0,
      });
    },
  };
}) satisfies Plugin;
