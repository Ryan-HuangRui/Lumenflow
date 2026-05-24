#!/usr/bin/env python3
"""Transcribe Bilibili tutorial audio with FunASR for subtitle backfill."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import fetch_bilibili_subtitles
import ingest_tutorial
import lumenflow_config

DEFAULT_AUDIO_CACHE_DIR = Path("knowledge/style_cards/tutorial_recipes/audio_cache")
DEFAULT_ASR_TRANSCRIPT_DIR = Path("knowledge/style_cards/tutorial_recipes/asr_transcripts")
DEFAULT_HOTWORDS_PATH = Path("knowledge/source_records/asr_hotwords.txt")
DEFAULT_MODEL = "paraformer-zh"
DEFAULT_VAD_MODEL = "fsmn-vad"
DEFAULT_PUNC_MODEL = "ct-punc"


class FunasrTranscriptionError(RuntimeError):
    """Raised when local FunASR transcription cannot be completed."""


def run_command(command: list[str], *, redact: bool = False) -> None:
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError as error:
        raise FunasrTranscriptionError(f"Command not found: {command[0]}") from error
    except subprocess.CalledProcessError as error:
        rendered = f"{command[0]} ...redacted..." if redact else " ".join(command)
        detail = (error.stderr or error.stdout or "").strip()
        raise FunasrTranscriptionError(f"Command failed: {rendered}\n{detail[-1200:]}") from error


def parse_cookie_pairs(cookie_header: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for raw_part in cookie_header.split(";"):
        part = raw_part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            pairs[key] = value
    return pairs


def write_netscape_cookie_file(cookie_header: str, path: Path) -> None:
    pairs = parse_cookie_pairs(cookie_header)
    lines = ["# Netscape HTTP Cookie File"]
    for key, value in pairs.items():
        lines.append(f".bilibili.com\tTRUE\t/\tFALSE\t0\t{key}\t{value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def read_hotwords(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    words = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            words.append(value)
    return " ".join(words)


def video_metadata(url: str, cookie_file: Path | None = None) -> dict[str, Any]:
    cookie_header = fetch_bilibili_subtitles.load_cookie_header(cookie_file)
    ref = fetch_bilibili_subtitles.parse_video_ref(url)
    info = fetch_bilibili_subtitles.fetch_video_info(ref, cookie_header=cookie_header)
    cid = fetch_bilibili_subtitles.select_cid(info, ref.page)
    return {
        "bvid": ref.bvid,
        "aid": info.get("aid"),
        "cid": cid,
        "title": str(info.get("title") or ref.bvid),
    }


def download_audio(
    *,
    url: str,
    bvid: str,
    audio_cache_dir: Path,
    cookie_file: Path | None = None,
    yt_dlp_command: str = "yt-dlp",
) -> Path:
    audio_cache_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(audio_cache_dir / f"{bvid}.%(ext)s")
    command = [
        yt_dlp_command,
        "--no-playlist",
        "--force-overwrites",
        "-f",
        "ba/bestaudio",
        "-o",
        output_template,
        url,
    ]

    cookie_header = fetch_bilibili_subtitles.load_cookie_header(cookie_file)
    with tempfile.TemporaryDirectory() as directory:
        if cookie_header:
            cookie_path = Path(directory) / "bilibili-cookies.txt"
            write_netscape_cookie_file(cookie_header, cookie_path)
            command[1:1] = ["--cookies", str(cookie_path)]
        run_command(command, redact=bool(cookie_header))

    candidates = sorted(
        path
        for path in audio_cache_dir.glob(f"{bvid}.*")
        if path.suffix.lower() not in {".wav", ".json", ".part", ".ytdl"}
    )
    if not candidates:
        raise FunasrTranscriptionError(f"{yt_dlp_command} did not produce an audio file for {bvid}")
    return candidates[0]


def convert_to_wav(audio_path: Path, wav_path: Path, ffmpeg_command: str = "ffmpeg") -> Path:
    wav_path.parent.mkdir(parents=True, exist_ok=True)
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
            str(wav_path),
        ]
    )
    return wav_path


def audio_duration_seconds(audio_path: Path, ffprobe_command: str = "ffprobe") -> float:
    command = [
        ffprobe_command,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return max(0.0, float(completed.stdout.strip()))
    except Exception:
        return 0.0


def normalize_timestamp_ms(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number / 1000.0 if number >= 1000 else number


def split_text_segments(text: str, *, duration: float = 0.0, max_chars: int = 120) -> list[dict[str, Any]]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    sentences = [
        part.strip()
        for part in re.split(r"(?<=[。！？!?；;])\s*", text)
        if part.strip()
    ]
    if not sentences:
        sentences = [text]

    chunks: list[str] = []
    for sentence in sentences:
        if len(sentence) <= max_chars:
            chunks.append(sentence)
            continue
        for start in range(0, len(sentence), max_chars):
            chunks.append(sentence[start : start + max_chars])

    if not chunks:
        return []
    step = duration / len(chunks) if duration > 0 else 0
    return [{"start": index * step, "text": chunk} for index, chunk in enumerate(chunks)]


def extract_segments(result: Any, *, fallback_duration: float = 0.0) -> list[dict[str, Any]]:
    if isinstance(result, list) and result:
        first = result[0]
    else:
        first = result

    if not isinstance(first, dict):
        return [{"start": 0.0, "text": str(first).strip()}] if str(first).strip() else []

    sentence_info = first.get("sentence_info")
    if isinstance(sentence_info, list) and sentence_info:
        segments = []
        for item in sentence_info:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            start = item.get("start") or item.get("timestamp") or 0
            if isinstance(start, (list, tuple)) and start:
                start = start[0]
            segments.append({"start": normalize_timestamp_ms(start), "text": text})
        if segments:
            return segments

    text = str(first.get("text") or "").strip()
    return split_text_segments(text, duration=fallback_duration) if text else []


def render_transcript(
    *,
    title: str,
    bvid: str,
    segments: list[dict[str, Any]],
    model_name: str,
) -> str:
    lines = [
        f"# {title}",
        "",
        f"- BVID: {bvid}",
        "- Language: FunASR 中文离线转写",
        f"- ASR model: {model_name}",
        "",
    ]
    for segment in segments:
        start = fetch_bilibili_subtitles.format_clock(float(segment.get("start") or 0.0))
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"## {start}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def transcribe_wav(
    wav_path: Path,
    *,
    model_name: str = DEFAULT_MODEL,
    vad_model: str = DEFAULT_VAD_MODEL,
    punc_model: str = DEFAULT_PUNC_MODEL,
    hotwords: str = "",
    batch_size_s: int = 300,
    batch_size_threshold_s: int = 60,
    max_single_segment_time: int = 60000,
) -> Any:
    try:
        from funasr import AutoModel
    except ImportError as error:
        raise FunasrTranscriptionError(
            "FunASR is not installed. Use the configured ASR Python after installing requirements-asr.txt."
        ) from error

    model = AutoModel(
        model=model_name,
        vad_model=vad_model or None,
        vad_kwargs={"max_single_segment_time": max_single_segment_time},
        punc_model=punc_model or None,
    )
    return model.generate(
        input=str(wav_path),
        batch_size_s=batch_size_s,
        batch_size_threshold_s=batch_size_threshold_s,
        sentence_timestamp=True,
        hotword=hotwords,
    )


def transcribe_bilibili_url(
    *,
    url: str,
    output_dir: Path = DEFAULT_ASR_TRANSCRIPT_DIR,
    audio_cache_dir: Path = DEFAULT_AUDIO_CACHE_DIR,
    cookie_file: Path | None = None,
    hotwords_path: Path | None = DEFAULT_HOTWORDS_PATH,
    keep_audio: bool = True,
    model_name: str = DEFAULT_MODEL,
    vad_model: str = DEFAULT_VAD_MODEL,
    punc_model: str = DEFAULT_PUNC_MODEL,
    tool_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tool_config = tool_config or {}
    metadata = video_metadata(url, cookie_file=cookie_file)
    bvid = str(metadata["bvid"])
    audio_path = download_audio(
        url=url,
        bvid=bvid,
        audio_cache_dir=audio_cache_dir,
        cookie_file=cookie_file,
        yt_dlp_command=lumenflow_config.tool_command(tool_config, "yt_dlp", "yt-dlp"),
    )
    wav_path = audio_cache_dir / f"{bvid}.16k.wav"
    convert_to_wav(
        audio_path,
        wav_path,
        ffmpeg_command=lumenflow_config.tool_command(tool_config, "ffmpeg", "ffmpeg"),
    )

    hotwords = read_hotwords(hotwords_path)
    duration = audio_duration_seconds(
        wav_path,
        ffprobe_command=lumenflow_config.tool_command(tool_config, "ffprobe", "ffprobe"),
    )
    raw_result = transcribe_wav(
        wav_path,
        model_name=model_name,
        vad_model=vad_model,
        punc_model=punc_model,
        hotwords=hotwords,
    )
    segments = extract_segments(raw_result, fallback_duration=duration)
    if not segments:
        raise FunasrTranscriptionError("FunASR returned no transcript text.")

    transcript_text = render_transcript(
        title=str(metadata["title"]),
        bvid=bvid,
        segments=segments,
        model_name=model_name,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = output_dir / f"bilibili_{bvid}.funasr.transcript.md"
    transcript_path.write_text(transcript_text, encoding="utf-8")

    if not keep_audio:
        for path in (audio_path, wav_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    return {
        "status": "ok",
        "transcript_path": str(transcript_path),
        "segment_count": len(segments),
        "source_metadata": {
            **metadata,
            "language": "asr-zh",
            "language_doc": "FunASR 中文离线转写",
            "transcription_method": f"funasr:{model_name}",
        },
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe Bilibili audio with FunASR.")
    parser.add_argument("url", help="Bilibili video URL.")
    parser.add_argument("--local-config", type=Path, default=lumenflow_config.DEFAULT_LOCAL_CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--audio-cache-dir", type=Path)
    parser.add_argument("--cookie-file", type=Path)
    parser.add_argument("--hotwords", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--vad-model")
    parser.add_argument("--punc-model")
    parser.add_argument("--discard-audio", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        local_config = lumenflow_config.read_local_config(args.local_config)
    except Exception as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1

    output_dir = (
        args.output_dir
        or lumenflow_config.config_path(local_config, "asr", "output_dir")
        or DEFAULT_ASR_TRANSCRIPT_DIR
    )
    audio_cache_dir = (
        args.audio_cache_dir
        or lumenflow_config.config_path(local_config, "asr", "audio_cache_dir")
        or DEFAULT_AUDIO_CACHE_DIR
    )
    cookie_file = (
        args.cookie_file
        or lumenflow_config.config_path(local_config, "bilibili", "cookie_file")
    )
    hotwords = (
        args.hotwords
        or lumenflow_config.config_path(local_config, "asr", "hotwords")
        or DEFAULT_HOTWORDS_PATH
    )
    discard_audio = args.discard_audio or lumenflow_config.config_bool(
        local_config,
        "asr",
        "discard_audio",
        default=False,
    )

    try:
        result = transcribe_bilibili_url(
            url=args.url,
            output_dir=output_dir,
            audio_cache_dir=audio_cache_dir,
            cookie_file=cookie_file,
            hotwords_path=hotwords,
            keep_audio=not discard_audio,
            model_name=args.model or lumenflow_config.config_str(local_config, "asr", "model") or DEFAULT_MODEL,
            vad_model=args.vad_model
            or lumenflow_config.config_str(local_config, "asr", "vad_model")
            or DEFAULT_VAD_MODEL,
            punc_model=args.punc_model
            or lumenflow_config.config_str(local_config, "asr", "punc_model")
            or DEFAULT_PUNC_MODEL,
            tool_config=local_config,
        )
    except Exception as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
