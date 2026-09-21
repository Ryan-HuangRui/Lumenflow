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
3. Creating rendered JPEG previews for development and emitting versioned, state-bound preview artifacts.
4. Rendering RawTherapee or darktable commands.
5. Fetching subtitles and normalizing transcripts.
6. Generating private tutorial recipes and evidence cards.
7. Merging source-clean reusable style knowledge and rebuilding its runtime index.

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
6. `scripts/create_previews.py` renders development previews when the embedded previews are insufficient. Its `PreviewProvider` emits `lumenflow.preview_artifact.v1`, binding the exact RAW fingerprint, ordered profile/sidecar fingerprints, starting-state hash, command, and output fingerprint.
7. The agent analyzes confirmed photos and reads style guidance.
8. The agent writes `adjustment_plan.json` using `knowledge/schemas/adjustment_plan.schema.json`.
9. `scripts/render_adjustment_plan.py` converts the plan into temporary RawTherapee `.pp3` profiles and renders outputs.
10. The agent reviews outputs and writes a revision plan when needed.
11. Reports are written for auditability.

Curation scripts deliberately do not score aesthetics. Purpose interpretation, expression, composition, narrative coverage, and sequence rhythm stay with the model; deterministic code keeps file identity and handoff state auditable.

Style cards are guidance only. Concrete values belong in the per-photo adjustment plan because the same style needs different settings on different images.

### Preview boundary

Preview generation is a backend boundary, not a loose JPEG helper. A downstream model may reason from a preview only when the manifest identifies the source bytes and the starting edit state used to render it. RawTherapee is the first provider: a source `.pp3` sidecar is treated as the complete starting state, while a base profile or engine defaults alone are marked partial. Lightroom remains fail-closed until the bridge proves both safe object-level develop reads and state-bound preview generation through a live probe.

### Backend capability boundary

Every backend publishes `lumenflow.backend_capabilities.v1` before later compiler and execution layers make a decision. Capability names and states are closed sets. `supported` permits execution, `unsupported` is a deterministic product limitation, and `unverified` requires runtime evidence rather than fallback or optimistic execution. RawTherapee, Lightroom, and the legacy darktable path declare the same capability keys so orchestration can compare them without backend-specific conditionals.

Lightroom capabilities are derived from the live versioned bridge contract. Protocol or version mismatch invalidates all runtime evidence even when individual capability flags are true. RawTherapee capabilities are static for the current profile-based adapter. Darktable intentionally advertises only `render.legacy` until the isolated dynamic-module spike succeeds.

The darktable feasibility gate is itself versioned as `lumenflow.darktable_probe.v1`. It runs a real RAW export with a temporary config/cache, an in-memory library, and sidecar writes disabled, then compares RAW and sidecar state and fingerprints the output. A command/version check alone is inconclusive. Probe success is necessary evidence but does not itself promote a capability; the state-bound preview provider, compiler, receipt adapter, and regression fixtures must exist before the static contract changes.

### Intent, compilation, and execution

The new runtime path separates model judgment from backend mechanics:

1. `lumenflow.edit_intent.v2` records authorization, exact source and preview-state evidence, purpose, style rationale, vendor-neutral global adjustments, composition, and local-adjustment intent.
2. A backend compiler checks `lumenflow.backend_capabilities.v1` and emits `lumenflow.execution_plan.v1`. Compilation is side-effect free.
3. The executor accepts an explicit allowed output root, revalidates source bytes, backend/compiler versions, artifact paths, embedded profile content, and the exact argv it can reconstruct locally.
4. `lumenflow.execution_receipt.v1` records per-operation outcomes, source before/after fingerprints, verified output bytes, and failure details.

The first compiler targets RawTherapee. It never invokes a shell, refuses output paths outside the caller-approved root, refuses existing output replacement, and rejects a plan whose command or profile payload was modified. `adjustment_plan.v1` remains available as a compatibility renderer while callers migrate; it is not extended with new runtime responsibilities.

## Style Library

Tutorial ingestion separates public reusable knowledge from private evidence:

- Public reusable knowledge: `knowledge/style_families/*.json`
- Private evidence: `knowledge/style_cards/tutorial_recipes/*.json` and `knowledge/style_cards/tutorial_derived/*.json`
- Private source map: `knowledge/private_provenance/style_source_map.json`

The entrypoint is `knowledge/style_library_index.json`.

The reusable cards and source-clean index are generated, reviewable, and tracked. Public repositories should also ship:

- hand-authored starter style cards
- reusable source-agnostic style knowledge
- `knowledge/style_library_index.example.json`
- source config examples
- generation scripts and tests

Transcripts, recipes, video-level evidence cards, source maps, source whitelists, cookies, and ASR caches remain ignored private data.

## Source Strategy

Lumenflow only works from user-approved sources by default.

- Bilibili: fetch exposed subtitles first; use local ASR only when explicitly requested.
- YouTube: prefer official captions or user-provided transcripts.
- X: prefer official API with explicit account whitelist.
- Instagram: avoid default scraping; use explicit authorized sources only.

Do not commit cookies, API tokens, generated transcripts, source whitelists, source maps, video-level evidence cards, or ASR audio caches. Reusable knowledge is commit-safe only after the builder's source-leak validation passes.
