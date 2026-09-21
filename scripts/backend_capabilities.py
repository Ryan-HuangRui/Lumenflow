#!/usr/bin/env python3
"""Versioned backend capability contracts and strict capability errors."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import driver_adapter
import lumenflow_config


BACKEND_CAPABILITIES_SCHEMA_VERSION = "lumenflow.backend_capabilities.v1"
CAPABILITY_NAMES = (
    "preview.state_bound",
    "state.read",
    "plan.compile.v1",
    "intent.compile.v2",
    "render",
    "render.legacy",
    "export.verified",
    "develop.write.verified",
    "composition.crop",
    "mask.ai",
    "adjustments.advanced_color",
)


@dataclass(frozen=True)
class Capability:
    state: str
    reason: str
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = list(self.evidence)
        return payload


class CapabilityContractError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        backend_id: str,
        capability: str,
        state: str,
        reason: str,
    ) -> None:
        self.code = code
        self.backend_id = backend_id
        self.capability_name = capability
        self.state = state
        self.reason = reason
        super().__init__(f"{code}: {backend_id} {capability} is {state}: {reason}")

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "backend_id": self.backend_id,
            "capability": self.capability_name,
            "state": self.state,
            "reason": self.reason,
        }


class UnsupportedCapabilityError(CapabilityContractError):
    pass


class UnverifiedCapabilityError(CapabilityContractError):
    pass


class UnknownCapabilityError(CapabilityContractError):
    pass


@dataclass(frozen=True)
class BackendCapabilities:
    schema_version: str
    backend_id: str
    adapter_version: str
    capabilities: dict[str, Capability]

    def capability(self, name: str) -> Capability:
        capability = self.capabilities.get(name)
        if capability is None:
            raise UnknownCapabilityError(
                code="BACKEND_CAPABILITY_UNKNOWN",
                backend_id=self.backend_id,
                capability=name,
                state="unknown",
                reason="Capability is not declared by this backend contract",
            )
        return capability

    def require(self, name: str) -> Capability:
        capability = self.capability(name)
        if capability.state == "supported":
            return capability
        error_type: type[CapabilityContractError]
        code: str
        if capability.state == "unverified":
            error_type = UnverifiedCapabilityError
            code = "BACKEND_CAPABILITY_UNVERIFIED"
        else:
            error_type = UnsupportedCapabilityError
            code = "BACKEND_CAPABILITY_UNSUPPORTED"
        raise error_type(
            code=code,
            backend_id=self.backend_id,
            capability=name,
            state=capability.state,
            reason=capability.reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "backend_id": self.backend_id,
            "adapter_version": self.adapter_version,
            "capabilities": {
                name: capability.to_dict()
                for name, capability in sorted(self.capabilities.items())
            },
        }


def _supported(reason: str, *evidence: str) -> Capability:
    return Capability("supported", reason, tuple(evidence))


def _unsupported(reason: str) -> Capability:
    return Capability("unsupported", reason)


def _unverified(reason: str, *evidence: str) -> Capability:
    return Capability("unverified", reason, tuple(evidence))


def _contract(
    backend_id: str,
    adapter_version: str,
    capabilities: dict[str, Capability],
) -> BackendCapabilities:
    missing = set(CAPABILITY_NAMES) - set(capabilities)
    extra = set(capabilities) - set(CAPABILITY_NAMES)
    if missing or extra:
        raise ValueError(
            f"Invalid {backend_id} capability declaration; missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return BackendCapabilities(
        schema_version=BACKEND_CAPABILITIES_SCHEMA_VERSION,
        backend_id=backend_id,
        adapter_version=adapter_version,
        capabilities=capabilities,
    )


def rawtherapee_capabilities() -> BackendCapabilities:
    return _contract(
        "rawtherapee",
        "rawtherapee-profile-v1",
        {
            "preview.state_bound": _supported(
                "Preview artifacts bind source bytes and the ordered PP3 profile stack"
            ),
            "state.read": _supported("PP3 profile inputs can be fingerprinted without mutating RAW files"),
            "plan.compile.v1": _supported("adjustment_plan.v1 compiles to temporary PP3 profiles"),
            "intent.compile.v2": _unsupported("EditIntent v2 compiler is not implemented yet"),
            "render": _supported("RawTherapee CLI renders isolated output files"),
            "render.legacy": _unsupported("Use the first-class RawTherapee renderer"),
            "export.verified": _unsupported("Final render receipts do not verify output fingerprints yet"),
            "develop.write.verified": _unsupported("RawTherapee does not write catalog develop state"),
            "composition.crop": _supported("Pixel crop compiles to the generated PP3 profile"),
            "mask.ai": _unsupported("RawTherapee AI mask compilation is not implemented"),
            "adjustments.advanced_color": _unsupported(
                "Lightroom-specific advanced color fields are not compiled to PP3"
            ),
        },
    )


def darktable_capabilities() -> BackendCapabilities:
    return _contract(
        "darktable",
        "darktable-legacy-v1",
        {
            "preview.state_bound": _unsupported("No state-bound darktable preview provider exists yet"),
            "state.read": _unsupported("Full darktable history-stack reads are not implemented"),
            "plan.compile.v1": _unsupported("adjustment_plan.v1 is not compiled to darktable modules"),
            "intent.compile.v2": _unsupported("EditIntent v2 compiler is not implemented yet"),
            "render": _unsupported("First-class isolated darktable rendering is not implemented"),
            "render.legacy": _supported("Legacy style or XMP command construction remains available"),
            "export.verified": _unsupported("Legacy exports do not emit verified receipts"),
            "develop.write.verified": _unsupported("Catalog develop writes are outside the legacy path"),
            "composition.crop": _unsupported("Dynamic crop compilation is not implemented"),
            "mask.ai": _unsupported("AI mask compilation is not implemented"),
            "adjustments.advanced_color": _unsupported("Dynamic module compilation is not implemented"),
        },
    )


def _lightroom_unverified_reason(*flags: str) -> str:
    return "Lightroom bridge has not verified " + " and ".join(flags)


def lightroom_capabilities_from_status(
    status: dict[str, Any] | None,
    *,
    required_cli_version: str | None = None,
    required_plugin_version: str | None = None,
) -> BackendCapabilities:
    base_reason = "Lightroom bridge status has not been probed"
    flags: dict[str, Any] = {}
    base_evidence: tuple[str, ...] = ()
    bridge_ready = False
    if status is not None:
        assessment = driver_adapter.assess_bridge_status(
            status,
            required_capabilities=(),
            required_cli_version=required_cli_version,
            required_plugin_version=required_plugin_version,
        )
        bridge_ready = assessment.ready
        flags = assessment.contract.get("capabilities") or {}
        if bridge_ready:
            base_reason = "Lightroom bridge protocol and versions are verified"
            base_evidence = ("bridge_contract.protocol_version=2", "bridge_contract.version_match=true")
        else:
            base_reason = "; ".join(assessment.issues)

    def flag_capability(flag: str, description: str) -> Capability:
        if bridge_ready and flags.get(flag) is True:
            return _supported(description, *base_evidence, f"bridge_contract.capabilities.{flag}=true")
        reason = base_reason if not bridge_ready else _lightroom_unverified_reason(flag)
        return _unverified(reason, *base_evidence)

    state_read = flag_capability(
        "safe_object_develop_read",
        "Bridge verified object-specific develop-state reads",
    )
    preview_flags = ("safe_object_develop_read", "verified_state_bound_preview")
    if bridge_ready and all(flags.get(flag) is True for flag in preview_flags):
        preview = _supported(
            "Bridge verified state-bound previews for exact photo instances",
            *base_evidence,
            *(f"bridge_contract.capabilities.{flag}=true" for flag in preview_flags),
        )
    else:
        reason = (
            f"{base_reason}; required capabilities: {' and '.join(preview_flags)}"
            if not bridge_ready
            else _lightroom_unverified_reason(*preview_flags)
        )
        preview = _unverified(reason, *base_evidence)

    develop_write = flag_capability(
        "safe_object_develop_write",
        "Bridge verified object-specific absolute develop writes",
    )
    export = flag_capability(
        "verified_export_result",
        "Bridge verified export completion and result identity",
    )
    if develop_write.state == "supported" and export.state == "supported":
        render = _supported(
            "Verified develop write and export capabilities form an executable render path",
            *develop_write.evidence,
            *export.evidence,
        )
    else:
        render = _unverified(
            _lightroom_unverified_reason("safe_object_develop_write", "verified_export_result")
            if bridge_ready
            else base_reason,
            *base_evidence,
        )

    ai_masks = flag_capability(
        "verified_ai_mask_targeting",
        "Bridge verified per-photo AI mask targeting and readback",
    )

    return _contract(
        "lightroom",
        "lightroom-bridge-v2",
        {
            "preview.state_bound": preview,
            "state.read": state_read,
            "plan.compile.v1": _supported(
                "adjustment_plan.v1 can be compiled to fail-closed Lightroom commands"
            ),
            "intent.compile.v2": _unsupported("EditIntent v2 compiler is not implemented yet"),
            "render": render,
            "render.legacy": _unsupported("Legacy unverified Lightroom writes are not allowed"),
            "export.verified": export,
            "develop.write.verified": develop_write,
            "composition.crop": _unsupported("Lightroom crop execution is not implemented"),
            "mask.ai": ai_masks,
            "adjustments.advanced_color": _supported(
                "The v1 compiler maps HSL, tone curve, color grading, and calibration fields"
            ),
        },
    )


def backend_capabilities_for(
    backend_id: str,
    *,
    bridge_status: dict[str, Any] | None = None,
    required_cli_version: str | None = None,
    required_plugin_version: str | None = None,
) -> BackendCapabilities:
    if backend_id == "rawtherapee":
        return rawtherapee_capabilities()
    if backend_id == "darktable":
        return darktable_capabilities()
    if backend_id == "lightroom":
        return lightroom_capabilities_from_status(
            bridge_status,
            required_cli_version=required_cli_version,
            required_plugin_version=required_plugin_version,
        )
    raise ValueError(f"Unsupported backend: {backend_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Print a Lumenflow backend capability contract.")
    parser.add_argument("backend", choices=["rawtherapee", "darktable", "lightroom"])
    parser.add_argument("--probe", action="store_true", help="Probe the live Lightroom bridge.")
    parser.add_argument("--local-config", type=Path, default=lumenflow_config.DEFAULT_LOCAL_CONFIG_PATH)
    args = parser.parse_args()

    local_config = lumenflow_config.read_local_config(args.local_config)
    bridge_status = None
    lightroom_config = local_config.get("lightroom") or {}
    if args.backend == "lightroom" and args.probe:
        executable = lumenflow_config.tool_command(local_config, "lightroom_cli", "lr")
        bridge_status = driver_adapter.read_bridge_status(executable)

    contract = backend_capabilities_for(
        args.backend,
        bridge_status=bridge_status,
        required_cli_version=lightroom_config.get("required_cli_version"),
        required_plugin_version=lightroom_config.get("required_plugin_version"),
    )
    print(json.dumps(contract.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
