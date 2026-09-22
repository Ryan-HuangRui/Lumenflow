"""Deterministic safety checks for the Lightroom driver boundary."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

REQUIRED_PROTOCOL_VERSION = "2"
REQUIRED_WRITE_CAPABILITIES = (
    "safe_object_develop_write",
    "verified_export_result",
)
REQUIRED_PREVIEW_CAPABILITIES = (
    "safe_object_develop_read",
    "verified_state_bound_preview",
)


class BridgeSafetyError(RuntimeError):
    """Raised before any edit when the loaded bridge cannot prove safety."""


@dataclass(frozen=True)
class BridgeAssessment:
    ready: bool
    issues: tuple[str, ...]
    contract: dict[str, Any]


Runner = Callable[[list[str], int], subprocess.CompletedProcess[str]]


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)


def read_bridge_status(executable: str, *, timeout: int = 10, runner: Runner = _run) -> dict[str, Any]:
    command = [executable, "-o", "json", "system", "status"]
    completed = runner(command, timeout)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise BridgeSafetyError(f"Unable to read Lightroom bridge status: {detail or 'command failed'}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise BridgeSafetyError("Lightroom bridge status was not valid JSON") from error
    if not isinstance(payload, dict):
        raise BridgeSafetyError("Lightroom bridge status must be a JSON object")
    return payload


def assess_bridge_status(
    status: dict[str, Any],
    *,
    required_protocol: str = REQUIRED_PROTOCOL_VERSION,
    required_capabilities: tuple[str, ...] = REQUIRED_WRITE_CAPABILITIES,
    required_cli_version: str | None = None,
    required_plugin_version: str | None = None,
) -> BridgeAssessment:
    issues: list[str] = []
    contract = status.get("bridge_contract")
    if not isinstance(contract, dict):
        return BridgeAssessment(False, ("bridge safety contract is missing",), {})

    if status.get("connected") is not True:
        issues.append("Lightroom bridge is not connected")

    protocol = contract.get("protocol_version")
    if str(protocol) != str(required_protocol):
        issues.append(f"unsupported bridge protocol: {protocol} (expected {required_protocol})")

    if contract.get("version_match") is not True:
        issues.append("CLI and loaded plugin versions do not match")

    cli_version = contract.get("cli_version")
    plugin_version = contract.get("plugin_version")
    if required_cli_version and cli_version != required_cli_version:
        issues.append(f"unexpected CLI version: {cli_version} (expected {required_cli_version})")
    if required_plugin_version and plugin_version != required_plugin_version:
        issues.append(f"unexpected plugin version: {plugin_version} (expected {required_plugin_version})")

    capabilities = contract.get("capabilities")
    if not isinstance(capabilities, dict):
        capabilities = {}
    for capability in required_capabilities:
        if capabilities.get(capability) is not True:
            issues.append(f"missing verified capability: {capability}")

    return BridgeAssessment(not issues, tuple(issues), contract)


def require_safe_bridge(
    status: dict[str, Any],
    **requirements: Any,
) -> BridgeAssessment:
    assessment = assess_bridge_status(status, **requirements)
    if not assessment.ready:
        raise BridgeSafetyError("Unsafe Lightroom bridge: " + "; ".join(assessment.issues))
    return assessment


def preflight_write(
    executable: str,
    *,
    timeout: int = 10,
    runner: Runner = _run,
    **requirements: Any,
) -> BridgeAssessment:
    return require_safe_bridge(
        read_bridge_status(executable, timeout=timeout, runner=runner),
        **requirements,
    )


def preflight_preview(
    executable: str,
    *,
    timeout: int = 10,
    runner: Runner = _run,
    **requirements: Any,
) -> BridgeAssessment:
    return require_safe_bridge(
        read_bridge_status(executable, timeout=timeout, runner=runner),
        required_capabilities=REQUIRED_PREVIEW_CAPABILITIES,
        **requirements,
    )
