---
name: develop-photos
description: Develop and style a user-specified directory of RAW photos with agent judgment, the local style knowledge base, and a RAW editing CLI such as RawTherapee or darktable.
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
3. Agent-selected styles from `knowledge/style_cards/`.
4. Rendered JPG/TIFF outputs through darktable CLI or RawTherapee CLI.
5. A processing report explaining what happened.

## Workflow

1. Parse the user's source directory and output directory.
2. Scan RAW files with `scripts/scan_raws.py`.
3. Prefer user-selected/marked files:
   - darktable `<raw filename>.xmp` rating/color labels if available.
   - RawTherapee `<raw filename>.pp3` rank if available.
   - Otherwise ask whether to process all RAWs or only a subset.
4. Read style cards from `knowledge/style_cards/`.
5. Use the host agent's vision/reasoning capability to choose one or more suitable styles per photo.
6. Resolve each style to a profile under `knowledge/raw_profiles/`.
7. Render with `scripts/develop_photos.py`, which calls `scripts/render_raw.py`.
8. Write `processing_records.json` and `processing_report.md`.

Typical command:

```bash
python scripts/develop_photos.py /path/to/photos --output-dir /path/to/output --engine auto --style-id clean_natural
```

## Rules

- Do not overwrite original RAW files.
- Do not write processed photos into the source directory unless the user explicitly asks.
- Do not invent a profile path. If a style has no executable profile, report it and choose a fallback.
- Keep every run auditable: source path, output path, style id, profile path, CLI command, and failure reason.
- Prefer darktable for the first closed loop because GUI rating/labeling and CLI export share the same XMP sidecar workflow.
- RawTherapee `.pp3` profiles remain supported when `rawtherapee-cli` is available and responsive.

## Expected Output

```text
output/
├── IMG_001_clean_natural.jpg
├── IMG_001_cinematic_moody.jpg
├── processing_records.json
└── processing_report.md
```
