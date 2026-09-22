# Autonomous RAW Engine Contract

Lumenflow treats RawTherapee 5.11 and darktable 5.4.1 as bounded, headless pixel
engines. The host model decides what the photograph needs; deterministic code
binds that decision to the preview state, compiles only allowlisted native
parameters, renders in an isolated process, fingerprints the result, and limits
the visual-review loop to two revisions by default.

This is intentionally not editor-GUI automation. Catalogs, history panels,
collections, asset browsers, and interactive tools remain outside the contract.

## Agent loop

1. Create a state-bound JPEG preview. For a bare darktable RAW,
   `create_previews.py` writes the codec-owned minimal XMP under the preview
   output directory; it never creates a sidecar beside the RAW.
2. Inspect the preview with the host model and author one per-photo
   `EditIntent v2`. Engine-native parameters belong in `style.rawtherapee` or
   `style.darktable`; unsupported fields fail closed.
3. Compile to an `ExecutionPlan`, then execute only beneath the explicitly
   allowed output root. The receipt records the input and output fingerprints.
4. Inspect the exact receipt-bound output, emit `ReviewResult`, and either accept,
   reject, or revise. A revision creates a new intent and a new output; existing
   renders are never overwritten.
5. Put the final container, bit depth, and bounded engine-specific output
   options in `EditIntent.output`. The execution plan reconstructs the exact
   CLI argv and the receipt binds the resulting high-quality output fingerprint.

Deterministic tests verify these transitions and byte bindings. They do not
pretend to perform aesthetic judgment; that remains the host model's job.

## Pixel capability matrix

| Pixel category | RawTherapee 5.11 | darktable 5.4.1 |
| --- | --- | --- |
| Basic RAW development | RAW/Bayer demosaic, chromatic-aberration and highlight recovery controls | `demosaic@6`, `highlights@4`, temperature and exposure |
| Exposure and tone | Exposure, shadows/highlights, tone equalizer, Retinex, luminance/RGB curves | `exposure@7`, `sigmoid@3`, `filmicrgb@6`, `toneequal@2` |
| Color | White balance, color appearance, vibrance, HSV equalizer, channel mixer, black-and-white | `temperature@4`, `colorbalancergb@5`, `colorequal@4` |
| Optics | Lens profile, distortion and chromatic-aberration controls | `lens@10` with bounded metadata/manual fields |
| Detail and noise | Directional/impulse denoise, USM/edge/micro/post-demosaic sharpening, local contrast | `denoiseprofile@12`, `sharpen@1`, `diffuse@2` |
| Geometry and crop | Rotation, perspective, crop, resize and coarse transforms | engine-native `crop@3` and `ashift@5`; vendor-neutral pixel crop is not mapped |
| Bounded regional edits | Gradient and post-crop vignette | not supported; mask/blend payloads fail closed |
| Output | JPEG, PNG 8/16, TIFF 8/16/16f/32f; live-verified `RTv4_sRGB` output profile | JPEG 8, PNG 8/16, TIFF 8/16/32, OpenEXR 16/32; allowlisted built-in ICC type/intent |

The matrix means “agent-authorable and live-verified through this exact adapter,”
not “the desktop editor happens to expose the feature.” Exact parameter names,
ranges, module versions, and evidence live in
[`rawtherapee_backend.md`](rawtherapee_backend.md) and
[`darktable_backend_spike.md`](darktable_backend_spike.md).

An explicit final export is part of `EditIntent v2`, for example:

```json
{"output":{"format":"tiff","bit_depth":"16","rawtherapee":{"tiff_compression":true}}}
```

```json
{"output":{"format":"openexr","bit_depth":"32","darktable":{"icc_type":"LIN_REC2020","icc_intent":"RELATIVE_COLORIMETRIC"}}}
```

The compiler rejects backend-incompatible formats, depths, options, suffixes,
or any execution-plan command that no longer matches the declared output.

## Explicit limits

- RawTherapee Locallab/RT-spots, arbitrary masks, spot removal, Film Simulation
  CLUTs, Wavelet, and Color Toning are not modeled.
- darktable local masks/blend geometry are not modeled. The 5.4.1 mask payload
  needs a version-pinned fixture and real-RAW pixel-delta proof before exposure.
- darktable generic pixel crop is not mapped; use the validated native crop
  module only when the model can author normalized engine coordinates safely.
- Neither backend writes a catalog or claims editable GUI history parity.

## Live verification

The opt-in integration test runs preview → compile → JPEG render → receipt-bound
review → revise → high-bit-depth final render → accept for three copied RAW
files per backend. RawTherapee finishes with TIFF 16-bit and darktable with
OpenEXR 32-bit:

```bash
LUMENFLOW_RAW_AUTONOMY_LIVE_FIXTURES=/path/to/local/raw-copies \
  python3 -m unittest tests.test_raw_engine_autonomy_live -v
```

If RawTherapee is not installed in the standard macOS application location,
set `RAWTHERAPEE_BASE_PROFILE` to a complete RawTherapee 5.11 PP3 base profile.
Set `LUMENFLOW_RAW_AUTONOMY_EVIDENCE_DIR=/path/to/empty/output` to retain the
previews, both renders, intents, plans, receipts, reviews, and final session for
manual visual inspection. The test refuses to overwrite an existing per-engine
evidence directory.

The fixture directory must contain `P1034631.RW2`, `P1034748.RW2`, and
`P1034812.RW2`. Use copies outside the repository; never point this test at the
only copy of a photograph.
