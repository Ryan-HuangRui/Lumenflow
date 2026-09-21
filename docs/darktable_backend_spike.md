# darktable Backend Feasibility Gate

## Decision

darktable now has a live-verified, first-class adapter for two operations: an EditIntent v2 may
replay the exact XMP history stack bound to its approved preview, or compile a deliberately
versioned subset of darktable 5.4.1 module structs into a new history stack. The dynamic codec is
fail-closed: it does not accept arbitrary XML fields or claim support for modules whose binary
parameter layout has not been verified.

The state-bound preview provider and execution-plan/receipt path were verified with a public RAW
sentinel and darktable-cli 5.4.1. A preview may bind either an external base XMP or a regular
source sidecar through the generic `preview_basis.state_inputs` roles `base_profile` and
`source_sidecar`. Dynamic compilation embeds the fingerprint-verified XMP bytes in the plan;
execution never re-reads a mutable sidecar.

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

## Dynamic module codec evidence on 2026-09-22

`scripts/darktable_codec.py` is pinned to darktable 5.4.1 and currently encodes only the following
module structs, using the exact little-endian layouts from the 5.4.1 source and neutral blend
parameters:

- `exposure` (module version 7);
- `temperature` / white balance (version 4);
- `sigmoid` (version 3);
- `filmicrgb` / AgX-adjacent tone mapping (version 6);
- `colorbalancergb` (version 5);
- `crop` (version 3, normalized coordinates).

Unknown operations and fields raise a codec error before any XMP or output is written. The
vendor-neutral global mapping is intentionally limited to exposure, black point, contrast and
saturation; white-balance and tone changes should use explicit `style.darktable.modules` requests
until their semantic mapping is made camera- and workflow-aware. The `crop` struct is
engine-native only: generic `composition.crop` is unsupported, and an explicit crop module is
allowed only alongside `composition.decision=preserve_existing_crop`.

For example, a dynamic EditIntent can request verified module fields like this (the normal
authorization/source/preview fields are omitted here):

```json
{
  "style": {
    "style_id": "darktable-verified-541",
    "rationale": "Use the version-pinned darktable codec.",
    "darktable": {
      "modules": [
        {"operation": "exposure", "params": {"exposure": 0.45}},
        {"operation": "filmicrgb", "params": {"contrast": 1.1}},
        {"operation": "colorbalancergb", "params": {"saturation_global": -0.04}},
        {"operation": "crop", "params": {"cx": 0.05, "cy": 0.05, "cw": 0.95, "ch": 0.95}}
      ]
    },
    "composition": {
      "decision": "preserve_existing_crop",
      "reason": "Use only the explicit engine-native crop module."
    }
  }
}
```

The opt-in live test is:

```bash
LUMENFLOW_DARKTABLE_LIVE_RAW_DIR=/private/tmp/lumenflow-raw-fixtures/bangkok-2026 \
  python3 -m unittest tests.test_darktable_codec_live -v
```

The full state-bound dynamic path is covered separately:

```bash
LUMENFLOW_DARKTABLE_LIVE_RAW_DIR=/private/tmp/lumenflow-raw-fixtures/bangkok-2026 \
  python3 -m unittest tests.test_darktable_dynamic_live -v
```

It passed for the three copied Bangkok RW2 files (`P1034631.RW2`, `P1034748.RW2`,
`P1034812.RW2`) with darktable-cli 5.4.1. Every run used `--library :memory:` and
`write_sidecar_files=never`; the copied RAW SHA-256 values remained unchanged and no sidecar was
created beside the source files. The generated six-module XMP had SHA-256
`b28c3d14387becea0de7c310df7ad6aebeba72a4e602d2cb2c8d1125e4623ca5`. Output fingerprints were:

| RAW copy | source SHA-256 | output SHA-256 |
| --- | --- | --- |
| `P1034631.RW2` | `1124595cf9e669f56f724636ef26fe45fb564a893336d849db8c0f5e48c9df51` | `1d036f721d084cb678e2cc95afafb7ef0fe0908b1b7db943cbea87be348d9c64` |
| `P1034748.RW2` | `40ff5e34965e5252ffab02244d2b336f69f5c8c7681ff0a1e2203ae30d52443a` | `1091bf29c2dc89388d0b53d1fc9c38c2afbbb0e1a4787a779ff7aa8b5221e778` |
| `P1034812.RW2` | `e62187c516083dd31797021bc81c853c6650e2e0b6945b109936177bd0503b02` | `168d2bec018215a6f171cae8de6d782f684a24f944ddced7c60712f8e6410b3b` |

This evidence promotes dynamic compilation only for the listed module fields. Denoise, lens
correction, rotate/perspective, local blending/masks, output profile/bit-depth options, and
catalog writes remain unsupported and fail closed.

The no-source-sidecar live path passed for all three copied Bangkok RAWs. Each test copied the
RAW into a temporary directory, rendered a preview from an external `base_profile` XMP, compiled
the module plan from `preview_basis.state_inputs`, and executed the embedded-XMP plan through
darktable-cli 5.4.1. The three source SHA-256 values above were unchanged and no adjacent XMP was
created.

## Implemented safety boundary

- Preview argv always uses a dedicated config/cache directory, `--library :memory:`, and
  `write_sidecar_files=never`.
- Preview artifacts fingerprint the RAW plus the exact explicit XMP and fail if either source or
  sidecar state changes during rendering.
- Existing preview and final-render outputs are never overwritten.
- Dynamic EditIntent compilation requires exactly one preview-bound XMP state input, a `complete`
  preview basis, and an exact starting-state hash match. It embeds the verified base XMP bytes in
  the execution plan and materializes the compiled snapshot inside the allowed output root.
  Legacy exact-XMP replay retains its regular source-sidecar fallback.
- Execution reconstructs and compares the full argv. Shell commands are never accepted, output
  paths must remain below the explicitly allowed root, and receipts fingerprint source/output.
- Dry-run and non-dry-run execution both use the same strict plan validation. The verified live
  slice is advertised by `preview.state_bound`, `state.read`, `intent.compile.v2`, `render`, and
  `export.verified`.

## Promotion work still required

1. Expand the codec one module at a time (denoise, lens, rotate/perspective, blending/masks and
   output profiles) with a version-pinned fixture and real-RAW evidence for every field.
2. Keep catalog writes and develop-state writes unsupported; the verified path only reads an XMP
   snapshot and renders through an in-memory library.
3. Add review-loop and benchmark evidence comparable to the RawTherapee path.
