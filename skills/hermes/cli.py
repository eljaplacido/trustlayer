"""Command-line entry point for Hermes.

Examples:

    python -m hermes.cli --vault obsidian_vault ingest traces.jsonl --reflect
    python -m hermes.cli --vault obsidian_vault reflect traces.jsonl
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .code_graph import CodeGraphImporter
from .hermes_agent import HermesAgent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hermes — TrustLayer memory subagent."
    )
    parser.add_argument(
        "--vault",
        required=True,
        help="Path to the Obsidian vault root (e.g. obsidian_vault/).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", help="Ingest a JSONL feed of trace events.")
    p_ingest.add_argument(
        "jsonl", help="Path to a JSONL file of AgentTraceEvent records."
    )
    p_ingest.add_argument(
        "--reflect",
        action="store_true",
        help="Also produce a reflection note covering the ingested sessions.",
    )

    p_reflect = sub.add_parser(
        "reflect",
        help="Load a JSONL feed and emit a reflection note.",
    )
    p_reflect.add_argument("jsonl", help="JSONL feed to load before reflecting.")

    p_codegraph = sub.add_parser(
        "import-code-graph",
        help="Mirror a GitNexus-style code graph into the vault as Obsidian notes.",
    )
    p_codegraph.add_argument(
        "--gitnexus-root",
        default=".gitnexus",
        help="Path to the directory containing graph.json (or nodes.json + edges.json).",
    )

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.cmd == "ingest":
        agent = HermesAgent(Path(args.vault))
        for note in agent.ingest_jsonl(args.jsonl):
            print(note)
        if args.reflect:
            reflection = agent.reflect()
            if reflection:
                print(reflection)
        return 0
    if args.cmd == "reflect":
        agent = HermesAgent(Path(args.vault))
        agent.ingest_jsonl(args.jsonl)
        reflection = agent.reflect()
        if reflection:
            print(reflection)
            return 0
        print("No sessions to reflect on.", file=sys.stderr)
        return 1
    if args.cmd == "import-code-graph":
        importer = CodeGraphImporter(Path(args.vault), Path(args.gitnexus_root))
        try:
            written = importer.import_graph()
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        for note in written:
            print(note)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
