#!/usr/bin/env python3
"""Probe darktable without trusting installation presence or mutating photo state."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import lumenflow_config
from render_raw import build_darktable_command


DARKTABLE_PROBE_SCHEMA_VERSION = "lumenflow.darktable_probe.v1"
SUPPORTED_RAW_EXTENSIONS = {
    ".3fr",
    ".arw",
    ".cr2",
    ".cr3",
    ".dng",
    ".erf",
    ".iiq",
    ".kdc",
    ".mef",
    ".mos",
    ".mrw",
    ".nef",
    ".nrw",
    ".orf",
    ".pef",
    ".raf",
    ".raw",
    ".rw2",
    ".sr2",
    ".srf",
    ".srw",
    ".x3f",
}
Runner = Callable[..., subprocess.CompletedProcess[str]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fingerprint(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return {"sha256": digest.hexdigest(), "size_bytes": size}


def _sidecar_candidates(raw: Path) -> tuple[Path, ...]:
    candidates = {raw.with_suffix(".xmp"), raw.with_name(raw.name + ".xmp")}
    return tuple(sorted(candidates))


def _sidecar_state(raw: Path) -> dict[str, dict[str, Any]]:
    return {
        str(path): _fingerprint(path)
        for path in _sidecar_candidates(raw)
        if path.is_file()
    }


def _bounded_output(value: str | None) -> str:
    return (value or "")[-4000:]


def _run_stage(
    name: str,
    command: list[str],
    *,
    runner: Runner,
    timeout: int,
) -> tuple[dict[str, Any], subprocess.CompletedProcess[str] | None]:
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return (
            {
                "name": name,
                "status": "failed",
                "command": command,
                "returncode": None,
                "stdout": "",
                "stderr": _bounded_output(str(error)),
            },
            None,
        )
    return (
        {
            "name": name,
            "status": "passed" if result.returncode == 0 else "failed",
            "command": command,
            "returncode": result.returncode,
            "stdout": _bounded_output(result.stdout),
            "stderr": _bounded_output(result.stderr),
        },
        result,
    )


def _base_report(executable: str) -> dict[str, Any]:
    return {
        "schema_version": DARKTABLE_PROBE_SCHEMA_VERSION,
        "probe_id": f"darktable_probe_{uuid.uuid4().hex}",
        "backend_id": "darktable",
        "executable": executable,
        "status": "failed",
        "version": "",
        "stages": [],
        "source_fingerprint_before": None,
        "source_fingerprint_after": None,
        "source_unchanged": None,
        "sidecars_unchanged": None,
        "output_fingerprint": None,
        "failure_reason": "",
        "started_at": _now(),
        "completed_at": "",
    }


def probe_darktable(
    *,
    executable: str = "darktable-cli",
    raw: Path | None = None,
    output_dir: Path | None = None,
    runner: Runner = subprocess.run,
    timeout: int = 60,
) -> dict[str, Any]:
    """Return evidence for an isolated darktable export; never promote capabilities."""
    report = _base_report(executable)
    version_stage, version_result = _run_stage(
        "version",
        [executable, "--version"],
        runner=runner,
        timeout=timeout,
    )
    report["stages"].append(version_stage)
    if version_result is None or version_result.returncode != 0:
        report["failure_reason"] = (
            version_stage["stderr"] or version_stage["stdout"] or "darktable version probe failed"
        )
        report["completed_at"] = _now()
        return report

    version_text = f"{version_result.stdout}\n{version_result.stderr}"
    match = re.search(
        r"darktable(?:-cli)?(?:\s+version)?\s+([0-9]+(?:\.[0-9]+)+)",
        version_text,
        re.I,
    )
    if match is None:
        version_stage["status"] = "failed"
        report["failure_reason"] = "darktable version was not parseable"
        report["completed_at"] = _now()
        return report
    report["version"] = match.group(1)
    if raw is None:
        report["status"] = "inconclusive"
        report["failure_reason"] = "RAW export was not exercised"
        report["completed_at"] = _now()
        return report

    raw = raw.expanduser()
    if raw.is_symlink() or not raw.is_file():
        report["stages"].append(
            {
                "name": "preflight",
                "status": "failed",
                "command": [],
                "returncode": None,
                "stdout": "",
                "stderr": "RAW input must be an existing regular file",
            }
        )
        report["failure_reason"] = "RAW input must be an existing regular file"
        report["completed_at"] = _now()
        return report
    raw = raw.resolve()
    if raw.suffix.lower() not in SUPPORTED_RAW_EXTENSIONS:
        report["stages"].append(
            {
                "name": "preflight",
                "status": "failed",
                "command": [],
                "returncode": None,
                "stdout": "",
                "stderr": "Unsupported RAW extension",
            }
        )
        report["failure_reason"] = "Unsupported RAW extension"
        report["completed_at"] = _now()
        return report
    if output_dir is None:
        report["status"] = "inconclusive"
        report["failure_reason"] = "An explicit output directory is required for the RAW export probe"
        report["completed_at"] = _now()
        return report

    output_root_input = output_dir.expanduser()
    if output_root_input.is_symlink():
        report["status"] = "failed"
        report["failure_reason"] = "Output directory must not be a symbolic link"
        report["completed_at"] = _now()
        return report
    output_root = output_root_input.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    before = _fingerprint(raw)
    sidecars_before = _sidecar_state(raw)
    report["source_fingerprint_before"] = before

    with tempfile.TemporaryDirectory(prefix="lumenflow-darktable-probe-", dir=output_root) as temporary:
        probe_root = Path(temporary)
        config_dir = probe_root / "config"
        cache_dir = probe_root / "cache"
        config_dir.mkdir()
        cache_dir.mkdir()
        output = probe_root / f"{raw.stem}.probe.jpg"
        command = build_darktable_command(
            raw,
            output,
            configdir=config_dir,
            cachedir=cache_dir,
            library=":memory:",
            write_sidecars=False,
            executable=executable,
        )
        export_stage, export_result = _run_stage(
            "isolated_export",
            command,
            runner=runner,
            timeout=timeout,
        )
        if export_result is not None and export_result.returncode == 0 and not output.is_file():
            export_stage["status"] = "failed"
            export_stage["stderr"] = "darktable returned success without producing an output file"
        report["stages"].append(export_stage)

        after = _fingerprint(raw)
        report["source_fingerprint_after"] = after
        report["source_unchanged"] = before == after
        report["sidecars_unchanged"] = sidecars_before == _sidecar_state(raw)
        if output.is_file():
            report["output_fingerprint"] = _fingerprint(output)

        checks_passed = (
            export_stage["status"] == "passed"
            and report["source_unchanged"]
            and report["sidecars_unchanged"]
            and report["output_fingerprint"] is not None
        )
        if checks_passed:
            report["status"] = "passed"
        else:
            failures = []
            if export_stage["status"] != "passed":
                failures.append(export_stage["stderr"] or "isolated export failed")
            if not report["source_unchanged"]:
                failures.append("RAW source changed during probe")
            if not report["sidecars_unchanged"]:
                failures.append("RAW sidecar state changed during probe")
            if report["output_fingerprint"] is None:
                failures.append("No verifiable output was produced")
            report["failure_reason"] = "; ".join(failures)

    report["completed_at"] = _now()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe darktable's isolated RAW export behavior.")
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--report-output", type=Path)
    parser.add_argument("--local-config", type=Path, default=lumenflow_config.DEFAULT_LOCAL_CONFIG_PATH)
    args = parser.parse_args()

    local_config = lumenflow_config.read_local_config(args.local_config)
    executable = lumenflow_config.tool_command(local_config, "darktable_cli", "darktable-cli")
    report = probe_darktable(
        executable=executable,
        raw=args.raw,
        output_dir=args.output_dir,
        timeout=args.timeout,
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report_output:
        args.report_output.parent.mkdir(parents=True, exist_ok=True)
        args.report_output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    raise SystemExit(0 if report["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
