"""Hermes — recursive memory and reflection subagent for TrustLayer.

Consumes ``trustlayer.AgentTraceEvent`` records and writes Obsidian-flavoured
markdown into the vault. See ``obsidian_vault/01_Architecture/ADR-002``.
"""

from .code_graph import CodeEdge, CodeGraph, CodeGraphImporter, CodeNode
from .hermes_agent import HermesAgent
from .reflector import (
    DeterministicReflector,
    Reflection,
    ReflectionEngine,
    SessionSummary,
)
from .render import render_reflection_note, render_session_note

__all__ = [
    "CodeEdge",
    "CodeGraph",
    "CodeGraphImporter",
    "CodeNode",
    "DeterministicReflector",
    "HermesAgent",
    "Reflection",
    "ReflectionEngine",
    "SessionSummary",
    "render_reflection_note",
    "render_session_note",
]

__version__ = "0.1.0"
