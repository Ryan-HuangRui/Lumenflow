---
name: learn-styles
description: Learn and update the local photo style knowledge base from approved social media accounts and color-grading tutorial sources.
---

# Learn Styles

Use this skill when the user asks an agent to update, ingest, refresh, or maintain the photo style library, or when a host scheduler runs the scheduled style update.

## Goal

Maintain `knowledge/` as the durable style source used by the develop-photos skill.

## Sources

Preferred sources:

- X accounts from a user-approved photographer whitelist.
- YouTube color-grading tutorial videos or playlists.
- User-provided Bilibili video links or subtitle/transcript files.
- User-curated reference links.

Instagram is supported only through conservative, explicit whitelist workflows. Do not assume arbitrary followed-account scraping is available.

## Workflow

1. Read source configuration from user input or `knowledge/source_records/`.
2. Fetch or ingest source content.
3. For social photos:
   - Store source metadata and link.
   - Analyze visual style.
   - Write or update source records.
   - Merge abstract style traits into style cards.
4. For tutorials:
   - Get transcript from official APIs, user-provided subtitles, or local ASR.
   - Extract a structured recipe.
   - Generate one video-level style guidance card per successful tutorial.
   - Rebuild the two-layer library: Layer 1 style/method families, Layer 2 video-level tutorial variants.
   - Preserve tuning ideas as tone/color/operation guidance, not fixed preset parameters.
5. Summarize changes and list files updated.

## X Photographer Whitelist Workflow

Use this path when scheduled updates or user requests mention X/Twitter photographer accounts.

Inputs:

- `knowledge/source_records/x_sources.json`, based on `x_sources.example.json`.
- `X_BEARER_TOKEN` in the environment.
- Optional run mode: `--dry-run` before writing records.

Run:

```bash
python scripts/update_x_sources.py --config knowledge/source_records/x_sources.json --dry-run
python scripts/update_x_sources.py --config knowledge/source_records/x_sources.json
```

Behavior:

1. Resolve each whitelisted username through the official X API.
2. Fetch recent posts with media using X API v2 user timeline endpoints.
3. Use `knowledge/source_records/x_sync_state.json` to pass `since_id` on later runs.
4. Write new records as `knowledge/source_records/x_{username}_{post_id}.json`.
5. Leave each new record with `analysis.status=pending_agent_review`.
6. Use the host agent's visual/reasoning ability to summarize media style and update `knowledge/style_cards/*.json`.

Rules:

- Do not use browser login state or cookies as the default path.
- Do not request write scopes; this workflow only needs read access.
- Do not store X API tokens in the repository.
- Keep account lists explicit and user-approved.
- Keep records idempotent: do not rewrite existing `x_{username}_{post_id}.json` files unless the user explicitly asks for refresh.
- Treat third-party readers such as fxtwitter only as a manual fallback for user-provided post URLs, not as the scheduled ingest path.

## Tutorial Source Workflow

Use this path when scheduled updates or user requests mention video tutorials, Bilibili links, YouTube links, or transcript files.

Inputs:

- Local, gitignored `knowledge/source_records/tutorial_sources.json`, copied from `knowledge/source_records/tutorial_sources.example.json`.
- Optional gitignored `config/lumenflow.local.json` for local Cookie path, ASR Python path, cache paths, and model names. Copy from `config/lumenflow.local.example.json`.
- Optional `LUMENFLOW_BILIBILI_COOKIE` or `--cookie-file` for one-off Bilibili subtitle tracks hidden from anonymous requests.
- Optional `.venv-asr` with `requirements-asr.txt` installed for local FunASR subtitle backfill.
- Optional local, gitignored ASR hotword list at `knowledge/source_records/asr_hotwords.txt`, copied from `knowledge/source_records/asr_hotwords.example.txt`.
- Optional run mode: `--dry-run` before writing recipe records.

Run:

```bash
cp knowledge/source_records/tutorial_sources.example.json knowledge/source_records/tutorial_sources.json
cp knowledge/source_records/asr_hotwords.example.txt knowledge/source_records/asr_hotwords.txt
python scripts/update_tutorial_sources.py --config knowledge/source_records/tutorial_sources.json --dry-run
python scripts/update_tutorial_sources.py --config knowledge/source_records/tutorial_sources.json
```

Full weekly refresh command:

```bash
python scripts/update_tutorial_sources.py \
  --config knowledge/source_records/tutorial_sources.json \
  --asr-fallback \
  --asr-discard-audio

python scripts/generate_tutorial_style_cards.py
python scripts/build_style_family_layer.py
python3 -m unittest discover -s tests
```

Run subtitle backfill with local FunASR only when explicitly requested:

```bash
${LUMENFLOW_ASR_PYTHON:-python} scripts/transcribe_bilibili_funasr.py \
  https://www.bilibili.com/video/BVxxxx/

python scripts/update_tutorial_sources.py \
  --config knowledge/source_records/tutorial_sources.json \
  --asr-fallback
```

Refresh video-level style cards after new recipes are created:

```bash
python scripts/generate_tutorial_style_cards.py
python scripts/build_style_family_layer.py
```

Behavior:

1. Read a user-approved tutorial source whitelist.
2. Skip disabled sources and skip existing recipes unless `--force` is passed.
3. For Bilibili collection sources (`platform=bilibili_season`), expand the collection into child video URLs.
4. For Bilibili video sources, call `scripts/fetch_bilibili_subtitles.py` through `scripts/ingest_tutorial.py`.
5. If `--asr-fallback` is explicitly passed and no existing subtitle track is available, call `scripts/transcribe_bilibili_funasr.py` with the ASR Python path from local config, then ingest the generated local transcript.
6. Write transcript files under `knowledge/style_cards/tutorial_recipes/transcripts/`.
7. Write recipe records as `knowledge/style_cards/tutorial_recipes/<platform>_<stable_id>.json`.
8. Leave each new recipe with `status=pending_agent_review` and `style_mapping.merge_status=pending_agent_review`.
9. Run `scripts/generate_tutorial_style_cards.py` to create or refresh one video-level guidance card per tutorial recipe under `knowledge/style_cards/tutorial_derived/`.
10. Run `scripts/build_style_family_layer.py` to assign each video-level card into the Layer 1 library under `knowledge/style_families/` and refresh `knowledge/style_library_index.json`.
11. Treat generated cards as `card_role=style_guidance`: they help the develop-photos agent reason about style, scene fit, tone, color, and operation order.
12. Use Layer 1 for retrieval and scene matching, then inspect Layer 2 tutorial variants for specific color-grading ideas.
13. Use the host agent's reasoning ability to review extracted steps and merge durable traits into approved `knowledge/style_cards/*.json` guidance cards only after review.

Rules:

- Keep source lists explicit and user-approved; do not search or bulk scrape tutorial platforms by default.
- Do not store Bilibili Cookie values in the repository.
- Do not store subtitle URLs as durable provenance because they can include temporary `auth_key` values.
- Do not silently run ASR. If no subtitle track is available, report `no_subtitle_or_cookie_required` unless the user explicitly requested `--asr-fallback`.
- Keep ASR model caches, downloaded audio, and generated wav files out of git. ASR transcripts may be kept when they are needed as recipe provenance.
- Keep generated tutorial transcripts, recipes, tutorial-derived cards, family indexes, and concrete tutorial source whitelists out of public/plugin distributions.
- Use `knowledge/source_records/asr_hotwords.txt` for project-specific Chinese color-grading and Lightroom terminology.
- Treat the deterministic recipe extraction as a first pass only; agent review is required before merging into approved style cards.
- Do not convert tutorial numbers into durable presets. Concrete values belong in per-photo `adjustment_plan.json` files generated by the develop-photos agent after it sees the target photo.
- Keep the tutorial style library two-layered:
  - Layer 1: `knowledge/style_families/*.json`, broad visual/method families for retrieval.
  - Layer 2: `knowledge/style_cards/tutorial_derived/*.json`, one candidate guidance card per successful source video.
  - `knowledge/style_library_index.json` is the routing index used by agents.
- After any tutorial recipe refresh, run `scripts/generate_tutorial_style_cards.py` and `scripts/build_style_family_layer.py` before considering the style library current.
- Keep scheduled jobs idempotent: skip existing recipes by default, then regenerate derived cards and indexes from the full current recipe set.

## Rules

- Do not bulk scrape platforms with unofficial APIs by default.
- Do not store social images as a training dataset.
- Store links, metadata, summaries, visual traits, and embeddings/derived descriptors where appropriate.
- Preserve provenance: every style card update should point back to `source_records` or `tutorial_recipes`.
- Cron runs must be incremental and idempotent.

## Output Files

```text
knowledge/style_cards/*.json
knowledge/style_families/*.json
knowledge/style_library_index.json
knowledge/style_cards/tutorial_derived/*.json
knowledge/style_cards/tutorial_recipes/*.json
knowledge/source_records/*.json
```

## Generated Style Card Contract

Tutorial-derived cards should be guidance material for agent reasoning, not executable profiles:

```json
{
  "schema_version": "lumenflow.style_card.tutorial_derived.v1",
  "card_role": "style_guidance",
  "parameter_strategy": "agent_infers_per_photo",
  "raw_profile_role": "none",
  "raw_profiles": [],
  "tone_guidance": {},
  "color_guidance": {},
  "operation_order": [],
  "adjustment_plan_guidance": {
    "schema_version": "lumenflow.adjustment_plan.v1"
  }
}
```
