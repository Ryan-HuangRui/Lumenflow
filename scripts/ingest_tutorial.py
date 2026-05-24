#!/usr/bin/env python3
"""Convert tutorial transcripts into Lumenflow tutorial recipe records."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fetch_bilibili_subtitles
import lumenflow_config

DEFAULT_OUTPUT_DIR = Path("knowledge/style_cards/tutorial_recipes")
DEFAULT_TRANSCRIPT_DIR = DEFAULT_OUTPUT_DIR / "transcripts"

KEYWORD_CATEGORIES = {
    "basic_tone": [
        "曝光",
        "对比",
        "高光",
        "阴影",
        "白色色阶",
        "黑色色阶",
        "色温",
        "色调",
        "exposure",
        "contrast",
        "highlight",
        "shadow",
        "white",
        "black",
        "temperature",
        "tint",
    ],
    "tone_curve": [
        "曲线",
        "暗部",
        "亮部",
        "阴影抬",
        "curve",
        "tone curve",
        "lift",
        "fade",
    ],
    "hsl_color": [
        "hsl",
        "色相",
        "饱和度",
        "明度",
        "绿色",
        "橙色",
        "蓝色",
        "黄色",
        "hue",
        "saturation",
        "luminance",
        "orange",
        "green",
        "blue",
        "yellow",
    ],
    "color_grading": [
        "分离色调",
        "颜色分级",
        "阴影加",
        "高光加",
        "中间调",
        "color grading",
        "split toning",
        "midtone",
    ],
    "presence_detail": [
        "清晰度",
        "纹理",
        "去朦胧",
        "锐化",
        "降噪",
        "clarity",
        "texture",
        "dehaze",
        "sharpen",
        "noise",
    ],
    "mask_local": [
        "蒙版",
        "径向",
        "渐变",
        "局部",
        "画笔",
        "mask",
        "radial",
        "gradient",
        "local",
        "brush",
    ],
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slugify(value: str, fallback: str = "tutorial") -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "_", value).strip("._-")
    return cleaned[:80] or fallback


def source_stable_id(
    platform: str,
    url: str,
    source_metadata: dict[str, Any] | None = None,
) -> str:
    source_metadata = source_metadata or {}
    if platform == "bilibili":
        bvid = source_metadata.get("bvid")
        if not bvid:
            match = fetch_bilibili_subtitles.BVID_RE.search(url)
            if match:
                bvid = match.group(1)
        if bvid:
            page = source_metadata.get("page")
            return f"{bvid}_p{page}" if page else str(bvid)
    return sha256_text(f"{platform}:{url}")[:16]


def recipe_id_for_source(
    platform: str,
    url: str,
    source_metadata: dict[str, Any] | None = None,
) -> str:
    return f"{slugify(platform)}_{slugify(source_stable_id(platform, url, source_metadata))}"


def parse_transcript_segments(transcript_text: str) -> list[dict[str, str]]:
    segments: list[dict[str, str]] = []
    current_timestamp = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines
        text = " ".join(line.strip() for line in current_lines if line.strip()).strip()
        if text:
            segments.append({"timestamp": current_timestamp, "text": text})
        current_lines = []

    for raw_line in transcript_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("# ") or line.startswith("- "):
            continue
        heading = re.match(r"^##\s+(.+)$", line)
        if heading:
            flush()
            current_timestamp = heading.group(1).strip()
            continue
        current_lines.append(line)
    flush()

    if segments:
        return segments

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", transcript_text) if part.strip()]
    return [{"timestamp": "", "text": paragraph} for paragraph in paragraphs]


def extract_adjustment_steps(segments: list[dict[str, str]], limit: int = 40) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for segment in segments:
        text = segment["text"]
        lower_text = text.lower()
        for category, keywords in KEYWORD_CATEGORIES.items():
            matched = [keyword for keyword in keywords if keyword.lower() in lower_text]
            if not matched:
                continue
            steps.append(
                {
                    "timestamp": segment.get("timestamp", ""),
                    "category": category,
                    "matched_keywords": matched,
                    "text": text,
                }
            )
            break
        if len(steps) >= limit:
            break
    return steps


def transcript_excerpt(segments: list[dict[str, str]], max_chars: int = 800) -> str:
    chunks = []
    for segment in segments:
        prefix = f"[{segment['timestamp']}] " if segment.get("timestamp") else ""
        chunks.append(prefix + segment["text"])
        if sum(len(chunk) for chunk in chunks) >= max_chars:
            break
    return "\n".join(chunks)[:max_chars]


def quality_warnings(segments: list[dict[str, str]], steps: list[dict[str, Any]]) -> list[str]:
    warnings = []
    if not steps:
        warnings.append("no_adjustment_steps_detected")
    if len(segments) < 10:
        warnings.append("short_transcript")
    return warnings


def write_transcript_file(
    *,
    transcript_text: str,
    transcript_dir: Path,
    recipe_id: str,
    output_dir: Path,
) -> str:
    transcript_dir.mkdir(parents=True, exist_ok=True)
    path = transcript_dir / f"{recipe_id}.transcript.md"
    path.write_text(transcript_text, encoding="utf-8")
    try:
        return str(path.relative_to(output_dir))
    except ValueError:
        return str(path)


def transcript_output_path(
    *,
    transcript_dir: Path,
    recipe_id: str,
    output_dir: Path,
) -> str:
    path = transcript_dir / f"{recipe_id}.transcript.md"
    try:
        return str(path.relative_to(output_dir))
    except ValueError:
        return str(path)


def build_recipe(
    *,
    platform: str,
    url: str,
    title: str,
    transcript_text: str,
    topic: str = "",
    source_metadata: dict[str, Any] | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    transcript_dir: Path = DEFAULT_TRANSCRIPT_DIR,
    write_transcript: bool = True,
) -> dict[str, Any]:
    source_metadata = source_metadata or {}
    recipe_id = recipe_id_for_source(platform, url, source_metadata)
    segments = parse_transcript_segments(transcript_text)
    steps = extract_adjustment_steps(segments)
    if write_transcript:
        transcript_path = write_transcript_file(
            transcript_text=transcript_text,
            transcript_dir=transcript_dir,
            recipe_id=recipe_id,
            output_dir=output_dir,
        )
    else:
        transcript_path = transcript_output_path(
            transcript_dir=transcript_dir,
            recipe_id=recipe_id,
            output_dir=output_dir,
        )
    matched_keywords = sorted(
        {keyword for step in steps for keyword in step.get("matched_keywords", [])},
        key=str.lower,
    )
    warnings = quality_warnings(segments, steps)

    return {
        "schema_version": "lumenflow.tutorial_recipe.v1",
        "recipe_id": recipe_id,
        "status": "pending_agent_review",
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "source": {
            "platform": platform,
            "url": url,
            "title": title,
            **source_metadata,
        },
        "topic": topic,
        "transcript": {
            "path": transcript_path,
            "sha256": sha256_text(transcript_text),
            "segment_count": len(segments),
            "excerpt": transcript_excerpt(segments),
        },
        "quality": {
            "warnings": warnings,
            "needs_manual_review": bool(warnings),
        },
        "extraction": {
            "method": "keyword_heuristic_v1",
            "confidence": "low",
            "agent_review_required": True,
            "matched_keywords": matched_keywords,
            "steps": steps,
        },
        "style_mapping": {
            "candidate_style_id": "",
            "merge_status": "pending_agent_review",
        },
    }


def write_recipe(
    recipe: dict[str, Any],
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    force: bool = True,
) -> Path:
    recipe_id = str(recipe["recipe_id"])
    path = output_dir / f"{recipe_id}.json"
    if path.exists() and not force:
        raise FileExistsError(path)
    write_json(path, recipe)
    return path


def recipe_path_for_source(
    platform: str,
    url: str,
    output_dir: Path,
    metadata: dict[str, Any] | None = None,
) -> Path:
    return output_dir / f"{recipe_id_for_source(platform, url, metadata)}.json"


def fetch_bilibili_transcript(
    url: str,
    *,
    preferred_languages: list[str] | None = None,
    cookie_file: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    cookie_header = fetch_bilibili_subtitles.load_cookie_header(cookie_file)
    subtitle = fetch_bilibili_subtitles.fetch_existing_subtitle(
        url,
        preferred_languages=preferred_languages,
        cookie_header=cookie_header,
    )
    transcript_text = fetch_bilibili_subtitles.render_markdown(subtitle)
    metadata = {
        "bvid": subtitle.bvid,
        "aid": subtitle.aid,
        "cid": subtitle.cid,
        "language": subtitle.language,
        "language_doc": subtitle.language_doc,
    }
    return transcript_text, {"title": subtitle.title, "metadata": metadata}


def ingest_url(
    *,
    platform: str,
    url: str,
    topic: str = "",
    title: str = "",
    transcript_file: Path | None = None,
    source_metadata: dict[str, Any] | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    transcript_dir: Path = DEFAULT_TRANSCRIPT_DIR,
    preferred_languages: list[str] | None = None,
    cookie_file: Path | None = None,
    dry_run: bool = False,
    force: bool = True,
) -> dict[str, Any]:
    source_metadata = dict(source_metadata or {})
    if transcript_file:
        transcript_text = transcript_file.read_text(encoding="utf-8")
        title = title or transcript_file.stem
    elif platform == "bilibili":
        transcript_text, fetched = fetch_bilibili_transcript(
            url,
            preferred_languages=preferred_languages,
            cookie_file=cookie_file,
        )
        title = title or fetched["title"]
        source_metadata.update(fetched["metadata"])
    else:
        raise SystemExit(
            f"Unsupported tutorial source platform without transcript file: {platform}"
        )

    recipe = build_recipe(
        platform=platform,
        url=url,
        title=title or url,
        transcript_text=transcript_text,
        topic=topic,
        source_metadata=source_metadata,
        output_dir=output_dir,
        transcript_dir=transcript_dir,
        write_transcript=False,
    )
    if not dry_run:
        target_path = output_dir / f"{recipe['recipe_id']}.json"
        if target_path.exists() and not force:
            raise FileExistsError(target_path)
        recipe["transcript"]["path"] = write_transcript_file(
            transcript_text=transcript_text,
            transcript_dir=transcript_dir,
            recipe_id=str(recipe["recipe_id"]),
            output_dir=output_dir,
        )
        write_recipe(recipe, output_dir=output_dir, force=force)
    return recipe


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest a color-grading tutorial transcript."
    )
    parser.add_argument("--platform", default="bilibili", help="Source platform.")
    parser.add_argument("--url", required=True, help="Tutorial URL.")
    parser.add_argument("--topic", default="", help="Optional topic label.")
    parser.add_argument("--title", default="", help="Optional title override.")
    parser.add_argument(
        "--transcript-file",
        type=Path,
        help="Use a local transcript instead of fetching.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--transcript-dir", type=Path, default=DEFAULT_TRANSCRIPT_DIR)
    parser.add_argument("--preferred-lang", action="append", dest="preferred_languages")
    parser.add_argument("--cookie-file", type=Path)
    parser.add_argument("--local-config", type=Path, default=lumenflow_config.DEFAULT_LOCAL_CONFIG_PATH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing recipe.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        local_config = lumenflow_config.read_local_config(args.local_config)
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    cookie_file = args.cookie_file or lumenflow_config.config_path(
        local_config,
        "bilibili",
        "cookie_file",
    )
    try:
        recipe = ingest_url(
            platform=args.platform,
            url=args.url,
            topic=args.topic,
            title=args.title,
            transcript_file=args.transcript_file,
            output_dir=args.output_dir,
            transcript_dir=args.transcript_dir,
            preferred_languages=args.preferred_languages,
            cookie_file=cookie_file,
            dry_run=args.dry_run,
            force=args.force,
        )
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {"status": "ok", "recipe_id": recipe["recipe_id"]},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
