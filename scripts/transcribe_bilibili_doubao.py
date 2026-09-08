#!/usr/bin/env python3
"""Transcribe Bilibili tutorial audio with the shared Doubao ASR skill."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import lumenflow_config
import transcribe_bilibili_funasr as funasr


DEFAULT_OUTPUT_DIR = Path("knowledge/style_cards/tutorial_recipes/asr_transcripts")
DEFAULT_AUDIO_CACHE_DIR = Path("knowledge/style_cards/tutorial_recipes/audio_cache")
DEFAULT_PROVIDER_ARTIFACTS_DIR = DEFAULT_OUTPUT_DIR / "doubao"
DEFAULT_DOUBAO_SCRIPT = (
    Path.home() / ".codex" / "skills" / "doubao-asr" / "scripts" / "transcribe_recording_file.py"
)
DEFAULT_DOUBAO_CONFIG = Path.home() / ".config" / "codex" / "doubao-asr.env"
FLASH_MAX_BYTES = 100 * 1024 * 1024


def run_command(command: list[str]) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(f"Command not found: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "").strip()
        raise RuntimeError(f"Audio preparation failed: {detail[-1200:]}") from error


def prepare_flash_audio(
    audio_path: Path,
    *,
    bvid: str,
    audio_cache_dir: Path,
    ffmpeg_command: str = "ffmpeg",
) -> Path:
    if audio_path.suffix.lower() in {".mp3", ".wav", ".ogg"} and audio_path.stat().st_size <= FLASH_MAX_BYTES:
        return audio_path

    output_path = audio_cache_dir / f"{bvid}.doubao.16k.mp3"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            ffmpeg_command,
            "-y",
            "-i",
            str(audio_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "48k",
            str(output_path),
        ]
    )
    if not output_path.is_file():
        raise RuntimeError("ffmpeg did not produce Doubao-compatible audio.")
    if output_path.stat().st_size > FLASH_MAX_BYTES:
        raise RuntimeError("Prepared audio exceeds the Doubao Flash 100 MiB limit.")
    return output_path


def run_doubao_cli(
    *,
    audio_path: Path,
    artifacts_dir: Path,
    doubao_python: Path = Path("python3"),
    doubao_script: Path = DEFAULT_DOUBAO_SCRIPT,
    doubao_config: Path = DEFAULT_DOUBAO_CONFIG,
) -> dict[str, Any]:
    command = [
        str(doubao_python),
        str(doubao_script),
        "--mode",
        "flash",
        "--audio-file",
        str(audio_path),
        "--format",
        audio_path.suffix.lower().lstrip("."),
        "--language",
        "zh-CN",
        "--output-dir",
        str(artifacts_dir),
        "--config",
        str(doubao_config),
    ]
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(f"Doubao Python not found: {doubao_python}") from error
    except subprocess.CalledProcessError as error:
        # The shared skill omits provider bodies and credentials from stderr.
        detail = (error.stderr or error.stdout or "").strip()
        raise RuntimeError(f"Doubao ASR failed: {detail[-1200:]}") from error

    transcript_path = artifacts_dir / "transcript.json"
    if not transcript_path.is_file():
        raise RuntimeError("Doubao ASR produced no normalized transcript.json artifact.")
    payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("provider") != "doubao":
        raise RuntimeError("Doubao ASR returned an invalid normalized transcript artifact.")
    return payload


def transcript_segments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    utterances = payload.get("utterances")
    segments: list[dict[str, Any]] = []
    if isinstance(utterances, list):
        for item in utterances:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            try:
                start = max(0.0, float(item.get("start_ms") or 0) / 1000.0)
            except (TypeError, ValueError):
                start = 0.0
            segments.append({"start": start, "text": text})
    if segments:
        return segments
    return funasr.split_text_segments(str(payload.get("text") or ""))


def render_transcript(*, title: str, bvid: str, segments: list[dict[str, Any]], resource_id: str) -> str:
    lines = [
        f"# {title}",
        "",
        f"- BVID: {bvid}",
        "- Language: 豆包录音文件极速版转写",
        f"- ASR resource: {resource_id}",
        "",
    ]
    for segment in segments:
        start = funasr.fetch_bilibili_subtitles.format_clock(float(segment.get("start") or 0.0))
        text = str(segment.get("text") or "").strip()
        if text:
            lines.extend([f"## {start}", text, ""])
    return "\n".join(lines).rstrip() + "\n"


def transcribe_bilibili_url(
    *,
    url: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    audio_cache_dir: Path = DEFAULT_AUDIO_CACHE_DIR,
    provider_artifacts_dir: Path = DEFAULT_PROVIDER_ARTIFACTS_DIR,
    cookie_file: Path | None = None,
    keep_audio: bool = True,
    doubao_python: Path = Path("python3"),
    doubao_script: Path = DEFAULT_DOUBAO_SCRIPT,
    doubao_config: Path = DEFAULT_DOUBAO_CONFIG,
    tool_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tool_config = tool_config or {}
    metadata = funasr.video_metadata(url, cookie_file=cookie_file)
    bvid = str(metadata["bvid"])
    audio_path = funasr.download_audio(
        url=url,
        bvid=bvid,
        audio_cache_dir=audio_cache_dir,
        cookie_file=cookie_file,
        yt_dlp_command=lumenflow_config.tool_command(tool_config, "yt_dlp", "yt-dlp"),
    )
    prepared_audio = prepare_flash_audio(
        audio_path,
        bvid=bvid,
        audio_cache_dir=audio_cache_dir,
        ffmpeg_command=lumenflow_config.tool_command(tool_config, "ffmpeg", "ffmpeg"),
    )
    artifacts_dir = provider_artifacts_dir / f"bilibili_{bvid}"
    payload = run_doubao_cli(
        audio_path=prepared_audio,
        artifacts_dir=artifacts_dir,
        doubao_python=doubao_python,
        doubao_script=doubao_script,
        doubao_config=doubao_config,
    )
    segments = transcript_segments(payload)
    if not segments:
        raise RuntimeError("Doubao ASR returned no transcript text.")

    resource_id = str(payload.get("resource_id") or "volc.bigasr.auc_turbo")
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = output_dir / f"bilibili_{bvid}.doubao.transcript.md"
    transcript_path.write_text(
        render_transcript(
            title=str(metadata.get("title") or bvid),
            bvid=bvid,
            segments=segments,
            resource_id=resource_id,
        ),
        encoding="utf-8",
    )

    if not keep_audio:
        for path in {audio_path, prepared_audio}:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    return {
        "status": "ok",
        "transcript_path": str(transcript_path),
        "segment_count": len(segments),
        "provider_artifacts_dir": str(artifacts_dir),
        "source_metadata": {
            **metadata,
            "language": "asr-zh",
            "language_doc": "豆包录音文件极速版转写",
            "transcription_method": f"doubao:{resource_id}",
        },
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe Bilibili audio with Doubao ASR.")
    parser.add_argument("url", help="Bilibili video URL.")
    parser.add_argument("--local-config", type=Path, default=lumenflow_config.DEFAULT_LOCAL_CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--audio-cache-dir", type=Path)
    parser.add_argument("--provider-artifacts-dir", type=Path)
    parser.add_argument("--cookie-file", type=Path)
    parser.add_argument("--doubao-python", type=Path)
    parser.add_argument("--doubao-script", type=Path)
    parser.add_argument("--doubao-config", type=Path)
    parser.add_argument("--discard-audio", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        local_config = lumenflow_config.read_local_config(args.local_config)
        result = transcribe_bilibili_url(
            url=args.url,
            output_dir=args.output_dir
            or lumenflow_config.config_path(local_config, "asr", "output_dir")
            or DEFAULT_OUTPUT_DIR,
            audio_cache_dir=args.audio_cache_dir
            or lumenflow_config.config_path(local_config, "asr", "audio_cache_dir")
            or DEFAULT_AUDIO_CACHE_DIR,
            provider_artifacts_dir=args.provider_artifacts_dir
            or lumenflow_config.config_path(local_config, "asr", "doubao", "artifacts_dir")
            or DEFAULT_PROVIDER_ARTIFACTS_DIR,
            cookie_file=args.cookie_file
            or lumenflow_config.config_path(local_config, "bilibili", "cookie_file"),
            keep_audio=not (
                args.discard_audio
                or lumenflow_config.config_bool(local_config, "asr", "discard_audio", default=False)
            ),
            doubao_python=args.doubao_python
            or lumenflow_config.config_path(local_config, "asr", "doubao", "python")
            or Path("python3"),
            doubao_script=args.doubao_script
            or lumenflow_config.config_path(local_config, "asr", "doubao", "script")
            or DEFAULT_DOUBAO_SCRIPT,
            doubao_config=args.doubao_config
            or lumenflow_config.config_path(local_config, "asr", "doubao", "config")
            or DEFAULT_DOUBAO_CONFIG,
            tool_config=local_config,
        )
    except Exception as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
