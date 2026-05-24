#!/usr/bin/env python3
"""Fetch existing Bilibili subtitle tracks for user-provided video links.

This helper intentionally does not perform ASR. It only downloads subtitle JSON
tracks that Bilibili already exposes for the video part.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import lumenflow_config

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_PREFERRED_LANGUAGES = [
    "zh-CN",
    "zh-Hans",
    "zh-Hant",
    "zh",
    "ai-zh",
    "ai-en",
    "en",
]
BVID_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
SHORT_LINK_HOSTS = {"b23.tv", "www.b23.tv", "bili2233.cn", "www.bili2233.cn"}
OutputFormat = Literal["markdown", "text", "srt", "json"]


class BilibiliSubtitleError(RuntimeError):
    """Raised when subtitles cannot be fetched from the existing subtitle APIs."""


@dataclass(frozen=True)
class VideoRef:
    bvid: str
    page: int | None = None


@dataclass(frozen=True)
class SubtitleTrack:
    language: str
    language_doc: str
    url: str


@dataclass(frozen=True)
class SubtitleResult:
    bvid: str
    aid: int
    cid: int
    title: str
    language: str
    language_doc: str
    body: list[dict[str, Any]]
    subtitle_url: str


def parse_video_ref(value: str) -> VideoRef:
    value = value.strip()
    match = BVID_RE.search(value)
    if not match:
        raise BilibiliSubtitleError(f"Could not find a BVID in input: {value}")

    page: int | None = None
    parsed = urllib.parse.urlparse(value)
    params = urllib.parse.parse_qs(parsed.query)
    raw_page = params.get("p") or params.get("page")
    if raw_page:
        try:
            candidate = int(raw_page[0])
            if candidate > 0:
                page = candidate
        except (TypeError, ValueError):
            page = None

    return VideoRef(bvid=match.group(1), page=page)


def normalize_subtitle_url(url: str) -> str:
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    if url.startswith("https://"):
        return url
    raise BilibiliSubtitleError(f"Unsupported subtitle URL: {url}")


def build_cookie_header(cookies: dict[str, Any]) -> str:
    pairs = []
    for key, value in cookies.items():
        if value is None:
            continue
        value_str = str(value).strip()
        if value_str:
            pairs.append(f"{key}={value_str}")
    return "; ".join(pairs)


def load_cookie_header(
    cookie_file: Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    env = env or os.environ
    for name in ("LUMENFLOW_BILIBILI_COOKIE", "BILIBILI_COOKIE"):
        if env.get(name):
            return env[name].strip()

    if cookie_file is None:
        return ""

    raw = cookie_file.read_text(encoding="utf-8").strip()
    if not raw:
        return ""
    if raw.startswith("{"):
        payload = json.loads(raw)
        cookies = payload.get("cookies", payload)
        if not isinstance(cookies, dict):
            raise BilibiliSubtitleError(f"Cookie JSON must contain an object: {cookie_file}")
        return build_cookie_header(cookies)

    lines = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if any("=" in line and ";" not in line for line in lines):
        return "; ".join(lines)
    return raw


def fetch_text(
    url: str,
    *,
    referer: str,
    cookie_header: str = "",
    timeout: int = 15,
) -> str:
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": referer,
        "Accept": "application/json, text/plain, */*",
    }
    if cookie_header:
        headers["Cookie"] = cookie_header

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise BilibiliSubtitleError(f"Bilibili HTTP {error.code}: {detail[:300]}") from error
    except urllib.error.URLError as error:
        raise BilibiliSubtitleError(f"Bilibili request failed: {error}") from error


def fetch_json(
    url: str,
    *,
    referer: str,
    cookie_header: str = "",
    timeout: int = 15,
) -> dict[str, Any]:
    text = fetch_text(url, referer=referer, cookie_header=cookie_header, timeout=timeout)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise BilibiliSubtitleError(f"Response was not JSON: {url}") from error
    if payload.get("code") not in (None, 0):
        message = payload.get("message") or payload.get("msg") or "unknown error"
        raise BilibiliSubtitleError(f"Bilibili API error: {message} (code {payload.get('code')})")
    return payload


def resolve_short_url(url: str, *, timeout: int = 15) -> str:
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.geturl()
    except urllib.error.URLError as error:
        raise BilibiliSubtitleError(f"Could not resolve short Bilibili URL: {url}") from error


def select_cid(video_info: dict[str, Any], page: int | None) -> int:
    if page:
        pages = video_info.get("pages")
        if isinstance(pages, list):
            for item in pages:
                if isinstance(item, dict) and item.get("page") == page and item.get("cid"):
                    return int(item["cid"])
            if 0 < page <= len(pages) and isinstance(pages[page - 1], dict):
                cid = pages[page - 1].get("cid")
                if cid:
                    return int(cid)
    cid = video_info.get("cid")
    if not cid:
        raise BilibiliSubtitleError("Could not determine video cid.")
    return int(cid)


def extract_subtitle_tracks(payload: dict[str, Any]) -> list[SubtitleTrack]:
    candidates = []
    for root in (payload, payload.get("data", {})):
        if not isinstance(root, dict):
            continue
        subtitle = root.get("subtitle")
        if not isinstance(subtitle, dict):
            continue
        for key in ("subtitles", "list"):
            raw_tracks = subtitle.get(key)
            if isinstance(raw_tracks, list):
                candidates.extend(raw_tracks)

    tracks: list[SubtitleTrack] = []
    seen_urls: set[str] = set()
    for raw_track in candidates:
        if not isinstance(raw_track, dict):
            continue
        raw_url = raw_track.get("subtitle_url") or raw_track.get("url")
        if not raw_url:
            continue
        try:
            url = normalize_subtitle_url(str(raw_url))
        except BilibiliSubtitleError:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        tracks.append(
            SubtitleTrack(
                language=str(raw_track.get("lan") or ""),
                language_doc=str(raw_track.get("lan_doc") or ""),
                url=url,
            )
        )
    return tracks


def choose_subtitle_track(
    tracks: list[SubtitleTrack],
    preferred_languages: list[str] | None = None,
    fallback_any: bool = True,
) -> SubtitleTrack:
    if not tracks:
        raise BilibiliSubtitleError("no_subtitle_or_cookie_required")

    preferred_languages = preferred_languages or DEFAULT_PREFERRED_LANGUAGES
    lowered_preferences = [language.lower() for language in preferred_languages]

    for language in lowered_preferences:
        for track in tracks:
            if track.language.lower() == language:
                return track

    for language in lowered_preferences:
        for track in tracks:
            if language and language in track.language.lower():
                return track

    if fallback_any:
        return tracks[0]

    available = ", ".join(track.language or "unknown" for track in tracks)
    raise BilibiliSubtitleError(f"No matching subtitle language. Available: {available}")


def fetch_video_info(ref: VideoRef, cookie_header: str = "") -> dict[str, Any]:
    referer = f"https://www.bilibili.com/video/{ref.bvid}/"
    url = "https://api.bilibili.com/x/web-interface/view?" + urllib.parse.urlencode({"bvid": ref.bvid})
    payload = fetch_json(url, referer=referer, cookie_header=cookie_header)
    data = payload.get("data")
    if not isinstance(data, dict):
        raise BilibiliSubtitleError(f"Video not found: {ref.bvid}")
    return data


def fetch_subtitle_tracks(
    ref: VideoRef,
    aid: int,
    cid: int,
    cookie_header: str = "",
) -> list[SubtitleTrack]:
    referer = f"https://www.bilibili.com/video/{ref.bvid}/"
    endpoints = [
        (
            "https://api.bilibili.com/x/player/wbi/v2?"
            + urllib.parse.urlencode({"aid": aid, "cid": cid, "bvid": ref.bvid})
        ),
        (
            "https://api.bilibili.com/x/v2/dm/view?"
            + urllib.parse.urlencode({"aid": aid, "oid": cid, "type": 1})
        ),
    ]

    tracks: list[SubtitleTrack] = []
    seen_urls: set[str] = set()
    endpoint_errors: list[str] = []
    for endpoint in endpoints:
        try:
            payload = fetch_json(endpoint, referer=referer, cookie_header=cookie_header)
        except BilibiliSubtitleError as error:
            endpoint_errors.append(str(error))
            continue
        for track in extract_subtitle_tracks(payload):
            if track.url not in seen_urls:
                seen_urls.add(track.url)
                tracks.append(track)
    if not tracks and endpoint_errors:
        raise BilibiliSubtitleError("; ".join(endpoint_errors))
    return tracks


def fetch_existing_subtitle(
    video_input: str,
    *,
    preferred_languages: list[str] | None = None,
    fallback_any: bool = True,
    cookie_header: str = "",
) -> SubtitleResult:
    parsed_url = urllib.parse.urlparse(video_input)
    if parsed_url.netloc.lower() in SHORT_LINK_HOSTS:
        video_input = resolve_short_url(video_input)

    ref = parse_video_ref(video_input)
    info = fetch_video_info(ref, cookie_header=cookie_header)
    aid = int(info["aid"])
    cid = select_cid(info, ref.page)
    title = str(info.get("title") or ref.bvid)

    tracks = extract_subtitle_tracks({"data": info})
    fetched_tracks = fetch_subtitle_tracks(ref, aid=aid, cid=cid, cookie_header=cookie_header)
    seen_urls = {track.url for track in tracks}
    tracks.extend(track for track in fetched_tracks if track.url not in seen_urls)
    selected = choose_subtitle_track(tracks, preferred_languages, fallback_any=fallback_any)

    subtitle_payload = fetch_json(selected.url, referer=f"https://www.bilibili.com/video/{ref.bvid}/")
    body = subtitle_payload.get("body")
    if not isinstance(body, list) or not body:
        raise BilibiliSubtitleError("Subtitle file is empty.")

    return SubtitleResult(
        bvid=ref.bvid,
        aid=aid,
        cid=cid,
        title=title,
        language=selected.language,
        language_doc=selected.language_doc,
        body=body,
        subtitle_url=selected.url,
    )


def seconds_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def format_clock(seconds: float) -> str:
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    remaining = total % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{remaining:02d}"
    return f"{minutes:02d}:{remaining:02d}"


def format_srt_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    whole_seconds = int(seconds % 60)
    milliseconds = int(round((seconds - int(seconds)) * 1000))
    if milliseconds == 1000:
        whole_seconds += 1
        milliseconds = 0
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


def subtitle_content(item: dict[str, Any]) -> str:
    return str(item.get("content", "")).strip()


def render_markdown(result: SubtitleResult) -> str:
    lines = [
        f"# {result.title}",
        "",
        f"- BVID: {result.bvid}",
        f"- Language: {result.language_doc or result.language}",
        "",
    ]
    for item in result.body:
        content = subtitle_content(item)
        if not content:
            continue
        start = seconds_value(item.get("from"))
        lines.append(f"## {format_clock(start)}")
        lines.append(content)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_text(result: SubtitleResult) -> str:
    return "\n".join(
        content
        for item in result.body
        if (content := subtitle_content(item))
    ).strip() + "\n"


def render_srt(result: SubtitleResult) -> str:
    blocks = []
    index = 1
    for item in result.body:
        content = subtitle_content(item)
        if not content:
            continue
        start = seconds_value(item.get("from"))
        end = seconds_value(item.get("to"))
        blocks.append(
            f"{index}\n"
            f"{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}\n"
            f"{content}"
        )
        index += 1
    return "\n\n".join(blocks).rstrip() + "\n"


def render_json(result: SubtitleResult) -> str:
    payload = {
        "bvid": result.bvid,
        "aid": result.aid,
        "cid": result.cid,
        "title": result.title,
        "language": result.language,
        "language_doc": result.language_doc,
        "subtitle_url": result.subtitle_url,
        "body": result.body,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def render_output(result: SubtitleResult, output_format: OutputFormat) -> str:
    if output_format == "markdown":
        return render_markdown(result)
    if output_format == "text":
        return render_text(result)
    if output_format == "srt":
        return render_srt(result)
    if output_format == "json":
        return render_json(result)
    raise BilibiliSubtitleError(f"Unsupported output format: {output_format}")


def safe_filename(value: str) -> str:
    cleaned = re.sub(r'[\x00-\x1f/\\:*?"<>|]+', "_", value).strip(" ._")
    return cleaned[:80] or "bilibili_subtitle"


def output_extension(output_format: OutputFormat) -> str:
    return {
        "markdown": ".transcript.md",
        "text": ".transcript.txt",
        "srt": ".srt",
        "json": ".subtitle.json",
    }[output_format]


def write_output(
    result: SubtitleResult,
    *,
    output_dir: Path,
    output_format: OutputFormat,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{safe_filename(result.title)}{output_extension(output_format)}"
    path.write_text(render_output(result, output_format), encoding="utf-8")
    return path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download existing Bilibili subtitles.")
    parser.add_argument("video", help="Bilibili video URL or BV id")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        help="Write output file to this directory",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "text", "srt", "json"],
        default="markdown",
        help="Output format. Defaults to markdown.",
    )
    parser.add_argument(
        "--preferred-lang",
        action="append",
        dest="preferred_languages",
        help="Preferred subtitle language. Can be repeated.",
    )
    parser.add_argument(
        "--strict-language",
        action="store_true",
        help="Fail instead of falling back when preferred language is unavailable.",
    )
    parser.add_argument(
        "--cookie-file",
        type=Path,
        help="Optional cookie file. Supports JSON cookies or key=value lines.",
    )
    parser.add_argument(
        "--local-config",
        type=Path,
        default=lumenflow_config.DEFAULT_LOCAL_CONFIG_PATH,
        help="Local gitignored runtime config. Defaults to config/lumenflow.local.json.",
    )
    parser.add_argument(
        "--json-result",
        action="store_true",
        help="Print a small JSON result manifest.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        local_config = lumenflow_config.read_local_config(args.local_config)
        cookie_file = args.cookie_file or lumenflow_config.config_path(
            local_config,
            "bilibili",
            "cookie_file",
        )
        cookie_header = load_cookie_header(cookie_file)
        result = fetch_existing_subtitle(
            args.video,
            preferred_languages=args.preferred_languages,
            fallback_any=not args.strict_language,
            cookie_header=cookie_header,
        )
        if args.output_dir:
            output_path = write_output(
                result,
                output_dir=args.output_dir,
                output_format=args.format,
            )
            if args.json_result:
                print(
                    json.dumps(
                        {
                            "status": "ok",
                            "bvid": result.bvid,
                            "aid": result.aid,
                            "cid": result.cid,
                            "title": result.title,
                            "language": result.language,
                            "language_doc": result.language_doc,
                            "output": str(output_path),
                        },
                        ensure_ascii=False,
                    )
                )
            else:
                print(output_path)
        else:
            print(render_output(result, args.format), end="")
    except BilibiliSubtitleError as error:
        if args.json_result:
            print(
                json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False),
                file=sys.stderr,
            )
        else:
            print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
