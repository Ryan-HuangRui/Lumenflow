"""High-level, contract-preserving operations exposed through MCP."""

from __future__ import annotations

import importlib.metadata
import shutil
from pathlib import Path
from typing import Any, Callable

from .. import backend_capabilities
from .. import config as lumenflow_config
from ..core import edit_intent, preview, review


ToolResult = dict[str, Any]


class RuntimeInputError(ValueError):
    """A stable, user-correctable runtime input failure."""

    def __init__(self, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")


def _success(result: Any) -> ToolResult:
    return {"ok": True, "result": result}


def _failure(code: str, reason: str) -> ToolResult:
    return {"ok": False, "error": {"code": code, "reason": reason}}


def _absolute_path(value: str, field: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise RuntimeInputError(
            "ABSOLUTE_PATH_REQUIRED", f"{field} must be an absolute path"
        )
    return path


def _tool_error(error: Exception) -> ToolResult:
    if isinstance(error, RuntimeInputError):
        return _failure(error.code, error.reason)
    if isinstance(error, edit_intent.ExecutionPreconditionError):
        return _failure(error.code, error.reason)
    if isinstance(error, review.ReviewLoopError):
        return _failure(error.code, error.reason)
    if isinstance(error, backend_capabilities.CapabilityContractError):
        return _failure(error.code, error.reason)
    if isinstance(error, edit_intent.IntentValidationError):
        return _failure("INVALID_EDIT_INTENT", str(error))
    if isinstance(error, preview.PreviewProviderError):
        return _failure("PREVIEW_FAILED", str(error))
    if isinstance(error, FileNotFoundError):
        return _failure("FILE_NOT_FOUND", str(error))
    if isinstance(error, ValueError):
        return _failure("INVALID_ARGUMENT", str(error))
    raise error


def _guard(operation: Callable[[], Any]) -> ToolResult:
    try:
        return _success(operation())
    except Exception as error:  # expected domain errors are normalized; crashes propagate
        return _tool_error(error)


class LumenflowRuntime:
    """Stable application facade used by both MCP and direct Python clients."""

    def __init__(self, *, local_config: dict[str, Any] | None = None) -> None:
        self.local_config = dict(local_config or {})

    def status(self) -> ToolResult:
        def inspect_runtime() -> dict[str, Any]:
            engines: dict[str, Any] = {}
            for backend_id, config_key, default_command in (
                ("rawtherapee", "rawtherapee_cli", "rawtherapee-cli"),
                ("darktable", "darktable_cli", "darktable-cli"),
            ):
                command = lumenflow_config.tool_command(
                    self.local_config, config_key, default_command
                )
                command_path = Path(command)
                resolved = (
                    str(command_path)
                    if command_path.is_absolute() and command_path.is_file()
                    else shutil.which(command)
                )
                engines[backend_id] = {
                    "configured_command": command,
                    "resolved_command": resolved,
                    "available": resolved is not None,
                    "capabilities": backend_capabilities.backend_capabilities_for(
                        backend_id
                    ).to_dict(),
                }
            try:
                version = importlib.metadata.version("lumenflow")
            except importlib.metadata.PackageNotFoundError:
                version = "0.1.0+source"
            return {
                "service": "lumenflow",
                "version": version,
                "protocol": "stdio",
                "mode": (
                    "full"
                    if any(engine["available"] for engine in engines.values())
                    else "lite"
                ),
                "engines": engines,
            }

        return _guard(inspect_runtime)

    def create_previews(
        self,
        *,
        backend_id: str,
        source_paths: list[str],
        output_dir: str,
        base_profile_paths: dict[str, str] | None = None,
        dry_run: bool = False,
        timeout: int | None = 120,
        selection_reason: str = "",
    ) -> ToolResult:
        def create() -> list[dict[str, Any]]:
            if not source_paths:
                raise RuntimeInputError(
                    "EMPTY_SOURCE_SET", "source_paths must contain at least one RAW file"
                )
            target_root = _absolute_path(output_dir, "output_dir")
            profile_paths = base_profile_paths or {}
            provider = preview.create_preview_provider(
                backend_id, local_config=self.local_config
            )
            requests: list[preview.PreviewRequest] = []
            outputs: set[Path] = set()
            for index, source_value in enumerate(source_paths):
                source = _absolute_path(source_value, f"source_paths[{index}]")
                if not source.is_file() or source.is_symlink():
                    raise RuntimeInputError(
                        "SOURCE_NOT_READABLE", f"source is not a regular file: {source}"
                    )
                output = target_root / f"{source.name}.preview.jpg"
                if output in outputs:
                    raise RuntimeInputError(
                        "PREVIEW_OUTPUT_COLLISION", f"duplicate preview output: {output}"
                    )
                if output.exists() or output.is_symlink():
                    raise RuntimeInputError(
                        "PREVIEW_ALREADY_EXISTS",
                        f"refusing to overwrite an existing preview: {output}",
                    )
                outputs.add(output)
                profile_value = profile_paths.get(source_value)
                base_profile = (
                    _absolute_path(profile_value, f"base_profile_paths[{source_value!r}]")
                    if profile_value
                    else None
                )
                if base_profile is not None and (
                    not base_profile.is_file() or base_profile.is_symlink()
                ):
                    raise RuntimeInputError(
                        "BASE_PROFILE_NOT_READABLE",
                        f"base profile is not a regular file: {base_profile}",
                    )
                requests.append(
                    preview.PreviewRequest(
                        source=source,
                        output=output,
                        base_profile=base_profile,
                        dry_run=dry_run,
                        timeout=timeout,
                        selection_reason=selection_reason,
                    )
                )
            return [provider.create_preview(request).to_dict() for request in requests]

        return _guard(create)

    def compile_edit(
        self,
        *,
        intent: dict[str, Any],
        backend_id: str,
        output_dir: str,
    ) -> ToolResult:
        return _guard(
            lambda: edit_intent.compile_intent(
                intent,
                backend_id=backend_id,
                output_dir=_absolute_path(output_dir, "output_dir"),
                local_config=self.local_config,
            )
        )

    def execute_edit(
        self,
        *,
        plan: dict[str, Any],
        allowed_output_dir: str,
        dry_run: bool = True,
        timeout: int | None = 300,
    ) -> ToolResult:
        return _guard(
            lambda: edit_intent.execute_plan(
                plan,
                dry_run=dry_run,
                timeout=timeout,
                allowed_output_dir=_absolute_path(
                    allowed_output_dir, "allowed_output_dir"
                ),
                local_config=self.local_config,
            )
        )

    def start_review(
        self, *, intent: dict[str, Any], max_revisions: int = 2
    ) -> ToolResult:
        return _guard(
            lambda: review.start_review_session(
                intent, max_revisions=max_revisions
            )
        )

    def advance_review(
        self,
        *,
        session: dict[str, Any],
        plan: dict[str, Any],
        receipt: dict[str, Any],
        review_result: dict[str, Any],
    ) -> ToolResult:
        return _guard(
            lambda: review.advance_review_session(
                session, plan, receipt, review_result
            )
        )
