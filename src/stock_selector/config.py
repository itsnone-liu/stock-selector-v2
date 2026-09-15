from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "default.yaml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    with DEFAULT_CONFIG.open("r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}
    if path:
        custom_path = Path(path).expanduser().resolve()
        with custom_path.open("r", encoding="utf-8") as fh:
            config = _deep_merge(config, yaml.safe_load(fh) or {})
    config["_project_root"] = str(PROJECT_ROOT)
    return config


def resolve_project_path(config: dict[str, Any], value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(config["_project_root"]) / path
    return path.resolve()
