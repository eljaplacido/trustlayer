/**
 * Minimal example: instrumenting an agent that picks a tool, runs it, and
 * feeds the result into a follow-up reasoning step.
 *
 * Uses a stub fetch that prints emitted events instead of POSTing them.
 *
 * Run with:
 *   npx tsx examples/agent.ts
 */

import { Tracer, TrustLayerClient, wrapTool } from "../src/index.js";

const printingFetch: typeof fetch = (async (
  _url: string | URL | Request,
  init?: RequestInit,
) => {
  console.log(
    "[trustlayer]",
    JSON.stringify(JSON.parse(init!.body as string), null, 2),
  );
  return new Response(null, { status: 202 });
}) as typeof fetch;

async function main(): Promise<void> {
  const tracer = new Tracer({
    agentId: "ts-demo",
    client: new TrustLayerClient({ fetch: printingFetch }),
  });

  const calculator = wrapTool(tracer, "calculator", (expr: string) =>
    // eslint-disable-next-line @typescript-eslint/no-implied-eval
    Function(`"use strict"; return (${expr})`)() as number,
  );

  const webSearch = wrapTool(tracer, "web_search", (q: string) =>
    Array.from({ length: 2 }, (_v, i) => `Result for ${q} #${i}`),
  );

  await tracer.emit("AGENT_START", { goal: "Answer a math question" });
  await tracer.policyCheck("tool_allowlist", "invoke calculator", "PASS");

  const answer = await calculator("(2 + 3) * 7");
  const hits = await webSearch("trustlayer schema");

  await tracer.emit("AGENT_END", { answer, supporting_docs: hits });
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
