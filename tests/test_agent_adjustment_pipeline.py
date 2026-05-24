from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import create_previews
import render_adjustment_plan


class AgentAdjustmentPipelineTests(unittest.TestCase):
    def test_create_previews_dry_run_writes_manifest_for_selected_raws(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            source_dir = tmp_path / "source"
            output_dir = tmp_path / "previews"
            source_dir.mkdir()

            selected = source_dir / "keeper.DNG"
            skipped = source_dir / "skip.DNG"
            selected.write_bytes(b"fake raw")
            skipped.write_bytes(b"fake raw")
            selected.with_name(selected.name + ".xmp").write_text(
                '<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:Rating="3" />',
                encoding="utf-8",
            )

            summary = create_previews.run(
                source_dir=source_dir,
                output_dir=output_dir,
                selected_only=True,
                min_rating=1,
                limit=None,
                dry_run=True,
                render_timeout=10,
                local_config={},
            )

            self.assertEqual(summary["previewed"], 1)
            self.assertEqual(summary["skipped"], 1)
            manifest = json.loads((output_dir / "preview_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest), 1)
            self.assertTrue(manifest[0]["source"].endswith("keeper.DNG"))
            self.assertTrue(manifest[0]["preview"].endswith("keeper_preview.jpg"))
            self.assertIn("rawtherapee-cli", manifest[0]["command"])
            self.assertEqual(manifest[0]["status"], "dry_run")

    def test_create_previews_uses_configured_rawtherapee_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            source_dir = tmp_path / "source"
            output_dir = tmp_path / "previews"
            source_dir.mkdir()
            selected = source_dir / "keeper.DNG"
            selected.write_bytes(b"fake raw")
            selected.with_name(selected.name + ".xmp").write_text(
                '<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:Rating="3" />',
                encoding="utf-8",
            )

            create_previews.run(
                source_dir=source_dir,
                output_dir=output_dir,
                selected_only=True,
                min_rating=1,
                limit=None,
                dry_run=True,
                render_timeout=10,
                local_config={"tools": {"rawtherapee_cli": "/custom/rawtherapee-cli"}},
            )

            manifest = json.loads((output_dir / "preview_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("/custom/rawtherapee-cli", manifest[0]["command"])

    def test_render_adjustment_plan_dry_run_writes_profiles_and_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            raw = tmp_path / "IMG_0001.DNG"
            output_dir = tmp_path / "output"
            plan_path = tmp_path / "adjustment_plan.json"
            raw.write_bytes(b"fake raw")
            plan_path.write_text(
                json.dumps(
                    {
                        "schema_version": "lumenflow.adjustment_plan.v1",
                        "source": str(raw),
                        "variants": [
                            {
                                "variant_id": "best",
                                "style_id": "clean_natural",
                                "rationale": "Slightly dark natural-light portrait.",
                                "adjustments": {
                                    "exposure_compensation": 0.35,
                                    "saturation": -4,
                                    "black": 300,
                                    "temperature": 5400,
                                    "green": 1.02,
                                },
                                "composition": {
                                    "crop": {
                                        "enabled": True,
                                        "unit": "pixels",
                                        "x": 120,
                                        "y": 80,
                                        "width": 3600,
                                        "height": 2400,
                                        "fixed_ratio": True,
                                        "ratio": "3:2",
                                        "reason": "Remove distracting edge clutter.",
                                    }
                                },
                            },
                            {
                                "variant_id": "warm",
                                "style_id": "warm_sunset",
                                "rationale": "Warmer alternate direction also fits.",
                                "adjustments": {
                                    "exposure_compensation": 0.2,
                                    "saturation": 8,
                                },
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            summary = render_adjustment_plan.run(
                plan_path=plan_path,
                output_dir=output_dir,
                dry_run=True,
                render_timeout=10,
                local_config={},
            )

            self.assertEqual(summary["rendered"], 2)
            best_profile = output_dir / "profiles" / "IMG_0001_best.pp3"
            self.assertTrue(best_profile.exists())
            profile_text = best_profile.read_text(encoding="utf-8")
            self.assertIn("Compensation=0.35", profile_text)
            self.assertIn("Saturation=-4", profile_text)
            self.assertIn("Black=300", profile_text)
            self.assertIn("[White Balance]", profile_text)
            self.assertIn("Temperature=5400", profile_text)
            self.assertIn("[Crop]", profile_text)
            self.assertIn("Enabled=true", profile_text)
            self.assertIn("X=120", profile_text)
            self.assertIn("Y=80", profile_text)
            self.assertIn("W=3600", profile_text)
            self.assertIn("H=2400", profile_text)
            self.assertIn("FixedRatio=true", profile_text)
            self.assertIn("Ratio=3:2", profile_text)

            records = json.loads((output_dir / "processing_records.json").read_text(encoding="utf-8"))
            self.assertEqual([record["variant_id"] for record in records], ["best", "warm"])
            self.assertEqual(records[0]["style_id"], "clean_natural")
            self.assertEqual(records[0]["status"], "dry_run")
            self.assertTrue(records[0]["composition"]["crop"]["enabled"])
            self.assertIn(str(best_profile), records[0]["command"])
            report = (output_dir / "processing_report.md").read_text(encoding="utf-8")
            self.assertIn("- 变体：best", report)
            self.assertIn("exposure_compensation=0.35", report)
            self.assertIn("- 构图：crop enabled", report)

    def test_adjustment_plan_requires_variants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan_path = Path(directory) / "bad_plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "schema_version": "lumenflow.adjustment_plan.v1",
                        "source": str(Path(directory) / "IMG_0001.DNG"),
                        "variants": [],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(SystemExit):
                render_adjustment_plan.read_plan(plan_path)


if __name__ == "__main__":
    unittest.main()
