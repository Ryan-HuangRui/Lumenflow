#!/usr/bin/env python3
"""Scan a directory for RAW photo files and print a JSON manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RAW_EXTENSIONS = {
    ".3fr",
    ".arw",
    ".cr2",
    ".cr3",
    ".dng",
    ".nef",
    ".orf",
    ".raf",
    ".raw",
    ".rw2",
}


def scan_raws(source_dir: Path) -> list[dict[str, str]]:
    return [
        {"path": str(path), "name": path.name, "extension": path.suffix.lower()}
        for path in sorted(source_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in RAW_EXTENSIONS
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan a directory for RAW photo files.")
    parser.add_argument("source_dir", type=Path)
    args = parser.parse_args()

    print(json.dumps({"raws": scan_raws(args.source_dir)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
