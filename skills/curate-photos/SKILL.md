---
name: curate-photos
description: Curate, cull, shortlist, and sequence a user-specified set of local RAW photos for a stated purpose using the host model's visual reasoning. Build contact sheets, identify technical rejects and near-duplicates, assign editorial roles, propose alternates, and wait for user confirmation before handing selected photos to development.
---

# Curate Photos

Use this skill when the user asks to select, cull, shortlist, organize, or sequence photos, or asks which photos should be edited for a portfolio, trip story, album, social post, or another purpose.

## Boundary

This skill decides **what belongs and in what order**. `develop-photos` decides **how confirmed photos should be edited**.

Use the host model's native vision and reasoning to interpret the user's purpose, compare frames, and construct the sequence. Scripts perform only deterministic work: scanning, date filtering, embedded-preview extraction, contact-sheet layout, contract validation, and packaging. Do not substitute a fixed aesthetic score for visual judgment.

Never modify RAW files, sidecars, Lightroom ratings, collection membership, or develop settings during curation.

## Runtime Routing (MCP First)

If Lumenflow MCP tools are available, always use them as the product interface:

1. Call `lumenflow.status` first.
2. Read `features.local_curation`; do not infer tool availability from the `lite` or `full` label alone.
3. When `local_curation=true`, use `lumenflow.prepare_curation` and `lumenflow.finalize_curation` for all local-file preparation and validation.
4. When `local_curation=false`, do not run repository scripts to bypass the runtime policy. Explain that allowed source/output roots must be configured. You may still curate images that the user has directly provided to the host, but do not claim that a local RAW folder was scanned.
5. If the Lumenflow MCP runtime itself is unavailable, enter Lite Mode and limit work to host-visible images and advisory curation.

Direct `scripts/` commands are a developer/debug fallback only. Do not use them in a normal installed Plugin workflow.

## Workflow

1. Resolve the user's source directory, purpose, and any hard scope such as dates, desired count, people, events, or output format. Infer a reasonable editorial purpose when it is obvious; otherwise ask one concise question.
2. Prepare a curation workspace with `lumenflow.prepare_curation`, passing the absolute source folder, absolute output directory, and optional date bounds.

3. Read `candidate_manifest.json`. Report preview failures or missing capture dates that changed the candidate set.
4. Inspect every contact sheet with the host model's vision. Open individual previews at higher detail when focus, expression, motion blur, or near-duplicate choice is uncertain.
5. Reason in this order:
   - Remove clear technical failures, accidental frames, and unusable expressions.
   - Group near-duplicates by subject, moment, and composition; choose the strongest representative rather than rewarding tiny score differences.
   - Match the stated purpose: subject coverage, emotional range, setting, visual variety, orientation, and expected output count.
   - Build an editorial sequence with explicit roles such as opener, scene-setter, portrait, action, detail, transition, climax, and closer.
   - Keep alternates only when they express a real tradeoff.
   - Nominate a small number of edit experiments when uncertain grading directions are worth comparing.
6. Write `selection_plan.json` using `knowledge/schemas/selection_plan.schema.json`. Each selected photo must have a unique contiguous order, an editorial role, and a concrete reason. Start with:

   ```json
   {
     "schema_version": "lumenflow.selection_plan.v1",
     "purpose": "A concise Bangkok travel story",
     "selection": [
       {
         "order": 1,
         "asset_id": "P1000001.RW2",
         "role": "Opener",
         "reason": "Establishes the location and humid evening atmosphere."
       }
     ],
     "alternates": [],
     "edit_experiments": [],
     "status": {
       "decision": "agent_recommended_pending_user_confirmation",
       "raw_files_modified": false
     }
   }
   ```

7. Validate and package the proposed sequence with `lumenflow.finalize_curation`, passing the absolute manifest and plan paths returned by the active workspace.

8. Show the proposed sequence, rationale, alternates, and `selection_report.md` to the user. Do not treat the proposal as approval.
9. After explicit user confirmation, change `status.decision` to `user_confirmed`, validate again, and hand only those ordered assets to `develop-photos`. If the user changes membership or order, create a revised plan and validate it before handoff.

## Developer/debug CLI fallback

Use this only when maintaining Lumenflow itself or when the user explicitly asks to debug the CLI without an MCP host:

```bash
python3 scripts/curate_photos.py prepare /path/to/raws \
  --output-dir /path/to/curation \
  --date-from 2026-06-01 \
  --date-to 2026-06-30

python3 scripts/curate_photos.py finalize \
  /path/to/curation/candidate_manifest.json \
  /path/to/curation/selection_plan.json
```

The same confirmation and source-immutability rules apply to this fallback.

## Visual Judgment Contract

- Judge photographs relationally, not in isolation. A strong individual frame may be omitted when it repeats a beat already covered better.
- Use native visual understanding for intent, narrative, expression, gesture, balance, atmosphere, and sequence rhythm.
- Treat focus and blur conservatively at contact-sheet scale. Inspect the individual preview before declaring a borderline frame technically unusable.
- Explain selection in terms of the user's purpose. Avoid generic reasons such as “best photo” or unexplained numeric scores.
- Preserve uncertainty honestly with alternates or edit experiments; do not hide it behind fake precision.
- Prefer a coherent, appropriately sized set over maximizing the number of acceptable photos.

## Output Contract

The workspace contains:

- `candidate_manifest.json`: traceable RAW-to-preview mapping and failures.
- `previews/`: camera-embedded JPEG previews; never edited RAW data.
- `contact_sheets/`: labeled overview pages for complete-set inspection.
- `selection_plan.json`: host-model-authored proposal.
- `selection_plan.validated.json`: normalized plan after validation.
- `selected_previews/`: ordered copies for easy review.
- `selection_report.md`: human-readable purpose, order, roles, reasons, alternates, and experiments.

`candidate_manifest.json` follows `knowledge/schemas/candidate_manifest.schema.json`; `selection_plan.json` follows `knowledge/schemas/selection_plan.schema.json`.

## Rules

- Inspect all in-scope candidates before finalizing a set.
- Do not silently exclude photos whose metadata or preview extraction failed.
- Do not fabricate visual observations for previews that were not inspected.
- Do not use `develop-photos` to edit a pending proposal. Require `user_confirmed` or a direct user-specified file list.
- Do not import into Lightroom or mutate Lightroom state merely to curate files on disk.
- Keep generated workspaces outside the source directory unless the user explicitly asks otherwise.
- Keep originals immutable and report `raw_files_modified=false` in every plan.
