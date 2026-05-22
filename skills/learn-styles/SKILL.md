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
