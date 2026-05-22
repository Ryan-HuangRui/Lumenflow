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
4. Rendered JPG/TIFF outputs through RawTherapee or darktable CLI.
5. A processing report explaining what happened.

## Workflow

1. Parse the user's source directory and output directory.
2. Scan RAW files with `scripts/scan_raws.py`.
3. Prefer user-selected/marked files:
   - XMP rating if available.
   - Sidecar marker files if available.
   - Otherwise ask whether to process all RAWs or only a subset.
4. Read style cards from `knowledge/style_cards/`.
5. Use the host agent's vision/reasoning capability to choose one or more suitable styles per photo.
6. Resolve each style to a profile under `knowledge/raw_profiles/`.
7. Render with `scripts/render_raw.py`.
8. Write `processing_report.md` with `scripts/write_processing_report.py`.

## Rules

- Do not overwrite original RAW files.
- Do not write processed photos into the source directory unless the user explicitly asks.
- Do not invent a profile path. If a style has no executable profile, report it and choose a fallback.
- Keep every run auditable: source path, output path, style id, profile path, CLI command, and failure reason.
- Prefer RawTherapee CLI for `.pp3` profiles. Use darktable only when the requested profile/workflow requires it.

## Expected Output

```text
output/
├── IMG_001_clean_natural.jpg
├── IMG_001_cinematic_moody.jpg
└── processing_report.md
```
