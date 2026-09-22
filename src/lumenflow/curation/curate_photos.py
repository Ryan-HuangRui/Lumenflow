"""Build and validate a model-driven photo curation workspace.

The curation package owns deterministic operations only: RAW discovery,
metadata/date filtering, embedded-preview extraction, contact sheets, plan
validation, and packaging.  Visual selection and sequencing remain the host
agent's job.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont, ImageOps

from lumenflow.config import read_local_config, resolve_photo_output_dir

from .scan_raws import scan_raws


CANDIDATE_SCHEMA_VERSION = "lumenflow.candidate_manifest.v1"
SELECTION_SCHEMA_VERSION = "lumenflow.selection_plan.v1"
SELECTION_DECISIONS = {
    "agent_recommended_pending_user_confirmation",
    "user_confirmed",
}


class CurationError(RuntimeError):
    """Base error for deterministic curation failures."""


class SelectionPlanError(CurationError):
    """Raised when a model-authored selection plan violates the contract."""


def _non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SelectionPlanError(f"{field} must be a non-empty string")
    return value.strip()


def parse_capture_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    formats = (
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    )
    for date_format in formats:
        try:
            return datetime.strptime(normalized[:19], date_format)
        except ValueError:
            continue
    return None


def read_capture_metadata(raw_path: Path, exiftool: str = "exiftool") -> dict[str, Any]:
    command = [
        exiftool,
        "-json",
        "-DateTimeOriginal",
        "-CreateDate",
        "-Model",
        str(raw_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise CurationError(result.stderr.strip() or f"ExifTool failed for {raw_path}")
    payload = json.loads(result.stdout)
    if not payload:
        return {}
    record = payload[0]
    return {
        "capture_time": record.get("DateTimeOriginal") or record.get("CreateDate"),
        "camera_model": record.get("Model"),
    }


def extract_embedded_preview(
    raw_path: Path,
    destination: Path,
    exiftool: str = "exiftool",
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    for tag in ("JpgFromRaw", "PreviewImage", "ThumbnailImage"):
        result = subprocess.run(
            [exiftool, "-q", "-q", "-b", f"-{tag}", str(raw_path)],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.startswith(b"\xff\xd8"):
            destination.write_bytes(result.stdout)
            return
    raise CurationError(f"No embedded JPEG preview found in {raw_path}")


def _date_bound(value: str | None, field: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CurationError(f"{field} must use YYYY-MM-DD") from exc


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return stem or "photo"


def _candidate_is_in_range(
    capture_time: datetime | None,
    date_from: date | None,
    date_to: date | None,
) -> bool:
    if date_from is None and date_to is None:
        return True
    if capture_time is None:
        return False
    captured = capture_time.date()
    return (date_from is None or captured >= date_from) and (date_to is None or captured <= date_to)


def create_contact_sheets(
    candidates: list[dict[str, Any]],
    output_dir: Path,
    *,
    per_sheet: int = 20,
    columns: int = 5,
    thumb_size: tuple[int, int] = (360, 240),
) -> list[Path]:
    if per_sheet <= 0 or columns <= 0:
        raise CurationError("per_sheet and columns must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    if not candidates:
        return []

    cell_width = thumb_size[0] + 24
    cell_height = thumb_size[1] + 56
    font = ImageFont.load_default()
    outputs: list[Path] = []

    for page_index, start in enumerate(range(0, len(candidates), per_sheet), start=1):
        page_candidates = candidates[start : start + per_sheet]
        rows = (len(page_candidates) + columns - 1) // columns
        page = Image.new("RGB", (columns * cell_width, rows * cell_height), "#171717")
        draw = ImageDraw.Draw(page)
        for slot, candidate in enumerate(page_candidates):
            preview_path = Path(candidate["preview"])
            with Image.open(preview_path) as opened:
                preview = ImageOps.exif_transpose(opened).convert("RGB")
                preview.thumbnail(thumb_size, Image.Resampling.LANCZOS)
                x = (slot % columns) * cell_width + (cell_width - preview.width) // 2
                y = (slot // columns) * cell_height + 10
                page.paste(preview, (x, y))
            label = f"{start + slot + 1:03d}  {candidate['asset_id']}"
            draw.text(
                ((slot % columns) * cell_width + 12, (slot // columns) * cell_height + thumb_size[1] + 20),
                label,
                fill="white",
                font=font,
            )
        destination = output_dir / f"contact_sheet_{page_index:03d}.jpg"
        page.save(destination, format="JPEG", quality=88)
        outputs.append(destination)
    return outputs


def prepare_workspace(
    source_dir: Path,
    output_dir: Path,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    metadata_reader: Callable[[Path], dict[str, Any]] | None = None,
    preview_extractor: Callable[[Path, Path], None] | None = None,
    per_sheet: int = 20,
    columns: int = 5,
) -> dict[str, Any]:
    source_dir = source_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not source_dir.is_dir():
        raise CurationError(f"Source directory does not exist: {source_dir}")

    lower = _date_bound(date_from, "date_from")
    upper = _date_bound(date_to, "date_to")
    if lower is not None and upper is not None and lower > upper:
        raise CurationError("date_from must not be after date_to")

    metadata_reader = metadata_reader or read_capture_metadata
    preview_extractor = preview_extractor or extract_embedded_preview
    output_dir.mkdir(parents=True, exist_ok=True)
    previews_dir = output_dir / "previews"
    previews_dir.mkdir(parents=True, exist_ok=True)

    raw_items = scan_raws(source_dir)
    candidates: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for raw_item in raw_items:
        raw_path = Path(raw_item["path"])
        asset_id = raw_path.relative_to(source_dir).as_posix()
        try:
            metadata = metadata_reader(raw_path) or {}
        except Exception as exc:  # keep one corrupt file from aborting the workspace
            metadata = {}
            failures.append({"asset_id": asset_id, "stage": "metadata", "error": str(exc)})

        captured = parse_capture_time(metadata.get("capture_time"))
        if not _candidate_is_in_range(captured, lower, upper):
            if captured is None and (lower is not None or upper is not None):
                failures.append(
                    {
                        "asset_id": asset_id,
                        "stage": "date_filter",
                        "error": "capture time unavailable; excluded from requested date range",
                    }
                )
            continue

        preview_name = f"{len(candidates) + 1:04d}_{_safe_stem(raw_path.stem)}.jpg"
        preview_path = previews_dir / preview_name
        try:
            preview_extractor(raw_path, preview_path)
        except Exception as exc:
            failures.append({"asset_id": asset_id, "stage": "preview", "error": str(exc)})
            continue

        candidates.append(
            {
                "asset_id": asset_id,
                "source": str(raw_path),
                "preview": str(preview_path),
                "capture_time": captured.isoformat(timespec="seconds") if captured else None,
                "camera_model": metadata.get("camera_model"),
            }
        )

    sheets = create_contact_sheets(
        candidates,
        output_dir / "contact_sheets",
        per_sheet=per_sheet,
        columns=columns,
    )
    manifest: dict[str, Any] = {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "source_dir": str(source_dir),
        "preview_basis": "embedded_camera_jpeg",
        "date_filter": {"from": date_from, "to": date_to},
        "raw_count": len(raw_items),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "contact_sheets": [str(path) for path in sheets],
        "failures": failures,
        "raw_files_modified": False,
    }
    (output_dir / "candidate_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def validate_selection_plan(plan: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema_version") != CANDIDATE_SCHEMA_VERSION:
        raise SelectionPlanError(f"manifest.schema_version must be {CANDIDATE_SCHEMA_VERSION}")
    if plan.get("schema_version") != SELECTION_SCHEMA_VERSION:
        raise SelectionPlanError(f"schema_version must be {SELECTION_SCHEMA_VERSION}")

    purpose = _non_empty_string(plan.get("purpose"), "purpose")
    manifest_candidates = manifest.get("candidates")
    if not isinstance(manifest_candidates, list):
        raise SelectionPlanError("manifest.candidates must be an array")
    known_assets = {
        item.get("asset_id"): item
        for item in manifest_candidates
        if isinstance(item, dict) and isinstance(item.get("asset_id"), str)
    }

    selection = plan.get("selection")
    if not isinstance(selection, list) or not selection:
        raise SelectionPlanError("selection must be a non-empty array")
    normalized_selection: list[dict[str, Any]] = []
    selected_assets: set[str] = set()
    for index, item in enumerate(selection):
        if not isinstance(item, dict):
            raise SelectionPlanError(f"selection[{index}] must be an object")
        order = item.get("order")
        if not isinstance(order, int) or isinstance(order, bool) or order <= 0:
            raise SelectionPlanError(f"selection[{index}].order must be a positive integer")
        asset_id = _non_empty_string(item.get("asset_id"), f"selection[{index}].asset_id")
        if asset_id not in known_assets:
            raise SelectionPlanError(f"selection[{index}].asset_id is not in the candidate manifest: {asset_id}")
        if asset_id in selected_assets:
            raise SelectionPlanError(f"selection contains duplicate asset_id: {asset_id}")
        selected_assets.add(asset_id)
        normalized_selection.append(
            {
                "order": order,
                "asset_id": asset_id,
                "role": _non_empty_string(item.get("role"), f"selection[{index}].role"),
                "reason": _non_empty_string(item.get("reason"), f"selection[{index}].reason"),
            }
        )

    normalized_selection.sort(key=lambda item: item["order"])
    actual_orders = [item["order"] for item in normalized_selection]
    expected_orders = list(range(1, len(normalized_selection) + 1))
    if actual_orders != expected_orders:
        raise SelectionPlanError(f"selection order must be contiguous starting at 1; got {actual_orders}")

    alternates = plan.get("alternates", [])
    if not isinstance(alternates, list):
        raise SelectionPlanError("alternates must be an array")
    normalized_alternates: list[dict[str, Any]] = []
    for index, item in enumerate(alternates):
        if not isinstance(item, dict):
            raise SelectionPlanError(f"alternates[{index}] must be an object")
        target = _non_empty_string(item.get("for_asset_id"), f"alternates[{index}].for_asset_id")
        if target not in selected_assets:
            raise SelectionPlanError(f"alternate target is not selected: {target}")
        assets = item.get("asset_ids")
        if not isinstance(assets, list) or not assets:
            raise SelectionPlanError(f"alternates[{index}].asset_ids must be a non-empty array")
        normalized_assets: list[str] = []
        for asset in assets:
            asset_id = _non_empty_string(asset, f"alternates[{index}].asset_ids")
            if asset_id not in known_assets:
                raise SelectionPlanError(f"alternate asset is not in the candidate manifest: {asset_id}")
            if asset_id in selected_assets:
                raise SelectionPlanError(f"alternate asset is already in the selected sequence: {asset_id}")
            normalized_assets.append(asset_id)
        normalized_alternates.append(
            {
                "for_asset_id": target,
                "asset_ids": normalized_assets,
                "tradeoff": _non_empty_string(item.get("tradeoff"), f"alternates[{index}].tradeoff"),
            }
        )

    experiments = plan.get("edit_experiments", [])
    if not isinstance(experiments, list):
        raise SelectionPlanError("edit_experiments must be an array")
    normalized_experiments: list[dict[str, Any]] = []
    for index, item in enumerate(experiments):
        if not isinstance(item, dict):
            raise SelectionPlanError(f"edit_experiments[{index}] must be an object")
        asset_id = _non_empty_string(item.get("asset_id"), f"edit_experiments[{index}].asset_id")
        if asset_id not in selected_assets:
            raise SelectionPlanError(f"edit experiment asset is not selected: {asset_id}")
        tests = item.get("tests")
        if not isinstance(tests, list) or not tests:
            raise SelectionPlanError(f"edit_experiments[{index}].tests must be a non-empty array")
        normalized_experiments.append(
            {"asset_id": asset_id, "tests": [_non_empty_string(test, "edit experiment test") for test in tests]}
        )

    status = plan.get("status")
    if not isinstance(status, dict):
        raise SelectionPlanError("status must be an object")
    decision = status.get("decision")
    if decision not in SELECTION_DECISIONS:
        raise SelectionPlanError(f"status.decision must be one of {sorted(SELECTION_DECISIONS)}")
    if status.get("raw_files_modified") is not False:
        raise SelectionPlanError("status.raw_files_modified must be false")

    normalized = dict(plan)
    normalized["purpose"] = purpose
    normalized["selection"] = normalized_selection
    normalized["alternates"] = normalized_alternates
    normalized["edit_experiments"] = normalized_experiments
    normalized["status"] = {"decision": decision, "raw_files_modified": False}
    return normalized


def _write_selection_report(plan: dict[str, Any], manifest: dict[str, Any], destination: Path) -> None:
    by_asset = {item["asset_id"]: item for item in manifest["candidates"]}
    lines = [
        "# Photo Selection Report",
        "",
        f"Purpose: {plan['purpose']}",
        "",
        f"Decision: `{plan['status']['decision']}`",
        "",
        "## Selected Sequence",
        "",
    ]
    for item in plan["selection"]:
        candidate = by_asset[item["asset_id"]]
        lines.extend(
            [
                f"{item['order']}. **{item['asset_id']}** — {item['role']}",
                f"   - Why: {item['reason']}",
                f"   - Source: `{candidate['source']}`",
            ]
        )
    if plan["alternates"]:
        lines.extend(["", "## Alternates", ""])
        for item in plan["alternates"]:
            lines.append(
                f"- For **{item['for_asset_id']}**: {', '.join(item['asset_ids'])} — {item['tradeoff']}"
            )
    if plan["edit_experiments"]:
        lines.extend(["", "## Edit Experiments", ""])
        for item in plan["edit_experiments"]:
            lines.append(f"- **{item['asset_id']}**: {', '.join(item['tests'])}")
    lines.extend(["", "RAW files modified: **no**", ""])
    destination.write_text("\n".join(lines), encoding="utf-8")


def finalize_selection(
    *,
    manifest_path: Path,
    plan_path: Path,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser().resolve()
    plan_path = plan_path.expanduser().resolve()
    output_dir = (output_dir or manifest_path.parent).expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    normalized = validate_selection_plan(plan, manifest)
    by_asset = {item["asset_id"]: item for item in manifest["candidates"]}

    selected_dir = output_dir / "selected_previews"
    selected_dir.mkdir(parents=True, exist_ok=True)
    packaged: list[str] = []
    for item in normalized["selection"]:
        candidate = by_asset[item["asset_id"]]
        preview = Path(candidate["preview"])
        if not preview.is_file():
            raise CurationError(f"Preview does not exist for {item['asset_id']}: {preview}")
        destination = selected_dir / f"{item['order']:02d}_{_safe_stem(Path(item['asset_id']).stem)}{preview.suffix.lower()}"
        shutil.copy2(preview, destination)
        packaged.append(str(destination))

    normalized_path = output_dir / "selection_plan.validated.json"
    normalized_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path = output_dir / "selection_report.md"
    _write_selection_report(normalized, manifest, report_path)
    return {
        "selected_count": len(packaged),
        "selected_previews": packaged,
        "validated_plan": str(normalized_path),
        "report": str(report_path),
        "decision": normalized["status"]["decision"],
        "raw_files_modified": False,
    }


def _prepare_command(args: argparse.Namespace) -> dict[str, Any]:
    config = read_local_config(args.config)
    output_dir = resolve_photo_output_dir(
        config,
        args.source_dir,
        explicit_output_dir=args.output_dir,
        subdir="curation",
    )
    return prepare_workspace(
        args.source_dir,
        output_dir,
        date_from=args.date_from,
        date_to=args.date_to,
        per_sheet=args.per_sheet,
        columns=args.columns,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare and validate model-driven photo curation workspaces.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Scan RAWs, extract previews, and build contact sheets.")
    prepare.add_argument("source_dir", type=Path)
    prepare.add_argument("--output-dir", type=Path)
    prepare.add_argument("--config", type=Path, default=Path("config/lumenflow.local.json"))
    prepare.add_argument("--date-from")
    prepare.add_argument("--date-to")
    prepare.add_argument("--per-sheet", type=int, default=20)
    prepare.add_argument("--columns", type=int, default=5)

    finalize = subparsers.add_parser("finalize", help="Validate a model-authored plan and package its previews.")
    finalize.add_argument("manifest", type=Path)
    finalize.add_argument("plan", type=Path)
    finalize.add_argument("--output-dir", type=Path)

    args = parser.parse_args()
    if args.command == "prepare":
        result = _prepare_command(args)
    else:
        result = finalize_selection(
            manifest_path=args.manifest,
            plan_path=args.plan,
            output_dir=args.output_dir,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


__all__ = [
    "CANDIDATE_SCHEMA_VERSION",
    "CurationError",
    "SELECTION_DECISIONS",
    "SELECTION_SCHEMA_VERSION",
    "SelectionPlanError",
    "create_contact_sheets",
    "extract_embedded_preview",
    "finalize_selection",
    "main",
    "parse_capture_time",
    "prepare_workspace",
    "read_capture_metadata",
    "resolve_photo_output_dir",
    "read_local_config",
    "scan_raws",
    "validate_selection_plan",
]
