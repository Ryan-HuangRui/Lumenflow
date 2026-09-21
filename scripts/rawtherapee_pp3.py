#!/usr/bin/env python3
"""Versioned RawTherapee PP3 parsing, merging, and compilation helpers.

RawTherapee's command line interface is intentionally profile driven.  A PP3
is not a small set of command line switches: it is the serialized state of
the processing pipeline.  This module keeps the profile handling in one place
so callers can safely compose a starting profile stack with agent-authored
overrides without accidentally dropping fields from newer RawTherapee
versions.

The parser deliberately does not maintain an allow-list of imported
RawTherapee keys: unknown sections and keys are retained when profiles are
merged.  Agent-authored native edits take a separate bounded path through
``validate_native_sections`` and ``RAWTHERAPEE_NATIVE_FIELD_SPECS``; unknown
sections and fields on that path fail closed.
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


PP3_COMPILER_VERSION = "lumenflow.rawtherapee-pp3.v3"
PP3_ENGINE_VERSION = "5.11"
RAWTHERAPEE_NATIVE_PROFILE_VERSION = 349
RAWTHERAPEE_NATIVE_SCHEMA_VERSION = "lumenflow.rawtherapee-native.v1"
MAX_PROFILE_BYTES = 1024 * 1024


class PP3Error(ValueError):
    """Base class for fail-closed PP3 errors."""


class PP3ParseError(PP3Error):
    """Raised when a profile is not a valid, bounded PP3 document."""


class PP3UnsupportedValue(PP3Error):
    """Raised when an agent value cannot be represented safely in a PP3."""


@dataclass(frozen=True)
class NativeFieldSpec:
    """Bounded type/range declaration for an agent-authored 5.11 PP3 field."""

    kind: str
    minimum: float | int | None = None
    maximum: float | int | None = None
    choices: tuple[str, ...] = ()


def _native_bool() -> NativeFieldSpec:
    return NativeFieldSpec("bool")


def _native_int(minimum: int, maximum: int) -> NativeFieldSpec:
    return NativeFieldSpec("int", minimum, maximum)


def _native_float(minimum: float, maximum: float) -> NativeFieldSpec:
    return NativeFieldSpec("float", minimum, maximum)


def _native_enum(*choices: str) -> NativeFieldSpec:
    return NativeFieldSpec("enum", choices=tuple(choices))


def _native_int_enum(*choices: int) -> NativeFieldSpec:
    return NativeFieldSpec("int_enum", choices=tuple(str(choice) for choice in choices))


def _native_curve() -> NativeFieldSpec:
    return NativeFieldSpec("curve")


# These are the only native fields an EditIntent may author.  Every entry is
# backed by RawTherapee 5.11 serialization/source inspection and the live
# fixture test in tests/test_rawtherapee_native_live.py.  Unknown sections and
# keys are deliberately rejected instead of being passed through as an opaque
# agent escape hatch.
RAWTHERAPEE_NATIVE_FIELD_SPECS: dict[str, dict[str, NativeFieldSpec]] = {
    "RAW": {
        "CA": _native_bool(),
        "CAAvoidColourshift": _native_bool(),
        "CAAutoIterations": _native_int(0, 20),
        "CARed": _native_float(-100.0, 100.0),
        "CABlue": _native_float(-100.0, 100.0),
        "HotPixelFilter": _native_bool(),
        "DeadPixelFilter": _native_bool(),
        "HotDeadPixelThresh": _native_int(0, 10000),
        "PreExposure": _native_float(0.0, 10.0),
    },
    "RAW Bayer": {
        "Method": _native_enum(
            "amaze",
            "ahd",
            "eahd",
            "hphd",
            "dcb",
            "lmmse",
            "igv",
            "vng4",
            "rcd",
            "pixelshift",
        ),
        "Border": _native_int(0, 64),
        "DCBIterations": _native_int(0, 10),
        "DCBEnhance": _native_bool(),
        "LMMSEIterations": _native_int(0, 10),
        "DualDemosaicAutoContrast": _native_bool(),
        "DualDemosaicContrast": _native_float(-100.0, 100.0),
    },
    "HLRecovery": {
        "Enabled": _native_bool(),
        "Method": _native_enum("Coloropp", "Luminance", "Inpaint", "Inpaint opposed"),
        "Hlbl": _native_float(0.0, 100.0),
        "Hlth": _native_float(0.0, 100.0),
    },
    "Exposure": {
        "Compensation": _native_float(-5.0, 5.0),
        "Brightness": _native_float(-100.0, 100.0),
        "Contrast": _native_float(-100.0, 100.0),
        "Saturation": _native_float(-100.0, 100.0),
        "Black": _native_float(-1000.0, 1000.0),
        "HighlightCompr": _native_float(0.0, 100.0),
        "HighlightComprThreshold": _native_float(0.0, 100.0),
        "ShadowCompr": _native_float(-100.0, 100.0),
        "CurveMode": _native_enum(
            "Standard",
            "FilmLike",
            "SatAndValueBlending",
            "WeightedStd",
            "Luminance",
            "Perceptual",
        ),
        "CurveMode2": _native_enum(
            "Standard",
            "FilmLike",
            "SatAndValueBlending",
            "WeightedStd",
            "Luminance",
            "Perceptual",
        ),
        "Curve": _native_curve(),
        "Curve2": _native_curve(),
        "Auto": _native_bool(),
        "HistogramMatching": _native_bool(),
        "ClampOOG": _native_bool(),
    },
    "White Balance": {
        "Enabled": _native_bool(),
        "Setting": _native_enum("Camera", "Auto", "Custom"),
        "Temperature": _native_float(1000.0, 50000.0),
        "Green": _native_float(0.0, 5.0),
        "TemperatureBias": _native_float(-100.0, 100.0),
    },
    "Color appearance": {
        "Enabled": _native_bool(),
        "Degree": _native_float(0.0, 360.0),
        "AutoDegree": _native_bool(),
        "Degreeout": _native_float(0.0, 360.0),
        "AutoDegreeout": _native_bool(),
        "AdaptLum": _native_float(0.0, 100.0),
        "Badpixsl": _native_float(0.0, 100.0),
        "J-Light": _native_float(-100.0, 100.0),
        "Q-Bright": _native_float(-100.0, 100.0),
        "C-Chroma": _native_float(-100.0, 100.0),
        "S-Chroma": _native_float(-100.0, 100.0),
        "M-Chroma": _native_float(-100.0, 100.0),
        "J-Contrast": _native_float(-100.0, 100.0),
        "Q-Contrast": _native_float(-100.0, 100.0),
        "H-Hue": _native_float(-100.0, 100.0),
        "RSTProtection": _native_float(0.0, 100.0),
        "AdaptScene": _native_float(0.0, 10000.0),
        "AutoAdapscen": _native_bool(),
        "YbScene": _native_float(0.0, 100.0),
        "Autoybscen": _native_bool(),
        "Gamut": _native_bool(),
    },
    "Directional Pyramid Denoising": {
        "Enabled": _native_bool(),
        "Enhance": _native_bool(),
        "Median": _native_bool(),
        "Luma": _native_float(0.0, 100.0),
        "Ldetail": _native_float(0.0, 100.0),
        "Chroma": _native_float(0.0, 100.0),
        "AutoGain": _native_bool(),
        "Gamma": _native_float(0.1, 10.0),
        "Passes": _native_int(1, 5),
    },
    "Vibrance": {
        "Enabled": _native_bool(),
        "Pastels": _native_float(-100.0, 100.0),
        "Saturated": _native_float(-100.0, 100.0),
        "ProtectSkins": _native_bool(),
        "AvoidColorShift": _native_bool(),
        "PastSatTog": _native_bool(),
    },
    "Shadows & Highlights": {
        "Enabled": _native_bool(),
        "Highlights": _native_float(-100.0, 100.0),
        "HighlightTonalWidth": _native_float(0.0, 100.0),
        "Shadows": _native_float(-100.0, 100.0),
        "ShadowTonalWidth": _native_float(0.0, 100.0),
        "Radius": _native_float(0.0, 100.0),
        "Lab": _native_bool(),
    },
    "Sharpening": {
        "Enabled": _native_bool(),
        "Contrast": _native_float(0.0, 100.0),
        "Method": _native_enum("usm", "rl", "deconv"),
        "Radius": _native_float(0.0, 10.0),
        "BlurRadius": _native_float(0.0, 10.0),
        "Amount": _native_float(0.0, 1000.0),
        "OnlyEdges": _native_bool(),
        "EdgedetectionRadius": _native_float(0.0, 20.0),
        "EdgeTolerance": _native_float(0.0, 10000.0),
        "HalocontrolEnabled": _native_bool(),
        "HalocontrolAmount": _native_float(0.0, 100.0),
        "DeconvRadius": _native_float(0.0, 10.0),
        "DeconvAmount": _native_float(0.0, 1000.0),
        "DeconvDamping": _native_float(0.0, 100.0),
        "DeconvIterations": _native_int(0, 100),
    },
    "SharpenEdge": {
        "Enabled": _native_bool(),
        "Passes": _native_int(1, 10),
        "Strength": _native_float(0.0, 100.0),
        "ThreeChannels": _native_bool(),
    },
    "SharpenMicro": {
        "Enabled": _native_bool(),
        "Matrix": _native_bool(),
        "Strength": _native_float(0.0, 100.0),
        "Contrast": _native_float(0.0, 100.0),
        "Uniformity": _native_float(0.0, 10.0),
    },
    "PostDemosaicSharpening": {
        "Enabled": _native_bool(),
        "Contrast": _native_float(0.0, 100.0),
        "AutoContrast": _native_bool(),
        "AutoRadius": _native_bool(),
        "DeconvRadius": _native_float(0.0, 10.0),
        "DeconvRadiusOffset": _native_float(-10.0, 10.0),
        "DeconvIterCheck": _native_bool(),
        "DeconvIterations": _native_int(0, 100),
    },
    "LensProfile": {
        "LcMode": _native_enum("none", "lfauto", "lfmanual", "lcp", "metadata"),
        "UseDistortion": _native_bool(),
        "UseVignette": _native_bool(),
        "UseCA": _native_bool(),
    },
    "Distortion": {"Amount": _native_float(-100.0, 100.0)},
    "CACorrection": {
        "Red": _native_float(-100.0, 100.0),
        "Blue": _native_float(-100.0, 100.0),
    },
    "Rotation": {"Degree": _native_float(-180.0, 180.0)},
    "Perspective": {
        "Method": _native_enum("simple", "camera_based", "control_lines"),
        "Horizontal": _native_float(-100.0, 100.0),
        "Vertical": _native_float(-100.0, 100.0),
    },
    "Crop": {
        "Enabled": _native_bool(),
        "X": _native_int(-1, 100000),
        "Y": _native_int(-1, 100000),
        "W": _native_int(1, 100000),
        "H": _native_int(1, 100000),
        "FixedRatio": _native_bool(),
    },
    "Resize": {
        "Enabled": _native_bool(),
        "Scale": _native_float(0.01, 10.0),
        "Width": _native_int(1, 100000),
        "Height": _native_int(1, 100000),
        "LongEdge": _native_int(1, 100000),
        "ShortEdge": _native_int(1, 100000),
        "AllowUpscaling": _native_bool(),
    },
    "Color Management": {
        "Gamut": _native_bool(),
        # The value is an exact bundled ICC base name, not a generic color-space
        # label.  Keep this to the live-verified profile until each additional
        # RawTherapee 5.11 output profile has its own embedded-ICC evidence.
        "OutputProfile": _native_enum("RTv4_sRGB"),
        "OutputProfileIntent": _native_enum("Relative", "Perceptual", "Saturation", "Absolute"),
        "OutputBPC": _native_bool(),
    },
    "Coarse Transformation": {
        "Rotate": _native_int_enum(0, 90, 180, 270),
        "HorizontalFlip": _native_bool(),
        "VerticalFlip": _native_bool(),
    },
    "Impulse Denoising": {
        "Enabled": _native_bool(),
        "Threshold": _native_float(0.0, 100.0),
    },
    "EPD": {
        "Enabled": _native_bool(),
        "Strength": _native_float(0.0, 10.0),
        "Gamma": _native_float(0.1, 10.0),
        "EdgeStopping": _native_float(0.0, 10.0),
        "Scale": _native_float(0.0, 10.0),
        "ReweightingIterates": _native_int(0, 100),
    },
}


def _validate_native_curve(section: str, key: str, value: Any) -> None:
    if not isinstance(value, str) or len(value) > 256 or not value.endswith(";"):
        raise PP3UnsupportedValue(f"{section}.{key} must be a bounded semicolon curve")
    tokens = value[:-1].split(";")
    if not tokens or len(tokens) > 35:
        raise PP3UnsupportedValue(f"{section}.{key} has too many curve points")
    try:
        curve_kind = int(tokens[0])
    except (TypeError, ValueError) as error:
        raise PP3UnsupportedValue(f"{section}.{key} has an invalid curve kind") from error
    if curve_kind not in {0, 1, 2, 3} or (len(tokens) - 1) % 2:
        raise PP3UnsupportedValue(f"{section}.{key} has an invalid curve shape")
    for token in tokens[1:]:
        try:
            number = float(token)
        except (TypeError, ValueError) as error:
            raise PP3UnsupportedValue(f"{section}.{key} has a non-numeric curve point") from error
        if not math.isfinite(number) or number < 0 or number > 1:
            raise PP3UnsupportedValue(f"{section}.{key} curve points must be between 0 and 1")


def validate_native_sections(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate and normalize the bounded ``style.rawtherapee`` contract."""

    if not isinstance(value, Mapping):
        raise PP3UnsupportedValue("style.rawtherapee must be an object")
    if set(value) != {"profile_version", "sections"}:
        raise PP3UnsupportedValue(
            "style.rawtherapee requires only profile_version and sections"
        )
    profile_version = value.get("profile_version")
    if (
        isinstance(profile_version, bool)
        or not isinstance(profile_version, int)
        or profile_version != RAWTHERAPEE_NATIVE_PROFILE_VERSION
    ):
        raise PP3UnsupportedValue(
            f"style.rawtherapee.profile_version must be {RAWTHERAPEE_NATIVE_PROFILE_VERSION}"
        )
    sections = value.get("sections")
    if not isinstance(sections, Mapping) or not sections:
        raise PP3UnsupportedValue("style.rawtherapee.sections must be a non-empty object")
    normalized_sections: dict[str, dict[str, Any]] = {}
    for section, fields in sections.items():
        if not isinstance(section, str) or section not in RAWTHERAPEE_NATIVE_FIELD_SPECS:
            raise PP3UnsupportedValue(f"Unsupported RawTherapee native section: {section!r}")
        if not isinstance(fields, Mapping) or not fields:
            raise PP3UnsupportedValue(f"{section} native fields must be a non-empty object")
        normalized_fields: dict[str, Any] = {}
        for key, field_value in fields.items():
            spec = RAWTHERAPEE_NATIVE_FIELD_SPECS[section].get(key)
            if spec is None:
                raise PP3UnsupportedValue(f"Unsupported RawTherapee native field: {section}.{key}")
            if spec.kind == "bool":
                if not isinstance(field_value, bool):
                    raise PP3UnsupportedValue(f"{section}.{key} must be a boolean")
            elif spec.kind == "int":
                if isinstance(field_value, bool) or not isinstance(field_value, int):
                    raise PP3UnsupportedValue(f"{section}.{key} must be an integer")
            elif spec.kind == "float":
                if isinstance(field_value, bool) or not isinstance(field_value, (int, float)):
                    raise PP3UnsupportedValue(f"{section}.{key} must be a finite number")
                if not math.isfinite(float(field_value)):
                    raise PP3UnsupportedValue(f"{section}.{key} must be a finite number")
            elif spec.kind == "enum":
                if not isinstance(field_value, str) or field_value not in spec.choices:
                    choices = ", ".join(spec.choices)
                    raise PP3UnsupportedValue(f"{section}.{key} must be one of: {choices}")
            elif spec.kind == "int_enum":
                if isinstance(field_value, bool) or not isinstance(field_value, int):
                    raise PP3UnsupportedValue(f"{section}.{key} must be an integer")
                if str(field_value) not in spec.choices:
                    choices = ", ".join(spec.choices)
                    raise PP3UnsupportedValue(f"{section}.{key} must be one of: {choices}")
            elif spec.kind == "curve":
                _validate_native_curve(section, key, field_value)
            else:  # pragma: no cover - schema declaration error
                raise PP3UnsupportedValue(f"Unknown native field kind: {spec.kind}")
            if spec.minimum is not None and float(field_value) < spec.minimum:
                raise PP3UnsupportedValue(f"{section}.{key} is below its supported range")
            if spec.maximum is not None and float(field_value) > spec.maximum:
                raise PP3UnsupportedValue(f"{section}.{key} is above its supported range")
            normalized_fields[key] = field_value
        normalized_sections[section] = normalized_fields
    return {"profile_version": profile_version, "sections": normalized_sections}


def native_sections_to_overrides(value: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return validated native sections in the shape consumed by ``PP3Document``."""

    validated = validate_native_sections(value)
    return {
        section: dict(fields)
        for section, fields in validated["sections"].items()
    }


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
        if (
            not isinstance(section, str)
            or not section.strip()
            or any(character in section for character in ("[", "]", "=", "\n", "\r", "\x00"))
        ):
            raise PP3UnsupportedValue("PP3 section names must be non-empty single-line strings")
        if (
            not isinstance(key, str)
            or not key.strip()
            or any(character in key for character in ("[", "]", "=", "\n", "\r", "\x00"))
        ):
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
    unsupported = set(adjustments) - set(mapping) - {"notes"}
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
    return sections


def discover_source_sidecar(source: Path) -> Path | None:
    candidate = source.with_name(source.name + ".pp3")
    return candidate if candidate.is_file() and not candidate.is_symlink() else None
