from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_tutorial_style_cards


class TutorialStyleCardTests(unittest.TestCase):
    def test_parse_summary_mapping_reads_video_family_rows(self) -> None:
        summary = """| recipe_id | language | segments | steps | candidate style card | video title |
| --- | --- | ---: | ---: | --- | --- |
| `bilibili_BV1abc` | ai-zh | 12 | 5 | `japanese_clean_portrait` | 标题 |
"""

        mapping = generate_tutorial_style_cards.parse_summary_mapping(summary)

        self.assertEqual(mapping["bilibili_BV1abc"], "japanese_clean_portrait")

    def test_build_card_keeps_one_video_as_one_style_card(self) -> None:
        recipe = {
            "recipe_id": "bilibili_BV1abc",
            "source": {
                "platform": "bilibili",
                "bvid": "BV1abc",
                "url": "https://www.bilibili.com/video/BV1abc/",
                "title": "【追色手记12】好干净的日系风！荒真人调色教程来啦",
                "language": "ai-zh",
            },
            "transcript": {
                "segment_count": 100,
                "path": "transcripts/bilibili_BV1abc.transcript.md",
            },
            "extraction": {
                "matched_keywords": ["曝光", "曲线", "橙色"],
                "steps": [
                    {
                        "timestamp": "00:10",
                        "category": "basic_tone",
                        "matched_keywords": ["曝光"],
                        "text": "先把曝光提高一点",
                    },
                    {
                        "timestamp": "00:20",
                        "category": "tone_curve",
                        "matched_keywords": ["曲线"],
                        "text": "曲线里轻轻抬起暗部",
                    },
                ],
            },
        }

        card = generate_tutorial_style_cards.build_card(
            recipe,
            "japanese_clean_portrait",
            generate_tutorial_style_cards.FAMILY_FALLBACKS,
        )

        self.assertEqual(card["style_id"], "tutorial_bilibili_BV1abc")
        self.assertEqual(card["source_recipe"], "bilibili_BV1abc")
        self.assertEqual(card["source_video"]["bvid"], "BV1abc")
        self.assertEqual(card["style_family"]["style_id"], "japanese_clean_portrait")
        self.assertEqual(card["source_video"]["step_count"], 2)
        self.assertTrue(card["tutorial_guidance"])
        self.assertEqual(card["card_role"], "style_guidance")
        self.assertEqual(card["parameter_strategy"], "agent_infers_per_photo")
        self.assertEqual(card["raw_profile_role"], "none")
        self.assertEqual(card["raw_profiles"], [])
        self.assertIn("operation_order", card)
        self.assertIn("tone_guidance", card)
        self.assertIn("color_guidance", card)
        self.assertIn("adjustment_plan_guidance", card)

    def test_infer_style_family_for_recipe_without_summary_mapping(self) -> None:
        recipe = {
            "source": {"title": "新手必学雨夜街拍电影感调色教程"},
            "transcript": {"excerpt": "这张照片要保留夜景层次和霓虹色彩。"},
            "extraction": {"matched_keywords": ["高光", "阴影"]},
        }

        self.assertEqual(
            generate_tutorial_style_cards.infer_style_family(recipe),
            "cinematic_street_night",
        )

    def test_generate_cards_writes_one_card_per_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe_dir = root / "recipes"
            family_dir = root / "families"
            output_dir = root / "cards"
            recipe_dir.mkdir()
            family_dir.mkdir()
            summary_path = root / "summary.md"

            (recipe_dir / "bilibili_BV1abc.json").write_text(
                """{
  "recipe_id": "bilibili_BV1abc",
  "source": {"platform": "bilibili", "bvid": "BV1abc", "url": "https://www.bilibili.com/video/BV1abc/", "title": "日系干净教程", "language": "ai-zh"},
  "transcript": {"segment_count": 3, "path": "transcripts/bilibili_BV1abc.transcript.md"},
  "extraction": {"matched_keywords": ["曝光"], "steps": [{"timestamp": "00:01", "category": "basic_tone", "matched_keywords": ["曝光"], "text": "提高曝光"}]}
}
""",
                encoding="utf-8",
            )
            summary_path.write_text(
                "| recipe_id | language | segments | steps | candidate style card | video title |\n"
                "| --- | --- | ---: | ---: | --- | --- |\n"
                "",
                encoding="utf-8",
            )

            written = generate_tutorial_style_cards.generate_cards(
                recipe_dir=recipe_dir,
                summary_path=summary_path,
                family_dir=family_dir,
                output_dir=output_dir,
            )

            self.assertEqual(len(written), 1)
            self.assertTrue((output_dir / "tutorial_bilibili_BV1abc.json").exists())
            self.assertTrue((output_dir / "index.md").exists())


if __name__ == "__main__":
    unittest.main()
