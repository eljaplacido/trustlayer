"""Code-graph importer for Hermes — mirrors a GitNexus-style graph into the vault.

See ADR-005. The importer is decoupled from GitNexus's on-disk storage:
it reads a generic JSON shape (``{nodes: [...], edges: [...]}``) so the
internal GitNexus format can change without breaking the bridge, and so
tests can construct synthetic graphs without GitNexus installed.

Output: one Obsidian markdown note per :class:`CodeNode` written to
``<vault>/06_Code_Graph/<language>/<safe_id>.md``. Edges become
``[[wikilinks]]`` so the static code graph is navigable in Obsidian
side-by-side with ``03_Memory_Traces/`` and ``05_Reflections/``.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .hermes_agent import _safe
from .render import _yaml_lines

logger = logging.getLogger("trustlayer.hermes.code_graph")

CODE_GRAPH_DIR = "06_Code_Graph"
UNKNOWN_LANG = "unknown"

EDGE_KIND_LABELS: dict[str, tuple[str, str]] = {
    "imports": ("Imports", "Imported by"),
    "calls": ("Calls", "Called by"),
    "inherits": ("Inherits from", "Inherited by"),
    "contains": ("Contains", "Contained in"),
}


class CodeNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    kind: str  # "file" | "class" | "function" | "module" | "cluster" | ...
    name: str
    path: str | None = None
    language: str | None = None
    cluster_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CodeEdge(BaseModel):
    model_config = ConfigDict(extra="allow")

    src: str
    dst: str
    kind: str  # "imports" | "calls" | "inherits" | "contains" | ...


class CodeGraph(BaseModel):
    nodes: list[CodeNode] = Field(default_factory=list)
    edges: list[CodeEdge] = Field(default_factory=list)


class CodeGraphImporter:
    """Read a JSON code graph and emit one Obsidian note per node."""

    def __init__(
        self,
        vault_path: str | Path,
        gitnexus_root: str | Path,
    ) -> None:
        self.vault_path = Path(vault_path)
        self.gitnexus_root = Path(gitnexus_root)
        self.code_graph_dir = self.vault_path / CODE_GRAPH_DIR

    # -- Public API -----------------------------------------------------

    def import_graph(self) -> list[Path]:
        graph = self.load_graph()
        return self.write_notes(graph)

    def load_graph(self) -> CodeGraph:
        single = self.gitnexus_root / "graph.json"
        if single.exists():
            data = json.loads(single.read_text(encoding="utf-8"))
            return CodeGraph.model_validate(data)
        nodes_path = self.gitnexus_root / "nodes.json"
        edges_path = self.gitnexus_root / "edges.json"
        if nodes_path.exists() and edges_path.exists():
            nodes = json.loads(nodes_path.read_text(encoding="utf-8"))
            edges = json.loads(edges_path.read_text(encoding="utf-8"))
            return CodeGraph.model_validate({"nodes": nodes, "edges": edges})
        raise FileNotFoundError(
            f"No code graph found at {self.gitnexus_root}: expected "
            "graph.json or nodes.json + edges.json."
        )

    def write_notes(self, graph: CodeGraph) -> list[Path]:
        nodes_by_id = {n.id: n for n in graph.nodes}
        out_edges: dict[str, list[CodeEdge]] = defaultdict(list)
        in_edges: dict[str, list[CodeEdge]] = defaultdict(list)
        for edge in graph.edges:
            out_edges[edge.src].append(edge)
            in_edges[edge.dst].append(edge)
        written: list[Path] = []
        for node in graph.nodes:
            path = self._note_path(node)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                self._render_node(
                    node,
                    out_edges.get(node.id, []),
                    in_edges.get(node.id, []),
                    nodes_by_id,
                ),
                encoding="utf-8",
            )
            written.append(path)
            logger.info("CodeGraphImporter wrote: %s", path)
        return written

    # -- Internals ------------------------------------------------------

    def _note_path(self, node: CodeNode) -> Path:
        language = _safe(node.language or UNKNOWN_LANG)
        return self.code_graph_dir / language / f"{_safe(node.id)}.md"

    def _wikilink(self, node: CodeNode) -> str:
        language = _safe(node.language or UNKNOWN_LANG)
        return f"[[{CODE_GRAPH_DIR}/{language}/{_safe(node.id)}|{node.name}]]"

    def _render_node(
        self,
        node: CodeNode,
        outgoing: Iterable[CodeEdge],
        incoming: Iterable[CodeEdge],
        nodes_by_id: dict[str, CodeNode],
    ) -> str:
        front: dict[str, Any] = {
            "id": node.id,
            "kind": node.kind,
            "name": node.name,
            "path": node.path or "",
            "language": node.language or UNKNOWN_LANG,
            "cluster": node.cluster_id or "",
            "tags": ["code-graph", f"kind/{node.kind}", f"lang/{node.language or UNKNOWN_LANG}"],
        }
        parts: list[str] = ["---", *_yaml_lines(front), "---", ""]
        parts.append(f"# `{node.name}` ({node.kind})")
        parts.append("")
        if node.path:
            parts.append(f"- **Source**: `{node.path}`")
        if node.language:
            parts.append(f"- **Language**: {node.language}")
        if node.cluster_id:
            parts.append(f"- **Cluster**: `{node.cluster_id}`")
        parts.append("")

        outgoing_by_kind: dict[str, list[CodeEdge]] = defaultdict(list)
        for edge in outgoing:
            outgoing_by_kind[edge.kind].append(edge)
        incoming_by_kind: dict[str, list[CodeEdge]] = defaultdict(list)
        for edge in incoming:
            incoming_by_kind[edge.kind].append(edge)

        for kind, (out_label, in_label) in EDGE_KIND_LABELS.items():
            if kind in outgoing_by_kind:
                parts.append(f"## {out_label}")
                for edge in outgoing_by_kind[kind]:
                    target = nodes_by_id.get(edge.dst)
                    parts.append(f"- {self._link_for(target, edge.dst)}")
                parts.append("")
            if kind in incoming_by_kind:
                parts.append(f"## {in_label}")
                for edge in incoming_by_kind[kind]:
                    source = nodes_by_id.get(edge.src)
                    parts.append(f"- {self._link_for(source, edge.src)}")
                parts.append("")

        extra_out = {k: v for k, v in outgoing_by_kind.items() if k not in EDGE_KIND_LABELS}
        if extra_out:
            parts.append("## Other outgoing")
            for kind, edges in sorted(extra_out.items()):
                for edge in edges:
                    target = nodes_by_id.get(edge.dst)
                    parts.append(f"- `{kind}` -> {self._link_for(target, edge.dst)}")
            parts.append("")

        if node.metadata:
            parts.append("## Metadata")
            parts.append(f"```json\n{json.dumps(node.metadata, indent=2, sort_keys=True, default=str)}\n```")
            parts.append("")

        return "\n".join(parts).rstrip() + "\n"

    def _link_for(self, node: CodeNode | None, fallback_id: str) -> str:
        if node is None:
            return f"`{fallback_id}` _(external)_"
        return self._wikilink(node)
