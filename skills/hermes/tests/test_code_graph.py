from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes.cli import main as cli_main
from hermes.code_graph import CodeGraphImporter


def _write_graph(root: Path, nodes: list[dict], edges: list[dict]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "graph.json").write_text(
        json.dumps({"nodes": nodes, "edges": edges}), encoding="utf-8"
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_import_writes_one_note_per_node(tmp_path: Path) -> None:
    gn = tmp_path / "gn"
    vault = tmp_path / "vault"
    _write_graph(
        gn,
        [
            {"id": "a", "kind": "function", "name": "alpha", "path": "a.py", "language": "python"},
            {"id": "b", "kind": "function", "name": "beta", "path": "b.py", "language": "python"},
            {"id": "c", "kind": "class", "name": "Gamma", "path": "g.rs", "language": "rust"},
        ],
        [
            {"src": "a", "dst": "b", "kind": "calls"},
            {"src": "a", "dst": "c", "kind": "imports"},
        ],
    )
    written = CodeGraphImporter(vault, gn).import_graph()
    assert len(written) == 3
    assert (vault / "06_Code_Graph" / "python" / "a.md").exists()
    assert (vault / "06_Code_Graph" / "python" / "b.md").exists()
    assert (vault / "06_Code_Graph" / "rust" / "c.md").exists()


def test_frontmatter_contains_node_fields(tmp_path: Path) -> None:
    gn = tmp_path / "gn"
    vault = tmp_path / "vault"
    _write_graph(
        gn,
        [
            {
                "id": "mod1",
                "kind": "module",
                "name": "trustlayer.schema",
                "path": "sdks/python/src/trustlayer/schema.py",
                "language": "python",
                "cluster_id": "core-types",
            }
        ],
        [],
    )
    CodeGraphImporter(vault, gn).import_graph()
    note = _read(vault / "06_Code_Graph" / "python" / "mod1.md")
    assert note.startswith("---\n")
    assert "id: mod1" in note
    assert "kind: module" in note
    assert "name: trustlayer.schema" in note
    assert "language: python" in note
    assert "cluster: core-types" in note
    assert "code-graph" in note  # tag


def test_edges_render_as_wikilinks(tmp_path: Path) -> None:
    gn = tmp_path / "gn"
    vault = tmp_path / "vault"
    _write_graph(
        gn,
        [
            {"id": "a", "kind": "function", "name": "alpha", "language": "python"},
            {"id": "b", "kind": "function", "name": "beta", "language": "python"},
            {"id": "c", "kind": "function", "name": "gamma", "language": "python"},
        ],
        [
            {"src": "a", "dst": "b", "kind": "calls"},
            {"src": "c", "dst": "a", "kind": "calls"},
        ],
    )
    CodeGraphImporter(vault, gn).import_graph()
    note_a = _read(vault / "06_Code_Graph" / "python" / "a.md")
    assert "## Calls" in note_a
    assert "[[06_Code_Graph/python/b|beta]]" in note_a
    assert "## Called by" in note_a
    assert "[[06_Code_Graph/python/c|gamma]]" in note_a


def test_unknown_edge_target_is_marked_external(tmp_path: Path) -> None:
    gn = tmp_path / "gn"
    vault = tmp_path / "vault"
    _write_graph(
        gn,
        [{"id": "a", "kind": "function", "name": "alpha", "language": "python"}],
        [{"src": "a", "dst": "external_lib", "kind": "imports"}],
    )
    CodeGraphImporter(vault, gn).import_graph()
    note = _read(vault / "06_Code_Graph" / "python" / "a.md")
    assert "## Imports" in note
    assert "external_lib" in note
    assert "_(external)_" in note


def test_idempotent_re_run_overwrites_without_duplicates(tmp_path: Path) -> None:
    gn = tmp_path / "gn"
    vault = tmp_path / "vault"
    _write_graph(
        gn,
        [{"id": "a", "kind": "function", "name": "alpha", "language": "python"}],
        [],
    )
    importer = CodeGraphImporter(vault, gn)
    first = importer.import_graph()
    second = importer.import_graph()
    assert first == second
    path = vault / "06_Code_Graph" / "python" / "a.md"
    # Only one note exists; running twice didn't fork it.
    assert path.exists()
    assert list((vault / "06_Code_Graph" / "python").glob("*.md")) == [path]


def test_filenames_are_sanitized(tmp_path: Path) -> None:
    gn = tmp_path / "gn"
    vault = tmp_path / "vault"
    _write_graph(
        gn,
        [
            {
                "id": "weird/id:with*chars",
                "kind": "function",
                "name": "weird",
                "language": "python",
            }
        ],
        [],
    )
    written = CodeGraphImporter(vault, gn).import_graph()
    assert len(written) == 1
    # No path-traversal characters survive into the filename.
    name = written[0].name
    for bad in "/:*":
        assert bad not in name


def test_missing_language_falls_back_to_unknown(tmp_path: Path) -> None:
    gn = tmp_path / "gn"
    vault = tmp_path / "vault"
    _write_graph(
        gn,
        [{"id": "x", "kind": "file", "name": "x"}],
        [],
    )
    written = CodeGraphImporter(vault, gn).import_graph()
    assert written == [vault / "06_Code_Graph" / "unknown" / "x.md"]


def test_two_file_format_supported(tmp_path: Path) -> None:
    gn = tmp_path / "gn"
    vault = tmp_path / "vault"
    gn.mkdir()
    (gn / "nodes.json").write_text(
        json.dumps([{"id": "a", "kind": "function", "name": "alpha", "language": "python"}]),
        encoding="utf-8",
    )
    (gn / "edges.json").write_text("[]", encoding="utf-8")
    written = CodeGraphImporter(vault, gn).import_graph()
    assert written == [vault / "06_Code_Graph" / "python" / "a.md"]


def test_missing_graph_raises(tmp_path: Path) -> None:
    gn = tmp_path / "gn"
    gn.mkdir()
    importer = CodeGraphImporter(tmp_path / "vault", gn)
    with pytest.raises(FileNotFoundError):
        importer.import_graph()


def test_cli_import_code_graph_subcommand(tmp_path: Path, capsys) -> None:
    gn = tmp_path / "gn"
    vault = tmp_path / "vault"
    _write_graph(
        gn,
        [{"id": "a", "kind": "function", "name": "alpha", "language": "python"}],
        [],
    )
    exit_code = cli_main(
        [
            "--vault",
            str(vault),
            "import-code-graph",
            "--gitnexus-root",
            str(gn),
        ]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "06_Code_Graph" in captured.out
    assert (vault / "06_Code_Graph" / "python" / "a.md").exists()


def test_cli_import_missing_graph_exit_1(tmp_path: Path, capsys) -> None:
    gn = tmp_path / "gn"
    gn.mkdir()
    exit_code = cli_main(
        [
            "--vault",
            str(tmp_path / "vault"),
            "import-code-graph",
            "--gitnexus-root",
            str(gn),
        ]
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "No code graph found" in captured.err
