"""Tunable thresholds for the rule engine."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field, fields
from pathlib import Path


@dataclass
class Thresholds:
    # complexity
    complexity_warning: int = 10
    complexity_critical: int = 20
    max_nesting: int = 4
    # code smells
    god_class_loc: int = 500
    god_class_methods: int = 20
    large_class_loc: int = 300
    large_class_methods: int = 15
    long_method_loc: int = 50
    very_long_method_loc: int = 120
    max_parameters: int = 5
    magic_number_min: int = 1
    # SOLID
    lcom4_warning: int = 2
    ocp_branches: int = 4
    ocp_type_checks: int = 2
    isp_abstract_methods: int = 5
    # duplication
    clone_min_nodes: int = 28
    clone_min_lines: int = 6
    # patterns
    strategy_min_implementations: int = 2
    # suppression
    ignore_rules: list[str] = field(default_factory=list)
    exclude_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def load(cls, path: str | Path) -> "Thresholds":
        """Read thresholds from a .toml or .json file.

        Unknown keys are rejected loudly — a silently ignored typo in a config
        file is worse than no config file at all.
        """
        file = Path(path)
        if not file.is_file():
            raise ValueError(f"Config file not found: {file}")

        if file.suffix == ".toml":
            import tomllib
            data = tomllib.loads(file.read_text(encoding="utf-8"))
        elif file.suffix == ".json":
            data = json.loads(file.read_text(encoding="utf-8"))
        else:
            raise ValueError("The config file must be .toml or .json")

        data = data.get("thresholds", data)
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(
                f"Unknown config key: {', '.join(sorted(unknown))}. "
                f"Valid keys: {', '.join(sorted(known))}"
            )
        return cls(**data)
