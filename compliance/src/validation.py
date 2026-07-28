"""Input validation helpers shared by the compliance command-line tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load a YAML document and require a mapping at its root."""
    with path.open(encoding="utf-8") as source:
        document = yaml.safe_load(source)
    if not isinstance(document, dict):
        raise TypeError(f"{path} must contain a YAML mapping")
    return document


def validate_document(document: dict[str, Any], schema_name: str) -> None:
    """Validate a YAML-derived document against a bundled JSON Schema."""
    schema_path = SCHEMA_DIR / schema_name
    with schema_path.open(encoding="utf-8") as source:
        schema = json.load(source)
    jsonschema.Draft202012Validator(schema).validate(document)
