#!/usr/bin/env python3
"""Run the local RAW photo processing workflow end to end."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import lumenflow_config
import render_raw
import scan_raws
import write_processing_report


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_style_cards(style_cards_dir: Path) -> dict[str, dict[str, Any]]:
    styles = {}
    for path in sorted(style_cards_dir.glob("*.json")):
        style = read_json(path)
        style_id = style.get("style_id") or path.stem
        styles[str(style_id)] = style
    if not styles:
        raise SystemExit(f"No style cards found in {style_cards_dir}")
    return styles


def choose_style(styles: dict[str, dict[str, Any]], preferred_style_id: str | None) -> dict[str, Any]:
    if preferred_style_id:
        if preferred_style_id not in styles:
            raise SystemExit(f"Style not found: {preferred_style_id}")
        return styles[preferred_style_id]
    if "clean_natural" in styles:
        return styles["clean_natural"]
    return styles[sorted(styles)[0]]


def command_is_responsive(command: list[str], timeout: int = 5) -> bool:
    if shutil.which(command[0]) is None:
        return False
    try:
        subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        return False
    return True


def resolve_engine(engine: str, local_config: dict[str, Any] | None = None) -> str:
    if engine != "auto":
        return engine
    local_config = local_config or {}
    rawtherapee_cli = lumenflow_config.tool_command(local_config, "rawtherapee_cli", "rawtherapee-cli")
    darktable_cli = lumenflow_config.tool_command(local_config, "darktable_cli", "darktable-cli")
    if command_is_responsive([rawtherapee_cli, "-v"]):
        return "rawtherapee"
    if command_is_responsive([darktable_cli, "--help"]):
        return "darktable"
    if shutil.which(rawtherapee_cli):
        return "rawtherapee"
    if shutil.which(darktable_cli):
        return "darktable"
    raise SystemExit("No RAW CLI found. Install RawTherapee or darktable.")


def resolve_rawtherapee_profiles(style: dict[str, Any]) -> list[Path]:
    profiles = []
    for raw_profile in style.get("raw_profiles", []):
        profile = Path(raw_profile)
        if profile.exists():
            profiles.append(profile)
    return profiles


def darktable_xmp_for(raw_item: dict[str, Any]) -> Path | None:
    sidecars = raw_item.get("sidecars") or {}
    xmp = sidecars.get("darktable_xmp")
    if xmp:
        path = Path(xmp)
        text = path.read_text(encoding="utf-8", errors="replace")
        if "darktable:history_end" in text or "darktable:operation" in text:
            return path
        return None
    candidate = Path(raw_item["path"]).with_name(Path(raw_item["path"]).name + ".xmp")
    if not candidate.exists():
        return None
    text = candidate.read_text(encoding="utf-8", errors="replace")
    if "darktable:history_end" in text or "darktable:operation" in text:
        return candidate
    return None


def output_name(raw_path: Path, style_id: str) -> str:
    return f"{raw_path.stem}_{style_id}.jpg"


def build_command(
    *,
    engine: str,
    raw_item: dict[str, Any],
    output: Path,
    style: dict[str, Any],
    local_config: dict[str, Any] | None = None,
) -> tuple[list[str], str]:
    local_config = local_config or {}
    raw_path = Path(raw_item["path"])
    style_id = str(style.get("style_id", "style"))
    if engine == "rawtherapee":
        profiles = resolve_rawtherapee_profiles(style)
        command = render_raw.build_rawtherapee_command(
            raw_path,
            output,
            profiles,
            executable=lumenflow_config.tool_command(
                local_config,
                "rawtherapee_cli",
                "rawtherapee-cli",
            ),
        )
        return command, ", ".join(str(profile) for profile in profiles)

    xmp = darktable_xmp_for(raw_item)
    style_name = style.get("darktable_style")
    command = render_raw.build_darktable_command(
        raw_path,
        output,
        xmp=xmp,
        style_name=style_name,
        configdir=output.parent / ".darktable-config",
        cachedir=output.parent / ".darktable-cache",
        executable=lumenflow_config.tool_command(local_config, "darktable_cli", "darktable-cli"),
    )
    profile = str(xmp) if xmp else ""
    if style_name:
        profile = f"{profile} style={style_name}".strip()
    elif not profile:
        profile = "darktable default pipeline; style card has no darktable_style"
    return command, profile


def run(
    *,
    source_dir: Path,
    output_dir: Path,
    style_cards_dir: Path,
    engine: str,
    selected_only: bool,
    min_rating: int | None,
    style_id: str | None,
    dry_run: bool,
    limit: int | None,
    render_timeout: int,
    local_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    local_config = local_config or {}
    styles = load_style_cards(style_cards_dir)
    style = choose_style(styles, style_id)
    resolved_engine = resolve_engine(engine, local_config)
    style_id_value = str(style.get("style_id", style_id or "style"))

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
        output = output_dir / output_name(raw_path, style_id_value)
        command, profile = build_command(
            engine=resolved_engine,
            raw_item=raw_item,
            output=output,
            style=style,
            local_config=local_config,
        )
        record = {
            "source": str(raw_path),
            "output": str(output),
            "style_id": style_id_value,
            "engine": resolved_engine,
            "profile": profile,
            "command": shlex.join(command),
            "reason": f"Selected by {raw_item.get('selection_reason', 'workflow')}; style chosen by request/default.",
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

    write_json(output_dir / "processing_records.json", records)
    report = write_processing_report.render_report(records)
    (output_dir / "processing_report.md").write_text(report, encoding="utf-8")

    summary = {
        "source_dir": str(source_dir),
        "output_dir": str(output_dir),
        "engine": resolved_engine,
        "style_id": style_id_value,
        "total_raws": len(all_raws),
        "processed": len(records),
        "succeeded": sum(1 for record in records if record["status"] in {"success", "dry_run"}),
        "failed": sum(1 for record in records if record["status"] == "failed"),
        "skipped": max(len(all_raws) - len(records), 0),
        "dry_run": dry_run,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Develop selected RAW photos into an output directory.")
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--style-cards-dir", type=Path, default=Path("knowledge/style_cards"))
    parser.add_argument("--engine", choices=["auto", "rawtherapee", "darktable"], default="auto")
    parser.add_argument("--all", action="store_true", help="Process all RAW files instead of selected files only.")
    parser.add_argument("--min-rating", type=int, default=1)
    parser.add_argument("--style-id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--render-timeout", type=int, default=300)
    parser.add_argument("--local-config", type=Path, default=lumenflow_config.DEFAULT_LOCAL_CONFIG_PATH)
    args = parser.parse_args()
    local_config = lumenflow_config.read_local_config(args.local_config)
    try:
        output_dir = lumenflow_config.resolve_photo_output_dir(
            local_config,
            args.source_dir,
            explicit_output_dir=args.output_dir,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error

    run(
        source_dir=args.source_dir,
        output_dir=output_dir,
        style_cards_dir=args.style_cards_dir,
        engine=args.engine,
        selected_only=not args.all,
        min_rating=args.min_rating,
        style_id=args.style_id,
        dry_run=args.dry_run,
        limit=args.limit,
        render_timeout=args.render_timeout,
        local_config=local_config,
    )


if __name__ == "__main__":
    main()
