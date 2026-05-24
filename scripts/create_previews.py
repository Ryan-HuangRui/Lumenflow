#!/usr/bin/env python3
"""Create JPEG previews for agent-led RAW analysis."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

import lumenflow_config
import render_raw
import scan_raws


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def preview_name(raw_path: Path) -> str:
    return f"{raw_path.stem}_preview.jpg"


def build_preview_command(
    raw_path: Path,
    preview_path: Path,
    base_profile: Path | None,
    local_config: dict[str, Any] | None = None,
) -> list[str]:
    profiles = [base_profile] if base_profile is not None and base_profile.exists() else []
    return render_raw.build_rawtherapee_command(
        raw_path,
        preview_path,
        profiles,
        executable=lumenflow_config.tool_command(
            local_config or {},
            "rawtherapee_cli",
            "rawtherapee-cli",
        ),
    )


def run(
    *,
    source_dir: Path,
    output_dir: Path,
    selected_only: bool,
    min_rating: int | None,
    limit: int | None,
    dry_run: bool,
    render_timeout: int,
    base_profile: Path | None = Path("knowledge/raw_profiles/base.pp3"),
    local_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    local_config = local_config or {}
    all_raws = scan_raws.scan_raws(source_dir, selected_only=False, min_rating=min_rating)
    selected_raws = [item for item in all_raws if item.get("selected")]
    if not selected_only:
        selected_raws = all_raws
    if limit is not None:
        selected_raws = selected_raws[:limit]

    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for raw_item in selected_raws:
        raw_path = Path(raw_item["path"])
        preview_path = output_dir / preview_name(raw_path)
        command = build_preview_command(raw_path, preview_path, base_profile, local_config)
        record = {
            "source": str(raw_path),
            "preview": str(preview_path),
            "command": shlex.join(command),
            "selection_reason": raw_item.get("selection_reason", ""),
            "status": "dry_run" if dry_run else "pending",
            "failure_reason": "",
        }
        try:
            render_raw.run_command(command, dry_run=dry_run, timeout=render_timeout)
            if not dry_run:
                record["status"] = "success"
        except (subprocess.SubprocessError, OSError) as exc:
            record["status"] = "failed"
            record["failure_reason"] = str(exc)
        records.append(record)

    write_json(output_dir / "preview_manifest.json", records)
    summary = {
        "source_dir": str(source_dir),
        "output_dir": str(output_dir),
        "total_raws": len(all_raws),
        "previewed": len(records),
        "succeeded": sum(1 for record in records if record["status"] in {"success", "dry_run"}),
        "failed": sum(1 for record in records if record["status"] == "failed"),
        "skipped": max(len(all_raws) - len(records), 0),
        "dry_run": dry_run,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Create JPEG previews for selected RAW photos.")
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--all", action="store_true", help="Preview all RAW files instead of selected files only.")
    parser.add_argument("--min-rating", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--render-timeout", type=int, default=300)
    parser.add_argument("--base-profile", type=Path, default=Path("knowledge/raw_profiles/base.pp3"))
    parser.add_argument("--local-config", type=Path, default=lumenflow_config.DEFAULT_LOCAL_CONFIG_PATH)
    args = parser.parse_args()
    local_config = lumenflow_config.read_local_config(args.local_config)
    try:
        output_dir = lumenflow_config.resolve_photo_output_dir(
            local_config,
            args.source_dir,
            explicit_output_dir=args.output_dir,
            subdir="previews",
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error

    run(
        source_dir=args.source_dir,
        output_dir=output_dir,
        selected_only=not args.all,
        min_rating=args.min_rating,
        limit=args.limit,
        dry_run=args.dry_run,
        render_timeout=args.render_timeout,
        base_profile=args.base_profile,
        local_config=local_config,
    )


if __name__ == "__main__":
    main()
