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

    def test_classification_preserves_an_existing_semantic_family(self) -> None:
        card = make_card("摄影参考案例")
        card["style_family"] = {
            "style_id": "blue_hour_travel_night",
            "style_name": "蓝调时刻旅拍夜景",
        }

        self.assertEqual(
            build_style_family_layer.classify_card(card),
            "blue_hour_travel_night",
        )

    def test_build_layer_emits_sanitized_reusable_knowledge_and_private_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recipe_dir = root / "recipes"
            card_dir = root / "cards"
            family_dir = root / "families"
            index_path = root / "style_library_index.json"
            provenance_path = root / "private" / "style_source_map.json"
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
                provenance_path=provenance_path,
                summary_path=summary_path,
            )

            self.assertEqual(result["tutorial_variants"], 1)
            self.assertTrue((family_dir / "japanese_transparent_backlight.json").exists())
            self.assertTrue(index_path.exists())
            self.assertTrue(provenance_path.exists())
            updated = json.loads((card_dir / "tutorial_bilibili_BV1abc.json").read_text(encoding="utf-8"))
            self.assertEqual(updated["style_family"]["style_id"], "japanese_transparent_backlight")
            self.assertEqual(updated["tone_guidance"]["overall"], "existing")
            self.assertEqual(updated["coarse_style_family"]["style_id"], "master_reference_texture")

            reusable = json.loads(
                (family_dir / "japanese_transparent_backlight.json").read_text(encoding="utf-8")
            )
            self.assertEqual(reusable["schema_version"], "lumenflow.reusable_style_knowledge.v1")
            self.assertEqual(reusable["style_id"], "japanese_transparent_backlight")
            self.assertEqual(reusable["source_evidence"]["tutorial_count"], 1)
            self.assertEqual(reusable["source_evidence"]["category_counts"], {"basic_tone": 1})
            self.assertIn("operation_order", reusable)
            self.assertIn("tone_guidance", reusable)
            self.assertIn("color_guidance", reusable)

            public_text = json.dumps(reusable, ensure_ascii=False) + index_path.read_text(encoding="utf-8")
            for source_noise in (
                "BV1abc",
                "bilibili",
                "逆光调出日系感？掌握这3个技巧！",
                "https://",
                "逆光脸黑",
                "提高曝光",
            ):
                self.assertNotIn(source_noise, public_text)

            provenance_text = provenance_path.read_text(encoding="utf-8")
            self.assertIn("BV1abc", provenance_text)
            self.assertIn("逆光调出日系感？掌握这3个技巧！", provenance_text)

    def test_family_payload_merges_duplicate_video_cards_without_source_identity(self) -> None:
        first = make_card("日系通透逆光教程", "tutorial_bilibili_BV1first")
        first["evidence"] = {"category_counts": {"basic_tone": 2, "hsl": 1}}
        second = make_card("另一个逆光教程", "tutorial_bilibili_BV1second")
        second["evidence"] = {"category_counts": {"basic_tone": 1, "mask": 2}}

        payload = build_style_family_layer.build_family_payload(
            "japanese_transparent_backlight",
            [first, second],
        )

        self.assertEqual(payload["source_evidence"]["tutorial_count"], 2)
        self.assertEqual(
            payload["source_evidence"]["category_counts"],
            {"basic_tone": 3, "hsl": 1, "mask": 2},
        )
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("BV1first", serialized)
        self.assertNotIn("BV1second", serialized)
        self.assertNotIn("另一个逆光教程", serialized)

    def test_only_reusable_style_and_method_families_are_publishable(self) -> None:
        self.assertTrue(build_style_family_layer.is_publishable_family("japanese_clean_portrait"))
        self.assertTrue(build_style_family_layer.is_publishable_family("rgb_curve_method"))
        self.assertFalse(build_style_family_layer.is_publishable_family("tool_workflow_non_style"))
        self.assertFalse(build_style_family_layer.is_publishable_family("non_tutorial_reference"))


if __name__ == "__main__":
    unittest.main()
