#!/usr/bin/env python3
"""Update tutorial recipe records from approved tutorial source URLs."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import fetch_bilibili_subtitles
import ingest_tutorial
import lumenflow_config

DEFAULT_CONFIG_PATH = Path("knowledge/source_records/tutorial_sources.json")
DEFAULT_OUTPUT_DIR = Path("knowledge/style_cards/tutorial_recipes")
DEFAULT_TRANSCRIPT_DIR = DEFAULT_OUTPUT_DIR / "transcripts"
DEFAULT_ASR_TRANSCRIPT_DIR = DEFAULT_OUTPUT_DIR / "asr_transcripts"
DEFAULT_ASR_AUDIO_CACHE_DIR = DEFAULT_OUTPUT_DIR / "audio_cache"
DEFAULT_ASR_HOTWORDS_PATH = Path("knowledge/source_records/asr_hotwords.txt")
DEFAULT_ASR_SCRIPT_PATH = Path("scripts/transcribe_bilibili_funasr.py")
DEFAULT_ASR_PYTHON_PATH = Path("python")
SEASON_URL_RE = re.compile(r"space\.bilibili\.com/(\d+)/lists/(\d+)")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def parse_sources(config: dict[str, Any]) -> list[dict[str, Any]]:
    sources = config.get("sources", [])
    if not isinstance(sources, list):
        raise SystemExit("Config field 'sources' must be an array.")
    parsed = []
    for source in sources:
        if not isinstance(source, dict):
            raise SystemExit("Each tutorial source must be an object.")
        if not source.get("url"):
            raise SystemExit("Each tutorial source must include url.")
        parsed.append(source)
    return parsed


def source_with_runtime_defaults(
    source: dict[str, Any],
    *,
    defaults: dict[str, Any],
    local_config: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(source)
    platform = str(merged.get("platform", defaults.get("platform", "bilibili")))
    merged.setdefault("platform", platform)

    if not merged.get("cookie_file") and defaults.get("cookie_file"):
        merged["cookie_file"] = defaults["cookie_file"]

    if platform.startswith("bilibili") and not merged.get("cookie_file"):
        cookie_file = lumenflow_config.config_path(local_config, "bilibili", "cookie_file")
        if cookie_file is not None:
            merged["cookie_file"] = str(cookie_file)

    return merged


def parse_bilibili_season_url(url: str) -> tuple[str, str]:
    match = SEASON_URL_RE.search(url)
    if not match:
        raise SystemExit(f"Could not parse Bilibili season URL: {url}")
    return match.group(1), match.group(2)


def api_get_json(
    url: str,
    *,
    referer: str,
    cookie_header: str = "",
    retries: int = 3,
) -> dict[str, Any]:
    headers = {
        "User-Agent": fetch_bilibili_subtitles.DEFAULT_USER_AGENT,
        "Referer": referer,
        "Accept": "application/json, text/plain, */*",
    }
    if cookie_header:
        headers["Cookie"] = cookie_header
    last_error: Exception | None = None
    for attempt in range(retries):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("code") in (None, 0):
                return payload

            message = payload.get("message") or payload.get("msg") or "unknown error"
            last_error = RuntimeError(
                f"Bilibili API error: {message} (code {payload.get('code')})"
            )
        except Exception as error:
            last_error = error

        if attempt < retries - 1:
            time.sleep(0.8 * (attempt + 1))

    raise RuntimeError(str(last_error or "Bilibili API request failed"))


def fetch_bilibili_season_archives(
    source_url: str,
    *,
    cookie_file: Path | None = None,
    max_pages: int = 10,
    page_size: int = 30,
) -> list[dict[str, Any]]:
    mid, season_id = parse_bilibili_season_url(source_url)
    cookie_header = fetch_bilibili_subtitles.load_cookie_header(cookie_file)
    referer = source_url
    archives: list[dict[str, Any]] = []
    seen_bvids: set[str] = set()

    for page_num in range(1, max_pages + 1):
        query = urllib.parse.urlencode(
            {
                "mid": mid,
                "season_id": season_id,
                "page_num": page_num,
                "page_size": page_size,
            }
        )
        url = f"https://api.bilibili.com/x/polymer/web-space/seasons_archives_list?{query}"
        payload = api_get_json(url, referer=referer, cookie_header=cookie_header)
        data = payload.get("data") or {}
        raw_archives = data.get("archives") or []
        if not isinstance(raw_archives, list) or not raw_archives:
            break

        for archive in raw_archives:
            if not isinstance(archive, dict) or not archive.get("bvid"):
                continue
            bvid = str(archive["bvid"])
            if bvid in seen_bvids:
                continue
            seen_bvids.add(bvid)
            archives.append(
                {
                    "bvid": bvid,
                    "aid": archive.get("aid"),
                    "title": archive.get("title") or bvid,
                    "url": f"https://www.bilibili.com/video/{bvid}/",
                }
            )

        page = data.get("page") or {}
        total = int(page.get("total") or len(archives))
        if len(archives) >= total:
            break

    return archives


def expand_source(source: dict[str, Any]) -> list[dict[str, Any]]:
    platform = str(source.get("platform", "bilibili"))
    if platform not in {"bilibili_season", "bilibili_collection"}:
        return [source]

    archives = fetch_bilibili_season_archives(
        str(source["url"]),
        cookie_file=Path(source["cookie_file"]) if source.get("cookie_file") else None,
    )
    expanded = []
    for archive in archives:
        child = dict(source)
        child["platform"] = "bilibili"
        child["url"] = archive.get("url") or f"https://www.bilibili.com/video/{archive['bvid']}/"
        child["title"] = archive["title"]
        child["source_collection_url"] = source["url"]
        child["source_collection_platform"] = platform
        expanded.append(child)
    return expanded


def source_metadata_for_path(source: dict[str, Any]) -> dict[str, Any]:
    platform = str(source.get("platform", "bilibili"))
    url = str(source["url"])
    if platform == "bilibili":
        try:
            ref = fetch_bilibili_subtitles.parse_video_ref(url)
            metadata: dict[str, Any] = {"bvid": ref.bvid}
            if ref.page:
                metadata["page"] = ref.page
            return metadata
        except fetch_bilibili_subtitles.BilibiliSubtitleError:
            return {}
    return {}


def source_recipe_path(source: dict[str, Any], output_dir: Path) -> Path:
    platform = str(source.get("platform", "bilibili"))
    url = str(source["url"])
    metadata = source_metadata_for_path(source)
    return ingest_tutorial.recipe_path_for_source(platform, url, output_dir, metadata)


def should_try_asr(error: Exception) -> bool:
    message = str(error)
    return "no_subtitle_or_cookie_required" in message or "No matching subtitle language" in message


def run_asr_backfill(
    source: dict[str, Any],
    *,
    asr_python: Path,
    asr_script: Path,
    asr_output_dir: Path,
    asr_audio_cache_dir: Path,
    asr_hotwords_path: Path,
    asr_discard_audio: bool = False,
    local_config_path: Path | None = None,
) -> dict[str, Any]:
    command = [
        str(asr_python),
        str(asr_script),
        str(source["url"]),
        "--output-dir",
        str(asr_output_dir),
        "--audio-cache-dir",
        str(asr_audio_cache_dir),
        "--hotwords",
        str(asr_hotwords_path),
    ]
    if local_config_path is not None:
        command.extend(["--local-config", str(local_config_path)])
    if source.get("cookie_file"):
        command.extend(["--cookie-file", str(source["cookie_file"])])
    if asr_discard_audio:
        command.append("--discard-audio")

    try:
        completed = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(f"ASR Python not found: {asr_python}") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "").strip()
        raise RuntimeError(f"ASR fallback failed: {detail[-1200:]}") from error

    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("ASR fallback produced no JSON result.")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise RuntimeError(f"ASR fallback returned invalid JSON: {lines[-1][:300]}") from error
    if payload.get("status") != "ok":
        raise RuntimeError(str(payload.get("error") or "ASR fallback failed."))
    return payload


def run_update(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    transcript_dir: Path = DEFAULT_TRANSCRIPT_DIR,
    dry_run: bool = False,
    force: bool = False,
    asr_fallback: bool = False,
    asr_python: Path = DEFAULT_ASR_PYTHON_PATH,
    asr_script: Path = DEFAULT_ASR_SCRIPT_PATH,
    asr_output_dir: Path = DEFAULT_ASR_TRANSCRIPT_DIR,
    asr_audio_cache_dir: Path = DEFAULT_ASR_AUDIO_CACHE_DIR,
    asr_hotwords_path: Path = DEFAULT_ASR_HOTWORDS_PATH,
    asr_discard_audio: bool = False,
    local_config: dict[str, Any] | None = None,
    local_config_path: Path | None = None,
) -> dict[str, Any]:
    config = read_json(config_path, None)
    if not isinstance(config, dict):
        raise SystemExit(f"Config must be a JSON object: {config_path}")

    defaults = config.get("defaults", {})
    if not isinstance(defaults, dict):
        raise SystemExit("Config field 'defaults' must be an object when present.")

    local_config = local_config or {}
    sources = parse_sources(config)
    summary = {
        "config": str(config_path),
        "processed": 0,
        "skipped": 0,
        "disabled": 0,
        "failed": 0,
        "records": [],
    }

    expanded_sources: list[dict[str, Any]] = []
    for raw_source in sources:
        source = source_with_runtime_defaults(
            raw_source,
            defaults=defaults,
            local_config=local_config,
        )
        if source.get("enabled", True) is False:
            summary["disabled"] += 1
            summary["records"].append({"url": source["url"], "status": "disabled"})
            continue
        try:
            expanded_sources.extend(expand_source(source))
        except Exception as error:
            summary["failed"] += 1
            summary["records"].append(
                {"url": source["url"], "status": "failed", "error": str(error)}
            )

    for source in expanded_sources:

        recipe_path = source_recipe_path(source, output_dir)
        if recipe_path.exists() and not force:
            summary["skipped"] += 1
            summary["records"].append(
                {
                    "url": source["url"],
                    "status": "skipped_existing",
                    "path": str(recipe_path),
                }
            )
            continue

        platform = str(source.get("platform", defaults.get("platform", "bilibili")))
        preferred_languages = source.get(
            "preferred_languages",
            defaults.get("preferred_languages"),
        )
        if preferred_languages is not None and not isinstance(preferred_languages, list):
            raise SystemExit("preferred_languages must be an array when present.")

        try:
            recipe = ingest_tutorial.ingest_url(
                platform=platform,
                url=str(source["url"]),
                topic=str(source.get("topic", "")),
                title=str(source.get("title", "")),
                output_dir=output_dir,
                transcript_dir=transcript_dir,
                preferred_languages=preferred_languages,
                cookie_file=Path(source["cookie_file"]) if source.get("cookie_file") else None,
                dry_run=dry_run,
                force=True,
            )
        except Exception as error:
            if not asr_fallback or platform != "bilibili" or not should_try_asr(error):
                summary["failed"] += 1
                summary["records"].append(
                    {"url": source["url"], "status": "failed", "error": str(error)}
                )
                continue

            if dry_run:
                summary["processed"] += 1
                summary["records"].append(
                    {
                        "url": source["url"],
                        "status": "dry_run_asr_fallback",
                        "error": str(error),
                    }
                )
                continue

            try:
                asr_payload = run_asr_backfill(
                    source,
                    asr_python=asr_python,
                    asr_script=asr_script,
                    asr_output_dir=asr_output_dir,
                    asr_audio_cache_dir=asr_audio_cache_dir,
                    asr_hotwords_path=asr_hotwords_path,
                    asr_discard_audio=asr_discard_audio,
                    local_config_path=local_config_path,
                )
                recipe = ingest_tutorial.ingest_url(
                    platform=platform,
                    url=str(source["url"]),
                    topic=str(source.get("topic", "")),
                    title=str(source.get("title", "")),
                    transcript_file=Path(asr_payload["transcript_path"]),
                    source_metadata=dict(asr_payload.get("source_metadata") or {}),
                    output_dir=output_dir,
                    transcript_dir=transcript_dir,
                    dry_run=dry_run,
                    force=True,
                )
                summary["processed"] += 1
                summary["records"].append(
                    {
                        "url": source["url"],
                        "status": "asr_processed",
                        "recipe_id": recipe["recipe_id"],
                        "path": str(output_dir / f"{recipe['recipe_id']}.json"),
                        "asr_transcript": asr_payload["transcript_path"],
                        "asr_segments": asr_payload.get("segment_count", 0),
                    }
                )
                continue
            except Exception as asr_error:
                summary["failed"] += 1
                summary["records"].append(
                    {
                        "url": source["url"],
                        "status": "failed",
                        "error": str(error),
                        "asr_error": str(asr_error),
                    }
                )
                continue

        summary["processed"] += 1
        summary["records"].append(
            {
                "url": source["url"],
                "status": "dry_run" if dry_run else "processed",
                "recipe_id": recipe["recipe_id"],
                "path": str(output_dir / f"{recipe['recipe_id']}.json"),
            }
        )

    return summary


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update approved tutorial source records.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--local-config", type=Path, default=lumenflow_config.DEFAULT_LOCAL_CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--transcript-dir", type=Path, default=DEFAULT_TRANSCRIPT_DIR)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--asr-fallback",
        action="store_true",
        help="Use local FunASR only when an existing subtitle track cannot be fetched.",
    )
    parser.add_argument("--asr-python", type=Path)
    parser.add_argument("--asr-script", type=Path, default=DEFAULT_ASR_SCRIPT_PATH)
    parser.add_argument("--asr-output-dir", type=Path)
    parser.add_argument("--asr-audio-cache-dir", type=Path)
    parser.add_argument("--asr-hotwords", type=Path)
    parser.add_argument("--asr-discard-audio", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        local_config = lumenflow_config.read_local_config(args.local_config)
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    asr_python = (
        args.asr_python
        or lumenflow_config.config_path(local_config, "asr", "python")
        or DEFAULT_ASR_PYTHON_PATH
    )
    asr_output_dir = (
        args.asr_output_dir
        or lumenflow_config.config_path(local_config, "asr", "output_dir")
        or DEFAULT_ASR_TRANSCRIPT_DIR
    )
    asr_audio_cache_dir = (
        args.asr_audio_cache_dir
        or lumenflow_config.config_path(local_config, "asr", "audio_cache_dir")
        or DEFAULT_ASR_AUDIO_CACHE_DIR
    )
    asr_hotwords_path = (
        args.asr_hotwords
        or lumenflow_config.config_path(local_config, "asr", "hotwords")
        or DEFAULT_ASR_HOTWORDS_PATH
    )
    asr_discard_audio = args.asr_discard_audio or lumenflow_config.config_bool(
        local_config,
        "asr",
        "discard_audio",
        default=False,
    )

    try:
        summary = run_update(
            config_path=args.config,
            output_dir=args.output_dir,
            transcript_dir=args.transcript_dir,
            dry_run=args.dry_run,
            force=args.force,
            asr_fallback=args.asr_fallback,
            asr_python=asr_python,
            asr_script=args.asr_script,
            asr_output_dir=asr_output_dir,
            asr_audio_cache_dir=asr_audio_cache_dir,
            asr_hotwords_path=asr_hotwords_path,
            asr_discard_audio=asr_discard_audio,
            local_config=local_config,
            local_config_path=args.local_config,
        )
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
