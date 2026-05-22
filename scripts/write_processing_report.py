#!/usr/bin/env python3
"""Write a Markdown processing report from JSON records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def render_report(records: list[dict[str, str]]) -> str:
    lines = ["# Processing Report", ""]
    for record in records:
        lines.extend(
            [
                f"## {record.get('source', 'unknown')}",
                "",
                f"- 输出：{record.get('output', '')}",
                f"- 风格：{record.get('style_id', '')}",
                f"- 引擎：{record.get('engine', '')}",
                f"- Profile：{record.get('profile', '')}",
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
