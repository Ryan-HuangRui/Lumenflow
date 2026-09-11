# Architecture Notes

Lumenflow is a set of portable agent skills for RAW photo development and private style-library building. It is not a full photo manager, SaaS app, or standalone editing UI.

## Shape

The repository is organized around:

- `skills/curate-photos/`: agent instructions for purpose-aware visual culling, duplicate comparison, editorial roles, sequencing, and user confirmation.
- `skills/develop-photos/`: agent instructions for preview generation, style matching, adjustment-plan authoring, rendering, and review of confirmed photos.
- `skills/learn-styles/`: agent instructions for building a local private style library from user-approved sources.
- `skills/fetch-bilibili-subtitles/`: a narrow skill for downloading existing Bilibili subtitles.
- `scripts/`: small reusable tools called by skills.
- `knowledge/`: local style knowledge, schemas, and source-record templates.
- `config/lumenflow.local.example.json`: template for machine-local configuration.

Generated tutorial data is intentionally local-only. Public distributions should include generators, schemas, templates, and empty directories, not third-party transcript-derived style libraries.

## Runtime Model

The agent host is the orchestrator. It may be Codex, Claude, OpenClaw, or another local-tool-capable agent runtime.

The host is responsible for:

1. Reading the skill instructions.
2. Inspecting every in-scope curation preview with native visual reasoning.
3. Interpreting purpose, choosing photos, and authoring the editorial sequence.
4. Inspecting confirmed-photo previews and style cards.
5. Choosing style direction and writing per-photo `adjustment_plan.json`.
6. Reviewing rendered outputs and deciding whether to revise.

The scripts are responsible for deterministic work:

1. Scanning RAW files and sidecar metadata.
2. Extracting embedded JPEG previews, generating contact sheets, and validating selection plans.
3. Creating rendered JPEG previews for development.
4. Rendering RawTherapee or darktable commands.
5. Fetching subtitles and normalizing transcripts.
6. Generating local tutorial recipes and derived cards.
7. Rebuilding local style-family indexes.

## Lightroom Safety Boundary

Lightroom is the intended review and handoff UI, but command availability is not treated as proof that an operation is safe. Before any non-dry-run edit, `scripts/driver_adapter.py` requires a versioned bridge contract with protocol `2`, matching CLI/plugin versions, and verified `safe_object_develop_write` and `verified_export_result` capabilities.

The current bridge advertises these capabilities as false. This deliberately keeps automatic writes disabled while offline work continues. The reserved `develop.applySettingsVerified` contract requires an exact photo instance ID, a frozen starting-state hash, an absolute settings object, and a stable operation ID; its plugin handler fails with `CAPABILITY_NOT_VERIFIED` until a real Lightroom probe proves the implementation.

The legacy `develop.applySettings` command remains available for compatibility in the driver repository, but Lumenflow no longer uses it for automatic editing.

## Workflow State

`adjustment_plan` describes only one photo's absolute edit targets and rationale. Cross-photo and mutable workflow state lives in the local SQLite store implemented by `scripts/task_store.py`:

- task purpose and input scope
- selection proposal revision
- immutable user approval snapshot
- catalog/photo-instance binding
- develop-state snapshot and completeness
- idempotent operation intent, result, and unknown outcome

The default database is `local/lumenflow_tasks.sqlite3`, which is ignored by git. Reusing an idempotency key for a different request is rejected. A lost response is recorded as `unknown` and returned on retry rather than being silently reissued.

## Photo Pipeline

The intended photo-processing flow is:

1. User points the agent at a source photo directory.
2. `scripts/curate_photos.py prepare` scans RAW files, applies hard scope such as capture dates, extracts camera previews, and builds labeled contact sheets.
3. The host agent inspects the complete candidate set with native vision, groups near-duplicates, matches the user's purpose, and writes an ordered `selection_plan.json`.
4. `scripts/curate_photos.py finalize` validates candidate identity, order, roles, reasons, alternates, and the no-RAW-mutation invariant.
5. The user explicitly confirms membership and order; only the confirmed set crosses into development.
6. `scripts/create_previews.py` renders development previews when the embedded previews are insufficient.
7. The agent analyzes confirmed photos and reads style guidance.
8. The agent writes `adjustment_plan.json` using `knowledge/schemas/adjustment_plan.schema.json`.
9. `scripts/render_adjustment_plan.py` converts the plan into temporary RawTherapee `.pp3` profiles and renders outputs.
10. The agent reviews outputs and writes a revision plan when needed.
11. Reports are written for auditability.

Curation scripts deliberately do not score aesthetics. Purpose interpretation, expression, composition, narrative coverage, and sequence rhythm stay with the model; deterministic code keeps file identity and handoff state auditable.

Style cards are guidance only. Concrete values belong in the per-photo adjustment plan because the same style needs different settings on different images.

## Style Library

The style library has two layers when tutorial ingestion is used locally:

- Layer 1: `knowledge/style_families/*.json`
- Layer 2: `knowledge/style_cards/tutorial_derived/*.json`

The entrypoint is `knowledge/style_library_index.json`.

These files are generated private data and are ignored by git by default. Public repositories should ship only:

- hand-authored starter style cards
- empty directory placeholders
- `knowledge/style_library_index.example.json`
- source config examples
- generation scripts and tests

## Source Strategy

Lumenflow only works from user-approved sources by default.

- Bilibili: fetch exposed subtitles first; use local ASR only when explicitly requested.
- YouTube: prefer official captions or user-provided transcripts.
- X: prefer official API with explicit account whitelist.
- Instagram: avoid default scraping; use explicit authorized sources only.

Do not commit cookies, API tokens, generated transcripts, source whitelists, ASR audio caches, or generated third-party-derived style libraries.
