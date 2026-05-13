from __future__ import annotations

from pathlib import Path

from hermes.cli import main


def test_cli_ingest_then_reflect(tmp_path: Path, sample_session, capsys):
    feed = tmp_path / "feed.jsonl"
    feed.write_text(
        "\n".join(e.model_dump_json() for e in sample_session) + "\n",
        encoding="utf-8",
    )
    vault = tmp_path / "vault"
    rc = main(["--vault", str(vault), "ingest", str(feed), "--reflect"])
    assert rc == 0
    out = capsys.readouterr().out
    # First printed path is a session note, last is a reflection note.
    lines = [line for line in out.splitlines() if line.strip()]
    session_note = Path(lines[0])
    reflection_note = Path(lines[-1])
    assert session_note.exists() and reflection_note.exists()
    assert "03_Memory_Traces" in str(session_note)
    assert "05_Reflections" in str(reflection_note)


def test_cli_reflect_alone_returns_1_when_empty(tmp_path: Path, capsys):
    feed = tmp_path / "empty.jsonl"
    feed.write_text("", encoding="utf-8")
    rc = main(["--vault", str(tmp_path / "vault"), "reflect", str(feed)])
    assert rc == 1
