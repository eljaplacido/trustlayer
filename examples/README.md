# TrustLayer end-to-end examples

## `end_to_end_demo.py`

Exercises the full stack — SDK → Guardian → JSONL → Hermes → Obsidian
vault — across four canonical policy-decision scenarios:

| # | Scenario | Tool | Cynefin domain | Expected verdict |
|---|---|---|---|---|
| A | PASS, allowed by rule | `calculator` | CLEAR | `PASS` |
| B | FAIL, blocked by rule | `external_llm` | COMPLICATED | `FAIL` |
| C | ESCALATE, by rule | `human_callout` | COMPLEX | `ESCALATE` |
| D | ESCALATE, Cynefin default | `novel_tool` | CHAOTIC | `ESCALATE` |

### Prerequisites

```bash
# 1. Install the Python SDK
cd sdks/python && pip install -e .

# 2. Start the guardian (in another terminal)
cd core-rs && cargo run --release --features server --bin trustlayer-guardian
```

### Run

From the repo root, with `skills/` on `PYTHONPATH`:

```powershell
$env:PYTHONPATH = "$PWD\sdks\python\src;$PWD\skills"
python examples\end_to_end_demo.py
```

### What you'll see
- Verdicts printed for each scenario.
- A JSONL stream written to `examples/.demo_traces.jsonl` (gitignored).
- One Obsidian-flavoured markdown note per session in
  `obsidian_vault/03_Memory_Traces/demo_agent/`.
- A dated reflection in `obsidian_vault/05_Reflections/`.

### Customise
- Edit `core-rs/policies/default.json` and restart the guardian to test
  policy changes (e.g. flip `allow_calculator` to `FAIL`).
- Kill the guardian to test the SDK's fail-open behaviour — every
  verdict comes back as `policy: "fallback", decision: "PASS"`.
- Append your own scenarios to the `scenarios` list in `main()`.

See [`docs/CURRENT_STATUS.md`](../docs/CURRENT_STATUS.md) for the full
roadmap and [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) for the
layered design.
