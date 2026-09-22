#!/usr/bin/env python3
"""Render RAW files with a chosen external editor CLI."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .. import config as lumenflow_config

DARKTABLE_ICC_TYPES = frozenset(
    {"SRGB", "ADOBERGB", "LIN_REC709", "LIN_REC2020", "REC709", "PROPHOTO_RGB", "DISPLAY_P3"}
)
DARKTABLE_ICC_INTENTS = frozenset(
    {"PERCEPTUAL", "RELATIVE_COLORIMETRIC", "SATURATION", "ABSOLUTE_COLORIMETRIC"}
)


def build_rawtherapee_command(
    raw: Path,
    output: Path,
    profiles: list[Path],
    executable: str = "rawtherapee-cli",
    *,
    output_format: str | None = None,
    bit_depth: str | int | None = None,
    jpeg_quality: int | None = None,
    jpeg_chroma: int | None = None,
    tiff_compression: bool = False,
    use_fast_export: bool = False,
) -> list[str]:
    """Build a bounded RawTherapee CLI command.

    PP3 files carry processing state; these flags select only the final
    container.  Keeping the output selection here lets previews use JPEG while
    final exports can request 16/32-bit TIFF or 16-bit PNG without changing
    the profile compiler.
    """

    if output_format is not None and not isinstance(output_format, str):
        raise ValueError("RawTherapee output_format must be a string")
    path_format = output.suffix.lstrip(".").lower()
    normalized_format = (output_format or path_format or "jpg").lower()
    aliases = {"jpg": "jpeg", "tif": "tiff"}
    normalized_format = aliases.get(normalized_format, normalized_format)
    if normalized_format not in {"jpeg", "png", "tiff"}:
        raise ValueError("RawTherapee output_format must be jpeg, png, or tiff")
    if bit_depth is not None:
        if isinstance(bit_depth, bool) or not isinstance(bit_depth, (str, int)):
            raise ValueError("RawTherapee bit_depth must be 8, 16, 16f, or 32")
        normalized_depth = str(bit_depth).lower()
        if normalized_depth not in {"8", "16", "16f", "32"}:
            raise ValueError("RawTherapee bit_depth must be 8, 16, 16f, or 32")
    else:
        normalized_depth = None
    if normalized_format == "jpeg" and normalized_depth not in {None, "8"}:
        raise ValueError("RawTherapee JPEG output supports only 8-bit depth")
    if normalized_format == "png" and normalized_depth not in {None, "8", "16"}:
        raise ValueError("RawTherapee PNG output supports only 8-bit or 16-bit depth")
    if jpeg_quality is not None and (
        isinstance(jpeg_quality, bool)
        or not isinstance(jpeg_quality, int)
        or not 1 <= jpeg_quality <= 100
    ):
        raise ValueError("RawTherapee jpeg_quality must be an integer between 1 and 100")
    if jpeg_chroma is not None and (
        isinstance(jpeg_chroma, bool)
        or not isinstance(jpeg_chroma, int)
        or jpeg_chroma not in {1, 2, 3}
    ):
        raise ValueError("RawTherapee jpeg_chroma must be one of the integers 1, 2, or 3")

    command = [executable, "-o", str(output), "-Y"]
    for profile in profiles:
        command.extend(["-p", str(profile)])
    if normalized_format == "jpeg":
        quality = jpeg_quality if jpeg_quality is not None else 92
        command.append(f"-j{quality}")
        if jpeg_chroma is not None:
            command.append(f"-js{jpeg_chroma}")
    elif normalized_format == "tiff":
        command.append("-tz" if tiff_compression else "-t")
    else:
        command.append("-n")
    # RawTherapee's JPEG path is always 8-bit and -b8 is redundant.  Do not
    # emit a misleading depth switch even when the caller explicitly chose 8.
    if normalized_depth is not None and normalized_format != "jpeg":
        command.append(f"-b{normalized_depth}")
    if use_fast_export:
        command.append("-f")
    command.extend(["-c", str(raw)])
    return command


def build_darktable_command(
    raw: Path,
    output: Path,
    xmp: Path | None = None,
    style_name: str | None = None,
    jpeg_quality: int = 95,
    *,
    output_format: str | None = None,
    bit_depth: str | int | None = None,
    icc_type: str | None = None,
    icc_intent: str | None = None,
    max_width: int | None = None,
    max_height: int | None = None,
    configdir: Path | None = None,
    cachedir: Path | None = None,
    library: str | Path | None = ":memory:",
    write_sidecars: bool = False,
    executable: str = "darktable-cli",
) -> list[str]:
    if isinstance(jpeg_quality, bool) or not isinstance(jpeg_quality, int) or not 1 <= jpeg_quality <= 100:
        raise ValueError("darktable jpeg_quality must be an integer between 1 and 100")
    if output_format is not None and not isinstance(output_format, str):
        raise ValueError("darktable output_format must be a string")
    path_format = output.suffix.lstrip(".").lower()
    normalized_format = (output_format or path_format or "jpg").lower()
    format_aliases = {
        "jpg": "jpeg",
        "jpe": "jpeg",
        "tif": "tiff",
        "openexr": "exr",
    }
    normalized_format = format_aliases.get(normalized_format, normalized_format)
    if output_format is not None and path_format:
        normalized_path_format = format_aliases.get(path_format, path_format)
        if normalized_path_format != normalized_format:
            raise ValueError("darktable output suffix must match output_format")
    if normalized_format not in {"jpeg", "png", "tiff", "exr"}:
        raise ValueError("darktable output_format must be jpeg, png, tiff, or openexr")
    if bit_depth is not None:
        if isinstance(bit_depth, bool) or not isinstance(bit_depth, (str, int)):
            raise ValueError("darktable bit_depth must be 8, 16, or 32")
        normalized_depth = str(bit_depth).lower()
    else:
        normalized_depth = {"jpeg": "8", "png": "8", "tiff": "8", "exr": "16"}[normalized_format]
    if normalized_depth not in {"8", "16", "32"}:
        raise ValueError("darktable bit_depth must be 8, 16, or 32")
    supported_depths = {
        "jpeg": {"8"},
        "png": {"8", "16"},
        "tiff": {"8", "16", "32"},
        "exr": {"16", "32"},
    }
    if normalized_depth not in supported_depths[normalized_format]:
        raise ValueError(f"darktable {normalized_format} output does not support {normalized_depth}-bit depth")
    if icc_type is not None and icc_type not in DARKTABLE_ICC_TYPES:
        raise ValueError(
            "darktable icc_type must be one of " + ", ".join(sorted(DARKTABLE_ICC_TYPES))
        )
    if icc_intent is not None and icc_intent not in DARKTABLE_ICC_INTENTS:
        raise ValueError(
            "darktable icc_intent must be one of " + ", ".join(sorted(DARKTABLE_ICC_INTENTS))
        )
    for name, value in (("max_width", max_width), ("max_height", max_height)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
            raise ValueError(f"darktable {name} must be a positive integer")

    out_ext = {"jpeg": "jpg", "png": "png", "tiff": "tif", "exr": "exr"}[normalized_format]
    command = [executable, str(raw)]
    if xmp is not None:
        command.append(str(xmp))
    command.append(str(output))
    command.extend(["--out-ext", out_ext])
    if max_width is not None:
        command.extend(["--width", str(max_width)])
    if max_height is not None:
        command.extend(["--height", str(max_height)])
    if icc_type is not None:
        command.extend(["--icc-type", icc_type])
    if icc_intent is not None:
        command.extend(["--icc-intent", icc_intent])
    if style_name:
        command.extend(["--style", style_name])
    # Keep headless renders independent of user-installed custom presets.  The
    # isolated config already disables OpenCL, but making CPU-only execution
    # explicit avoids GPU/plugin state and limits this 5.4.1 path to one
    # deterministic OpenMP worker; it does not change the XMP pixel intent.
    command.extend(["--apply-custom-presets", "false"])
    command.append("--core")
    command.extend(["--disable-opencl", "--threads", "1"])
    if configdir is not None:
        command.extend(["--configdir", str(configdir)])
    if cachedir is not None:
        command.extend(["--cachedir", str(cachedir)])
    if library is not None:
        command.extend(["--library", str(library)])
    if not write_sidecars:
        command.extend(["--conf", "write_sidecar_files=never"])
    command.extend(["--conf", f"plugins/imageio/format/jpeg/quality={jpeg_quality}"])
    if normalized_format == "png":
        command.extend(["--conf", f"plugins/imageio/format/png/bpp={normalized_depth}"])
    elif normalized_format == "tiff":
        command.extend(["--conf", f"plugins/imageio/format/tiff/bpp={normalized_depth}"])
        # 16-bit integer is the portable/common TIFF contract; 32-bit TIFF
        # is written as IEEE float by darktable's 5.4.1 format backend.
        command.extend(["--conf", "plugins/imageio/format/tiff/pixelformat=false"])
    elif normalized_format == "exr":
        # darktable stores EXR's HALF/FLOAT selector as enum values shifted
        # four bits: HALF (enum 1) -> 16 and FLOAT (enum 2) -> 32.  These
        # happen to equal the advertised bit depths, but are not arbitrary
        # output sizes; keep the mapping explicit and source-pinned.
        exr_bpp = normalized_depth
        command.extend(["--conf", f"plugins/imageio/format/exr/bpp={exr_bpp}"])
    return command


def executable_for_engine(engine: str, local_config: dict | None = None) -> str:
    local_config = local_config or {}
    if engine == "rawtherapee":
        return lumenflow_config.tool_command(local_config, "rawtherapee_cli", "rawtherapee-cli")
    if engine == "darktable":
        return lumenflow_config.tool_command(local_config, "darktable_cli", "darktable-cli")
    raise ValueError(f"Unsupported engine: {engine}")


def run_command(command: list[str], *, dry_run: bool = False, timeout: int | None = None) -> int:
    print(shlex.join(command), file=sys.stderr)
    if dry_run:
        return 0
    environment = None
    if command and Path(command[0]).name == "rawtherapee-cli":
        # RawTherapee 5.11's RAW path has a small OpenMP race in some camera
        # decoders.  A single worker makes preview and final execution produce
        # the same pixel fingerprint for an identical PP3/source pair.
        environment = os.environ.copy()
        environment["OMP_NUM_THREADS"] = "1"
    subprocess.run(command, check=True, timeout=timeout, env=environment)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a RAW file through a RAW editor CLI.")
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output-name")
    parser.add_argument("--profile", type=Path, action="append", default=[])
    parser.add_argument("--engine", choices=["rawtherapee", "darktable"], default="rawtherapee")
    parser.add_argument("--xmp", type=Path)
    parser.add_argument("--style-name")
    parser.add_argument("--output-format", choices=["jpeg", "jpg", "png", "tiff", "tif", "openexr", "exr"])
    parser.add_argument("--bit-depth")
    parser.add_argument("--icc-type")
    parser.add_argument("--icc-intent")
    parser.add_argument("--max-width", type=int)
    parser.add_argument("--max-height", type=int)
    parser.add_argument("--jpeg-quality", type=int, default=95)
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--local-config", type=Path, default=lumenflow_config.DEFAULT_LOCAL_CONFIG_PATH)
    args = parser.parse_args()

    local_config = lumenflow_config.read_local_config(args.local_config)
    executable = executable_for_engine(args.engine, local_config)
    if not args.dry_run and shutil.which(executable) is None:
        raise SystemExit(f"{executable} not found. Install it or use --dry-run.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    requested_format = (args.output_format or "jpeg").lower()
    output_suffix = {
        "jpeg": "jpg",
        "jpg": "jpg",
        "png": "png",
        "tiff": "tif",
        "tif": "tif",
        "openexr": "exr",
        "exr": "exr",
    }[requested_format]
    output = args.output_dir / (args.output_name or f"{args.raw.stem}.{output_suffix}")
    if args.engine == "rawtherapee":
        command = build_rawtherapee_command(
            args.raw,
            output,
            args.profile,
            executable=executable,
            output_format=args.output_format,
            bit_depth=args.bit_depth,
            jpeg_quality=args.jpeg_quality,
        )
    else:
        command = build_darktable_command(
            args.raw,
            output,
            xmp=args.xmp,
            style_name=args.style_name,
            jpeg_quality=args.jpeg_quality,
            output_format=args.output_format,
            bit_depth=args.bit_depth,
            icc_type=args.icc_type,
            icc_intent=args.icc_intent,
            max_width=args.max_width,
            max_height=args.max_height,
            executable=executable,
        )
    run_command(command, dry_run=args.dry_run, timeout=args.timeout)


if __name__ == "__main__":
    main()
