"""MCP server exposing Lumenflow's minimal RAW development vertical slice."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .. import config as lumenflow_config
from .runtime import LumenflowRuntime


def create_server(
    *,
    local_config: dict[str, Any] | None = None,
    local_config_path: Path | None = lumenflow_config.DEFAULT_LOCAL_CONFIG_PATH,
    workspace_root: Path | None = None,
) -> MCPServer:
    """Create an MCP server without performing I/O on import."""

    runtime = LumenflowRuntime(
        local_config=(
            local_config
            if local_config is not None
            else lumenflow_config.read_local_config(local_config_path)
        ),
        workspace_root=workspace_root,
    )
    server = MCPServer(
        name="lumenflow",
        title="Lumenflow Local RAW Runtime",
        version="0.1.0",
        instructions=(
            "Use previews as visual evidence, compile a user-authorized EditIntent v2, "
            "execute only its validated plan, then review the verified output receipt."
        ),
    )

    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    workspace_write = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
    workspace_replace = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True,
    )

    @server.tool(
        name="lumenflow.status",
        description="Inspect local RAW engine availability and declared capabilities.",
        annotations=read_only,
    )
    def status() -> dict[str, Any]:
        return runtime.status()

    @server.tool(
        name="lumenflow.prepare_curation",
        description=(
            "Scan a RAW directory, extract embedded previews, and build contact sheets for visual curation."
        ),
        annotations=workspace_replace,
    )
    def prepare_curation(
        source_dir: str,
        output_dir: str,
        date_from: str | None = None,
        date_to: str | None = None,
        per_sheet: int = 20,
        columns: int = 5,
    ) -> dict[str, Any]:
        return runtime.prepare_curation(
            source_dir=source_dir,
            output_dir=output_dir,
            date_from=date_from,
            date_to=date_to,
            per_sheet=per_sheet,
            columns=columns,
        )

    @server.tool(
        name="lumenflow.finalize_curation",
        description=(
            "Validate an agent-authored selection plan and package its ordered preview sequence."
        ),
        annotations=workspace_replace,
    )
    def finalize_curation(
        manifest_path: str,
        plan_path: str,
        output_dir: str | None = None,
    ) -> dict[str, Any]:
        return runtime.finalize_curation(
            manifest_path=manifest_path,
            plan_path=plan_path,
            output_dir=output_dir,
        )

    @server.tool(
        name="lumenflow.create_previews",
        description=(
            "Create state-bound previews for absolute RAW paths under an explicit output directory."
        ),
        annotations=workspace_write,
    )
    def create_previews(
        backend_id: str,
        source_paths: list[str],
        output_dir: str,
        base_profile_paths: dict[str, str] | None = None,
        dry_run: bool = False,
        timeout: int | None = 120,
        selection_reason: str = "",
    ) -> dict[str, Any]:
        return runtime.create_previews(
            backend_id=backend_id,
            source_paths=source_paths,
            output_dir=output_dir,
            base_profile_paths=base_profile_paths,
            dry_run=dry_run,
            timeout=timeout,
            selection_reason=selection_reason,
        )

    @server.tool(
        name="lumenflow.search_styles",
        description="Rank local semantic style cards for a visual goal and stated purpose.",
        annotations=read_only,
    )
    def search_styles(
        query: str, purpose: str = "", limit: int = 5
    ) -> dict[str, Any]:
        return runtime.search_styles(query=query, purpose=purpose, limit=limit)

    @server.tool(
        name="lumenflow.search_examples",
        description="Search private, user-accepted edit examples without exposing source paths.",
        annotations=read_only,
    )
    def search_examples(
        purpose: str = "",
        tags: list[str] | None = None,
        style_id: str | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        return runtime.search_examples(
            purpose=purpose,
            tags=tags,
            style_id=style_id,
            limit=limit,
        )

    @server.tool(
        name="lumenflow.store_example",
        description=(
            "Persist one accepted edit only after session, plan, receipt, and output bytes revalidate."
        ),
        annotations=workspace_write,
    )
    def store_example(
        session: dict[str, Any],
        plan: dict[str, Any],
        receipt: dict[str, Any],
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        return runtime.store_example(
            session=session,
            plan=plan,
            receipt=receipt,
            tags=tags,
        )

    @server.tool(
        name="lumenflow.compile_edit",
        description="Compile EditIntent v2 into a deterministic backend execution plan.",
        annotations=read_only,
    )
    def compile_edit(
        intent: dict[str, Any], backend_id: str, output_dir: str
    ) -> dict[str, Any]:
        return runtime.compile_edit(
            intent=intent, backend_id=backend_id, output_dir=output_dir
        )

    @server.tool(
        name="lumenflow.execute_edit",
        description=(
            "Validate and execute a compiled plan inside its explicit allowed output directory."
        ),
        annotations=workspace_write,
    )
    def execute_edit(
        plan: dict[str, Any],
        allowed_output_dir: str,
        dry_run: bool = True,
        timeout: int | None = 300,
    ) -> dict[str, Any]:
        return runtime.execute_edit(
            plan=plan,
            allowed_output_dir=allowed_output_dir,
            dry_run=dry_run,
            timeout=timeout,
        )

    @server.tool(
        name="lumenflow.start_review",
        description="Start a bounded review session for an EditIntent v2 document.",
        annotations=read_only,
    )
    def start_review(
        intent: dict[str, Any], max_revisions: int = 2
    ) -> dict[str, Any]:
        return runtime.start_review(intent=intent, max_revisions=max_revisions)

    @server.tool(
        name="lumenflow.advance_review",
        description=(
            "Advance review using an exactly bound plan, verified receipt, and ReviewResult."
        ),
        annotations=read_only,
    )
    def advance_review(
        session: dict[str, Any],
        plan: dict[str, Any],
        receipt: dict[str, Any],
        review_result: dict[str, Any],
    ) -> dict[str, Any]:
        return runtime.advance_review(
            session=session,
            plan=plan,
            receipt=receipt,
            review_result=review_result,
        )

    @server.resource(
        "lumenflow://styles/{style_id}",
        name="Lumenflow style card",
        description="Full local semantic style card by stable style id.",
        mime_type="application/json",
    )
    def style_resource(style_id: str) -> dict[str, Any]:
        return runtime.read_resource("styles", style_id)

    @server.resource(
        "lumenflow://workspaces/{workspace_id}",
        name="Lumenflow curation workspace",
        description="Curation workspace created during this runtime session.",
        mime_type="application/json",
    )
    def workspace_resource(workspace_id: str) -> dict[str, Any]:
        return runtime.read_resource("workspaces", workspace_id)

    @server.resource(
        "lumenflow://previews/{artifact_id}",
        name="Lumenflow preview artifact",
        description="State-bound preview evidence created during this runtime session.",
        mime_type="application/json",
    )
    def preview_resource(artifact_id: str) -> dict[str, Any]:
        return runtime.read_resource("previews", artifact_id)

    @server.resource(
        "lumenflow://receipts/{receipt_id}",
        name="Lumenflow execution receipt",
        description="Verified execution receipt created during this runtime session.",
        mime_type="application/json",
    )
    def receipt_resource(receipt_id: str) -> dict[str, Any]:
        return runtime.read_resource("receipts", receipt_id)

    @server.resource(
        "lumenflow://reviews/{session_id}",
        name="Lumenflow review session",
        description="Current bounded review state created during this runtime session.",
        mime_type="application/json",
    )
    def review_resource(session_id: str) -> dict[str, Any]:
        return runtime.read_resource("reviews", session_id)

    @server.resource(
        "lumenflow://backends/{backend_id}",
        name="Lumenflow backend capability contract",
        description="Static capability contract for a named RAW backend.",
        mime_type="application/json",
    )
    def backend_resource(backend_id: str) -> dict[str, Any]:
        return runtime.read_resource("backends", backend_id)

    return server


def main() -> None:
    """Run the local MCP server over standard input/output."""

    create_server().run()


if __name__ == "__main__":
    main()
