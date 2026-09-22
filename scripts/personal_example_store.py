#!/usr/bin/env python3
"""Compatibility CLI for :mod:`lumenflow.memory.personal_examples`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from _package_compat import ensure_package_importable


ensure_package_importable()

from lumenflow import config as lumenflow_config  # noqa: E402
from lumenflow.memory.personal_examples import (  # noqa: E402,F401
    MAX_EXAMPLE_BYTES,
    PERSONAL_EXAMPLE_VERSION,
    ExampleStoreError,
    PersonalExampleStore,
    build_personal_example,
    example_id_for,
    validate_personal_example,
)


def _read_json(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError(f"JSON file is too large: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage accepted personal photo edit examples."
    )
    parser.add_argument("--store", type=Path)
    parser.add_argument(
        "--local-config",
        type=Path,
        default=lumenflow_config.DEFAULT_LOCAL_CONFIG_PATH,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    add = subparsers.add_parser("add")
    add.add_argument("session", type=Path)
    add.add_argument("plan", type=Path)
    add.add_argument("receipt", type=Path)
    add.add_argument("--tag", action="append", default=[])
    search = subparsers.add_parser("search")
    search.add_argument("--purpose", default="")
    search.add_argument("--tag", action="append", default=[])
    search.add_argument("--style-id")
    search.add_argument("--limit", type=int, default=5)
    listing = subparsers.add_parser("list")
    listing.add_argument("--limit", type=int, default=20)
    remove = subparsers.add_parser("remove")
    remove.add_argument("example_id")
    args = parser.parse_args()

    config = lumenflow_config.read_local_config(args.local_config)
    store_path = args.store or lumenflow_config.personal_example_store_path(
        config, repo_root=Path(__file__).parents[1]
    )
    with PersonalExampleStore(store_path) as store:
        if args.command == "add":
            result: Any = store.add(
                build_personal_example(
                    _read_json(args.session),
                    _read_json(args.plan),
                    _read_json(args.receipt),
                    tags=args.tag,
                )
            )
        elif args.command == "search":
            result = store.search(
                purpose=args.purpose,
                tags=args.tag,
                style_id=args.style_id,
                limit=args.limit,
            )
        elif args.command == "list":
            result = store.list_examples(limit=args.limit)
        else:
            result = {
                "removed": store.remove(args.example_id),
                "example_id": args.example_id,
            }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
