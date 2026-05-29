#!/usr/bin/env python3
"""Render Lumenflow adjustment plans through Lightroom Classic via lightroom-cli."""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

import lumenflow_config
import write_processing_report

DIRECT_ADJUSTMENT_MAP = {
    "exposure_compensation": "Exposure",
    "saturation": "Saturation",
    "brightness": "Brightness",
    "contrast": "Contrast",
    "temperature": "Temperature",
    "tint": "Tint",
    "highlights": "Highlights",
    "shadows": "Shadows",
    "whites": "Whites",
    "blacks": "Blacks",
    "black": "Blacks",
    "clarity": "Clarity",
    "vibrance": "Vibrance",
    "dehaze": "Dehaze",
    "texture": "Texture",
}

RANGED_SETTINGS = {
    "Saturation",
    "Brightness",
    "Contrast",
    "Tint",
    "Highlights",
    "Shadows",
    "Whites",
    "Blacks",
    "Clarity",
    "Vibrance",
    "Dehaze",
    "Texture",
}

AI_MASK_TYPES = {"subject", "sky", "background", "objects", "people", "landscape"}
BASIC_LIGHTROOM_SETTING_KEYS = set(DIRECT_ADJUSTMENT_MAP.values()) | RANGED_SETTINGS | {"Exposure", "Temperature"}
LIGHTROOM_SETTING_KEYS = set(BASIC_LIGHTROOM_SETTING_KEYS)

HSL_COLORS = {
    "red": "Red",
    "orange": "Orange",
    "yellow": "Yellow",
    "green": "Green",
    "aqua": "Aqua",
    "blue": "Blue",
    "purple": "Purple",
    "magenta": "Magenta",
}

HSL_SETTING_PREFIXES = {
    "hue": "HueAdjustment",
    "saturation": "SaturationAdjustment",
    "luminance": "LuminanceAdjustment",
}

PARAMETRIC_CURVE_MAP = {
    "darks": "ParametricDarks",
    "lights": "ParametricLights",
    "shadows": "ParametricShadows",
    "highlights": "ParametricHighlights",
    "shadow_split": "ParametricShadowSplit",
    "midtone_split": "ParametricMidtoneSplit",
    "highlight_split": "ParametricHighlightSplit",
}

POINT_CURVE_MAP = {
    "point": "ToneCurvePV2012",
    "rgb": "ToneCurvePV2012",
    "red": "ToneCurvePV2012Red",
    "green": "ToneCurvePV2012Green",
    "blue": "ToneCurvePV2012Blue",
}

COLOR_GRADING_CHANNELS = {
    "shadows": {
        "hue": "SplitToningShadowHue",
        "saturation": "SplitToningShadowSaturation",
        "luminance": "ColorGradeShadowLum",
    },
    "highlights": {
        "hue": "SplitToningHighlightHue",
        "saturation": "SplitToningHighlightSaturation",
        "luminance": "ColorGradeHighlightLum",
    },
    "midtones": {
        "hue": "ColorGradeMidtoneHue",
        "saturation": "ColorGradeMidtoneSat",
        "luminance": "ColorGradeMidtoneLum",
    },
    "global": {
        "hue": "ColorGradeGlobalHue",
        "saturation": "ColorGradeGlobalSat",
        "luminance": "ColorGradeGlobalLum",
    },
}

COLOR_GRADING_GLOBAL_MAP = {
    "blending": "ColorGradeBlending",
    "balance": "SplitToningBalance",
}

CALIBRATION_CHANNELS = {
    "red": "Red",
    "green": "Green",
    "blue": "Blue",
}

CALIBRATION_GLOBAL_MAP = {
    "shadow_tint": "ShadowTint",
}

ADVANCED_LIGHTROOM_SETTINGS = (
    set(PARAMETRIC_CURVE_MAP.values())
    | set(POINT_CURVE_MAP.values())
    | {"CurveRefineSaturation"}
    | {f"{prefix}{color}" for prefix in HSL_SETTING_PREFIXES.values() for color in HSL_COLORS.values()}
    | {setting for channel in COLOR_GRADING_CHANNELS.values() for setting in channel.values()}
    | set(COLOR_GRADING_GLOBAL_MAP.values())
    | set(CALIBRATION_GLOBAL_MAP.values())
    | {f"{channel}{suffix}" for channel in CALIBRATION_CHANNELS.values() for suffix in ("Hue", "Saturation")}
)
LIGHTROOM_SETTING_KEYS |= ADVANCED_LIGHTROOM_SETTINGS

FORMAT_EXTENSIONS = {
    "JPEG": ".jpg",
    "TIFF": ".tif",
    "DNG": ".dng",
    "ORIGINAL": "",
}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalized_number(value: Any) -> int | float:
    number = float(value)
    if number.is_integer():
        return int(number)
    return number


def normalized_ranged_number(value: Any, low: float = -100, high: float = 100) -> int | float:
    return normalized_number(clamp(float(value), low, high))


def require_object(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Lightroom {field} adjustments must be an object")
    return value


def add_hsl_settings(settings: dict[str, Any], hsl: Any, *, field: str) -> None:
    for color_name, channels in require_object(hsl, field=field).items():
        color = HSL_COLORS.get(str(color_name).lower())
        if not color:
            raise ValueError(f"Unsupported Lightroom {field} color: {color_name}")
        if not isinstance(channels, dict):
            raise ValueError(f"Lightroom {field}.{color_name} must be an object")
        for channel_name, value in channels.items():
            prefix = HSL_SETTING_PREFIXES.get(str(channel_name).lower())
            if not prefix:
                raise ValueError(f"Unsupported Lightroom {field} channel: {channel_name}")
            if value is not None:
                settings[f"{prefix}{color}"] = normalized_ranged_number(value)


def curve_points(value: Any) -> list[int | float]:
    if not isinstance(value, list):
        raise ValueError("Lightroom tone curve points must be an array")
    flattened: list[Any] = []
    for item in value:
        if isinstance(item, list):
            if len(item) != 2:
                raise ValueError("Lightroom tone curve point arrays must contain exactly two numbers")
            flattened.extend(item)
        else:
            flattened.append(item)
    if len(flattened) % 2 != 0:
        raise ValueError("Lightroom tone curve points must contain x/y pairs")
    return [normalized_ranged_number(point, 0, 255) for point in flattened]


def add_tone_curve_settings(settings: dict[str, Any], tone_curve: Any) -> None:
    tone_curve = require_object(tone_curve, field="tone_curve")
    parametric = tone_curve.get("parametric")
    if parametric is not None:
        for key, value in require_object(parametric, field="tone_curve.parametric").items():
            setting = PARAMETRIC_CURVE_MAP.get(str(key).lower())
            if not setting:
                raise ValueError(f"Unsupported Lightroom parametric curve key: {key}")
            key_name = str(key).lower()
            low, high = (0, 100) if key_name in {"shadow_split", "midtone_split", "highlight_split"} else (-100, 100)
            if value is not None:
                settings[setting] = normalized_ranged_number(value, low, high)

    for key, setting in POINT_CURVE_MAP.items():
        if key in tone_curve and tone_curve[key] is not None:
            settings[setting] = curve_points(tone_curve[key])
    if tone_curve.get("curve_refine_saturation") is not None:
        settings["CurveRefineSaturation"] = normalized_ranged_number(tone_curve["curve_refine_saturation"])


def add_color_grading_settings(settings: dict[str, Any], color_grading: Any) -> None:
    color_grading = require_object(color_grading, field="color_grading")
    for group_name, channel_map in COLOR_GRADING_CHANNELS.items():
        group = color_grading.get(group_name)
        if group is None:
            continue
        for key, value in require_object(group, field=f"color_grading.{group_name}").items():
            setting = channel_map.get(str(key).lower())
            if not setting:
                raise ValueError(f"Unsupported Lightroom color grading key: {group_name}.{key}")
            if value is None:
                continue
            if str(key).lower() == "hue":
                settings[setting] = normalized_ranged_number(value, 0, 360)
            elif str(key).lower() == "saturation":
                settings[setting] = normalized_ranged_number(value, 0, 100)
            else:
                settings[setting] = normalized_ranged_number(value)

    for key, setting in COLOR_GRADING_GLOBAL_MAP.items():
        if color_grading.get(key) is None:
            continue
        low, high = (0, 100) if key == "blending" else (-100, 100)
        settings[setting] = normalized_ranged_number(color_grading[key], low, high)


def add_calibration_settings(settings: dict[str, Any], calibration: Any) -> None:
    calibration = require_object(calibration, field="calibration")
    for key, setting in CALIBRATION_GLOBAL_MAP.items():
        if calibration.get(key) is not None:
            settings[setting] = normalized_ranged_number(calibration[key])

    for channel_name, prefix in CALIBRATION_CHANNELS.items():
        channel = calibration.get(channel_name)
        if channel is None:
            continue
        for key, value in require_object(channel, field=f"calibration.{channel_name}").items():
            suffix = {"hue": "Hue", "saturation": "Saturation"}.get(str(key).lower())
            if not suffix:
                raise ValueError(f"Unsupported Lightroom calibration key: {channel_name}.{key}")
            if value is not None:
                settings[f"{prefix}{suffix}"] = normalized_ranged_number(value)


def lightroom_settings_from_adjustments(
    adjustments: dict[str, Any],
    *,
    include_advanced: bool = True,
) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    for source_key, lightroom_key in DIRECT_ADJUSTMENT_MAP.items():
        if source_key not in adjustments or adjustments[source_key] is None:
            continue
        value = normalized_number(adjustments[source_key])
        if lightroom_key == "Exposure":
            value = clamp(float(value), -5, 5)
        elif lightroom_key == "Temperature":
            value = clamp(float(value), 2000, 50000)
        elif lightroom_key in RANGED_SETTINGS:
            value = clamp(float(value), -100, 100)
        settings[lightroom_key] = normalized_number(value)

    valid_setting_keys = LIGHTROOM_SETTING_KEYS if include_advanced else BASIC_LIGHTROOM_SETTING_KEYS
    for source_key, value in adjustments.items():
        if source_key not in valid_setting_keys:
            continue
        if source_key in settings or value is None:
            continue
        if source_key in set(POINT_CURVE_MAP.values()):
            settings[source_key] = curve_points(value)
            continue
        if source_key == "Temperature":
            number = clamp(float(normalized_number(value)), 2000, 50000)
        elif source_key == "Exposure":
            number = clamp(float(normalized_number(value)), -5, 5)
        else:
            number = clamp(float(normalized_number(value)), -100, 100)
        settings[source_key] = normalized_number(number)

    if "highlight_compression" in adjustments and "Highlights" not in settings:
        settings["Highlights"] = normalized_number(clamp(-float(adjustments["highlight_compression"]), -100, 100))
    if "shadow_compression" in adjustments and "Shadows" not in settings:
        settings["Shadows"] = normalized_number(clamp(float(adjustments["shadow_compression"]), -100, 100))

    if not include_advanced:
        return settings

    if adjustments.get("hsl") is not None:
        add_hsl_settings(settings, adjustments["hsl"], field="hsl")
    if adjustments.get("color_mixer") is not None:
        add_hsl_settings(settings, adjustments["color_mixer"], field="color_mixer")
    if adjustments.get("tone_curve") is not None:
        add_tone_curve_settings(settings, adjustments["tone_curve"])
    if adjustments.get("color_grading") is not None:
        add_color_grading_settings(settings, adjustments["color_grading"])
    if adjustments.get("calibration") is not None:
        add_calibration_settings(settings, adjustments["calibration"])

    return settings


def output_name(raw_path: Path, variant_id: str, export_format: str = "JPEG") -> str:
    extension = FORMAT_EXTENSIONS.get(export_format.upper(), ".jpg") or raw_path.suffix
    return f"{raw_path.stem}_{variant_id}{extension}"


def lightroom_cli(local_config: dict[str, Any] | None = None) -> str:
    return lumenflow_config.tool_command(local_config or {}, "lightroom_cli", "lr")


def export_options(local_config: dict[str, Any] | None = None) -> dict[str, Any]:
    lightroom_config = (local_config or {}).get("lightroom") or {}
    return {
        "format": str(lightroom_config.get("export_format", "JPEG")).upper(),
        "quality": int(lightroom_config.get("quality", 95)),
        "color_space": lightroom_config.get("color_space", "sRGB"),
        "resize_long_edge": lightroom_config.get("resize_long_edge"),
        "overwrite": bool(lightroom_config.get("overwrite", False)),
    }


def allow_unverified_ai_masks(local_config: dict[str, Any] | None = None) -> bool:
    lightroom_config = (local_config or {}).get("lightroom") or {}
    return bool(lightroom_config.get("allow_unverified_ai_masks", False))


def find_photo_command(raw_path: Path, *, executable: str) -> list[str]:
    return [executable, "-o", "json", "catalog", "find-by-path", str(raw_path)]


def develop_apply_command(
    photo_id: str,
    settings: dict[str, Any],
    *,
    executable: str,
) -> list[str]:
    return [
        executable,
        "develop",
        "apply",
        "--photo-id",
        photo_id,
        "--settings",
        json.dumps(settings, ensure_ascii=False, separators=(",", ":")),
    ]


def export_command(
    photo_id: str,
    *,
    output_dir: Path,
    variant_id: str,
    executable: str,
    options: dict[str, Any],
) -> list[str]:
    command = [
        executable,
        "export",
        "photo",
        photo_id,
        "--output-dir",
        str(output_dir),
        "--format",
        str(options["format"]),
        "--quality",
        str(options["quality"]),
        "--color-space",
        str(options["color_space"]),
        "--filename-suffix",
        f"_{variant_id}",
    ]
    if options.get("resize_long_edge"):
        command.extend(["--resize-long-edge", str(options["resize_long_edge"])])
    if options.get("overwrite"):
        command.append("--overwrite")
    return command


def ai_mask_settings(mask: dict[str, Any]) -> dict[str, Any]:
    raw_settings = mask.get("settings")
    if raw_settings is None:
        raw_settings = mask.get("adjustments")
    if raw_settings is None:
        return {}
    if not isinstance(raw_settings, dict):
        raise ValueError("Lightroom mask settings must be an object")
    return lightroom_settings_from_adjustments(raw_settings, include_advanced=False)


def lightroom_masks_from_variant(variant: dict[str, Any]) -> list[dict[str, Any]]:
    masks = variant.get("masks", [])
    if masks is None:
        return []
    if not isinstance(masks, list):
        raise ValueError("Variant masks must be an array")

    resolved_masks = []
    for index, mask in enumerate(masks):
        if not isinstance(mask, dict):
            raise ValueError(f"Mask {index} must be an object")
        mask_type = str(mask.get("type") or mask.get("selection_type") or "").lower()
        if mask_type not in AI_MASK_TYPES:
            raise ValueError(f"Unsupported Lightroom AI mask type: {mask_type}")
        if mask.get("part"):
            raise ValueError("Part-specific AI masks are not supported by the lightroom-cli batch command")
        if mask.get("tool"):
            raise ValueError("Local geometric masks are not supported by the photo-id based Lightroom backend")

        preset = mask.get("preset") or mask.get("adjust_preset")
        settings = ai_mask_settings(mask)
        if preset and settings:
            raise ValueError("Lightroom mask cannot use both preset and settings")

        resolved_masks.append(
            {
                "type": mask_type,
                "settings": settings,
                "preset": preset,
                "rationale": mask.get("rationale", ""),
            }
        )
    return resolved_masks


def ensure_lightroom_composition_supported(variant: dict[str, Any]) -> None:
    composition = variant.get("composition")
    if not isinstance(composition, dict):
        return
    crop = composition.get("crop")
    if isinstance(crop, dict) and crop.get("enabled"):
        raise ValueError(
            "Lightroom backend does not execute crop parameters yet; use "
            "composition.decision=preserve_existing_crop, no_crop, or manual_recommendation"
        )


def ai_mask_command(
    photo_id: str,
    mask: dict[str, Any],
    *,
    executable: str,
) -> list[str]:
    resolved = lightroom_masks_from_variant({"masks": [mask]})[0]
    command = [
        executable,
        "develop",
        "ai",
        "batch",
        resolved["type"],
        "--photos",
        photo_id,
    ]
    if resolved["settings"]:
        command.extend(
            [
                "--adjust",
                json.dumps(resolved["settings"], ensure_ascii=False, separators=(",", ":")),
            ]
        )
    if resolved["preset"]:
        command.extend(["--adjust-preset", str(resolved["preset"])])
    return command


def photo_id_from_response(stdout: str) -> str | None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None

    candidates = [payload]
    result = payload.get("result") if isinstance(payload, dict) else None
    if isinstance(result, dict):
        candidates.insert(0, result)

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in ("photoId", "photo_id", "id", "localId", "local_id"):
            value = candidate.get(key)
            if value is not None:
                return str(value)
    return None


def run_subprocess(command: list[str], *, timeout: int | None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)


def resolve_photo_id(
    *,
    raw_path: Path,
    plan: dict[str, Any],
    variant: dict[str, Any],
    executable: str,
    dry_run: bool,
    render_timeout: int,
) -> tuple[str, list[list[str]]]:
    lightroom_plan = plan.get("lightroom") if isinstance(plan.get("lightroom"), dict) else {}
    lightroom_variant = variant.get("lightroom") if isinstance(variant.get("lightroom"), dict) else {}
    photo_id = lightroom_variant.get("photo_id") or lightroom_plan.get("photo_id")
    if photo_id:
        return str(photo_id), []

    command = find_photo_command(raw_path, executable=executable)
    if dry_run:
        return "<resolved-photo-id>", [command]

    completed = run_subprocess(command, timeout=render_timeout)
    resolved = photo_id_from_response(completed.stdout)
    if not resolved:
        raise RuntimeError(f"Could not resolve Lightroom photo id for {raw_path}")
    return resolved, [command]


def render_plan(
    *,
    plan: dict[str, Any],
    output_dir: Path,
    dry_run: bool,
    render_timeout: int,
    local_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    local_config = local_config or {}
    raw_path = Path(plan["source"])
    output_dir.mkdir(parents=True, exist_ok=True)

    executable = lightroom_cli(local_config)
    options = export_options(local_config)
    allow_ai_masks = allow_unverified_ai_masks(local_config)
    records = []

    for variant in plan["variants"]:
        variant_id = str(variant["variant_id"])
        style_id = str(variant.get("style_id", "agent_selected"))
        settings = lightroom_settings_from_adjustments(variant["adjustments"])
        ensure_lightroom_composition_supported(variant)
        masks = lightroom_masks_from_variant(variant)
        output_path = output_dir / output_name(raw_path, variant_id, str(options["format"]))

        record = {
            "source": str(raw_path),
            "output": str(output_path),
            "style_id": style_id,
            "variant_id": variant_id,
            "engine": "lightroom",
            "profile": "Lightroom develop settings",
            "reason": variant.get("rationale", ""),
            "adjustments": variant["adjustments"],
            "composition": variant.get("composition", {}),
            "mask_decision": variant.get("mask_decision", {}),
            "lightroom_settings": settings,
            "lightroom_masks": masks,
            "status": "dry_run" if dry_run else "pending",
            "failure_reason": "",
        }

        try:
            photo_id, resolve_commands = resolve_photo_id(
                raw_path=raw_path,
                plan=plan,
                variant=variant,
                executable=executable,
                dry_run=dry_run,
                render_timeout=render_timeout,
            )
            mask_commands = [
                ai_mask_command(photo_id, mask, executable=executable)
                for mask in (variant.get("masks") or [])
            ]
            if mask_commands and not allow_ai_masks:
                raise ValueError(
                    "Lightroom AI mask execution is disabled by default because the current "
                    "batch bridge can bind AI masks to the wrong active photo. Use "
                    "mask_decision=manual_recommendation, or set "
                    "lightroom.allow_unverified_ai_masks=true only after manual overlay validation."
                )
            commands = [
                *resolve_commands,
                develop_apply_command(photo_id, settings, executable=executable),
                *mask_commands,
                export_command(
                    photo_id,
                    output_dir=output_dir,
                    variant_id=variant_id,
                    executable=executable,
                    options=options,
                ),
            ]
            record["photo_id"] = photo_id
            record["command"] = " && ".join(shlex.join(command) for command in commands)

            if not dry_run:
                for command in commands:
                    run_subprocess(command, timeout=render_timeout)
                record["status"] = "success"
        except (subprocess.SubprocessError, OSError, RuntimeError, ValueError) as exc:
            record["status"] = "failed"
            record["failure_reason"] = str(exc)

        records.append(record)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "processing_records.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = write_processing_report.render_report(records)
    (output_dir / "processing_report.md").write_text(report, encoding="utf-8")

    return {
        "source": str(raw_path),
        "output_dir": str(output_dir),
        "engine": "lightroom",
        "rendered": len(records),
        "succeeded": sum(1 for record in records if record["status"] in {"success", "dry_run"}),
        "failed": sum(1 for record in records if record["status"] == "failed"),
        "dry_run": dry_run,
    }
