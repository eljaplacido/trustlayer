"""The evidence window an evaluator is allowed to cite (ADR-020 §3, §7).

The window is the *only* set of events a finding may cite. Anything outside it
is, by construction, a fabrication — which is what makes the grounding check a
set-membership test rather than a judgement call.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from typing import Any
from uuid import UUID

from .models import EvidenceWindowRef


class EvidenceWindow:
    """A queried set of events, plus the ids that may be cited against it."""

    def __init__(self, events: Sequence[dict[str, Any]], *, query: str) -> None:
        self._events = list(events)
        self._query = query
        self._by_id: dict[UUID, dict[str, Any]] = {}
        for event in self._events:
            raw = event.get("trace_id")
            if not isinstance(raw, str):
                continue
            try:
                self._by_id[UUID(raw)] = event
            except ValueError:
                # A malformed id in the store is a store problem, not a reason
                # to abort evaluation — it simply is not citable.
                continue

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    @property
    def trace_ids(self) -> frozenset[UUID]:
        return frozenset(self._by_id)

    def __len__(self) -> int:
        return len(self._events)

    def __contains__(self, trace_id: object) -> bool:
        return trace_id in self._by_id

    def get(self, trace_id: UUID) -> dict[str, Any] | None:
        return self._by_id.get(trace_id)

    def result_hash(self) -> str:
        """Hash of the window's contents, for re-checkability (ADR-020 §7).

        Sorted by trace_id and serialised with sorted keys, so the hash is a
        property of the *set of events*, not of the order the store happened to
        return them. Re-running the query later and getting a different hash
        means the window moved — the finding is not directly comparable.
        """
        canonical = json.dumps(
            sorted(self._events, key=lambda e: str(e.get("trace_id", ""))),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def ref(self) -> EvidenceWindowRef:
        seqs = [e["seq"] for e in self._events if isinstance(e.get("seq"), int)]
        return EvidenceWindowRef(
            query=self._query,
            result_hash=self.result_hash(),
            event_count=len(self._events),
            first_seq=min(seqs) if seqs else None,
            last_seq=max(seqs) if seqs else None,
        )

    def render(self, *, limit: int | None = None) -> str:
        """Render the window for a prompt, one line per event.

        Every line leads with the `trace_id`, because that id is what a finding
        must cite — a model that cannot see the ids cannot ground anything.
        """
        lines: list[str] = []
        for event in self._events[: limit if limit is not None else len(self._events)]:
            lines.append(
                "- trace_id={trace_id} type={event_type} agent={agent_id} "
                "session={session_id} time={timestamp}\n  payload={payload}".format(
                    trace_id=event.get("trace_id"),
                    event_type=event.get("event_type"),
                    agent_id=event.get("agent_id"),
                    session_id=event.get("session_id"),
                    timestamp=event.get("timestamp"),
                    payload=json.dumps(event.get("payload", {}), sort_keys=True)[:400],
                )
            )
        if limit is not None and len(self._events) > limit:
            lines.append(f"- ... {len(self._events) - limit} further events not shown")
        return "\n".join(lines)


def window_from_events(
    events: Iterable[dict[str, Any]], *, query: str = "unspecified"
) -> EvidenceWindow:
    return EvidenceWindow(list(events), query=query)
