# Render Review and Bounded Refinement

The host model performs the visual judgment. Deterministic code does not assign aesthetic scores;
it binds the model-authored review to the exact rendered bytes and controls how another edit may
be attempted.

## Contracts

`lumenflow.review_result.v1` records:

- the EditIntent id and revision reviewed;
- the exact ExecutionPlan, ExecutionReceipt, and output SHA-256;
- `accept`, `revise`, or `reject`;
- categorized visual issues and concrete recommendations;
- for `revise`, replacements for editable intent fields only.

The model may revise `style`, `global_adjustments`, `composition`, or `local_adjustments`. It cannot
change the user authorization, source RAW identity/fingerprint, preview basis, purpose, or intent
identity through a review patch.

`lumenflow.review_session.v1` persists the bounded loop. The default budget is two revisions and
the hard contract maximum is five. It records used review ids and semantic intent hashes so a
retry cannot silently reapply the same review, reset the budget, submit a no-op, or alternate
between earlier intents indefinitely.

## Evidence gate

A review advances only when all of these remain true:

1. the plan targets the session's current intent revision and immutable evidence;
2. the receipt reports success and unchanged RAW bytes;
3. the receipt contains an output fingerprint;
4. the current JPEG is a regular file under the declared output root;
5. its bytes still match the receipt fingerprint;
6. ReviewResult references all four identities exactly.

Dry-run and failed receipts are not visually reviewable evidence. If the JPEG changes after the
receipt, the loop stops with `REVIEW_OUTPUT_DRIFT`.

## Workflow

Start once for the initial intent:

```bash
python3 scripts/review_loop.py start IMG_001.edit_intent.json \
  --max-revisions 2 \
  --state-output IMG_001.review_session.json
```

After the host model inspects the rendered JPEG and writes `IMG_001.review_result.json`, advance:

```bash
python3 scripts/review_loop.py advance \
  IMG_001.review_session.json \
  IMG_001.execution_plan.json \
  IMG_001.execution_receipt.json \
  IMG_001.review_result.json \
  --state-output IMG_001.review_session.json \
  --next-intent-output IMG_001.edit_intent.r2.json
```

For `revise`, compile and execute the emitted next intent, let the model inspect the new output,
then advance again. `accept`, `reject`, and `revision_limit_reached` are terminal. Reopening the
loop requires a new explicit workflow decision rather than mutating the closed session.
