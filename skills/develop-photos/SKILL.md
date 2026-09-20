---
name: develop-photos
description: Develop and style user-confirmed or explicitly specified RAW photos with agent judgment, the local style knowledge base, and a RAW editing CLI such as RawTherapee, darktable, or Lightroom.
---

# Develop Photos

Use this skill when the user asks an agent to process, grade, color, render, export, or batch-edit RAW photos in a local directory.

## Goal

Turn a user request like:

```text
帮我处理 /path/to/photos 里的照片，输出到 /path/to/output
```

into:

1. A confirmed selection plan or an explicit user-specified photo set.
2. JPEG previews that the host agent can inspect visually.
3. Agent-authored per-photo `EditIntent v2` documents based on the two-layer style library.
4. Rendered JPG outputs through RawTherapee CLI by default, or Lightroom when explicitly selected and available.
5. Agent review of rendered outputs, with revised plans when needed.
6. A processing report explaining what happened.

## Workflow

1. Parse the user's source directory. If the user does not provide an output directory, use `photos.output_root` from `config/lumenflow.local.json` and create `<photos.output_root>/<source directory name>/`.
2. Resolve the edit set before scanning:
   - Prefer a `curate-photos` selection plan with `status.decision=user_confirmed`.
   - Accept a direct file list or explicit folder-wide instruction from the user.
   - Do not edit a curation proposal whose status is still `agent_recommended_pending_user_confirmation`.
3. Scan the confirmed RAW files with `scripts/scan_raws.py`. When the user explicitly chose an existing editor selection, honor:
   - darktable `<raw filename>.xmp` rating/color labels if available.
   - RawTherapee `<raw filename>.pp3` rank if available.
   - If the user wants the agent to choose from an uncurated folder, invoke `curate-photos` first.
4. Generate previews with `scripts/create_previews.py`.
5. Read `preview_manifest.json` before visual analysis. Each entry must use `lumenflow.preview_artifact.v1`; retain its `artifact_id`, `source_fingerprint`, `starting_state_hash`, and `state_completeness` with downstream plan/review evidence. A partial starting state is usable for RawTherapee drafting but must not be represented as a complete editor-state snapshot.
6. Inspect the preview images with the host agent's vision/reasoning capability.
7. Read the selected backend's `lumenflow.backend_capabilities.v1` contract and require the operation needed for the current stage. Stop on `unsupported`, and stop for real verification on `unverified`; do not silently choose a different backend when the user selected one explicitly.
8. Retrieve style guidance from the two-layer style library:
   - Read `knowledge/style_library_index.json` first.
   - Filter direct candidates to entries with `active_for_photo_matching=true`.
   - Choose a Layer 1 family from `knowledge/style_families/*.json`.
   - Inspect matching Layer 2 video variants from `knowledge/style_cards/tutorial_derived/*.json` only after the Layer 1 direction fits the photo.
   - Use method/workflow cards only as supporting execution guidance, not as the primary visual style.
9. Choose the best style per photo. If more than one direction is genuinely appropriate, create multiple variants.
10. Decide composition before rendering. This is a per-photo judgment, not a batch preset:
   - Keep original framing when the composition is already intentional.
   - Preserve detected existing crops by default unless the user explicitly asks to change them.
   - Crop only when it removes clear distractions, strengthens the subject, or fixes a weak frame.
   - Record `composition.decision` as `preserve_existing_crop`, `no_crop`, `crop`, or `manual_recommendation`.
   - Record the framing reason in `composition.reason`; crop executions should also include `composition.crop.reason`.
   - Use pixel crop values when the crop should be executed by RawTherapee; otherwise record a recommendation for manual/future implementation.
11. Decide local adjustments before rendering. Record `local_adjustments.decision` as `none`, `use_masks`, or `manual_recommendation`. If `use_masks`, include requested masks; the compiler must still reject them when the selected backend lacks verified `mask.ai` capability. If no mask is needed, explain why in `local_adjustments.reason`.
12. Write one vendor-neutral `EditIntent v2` per RAW using `knowledge/schemas/edit_intent.schema.json`. Bind it to the confirmed authorization reference, source fingerprint, preview artifact id, and starting-state hash.
13. Compile the intent with `scripts/edit_intent.py compile`. The compiler must produce `lumenflow.execution_plan.v1` without writing a profile or rendered image.
14. Execute the plan with `scripts/edit_intent.py execute`, passing the exact allowed output directory. Preserve the resulting `lumenflow.execution_receipt.v1` for review. Use `scripts/render_adjustment_plan.py` only for existing `adjustment_plan.v1` compatibility inputs.
15. Review rendered outputs with the host agent's vision/reasoning capability:
    - exposure and highlight clipping
    - blocked shadows
    - color cast and skin/subject color
    - style strength
    - crop quality and whether important context was lost
    - obvious rendering artifacts
16. Write `lumenflow.review_result.v1`, binding the current intent revision, plan, receipt, and output fingerprint. Use `accept`, `revise`, or `reject`; a revision may replace only style, global adjustments, composition, or local-adjustment intent.
17. Advance the persisted session with `scripts/review_loop.py`. Default to at most two revisions. Do not bypass `revision_limit_reached`, replay a review id, or recreate an earlier semantic intent.
18. For `revise`, compile and execute the emitted next intent, inspect the new verified output, and repeat. Write final execution receipts, session state, processing report, and review notes when the session reaches a terminal state.
19. For benchmark runs, write a `lumenflow.visual_assessment.v1` only after inspecting the exact output fingerprint, then use `scripts/benchmark_eval.py record`. Do not assign a visual score to a failed or dry-run execution, and do not omit failed cases from the aggregate report.

Typical command:

```bash
python scripts/create_previews.py /path/to/photos
python scripts/edit_intent.py compile /path/to/IMG_001.edit_intent.json --backend rawtherapee --output-dir /path/to/output --plan-output /path/to/output/IMG_001.execution_plan.json
python scripts/edit_intent.py execute /path/to/output/IMG_001.execution_plan.json --allowed-output-dir /path/to/output --receipt-output /path/to/output/IMG_001.execution_receipt.json
python scripts/review_loop.py start /path/to/IMG_001.edit_intent.json --state-output /path/to/output/IMG_001.review_session.json
python scripts/review_loop.py advance /path/to/output/IMG_001.review_session.json /path/to/output/IMG_001.execution_plan.json /path/to/output/IMG_001.execution_receipt.json /path/to/output/IMG_001.review_result.json --state-output /path/to/output/IMG_001.review_session.json --next-intent-output /path/to/output/IMG_001.edit_intent.r2.json
```

With `photos.output_root` set to `/photo-output-root`, a source such as `/photo-source/negative_raw/2026五一港珠澳/P1034473.RW2` renders into `/photo-output-root/2026五一港珠澳/`.

`scripts/develop_photos.py` is a legacy/debug batch path for applying fixed profiles. Do not use it as the main agent workflow when visual analysis and per-photo parameters are available.

## Engine Selection

Default to RawTherapee unless the user explicitly asks for Lightroom, the plan requires executable Lightroom AI masks, or the source workflow is already organized around Lightroom catalog selections.

The `EditIntent v2` compiler currently supports RawTherapee only. Lightroom inputs remain on the fail-closed `adjustment_plan.v1` compatibility path until the Lightroom v2 compiler and state-bound preview probe are implemented; do not silently translate a v2 intent into legacy Lightroom commands.

darktable is also legacy-only. Do not infer first-class capability from an installed command. Before considering backend promotion, run `scripts/darktable_probe.py` against a disposable sentinel RAW and require a `passed` `lumenflow.darktable_probe.v1` report. Probe success is necessary but not sufficient: the state-bound preview provider and EditIntent compiler must also exist.

Use RawTherapee when:

- The user wants unattended local RAW rendering.
- The source photos are just files in a folder and may not be in a Lightroom catalog.
- The plan needs executable crop through the current Lumenflow profile path.

Use Lightroom only when all of these are true:

- Lightroom Classic is open.
- `Lightroom CLI Bridge` is installed and started.
- `lr system ping` succeeds.
- The target RAW is already in the Lightroom catalog, or the plan provides `lightroom.photo_id`.
- The user accepts that Lightroom rendering mutates Lightroom catalog develop state before export.

Before a real Lightroom render, run:

```bash
lr system ping
```

For dry-run validation, use:

```bash
python scripts/render_adjustment_plan.py /path/to/plan.json --engine lightroom --dry-run
```

Do not silently fall back from Lightroom to RawTherapee when the user explicitly requested Lightroom. Report the bridge/catalog problem instead.

## Lightroom Operational Pitfalls

Use this checklist whenever the request requires editable Lightroom state, not just exported JPGs:

- Treat Lightroom as an interactive catalog backend, not a headless RAW renderer. The final editable result must be written into the Lightroom catalog.
- If the user wants to continue editing in Lightroom, do not use RawTherapee fallback as the final output. RawTherapee output can be used only as a preview/reference unless the user accepts that the result is no longer Lightroom-editable RAW develop state.
- Prefer preserving the user's existing Lightroom edits by creating a snapshot or virtual copy before applying a substantial automated edit, especially when the request is exploratory or may need comparison.
- Verify Bridge health before execution. If `lr system ping` fails, check whether the `Lightroom CLI Bridge` plugin is installed and started; if Lightroom was restarted, the plugin may need to be started again from Lightroom's plugin/menu action before commands work.
- `lr` may be unavailable even when the Bridge plugin exists. In that case, use the configured Lightroom CLI path or the local Bridge transport supported by the environment; do not assume Lightroom itself is unavailable until Bridge health has been checked.
- Resolve and record `lightroom.photo_id` before writing develop settings. If catalog lookup fails, report that the source RAW is missing from the catalog or cannot be resolved by path.
- If export fails with a missing/corrupt original-photo style error, first check the Lightroom catalog file link and source RAW path. Do not interpret that error as proof that develop settings failed.
- Do not judge success from Library/Grid thumbnails alone. Lightroom Library previews can lag and may still look like the original. Verify in Develop module, by reading back key develop values when possible, and by exporting a fresh verification contact sheet.
- Prefer applying settings while the target photo is active in Develop module, then read back or export to verify. Batch execution is acceptable for applying already-decided settings, but not for judging composition, masks, or local color moves.
- If a written edit appears unchanged, inspect the exact selected photo id/name before retrying. A stale selection, stale thumbnail, or wrong active photo can look like a failed edit.
- Do not trust Lightroom AI mask batch success as proof that the mask is on the right image. The current Bridge batch path can switch selection and immediately call `createNewMask`; Lightroom may still use a stale Develop/Masking context and write a subject or sky mask to the wrong photo.
- Treat Lightroom AI masks as experimental unless each mask is created while the target photo is active, followed by overlay inspection or reliable mask readback for that exact photo. If that verification is not possible, record the local edit as `mask_decision=manual_recommendation` and keep only global Lightroom settings executable.

## Per-Photo Judgment Contract

Batching is allowed for execution, not for judgment. The agent may batch scan, preview generation, Lightroom id lookup, grouped global setting writes, and export, but must make these decisions per photo:

- composition: preserve existing crop, no crop, crop, or manual recommendation.
- local adjustments: no mask, executable Lightroom AI mask, or manual recommendation.
- review outcome: accept or revise after inspecting rendered output.

Every variant must include:

```json
"composition": {
  "decision": "no_crop",
  "reason": "The existing framing already balances subject and context."
},
"mask_decision": {
  "decision": "none",
  "reason": "Global tone controls are enough; no isolated sky, subject, or background correction is needed."
}
```

If `composition.decision` is `crop`, `composition.crop.enabled` must be true and the crop must include a reason. If `mask_decision.decision` is `use_masks`, at least one executable Lightroom AI mask must be present. A plan missing these decisions is invalid.

## Style Retrieval Contract

Use this exact retrieval order:

1. Inspect the target preview and summarize subject, light, scene, exposure issues, color casts, skin/subject color risks, and composition risks.
2. Read `knowledge/style_library_index.json`.
3. Exclude `inactive_cards` from direct style selection.
4. Prefer Layer 1 families where `active_for_photo_matching=true` and `role=visual_style`.
5. Read the chosen `knowledge/style_families/<style_family_id>.json`.
6. Inspect representative Layer 2 cards listed in that family. Pick one Layer 2 card only when its scene, color direction, and operation guidance fit the target photo.
7. Optionally read inactive method cards such as `rgb_curve_method`, `mask_local_retouch_method`, or `reference_color_matching_method` after choosing the visual style.
8. Write the plan with `style_family_id`, `style_id`, and `source_style_card` when a Layer 2 card is used.
9. Infer concrete parameters from the target photo. Do not copy tutorial values as fixed presets.

If no Layer 2 card fits, use the Layer 1 family as the style direction and set `style_id` to the family id.

## Rules

- Do not overwrite original RAW files.
- Do not write processed photos into the source directory unless the user explicitly asks.
- Do not treat style-card `raw_profiles` as fixed presets. Style cards are guidance; concrete values belong in `adjustment_plan.json`.
- Do not select method/workflow/non-style reference cards as the primary visual style.
- Keep Layer 1 selection and Layer 2 evidence auditable in the plan rationale or metadata.
- Keep every run auditable: source path, preview path, style id, variant id, agent rationale, generated adjustments, composition decision, profile path, CLI command, review outcome, and failure reason.
- Do not treat a preview path alone as evidence. Carry the versioned preview artifact id and starting-state hash into downstream workflow state so a stale preview cannot silently justify a new edit.
- Do not put backend command names, executable paths, PP3 keys, Lightroom parameter names, or output paths in `EditIntent v2`; those belong in the compiled execution plan.
- Do not execute a plan without an explicit allowed output root. Refuse source fingerprint drift, path escape, command mismatch, profile hash mismatch, or an existing output file before invoking the backend.
- Prefer one best variant per photo. Add extra variants only when the photo has multiple credible directions.
- RawTherapee is the default dynamic rendering backend. Use darktable only for legacy/fallback workflows until dynamic darktable parameter generation is implemented. Use Lightroom only when Lightroom Classic is open, the CLI Bridge plugin is running, `lr system ping` succeeds, and the source RAW is already in the Lightroom catalog.
- Keep generated `.pp3` files under the output directory, not in `knowledge/raw_profiles/`.
- Do not crop by default. Cropping is an agent decision and must include a reason.
- Do not batch-copy crop geometry across photos unless each photo has been separately inspected and the report explains why the same geometry is correct for each frame.
- A plan must fail validation when a variant lacks `composition.decision`, `composition.reason`, `mask_decision.decision`, or `mask_decision.reason`.
- Treat first renders as drafts until reviewed. Mark or document the final accepted render after review.
- Lightroom renders modify the Lightroom catalog state for the target photo before export. Prefer one best variant, or use variant-specific virtual copies outside this script when preserving multiple Lightroom edit states matters.
- Lightroom crop execution is not supported by the current backend. Use `preserve_existing_crop`, `no_crop`, or `manual_recommendation` for Lightroom plans unless crop support has been implemented and verified.
- Lightroom `masks` through the current batch Bridge are disabled by default because AI masks can be written to the wrong active photo and sky/subject selections can be visibly wrong in low-contrast scenes. Use `mask_decision=manual_recommendation` unless the executor has explicit per-photo active-image validation and overlay review.
- Experimental Lightroom AI batch execution is allowed only when the local config explicitly sets `lightroom.allow_unverified_ai_masks=true`, and the report must state that the masks still require human overlay verification in Lightroom.
- Local brush/gradient/radial masks and people/landscape part-specific masks are not executable yet; record them as review notes or supporting rationale instead.
- When using Lightroom `masks`, put global changes in `adjustments` and local changes in each mask's `settings`. Do not duplicate the same correction globally and locally unless that is intentional and explained in the rationale.
- For Lightroom mask settings, use Lumenflow adjustment keys such as `exposure_compensation`, `highlights`, `shadows`, `contrast`, `clarity`, `dehaze`, `temperature`, and `saturation`; the renderer maps them to Lightroom develop setting names.
- Lightroom global `adjustments` also support Lightroom-only advanced color controls: `hsl`, `color_mixer`, `tone_curve`, `color_grading`, and `calibration`. These are executable only by the Lightroom engine; RawTherapee currently ignores them except as recorded plan data.

## Lightroom Plan Contract

Lightroom-specific metadata can be top-level or variant-level:

```json
"lightroom": {
  "photo_id": "123"
}
```

Top-level `lightroom.photo_id` applies to all variants. Variant-level `lightroom.photo_id` overrides it.

Executable AI masks belong inside the variant:

```json
"masks": [
  {
    "type": "sky",
    "rationale": "Recover bright sky detail without darkening the subject.",
    "settings": {
      "highlights": -35,
      "dehaze": 12
    }
  },
  {
    "type": "subject",
    "rationale": "Lift the subject after global exposure is set.",
    "settings": {
      "exposure_compensation": 0.25,
      "clarity": 8
    }
  }
]
```

Supported `type` values are `subject`, `sky`, `background`, `objects`, `people`, and `landscape`.

The Lightroom execution order is:

1. Resolve `photo_id` from the plan or `lr -o json catalog find-by-path <source>`.
2. Apply global `adjustments` via `lr develop apply`.
3. Apply each AI mask via `lr develop ai batch <type> --photos <photo_id> --adjust <settings>`.
4. Export via `lr export photo`.

Unsupported local edits should be recorded as review notes or in `composition`/`photo_analysis`, not as executable `masks`. This includes brush, gradient, radial, mask intersections/subtractions, and part-specific people/landscape masks.

Lightroom-only global adjustment shapes:

```json
"adjustments": {
  "exposure_compensation": 0.35,
  "temperature": 5400,
  "hsl": {
    "orange": {"saturation": -5, "luminance": 8},
    "green": {"hue": -10, "saturation": -20},
    "blue": {"saturation": -12, "luminance": -8}
  },
  "color_mixer": {
    "aqua": {"hue": -8, "saturation": -10}
  },
  "tone_curve": {
    "parametric": {"shadows": -8, "lights": 6, "highlights": -10},
    "point": [[0, 0], [64, 58], [128, 132], [255, 255]],
    "blue": [[0, 4], [128, 128], [255, 250]]
  },
  "color_grading": {
    "shadows": {"hue": 210, "saturation": 8},
    "highlights": {"hue": 42, "saturation": 10},
    "midtones": {"hue": 35, "saturation": 4, "luminance": 0},
    "global": {"hue": 38, "saturation": 3},
    "blending": 50,
    "balance": 5
  },
  "calibration": {
    "shadow_tint": 4,
    "red": {"hue": 5, "saturation": -3},
    "blue": {"hue": -8, "saturation": 12}
  }
}
```

Use these only when they materially improve the photo. HSL/Color Mixer is the preferred first tool for selective color cleanup; Color Grading is for deliberate shadow/highlight/midtone color separation; Tone Curve is for contrast shape or RGB channel color separation; Calibration is a global camera-profile-level color move and should be used sparingly.

## Expected Output

```text
output/
├── previews/
│   └── IMG_001_preview.jpg
├── plans/
│   ├── IMG_001.adjustment_plan.json
│   └── IMG_001.revision_2.adjustment_plan.json
├── profiles/
│   └── IMG_001_best.pp3
├── IMG_001_best.jpg
├── IMG_001_warm_alt.jpg
├── review_notes.json
├── processing_records.json
└── processing_report.md
```

## Adjustment Plan Shape

The agent writes concrete values after inspecting the photo and style cards:

```json
{
  "schema_version": "lumenflow.adjustment_plan.v1",
  "revision": 1,
  "source": "/path/to/photos/IMG_001.DNG",
  "preview": "/path/to/output/previews/IMG_001_preview.jpg",
  "photo_analysis": {
    "subject": "natural-light portrait",
    "issues": ["slightly underexposed", "skin is a little green"],
    "fit": "clean_natural with a soft portrait bias"
  },
  "variants": [
    {
      "variant_id": "best",
      "style_id": "clean_natural",
      "rationale": "Keep the portrait natural, lift exposure, protect highlights, and clean up skin tone.",
      "adjustments": {
        "exposure_compensation": 0.35,
        "saturation": -4,
        "temperature": 5400,
        "green": 1.02,
        "hsl": {
          "orange": {"saturation": -5, "luminance": 8},
          "green": {"hue": -10, "saturation": -20}
        },
        "tone_curve": {
          "parametric": {"shadows": -8, "lights": 6},
          "point": [[0, 0], [64, 58], [128, 132], [255, 255]]
        },
        "color_grading": {
          "shadows": {"hue": 210, "saturation": 8},
          "highlights": {"hue": 42, "saturation": 10},
          "balance": 5
        },
        "calibration": {
          "blue": {"hue": -8, "saturation": 12}
        }
      },
      "lightroom": {
        "photo_id": "123"
      },
      "mask_decision": {
        "decision": "use_masks",
        "reason": "The portrait subject needs a small local lift after the global exposure is set."
      },
      "masks": [
        {
          "type": "subject",
          "rationale": "Lift the portrait subject without washing out the background.",
          "settings": {
            "exposure_compensation": 0.25,
            "clarity": 8
          }
        }
      ],
      "composition": {
        "decision": "crop",
        "reason": "The left edge has distracting clutter and the subject benefits from a tighter frame.",
        "crop": {
          "enabled": true,
          "unit": "pixels",
          "x": 120,
          "y": 80,
          "width": 3600,
          "height": 2400,
          "fixed_ratio": true,
          "ratio": "3:2",
          "reason": "Remove distracting edge clutter and keep attention on the subject."
        }
      }
    }
  ]
}
```

## Review Notes Shape

After first render, write review notes. If `needs_revision` is true, generate a revised plan and render it.

```json
{
  "schema_version": "lumenflow.render_review.v1",
  "source_plan": "/path/to/output/plans/IMG_001.adjustment_plan.json",
  "reviewed_outputs": ["/path/to/output/IMG_001_best.jpg"],
  "decision": "accept",
  "needs_revision": false,
  "checks": {
    "exposure": "ok",
    "highlights": "ok",
    "shadows": "ok",
    "color": "ok",
    "composition": "crop improves focus without losing context",
    "style_strength": "ok"
  },
  "notes": "Final render accepted."
}
```
