#!/usr/bin/env python3
"""Render agent-authored adjustment plans through a configured photo engine."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

import lumenflow_config
import render_lightroom
import render_raw
import write_processing_report

SCHEMA_VERSION = "lumenflow.adjustment_plan.v1"
COMPOSITION_DECISIONS = {"preserve_existing_crop", "no_crop", "crop", "manual_recommendation"}
MASK_DECISIONS = {"none", "use_masks", "manual_recommendation"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_plan(path: Path) -> dict[str, Any]:
    plan = read_json(path)
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit(f"Unsupported adjustment plan schema_version: {plan.get('schema_version')}")
    if not plan.get("source"):
        raise SystemExit("Adjustment plan must include source")
    variants = plan.get("variants")
    if not isinstance(variants, list) or not variants:
        raise SystemExit("Adjustment plan must include at least one variant")
    for index, variant in enumerate(variants):
        if not isinstance(variant, dict):
            raise SystemExit(f"Variant {index} must be an object")
        if not variant.get("variant_id"):
            raise SystemExit(f"Variant {index} must include variant_id")
        if not isinstance(variant.get("adjustments"), dict):
            raise SystemExit(f"Variant {variant.get('variant_id')} must include adjustments")
        validate_variant_decisions(variant)
    return plan


def validate_variant_decisions(variant: dict[str, Any]) -> None:
    variant_id = str(variant.get("variant_id", "<unknown>"))

    composition = variant.get("composition")
    if not isinstance(composition, dict):
        raise SystemExit(f"Variant {variant_id} must include composition decision")
    composition_decision = composition.get("decision")
    if composition_decision not in COMPOSITION_DECISIONS:
        allowed = ", ".join(sorted(COMPOSITION_DECISIONS))
        raise SystemExit(f"Variant {variant_id} composition.decision must be one of: {allowed}")
    if not str(composition.get("reason", "")).strip():
        raise SystemExit(f"Variant {variant_id} composition.reason must explain the per-photo framing decision")

    crop = composition.get("crop")
    crop_enabled = isinstance(crop, dict) and bool(crop.get("enabled"))
    if composition_decision == "crop":
        if not crop_enabled:
            raise SystemExit(f"Variant {variant_id} composition.decision=crop requires crop.enabled=true")
        if not str(crop.get("reason") or composition.get("reason") or "").strip():
            raise SystemExit(f"Variant {variant_id} crop requires a reason")
    elif crop_enabled:
        raise SystemExit(f"Variant {variant_id} has crop.enabled=true but composition.decision={composition_decision}")

    mask_decision = variant.get("mask_decision")
    if not isinstance(mask_decision, dict):
        raise SystemExit(f"Variant {variant_id} must include mask_decision")
    decision = mask_decision.get("decision")
    if decision not in MASK_DECISIONS:
        allowed = ", ".join(sorted(MASK_DECISIONS))
        raise SystemExit(f"Variant {variant_id} mask_decision.decision must be one of: {allowed}")
    if not str(mask_decision.get("reason", "")).strip():
        raise SystemExit(f"Variant {variant_id} mask_decision.reason must explain the per-photo local-edit decision")

    masks = variant.get("masks") or []
    if decision == "use_masks":
        if not isinstance(masks, list) or not masks:
            raise SystemExit(f"Variant {variant_id} mask_decision=use_masks requires at least one executable mask")
        for index, mask in enumerate(masks):
            if not isinstance(mask, dict):
                raise SystemExit(f"Variant {variant_id} mask {index} must be an object")
            if not str(mask.get("rationale", "")).strip():
                raise SystemExit(f"Variant {variant_id} mask {index} must include rationale")
    elif masks:
        raise SystemExit(f"Variant {variant_id} includes executable masks but mask_decision.decision={decision}")


def pp3_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def crop_profile_lines(composition: dict[str, Any] | None) -> list[str]:
    if not isinstance(composition, dict):
        return []
    crop = composition.get("crop")
    if not isinstance(crop, dict) or not crop.get("enabled"):
        return []
    if crop.get("unit", "pixels") != "pixels":
        return []

    required_keys = ["x", "y", "width", "height"]
    if any(key not in crop for key in required_keys):
        return []

    lines = [
        "",
        "[Crop]",
        "Enabled=true",
        f"X={pp3_value(crop['x'])}",
        f"Y={pp3_value(crop['y'])}",
        f"W={pp3_value(crop['width'])}",
        f"H={pp3_value(crop['height'])}",
    ]
    if "fixed_ratio" in crop:
        lines.append(f"FixedRatio={pp3_value(crop['fixed_ratio'])}")
    if crop.get("ratio"):
        lines.append(f"Ratio={crop['ratio']}")
    return lines


def rawtherapee_profile_text(
    adjustments: dict[str, Any],
    composition: dict[str, Any] | None = None,
) -> str:
    exposure_keys = {
        "exposure_compensation": "Compensation",
        "saturation": "Saturation",
        "black": "Black",
        "brightness": "Brightness",
        "contrast": "Contrast",
        "highlight_compression": "HighlightCompr",
        "shadow_compression": "ShadowCompr",
    }
    exposure_lines = ["[Exposure]", "Enabled=true"]
    for source_key, pp3_key in exposure_keys.items():
        if source_key in adjustments and adjustments[source_key] is not None:
            exposure_lines.append(f"{pp3_key}={pp3_value(adjustments[source_key])}")

    sections = [
        "[Version]",
        "AppVersion=5.10",
        "Version=349",
        "",
        *exposure_lines,
    ]

    white_balance_keys = {
        "temperature": "Temperature",
        "green": "Green",
    }
    white_balance_lines = ["", "[White Balance]", "Enabled=true", "Setting=Custom"]
    has_white_balance = False
    for source_key, pp3_key in white_balance_keys.items():
        if source_key in adjustments and adjustments[source_key] is not None:
            white_balance_lines.append(f"{pp3_key}={pp3_value(adjustments[source_key])}")
            has_white_balance = True
    if has_white_balance:
        sections.extend(white_balance_lines)

    sections.extend(crop_profile_lines(composition))

    notes = adjustments.get("notes")
    if notes:
        sections.extend(["", "[Lumenflow]", f"Notes={str(notes).replace(chr(10), ' ')}"])

    return "\n".join(sections) + "\n"


def output_name(raw_path: Path, variant_id: str) -> str:
    return f"{raw_path.stem}_{variant_id}.jpg"


def profile_name(raw_path: Path, variant_id: str) -> str:
    return f"{raw_path.stem}_{variant_id}.pp3"


def run(
    *,
    plan_path: Path,
    output_dir: Path,
    dry_run: bool,
    render_timeout: int,
    local_config: dict[str, Any] | None = None,
    engine: str = "rawtherapee",
) -> dict[str, Any]:
    local_config = local_config or {}
    plan = read_plan(plan_path)
    if engine == "lightroom":
        summary = render_lightroom.render_plan(
            plan=plan,
            output_dir=output_dir,
            dry_run=dry_run,
            render_timeout=render_timeout,
            local_config=local_config,
        )
        summary["plan"] = str(plan_path)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    raw_path = Path(plan["source"])
    output_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir = output_dir / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    records = []
    for variant in plan["variants"]:
        variant_id = str(variant["variant_id"])
        style_id = str(variant.get("style_id", "agent_selected"))
        profile_path = profiles_dir / profile_name(raw_path, variant_id)
        output_path = output_dir / output_name(raw_path, variant_id)
        composition = variant.get("composition", {})
        profile_path.write_text(
            rawtherapee_profile_text(variant["adjustments"], composition),
            encoding="utf-8",
        )
        command = render_raw.build_rawtherapee_command(
            raw_path,
            output_path,
            [profile_path],
            executable=lumenflow_config.tool_command(
                local_config,
                "rawtherapee_cli",
                "rawtherapee-cli",
            ),
        )
        record = {
            "source": str(raw_path),
            "output": str(output_path),
            "style_id": style_id,
            "variant_id": variant_id,
            "engine": "rawtherapee",
            "profile": str(profile_path),
            "command": shlex.join(command),
            "reason": variant.get("rationale", ""),
            "adjustments": variant["adjustments"],
            "composition": composition,
            "mask_decision": variant.get("mask_decision", {}),
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
        "plan": str(plan_path),
        "source": str(raw_path),
        "output_dir": str(output_dir),
        "engine": "rawtherapee",
        "rendered": len(records),
        "succeeded": sum(1 for record in records if record["status"] in {"success", "dry_run"}),
        "failed": sum(1 for record in records if record["status"] == "failed"),
        "dry_run": dry_run,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a Lumenflow agent adjustment plan.")
    parser.add_argument("plan_path", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--engine", choices=["rawtherapee", "lightroom"], default="rawtherapee")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--render-timeout", type=int, default=300)
    parser.add_argument("--local-config", type=Path, default=lumenflow_config.DEFAULT_LOCAL_CONFIG_PATH)
    args = parser.parse_args()
    local_config = lumenflow_config.read_local_config(args.local_config)
    plan = read_plan(args.plan_path)
    try:
        output_dir = lumenflow_config.resolve_photo_output_dir(
            local_config,
            Path(plan["source"]),
            explicit_output_dir=args.output_dir,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from error

    run(
        plan_path=args.plan_path,
        output_dir=output_dir,
        dry_run=args.dry_run,
        render_timeout=args.render_timeout,
        local_config=local_config,
        engine=args.engine,
    )


if __name__ == "__main__":
    main()
