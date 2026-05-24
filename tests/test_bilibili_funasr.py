from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import transcribe_bilibili_funasr


class BilibiliFunasrTests(unittest.TestCase):
    def test_read_hotwords_joins_non_comment_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hotwords.txt"
            path.write_text("# comment\nLightroom\n\nHSL\n色温\n", encoding="utf-8")

            self.assertEqual(
                transcribe_bilibili_funasr.read_hotwords(path),
                "Lightroom HSL 色温",
            )

    def test_extract_segments_accepts_sentence_info(self) -> None:
        result = [
            {
                "text": "完整文本",
                "sentence_info": [
                    {"text": "提高曝光。", "start": 1000, "end": 2000},
                    {"text": "降低高光。", "start": 2500, "end": 4000},
                ],
            }
        ]

        segments = transcribe_bilibili_funasr.extract_segments(result)

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]["start"], 1.0)
        self.assertEqual(segments[1]["text"], "降低高光。")

    def test_extract_segments_splits_plain_text_result(self) -> None:
        result = [{"text": "先提高曝光。然后降低高光。接着进入曲线调整暗部。"}]

        segments = transcribe_bilibili_funasr.extract_segments(
            result,
            fallback_duration=30.0,
        )

        self.assertGreaterEqual(len(segments), 3)
        self.assertEqual(segments[0]["start"], 0.0)
        self.assertGreater(segments[1]["start"], segments[0]["start"])
        self.assertIn("降低高光", segments[1]["text"])

    def test_render_transcript_uses_bilibili_markdown_shape(self) -> None:
        transcript = transcribe_bilibili_funasr.render_transcript(
            title="调色教程",
            bvid="BV1YtZcBKESW",
            segments=[{"start": 7.5, "text": "提高曝光。"}],
            model_name="paraformer-zh",
        )

        self.assertIn("# 调色教程", transcript)
        self.assertIn("- BVID: BV1YtZcBKESW", transcript)
        self.assertIn("## 00:07", transcript)
        self.assertIn("提高曝光。", transcript)

    def test_audio_helpers_accept_configured_tool_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wav_path = Path(directory) / "out.wav"
            audio_path = Path(directory) / "in.m4a"
            audio_path.write_bytes(b"fake audio")
            calls: list[list[str]] = []

            def fake_run_command(command: list[str], *, redact: bool = False) -> None:
                calls.append(command)

            original = transcribe_bilibili_funasr.run_command
            transcribe_bilibili_funasr.run_command = fake_run_command
            try:
                transcribe_bilibili_funasr.convert_to_wav(
                    audio_path,
                    wav_path,
                    ffmpeg_command="/custom/ffmpeg",
                )
            finally:
                transcribe_bilibili_funasr.run_command = original

            self.assertEqual(calls[0][0], "/custom/ffmpeg")


if __name__ == "__main__":
    unittest.main()
