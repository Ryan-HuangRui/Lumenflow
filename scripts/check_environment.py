#!/usr/bin/env python3
"""Report Lumenflow runtime dependency status as JSON."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import lumenflow_config


@dataclass(frozen=True)
class CommandSpec:
    name: str
    phase: str
    required: bool
    command: list[str]
    timeout_seconds: int = 5
    success_returncodes: tuple[int, ...] = (0, 1)


@dataclass(frozen=True)
class PythonModuleSpec:
    module_name: str
    phase: str
    required: bool


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


DEFAULT_COMMAND_SPECS = [
    CommandSpec("python3", "phase0_environment", True, ["python3", "--version"]),
    CommandSpec("git", "phase0_environment", True, ["git", "--version"]),
    CommandSpec("exiftool", "phase1_photos", True, ["exiftool", "-ver"]),
    CommandSpec("rawtherapee-cli", "phase1_photos", True, ["rawtherapee-cli", "-v"], 5, (0, 255)),
    CommandSpec("darktable-cli", "phase1_photos_fallback", False, ["darktable-cli", "--help"], 10),
    CommandSpec("lr", "phase1_photos_lightroom_optional", False, ["lr", "--version"]),
    CommandSpec("ffmpeg", "phase3_tutorials", False, ["ffmpeg", "-version"]),
    CommandSpec("ffprobe", "phase3_tutorials", False, ["ffprobe", "-version"]),
    CommandSpec("yt-dlp", "phase3_tutorials", False, ["yt-dlp", "--version"]),
    CommandSpec("whisper-cli", "phase3_tutorials", False, ["whisper-cli", "--help"]),
    CommandSpec("jq", "phase0_environment", False, ["jq", "--version"]),
]

DEFAULT_MODULE_SPECS = [
    PythonModuleSpec("requests", "phase0_environment", False),
    PythonModuleSpec("youtube_transcript_api", "phase3_tutorials", False),
    PythonModuleSpec("googleapiclient", "phase3_tutorials", False),
    PythonModuleSpec("openai", "headless_model_provider", False),
    PythonModuleSpec("tweepy", "phase4_social_optional_sdk", False),
]

TOOL_CONFIG_KEYS = {
    "rawtherapee-cli": "rawtherapee_cli",
    "darktable-cli": "darktable_cli",
    "lr": "lightroom_cli",
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffprobe",
    "yt-dlp": "yt_dlp",
}

STATUS_ORDER = {
    "available": 0,
    "missing_optional": 1,
    "unavailable_optional": 1,
    "missing_required": 2,
    "unavailable_required": 2,
}


def run_subprocess(command: list[str], timeout: int) -> CommandResult:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def check_command(
    *,
    name: str,
    phase: str,
    required: bool,
    command: list[str],
    timeout_seconds: int,
    success_returncodes: tuple[int, ...] = (0, 1),
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[[list[str], int], CommandResult] | None = run_subprocess,
) -> dict[str, Any]:
    path = which(name)
    if path is None:
        return {
            "name": name,
            "phase": phase,
            "kind": "command",
            "required": required,
            "status": "missing_required" if required else "missing_optional",
            "path": "",
            "version": "",
            "message": f"{name} not found in PATH",
        }

    if runner is None:
        return {
            "name": name,
            "phase": phase,
            "kind": "command",
            "required": required,
            "status": "available",
            "path": path,
            "version": "",
            "message": "",
        }

    try:
        result = runner(command, timeout_seconds)
    except TimeoutError as exc:
        return {
            "name": name,
            "phase": phase,
            "kind": "command",
            "required": required,
            "status": "unavailable_required" if required else "unavailable_optional",
            "path": path,
            "version": "",
            "message": str(exc),
        }
    except subprocess.TimeoutExpired:
        return {
            "name": name,
            "phase": phase,
            "kind": "command",
            "required": required,
            "status": "unavailable_required" if required else "unavailable_optional",
            "path": path,
            "version": "",
            "message": f"{name} did not return within {timeout_seconds}s",
        }
    except OSError as exc:
        return {
            "name": name,
            "phase": phase,
            "kind": "command",
            "required": required,
            "status": "unavailable_required" if required else "unavailable_optional",
            "path": path,
            "version": "",
            "message": str(exc),
        }

    output = (result.stdout or result.stderr).strip()
    if result.returncode not in success_returncodes:
        return {
            "name": name,
            "phase": phase,
            "kind": "command",
            "required": required,
            "status": "unavailable_required" if required else "unavailable_optional",
            "path": path,
            "version": first_line(output),
            "message": f"{name} exited with code {result.returncode}",
        }

    return {
        "name": name,
        "phase": phase,
        "kind": "command",
        "required": required,
        "status": "available",
        "path": path,
        "version": first_line(output),
        "message": "",
    }


def check_python_module(module_name: str, phase: str, required: bool) -> dict[str, Any]:
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return {
            "name": module_name,
            "phase": phase,
            "kind": "python_module",
            "required": required,
            "status": "missing_required" if required else "missing_optional",
            "path": "",
            "version": "",
            "message": f"Python module {module_name} is not importable",
        }

    return {
        "name": module_name,
        "phase": phase,
        "kind": "python_module",
        "required": required,
        "status": "available",
        "path": str(spec.origin or ""),
        "version": "",
        "message": "",
    }


def check_env_var(name: str, phase: str, required: bool, env: dict[str, str]) -> dict[str, Any]:
    exists = bool(env.get(name))
    return {
        "name": name,
        "phase": phase,
        "kind": "env_var",
        "required": required,
        "status": "available" if exists else ("missing_required" if required else "missing_optional"),
        "path": "",
        "version": "",
        "message": "" if exists else f"{name} is not set",
    }


def check_file(path: Path, display_name: str, phase: str, required: bool) -> dict[str, Any]:
    exists = path.exists()
    return {
        "name": display_name,
        "phase": phase,
        "kind": "file",
        "required": required,
        "status": "available" if exists else ("missing_required" if required else "missing_optional"),
        "path": str(path),
        "version": "",
        "message": "" if exists else f"{display_name} does not exist",
    }


def apply_local_tool_config(
    command_specs: list[CommandSpec],
    local_config: dict[str, Any] | None = None,
) -> list[CommandSpec]:
    local_config = local_config or {}
    resolved_specs = []
    for spec in command_specs:
        key = TOOL_CONFIG_KEYS.get(spec.name)
        if key is None:
            resolved_specs.append(spec)
            continue
        executable = lumenflow_config.tool_command(local_config, key, spec.command[0])
        resolved_specs.append(
            CommandSpec(
                executable,
                spec.phase,
                spec.required,
                [executable, *spec.command[1:]],
                spec.timeout_seconds,
                spec.success_returncodes,
            )
        )
    return resolved_specs


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        "available": 0,
        "missing_required": 0,
        "unavailable_required": 0,
        "missing_optional": 0,
        "unavailable_optional": 0,
    }
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    blocking = counts["missing_required"] + counts["unavailable_required"]
    return {
        **counts,
        "blocking": blocking,
        "overall_status": "ready" if blocking == 0 else "blocked",
    }


def sort_checks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (STATUS_ORDER.get(item["status"], 9), item["phase"], item["name"]))


def collect_environment(
    *,
    repo_root: Path,
    env: dict[str, str],
    command_specs: list[CommandSpec] = DEFAULT_COMMAND_SPECS,
    module_specs: list[PythonModuleSpec] = DEFAULT_MODULE_SPECS,
    local_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    command_specs = apply_local_tool_config(command_specs, local_config)
    tools = [
        check_command(
            name=spec.name,
            phase=spec.phase,
            required=spec.required,
            command=spec.command,
            timeout_seconds=spec.timeout_seconds,
            success_returncodes=spec.success_returncodes,
        )
        for spec in command_specs
    ]
    python_modules = [
        check_python_module(spec.module_name, spec.phase, spec.required)
        for spec in module_specs
    ]
    config = [
        check_env_var("X_BEARER_TOKEN", "phase4_social", False, env),
        check_env_var("OPENAI_API_KEY", "headless_model_provider", False, env),
        check_env_var("ASSEMBLYAI_API_KEY", "phase3_tutorials_optional_asr", False, env),
        check_env_var("DEEPGRAM_API_KEY", "phase3_tutorials_optional_asr", False, env),
        check_env_var("GLADIA_API_KEY", "phase3_tutorials_optional_asr", False, env),
        check_file(
            repo_root / "knowledge" / "source_records" / "x_sources.json",
            "knowledge/source_records/x_sources.json",
            "phase4_social",
            False,
        ),
    ]
    all_items = tools + python_modules + config
    return {
        "schema_version": 1,
        "project": "Lumenflow",
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "summary": summarize(all_items),
        "tools": sort_checks(tools),
        "python_modules": sort_checks(python_modules),
        "config": sort_checks(config),
    }


def render_environment_json(repo_root: Path, env: dict[str, str]) -> str:
    return json.dumps(collect_environment(repo_root=repo_root, env=dict(env)), ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Lumenflow local runtime dependencies.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--local-config", type=Path, default=lumenflow_config.DEFAULT_LOCAL_CONFIG_PATH)
    parser.add_argument("--fail-on-missing-required", action="store_true")
    args = parser.parse_args()
    local_config = lumenflow_config.read_local_config(args.local_config)

    payload = collect_environment(repo_root=args.repo_root, env=dict(os.environ), local_config=local_config)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.fail_on_missing_required and payload["summary"]["blocking"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
