---
name: fetch-bilibili-subtitles
description: Fetch existing subtitle tracks from user-provided Bilibili video links or BV ids and convert them to Markdown, plain text, SRT, or subtitle JSON. Use when the user wants Bilibili transcript/subtitle download, not audio transcription.
---

# Fetch Bilibili Subtitles

Use this skill when the user provides a Bilibili video URL or BV id and asks for subtitles, transcript, captions, or the spoken content of a video.

This skill only downloads subtitle tracks that Bilibili already exposes. It does not download audio, run ASR, or transcribe speech.

## Workflow

1. Confirm the user provided a Bilibili URL or BV id.
2. Run the helper script:

```bash
python scripts/fetch_bilibili_subtitles.py "https://www.bilibili.com/video/BV..." -o /path/to/output --format markdown --json-result
```

3. If the user needs another format, use `--format text`, `--format srt`, or `--format json`.
4. If the user needs a specific language, pass `--preferred-lang zh-CN` or another Bilibili language id. Repeat the flag to provide an ordered preference list.
5. If strict language matching is required, add `--strict-language`.
6. Report the output file path, selected language, and any failure reason.

## Cookie Handling

Some Bilibili AI subtitle tracks are hidden from anonymous requests. If the script returns `no_subtitle_or_cookie_required`, ask the user to provide or configure a Cookie before retrying.

Preferred cookie input is the gitignored local config:

```bash
cp config/lumenflow.local.example.json config/lumenflow.local.json
python scripts/fetch_bilibili_subtitles.py "BV..." -o /tmp/bilibili-subtitles
```

Per-run overrides are also supported:

```bash
export LUMENFLOW_BILIBILI_COOKIE='key=value; another_key=another_value'
python scripts/fetch_bilibili_subtitles.py "BV..." -o /tmp/bilibili-subtitles
```

or:

```bash
python scripts/fetch_bilibili_subtitles.py "BV..." --cookie-file "$BILIBILI_COOKIE_FILE" -o /tmp/bilibili-subtitles
```

Rules:

- Do not commit Cookie values or generated subtitle files to the repository unless the user explicitly asks.
- Do not store subtitle URLs as durable source records; they often include temporary `auth_key` parameters.
- Do not silently fall back to ASR. If no subtitle track is available, report that clearly.
- For multi-part videos, preserve the `?p=` page from the user-provided URL so the correct `cid` is used.

## Output

Default Markdown output:

```text
output/
└── Video Title.transcript.md
```

The Markdown transcript includes title metadata and timestamped content. SRT output uses standard `HH:MM:SS,mmm` timestamps.
