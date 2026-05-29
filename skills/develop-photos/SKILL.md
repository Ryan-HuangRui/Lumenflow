---
name: develop-photos
description: Develop and style a user-specified directory of RAW photos with agent judgment, the local style knowledge base, and a RAW editing CLI such as RawTherapee, darktable, or Lightroom.
---

# Develop Photos

Use this skill when the user asks an agent to process, grade, color, render, export, or batch-edit RAW photos in a local directory.

## Goal

Turn a user request like:

```text
帮我处理 /path/to/photos 里的照片，输出到 /path/to/output
```

into:

1. A scan of candidate RAW files.
2. A filtered set of selected/marked photos.
3. JPEG previews that the host agent can inspect visually.
4. Agent-authored per-photo adjustment plans based on the two-layer style library.
5. Rendered JPG outputs through RawTherapee CLI by default, or Lightroom when explicitly selected and available.
6. Agent review of rendered outputs, with revised plans when needed.
7. A processing report explaining what happened.

## Workflow

1. Parse the user's source directory. If the user does not provide an output directory, use `photos.output_root` from `config/lumenflow.local.json` and create `<photos.output_root>/<source directory name>/`.
2. Scan RAW files with `scripts/scan_raws.py`.
3. Prefer user-selected/marked files:
   - darktable `<raw filename>.xmp` rating/color labels if available.
   - RawTherapee `<raw filename>.pp3` rank if available.
   - Otherwise ask whether to process all RAWs or only a subset.
4. Generate previews with `scripts/create_previews.py`.
5. Inspect the preview images with the host agent's vision/reasoning capability.
6. Retrieve style guidance from the two-layer style library:
   - Read `knowledge/style_library_index.json` first.
   - Filter direct candidates to entries with `active_for_photo_matching=true`.
   - Choose a Layer 1 family from `knowledge/style_families/*.json`.
   - Inspect matching Layer 2 video variants from `knowledge/style_cards/tutorial_derived/*.json` only after the Layer 1 direction fits the photo.
   - Use method/workflow cards only as supporting execution guidance, not as the primary visual style.
7. Choose the best style per photo. If more than one direction is genuinely appropriate, create multiple variants.
8. Decide composition before rendering. This is a per-photo judgment, not a batch preset:
   - Keep original framing when the composition is already intentional.
   - Preserve detected existing crops by default unless the user explicitly asks to change them.
   - Crop only when it removes clear distractions, strengthens the subject, or fixes a weak frame.
   - Record `composition.decision` as `preserve_existing_crop`, `no_crop`, `crop`, or `manual_recommendation`.
   - Record the framing reason in `composition.reason`; crop executions should also include `composition.crop.reason`.
   - Use pixel crop values when the crop should be executed by RawTherapee; otherwise record a recommendation for manual/future implementation.
9. Decide local adjustments before rendering. Record `mask_decision.decision` as `none`, `use_masks`, or `manual_recommendation`. If `use_masks`, include executable Lightroom AI `masks`; if no mask is needed, explain why in `mask_decision.reason`.
10. Write one `adjustment_plan.json` per RAW using `knowledge/schemas/adjustment_plan.schema.json`.
11. Render each plan with `scripts/render_adjustment_plan.py`. The default RawTherapee path creates temporary `.pp3` profiles and calls the configured RawTherapee CLI from `config/lumenflow.local.json` when present. For Lightroom, pass `--engine lightroom`; the plan must include `lightroom.photo_id`, or the source RAW must already be resolvable in the Lightroom catalog by file path.
12. Review rendered outputs with the host agent's vision/reasoning capability:
    - exposure and highlight clipping
    - blocked shadows
    - color cast and skin/subject color
    - style strength
    - crop quality and whether important context was lost
    - obvious rendering artifacts
13. If review finds a material issue, write a revised plan with `revision` incremented, `parent_plan` pointing to the previous plan, and `review_basis` explaining the change; render again.
14. Write final `processing_records.json`, `processing_report.md`, and review notes.

Typical command:

```bash
python scripts/create_previews.py /path/to/photos
python scripts/render_adjustment_plan.py /path/to/output/plans/IMG_001.adjustment_plan.json
python scripts/render_adjustment_plan.py /path/to/output/plans/IMG_001.adjustment_plan.json --engine lightroom
```

With `photos.output_root` set to `/photo-output-root`, a source such as `/photo-source/negative_raw/2026五一港珠澳/P1034473.RW2` renders into `/photo-output-root/2026五一港珠澳/`.

`scripts/develop_photos.py` is a legacy/debug batch path for applying fixed profiles. Do not use it as the main agent workflow when visual analysis and per-photo parameters are available.

## Engine Selection

Default to RawTherapee unless the user explicitly asks for Lightroom, the plan requires executable Lightroom AI masks, or the source workflow is already organized around Lightroom catalog selections.

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
