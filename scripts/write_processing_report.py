#!/usr/bin/env python3
"""Write a Markdown processing report from JSON records."""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path


def render_adjustments(adjustments: object) -> str:
    if not isinstance(adjustments, dict) or not adjustments:
        return ""
    parts = []
    for key in sorted(adjustments):
        value = adjustments[key]
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        parts.append(f"{key}={shlex.quote(str(value))}")
    return ", ".join(parts)


def render_composition(composition: object) -> str:
    if not isinstance(composition, dict) or not composition:
        return ""
    crop = composition.get("crop")
    parts = []
    if isinstance(crop, dict) and crop.get("enabled"):
        unit = crop.get("unit", "pixels")
        if unit == "pixels":
            parts.append(
                "crop enabled x={} y={} w={} h={}".format(
                    crop.get("x", ""),
                    crop.get("y", ""),
                    crop.get("width", ""),
                    crop.get("height", ""),
                )
            )
        else:
            parts.append(f"crop requested unit={unit}")
        if crop.get("reason"):
            parts.append(f"reason={crop.get('reason')}")
    if composition.get("straighten_degrees") is not None:
        parts.append(f"straighten_degrees={composition.get('straighten_degrees')}")
    return ", ".join(parts)


def render_report(records: list[dict[str, object]]) -> str:
    lines = ["# Processing Report", ""]
    for record in records:
        adjustments = render_adjustments(record.get("adjustments"))
        composition = render_composition(record.get("composition"))
        lines.extend(
            [
                f"## {record.get('source', 'unknown')}",
                "",
                f"- 输出：{record.get('output', '')}",
                f"- 风格：{record.get('style_id', '')}",
                f"- 变体：{record.get('variant_id', '')}",
                f"- 引擎：{record.get('engine', '')}",
                f"- Profile：{record.get('profile', '')}",
                f"- 参数：{adjustments}",
                f"- 构图：{composition}",
                f"- 命令：`{record.get('command', '')}`",
                f"- 理由：{record.get('reason', '')}",
                f"- 状态：{record.get('status', '')}",
                f"- 失败原因：{record.get('failure_reason', '')}",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a photo processing report.")
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    records = json.loads(args.records.read_text())
    args.output.write_text(render_report(records), encoding="utf-8")


if __name__ == "__main__":
    main()
