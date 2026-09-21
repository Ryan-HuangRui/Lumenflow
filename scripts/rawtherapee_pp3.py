#!/usr/bin/env python3
"""Versioned RawTherapee PP3 parsing, merging, and compilation helpers.

RawTherapee's command line interface is intentionally profile driven.  A PP3
is not a small set of command line switches: it is the serialized state of
the processing pipeline.  This module keeps the profile handling in one place
so callers can safely compose a starting profile stack with agent-authored
overrides without accidentally dropping fields from newer RawTherapee
versions.

The parser deliberately does not maintain an allow-list of RawTherapee keys.
Unknown sections and keys are retained when profiles are merged.  We only
validate the PP3 container syntax and reject malformed input; unsupported
semantic edits must be rejected by the caller before they reach this module.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


PP3_COMPILER_VERSION = "lumenflow.rawtherapee-pp3.v2"
PP3_ENGINE_VERSION = "5.11"
MAX_PROFILE_BYTES = 1024 * 1024


class PP3Error(ValueError):
    """Base class for fail-closed PP3 errors."""


class PP3ParseError(PP3Error):
    """Raised when a profile is not a valid, bounded PP3 document."""


class PP3UnsupportedValue(PP3Error):
    """Raised when an agent value cannot be represented safely in a PP3."""


_SECTION_RE = re.compile(r"^\[([^\]\r\n]+)\]$")


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PP3UnsupportedValue("PP3 numeric values must be finite")
        return f"{value:.8f}".rstrip("0").rstrip(".") or "0"
    if isinstance(value, str):
        if "\n" in value or "\r" in value or "\x00" in value:
            raise PP3UnsupportedValue("PP3 string values may not contain line breaks or NULs")
        return value
    raise PP3UnsupportedValue(f"Unsupported PP3 value type: {type(value).__name__}")


@dataclass
class PP3Document:
    """An ordered PP3 document preserving every parsed field.

    The mapping stores all keys, including sections introduced by a newer
    RawTherapee release.  ``set`` replaces only the requested field and
    ``merge`` overlays later documents without discarding unrelated fields.
    Comments and blank lines are intentionally normalized on serialization;
    the processing state itself is preserved exactly.
    """

    sections: OrderedDict[str, OrderedDict[str, str]]

    @classmethod
    def empty(cls) -> "PP3Document":
        return cls(OrderedDict())

    @classmethod
    def parse(cls, text: str, *, source: str = "<memory>") -> "PP3Document":
        if not isinstance(text, str):
            raise PP3ParseError(f"PP3 input must be text: {source}")
        encoded = text.encode("utf-8")
        if len(encoded) > MAX_PROFILE_BYTES:
            raise PP3ParseError(f"PP3 profile exceeds {MAX_PROFILE_BYTES} bytes: {source}")
        if "\x00" in text:
            raise PP3ParseError(f"PP3 profile contains NUL bytes: {source}")

        sections: OrderedDict[str, OrderedDict[str, str]] = OrderedDict()
        current: OrderedDict[str, str] | None = None
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            section_match = _SECTION_RE.fullmatch(line)
            if section_match:
                name = section_match.group(1).strip()
                if not name:
                    raise PP3ParseError(f"Empty PP3 section at {source}:{line_number}")
                current = sections.setdefault(name, OrderedDict())
                continue
            if current is None:
                raise PP3ParseError(
                    f"PP3 field appears before a section at {source}:{line_number}"
                )
            if "=" not in line:
                raise PP3ParseError(f"Malformed PP3 field at {source}:{line_number}")
            key, value = line.split("=", 1)
            key = key.strip()
            if not key or "[" in key or "]" in key or "\n" in value or "\r" in value:
                raise PP3ParseError(f"Malformed PP3 field at {source}:{line_number}")
            # RawTherapee treats the last occurrence as authoritative.  Keep
            # the original insertion position while replacing its value.
            current[key] = value
        return cls(sections)

    @classmethod
    def read(cls, path: Path) -> "PP3Document":
        if not path.is_file() or path.is_symlink():
            raise PP3ParseError(f"PP3 profile is not a regular file: {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise PP3ParseError(f"PP3 profile must be UTF-8: {path}") from error
        return cls.parse(text, source=str(path))

    def copy(self) -> "PP3Document":
        return PP3Document(
            OrderedDict(
                (section, OrderedDict(fields)) for section, fields in self.sections.items()
            )
        )

    def set(self, section: str, key: str, value: Any) -> None:
        if not isinstance(section, str) or not section.strip() or "\n" in section or "\r" in section:
            raise PP3UnsupportedValue("PP3 section names must be non-empty single-line strings")
        if not isinstance(key, str) or not key.strip() or "=" in key or "\n" in key or "\r" in key:
            raise PP3UnsupportedValue("PP3 field names must be non-empty single-line strings")
        fields = self.sections.setdefault(section.strip(), OrderedDict())
        fields[key.strip()] = _format_value(value)

    def get(self, section: str, key: str, default: str | None = None) -> str | None:
        return self.sections.get(section, {}).get(key, default)

    def merge(self, other: "PP3Document") -> "PP3Document":
        merged = self.copy()
        for section, fields in other.sections.items():
            target = merged.sections.setdefault(section, OrderedDict())
            target.update(fields)
        return merged

    def to_text(self) -> str:
        chunks: list[str] = []
        for section, fields in self.sections.items():
            chunks.append(f"[{section}]")
            chunks.extend(f"{key}={value}" for key, value in fields.items())
            chunks.append("")
        return "\n".join(chunks)

    def write(self, path: Path) -> str:
        text = self.to_text()
        encoded = text.encode("utf-8")
        if len(encoded) > MAX_PROFILE_BYTES:
            raise PP3Error(f"Compiled PP3 profile exceeds {MAX_PROFILE_BYTES} bytes: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return text


def merge_profiles(
    profiles: Iterable[Path | PP3Document],
    *,
    overrides: Mapping[str, Mapping[str, Any]] | PP3Document | None = None,
) -> PP3Document:
    """Merge profiles in RawTherapee CLI order and apply final overrides.

    A later profile wins only for fields it contains.  This matches the
    documented ``rawtherapee-cli -p first.pp3 -p second.pp3`` behavior while
    retaining all unrelated/unknown fields from the earlier profile.
    """

    merged = PP3Document.empty()
    for profile in profiles:
        document = profile if isinstance(profile, PP3Document) else PP3Document.read(Path(profile))
        merged = merged.merge(document)
    if overrides is not None:
        if isinstance(overrides, PP3Document):
            merged = merged.merge(overrides)
        else:
            override_document = PP3Document.empty()
            for section, fields in overrides.items():
                if not isinstance(fields, Mapping):
                    raise PP3UnsupportedValue(f"PP3 section overrides must be mappings: {section}")
                for key, value in fields.items():
                    override_document.set(str(section), str(key), value)
            merged = merged.merge(override_document)
    return merged


def compile_profile_text(
    profiles: Iterable[Path | PP3Document] = (),
    *,
    overrides: Mapping[str, Mapping[str, Any]] | PP3Document | None = None,
    app_version: str = PP3_ENGINE_VERSION,
    profile_version: int = 349,
) -> str:
    """Compile a bounded PP3 with a version marker and preserved state."""

    version = PP3Document.empty()
    version.set("Version", "AppVersion", app_version)
    version.set("Version", "Version", profile_version)
    merged = merge_profiles(profiles, overrides=overrides)
    # The explicit compiler marker is useful for receipts and is harmless to
    # RawTherapee because unknown sections/keys are ignored by the engine.
    marker = PP3Document.empty()
    marker.set("Lumenflow", "Compiler", PP3_COMPILER_VERSION)
    return version.merge(merged).merge(marker).to_text()


def profile_stack_state(
    inputs: Iterable[tuple[str, Path]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return the canonical state record used by preview/execute contracts."""

    profile_stack: list[dict[str, Any]] = []
    state_inputs: list[dict[str, Any]] = []
    for role, path in inputs:
        fingerprint = file_fingerprint(path)
        profile_stack.append({"role": role, **fingerprint})
        state_inputs.append({"role": role, "path": str(path), **fingerprint})
    starting_state = {
        "kind": "rawtherapee_profile_stack",
        "profile_stack": profile_stack,
        "uses_engine_default": not profile_stack,
    }
    return starting_state, state_inputs


def file_fingerprint(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise PP3Error(f"PP3 state input is not a regular file: {path}")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return {"sha256": digest.hexdigest(), "size_bytes": size}


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def semantic_overrides(
    adjustments: Mapping[str, Any],
    *,
    composition: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Map the currently supported vendor-neutral fields into PP3 sections.

    This function intentionally maps only fields whose 5.11 serialization is
    known.  Callers must reject other semantic fields rather than guessing a
    PP3 key.  Full module-specific profile dictionaries can still be supplied
    through :func:`compile_profile_text` once their fixtures are validated.
    """

    mapping = {
        "exposure_compensation": ("Exposure", "Compensation"),
        "brightness": ("Exposure", "Brightness"),
        "contrast": ("Exposure", "Contrast"),
        "saturation": ("Exposure", "Saturation"),
        "black": ("Exposure", "Black"),
        "highlight_compression": ("Exposure", "HighlightCompr"),
        "shadow_compression": ("Exposure", "ShadowCompr"),
        "temperature": ("White Balance", "Temperature"),
        "green": ("White Balance", "Green"),
    }
    unsupported = set(adjustments) - set(mapping) - {"notes", "rawtherapee_native"}
    if unsupported:
        raise PP3UnsupportedValue(
            "RawTherapee semantic fields are not mapped: " + ", ".join(sorted(unsupported))
        )

    sections: dict[str, dict[str, Any]] = {}
    for source_key, (section, target_key) in mapping.items():
        if source_key in adjustments and adjustments[source_key] is not None:
            sections.setdefault(section, {})[target_key] = adjustments[source_key]
    if sections.get("Exposure"):
        sections["Exposure"].setdefault("Enabled", "true")
    if "White Balance" in sections:
        sections["White Balance"].setdefault("Enabled", "true")
        sections["White Balance"].setdefault("Setting", "Custom")

    if composition:
        crop = composition.get("crop")
        if composition.get("decision") == "crop":
            if not isinstance(crop, Mapping) or crop.get("unit", "pixels") != "pixels":
                raise PP3UnsupportedValue("RawTherapee crop requires pixel coordinates")
            required = ("x", "y", "width", "height")
            if any(key not in crop for key in required):
                raise PP3UnsupportedValue("RawTherapee crop is missing coordinates")
            sections["Crop"] = {
                "Enabled": "true",
                "X": crop["x"],
                "Y": crop["y"],
                "W": crop["width"],
                "H": crop["height"],
            }
            for key in ("fixed_ratio", "ratio"):
                if key in crop:
                    sections["Crop"][{"fixed_ratio": "FixedRatio", "ratio": "Ratio"}[key]] = crop[key]
    if "notes" in adjustments and adjustments["notes"]:
        sections.setdefault("Lumenflow", {})["Notes"] = str(adjustments["notes"]).replace("\n", " ")
    native = adjustments.get("rawtherapee_native")
    if native is not None:
        if not isinstance(native, Mapping):
            raise PP3UnsupportedValue("rawtherapee_native must be an object of PP3 sections")
        for section, fields in native.items():
            if not isinstance(fields, Mapping):
                raise PP3UnsupportedValue(
                    f"rawtherapee_native section must be an object: {section}"
                )
            if not str(section).strip():
                raise PP3UnsupportedValue("rawtherapee_native section names may not be empty")
            target = sections.setdefault(str(section), {})
            for key, value in fields.items():
                # RawTherapee serializes a few curves as opaque semicolon
                # strings.  Preserve those values, but reject structures and
                # non-finite numbers that cannot be represented in PP3.
                target[str(key)] = _format_value(value)
    return sections


def discover_source_sidecar(source: Path) -> Path | None:
    candidate = source.with_name(source.name + ".pp3")
    return candidate if candidate.is_file() and not candidate.is_symlink() else None
