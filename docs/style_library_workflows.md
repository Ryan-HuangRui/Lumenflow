# Style Library Workflows

This document fixes the operational contract for the Lumenflow style library.

The library separates reusable knowledge from private source evidence:

- Public reusable knowledge: `knowledge/style_families/*.json`
  Source-agnostic style or method families used for retrieval, filtering, scene matching, and parameter reasoning.
- Private evidence: `knowledge/style_cards/tutorial_recipes/*.json` and `knowledge/style_cards/tutorial_derived/*.json`
  Per-source transcripts, recipes, and intermediate cards used only to rebuild and audit the public knowledge.
- Private provenance: `knowledge/private_provenance/style_source_map.json`
  The ignored mapping from reusable knowledge back to its source records.

`knowledge/style_library_index.json` is the runtime entrypoint. It contains no source identity and tells the agent which reusable cards are active for photo matching and which are method/workflow/reference material only.

## Update Flow

Use this flow for manual refreshes and scheduled jobs.

These source-bearing files are local private data and are ignored by git:

- `knowledge/source_records/tutorial_sources.json`
- `knowledge/source_records/asr_hotwords.txt`
- `knowledge/style_cards/tutorial_recipes/*`
- `knowledge/style_cards/tutorial_derived/*`
- `knowledge/private_provenance/*`

The cleaned outputs under `knowledge/style_families/*.json` and `knowledge/style_library_index.json` are safe to review and commit. The builder fails if source keys, URLs, BVIDs, or source IDs leak into them.

Copy the committed `*.example.*` files before running the flow locally.

```bash
cp knowledge/source_records/tutorial_sources.example.json knowledge/source_records/tutorial_sources.json
cp knowledge/source_records/asr_hotwords.example.txt knowledge/source_records/asr_hotwords.txt

python scripts/update_tutorial_sources.py \
  --config knowledge/source_records/tutorial_sources.json \
  --asr-fallback \
  --asr-discard-audio

python scripts/generate_tutorial_style_cards.py
python scripts/build_style_family_layer.py
python3 -m unittest discover -s tests
```

Step contract:

1. `scripts/update_tutorial_sources.py`
   - Reads approved tutorial source playlists from `knowledge/source_records/tutorial_sources.json`.
   - Reads machine-local paths from `config/lumenflow.local.json` when present.
   - Skips existing recipe records unless `--force` is passed.
   - Fetches official subtitle tracks first.
   - Uses the shared Doubao recording-file ASR when enabled and no usable subtitle track is available.
   - Falls back to local FunASR only when `--asr-fallback` is explicitly passed and Doubao does not complete.
   - Writes recipe records to `knowledge/style_cards/tutorial_recipes/`.
   - Writes transcript provenance under `knowledge/style_cards/tutorial_recipes/transcripts/` or `knowledge/style_cards/tutorial_recipes/asr_transcripts/`.
2. `scripts/generate_tutorial_style_cards.py`
   - Reads every successful recipe.
   - Writes one private evidence card per recipe under `knowledge/style_cards/tutorial_derived/`.
   - Preserves source guidance for classification and audit; these cards are not runtime style knowledge.
3. `scripts/build_style_family_layer.py`
   - Classifies private evidence cards and merges duplicates into semantic families.
   - Writes source-clean reusable cards to `knowledge/style_families/*.json`.
   - Refreshes the source-clean `knowledge/style_library_index.json`.
   - Writes the source mapping to ignored `knowledge/private_provenance/style_source_map.json`.
   - Refreshes `knowledge/style_cards/tutorial_derived/index.md`.
   - Refreshes `knowledge/style_cards/tutorial_recipes/tutorial_recipe_style_summary.md`.
4. Tests
   - Run the full test suite after library rebuilds when the update is done inside the repo.
   - A scheduled job should report source counts, merged knowledge counts, failures, tests, and the public-data leak check.

Rules:

- Do not store Bilibili cookies in the repository.
- Do not store subtitle URLs with temporary auth keys as durable provenance.
- Do not commit generated tutorial transcripts, recipes, tutorial-derived cards, private provenance, or concrete source whitelists.
- Public reusable cards must not contain platform/video IDs, source titles, source URLs, transcript paths, transcript excerpts, timestamps, or source-specific style IDs.
- Do not store ASR audio cache files.
- Do not manually edit private evidence cards unless doing a deliberate review pass; rerun the generator afterward.
- Publish a method tutorial only when it yields reusable method knowledge, with `active_for_photo_matching=false`; keep pure tool demos and non-tutorial references private-only.

## Retrieval Flow

Use this flow when `develop-photos` chooses a style for a target photo.

1. Read `knowledge/style_library_index.json`.
2. Filter direct visual candidates:
   - Include reusable cards with `active_for_photo_matching=true`.
   - Prefer `role=visual_style`.
   - Exclude direct matches where `role` is `method_family`, `workflow_reference`, or `non_style_reference`.
3. Inspect the target preview image.
4. Select one reusable style using the image's subject, light, color problems, scene, and risk profile.
5. Read the selected `knowledge/style_families/<style_id>.json`.
6. Optionally read reusable method cards after the visual direction is chosen:
   - `rgb_curve_method`
   - `mask_local_retouch_method`
   - `reference_color_matching_method`
   - Other inactive method cards
7. Generate `adjustment_plan.json` with:
   - `style_family_id` and `style_id`: the selected reusable semantic id.
   - `source_style_card`: the selected reusable card path.
   - Concrete per-photo parameters inferred from the target preview.
8. Render and review. If the result misses exposure, color, crop, or style strength, revise the plan instead of changing the style library.

Selection rules:

- A photo should usually get one best visual direction.
- Add alternate variants only when multiple families genuinely fit the image.
- Method cards support execution; they should not be the primary visual style.
- Private tutorial values are build-time evidence only and must never be copied into runtime plans.
- The final parameter values belong in `adjustment_plan.json`, not in reusable knowledge cards.

## Current Library Shape

As of the current generated library:

- 162 private tutorial evidence cards classified into 24 semantic groups.
- 22 reusable knowledge cards are published: 18 visual styles and 4 supporting methods.
- 2 non-style/workflow groups remain private-only and are excluded from runtime retrieval.

The authoritative live counts are always in `knowledge/style_library_index.json`.
