#!/usr/bin/env python3
"""Render RAW files with a chosen external editor CLI."""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
from pathlib import Path


def build_rawtherapee_command(raw: Path, output_dir: Path, profiles: list[Path]) -> list[str]:
    command = ["rawtherapee-cli", "-o", str(output_dir), "-Y"]
    for profile in profiles:
        command.extend(["-p", str(profile)])
    command.extend(["-c", str(raw)])
    return command


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a RAW file through RawTherapee CLI.")
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path, action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and shutil.which("rawtherapee-cli") is None:
        raise SystemExit("rawtherapee-cli not found. Install RawTherapee or use --dry-run.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    command = build_rawtherapee_command(args.raw, args.output_dir, args.profile)
    print(shlex.join(command))
    if not args.dry_run:
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
