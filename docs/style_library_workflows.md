# Style Library Workflows

This document fixes the operational contract for the Lumenflow style library.

The library has two layers:

- Layer 1: `knowledge/style_families/*.json`
  Broad style or method families used for retrieval, filtering, and scene matching.
- Layer 2: `knowledge/style_cards/tutorial_derived/*.json`
  One video-level guidance card per successful tutorial source.

`knowledge/style_library_index.json` is the entrypoint for agents. It tells the agent where the two layers live, which families are active for photo matching, and which cards are method/workflow/reference material only.

## Update Flow

Use this flow for manual refreshes and scheduled jobs.

For public/plugin distribution, the files produced by this flow are local private data and are ignored by git:

- `knowledge/source_records/tutorial_sources.json`
- `knowledge/source_records/asr_hotwords.txt`
- `knowledge/style_cards/tutorial_recipes/*`
- `knowledge/style_cards/tutorial_derived/*`
- `knowledge/style_families/*`
- `knowledge/style_library_index.json`

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
   - Uses local FunASR only when `--asr-fallback` is explicitly passed and no usable subtitle track is available.
   - Writes recipe records to `knowledge/style_cards/tutorial_recipes/`.
   - Writes transcript provenance under `knowledge/style_cards/tutorial_recipes/transcripts/` or `knowledge/style_cards/tutorial_recipes/asr_transcripts/`.
2. `scripts/generate_tutorial_style_cards.py`
   - Reads every successful recipe.
   - Writes one Layer 2 card per recipe under `knowledge/style_cards/tutorial_derived/`.
   - Preserves tutorial guidance as reasoning material, not fixed preset parameters.
3. `scripts/build_style_family_layer.py`
   - Assigns each Layer 2 card to a Layer 1 family.
   - Writes `knowledge/style_families/*.json`.
   - Refreshes `knowledge/style_library_index.json`.
   - Refreshes `knowledge/style_cards/tutorial_derived/index.md`.
   - Refreshes `knowledge/style_cards/tutorial_recipes/tutorial_recipe_style_summary.md`.
4. Tests
   - Run the full test suite after library rebuilds when the update is done inside the repo.
   - A scheduled job should at least report counts, failures, and whether the Layer 1/Layer 2 consistency check passed.

Rules:

- Do not store Bilibili cookies in the repository.
- Do not store subtitle URLs with temporary auth keys as durable provenance.
- Do not commit generated tutorial transcripts, recipes, tutorial-derived cards, family indexes, or concrete source whitelists to public/plugin distributions.
- Do not store ASR audio cache files.
- Do not manually edit generated Layer 2 cards unless doing a deliberate review pass; rerun the generator afterward.
- If a source is a tool demo, method tutorial, or non-tutorial reference, keep it in the library but set `active_for_photo_matching=false` through the Layer 1 build step.

## Retrieval Flow

Use this flow when `develop-photos` chooses a style for a target photo.

1. Read `knowledge/style_library_index.json`.
2. Filter direct visual candidates:
   - Include families with `active_for_photo_matching=true`.
   - Prefer `role=visual_style`.
   - Exclude direct matches where `role` is `method_family`, `workflow_reference`, or `non_style_reference`.
3. Inspect the target preview image.
4. Select a Layer 1 family using the image's subject, light, color problems, scene, and risk profile.
5. Read the selected `knowledge/style_families/<style_family_id>.json`.
6. Inspect representative Layer 2 variants from that family.
7. Pick one best Layer 2 tutorial card when a specific variant fits the photo. If no variant fits cleanly, use only the Layer 1 family guidance.
8. Optionally read method cards after the visual direction is chosen:
   - `rgb_curve_method`
   - `mask_local_retouch_method`
   - `reference_color_matching_method`
   - Other inactive method/workflow cards
9. Generate `adjustment_plan.json` with:
   - `style_family_id`: the selected Layer 1 family.
   - `style_id`: the selected Layer 2 card id when one is used, otherwise the Layer 1 family id.
   - `source_style_card`: the Layer 2 card path when used.
   - Concrete per-photo parameters inferred from the target preview.
10. Render and review. If the result misses exposure, color, crop, or style strength, revise the plan instead of changing the style library.

Selection rules:

- A photo should usually get one best visual direction.
- Add alternate variants only when multiple families genuinely fit the image.
- Method cards support execution; they should not be the primary visual style.
- Tutorial values are examples and reasoning evidence. The agent must not copy transcript numbers blindly.
- The final parameter values belong in `adjustment_plan.json`, not in style families or tutorial cards.

## Current Library Shape

As of the current generated library:

- 154 Layer 2 tutorial-derived cards.
- 24 Layer 1 style/method families.
- 140 cards active for direct photo matching.
- 14 cards retained as method, workflow, or non-style references.

The authoritative live counts are always in `knowledge/style_library_index.json`.
