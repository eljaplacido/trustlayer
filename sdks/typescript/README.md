# @trustlayer/sdk (TypeScript)

Lightweight TypeScript SDK for emitting agent trace events to a TrustLayer
collector.

## Install

```bash
npm install
npm run build
```

## Quickstart

```ts
import { Tracer } from "@trustlayer/sdk";

const tracer = new Tracer({ agentId: "researcher-1" });

const answer = await tracer.toolCall(
  "web.search",
  { q: "trustlayer" },
  () => runSearch("trustlayer"),
);

await tracer.policyCheck("pii_redaction", "send_to_llm", "PASS");
```

The wire format is defined in `docs/SCHEMA.md` and mirrored in
`sdks/python/src/trustlayer/schema.py`.

## Test

```bash
npm test
```
