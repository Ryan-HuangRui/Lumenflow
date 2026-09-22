"""High-level, contract-preserving operations exposed through MCP."""

from __future__ import annotations

import importlib.metadata
import copy
import hashlib
import shutil
from pathlib import Path
from typing import Any, Callable

from .. import backend_capabilities
from .. import config as lumenflow_config
from ..curation import CurationError, SelectionPlanError
from ..core import edit_intent, preview, review
from ..memory import personal_examples
from ..style_library import StyleLibrary, StyleLibraryError


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
    if isinstance(error, personal_examples.ExampleStoreError):
        return _failure(error.code, error.reason)
    if isinstance(error, StyleLibraryError):
        return _failure("STYLE_LIBRARY_ERROR", str(error))
    if isinstance(error, SelectionPlanError):
        return _failure("INVALID_SELECTION_PLAN", str(error))
    if isinstance(error, CurationError):
        return _failure("CURATION_FAILED", str(error))
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

    def __init__(
        self,
        *,
        local_config: dict[str, Any] | None = None,
        workspace_root: Path | None = None,
    ) -> None:
        self.local_config = dict(local_config or {})
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self._resources: dict[str, Any] = {}

    def _register(self, uri: str, value: Any) -> None:
        self._resources[uri] = copy.deepcopy(value)

    def _style_library(self) -> StyleLibrary:
        configured = lumenflow_config.nested_value(self.local_config, "styles", "roots")
        if configured is None:
            workspace_cards = self.workspace_root / "knowledge" / "style_cards"
            bundled_cards = Path(__file__).resolve().parents[1] / "data" / "style_cards"
            roots = [workspace_cards if workspace_cards.is_dir() else bundled_cards]
        elif isinstance(configured, list) and all(
            isinstance(item, str) and item for item in configured
        ):
            roots = [Path(item) for item in configured]
            roots = [path if path.is_absolute() else self.workspace_root / path for path in roots]
        else:
            raise RuntimeInputError(
                "INVALID_STYLE_ROOTS", "styles.roots must be an array of directory paths"
            )
        return StyleLibrary(roots)

    def _example_store_path(self) -> Path:
        return lumenflow_config.personal_example_store_path(
            self.local_config, repo_root=self.workspace_root
        )

    @staticmethod
    def _workspace_id(path: Path) -> str:
        digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()
        return "workspace_" + digest[:32]

    def read_resource(self, kind: str, identifier: str) -> dict[str, Any]:
        if kind == "styles":
            return self._style_library().get(identifier)
        if kind == "backends":
            return backend_capabilities.backend_capabilities_for(identifier).to_dict()
        uri = f"lumenflow://{kind}/{identifier}"
        try:
            return copy.deepcopy(self._resources[uri])
        except KeyError:
            raise RuntimeInputError(
                "RESOURCE_NOT_FOUND", f"No active runtime resource exists for {uri}"
            ) from None

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

        response = _guard(create)
        if response["ok"]:
            for artifact in response["result"]:
                self._register(
                    f"lumenflow://previews/{artifact['artifact_id']}", artifact
                )
        return response

    def prepare_curation(
        self,
        *,
        source_dir: str,
        output_dir: str,
        date_from: str | None = None,
        date_to: str | None = None,
        per_sheet: int = 20,
        columns: int = 5,
    ) -> ToolResult:
        def prepare() -> dict[str, Any]:
            from ..curation import prepare_workspace

            source = _absolute_path(source_dir, "source_dir")
            output = _absolute_path(output_dir, "output_dir")
            manifest = prepare_workspace(
                source,
                output,
                date_from=date_from,
                date_to=date_to,
                per_sheet=per_sheet,
                columns=columns,
            )
            workspace_id = self._workspace_id(output)
            payload = {
                "workspace_id": workspace_id,
                "resource_uri": f"lumenflow://workspaces/{workspace_id}",
                "manifest_path": str(output / "candidate_manifest.json"),
                "manifest": manifest,
            }
            self._register(payload["resource_uri"], payload)
            return payload

        return _guard(prepare)

    def finalize_curation(
        self,
        *,
        manifest_path: str,
        plan_path: str,
        output_dir: str | None = None,
    ) -> ToolResult:
        def finalize() -> dict[str, Any]:
            from ..curation import finalize_selection

            manifest = _absolute_path(manifest_path, "manifest_path")
            plan = _absolute_path(plan_path, "plan_path")
            output = _absolute_path(output_dir, "output_dir") if output_dir else manifest.parent
            result = finalize_selection(
                manifest_path=manifest,
                plan_path=plan,
                output_dir=output,
            )
            workspace_id = self._workspace_id(output)
            payload = {
                "workspace_id": workspace_id,
                "resource_uri": f"lumenflow://workspaces/{workspace_id}",
                **result,
            }
            self._register(payload["resource_uri"], payload)
            return payload

        return _guard(finalize)

    def search_styles(
        self, *, query: str, purpose: str = "", limit: int = 5
    ) -> ToolResult:
        return _guard(
            lambda: self._style_library().search(
                query=query, purpose=purpose, limit=limit
            )
        )

    def search_examples(
        self,
        *,
        purpose: str = "",
        tags: list[str] | None = None,
        style_id: str | None = None,
        limit: int = 5,
    ) -> ToolResult:
        def search() -> list[dict[str, Any]]:
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
                raise personal_examples.ExampleStoreError(
                    "INVALID_QUERY", "search limit must be between 1 and 20"
                )
            if not purpose.strip() and not (tags or []) and not (style_id or "").strip():
                raise personal_examples.ExampleStoreError(
                    "INVALID_QUERY", "purpose, tags, or style_id is required"
                )
            store_path = self._example_store_path()
            if not store_path.exists():
                return []
            with personal_examples.PersonalExampleStore(store_path) as store:
                return store.search(
                    purpose=purpose,
                    tags=tags,
                    style_id=style_id,
                    limit=limit,
                )

        return _guard(search)

    def store_example(
        self,
        *,
        session: dict[str, Any],
        plan: dict[str, Any],
        receipt: dict[str, Any],
        tags: list[str] | None = None,
    ) -> ToolResult:
        def store() -> dict[str, Any]:
            example = personal_examples.build_personal_example(
                session, plan, receipt, tags=tags or []
            )
            with personal_examples.PersonalExampleStore(
                self._example_store_path()
            ) as example_store:
                return example_store.add(example)

        return _guard(store)

    def compile_edit(
        self,
        *,
        intent: dict[str, Any],
        backend_id: str,
        output_dir: str,
    ) -> ToolResult:
        response = _guard(
            lambda: edit_intent.compile_intent(
                intent,
                backend_id=backend_id,
                output_dir=_absolute_path(output_dir, "output_dir"),
                local_config=self.local_config,
            )
        )
        if response["ok"]:
            plan = response["result"]
            self._register(f"lumenflow://plans/{plan['plan_id']}", plan)
        return response

    def execute_edit(
        self,
        *,
        plan: dict[str, Any],
        allowed_output_dir: str,
        dry_run: bool = True,
        timeout: int | None = 300,
    ) -> ToolResult:
        response = _guard(
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
        if response["ok"]:
            receipt = response["result"]
            self._register(
                f"lumenflow://receipts/{receipt['receipt_id']}", receipt
            )
        return response

    def start_review(
        self, *, intent: dict[str, Any], max_revisions: int = 2
    ) -> ToolResult:
        response = _guard(
            lambda: review.start_review_session(
                intent, max_revisions=max_revisions
            )
        )
        if response["ok"]:
            session = response["result"]
            self._register(
                f"lumenflow://reviews/{session['session_id']}", session
            )
        return response

    def advance_review(
        self,
        *,
        session: dict[str, Any],
        plan: dict[str, Any],
        receipt: dict[str, Any],
        review_result: dict[str, Any],
    ) -> ToolResult:
        response = _guard(
            lambda: review.advance_review_session(
                session, plan, receipt, review_result
            )
        )
        if response["ok"]:
            updated_session = response["result"]["session"]
            self._register(
                f"lumenflow://reviews/{updated_session['session_id']}",
                updated_session,
            )
        return response
