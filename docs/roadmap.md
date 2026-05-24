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

## Phase 1: Local Photo Loop

Goal: process a user-selected RAW folder through an agent-authored adjustment plan.

Implemented foundation:

- RAW scanning and sidecar metadata reading.
- Preview generation.
- RawTherapee and darktable command construction.
- `adjustment_plan.json` schema.
- Rendering from an agent-authored plan.
- Processing records and Markdown reporting.
- Local configuration through `config/lumenflow.local.json`.

Next work:

- Expand RawTherapee `.pp3` parameter coverage.
- Improve render-review notes and revision-loop output.
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
