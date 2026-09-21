"""Versioned, state-bound preview providers for Lumenflow photo workflows."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import driver_adapter
import lumenflow_config
import render_raw


PREVIEW_ARTIFACT_SCHEMA_VERSION = "lumenflow.preview_artifact.v1"


class PreviewProviderError(RuntimeError):
    """Raised when a preview provider cannot produce a trustworthy artifact."""


class PreviewCapabilityError(PreviewProviderError):
    """Raised before preview work when a backend cannot prove required capabilities."""


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_fingerprint(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return {"sha256": digest.hexdigest(), "size_bytes": size}


@dataclass(frozen=True)
class PreviewRequest:
    source: Path
    output: Path
    base_profile: Path | None
    dry_run: bool
    timeout: int | None
    selection_reason: str = ""


@dataclass(frozen=True)
class PreviewArtifact:
    schema_version: str
    artifact_id: str
    provider: dict[str, Any]
    source: str
    preview: str
    source_fingerprint: dict[str, Any]
    preview_fingerprint: dict[str, Any] | None
    starting_state: dict[str, Any]
    starting_state_hash: str
    state_inputs: list[dict[str, Any]]
    state_completeness: str
    command: str
    command_argv: list[str]
    selection_reason: str
    status: str
    failure_reason: str
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PreviewProvider(Protocol):
    provider_id: str

    def create_preview(self, request: PreviewRequest) -> PreviewArtifact:
        """Create one preview and return a state-bound artifact record."""


CommandRunner = Callable[..., int]


class RawTherapeePreviewProvider:
    provider_id = "rawtherapee"
    adapter_version = "1"

    def __init__(
        self,
        *,
        local_config: dict[str, Any] | None = None,
        runner: CommandRunner = render_raw.run_command,
    ) -> None:
        self.local_config = local_config or {}
        self.runner = runner
        self.executable = lumenflow_config.tool_command(
            self.local_config,
            "rawtherapee_cli",
            "rawtherapee-cli",
        )

    @staticmethod
    def _profile_stack(
        request: PreviewRequest,
    ) -> tuple[list[Path], dict[str, Any], list[dict[str, Any]], str]:
        profile_inputs: list[tuple[str, Path]] = []
        if request.base_profile is not None and request.base_profile.exists():
            profile_inputs.append(("base_profile", request.base_profile))

        source_sidecar = request.source.with_name(request.source.name + ".pp3")
        if source_sidecar.exists() and all(path != source_sidecar for _role, path in profile_inputs):
            profile_inputs.append(("source_sidecar", source_sidecar))

        profile_stack = []
        state_inputs = []
        for role, path in profile_inputs:
            fingerprint = file_fingerprint(path)
            profile_stack.append({"role": role, **fingerprint})
            state_inputs.append({"role": role, "path": str(path), **fingerprint})

        starting_state = {
            "kind": "rawtherapee_profile_stack",
            "profile_stack": profile_stack,
            "uses_engine_default": not profile_stack,
        }
        completeness = (
            "complete"
            if any(item["role"] == "source_sidecar" for item in profile_stack)
            else "partial"
        )
        return [path for _role, path in profile_inputs], starting_state, state_inputs, completeness

    def create_preview(self, request: PreviewRequest) -> PreviewArtifact:
        source_fingerprint = file_fingerprint(request.source)
        profiles, starting_state, state_inputs, completeness = self._profile_stack(request)
        starting_state_hash = canonical_hash(starting_state)
        command = render_raw.build_rawtherapee_command(
            request.source,
            request.output,
            profiles,
            executable=self.executable,
        )
        artifact_id = "preview_" + canonical_hash(
            {
                "schema_version": PREVIEW_ARTIFACT_SCHEMA_VERSION,
                "provider_id": self.provider_id,
                "source_fingerprint": source_fingerprint,
                "starting_state_hash": starting_state_hash,
                "preview_path": str(request.output),
            }
        )[:32]

        status = "dry_run" if request.dry_run else "pending"
        failure_reason = ""
        preview_fingerprint = None
        try:
            self.runner(command, dry_run=request.dry_run, timeout=request.timeout)
            if not request.dry_run:
                if not request.output.exists():
                    raise PreviewProviderError(f"Preview command did not create output: {request.output}")
                preview_fingerprint = file_fingerprint(request.output)
                status = "success"
        except (PreviewProviderError, subprocess.SubprocessError, OSError) as error:
            status = "failed"
            failure_reason = str(error)

        return PreviewArtifact(
            schema_version=PREVIEW_ARTIFACT_SCHEMA_VERSION,
            artifact_id=artifact_id,
            provider={
                "id": self.provider_id,
                "adapter_version": self.adapter_version,
                "executable": self.executable,
            },
            source=str(request.source),
            preview=str(request.output),
            source_fingerprint=source_fingerprint,
            preview_fingerprint=preview_fingerprint,
            starting_state=starting_state,
            starting_state_hash=starting_state_hash,
            state_inputs=state_inputs,
            state_completeness=completeness,
            command=shlex.join(command),
            command_argv=command,
            selection_reason=request.selection_reason,
            status=status,
            failure_reason=failure_reason,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )


class LightroomPreviewProvider:
    """Fail-closed placeholder for a future verified Lightroom preview adapter."""

    provider_id = "lightroom"

    def __init__(
        self,
        *,
        local_config: dict[str, Any] | None = None,
        status_runner: driver_adapter.Runner | None = None,
    ) -> None:
        self.local_config = local_config or {}
        self.status_runner = status_runner
        self.executable = lumenflow_config.tool_command(
            self.local_config,
            "lightroom_cli",
            "lr",
        )

    def create_preview(self, request: PreviewRequest) -> PreviewArtifact:
        del request
        lightroom_config = self.local_config.get("lightroom") or {}
        try:
            requirements = {
                "required_cli_version": lightroom_config.get("required_cli_version"),
                "required_plugin_version": lightroom_config.get("required_plugin_version"),
            }
            if self.status_runner is None:
                driver_adapter.preflight_preview(self.executable, timeout=10, **requirements)
            else:
                driver_adapter.preflight_preview(
                    self.executable,
                    timeout=10,
                    runner=self.status_runner,
                    **requirements,
                )
        except driver_adapter.BridgeSafetyError as error:
            raise PreviewCapabilityError(str(error)) from error
        raise PreviewCapabilityError(
            "Lightroom reported preview capabilities, but the state-bound preview adapter has not been implemented"
        )


def create_preview_provider(
    name: str,
    *,
    local_config: dict[str, Any] | None = None,
) -> PreviewProvider:
    if name == "rawtherapee":
        return RawTherapeePreviewProvider(local_config=local_config)
    if name == "lightroom":
        return LightroomPreviewProvider(local_config=local_config)
    raise ValueError(f"Unsupported preview provider: {name}")
