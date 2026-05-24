#!/usr/bin/env python3
"""Render RAW files with a chosen external editor CLI."""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
from pathlib import Path

import lumenflow_config


def build_rawtherapee_command(
    raw: Path,
    output: Path,
    profiles: list[Path],
    executable: str = "rawtherapee-cli",
) -> list[str]:
    command = [executable, "-o", str(output), "-Y"]
    for profile in profiles:
        command.extend(["-p", str(profile)])
    command.extend(["-c", str(raw)])
    return command


def build_darktable_command(
    raw: Path,
    output: Path,
    xmp: Path | None = None,
    style_name: str | None = None,
    jpeg_quality: int = 95,
    configdir: Path | None = None,
    cachedir: Path | None = None,
    executable: str = "darktable-cli",
) -> list[str]:
    command = [executable, str(raw)]
    if xmp is not None:
        command.append(str(xmp))
    command.append(str(output))
    if style_name:
        command.extend(["--style", style_name])
    command.append("--core")
    if configdir is not None:
        command.extend(["--configdir", str(configdir)])
    if cachedir is not None:
        command.extend(["--cachedir", str(cachedir)])
    command.extend(["--conf", f"plugins/imageio/format/jpeg/quality={jpeg_quality}"])
    return command


def executable_for_engine(engine: str, local_config: dict | None = None) -> str:
    local_config = local_config or {}
    if engine == "rawtherapee":
        return lumenflow_config.tool_command(local_config, "rawtherapee_cli", "rawtherapee-cli")
    if engine == "darktable":
        return lumenflow_config.tool_command(local_config, "darktable_cli", "darktable-cli")
    raise ValueError(f"Unsupported engine: {engine}")


def run_command(command: list[str], *, dry_run: bool = False, timeout: int | None = None) -> int:
    print(shlex.join(command))
    if dry_run:
        return 0
    subprocess.run(command, check=True, timeout=timeout)
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
    output = args.output_dir / (args.output_name or f"{args.raw.stem}.jpg")
    if args.engine == "rawtherapee":
        command = build_rawtherapee_command(args.raw, output, args.profile, executable=executable)
    else:
        command = build_darktable_command(
            args.raw,
            output,
            xmp=args.xmp,
            style_name=args.style_name,
            jpeg_quality=args.jpeg_quality,
            executable=executable,
        )
    run_command(command, dry_run=args.dry_run, timeout=args.timeout)


if __name__ == "__main__":
    main()
