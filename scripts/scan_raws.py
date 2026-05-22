#!/usr/bin/env python3
"""Scan a directory for RAW photo files and print a JSON manifest.

The scanner intentionally understands the sidecar formats that matter for the
first Lumenflow workflow:

- darktable writes `<raw filename>.xmp` sidecars with rating/color-label data.
- RawTherapee writes `<raw filename>.pp3` sidecars and stores its rank there.
"""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

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

COLOR_LABELS = {
    "0": "red",
    "1": "yellow",
    "2": "green",
    "3": "blue",
    "4": "purple",
}


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def normalize_color_labels(value: str | None) -> list[str]:
    if not value:
        return []
    labels = []
    for item in re.split(r"[,; ]+", value.strip()):
        if not item:
            continue
        labels.append(COLOR_LABELS.get(item, item))
    return labels


def parse_darktable_xmp(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    rating: int | None = None
    color_labels: list[str] = []

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        root = None

    if root is not None:
        for element in root.iter():
            for key, value in element.attrib.items():
                local_name = key.rsplit("}", 1)[-1].lower()
                if local_name == "rating":
                    rating = parse_int(value)
                elif local_name == "colorlabels":
                    color_labels = normalize_color_labels(value)

    if rating is None:
        match = re.search(r"(?:xmp:)?Rating=[\"'](-?\d+)[\"']", text)
        if match:
            rating = parse_int(match.group(1))
    if not color_labels:
        match = re.search(r"(?:darktable:)?colorlabels=[\"']([^\"']+)[\"']", text)
        if match:
            color_labels = normalize_color_labels(match.group(1))

    return {
        "rating": rating,
        "rejected": rating is not None and rating < 0,
        "color_labels": color_labels,
    }


def parse_rawtherapee_pp3(path: Path) -> dict[str, Any]:
    rating: int | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip().lower() == "rank":
            rating = parse_int(value)
            break
    return {"rating": rating, "rejected": False, "color_labels": []}


def find_sidecars(raw_path: Path) -> dict[str, Path]:
    sidecars = {}
    darktable_xmp = raw_path.with_name(raw_path.name + ".xmp")
    rawtherapee_pp3 = raw_path.with_name(raw_path.name + ".pp3")
    if darktable_xmp.exists():
        sidecars["darktable_xmp"] = darktable_xmp
    if rawtherapee_pp3.exists():
        sidecars["rawtherapee_pp3"] = rawtherapee_pp3
    return sidecars


def read_selection_metadata(raw_path: Path) -> dict[str, Any]:
    sidecars = find_sidecars(raw_path)
    metadata: dict[str, Any] = {
        "rating": None,
        "rejected": False,
        "color_labels": [],
        "sidecars": {key: str(value) for key, value in sidecars.items()},
        "selection_source": "",
    }

    if "darktable_xmp" in sidecars:
        parsed = parse_darktable_xmp(sidecars["darktable_xmp"])
        metadata.update(parsed)
        metadata["selection_source"] = "darktable_xmp"
    elif "rawtherapee_pp3" in sidecars:
        parsed = parse_rawtherapee_pp3(sidecars["rawtherapee_pp3"])
        metadata.update(parsed)
        metadata["selection_source"] = "rawtherapee_pp3"

    return metadata


def is_selected(metadata: dict[str, Any], min_rating: int | None) -> tuple[bool, str]:
    if metadata.get("rejected"):
        return False, "rejected"

    rating = metadata.get("rating")
    color_labels = metadata.get("color_labels") or []
    effective_min_rating = 1 if min_rating is None else min_rating
    if isinstance(rating, int) and rating >= effective_min_rating:
        return True, f"rating>={effective_min_rating}"
    if color_labels:
        return True, "color_label"
    return False, "unselected"


def scan_raws(
    source_dir: Path,
    *,
    selected_only: bool = False,
    min_rating: int | None = None,
) -> list[dict[str, Any]]:
    raws = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in RAW_EXTENSIONS:
            continue
        metadata = read_selection_metadata(path)
        selected, reason = is_selected(metadata, min_rating)
        item: dict[str, Any] = {
            "path": str(path),
            "name": path.name,
            "extension": path.suffix.lower(),
            "selected": selected,
            "selection_reason": reason,
        }
        item.update(metadata)
        if selected_only and not selected:
            continue
        raws.append(item)
    return raws


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan a directory for RAW photo files.")
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--selected-only", action="store_true")
    parser.add_argument("--min-rating", type=int)
    args = parser.parse_args()

    print(
        json.dumps(
            {
                "raws": scan_raws(
                    args.source_dir,
                    selected_only=args.selected_only,
                    min_rating=args.min_rating,
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
