"""
Attack Catalog Loader and Schema Validator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml

from benchmark.models import AttackCase


def validate_attack_dict(data: dict[str, Any]) -> AttackCase:
    """Validate a raw dictionary against the AttackCase Pydantic model."""
    return AttackCase.model_validate(data)


def load_attacks(yaml_path: str | Path) -> list[AttackCase]:
    """
    Load and validate attack definitions from a YAML file.

    Raises:
        FileNotFoundError: If the YAML file doesn't exist.
        ValueError: If the YAML content is not a list.
        pydantic.ValidationError: If any entry violates the schema.
    """
    path = Path(yaml_path)
    if not path.is_file():
        raise FileNotFoundError(f"Attack catalog not found at {path}")

    with path.open("r", encoding="utf-8") as f:
        raw_data = yaml.safe_load(f)

    if not isinstance(raw_data, list):
        raise ValueError(f"Expected a YAML list of attack cases, got {type(raw_data).__name__}")

    cases: list[AttackCase] = []
    seen_ids: set[str] = set()

    for item in raw_data:
        case = validate_attack_dict(item)
        if case.id in seen_ids:
            raise ValueError(f"Duplicate attack case ID detected: {case.id}")
        seen_ids.add(case.id)
        cases.append(case)

    return cases

