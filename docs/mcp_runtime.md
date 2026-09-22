# Local MCP runtime

Lumenflow exposes its deterministic RAW pipeline as a local Model Context Protocol
(MCP) server. The transport is STDIO: the agent host starts the process locally and
exchanges JSON-RPC messages over standard input/output. RAW files, previews, profiles,
and exports remain on the user's machine.

## Install and start

Python 3.11 or newer is required.

```bash
python -m pip install -e .
lumenflow-mcp
```

The equivalent source-checkout entry point is:

```bash
PYTHONPATH=src python -m lumenflow.mcp.server
```

The server must own standard output, so diagnostics belong on standard error. It reads
the existing `config/lumenflow.local.json` configuration when present.

## Tool surface

The runtime exposes 11 workflow-level tools rather than the hundreds of individual
RAW editor controls:

| Tool | Role | Side effects |
| --- | --- | --- |
| `lumenflow.status` | Report package, transport, engine availability, and declared capabilities | None |
| `lumenflow.prepare_curation` | Scan RAWs, extract embedded previews, and build contact sheets | Creates a curation workspace; never edits RAWs |
| `lumenflow.finalize_curation` | Validate the proposed sequence and package ordered previews | Creates validated plan/report files |
| `lumenflow.create_previews` | Produce state-bound preview evidence for one or more absolute RAW paths | Creates new preview workspace files; never writes beside a RAW implicitly |
| `lumenflow.search_styles` | Rank local semantic style cards for the stated goal | None |
| `lumenflow.search_examples` | Search private, user-accepted edit examples | None; a missing store returns no matches |
| `lumenflow.store_example` | Store a path-redacted example after accepted-evidence revalidation | Writes the private local SQLite store |
| `lumenflow.compile_edit` | Validate and compile `EditIntent v2` to `ExecutionPlan v1` | None |
| `lumenflow.execute_edit` | Revalidate and execute an exact plan | Creates profile/export files only under the explicit allowed output directory |
| `lumenflow.start_review` | Start a bounded review session | None |
| `lumenflow.advance_review` | Bind a `ReviewResult` to the exact plan, receipt, and rendered bytes | None |

The matching MCP resource templates are:

- `lumenflow://styles/{style_id}`
- `lumenflow://workspaces/{workspace_id}`
- `lumenflow://previews/{artifact_id}`
- `lumenflow://receipts/{receipt_id}`
- `lumenflow://reviews/{session_id}`
- `lumenflow://backends/{backend_id}`

Style and backend resources are reproducible from local knowledge. Workspace, preview,
receipt, and review resources reflect artifacts created during the current server
session; their identifiers remain stable inside the underlying contracts.

All tool responses use one envelope:

```json
{"ok": true, "result": {}}
```

Expected, user-correctable failures are returned with stable error codes:

```json
{"ok": false, "error": {"code": "PLAN_COMMAND_MISMATCH", "reason": "..."}}
```

Unexpected implementation failures remain MCP tool errors; they are not converted into
apparently successful results.

## Safety invariants

- File parameters in the MCP surface must be absolute paths.
- A preview call refuses to replace an existing preview.
- Compilation verifies the source fingerprint carried by `EditIntent v2`.
- Execution reconstructs and compares the backend command instead of trusting arbitrary
  `command_argv` supplied by a client.
- The execution plan's output root must equal the explicit `allowed_output_dir`.
- An existing final output is never overwritten.
- The RAW fingerprint is checked before and after rendering and recorded in the
  `ExecutionReceipt`.
- Review only advances with a successful, source-unchanged receipt whose rendered bytes
  still match the receipt fingerprint.
- Only an accepted, exactly bound review can enter personal memory; stored examples omit
  source and output paths and the SQLite database is created with owner-only permissions.

The portable plugin manifests and host-configured allowed source/output roots are added
in a later packaging layer. Until then, callers must pass explicit absolute paths and
the core output-root checks remain authoritative.
