"""End-to-end TrustLayer demo: SDK -> Guardian -> JSONL -> Hermes -> Vault.

Exercises four canonical policy-decision scenarios:
  A. PASS    — calculator (allowed by rule)
  B. FAIL    — external_llm (blocked by rule)
  C. ESCAL   — human_callout in COMPLEX domain (escalated by rule)
  D. CHAOTIC — unknown tool in CHAOTIC domain (default escalation, no rule)

Prerequisites:
  - Python SDK installed editable: ``pip install -e sdks/python``
  - ``skills/`` on PYTHONPATH (so ``import hermes`` resolves)
  - Guardian server running on http://127.0.0.1:8089:
        cd core-rs
        cargo run --release --features server --bin trustlayer-guardian

Run:
    python examples/end_to_end_demo.py

Outputs:
  - ``examples/.demo_traces.jsonl`` — the raw event stream (gitignored)
  - ``obsidian_vault/03_Memory_Traces/demo_agent/session-{A,B,C,D}.md``
  - ``obsidian_vault/05_Reflections/reflection-<today>.md``
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from trustlayer import (
    AgentTraceEvent,
    CynefinDomain,
    EventType,
    GuardianClient,
    Metrics,
    PolicyCheckPayload,
    PolicyCheckResult,
    ToolCallPayload,
    ToolResultPayload,
)
from hermes.hermes_agent import HermesAgent

REPO = Path(__file__).resolve().parents[1]
JSONL_PATH = REPO / "examples" / ".demo_traces.jsonl"
VAULT = REPO / "obsidian_vault"
GUARDIAN_URL = "http://127.0.0.1:8089/v1/check"


def emit(events: list[AgentTraceEvent], event: AgentTraceEvent) -> None:
    """Add to the in-memory list AND append to the JSONL tee."""
    events.append(event)
    with JSONL_PATH.open("a", encoding="utf-8") as fh:
        fh.write(event.model_dump_json() + "\n")


def make_event(
    *,
    agent_id: str,
    session_id: str,
    event_type: EventType,
    payload: dict,
    cynefin_domain: CynefinDomain = CynefinDomain.DISORDER,
    latency_ms: float | None = None,
) -> AgentTraceEvent:
    return AgentTraceEvent(
        trace_id=uuid4(),
        agent_id=agent_id,
        session_id=session_id,
        timestamp=datetime.now(timezone.utc),
        event_type=event_type,
        cynefin_domain=cynefin_domain,
        payload=payload,
        metrics=Metrics(latency_ms=latency_ms),
    )


def run_scenario(
    label: str,
    *,
    agent_id: str,
    session_id: str,
    tool_name: str,
    cynefin_domain: CynefinDomain,
    guardian: GuardianClient,
) -> dict:
    """Simulate one tool-using turn. Returns the verdict for inspection."""
    events: list[AgentTraceEvent] = []

    emit(
        events,
        make_event(
            agent_id=agent_id,
            session_id=session_id,
            event_type=EventType.AGENT_START,
            payload={"goal": label},
            cynefin_domain=cynefin_domain,
        ),
    )

    candidate = make_event(
        agent_id=agent_id,
        session_id=session_id,
        event_type=EventType.TOOL_CALL,
        payload=ToolCallPayload(
            tool_name=tool_name, tool_args={"q": "hello"}
        ).model_dump(),
        cynefin_domain=cynefin_domain,
    )
    verdict = guardian.check(candidate)

    # The candidate TOOL_CALL is always recorded so the timeline shows what
    # the agent attempted, even if the guardian denied it.
    emit(events, candidate)
    emit(
        events,
        make_event(
            agent_id=agent_id,
            session_id=session_id,
            event_type=EventType.POLICY_CHECK,
            payload=PolicyCheckPayload(
                policy_name=verdict["policy"],
                action=f"invoke {tool_name}",
                result=PolicyCheckResult(verdict["decision"]),
                reason=verdict["reason"],
            ).model_dump(),
            cynefin_domain=cynefin_domain,
        ),
    )

    if verdict["decision"] == "PASS":
        # The agent would actually run the tool here. Simulate a result.
        emit(
            events,
            make_event(
                agent_id=agent_id,
                session_id=session_id,
                event_type=EventType.TOOL_RESULT,
                payload=ToolResultPayload(
                    tool_name=tool_name, result={"ok": True, "value": 42}
                ).model_dump(),
                latency_ms=5.0,
                cynefin_domain=cynefin_domain,
            ),
        )

    emit(
        events,
        make_event(
            agent_id=agent_id,
            session_id=session_id,
            event_type=EventType.AGENT_END,
            payload={"status": verdict["decision"]},
            cynefin_domain=cynefin_domain,
        ),
    )
    return verdict


def main() -> None:
    JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSONL_PATH.unlink(missing_ok=True)

    print("\n=== TrustLayer end-to-end demo ===")
    print(f"Guardian:  {GUARDIAN_URL}")
    print(f"JSONL tee: {JSONL_PATH.relative_to(REPO).as_posix()}")
    print(f"Vault:     {VAULT.relative_to(REPO).as_posix()}\n")

    with GuardianClient(
        endpoint=GUARDIAN_URL, policy_name="default", timeout=2.0
    ) as guardian:
        scenarios = [
            ("A. PASS    calculator (allowed)",
             "demo_agent", "session-A", "calculator", CynefinDomain.CLEAR),
            ("B. FAIL    external_llm (blocked)",
             "demo_agent", "session-B", "external_llm", CynefinDomain.COMPLICATED),
            ("C. ESCAL   human_callout in COMPLEX",
             "demo_agent", "session-C", "human_callout", CynefinDomain.COMPLEX),
            ("D. CHAOTIC unknown tool, no rule",
             "demo_agent", "session-D", "novel_tool", CynefinDomain.CHAOTIC),
        ]
        for label, agent, session, tool, domain in scenarios:
            verdict = run_scenario(
                label,
                agent_id=agent,
                session_id=session,
                tool_name=tool,
                cynefin_domain=domain,
                guardian=guardian,
            )
            mark = {
                "PASS": "[PASS]   ",
                "FAIL": "[FAIL]   ",
                "ESCALATE": "[ESCAL]  ",
            }[verdict["decision"]]
            print(f"  {mark} {label:50s} -> rule={verdict['rule']!s}")

    print("\n=== Hermes ingest + reflect ===")
    hermes = HermesAgent(VAULT)
    notes = hermes.ingest_jsonl(JSONL_PATH)
    print(f"  wrote {len(notes)} session notes:")
    for n in notes:
        print(f"    - {n.relative_to(REPO).as_posix()}")
    reflection = hermes.reflect()
    if reflection:
        print(f"  reflection: {reflection.relative_to(REPO).as_posix()}")
        body = reflection.read_text(encoding="utf-8")
        head = "\n".join(body.splitlines()[:25])
        print("\n--- reflection (first 25 lines) ---")
        print(head)


if __name__ == "__main__":
    main()
