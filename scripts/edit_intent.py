#!/usr/bin/env python3
"""Compile vendor-neutral EditIntent documents and execute backend plans safely."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import backend_capabilities
import darktable_codec
import lumenflow_config
import preview_provider
import render_adjustment_plan
import render_raw
import rawtherapee_pp3
import scan_raws


EDIT_INTENT_SCHEMA_VERSION = "lumenflow.edit_intent.v2"
EXECUTION_PLAN_SCHEMA_VERSION = "lumenflow.execution_plan.v1"
EXECUTION_RECEIPT_SCHEMA_VERSION = "lumenflow.execution_receipt.v1"


class IntentValidationError(ValueError):
    """Raised when an EditIntent document violates the v2 contract."""


class ExecutionPreconditionError(RuntimeError):
    def __init__(self, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "reason": self.reason}


CommandRunner = Callable[..., int]

INTENT_FIELDS = {
    "schema_version",
    "intent_id",
    "revision",
    "authorization",
    "source",
    "preview_basis",
    "purpose",
    "style",
    "global_adjustments",
    "composition",
    "local_adjustments",
}
GLOBAL_ADJUSTMENT_RANGES: dict[str, tuple[float | None, float | None]] = {
    "exposure_ev": (-5, 5),
    "brightness": (-100, 100),
    "contrast": (-100, 100),
    "highlight_recovery": (0, 100),
    "shadow_lift": (-100, 100),
    "black_point": (None, None),
    "saturation": (-100, 100),
    "temperature_k": (2000, 50000),
    "green_multiplier": (0, None),
}
DARKTABLE_STATE_INPUT_ROLES = {"base_profile", "source_sidecar"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    if not name:
        raise IntentValidationError("intent_id must contain at least one filename-safe character")
    return name


def _require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntentValidationError(f"{field} must be an object")
    return value


def _reject_unknown(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise IntentValidationError(f"{field} contains unknown fields: {', '.join(sorted(unknown))}")


def _validate_fingerprint(value: dict[str, Any], field: str) -> None:
    _reject_unknown(value, {"sha256", "size_bytes"}, field)
    if not re.fullmatch(r"[0-9a-f]{64}", str(value.get("sha256", ""))):
        raise IntentValidationError(f"{field}.sha256 must be a lowercase SHA-256")
    if not isinstance(value.get("size_bytes"), int) or value["size_bytes"] < 0:
        raise IntentValidationError(f"{field}.size_bytes must be a non-negative integer")


def _validate_adjustments(value: dict[str, Any], field: str) -> None:
    _reject_unknown(value, set(GLOBAL_ADJUSTMENT_RANGES), field)
    for key, adjustment in value.items():
        if isinstance(adjustment, bool) or not isinstance(adjustment, (int, float)):
            raise IntentValidationError(f"{field}.{key} must be a finite number")
        number = float(adjustment)
        if not math.isfinite(number):
            raise IntentValidationError(f"{field}.{key} must be a finite number")
        minimum, maximum = GLOBAL_ADJUSTMENT_RANGES[key]
        if minimum is not None and (number < minimum or (key == "green_multiplier" and number == 0)):
            raise IntentValidationError(f"{field}.{key} is below its supported range")
        if maximum is not None and number > maximum:
            raise IntentValidationError(f"{field}.{key} is above its supported range")


def validate_edit_intent(intent: dict[str, Any]) -> None:
    _reject_unknown(intent, INTENT_FIELDS, "EditIntent")
    if intent.get("schema_version") != EDIT_INTENT_SCHEMA_VERSION:
        raise IntentValidationError(
            f"Unsupported EditIntent schema_version: {intent.get('schema_version')}"
        )
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(intent.get("intent_id", ""))):
        raise IntentValidationError("intent_id must use only letters, numbers, dot, underscore, or hyphen")
    if not isinstance(intent.get("revision"), int) or intent["revision"] < 1:
        raise IntentValidationError("revision must be a positive integer")

    authorization = _require_object(intent.get("authorization"), "authorization")
    _reject_unknown(authorization, {"kind", "reference_id"}, "authorization")
    if authorization.get("kind") not in {"user_confirmed_selection", "explicit_user_request"}:
        raise IntentValidationError("authorization.kind is not supported")
    if not str(authorization.get("reference_id", "")).strip():
        raise IntentValidationError("authorization.reference_id is required")

    source = _require_object(intent.get("source"), "source")
    _reject_unknown(source, {"path", "fingerprint"}, "source")
    if not str(source.get("path", "")).strip():
        raise IntentValidationError("source.path is required")
    if Path(source["path"]).suffix.lower() not in scan_raws.RAW_EXTENSIONS:
        raise IntentValidationError("source.path must use a supported RAW extension")
    fingerprint = _require_object(source.get("fingerprint"), "source.fingerprint")
    _validate_fingerprint(fingerprint, "source.fingerprint")

    preview_basis = _require_object(intent.get("preview_basis"), "preview_basis")
    _reject_unknown(
        preview_basis,
        {"artifact_id", "starting_state_hash", "state_completeness", "state_inputs"},
        "preview_basis",
    )
    if not re.fullmatch(r"preview_[0-9a-f]{32}", str(preview_basis.get("artifact_id", ""))):
        raise IntentValidationError("preview_basis.artifact_id is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(preview_basis.get("starting_state_hash", ""))):
        raise IntentValidationError("preview_basis.starting_state_hash must be a SHA-256")
    if preview_basis.get("state_completeness") not in {"complete", "partial"}:
        raise IntentValidationError("preview_basis.state_completeness must be complete or partial")
    state_inputs = preview_basis.get("state_inputs")
    if state_inputs is not None:
        if not isinstance(state_inputs, list):
            raise IntentValidationError("preview_basis.state_inputs must be an array")
        allowed_roles = {"base_profile", "source_sidecar"}
        for index, item in enumerate(state_inputs):
            item = _require_object(item, f"preview_basis.state_inputs[{index}]")
            _reject_unknown(
                item,
                {"role", "path", "sha256", "size_bytes"},
                f"preview_basis.state_inputs[{index}]",
            )
            if item.get("role") not in allowed_roles:
                raise IntentValidationError(
                    f"preview_basis.state_inputs[{index}].role is not supported"
                )
            if not str(item.get("path", "")).strip():
                raise IntentValidationError(
                    f"preview_basis.state_inputs[{index}].path is required"
                )
            _validate_fingerprint(
                {"sha256": item.get("sha256"), "size_bytes": item.get("size_bytes")},
                f"preview_basis.state_inputs[{index}]",
            )

    if not str(intent.get("purpose", "")).strip():
        raise IntentValidationError("purpose is required")
    style = _require_object(intent.get("style"), "style")
    _reject_unknown(style, {"style_id", "rationale", "darktable", "rawtherapee"}, "style")
    if not str(style.get("style_id", "")).strip() or not str(style.get("rationale", "")).strip():
        raise IntentValidationError("style_id and style rationale are required")
    darktable_style = style.get("darktable")
    if darktable_style is not None:
        darktable_style = _require_object(darktable_style, "style.darktable")
        _reject_unknown(darktable_style, {"modules"}, "style.darktable")
        modules = darktable_style.get("modules")
        if not isinstance(modules, list) or not modules:
            raise IntentValidationError("style.darktable.modules must be a non-empty array")
        # The engine-specific codec performs field/range validation during
        # compilation.  Keep schema validation strict about the container so
        # malformed JSON cannot be interpreted as a replay request.
        for index, module in enumerate(modules):
            if not isinstance(module, dict):
                raise IntentValidationError(f"style.darktable.modules[{index}] must be an object")
    if "rawtherapee" in style:
        try:
            rawtherapee_pp3.validate_native_sections(style["rawtherapee"])
        except rawtherapee_pp3.PP3UnsupportedValue as error:
            raise IntentValidationError(str(error)) from error
    global_adjustments = _require_object(intent.get("global_adjustments"), "global_adjustments")
    _validate_adjustments(global_adjustments, "global_adjustments")

    composition = _require_object(intent.get("composition"), "composition")
    _reject_unknown(composition, {"decision", "reason", "crop"}, "composition")
    decision = composition.get("decision")
    if decision not in {"preserve_existing_crop", "no_crop", "crop", "manual_recommendation"}:
        raise IntentValidationError("composition.decision is not supported")
    if not str(composition.get("reason", "")).strip():
        raise IntentValidationError("composition.reason is required")
    crop = composition.get("crop")
    if decision == "crop":
        crop = _require_object(crop, "composition.crop")
        _reject_unknown(
            crop,
            {"unit", "x", "y", "width", "height", "fixed_ratio", "ratio"},
            "composition.crop",
        )
        if crop.get("unit") != "pixels":
            raise IntentValidationError("The v2 RawTherapee slice requires pixel crop coordinates")
        for key in ("x", "y", "width", "height"):
            if isinstance(crop.get(key), bool) or not isinstance(crop.get(key), int):
                raise IntentValidationError(f"composition.crop.{key} must be an integer")
        if crop["x"] < 0 or crop["y"] < 0 or crop["width"] < 1 or crop["height"] < 1:
            raise IntentValidationError("composition.crop coordinates and dimensions are invalid")
        if "fixed_ratio" in crop and not isinstance(crop["fixed_ratio"], bool):
            raise IntentValidationError("composition.crop.fixed_ratio must be a boolean")
        if "ratio" in crop and not str(crop["ratio"]).strip():
            raise IntentValidationError("composition.crop.ratio must not be empty")
    elif crop is not None:
        raise IntentValidationError("composition.crop is only valid when decision=crop")

    local_adjustments = _require_object(intent.get("local_adjustments"), "local_adjustments")
    _reject_unknown(local_adjustments, {"decision", "reason", "masks"}, "local_adjustments")
    if local_adjustments.get("decision") not in {"none", "use_masks", "manual_recommendation"}:
        raise IntentValidationError("local_adjustments.decision is not supported")
    if not str(local_adjustments.get("reason", "")).strip():
        raise IntentValidationError("local_adjustments.reason is required")
    masks = local_adjustments.get("masks")
    if not isinstance(masks, list):
        raise IntentValidationError("local_adjustments.masks must be an array")
    if local_adjustments.get("decision") == "use_masks" and not masks:
        raise IntentValidationError("local_adjustments.decision=use_masks requires masks")
    if local_adjustments.get("decision") != "use_masks" and masks:
        raise IntentValidationError("Executable masks require local_adjustments.decision=use_masks")
    for index, mask in enumerate(masks):
        mask = _require_object(mask, f"local_adjustments.masks[{index}]")
        _reject_unknown(
            mask,
            {"type", "rationale", "adjustments"},
            f"local_adjustments.masks[{index}]",
        )
        if mask.get("type") not in {"subject", "sky", "background", "objects", "people", "landscape"}:
            raise IntentValidationError(f"local_adjustments.masks[{index}].type is not supported")
        if not str(mask.get("rationale", "")).strip():
            raise IntentValidationError(f"local_adjustments.masks[{index}].rationale is required")
        mask_adjustments = _require_object(
            mask.get("adjustments"),
            f"local_adjustments.masks[{index}].adjustments",
        )
        _validate_adjustments(mask_adjustments, f"local_adjustments.masks[{index}].adjustments")


def _legacy_adjustments(global_adjustments: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "exposure_ev": "exposure_compensation",
        "brightness": "brightness",
        "contrast": "contrast",
        "highlight_recovery": "highlight_compression",
        "shadow_lift": "shadow_compression",
        "black_point": "black",
        "saturation": "saturation",
        "temperature_k": "temperature",
        "green_multiplier": "green",
    }
    unknown = set(global_adjustments) - set(mapping)
    if unknown:
        raise IntentValidationError(
            "Unsupported EditIntent v2 global adjustments: " + ", ".join(sorted(unknown))
        )
    return {
        target: global_adjustments[source]
        for source, target in mapping.items()
        if source in global_adjustments
    }


def _legacy_composition(composition: dict[str, Any]) -> dict[str, Any]:
    payload = dict(composition)
    if composition.get("decision") == "crop":
        payload["crop"] = {**composition["crop"], "enabled": True}
    return payload


def _rawtherapee_profile_inputs(
    intent: dict[str, Any],
) -> list[tuple[str, Path]]:
    """Resolve and verify the profile stack used by the approved preview.

    Older EditIntent documents only contain the starting-state hash.  For
    those documents we can still replay the source sidecar when present.  New
    documents may carry the preview artifact's explicit ``state_inputs`` so a
    base profile outside the RAW directory is also captured and replayed.
    The compiled profile embeds the verified bytes, so execution never reads
    a mutable NAS sidecar after compilation.
    """

    source_path = Path(intent["source"]["path"])
    preview_basis = intent["preview_basis"]
    raw_inputs = preview_basis.get("state_inputs")
    inputs: list[tuple[str, Path]] = []
    if raw_inputs is not None:
        seen: set[Path] = set()
        for item in raw_inputs:
            path = Path(item["path"])
            if path in seen:
                raise ExecutionPreconditionError(
                    "INVALID_PREVIEW_STATE",
                    f"Duplicate RawTherapee profile input: {path}",
                )
            seen.add(path)
            if not path.is_file() or path.is_symlink():
                raise ExecutionPreconditionError(
                    "PREVIEW_STATE_INPUT_MISSING",
                    f"RawTherapee preview profile input is not a regular file: {path}",
                )
            if path.suffix.lower() != ".pp3":
                raise ExecutionPreconditionError(
                    "INVALID_PREVIEW_STATE",
                    f"RawTherapee preview profile input must use .pp3: {path}",
                )
            actual = rawtherapee_pp3.file_fingerprint(path)
            expected = {"sha256": item["sha256"], "size_bytes": item["size_bytes"]}
            if actual != expected:
                raise ExecutionPreconditionError(
                    "PREVIEW_STATE_INPUT_MISMATCH",
                    f"RawTherapee preview profile input changed: {path}",
                )
            inputs.append((str(item["role"]), path))
    else:
        sidecar = rawtherapee_pp3.discover_source_sidecar(source_path)
        if sidecar is not None:
            inputs.append(("source_sidecar", sidecar))

    # If state inputs are explicit, the hash is a mandatory binding.  When a
    # legacy intent discovers only the source sidecar, validate it when the
    # preview hash is meaningful; old fixtures with no inputs remain backward
    # compatible and are handled by the original neutral-state path.
    if inputs:
        starting_state, _state_inputs = rawtherapee_pp3.profile_stack_state(inputs)
        expected_hash = rawtherapee_pp3.canonical_hash(starting_state)
        if preview_basis["starting_state_hash"] != expected_hash:
            raise ExecutionPreconditionError(
                "STARTING_STATE_MISMATCH",
                "The current RawTherapee PP3 profile stack no longer matches the preview basis",
            )
    return inputs


def _darktable_starting_state(fingerprint: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "darktable_xmp",
        "xmp": fingerprint,
        "uses_engine_default": False,
        "library": ":memory:",
        "write_sidecars": False,
    }


def _read_darktable_xmp(path: Path) -> tuple[str, dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise IntentValidationError("darktable XMP input must be an existing regular file")
    if path.stat().st_size > 1024 * 1024:
        raise IntentValidationError("darktable XMP input exceeds the 1 MiB plan limit")
    raw = path.read_bytes()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise IntentValidationError("darktable XMP input must be UTF-8") from error
    fingerprint = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }
    return content, fingerprint


def _darktable_xmp_input(source_path: Path) -> tuple[Path, str, dict[str, Any], str]:
    candidates = {
        source_path.with_suffix(".xmp"),
        source_path.with_name(source_path.name + ".xmp"),
    }
    existing = sorted(path for path in candidates if path.is_file() and not path.is_symlink())
    if len(existing) != 1:
        raise IntentValidationError(
            "darktable XMP replay requires exactly one regular source sidecar"
        )
    xmp_path = existing[0]
    content, fingerprint = _read_darktable_xmp(xmp_path)
    return (
        xmp_path,
        content,
        fingerprint,
        preview_provider.canonical_hash(_darktable_starting_state(fingerprint)),
    )


def _darktable_state_input(
    intent: dict[str, Any],
    source_path: Path,
) -> tuple[Path, str, dict[str, Any], str, dict[str, Any]]:
    """Resolve the preview-bound XMP, embedding its bytes before execution.

    An explicit state input may carry content copied from the preview artifact;
    in that case the path is provenance only and is never read.  Without
    content, the path is read once during compilation and its declared
    fingerprint must match.  The executor consumes only the resulting plan.
    """

    state_inputs = intent.get("preview_basis", {}).get("state_inputs")
    if state_inputs is None:
        xmp_path, content, fingerprint, state_hash = _darktable_xmp_input(source_path)
        return (
            xmp_path,
            content,
            fingerprint,
            state_hash,
            {"role": "source_sidecar", "path": str(xmp_path), **fingerprint},
        )
    if not isinstance(state_inputs, list) or len(state_inputs) != 1:
        raise IntentValidationError(
            "preview_basis.state_inputs must contain exactly one darktable XMP input"
        )
    state_input = state_inputs[0]
    if not isinstance(state_input, dict):
        raise IntentValidationError("preview_basis.state_inputs[0] must be an object")
    role = state_input.get("role")
    if role not in DARKTABLE_STATE_INPUT_ROLES:
        raise IntentValidationError("preview_basis.state_inputs[0].role is not supported")
    path_text = str(state_input.get("path", "")).strip()
    if not path_text:
        raise IntentValidationError("preview_basis.state_inputs[0].path is required")
    declared = {
        "sha256": state_input.get("sha256"),
        "size_bytes": state_input.get("size_bytes"),
    }
    _validate_fingerprint(declared, "preview_basis.state_inputs[0]")
    xmp_path = Path(path_text)
    if "content" in state_input:
        content = state_input["content"]
        if not isinstance(content, str):
            raise IntentValidationError("preview_basis.state_inputs[0].content must be UTF-8 text")
        raw = content.encode("utf-8")
        if len(raw) > 1024 * 1024:
            raise IntentValidationError("darktable XMP input exceeds the 1 MiB plan limit")
        actual = {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}
        if actual != declared:
            raise ExecutionPreconditionError(
                "STATE_INPUT_FINGERPRINT_MISMATCH",
                "Embedded darktable XMP bytes do not match the preview-bound fingerprint",
            )
    else:
        content, actual = _read_darktable_xmp(xmp_path)
        if actual != declared:
            raise ExecutionPreconditionError(
                "STATE_INPUT_FINGERPRINT_MISMATCH",
                "Darktable XMP input changed since the preview was created",
            )
    try:
        darktable_codec.validate_xmp(content)
    except darktable_codec.DarktableCodecError as error:
        raise IntentValidationError(str(error)) from error
    starting_state = _darktable_starting_state(declared)
    normalized = {"role": role, "path": path_text, **declared}
    return (
        xmp_path,
        content,
        declared,
        preview_provider.canonical_hash(starting_state),
        normalized,
    )


def _compile_darktable_intent(
    intent: dict[str, Any],
    *,
    output_dir: Path,
    local_config: dict[str, Any],
    capabilities: backend_capabilities.BackendCapabilities,
) -> dict[str, Any]:
    if "rawtherapee" in intent["style"]:
        raise IntentValidationError(
            "style.rawtherapee is only supported by the rawtherapee backend"
        )
    explicit_modules = (
        intent["style"].get("darktable", {}).get("modules", [])
        if isinstance(intent["style"].get("darktable"), dict)
        else []
    )
    dynamic_modules: list[dict[str, Any]] = []
    if intent["global_adjustments"]:
        try:
            dynamic_modules.extend(
                darktable_codec.modules_from_global_adjustments(intent["global_adjustments"])
            )
        except darktable_codec.DarktableCodecError as error:
            raise IntentValidationError(
                "The darktable compiler does not map dynamic adjustments: " + str(error)
            ) from error
    if explicit_modules:
        dynamic_modules.extend(explicit_modules)

    composition_decision = intent["composition"]["decision"]
    if composition_decision != "preserve_existing_crop":
        raise IntentValidationError(
            "The darktable module compiler requires composition.decision=preserve_existing_crop; "
            "vendor-neutral pixel crop is not supported"
        )
    if intent["local_adjustments"]["decision"] != "none":
        raise IntentValidationError(
            "The darktable module compiler does not map local adjustments"
        )

    source_path = Path(intent["source"]["path"])
    _xmp_path, xmp_content, xmp_fingerprint, starting_state_hash, state_input = (
        _darktable_state_input(intent, source_path)
    )
    if intent["preview_basis"]["state_completeness"] != "complete":
        raise ExecutionPreconditionError(
            "PREVIEW_STATE_INCOMPLETE",
            "darktable execution requires a complete, explicit XMP preview state",
        )
    if intent["preview_basis"]["starting_state_hash"] != starting_state_hash:
        raise ExecutionPreconditionError(
            "STARTING_STATE_MISMATCH",
            "The current darktable XMP no longer matches the preview basis",
        )

    safe_source_stem = _safe_name(source_path.stem)
    safe_intent_id = _safe_name(str(intent["intent_id"]))
    stem = f"{safe_source_stem}_{safe_intent_id}_r{intent['revision']}"
    profile_path = output_dir / "profiles" / f"{stem}.xmp"
    output_path = output_dir / f"{stem}.jpg"
    compiler = {"id": "lumenflow.darktable-xmp-replay", "version": "1"}
    profile_content = xmp_content
    profile_sha256 = xmp_fingerprint["sha256"]
    starting_state_payload: dict[str, Any] | None = None
    if dynamic_modules:
        try:
            profile_content, encoded_modules = darktable_codec.compile_xmp(
                xmp_content,
                dynamic_modules,
            )
        except darktable_codec.DarktableCodecError as error:
            raise IntentValidationError(str(error)) from error
        compiler = {"id": "lumenflow.darktable-xmp-modules", "version": "2"}
        profile_sha256 = hashlib.sha256(profile_content.encode("utf-8")).hexdigest()
        starting_state_payload = {
            **_darktable_starting_state(xmp_fingerprint),
            "state_inputs": [state_input],
            "xmp_content": xmp_content,
        }
    runtime_key = _canonical_hash(
        {
            "source": intent["source"],
            "preview_basis": intent["preview_basis"],
            "intent_id": intent["intent_id"],
            "revision": intent["revision"],
        }
    )[:24]
    runtime_root = output_dir / ".darktable-runtime" / runtime_key
    executable = lumenflow_config.tool_command(local_config, "darktable_cli", "darktable-cli")
    command = render_raw.build_darktable_command(
        source_path,
        output_path,
        xmp=profile_path,
        configdir=runtime_root / "config",
        cachedir=runtime_root / "cache",
        library=":memory:",
        write_sidecars=False,
        executable=executable,
    )
    required_capabilities = ["intent.compile.v2", "render"]
    identity = {
        "intent_id": intent["intent_id"],
        "intent_revision": intent["revision"],
        "authorization": intent["authorization"],
        "backend_id": "darktable",
        "source": intent["source"],
        "preview_basis": intent["preview_basis"],
        "required_capabilities": required_capabilities,
        "profile_path": str(profile_path),
        "profile_sha256": profile_sha256,
        "output_path": str(output_path),
        "command_argv": command,
    }
    plan_id = "plan_" + _canonical_hash(identity)[:32]
    plan = {
        "schema_version": EXECUTION_PLAN_SCHEMA_VERSION,
        "plan_id": plan_id,
        "intent_id": intent["intent_id"],
        "intent_revision": intent["revision"],
        "authorization": intent["authorization"],
        "backend": {
            "id": "darktable",
            "adapter_version": capabilities.adapter_version,
            "capability_contract_version": capabilities.schema_version,
        },
        "source": intent["source"],
        "preview_basis": intent["preview_basis"],
        "output_root": str(output_dir),
        "required_capabilities": required_capabilities,
        "artifacts": {
            "profile": {"path": str(profile_path), "sha256": profile_sha256},
            "output": {"path": str(output_path), "format": "JPEG"},
        },
        "operations": [
            {
                "operation_id": f"{plan_id}:profile",
                "kind": "materialize_profile",
                "payload": {
                    "path": str(profile_path),
                    "content": profile_content,
                    "sha256": profile_sha256,
                },
                "command_argv": [],
            },
            {
                "operation_id": f"{plan_id}:render",
                "kind": "render",
                "payload": {"output_path": str(output_path)},
                "command_argv": command,
            },
        ],
        "compiler": compiler,
        "created_at": _now(),
    }
    if starting_state_payload is not None:
        plan["starting_state"] = starting_state_payload
    return plan


def compile_intent(
    intent: dict[str, Any],
    *,
    backend_id: str,
    output_dir: Path,
    local_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_edit_intent(intent)
    local_config = local_config or {}
    capabilities = backend_capabilities.backend_capabilities_for(backend_id)
    required_capabilities = ["intent.compile.v2", "render"]
    if intent["composition"]["decision"] == "crop":
        required_capabilities.append("composition.crop")
    if intent["local_adjustments"]["decision"] == "use_masks":
        required_capabilities.append("mask.ai")
    capabilities.require("intent.compile.v2")
    for capability in required_capabilities[1:]:
        capabilities.require(capability)

    source_path = Path(intent["source"]["path"])
    actual_source_fingerprint = preview_provider.file_fingerprint(source_path)
    if actual_source_fingerprint != intent["source"]["fingerprint"]:
        raise ExecutionPreconditionError(
            "SOURCE_FINGERPRINT_MISMATCH",
            "The source bytes no longer match the EditIntent fingerprint",
        )

    if backend_id == "darktable":
        return _compile_darktable_intent(
            intent,
            output_dir=output_dir,
            local_config=local_config,
            capabilities=capabilities,
        )

    if backend_id != "rawtherapee":
        raise IntentValidationError(f"No EditIntent v2 compiler is registered for {backend_id}")
    if "darktable" in intent["style"]:
        raise IntentValidationError(
            "style.darktable is only supported by the darktable backend"
        )

    safe_source_stem = _safe_name(source_path.stem)
    safe_intent_id = _safe_name(str(intent["intent_id"]))
    stem = f"{safe_source_stem}_{safe_intent_id}_r{intent['revision']}"
    profile_path = output_dir / "profiles" / f"{stem}.pp3"
    output_path = output_dir / f"{stem}.jpg"
    profile_inputs = _rawtherapee_profile_inputs(intent)
    overrides = rawtherapee_pp3.semantic_overrides(
        _legacy_adjustments(intent["global_adjustments"]),
        composition=_legacy_composition(intent["composition"]),
    )
    native_contract = intent["style"].get("rawtherapee")
    if native_contract is not None:
        native_overrides = rawtherapee_pp3.native_sections_to_overrides(native_contract)
        for section, fields in native_overrides.items():
            target = overrides.setdefault(section, {})
            for key, value in fields.items():
                if key in target and target[key] != value:
                    raise IntentValidationError(
                        f"Conflicting RawTherapee overrides for {section}.{key}"
                    )
                target[key] = value
    profile_text = rawtherapee_pp3.compile_profile_text(
        [path for _role, path in profile_inputs],
        overrides=overrides,
        app_version="5.11",
        profile_version=(
            native_contract["profile_version"]
            if native_contract is not None
            else rawtherapee_pp3.RAWTHERAPEE_NATIVE_PROFILE_VERSION
        ),
    )
    executable = lumenflow_config.tool_command(
        local_config,
        "rawtherapee_cli",
        "rawtherapee-cli",
    )
    command = render_raw.build_rawtherapee_command(
        source_path,
        output_path,
        [profile_path],
        executable=executable,
    )
    identity = {
        "intent_id": intent["intent_id"],
        "intent_revision": intent["revision"],
        "authorization": intent["authorization"],
        "backend_id": backend_id,
        "source": intent["source"],
        "preview_basis": intent["preview_basis"],
        "required_capabilities": required_capabilities,
        "profile_path": str(profile_path),
        "profile_sha256": hashlib.sha256(profile_text.encode("utf-8")).hexdigest(),
        "output_path": str(output_path),
        "command_argv": command,
    }
    plan_id = "plan_" + _canonical_hash(identity)[:32]
    return {
        "schema_version": EXECUTION_PLAN_SCHEMA_VERSION,
        "plan_id": plan_id,
        "intent_id": intent["intent_id"],
        "intent_revision": intent["revision"],
        "authorization": intent["authorization"],
        "backend": {
            "id": backend_id,
            "adapter_version": capabilities.adapter_version,
            "capability_contract_version": capabilities.schema_version,
        },
        "source": intent["source"],
        "preview_basis": intent["preview_basis"],
        "output_root": str(output_dir),
        "required_capabilities": required_capabilities,
        "artifacts": {
            "profile": {
                "path": str(profile_path),
                "sha256": identity["profile_sha256"],
            },
            "output": {
                "path": str(output_path),
                "format": "JPEG",
            },
        },
        "operations": [
            {
                "operation_id": f"{plan_id}:profile",
                "kind": "materialize_profile",
                "payload": {
                    "path": str(profile_path),
                    "content": profile_text,
                    "sha256": identity["profile_sha256"],
                },
                "command_argv": [],
            },
            {
                "operation_id": f"{plan_id}:render",
                "kind": "render",
                "payload": {
                    "output_path": str(output_path),
                },
                "command_argv": command,
            },
        ],
        "compiler": {
            "id": "lumenflow.rawtherapee",
            "version": "1",
        },
        "created_at": _now(),
    }


def _resolved_child(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _validate_execution_plan(
    plan: dict[str, Any],
    *,
    allowed_output_dir: Path,
    local_config: dict[str, Any],
) -> None:
    expected_fields = {
        "schema_version",
        "plan_id",
        "intent_id",
        "intent_revision",
        "authorization",
        "backend",
        "source",
        "preview_basis",
        "output_root",
        "required_capabilities",
        "artifacts",
        "operations",
        "compiler",
        "created_at",
        "starting_state",
    }
    unknown = set(plan) - expected_fields
    if unknown:
        raise ExecutionPreconditionError(
            "INVALID_EXECUTION_PLAN",
            "Execution plan contains unknown fields: " + ", ".join(sorted(unknown)),
        )
    if plan.get("schema_version") != EXECUTION_PLAN_SCHEMA_VERSION:
        raise ExecutionPreconditionError(
            "UNSUPPORTED_EXECUTION_PLAN",
            f"Unsupported execution plan schema_version: {plan.get('schema_version')}",
        )
    if not isinstance(plan.get("operations"), list) or not plan["operations"]:
        raise ExecutionPreconditionError("INVALID_EXECUTION_PLAN", "Execution plan has no operations")
    output_root = plan.get("output_root")
    if not isinstance(output_root, str) or Path(output_root).resolve() != allowed_output_dir.resolve():
        raise ExecutionPreconditionError(
            "OUTPUT_ROOT_MISMATCH",
            "Execution plan output_root does not match the explicitly allowed output directory",
        )
    backend_id = plan.get("backend", {}).get("id")
    if backend_id not in {"rawtherapee", "darktable"}:
        raise ExecutionPreconditionError(
            "UNSUPPORTED_EXECUTION_BACKEND",
            "The execution backend is not supported by this executor",
        )
    capabilities = backend_capabilities.backend_capabilities_for(backend_id)
    expected_backend = {
        "id": backend_id,
        "adapter_version": capabilities.adapter_version,
        "capability_contract_version": capabilities.schema_version,
    }
    if plan.get("backend") != expected_backend:
        raise ExecutionPreconditionError(
            "BACKEND_CONTRACT_MISMATCH",
            "Execution plan backend contract does not match the active adapter",
        )
    if not re.fullmatch(r"plan_[0-9a-f]{32}", str(plan.get("plan_id", ""))):
        raise ExecutionPreconditionError("INVALID_EXECUTION_PLAN", "Execution plan id is invalid")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(plan.get("intent_id", ""))):
        raise ExecutionPreconditionError("INVALID_EXECUTION_PLAN", "Intent id is invalid")
    if not isinstance(plan.get("intent_revision"), int) or plan["intent_revision"] < 1:
        raise ExecutionPreconditionError("INVALID_EXECUTION_PLAN", "Intent revision is invalid")
    authorization = plan.get("authorization")
    if (
        not isinstance(authorization, dict)
        or set(authorization) != {"kind", "reference_id"}
        or authorization.get("kind") not in {"user_confirmed_selection", "explicit_user_request"}
        or not str(authorization.get("reference_id", "")).strip()
    ):
        raise ExecutionPreconditionError("INVALID_EXECUTION_PLAN", "Authorization evidence is invalid")
    preview_basis = plan.get("preview_basis")
    if not isinstance(preview_basis, dict) or not {
        "artifact_id",
        "starting_state_hash",
        "state_completeness",
    }.issubset(preview_basis) or set(preview_basis) - {
        "artifact_id",
        "starting_state_hash",
        "state_completeness",
        "state_inputs",
    }:
        raise ExecutionPreconditionError("INVALID_EXECUTION_PLAN", "Preview basis is invalid")
    if not re.fullmatch(r"preview_[0-9a-f]{32}", str(preview_basis.get("artifact_id", ""))):
        raise ExecutionPreconditionError("INVALID_EXECUTION_PLAN", "Preview artifact id is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(preview_basis.get("starting_state_hash", ""))):
        raise ExecutionPreconditionError("INVALID_EXECUTION_PLAN", "Starting-state hash is invalid")
    if preview_basis.get("state_completeness") not in {"complete", "partial"}:
        raise ExecutionPreconditionError("INVALID_EXECUTION_PLAN", "State completeness is invalid")
    state_inputs = preview_basis.get("state_inputs")
    if state_inputs is not None:
        if not isinstance(state_inputs, list):
            raise ExecutionPreconditionError("INVALID_EXECUTION_PLAN", "Preview state inputs are invalid")
        for item in state_inputs:
            if (
                not isinstance(item, dict)
                or set(item) != {"role", "path", "sha256", "size_bytes"}
                or item.get("role") not in {"base_profile", "source_sidecar"}
                or not isinstance(item.get("path"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", "")))
                or not isinstance(item.get("size_bytes"), int)
                or item["size_bytes"] < 0
            ):
                raise ExecutionPreconditionError(
                    "INVALID_EXECUTION_PLAN",
                    "Preview state inputs are invalid",
                )
    required_capabilities = plan.get("required_capabilities")
    allowed_capabilities = {"intent.compile.v2", "render", "composition.crop", "mask.ai"}
    if (
        not isinstance(required_capabilities, list)
        or len(required_capabilities) != len(set(required_capabilities))
        or not {"intent.compile.v2", "render"}.issubset(required_capabilities)
        or not set(required_capabilities).issubset(allowed_capabilities)
    ):
        raise ExecutionPreconditionError(
            "INVALID_EXECUTION_PLAN",
            "Required capabilities are invalid",
        )
    allowed_compilers = {
        "rawtherapee": [{"id": "lumenflow.rawtherapee", "version": "1"}],
        "darktable": [
            {"id": "lumenflow.darktable-xmp-replay", "version": "1"},
            {"id": "lumenflow.darktable-xmp-modules", "version": "2"},
        ],
    }[backend_id]
    if plan.get("compiler") not in allowed_compilers:
        raise ExecutionPreconditionError(
            "COMPILER_CONTRACT_MISMATCH",
            "Execution plan compiler does not match the active compiler contract",
        )
    if backend_id == "darktable" and plan["compiler"]["id"] == "lumenflow.darktable-xmp-modules":
        starting_state = plan.get("starting_state")
        expected_state_fields = {
            "kind",
            "xmp",
            "uses_engine_default",
            "library",
            "write_sidecars",
            "state_inputs",
            "xmp_content",
        }
        if not isinstance(starting_state, dict) or set(starting_state) != expected_state_fields:
            raise ExecutionPreconditionError(
                "INVALID_EXECUTION_PLAN",
                "Dynamic darktable plans must embed their preview-bound XMP state",
            )
        if (
            starting_state.get("kind") != "darktable_xmp"
            or starting_state.get("uses_engine_default") is not False
            or starting_state.get("library") != ":memory:"
            or starting_state.get("write_sidecars") is not False
        ):
            raise ExecutionPreconditionError(
                "INVALID_EXECUTION_PLAN",
                "Embedded darktable starting state is invalid",
            )
        xmp_fingerprint = starting_state.get("xmp")
        if (
            not isinstance(xmp_fingerprint, dict)
            or set(xmp_fingerprint) != {"sha256", "size_bytes"}
            or not re.fullmatch(r"[0-9a-f]{64}", str(xmp_fingerprint.get("sha256", "")))
            or not isinstance(xmp_fingerprint.get("size_bytes"), int)
            or xmp_fingerprint["size_bytes"] < 0
        ):
            raise ExecutionPreconditionError(
                "INVALID_EXECUTION_PLAN",
                "Embedded darktable XMP fingerprint is invalid",
            )
        state_inputs = starting_state.get("state_inputs")
        if not isinstance(state_inputs, list) or len(state_inputs) != 1:
            raise ExecutionPreconditionError(
                "INVALID_EXECUTION_PLAN",
                "Embedded darktable state_inputs must contain exactly one input",
            )
        state_input = state_inputs[0]
        if (
            not isinstance(state_input, dict)
            or set(state_input) != {"role", "path", "sha256", "size_bytes"}
            or state_input.get("role") not in DARKTABLE_STATE_INPUT_ROLES
            or not str(state_input.get("path", "")).strip()
            or state_input.get("sha256") != xmp_fingerprint["sha256"]
            or state_input.get("size_bytes") != xmp_fingerprint["size_bytes"]
        ):
            raise ExecutionPreconditionError(
                "INVALID_EXECUTION_PLAN",
                "Embedded darktable state input is invalid",
            )
        xmp_content = starting_state.get("xmp_content")
        if not isinstance(xmp_content, str) or len(xmp_content.encode("utf-8")) > 1048576:
            raise ExecutionPreconditionError(
                "INVALID_EXECUTION_PLAN",
                "Embedded darktable XMP content is invalid",
            )
        xmp_bytes = xmp_content.encode("utf-8")
        if (
            len(xmp_bytes) != xmp_fingerprint["size_bytes"]
            or hashlib.sha256(xmp_bytes).hexdigest() != xmp_fingerprint["sha256"]
        ):
            raise ExecutionPreconditionError(
                "PROFILE_INTEGRITY_MISMATCH",
                "Embedded darktable XMP content does not match its fingerprint",
            )
        try:
            darktable_codec.validate_xmp(xmp_content)
        except darktable_codec.DarktableCodecError as error:
            raise ExecutionPreconditionError(
                "INVALID_EXECUTION_PLAN",
                "Embedded darktable XMP content is not a valid 5.4.1 document",
            ) from error
        expected_state_hash = preview_provider.canonical_hash(
            {
                "kind": "darktable_xmp",
                "xmp": xmp_fingerprint,
                "uses_engine_default": False,
                "library": ":memory:",
                "write_sidecars": False,
            }
        )
        if (
            preview_basis["state_completeness"] != "complete"
            or preview_basis["starting_state_hash"] != expected_state_hash
        ):
            raise ExecutionPreconditionError(
                "STARTING_STATE_MISMATCH",
                "The embedded darktable XMP state does not match the preview basis",
            )

    source = plan.get("source")
    if not isinstance(source, dict) or set(source) != {"path", "fingerprint"}:
        raise ExecutionPreconditionError("INVALID_EXECUTION_PLAN", "Execution plan source is invalid")
    fingerprint = source.get("fingerprint")
    if not isinstance(fingerprint, dict) or set(fingerprint) != {"sha256", "size_bytes"}:
        raise ExecutionPreconditionError(
            "INVALID_EXECUTION_PLAN",
            "Execution plan source fingerprint is invalid",
        )
    if (
        not re.fullmatch(r"[0-9a-f]{64}", str(fingerprint.get("sha256", "")))
        or not isinstance(fingerprint.get("size_bytes"), int)
        or fingerprint["size_bytes"] < 0
    ):
        raise ExecutionPreconditionError(
            "INVALID_EXECUTION_PLAN",
            "Execution plan source fingerprint values are invalid",
        )
    if Path(source["path"]).suffix.lower() not in scan_raws.RAW_EXTENSIONS:
        raise ExecutionPreconditionError(
            "INVALID_EXECUTION_PLAN",
            "Execution plan source must use a supported RAW extension",
        )

    artifacts = plan.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"profile", "output"}:
        raise ExecutionPreconditionError("INVALID_EXECUTION_PLAN", "Execution plan artifacts are invalid")
    profile = artifacts["profile"]
    output = artifacts["output"]
    if not isinstance(profile, dict) or set(profile) != {"path", "sha256"}:
        raise ExecutionPreconditionError("INVALID_EXECUTION_PLAN", "Profile artifact is invalid")
    if not isinstance(output, dict) or set(output) != {"path", "format"} or output.get("format") != "JPEG":
        raise ExecutionPreconditionError("INVALID_EXECUTION_PLAN", "Output artifact is invalid")
    profile_path = Path(profile["path"])
    output_path = Path(output["path"])
    if not _resolved_child(profile_path, allowed_output_dir) or not _resolved_child(
        output_path,
        allowed_output_dir,
    ):
        raise ExecutionPreconditionError(
            "OUTPUT_PATH_OUTSIDE_ALLOWED_ROOT",
            "Execution artifacts must remain inside the explicitly allowed output directory",
        )
    if profile_path.resolve() == Path(source["path"]).resolve() or output_path.resolve() == Path(
        source["path"]
    ).resolve():
        raise ExecutionPreconditionError(
            "SOURCE_OVERWRITE_FORBIDDEN",
            "Execution artifacts cannot target the source RAW path",
        )

    operations = plan["operations"]
    if len(operations) != 2:
        raise ExecutionPreconditionError(
            "INVALID_EXECUTION_PLAN",
            "Execution plans must contain exactly two operations",
        )
    profile_operation, render_operation = operations
    expected_operation_fields = {"operation_id", "kind", "payload", "command_argv"}
    if set(profile_operation) != expected_operation_fields or set(render_operation) != expected_operation_fields:
        raise ExecutionPreconditionError(
            "INVALID_EXECUTION_PLAN",
            "Execution operation fields do not match the v1 contract",
        )
    if (
        profile_operation["operation_id"] != f"{plan['plan_id']}:profile"
        or profile_operation["kind"] != "materialize_profile"
    ):
        raise ExecutionPreconditionError("INVALID_EXECUTION_PLAN", "Profile operation identity is invalid")
    if render_operation["operation_id"] != f"{plan['plan_id']}:render" or render_operation["kind"] != "render":
        raise ExecutionPreconditionError("INVALID_EXECUTION_PLAN", "Render operation identity is invalid")
    profile_payload = profile_operation["payload"]
    if not isinstance(profile_payload, dict) or set(profile_payload) != {"path", "content", "sha256"}:
        raise ExecutionPreconditionError("INVALID_EXECUTION_PLAN", "Profile payload is invalid")
    if not isinstance(profile_payload["content"], str) or len(profile_payload["content"].encode("utf-8")) > 1048576:
        raise ExecutionPreconditionError("INVALID_EXECUTION_PLAN", "Profile content is invalid")
    content_hash = hashlib.sha256(profile_payload["content"].encode("utf-8")).hexdigest()
    if (
        profile_payload["path"] != profile["path"]
        or profile_payload["sha256"] != profile["sha256"]
        or content_hash != profile["sha256"]
        or profile_operation["command_argv"] != []
    ):
        raise ExecutionPreconditionError(
            "PROFILE_INTEGRITY_MISMATCH",
            "Profile operation does not match the declared profile artifact",
        )
    if render_operation["payload"] != {"output_path": output["path"]}:
        raise ExecutionPreconditionError(
            "INVALID_EXECUTION_PLAN",
            "Render payload does not match the declared output artifact",
        )
    if backend_id == "rawtherapee":
        executable = lumenflow_config.tool_command(local_config, "rawtherapee_cli", "rawtherapee-cli")
        expected_command = render_raw.build_rawtherapee_command(
            Path(source["path"]),
            output_path,
            [profile_path],
            executable=executable,
        )
    else:
        if plan["compiler"]["id"] == "lumenflow.darktable-xmp-modules":
            embedded_state = plan["starting_state"]
            expected_state_hash = preview_provider.canonical_hash(
                {
                    "kind": embedded_state["kind"],
                    "xmp": embedded_state["xmp"],
                    "uses_engine_default": embedded_state["uses_engine_default"],
                    "library": embedded_state["library"],
                    "write_sidecars": embedded_state["write_sidecars"],
                }
            )
        else:
            fingerprint = {
                "sha256": profile["sha256"],
                "size_bytes": len(profile_payload["content"].encode("utf-8")),
            }
            expected_state_hash = preview_provider.canonical_hash(
                {
                    "kind": "darktable_xmp",
                    "xmp": fingerprint,
                    "uses_engine_default": False,
                    "library": ":memory:",
                    "write_sidecars": False,
                }
            )
        if (
            preview_basis["state_completeness"] != "complete"
            or preview_basis["starting_state_hash"] != expected_state_hash
        ):
            raise ExecutionPreconditionError(
                "STARTING_STATE_MISMATCH",
                "The materialized darktable XMP does not match the preview basis",
            )
        runtime_key = _canonical_hash(
            {
                "source": source,
                "preview_basis": preview_basis,
                "intent_id": plan["intent_id"],
                "revision": plan["intent_revision"],
            }
        )[:24]
        runtime_root = allowed_output_dir / ".darktable-runtime" / runtime_key
        executable = lumenflow_config.tool_command(local_config, "darktable_cli", "darktable-cli")
        expected_command = render_raw.build_darktable_command(
            Path(source["path"]),
            output_path,
            xmp=profile_path,
            configdir=runtime_root / "config",
            cachedir=runtime_root / "cache",
            library=":memory:",
            write_sidecars=False,
            executable=executable,
        )
    if render_operation["command_argv"] != expected_command:
        raise ExecutionPreconditionError(
            "PLAN_COMMAND_MISMATCH",
            "Render command does not match the validated source, artifacts, and configured executable",
        )


def _assert_no_output_conflicts(plan: dict[str, Any]) -> None:
    profile = plan["artifacts"]["profile"]
    profile_path = Path(profile["path"])
    if profile_path.exists():
        existing_hash = hashlib.sha256(profile_path.read_bytes()).hexdigest()
        if existing_hash != profile["sha256"]:
            raise ExecutionPreconditionError(
                "PROFILE_CONFLICT",
                f"Existing profile differs from the execution plan: {profile_path}",
            )
    output_path = Path(plan["artifacts"]["output"]["path"])
    if output_path.exists():
        raise ExecutionPreconditionError(
            "OUTPUT_ALREADY_EXISTS",
            f"Refusing to overwrite an existing render: {output_path}",
        )


def execute_plan(
    plan: dict[str, Any],
    *,
    dry_run: bool,
    timeout: int | None,
    runner: CommandRunner = render_raw.run_command,
    allowed_output_dir: Path,
    local_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    local_config = local_config or {}
    try:
        _validate_execution_plan(
            plan,
            allowed_output_dir=allowed_output_dir,
            local_config=local_config,
        )
    except ExecutionPreconditionError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise ExecutionPreconditionError(
            "INVALID_EXECUTION_PLAN",
            "Execution plan structure is invalid",
        ) from error
    capabilities = backend_capabilities.backend_capabilities_for(plan["backend"]["id"])
    capabilities_to_require = (
        [capability for capability in plan["required_capabilities"] if capability != "render"]
        if dry_run
        else plan["required_capabilities"]
    )
    for capability in capabilities_to_require:
        capabilities.require(capability)

    source_path = Path(plan["source"]["path"])
    source_before = preview_provider.file_fingerprint(source_path)
    if source_before != plan["source"]["fingerprint"]:
        raise ExecutionPreconditionError(
            "SOURCE_FINGERPRINT_MISMATCH",
            "The source bytes no longer match the execution plan",
        )
    _assert_no_output_conflicts(plan)

    started_at = _now()
    operation_receipts: list[dict[str, Any]] = []
    failure_reason = ""
    status = "dry_run" if dry_run else "pending"
    output_fingerprint = None

    if dry_run:
        operation_receipts = [
            {
                "operation_id": operation["operation_id"],
                "kind": operation["kind"],
                "status": "dry_run",
                "error": "",
            }
            for operation in plan["operations"]
        ]
    else:
        try:
            for operation in plan["operations"]:
                if operation["kind"] == "materialize_profile":
                    path = Path(operation["payload"]["path"])
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(operation["payload"]["content"], encoding="utf-8")
                elif operation["kind"] == "render":
                    if plan["backend"]["id"] == "darktable":
                        command = operation["command_argv"]
                        for flag in ("--configdir", "--cachedir"):
                            Path(command[command.index(flag) + 1]).mkdir(parents=True, exist_ok=True)
                    runner(operation["command_argv"], dry_run=False, timeout=timeout)
                else:
                    raise RuntimeError(f"Unsupported execution operation: {operation['kind']}")
                operation_receipts.append(
                    {
                        "operation_id": operation["operation_id"],
                        "kind": operation["kind"],
                        "status": "success",
                        "error": "",
                    }
                )

            output_path = Path(plan["artifacts"]["output"]["path"])
            if not output_path.exists():
                raise RuntimeError(f"Render command did not create output: {output_path}")
            output_fingerprint = preview_provider.file_fingerprint(output_path)
            status = "success"
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            status = "failed"
            failure_reason = str(error)
            completed_ids = {item["operation_id"] for item in operation_receipts}
            failure_recorded = False
            for operation in plan["operations"]:
                if operation["operation_id"] in completed_ids:
                    continue
                operation_receipts.append(
                    {
                        "operation_id": operation["operation_id"],
                        "kind": operation["kind"],
                        "status": "failed" if not failure_recorded else "skipped",
                        "error": failure_reason,
                    }
                )
                failure_recorded = True

    source_after = preview_provider.file_fingerprint(source_path)
    source_unchanged = source_before == source_after
    if not source_unchanged:
        status = "failed"
        failure_reason = "Source RAW changed during execution"

    completed_at = _now()
    receipt_id = "receipt_" + uuid.uuid4().hex
    return {
        "schema_version": EXECUTION_RECEIPT_SCHEMA_VERSION,
        "receipt_id": receipt_id,
        "plan_id": plan["plan_id"],
        "intent_id": plan["intent_id"],
        "backend_id": plan["backend"]["id"],
        "status": status,
        "operations": operation_receipts,
        "source_fingerprint_before": source_before,
        "source_fingerprint_after": source_after,
        "source_unchanged": source_unchanged,
        "output_fingerprint": output_fingerprint,
        "failure_reason": failure_reason,
        "started_at": started_at,
        "completed_at": completed_at,
    }


def _read_json(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError(f"JSON contract file is too large: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile and execute Lumenflow EditIntent v2.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compile_parser = subparsers.add_parser("compile")
    compile_parser.add_argument("intent", type=Path)
    compile_parser.add_argument("--backend", choices=["rawtherapee", "darktable", "lightroom"], required=True)
    compile_parser.add_argument("--output-dir", type=Path, required=True)
    compile_parser.add_argument("--plan-output", type=Path, required=True)
    compile_parser.add_argument("--local-config", type=Path, default=lumenflow_config.DEFAULT_LOCAL_CONFIG_PATH)

    execute_parser = subparsers.add_parser("execute")
    execute_parser.add_argument("plan", type=Path)
    execute_parser.add_argument("--receipt-output", type=Path, required=True)
    execute_parser.add_argument("--allowed-output-dir", type=Path, required=True)
    execute_parser.add_argument("--dry-run", action="store_true")
    execute_parser.add_argument("--timeout", type=int, default=300)
    execute_parser.add_argument("--local-config", type=Path, default=lumenflow_config.DEFAULT_LOCAL_CONFIG_PATH)

    args = parser.parse_args()
    if args.command == "compile":
        plan = compile_intent(
            _read_json(args.intent),
            backend_id=args.backend,
            output_dir=args.output_dir,
            local_config=lumenflow_config.read_local_config(args.local_config),
        )
        _write_json(args.plan_output, plan)
        print(json.dumps({"plan_id": plan["plan_id"], "plan": str(args.plan_output)}, indent=2))
        return

    receipt = execute_plan(
        _read_json(args.plan),
        dry_run=args.dry_run,
        timeout=args.timeout,
        allowed_output_dir=args.allowed_output_dir,
        local_config=lumenflow_config.read_local_config(args.local_config),
    )
    _write_json(args.receipt_output, receipt)
    print(json.dumps({"receipt_id": receipt["receipt_id"], "status": receipt["status"]}, indent=2))


if __name__ == "__main__":
    main()
