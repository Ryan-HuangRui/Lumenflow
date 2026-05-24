"""Local, gitignored runtime configuration helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_LOCAL_CONFIG_PATH = Path("config/lumenflow.local.json")


def read_local_config(path: Path | None = DEFAULT_LOCAL_CONFIG_PATH) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Local config must be a JSON object: {path}")
    return payload


def nested_value(config: dict[str, Any], *keys: str) -> Any:
    value: Any = config
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def expand_path(value: str | Path | None) -> Path | None:
    if value is None or value == "":
        return None
    return Path(os.path.expandvars(os.path.expanduser(str(value))))


def config_path(config: dict[str, Any], *keys: str) -> Path | None:
    value = nested_value(config, *keys)
    return expand_path(value) if isinstance(value, (str, Path)) else None


def config_str(config: dict[str, Any], *keys: str) -> str | None:
    value = nested_value(config, *keys)
    return str(value) if value not in (None, "") else None


def config_bool(config: dict[str, Any], *keys: str, default: bool = False) -> bool:
    value = nested_value(config, *keys)
    return default if value is None else bool(value)


def tool_command(config: dict[str, Any], key: str, default: str) -> str:
    return config_str(config, "tools", key) or default


def photo_collection_name(source_path: Path) -> str:
    source = Path(source_path)
    if source.suffix:
        return source.parent.name
    return source.name


def photo_output_root(config: dict[str, Any]) -> Path | None:
    return config_path(config, "photos", "output_root")


def photo_output_dir(
    config: dict[str, Any],
    source_path: Path,
    subdir: str | None = None,
) -> Path | None:
    root = photo_output_root(config)
    if root is None:
        return None
    output_dir = root / photo_collection_name(source_path)
    return output_dir / subdir if subdir else output_dir


def resolve_photo_output_dir(
    config: dict[str, Any],
    source_path: Path,
    explicit_output_dir: Path | None = None,
    subdir: str | None = None,
) -> Path:
    if explicit_output_dir is not None:
        return explicit_output_dir
    output_dir = photo_output_dir(config, source_path, subdir=subdir)
    if output_dir is None:
        raise ValueError("Missing photos.output_root in local config. Pass --output-dir or configure it.")
    return output_dir
