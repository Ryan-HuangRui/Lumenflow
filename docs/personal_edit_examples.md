# Personal Edit Example Store

The personal example store helps the agent remember edits the user actually accepted. It is a
local retrieval aid, not model training, an automatic preset generator, or a replacement for
per-photo visual reasoning.

## Admission gate

An example can be built only from the final evidence of an `accepted` review session:

- current EditIntent revision;
- matching ExecutionPlan and successful ExecutionReceipt;
- unchanged RAW fingerprint;
- still-matching rendered output bytes;
- final accept review identity.

Rejected, active, revision-limit, failed, dry-run, or output-drifted work cannot enter the store.
This keeps “things the agent tried” separate from “things the user/model workflow accepted.”

## Privacy boundary

The stored `lumenflow.personal_edit_example.v1` contains purpose, style rationale, adjustments,
composition/local-edit decisions, user-supplied retrieval tags, backend/evidence ids, and content
fingerprints. It deliberately excludes:

- RAW and JPEG pixels;
- RAW, preview, profile, and output paths;
- authorization references;
- catalog ids and account data.

The default database is the gitignored `local/personal_edit_examples.sqlite3`. A new database is
created with mode `0600`; symbolic-link database targets are refused and SQLite secure-delete is
enabled. The data is still personal: filesystem backups and copied databases remain outside
Lumenflow's control.

Configure another local path if desired:

```json
{
  "workflow": {
    "personal_example_store": "/private/path/personal_edit_examples.sqlite3"
  }
}
```

## Add and retrieve

After final acceptance:

```bash
python3 scripts/personal_example_store.py add \
  review_session.json execution_plan.json execution_receipt.json \
  --tag bangkok --tag night --tag market
```

Before authoring a new EditIntent, query with the current purpose and scene tags:

```bash
python3 scripts/personal_example_store.py search \
  --purpose "Bangkok night travel story" \
  --tag night --tag market \
  --style-id clean_natural \
  --limit 5
```

Ranking is deterministic and explainable: purpose-token overlap, tag overlap, and exact style id.
The host model must still inspect the new preview, decide whether a retrieved example is relevant,
and infer new per-photo parameters. Never copy crop geometry, exposure, white balance, or local
edits without validating them against the new image.

## Inspect and remove

```bash
python3 scripts/personal_example_store.py list --limit 20
python3 scripts/personal_example_store.py remove edit_example_0123456789abcdef0123456789abcdef
```

Removal deletes the live SQLite row with secure-delete enabled. It cannot erase external backups,
filesystem snapshots, or database copies.
