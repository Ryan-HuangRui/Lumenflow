from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ingest_tutorial
import update_tutorial_sources


SAMPLE_TRANSCRIPT = """# 日系调色教程

- BVID: BV1YtZcBKESW

## 00:07
先把曝光提高一点，降低高光，找回天空细节。

## 00:22
然后进入曲线工具，把暗部轻轻抬起来，做出干净的日系灰度。

## 00:45
HSL 里降低绿色饱和度，提高橙色明度，让肤色更通透。
"""


class TutorialIngestTests(unittest.TestCase):
    def test_extract_adjustment_steps_from_transcript(self) -> None:
        segments = ingest_tutorial.parse_transcript_segments(SAMPLE_TRANSCRIPT)
        steps = ingest_tutorial.extract_adjustment_steps(segments)

        categories = {step["category"] for step in steps}
        self.assertIn("basic_tone", categories)
        self.assertIn("tone_curve", categories)
        self.assertIn("hsl_color", categories)
        self.assertTrue(any("曝光" in step["text"] for step in steps))

    def test_build_recipe_marks_no_step_transcript_for_review(self) -> None:
        recipe = ingest_tutorial.build_recipe(
            platform="bilibili",
            url="https://www.bilibili.com/video/BV1nERXBpEpG/",
            title="疑似错配字幕",
            transcript_text="# 疑似错配字幕\n\n## 00:01\n这是一段和调色无关的歌词。",
            output_dir=Path("/tmp/recipes"),
            transcript_dir=Path("/tmp/recipes/transcripts"),
            write_transcript=False,
        )

        self.assertIn("no_adjustment_steps_detected", recipe["quality"]["warnings"])
        self.assertIn("short_transcript", recipe["quality"]["warnings"])

    def test_build_recipe_writes_transcript_and_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe = ingest_tutorial.build_recipe(
                platform="bilibili",
                url="https://www.bilibili.com/video/BV1YtZcBKESW/",
                title="日系调色教程",
                transcript_text=SAMPLE_TRANSCRIPT,
                topic="日系干净色调",
                source_metadata={"bvid": "BV1YtZcBKESW", "language": "zh-CN"},
                output_dir=root / "recipes",
                transcript_dir=root / "recipes" / "transcripts",
            )
            recipe_path = ingest_tutorial.write_recipe(recipe, output_dir=root / "recipes")

            payload = json.loads(recipe_path.read_text(encoding="utf-8"))
            transcript_path = root / "recipes" / payload["transcript"]["path"]
            self.assertEqual(payload["source"]["platform"], "bilibili")
            self.assertEqual(payload["status"], "pending_agent_review")
            self.assertTrue(transcript_path.exists())
            self.assertGreaterEqual(len(payload["extraction"]["steps"]), 3)

    def test_update_sources_skips_existing_recipe_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "tutorial_sources.json"
            output_dir = root / "recipes"
            output_dir.mkdir()
            existing = output_dir / "bilibili_BV1YtZcBKESW.json"
            existing.write_text("{}", encoding="utf-8")
            config_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "platform": "bilibili",
                                "url": "https://www.bilibili.com/video/BV1YtZcBKESW/",
                                "enabled": True,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            summary = update_tutorial_sources.run_update(
                config_path=config_path,
                output_dir=output_dir,
                transcript_dir=output_dir / "transcripts",
                dry_run=False,
                force=False,
            )

            self.assertEqual(summary["skipped"], 1)
            self.assertEqual(summary["processed"], 0)

    def test_update_sources_invokes_ingest_for_enabled_bilibili_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "tutorial_sources.json"
            output_dir = root / "recipes"
            config_path.write_text(
                json.dumps(
                    {
                        "defaults": {"preferred_languages": ["zh-CN", "ai-en"]},
                        "sources": [
                            {
                                "platform": "bilibili",
                                "url": "https://www.bilibili.com/video/BV1YtZcBKESW/",
                                "topic": "日系干净色调",
                                "enabled": True,
                            },
                            {
                                "platform": "bilibili",
                                "url": "https://www.bilibili.com/video/BVdisabled000/",
                                "enabled": False,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            fake_recipe = {
                "recipe_id": "bilibili_BV1YtZcBKESW",
                "source": {"platform": "bilibili"},
            }
            with mock.patch.object(
                update_tutorial_sources.ingest_tutorial,
                "ingest_url",
            ) as mocked:
                mocked.return_value = fake_recipe
                summary = update_tutorial_sources.run_update(
                    config_path=config_path,
                    output_dir=output_dir,
                    transcript_dir=output_dir / "transcripts",
                    dry_run=True,
                    force=False,
                )

            self.assertEqual(summary["processed"], 1)
            self.assertEqual(summary["disabled"], 1)
            mocked.assert_called_once()
            self.assertEqual(
                mocked.call_args.kwargs["preferred_languages"],
                ["zh-CN", "ai-en"],
            )

    def test_update_sources_expands_bilibili_season_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "tutorial_sources.json"
            output_dir = root / "recipes"
            config_path.write_text(
                json.dumps(
                    {
                        "defaults": {"preferred_languages": ["zh-CN"]},
                        "sources": [
                            {
                                "platform": "bilibili_season",
                                "url": "https://space.bilibili.com/3706984584972433/lists/8124987?type=season",
                                "topic": "名人仿色教程",
                                "enabled": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            archives = [
                {"bvid": "BV1nERXBpEpG", "title": "教程 1"},
                {"bvid": "BV1xx411c7mD", "title": "教程 2"},
            ]
            fake_recipe = {"recipe_id": "bilibili_BV1nERXBpEpG"}
            with mock.patch.object(
                update_tutorial_sources,
                "fetch_bilibili_season_archives",
                return_value=archives,
            ), mock.patch.object(update_tutorial_sources.ingest_tutorial, "ingest_url") as mocked:
                mocked.return_value = fake_recipe
                summary = update_tutorial_sources.run_update(
                    config_path=config_path,
                    output_dir=output_dir,
                    transcript_dir=output_dir / "transcripts",
                    dry_run=True,
                    force=False,
                )

            self.assertEqual(summary["processed"], 2)
            self.assertEqual(mocked.call_count, 2)
            self.assertEqual(
                mocked.call_args_list[0].kwargs["url"],
                "https://www.bilibili.com/video/BV1nERXBpEpG/",
            )
            self.assertEqual(mocked.call_args_list[0].kwargs["topic"], "名人仿色教程")

    def test_ingest_dry_run_does_not_write_transcript_or_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript_file = root / "input.md"
            transcript_file.write_text(SAMPLE_TRANSCRIPT, encoding="utf-8")

            recipe = ingest_tutorial.ingest_url(
                platform="bilibili",
                url="https://www.bilibili.com/video/BV1YtZcBKESW/",
                title="日系调色教程",
                transcript_file=transcript_file,
                output_dir=root / "recipes",
                transcript_dir=root / "recipes" / "transcripts",
                dry_run=True,
            )

            self.assertEqual(recipe["recipe_id"], "bilibili_BV1YtZcBKESW")
            self.assertFalse((root / "recipes").exists())

    def test_ingest_transcript_file_keeps_asr_source_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript_file = root / "asr.md"
            transcript_file.write_text(SAMPLE_TRANSCRIPT, encoding="utf-8")

            recipe = ingest_tutorial.ingest_url(
                platform="bilibili",
                url="https://www.bilibili.com/video/BV1YtZcBKESW/",
                title="ASR 转写教程",
                transcript_file=transcript_file,
                source_metadata={
                    "bvid": "BV1YtZcBKESW",
                    "language": "asr-zh",
                    "language_doc": "FunASR 中文离线转写",
                    "transcription_method": "funasr:paraformer-zh",
                },
                output_dir=root / "recipes",
                transcript_dir=root / "recipes" / "transcripts",
                dry_run=True,
            )

            self.assertEqual(recipe["source"]["language"], "asr-zh")
            self.assertEqual(recipe["source"]["transcription_method"], "funasr:paraformer-zh")

    def test_update_sources_uses_asr_fallback_for_missing_bilibili_subtitles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "tutorial_sources.json"
            output_dir = root / "recipes"
            asr_transcript = root / "asr.md"
            asr_transcript.write_text(SAMPLE_TRANSCRIPT, encoding="utf-8")
            config_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "platform": "bilibili",
                                "url": "https://www.bilibili.com/video/BV1YtZcBKESW/",
                                "topic": "ASR fallback",
                                "enabled": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def fail_without_subtitles(**_kwargs: object) -> dict[str, object]:
                raise RuntimeError("no_subtitle_or_cookie_required")

            with mock.patch.object(
                update_tutorial_sources.ingest_tutorial,
                "ingest_url",
                side_effect=fail_without_subtitles,
            ) as mocked_ingest, mock.patch.object(
                update_tutorial_sources,
                "run_asr_backfill",
                return_value={
                    "status": "ok",
                    "transcript_path": str(asr_transcript),
                    "segment_count": 3,
                    "source_metadata": {
                        "bvid": "BV1YtZcBKESW",
                        "language": "asr-zh",
                    },
                },
            ) as mocked_asr:

                def second_ingest(**kwargs: object) -> dict[str, object]:
                    if kwargs.get("transcript_file"):
                        return {"recipe_id": "bilibili_BV1YtZcBKESW"}
                    raise RuntimeError("no_subtitle_or_cookie_required")

                mocked_ingest.side_effect = second_ingest
                summary = update_tutorial_sources.run_update(
                    config_path=config_path,
                    output_dir=output_dir,
                    transcript_dir=output_dir / "transcripts",
                    dry_run=False,
                    force=False,
                    asr_fallback=True,
                    asr_python=Path("python"),
                    asr_audio_cache_dir=root / "audio",
                )

            self.assertEqual(summary["processed"], 1)
            self.assertEqual(summary["failed"], 0)
            self.assertEqual(summary["records"][0]["status"], "asr_processed")
            mocked_asr.assert_called_once()
            self.assertEqual(mocked_ingest.call_count, 2)

    def test_update_sources_dry_run_does_not_execute_asr_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "tutorial_sources.json"
            output_dir = root / "recipes"
            config_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "platform": "bilibili",
                                "url": "https://www.bilibili.com/video/BV1YtZcBKESW/",
                                "enabled": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                update_tutorial_sources.ingest_tutorial,
                "ingest_url",
                side_effect=RuntimeError("no_subtitle_or_cookie_required"),
            ), mock.patch.object(update_tutorial_sources, "run_asr_backfill") as mocked_asr:
                summary = update_tutorial_sources.run_update(
                    config_path=config_path,
                    output_dir=output_dir,
                    transcript_dir=output_dir / "transcripts",
                    dry_run=True,
                    asr_fallback=True,
                )

            self.assertEqual(summary["processed"], 1)
            self.assertEqual(summary["records"][0]["status"], "dry_run_asr_fallback")
            mocked_asr.assert_not_called()

    def test_source_runtime_defaults_fill_bilibili_cookie_from_local_config(self) -> None:
        source = {
            "platform": "bilibili_season",
            "url": "https://space.bilibili.com/1/lists/2?type=season",
        }

        merged = update_tutorial_sources.source_with_runtime_defaults(
            source,
            defaults={},
            local_config={"bilibili": {"cookie_file": "$HOME/.config/lumenflow/cookie.txt"}},
        )

        self.assertIn("cookie_file", merged)
        self.assertTrue(str(merged["cookie_file"]).endswith(".config/lumenflow/cookie.txt"))

    def test_ingest_without_force_does_not_overwrite_transcript_when_recipe_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript_file = root / "input.md"
            output_dir = root / "recipes"
            transcript_dir = output_dir / "transcripts"
            output_dir.mkdir()
            transcript_file.write_text(SAMPLE_TRANSCRIPT, encoding="utf-8")
            (output_dir / "bilibili_BV1YtZcBKESW.json").write_text("{}", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                ingest_tutorial.ingest_url(
                    platform="bilibili",
                    url="https://www.bilibili.com/video/BV1YtZcBKESW/",
                    title="日系调色教程",
                    transcript_file=transcript_file,
                    output_dir=output_dir,
                    transcript_dir=transcript_dir,
                    dry_run=False,
                    force=False,
                )

            self.assertFalse(transcript_dir.exists())


if __name__ == "__main__":
    unittest.main()
