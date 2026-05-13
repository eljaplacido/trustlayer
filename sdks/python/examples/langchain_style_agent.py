"""Minimal example: instrumenting a LangChain-style tool-using agent.

This file does *not* depend on LangChain — it mimics the call patterns
(tools as callables, an agent that picks one and feeds the result into the
next reasoning step) so the SDK behavior is observable in isolation.

Run with:
    python examples/langchain_style_agent.py
"""

from __future__ import annotations

import json

import httpx

from trustlayer import (
    EventType,
    PolicyCheckResult,
    Tracer,
    TrustLayerClient,
    instrument_tool,
)


def _stdout_collector() -> TrustLayerClient:
    """Collector that prints emitted events instead of POSTing them anywhere."""

    def handler(request: httpx.Request) -> httpx.Response:
        print("[trustlayer]", json.dumps(json.loads(request.content), indent=2))
        return httpx.Response(202)

    return TrustLayerClient(transport=httpx.MockTransport(handler))


def main() -> None:
    tracer = Tracer(agent_id="langchain-demo", client=_stdout_collector())

    @instrument_tool(tracer, tool_name="calculator")
    def calculator(expression: str) -> float:
        return float(eval(expression, {"__builtins__": {}}, {}))

    @instrument_tool(tracer, tool_name="web_search")
    def web_search(query: str) -> list[str]:
        return [f"Result for {query!r} #{i}" for i in range(2)]

    tracer.emit(EventType.AGENT_START, payload={"goal": "Answer a math question"})
    tracer.policy_check(
        "tool_allowlist",
        action="invoke calculator",
        result=PolicyCheckResult.PASS,
    )

    answer = calculator("(2 + 3) * 7")
    hits = web_search("trustlayer schema")

    tracer.emit(
        EventType.AGENT_END,
        payload={"answer": answer, "supporting_docs": hits},
    )


if __name__ == "__main__":
    main()
