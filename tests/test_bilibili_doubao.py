from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import transcribe_bilibili_doubao


class BilibiliDoubaoTests(unittest.TestCase):
    def test_prepare_flash_audio_converts_unsupported_container(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tutorial.m4a"
            source.write_bytes(b"source")

            def fake_command(command: list[str]) -> None:
                Path(command[-1]).write_bytes(b"mp3")

            with mock.patch.object(
                transcribe_bilibili_doubao,
                "run_command",
                side_effect=fake_command,
            ) as mocked_run:
                result = transcribe_bilibili_doubao.prepare_flash_audio(
                    source,
                    bvid="BV1TEST",
                    audio_cache_dir=root,
                    ffmpeg_command="custom-ffmpeg",
                )

            self.assertEqual(result, root / "BV1TEST.doubao.16k.mp3")
            self.assertEqual(mocked_run.call_args.args[0][0], "custom-ffmpeg")

    def test_transcript_segments_falls_back_to_plain_text(self) -> None:
        segments = transcribe_bilibili_doubao.transcript_segments(
            {"text": "提高曝光。降低高光。", "utterances": []}
        )

        self.assertEqual([item["text"] for item in segments], ["提高曝光。", "降低高光。"])

    def test_run_doubao_cli_reads_normalized_transcript_without_exposing_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio_path = root / "tutorial.mp3"
            audio_path.write_bytes(b"audio")
            artifacts_dir = root / "artifacts"

            def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                self.assertIn("--mode", command)
                self.assertIn("flash", command)
                self.assertIn("--audio-file", command)
                self.assertNotIn("VOLC_SPEECH_API_KEY", " ".join(command))
                artifacts_dir.mkdir(parents=True)
                (artifacts_dir / "transcript.json").write_text(
                    json.dumps(
                        {
                            "provider": "doubao",
                            "resource_id": "volc.bigasr.auc_turbo",
                            "text": "先降低高光，再调整HSL。",
                            "utterances": [
                                {
                                    "start_ms": 1250,
                                    "end_ms": 4200,
                                    "text": "先降低高光，再调整HSL。",
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

            with mock.patch.object(transcribe_bilibili_doubao.subprocess, "run", side_effect=fake_run):
                payload = transcribe_bilibili_doubao.run_doubao_cli(
                    audio_path=audio_path,
                    artifacts_dir=artifacts_dir,
                    doubao_python=Path("python3"),
                    doubao_script=Path("/opt/doubao/transcribe_recording_file.py"),
                    doubao_config=Path("/private/doubao-asr.env"),
                )

            self.assertEqual(payload["provider"], "doubao")
            self.assertEqual(payload["utterances"][0]["start_ms"], 1250)

    def test_transcribe_bilibili_url_writes_recipe_compatible_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio_path = root / "BV1TEST.mp3"
            audio_path.write_bytes(b"audio")
            output_dir = root / "transcripts"

            with mock.patch.object(
                transcribe_bilibili_doubao.funasr,
                "video_metadata",
                return_value={"bvid": "BV1TEST", "title": "调色教程", "aid": 1, "cid": 2},
            ), mock.patch.object(
                transcribe_bilibili_doubao.funasr,
                "download_audio",
                return_value=audio_path,
            ), mock.patch.object(
                transcribe_bilibili_doubao,
                "run_doubao_cli",
                return_value={
                    "provider": "doubao",
                    "resource_id": "volc.bigasr.auc_turbo",
                    "text": "提高曝光。降低高光。",
                    "utterances": [
                        {"start_ms": 0, "end_ms": 1000, "text": "提高曝光。"},
                        {"start_ms": 1500, "end_ms": 2500, "text": "降低高光。"},
                    ],
                },
            ):
                result = transcribe_bilibili_doubao.transcribe_bilibili_url(
                    url="https://www.bilibili.com/video/BV1TEST/",
                    output_dir=output_dir,
                    audio_cache_dir=root / "audio",
                    provider_artifacts_dir=root / "provider",
                    keep_audio=True,
                )

            transcript_path = Path(result["transcript_path"])
            transcript = transcript_path.read_text(encoding="utf-8")
            self.assertIn("## 00:00", transcript)
            self.assertIn("## 00:01", transcript)
            self.assertEqual(result["segment_count"], 2)
            self.assertEqual(
                result["source_metadata"]["transcription_method"],
                "doubao:volc.bigasr.auc_turbo",
            )

    def test_transcribe_rejects_empty_doubao_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio_path = root / "BV1TEST.mp3"
            audio_path.write_bytes(b"audio")
            with mock.patch.object(
                transcribe_bilibili_doubao.funasr,
                "video_metadata",
                return_value={"bvid": "BV1TEST", "title": "调色教程"},
            ), mock.patch.object(
                transcribe_bilibili_doubao.funasr,
                "download_audio",
                return_value=audio_path,
            ), mock.patch.object(
                transcribe_bilibili_doubao,
                "run_doubao_cli",
                return_value={"provider": "doubao", "resource_id": "test", "text": "", "utterances": []},
            ):
                with self.assertRaisesRegex(RuntimeError, "no transcript text"):
                    transcribe_bilibili_doubao.transcribe_bilibili_url(
                        url="https://www.bilibili.com/video/BV1TEST/",
                        output_dir=root / "transcripts",
                        audio_cache_dir=root / "audio",
                        provider_artifacts_dir=root / "provider",
                    )

    def test_main_resolves_local_config_and_prints_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local_config = root / "local.json"
            local_config.write_text(
                json.dumps(
                    {
                        "asr": {
                            "doubao": {
                                "enabled": True,
                                "script": "/opt/doubao.py",
                                "config": "/private/doubao.env",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                transcribe_bilibili_doubao,
                "transcribe_bilibili_url",
                return_value={"status": "ok", "transcript_path": "/tmp/result.md"},
            ) as mocked_transcribe, mock.patch("builtins.print") as mocked_print:
                status = transcribe_bilibili_doubao.main(
                    [
                        "https://www.bilibili.com/video/BV1TEST/",
                        "--local-config",
                        str(local_config),
                        "--discard-audio",
                    ]
                )

            self.assertEqual(status, 0)
            self.assertFalse(mocked_transcribe.call_args.kwargs["keep_audio"])
            self.assertEqual(mocked_transcribe.call_args.kwargs["doubao_script"], Path("/opt/doubao.py"))
            mocked_print.assert_called_once()

    def test_main_returns_error_without_leaking_exception_details_to_stdout(self) -> None:
        with mock.patch.object(
            transcribe_bilibili_doubao,
            "transcribe_bilibili_url",
            side_effect=RuntimeError("provider failed"),
        ), mock.patch("builtins.print") as mocked_print:
            status = transcribe_bilibili_doubao.main(
                ["https://www.bilibili.com/video/BV1TEST/", "--local-config", "/missing.json"]
            )

        self.assertEqual(status, 1)
        self.assertIn("provider failed", mocked_print.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
