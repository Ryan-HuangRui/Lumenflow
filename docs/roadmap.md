# Roadmap

Lumenflow is a portable agent-skill workflow for personal RAW photo development and private style-library building.

## Principles

- Agent first: the user interacts with an agent host, not a complex CLI.
- Local first: photos, cookies, source lists, transcripts, and generated style libraries stay on the user's machine.
- Guidance over presets: style cards guide reasoning; the agent generates concrete parameters per photo.
- Public-safe defaults: the repository ships code, templates, schemas, tests, and hand-authored starter cards, not third-party-derived style data.
- Small scripts: deterministic work belongs in `scripts/`; judgment belongs in the agent.

## Current Public Shape

The repository should expose:

- `skills/curate-photos/`
- `skills/develop-photos/`
- `skills/learn-styles/`
- `skills/fetch-bilibili-subtitles/`
- `scripts/` helpers for scanning, previewing, rendering, subtitle fetching, tutorial ingestion, and local style-library generation
- `knowledge/schemas/`
- hand-authored starter style cards under `knowledge/style_cards/*.json`
- empty generated-data directories:
  - `knowledge/style_cards/tutorial_recipes/`
  - `knowledge/style_cards/tutorial_derived/`
  - `knowledge/style_families/`
- examples:
  - `config/lumenflow.local.example.json`
  - `knowledge/source_records/tutorial_sources.example.json`
  - `knowledge/source_records/asr_hotwords.example.txt`
  - `knowledge/style_library_index.example.json`

The repository should not expose:

- `config/lumenflow.local.json`
- real source whitelists
- Bilibili or platform cookies
- full generated transcripts
- generated tutorial recipes
- generated tutorial-derived cards
- generated style-family indexes
- downloaded audio, ASR cache, or local render outputs

## Phase 0: Trusted Lightroom Boundary

Goal: prove that Lumenflow can identify and operate the intended Lightroom edit version before enabling automatic writes.

Implemented offline foundation:

- versioned CLI/plugin capability handshake
- fail-closed Lumenflow write preflight
- reserved verified-write command contract with photo identity, state precondition, absolute settings, and operation identity
- local task, approval, photo-instance, state-snapshot, and idempotency records
- legacy Lightroom writes no longer used by Lumenflow

Real-Lightroom gate:

- isolated test catalog with sentinel photos
- UI showing A while a command targets B
- switching selection and concurrent manual-change fault injection
- response-loss and rerun recovery
- independent state/readback/export verification
- zero wrong-photo edits, lost manual edits, or duplicate virtual copies

Until that gate passes, Lightroom non-dry-run editing remains disabled.

## Phase 1: Single-purpose Lightroom Slice

Goal: one existing Lightroom collection becomes one purpose-specific proposal; the user explicitly freezes the confirmed members; only those photos receive isolated initial edits and are handed back to Lightroom.

Scope after the real-Lightroom gate:

- flat managed collections only
- one purpose and one proposal revision
- explicit confirmation separate from collection membership
- work virtual copies with returned identities
- Lightroom-origin previews tied to the starting state
- handoff protection: no automatic in-place edits after the user can take over

Deferred: collection hierarchy, Lightroom navigation, native order synchronization, multiple simultaneous purposes, automatic masks, publishing, and driver migration.

## Existing Local Photo Loop

Goal: process a user-selected RAW folder through an agent-authored adjustment plan.

Implemented foundation:

- RAW scanning and sidecar metadata reading.
- Purpose-aware curation workspace with capture-date filtering, embedded previews, and contact sheets.
- Model-authored selection-plan contract with ordered editorial roles, alternates, edit experiments, and explicit confirmation state.
- Deterministic plan validation and ordered preview packaging without RAW mutation.
- Preview generation.
- Versioned, state-bound `PreviewArtifact` manifests for RawTherapee previews.
- Strict cross-backend capability contracts with fail-closed Lightroom evidence mapping.
- Vendor-neutral `EditIntent v2` plus RawTherapee `ExecutionPlan` and verified `ExecutionReceipt` contracts.
- RawTherapee and isolated legacy darktable command construction.
- A versioned darktable real-RAW feasibility probe that fails closed on source, sidecar, or output-integrity violations.
- Model-authored `ReviewResult` evidence bound to verified output bytes, plus a persisted two-revision refinement loop with replay and cycle protection.
- `adjustment_plan.json` schema.
- Rendering from an agent-authored plan.
- Processing records and Markdown reporting.
- Local configuration through `config/lumenflow.local.json`.

Maintenance work:

- Expand RawTherapee `.pp3` parameter coverage.
- Add EditIntent v2 compilers only after each backend advertises the required capabilities.
- Rerun the darktable feasibility probe after a trusted Gatekeeper-compatible installation is available; keep the backend legacy-only until the provider/compiler/receipt gates also pass.
- Expand review categories only when benchmark evidence shows the current contract is insufficient.
- Add more fixture coverage for adjustment-plan edge cases.
- Improve failure messages when external tools are missing.

## Phase 2: Style Knowledge Contract

Goal: keep the style library stable and useful across agent hosts.

Implemented foundation:

- Hand-authored starter style cards.
- Tutorial-derived card schema in generator output.
- Two-layer library build script for local generated data.
- Example style-library index.

Next work:

- Add a committed JSON schema for starter style cards.
- Add a committed JSON schema for tutorial recipes.
- Add a committed JSON schema for source records.
- Document how an agent should select between starter cards and local tutorial-derived cards.
- Add a compact local index format suitable for plugin distribution.

## Phase 3: Tutorial Ingestion

Goal: let users build a private tutorial-derived style library from approved links.

Implemented foundation:

- Bilibili subtitle fetcher.
- Local FunASR fallback script.
- Tutorial ingestion into local recipe files.
- Video-level style-card generation.
- Layer 1 family/index generation.
- Example source and hotword configs.

Next work:

- Add provider abstraction for YouTube captions and user-provided transcript files.
- Add stricter quality flags for weak ASR, non-tutorial content, and low-signal transcripts.
- Add a review workflow for accepting or rejecting generated cards.
- Keep generated outputs ignored by default for public/plugin distributions.

## Phase 4: Social Source Records

Goal: let users maintain private source records from approved creator accounts.

Next work:

- Keep source configuration local and ignored.
- Prefer official APIs and explicit account whitelists.
- Store source links, metadata, and abstract style observations.
- Avoid copying third-party media into the repository.
- Keep agent review as the step that merges observations into style cards.

## Phase 5: Agent Host Packaging

Goal: make Lumenflow easy to install as a skill/plugin.

Next work:

- Add packaging metadata for target agent hosts.
- Keep local setup instructions short and explicit.
- Validate a clean clone with no private generated data.
- Add a public release checklist:
  - no local config
  - no real source lists
  - no generated transcripts
  - no generated third-party style cards
  - tests pass

## Non-Goals

Short-term non-goals:

- Full photo management UI.
- SaaS sync service.
- Large-scale scraping.
- Model training.
- Replacing Lightroom, darktable, or RawTherapee as a full editor.
- Publishing third-party-derived style libraries.
