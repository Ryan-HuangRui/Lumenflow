# Architecture Notes

Lumenflow is a set of portable agent skills for RAW photo development and private style-library building. It is not a full photo manager, SaaS app, or standalone editing UI.

## Shape

The repository is organized around:

- `skills/develop-photos/`: agent instructions for photo selection, preview generation, style matching, adjustment-plan authoring, rendering, and review.
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
2. Inspecting preview images and style cards.
3. Choosing style direction.
4. Writing per-photo `adjustment_plan.json`.
5. Reviewing rendered outputs and deciding whether to revise.

The scripts are responsible for deterministic work:

1. Scanning RAW files and sidecar metadata.
2. Creating JPEG previews.
3. Rendering RawTherapee or darktable commands.
4. Fetching subtitles and normalizing transcripts.
5. Generating local tutorial recipes and derived cards.
6. Rebuilding local style-family indexes.

## Photo Pipeline

The intended photo-processing flow is:

1. User points the agent at a source photo directory.
2. `scripts/scan_raws.py` finds RAW files and reads XMP / PP3 selection metadata when present.
3. `scripts/create_previews.py` renders lightweight previews.
4. The agent analyzes the previews and reads style guidance.
5. The agent writes `adjustment_plan.json` using `knowledge/schemas/adjustment_plan.schema.json`.
6. `scripts/render_adjustment_plan.py` converts the plan into temporary RawTherapee `.pp3` profiles and renders outputs.
7. The agent reviews outputs and writes a revision plan when needed.
8. Reports are written for auditability.

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
