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
   - Link recipe to an existing style card or create a new candidate style card.
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

## Rules

- Do not bulk scrape platforms with unofficial APIs by default.
- Do not store social images as a training dataset.
- Store links, metadata, summaries, visual traits, and embeddings/derived descriptors where appropriate.
- Preserve provenance: every style card update should point back to `source_records` or `tutorial_recipes`.
- Cron runs must be incremental and idempotent.

## Output Files

```text
knowledge/style_cards/*.json
knowledge/tutorial_recipes/*.json
knowledge/source_records/*.json
```
