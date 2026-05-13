"""Hermes — recursive memory and reflection subagent for TrustLayer.

Memory model (see ADR-003):
  * Payload truncation caps individual string fields so notes stay
    token-bounded even when an upstream agent logs a 100 KB tool result.
  * A bounded LRU cache keeps in-process memory predictable; evicted
    sessions remain on disk in the JSONL sidecar and rehydrate on
    ``reflect()``.
  * Re-ingest is idempotent on ``trace_id``; the sidecar is append-only
    but the in-memory cache and rendered note always reflect the deduped
    truth.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trustlayer.schema import AgentTraceEvent

from .reflector import DeterministicReflector, ReflectionEngine
from .render import render_reflection_note, render_session_note

logger = logging.getLogger("trustlayer.hermes")

MEMORY_DIR = "03_Memory_Traces"
REFLECTION_DIR = "05_Reflections"
STATE_DIR = ".hermes_state"

SessionKey = tuple[str, str]


class HermesAgent:
    """Persists agent traces to an Obsidian vault and reflects over them."""

    def __init__(
        self,
        vault_path: str | Path,
        reflector: ReflectionEngine | None = None,
        *,
        max_payload_chars: int = 2_000,
        max_cached_sessions: int | None = 256,
        persist_events: bool = True,
        state_path: str | Path | None = None,
    ) -> None:
        self.vault_path = Path(vault_path)
        self.memory_dir = self.vault_path / MEMORY_DIR
        self.reflection_dir = self.vault_path / REFLECTION_DIR
        self.state_path = (
            Path(state_path) if state_path is not None else self.vault_path / STATE_DIR
        )
        self.reflector = reflector or DeterministicReflector()
        self.max_payload_chars = max_payload_chars
        self.max_cached_sessions = max_cached_sessions
        self.persist_events = persist_events
        self._sessions: dict[SessionKey, OrderedDict[str, AgentTraceEvent]] = {}
        self._lru: OrderedDict[SessionKey, None] = OrderedDict()

    # -- Ingestion ------------------------------------------------------

    def ingest(
        self,
        events: Iterable[AgentTraceEvent | dict[str, Any] | str],
    ) -> list[Path]:
        touched: set[SessionKey] = set()
        for raw in events:
            event = self._truncate_payload(self._coerce(raw))
            key = (event.agent_id, event.session_id)
            session = self._sessions.setdefault(key, OrderedDict())
            tid = str(event.trace_id)
            is_new = tid not in session
            session[tid] = event
            self._touch(key)
            if is_new and self.persist_events:
                self._append_sidecar(key, event)
            touched.add(key)
        written = [self._flush_session(key) for key in sorted(touched)]
        self._maybe_evict()
        return written

    def ingest_jsonl(self, jsonl_path: str | Path) -> list[Path]:
        with Path(jsonl_path).open("r", encoding="utf-8") as fh:
            return self.ingest(line for line in fh if line.strip())

    # -- Reflection -----------------------------------------------------

    def reflect(self) -> Path | None:
        keys = self._all_known_keys()
        if not keys:
            return None
        summaries = []
        for key in sorted(keys):
            events = self._load_events_for(key)
            if events:
                summaries.append(self.reflector.summarise_session(events))
        if not summaries:
            return None
        reflection = self.reflector.synthesise(summaries)
        self.reflection_dir.mkdir(parents=True, exist_ok=True)
        out_path = (
            self.reflection_dir
            / f"reflection-{datetime.now(timezone.utc).date().isoformat()}.md"
        )
        out_path.write_text(
            render_reflection_note(reflection, summaries),
            encoding="utf-8",
        )
        logger.info("Hermes wrote reflection: %s", out_path)
        return out_path

    # -- Introspection --------------------------------------------------

    @property
    def session_keys(self) -> list[SessionKey]:
        return sorted(self._sessions)

    def session_events(
        self, agent_id: str, session_id: str
    ) -> list[AgentTraceEvent]:
        key = (agent_id, session_id)
        if key in self._sessions:
            return self._ordered_events(key)
        return self._load_sidecar(key)

    # -- Internals: discovery / rehydration -----------------------------

    def _all_known_keys(self) -> set[SessionKey]:
        keys: set[SessionKey] = set(self._sessions)
        if self.persist_events and self.state_path.exists():
            for agent_dir in self.state_path.iterdir():
                if not agent_dir.is_dir():
                    continue
                for sidecar in agent_dir.glob("*.events.jsonl"):
                    session_id = sidecar.name.removesuffix(".events.jsonl")
                    keys.add((agent_dir.name, session_id))
        return keys

    def _load_events_for(self, key: SessionKey) -> list[AgentTraceEvent]:
        if key in self._sessions:
            return self._ordered_events(key)
        return self._load_sidecar(key)

    def _load_sidecar(self, key: SessionKey) -> list[AgentTraceEvent]:
        agent_id, session_id = key
        path = self._sidecar_path(agent_id, session_id)
        if not path.exists():
            return []
        events: list[AgentTraceEvent] = []
        seen: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            evt = AgentTraceEvent.model_validate_json(stripped)
            tid = str(evt.trace_id)
            if tid in seen:
                continue
            seen.add(tid)
            events.append(evt)
        events.sort(key=lambda e: e.timestamp)
        return events

    def _append_sidecar(self, key: SessionKey, event: AgentTraceEvent) -> None:
        agent_id, session_id = key
        path = self._sidecar_path(agent_id, session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(event.model_dump_json() + "\n")

    def _sidecar_path(self, agent_id: str, session_id: str) -> Path:
        return self.state_path / _safe(agent_id) / f"{_safe(session_id)}.events.jsonl"

    # -- Internals: markdown flush --------------------------------------

    def _flush_session(self, key: SessionKey) -> Path:
        events = self._ordered_events(key)
        agent_id, session_id = key
        path = self._session_path(agent_id, session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_session_note(events), encoding="utf-8")
        logger.info("Hermes wrote session note: %s", path)
        return path

    def _ordered_events(self, key: SessionKey) -> list[AgentTraceEvent]:
        return sorted(self._sessions[key].values(), key=lambda e: e.timestamp)

    def _session_path(self, agent_id: str, session_id: str) -> Path:
        return self.memory_dir / _safe(agent_id) / f"{_safe(session_id)}.md"

    # -- Internals: LRU + truncation -----------------------------------

    def _touch(self, key: SessionKey) -> None:
        self._lru.pop(key, None)
        self._lru[key] = None

    def _maybe_evict(self) -> None:
        if self.max_cached_sessions is None:
            return
        while len(self._lru) > self.max_cached_sessions:
            old_key, _ = self._lru.popitem(last=False)
            evicted = self._sessions.pop(old_key, None)
            if evicted is not None:
                logger.info(
                    "Hermes evicted %s (%d events) from cache",
                    old_key,
                    len(evicted),
                )

    def _truncate_payload(self, event: AgentTraceEvent) -> AgentTraceEvent:
        if self.max_payload_chars <= 0:
            return event
        truncated = self._truncate_value(event.payload)
        return event.model_copy(update={"payload": truncated})

    def _truncate_value(self, value: Any) -> Any:
        limit = self.max_payload_chars
        if isinstance(value, str):
            if len(value) > limit:
                return value[:limit] + f"<...truncated {len(value) - limit} chars>"
            return value
        if isinstance(value, dict):
            return {k: self._truncate_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._truncate_value(v) for v in value]
        return value

    @staticmethod
    def _coerce(
        raw: AgentTraceEvent | dict[str, Any] | str,
    ) -> AgentTraceEvent:
        if isinstance(raw, AgentTraceEvent):
            return raw
        if isinstance(raw, str):
            return AgentTraceEvent.model_validate_json(raw)
        return AgentTraceEvent.model_validate(raw)


def _safe(value: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_." else "_" for c in value)
    return cleaned or "unknown"
