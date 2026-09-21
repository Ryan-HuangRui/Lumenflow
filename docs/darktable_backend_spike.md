# darktable Backend Feasibility Gate

## Decision

darktable now has a live-verified, first-class adapter for one deliberately narrow operation: an
EditIntent v2 may replay
the exact XMP history stack bound to its approved preview. It does not synthesize darktable module
parameters. Non-empty global adjustments, crop changes, local adjustments, masks, and advanced
color edits fail closed.

The state-bound preview provider and execution-plan/receipt path were verified with a public RAW
sentinel and darktable-cli 5.4.1. The compiler only copies a fingerprint-matched XMP into the
allowed output root and constructs validated argv.

The presence of a `darktable-cli` path is not sufficient evidence. Run:

```bash
python3 scripts/darktable_probe.py \
  --raw /absolute/path/to/sentinel.NEF \
  --output-dir /absolute/path/to/probe-output \
  --report-output /absolute/path/to/darktable-probe.json
```

The report uses `lumenflow.darktable_probe.v1`. A `passed` result requires all of the following:

- the executable returns a parseable version response;
- a real RAW exports through a fresh temporary config and cache;
- the command uses an in-memory library and `write_sidecar_files=never`;
- the RAW fingerprint is identical before and after execution;
- existing sidecars are unchanged and no standard darktable XMP sidecar appears;
- the output exists and has a recorded SHA-256 fingerprint.

A version-only check is `inconclusive`, not `passed`. Any missing executable, non-zero exit,
missing output, source drift, or sidecar drift fails closed.

## Local evidence on 2026-09-21

The original PATH wrappers targeted a missing app bundle and correctly failed the version stage.
After the app bundle was restored, `darktable-cli --version` independently returned 5.4.1. A GUI
launch failure was not treated as CLI evidence.

The real probe used the public MIT-licensed `pixel3.dng` fixture from `syoyo/tinydng`:

`https://raw.githubusercontent.com/syoyo/tinydng/release/pixel3.dng`

The complete file is exactly 12,234,280 bytes with SHA-256
`b8979553ec61b579c2600787e62d9e10885645358e07bafbd6c58cddc84cce4e`. The opt-in integration
test refuses any other size or hash before invoking darktable, so an interrupted download cannot
be mistaken for renderer evidence.
Probe `darktable_probe_7a4a7a02494044ceb2141c26199a8805` passed all gates:

- isolated export succeeded through darktable-cli 5.4.1;
- RAW fingerprint before/after was identical;
- adjacent sidecar state was unchanged;
- output SHA-256 was `9667ce6044ae49764f962b856664815de307f4b87c10b4dbd239e011f025d480`.

An explicit minimal darktable XMP was then bound to a real provider preview. The XMP SHA-256
`996049c1d22a23147591236b308935e50a78d8bec86e7a221715a654a3d4992e` produced starting-state
hash `285eb39fc408432d328a6565daa43f5b23792566b6067879cca0de0ddd488f14` and a successful preview.
The same state compiled to plan `plan_8a56e9396a47ebd16cde756da3e149dd`; non-dry-run execution
returned success receipt `receipt_3ab97c3be4994c9b8e96077e9a781c6c` and output SHA-256
`19862257262cfc6da3036d48de737f90d0d2e47ea8b1f3d2db535f808534e5ee`. RAW and XMP hashes
remained identical before and after.

## Implemented safety boundary

- Preview argv always uses a dedicated config/cache directory, `--library :memory:`, and
  `write_sidecar_files=never`.
- Preview artifacts fingerprint the RAW plus the exact explicit XMP and fail if either source or
  sidecar state changes during rendering.
- Existing preview and final-render outputs are never overwritten.
- The EditIntent compiler requires exactly one regular source XMP, a `complete` preview basis, and
  an exact starting-state hash match. It materializes a byte-identical XMP snapshot inside the
  allowed output root.
- Execution reconstructs and compares the full argv. Shell commands are never accepted, output
  paths must remain below the explicitly allowed root, and receipts fingerprint source/output.
- Dry-run and non-dry-run execution both use the same strict plan validation. The verified live
  slice is advertised by `preview.state_bound`, `state.read`, `intent.compile.v2`, `render`, and
  `export.verified`.

## Promotion work still required

1. Keep dynamic exposure/color/crop/module generation unsupported until each mapping is proven
   against darktable's actual XMP/module contract. Do not infer support from GUI behavior.
2. Keep catalog writes and develop-state writes unsupported; the verified path only reads an XMP
   snapshot and renders through an in-memory library.
3. Add review-loop and benchmark evidence comparable to the RawTherapee path.
