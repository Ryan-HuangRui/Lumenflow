from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_style_family_layer


def make_card(title: str, style_id: str = "tutorial_bilibili_BV1abc") -> dict[str, object]:
    return {
        "schema_version": "lumenflow.style_card.tutorial_derived.v1",
        "style_id": style_id,
        "style_name": title,
        "status": "candidate",
        "source_recipe": "bilibili_BV1abc",
        "source_video": {
            "platform": "bilibili",
            "bvid": "BV1abc",
            "url": "https://www.bilibili.com/video/BV1abc/",
            "title": title,
            "language": "asr-zh",
            "segment_count": 10,
            "step_count": 8,
        },
        "style_family": {"style_id": "master_reference_texture", "style_name": "大师仿色质感"},
        "suitable_scenes": [],
        "tutorial_guidance": [],
        "evidence": {"matched_keywords": [], "representative_steps": []},
        "parameter_strategy": "agent_infers_per_photo",
        "raw_profile_role": "none",
        "raw_profiles": [],
    }


class StyleFamilyLayerTests(unittest.TestCase):
    def test_classify_rainy_street_night(self) -> None:
        card = make_card("如何调出电影感？雨夜街拍必学色调！Dimitri仿色教程")

        self.assertEqual(
            build_style_family_layer.classify_card(card),
            "rainy_cinematic_street",
        )

    def test_classify_rgb_curve_method(self) -> None:
        card = make_card("3分钟认识红绿蓝曲线！成为调色高手！")

        self.assertEqual(
            build_style_family_layer.classify_card(card),
            "rgb_curve_method",
        )

    def test_classify_forest_moss_green(self) -> None:
        card = make_card("Michael Kagerer森系调色大法，低饱和墨绿色教程")

        self.assertEqual(
            build_style_family_layer.classify_card(card),
            "forest_moss_green",
        )

    def test_classify_tool_workflow_non_style(self) -> None:
        card = make_card("「工具篇」每位摄影师都应该去立即安装Ps2023（Beta）版！")

        self.assertEqual(
            build_style_family_layer.classify_card(card),
            "tool_workflow_non_style",
        )

    def test_classify_no_step_vlog_reference(self) -> None:
        card = make_card("在北疆，我驶进了雾与光的边界｜阿尔山秋季自驾vlog")
        card["source_video"]["step_count"] = 0  # type: ignore[index]
        recipe = {"quality": {"needs_manual_review": True}, "extraction": {"steps": []}}

        self.assertEqual(
            build_style_family_layer.classify_card(card, recipe),
            "non_tutorial_reference",
        )

    def test_build_layer_preserves_existing_card_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe_dir = root / "recipes"
            card_dir = root / "cards"
            family_dir = root / "families"
            index_path = root / "style_library_index.json"
            summary_path = root / "summary.md"
            recipe_dir.mkdir()
            card_dir.mkdir()

            recipe = {
                "recipe_id": "bilibili_BV1abc",
                "quality": {"needs_manual_review": False},
                "extraction": {"steps": [{"text": "提高曝光", "category": "basic_tone"}]},
                "source": {"title": "逆光调出日系感？掌握这3个技巧！"},
                "transcript": {"excerpt": "逆光脸黑，要提升主体通透感。"},
            }
            (recipe_dir / "bilibili_BV1abc.json").write_text(
                json.dumps(recipe, ensure_ascii=False),
                encoding="utf-8",
            )
            card = make_card("逆光调出日系感？掌握这3个技巧！")
            card["tone_guidance"] = {"overall": "existing"}
            (card_dir / "tutorial_bilibili_BV1abc.json").write_text(
                json.dumps(card, ensure_ascii=False),
                encoding="utf-8",
            )

            result = build_style_family_layer.build_layer(
                recipe_dir=recipe_dir,
                card_dir=card_dir,
                family_dir=family_dir,
                index_path=index_path,
                summary_path=summary_path,
            )

            self.assertEqual(result["tutorial_variants"], 1)
            self.assertTrue((family_dir / "japanese_transparent_backlight.json").exists())
            self.assertTrue(index_path.exists())
            updated = json.loads((card_dir / "tutorial_bilibili_BV1abc.json").read_text(encoding="utf-8"))
            self.assertEqual(updated["style_family"]["style_id"], "japanese_transparent_backlight")
            self.assertEqual(updated["tone_guidance"]["overall"], "existing")
            self.assertEqual(updated["coarse_style_family"]["style_id"], "master_reference_texture")


if __name__ == "__main__":
    unittest.main()
