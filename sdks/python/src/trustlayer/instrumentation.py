"""Decorator-style instrumentation helpers."""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from .schema import EventType, Metrics, ToolCallPayload, ToolResultPayload
from .tracer import Tracer

P = ParamSpec("P")
R = TypeVar("R")


def instrument_tool(
    tracer: Tracer,
    tool_name: str | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Wrap a callable so each invocation produces TOOL_CALL/TOOL_RESULT events."""

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        name = tool_name or func.__name__

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            tracer.emit(
                EventType.TOOL_CALL,
                payload=ToolCallPayload(
                    tool_name=name,
                    tool_args=_safe_args(args, kwargs),
                ).model_dump(),
            )
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                tracer.emit(
                    EventType.TOOL_RESULT,
                    payload=ToolResultPayload(
                        tool_name=name, error=repr(exc)
                    ).model_dump(),
                    metrics=Metrics(latency_ms=(time.perf_counter() - start) * 1000),
                )
                raise
            tracer.emit(
                EventType.TOOL_RESULT,
                payload=ToolResultPayload(tool_name=name, result=result).model_dump(),
                metrics=Metrics(latency_ms=(time.perf_counter() - start) * 1000),
            )
            return result

        return wrapper

    return decorator


def _safe_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    return {"args": [_repr(a) for a in args], "kwargs": {k: _repr(v) for k, v in kwargs.items()}}


def _repr(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
