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
the existing `config/lumenflow.local.json` configuration when present. A plugin host can
override that path with `LUMENFLOW_CONFIG`, keep private state under
`LUMENFLOW_DATA_ROOT`, and set the checkout root with `LUMENFLOW_WORKSPACE_ROOT`.

## Lite and Full routing

`lumenflow.status` reports both the resolved RAW engines and the active path policy.
The runtime deliberately starts in **Lite Mode** unless both of these conditions hold:

1. `security.allowed_source_roots` and `security.allowed_output_roots` are non-empty,
   absolute, existing directories.
2. At least one supported RAW engine command resolves to a local executable.

Lite Mode keeps non-photo operations such as status, style search, and private example
search available. Tools that would read photos, materialize profiles, or write exports
fail closed. **Full Mode** enables the RAW editing route, while each requested backend
is still checked independently before use. Curation can run once its file roots are
configured; it does not require a RAW rendering backend.

Example local policy:

```json
{
  "security": {
    "allowed_source_roots": ["/absolute/path/to/RAW photos"],
    "allowed_output_roots": ["/absolute/path/to/Lumenflow output"]
  },
  "tools": {
    "rawtherapee_cli": "rawtherapee-cli",
    "darktable_cli": "darktable-cli"
  }
}
```

Plugin environments may instead provide path-separated
`LUMENFLOW_ALLOWED_SOURCE_ROOTS` and `LUMENFLOW_ALLOWED_OUTPUT_ROOTS` values. JSON config
takes precedence when the corresponding key is present.

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

## Optional MCP Apps UI

Compatible hosts can render three versioned, self-contained UI resources:

| Resource | Linked tools | Purpose |
| --- | --- | --- |
| `ui://lumenflow/runtime-status/v1.html` | `lumenflow.status` | Lite/Full routing, engine readiness, and allowlist summaries |
| `ui://lumenflow/curation/v1.html` | `lumenflow.prepare_curation`, `lumenflow.finalize_curation` | Candidate/sequence inspection, editorial roles, and confirmation state |
| `ui://lumenflow/review/v1.html` | `lumenflow.start_review`, `lumenflow.advance_review` | Bounded revision status and verified plan/receipt/source evidence |

Each resource uses `text/html;profile=mcp-app`, declares empty external CSP domain
allowlists, and communicates through the standards-first `ui/*` JSON-RPC bridge. Tool
metadata uses `_meta.ui.resourceUri`; `openai/outputTemplate` is included only as the
ChatGPT compatibility alias. The documents have no remote JavaScript, stylesheet,
image, frame, or API dependency.

The UI is optional and non-authoritative. All 11 tools keep the same JSON inputs and
structured result envelopes when a host does not render MCP Apps. A curation card cannot
promote an agent proposal to user-confirmed state or invoke RAW execution. A review card
only displays server-validated session/evidence state; accepted/revise/reject transitions
still pass through `lumenflow.advance_review` and its existing contract checks.

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
- Every photo read resolves through an allowed source root; every artifact read or write
  resolves through an allowed output root. Real-path containment prevents `..` and
  symbolic-link escapes.
- Curation skips symbolic-link RAW entries, and finalization revalidates source and
  preview paths embedded inside the candidate manifest.
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

Expected policy failures use stable codes including `ALLOWED_ROOTS_REQUIRED`,
`PATH_NOT_ALLOWED`, `BACKEND_UNAVAILABLE`, and `ABSOLUTE_PATH_REQUIRED`. The allowlist is
an MCP boundary in addition to the core execution-plan checks; it does not weaken the
existing source fingerprint, command reconstruction, or no-overwrite invariants.

## Portable Agent Plugin packaging

The checkout is a portable package with root `plugin.json`, root `mcp.json`, the fixed
`skills/` directory, and the plugin-relative executable
`./scripts/launch_lumenflow_mcp`. `.codex-plugin/plugin.json` and `.mcp.json` retain
compatibility with older Codex plugin loaders.

The launcher never installs dependencies or reads credentials on its own. It chooses the
first Python 3.11+ interpreter containing `mcp` and Pillow from:

1. `${PLUGIN_DATA}/venv/bin/python`
2. `${PLUGIN_ROOT}/.venv/bin/python`
3. `python3` from `PATH`

For an installed local plugin, prepare its private runtime once:

```bash
python3.11 -m venv /absolute/path/to/lumenflow-plugin-data/venv
/absolute/path/to/lumenflow-plugin-data/venv/bin/python -m pip install -e /absolute/path/to/Lumenflow
cp /absolute/path/to/Lumenflow/config/lumenflow.local.example.json \
  /absolute/path/to/lumenflow-plugin-data/lumenflow.local.json
```

Edit the copied config with the actual allowed roots before enabling file-facing tools.
No secret or machine-specific photo path is stored in either plugin manifest.
