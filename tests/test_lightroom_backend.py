from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import render_adjustment_plan
import render_lightroom


class LightroomBackendTests(unittest.TestCase):
    def test_maps_lumenflow_adjustments_to_lightroom_settings(self) -> None:
        settings = render_lightroom.lightroom_settings_from_adjustments(
            {
                "exposure_compensation": 0.35,
                "saturation": -4,
                "contrast": 18,
                "temperature": 5400,
                "highlights": -20,
                "shadow_compression": 35,
                "black": -12,
                "notes": "not executable",
            }
        )

        self.assertEqual(
            settings,
            {
                "Exposure": 0.35,
                "Saturation": -4,
                "Contrast": 18,
                "Temperature": 5400,
                "Highlights": -20,
                "Shadows": 35,
                "Blacks": -12,
            },
        )

    def test_render_plan_lightroom_dry_run_writes_commands_and_records(self) -> None:
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
                        "lightroom": {"photo_id": "123"},
                        "variants": [
                            {
                                "variant_id": "best",
                                "style_id": "clean_natural",
                                "rationale": "Use Lightroom as the rendering engine.",
                                "adjustments": {
                                    "exposure_compensation": 0.35,
                                    "saturation": -4,
                                    "temperature": 5400,
                                },
                            }
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
                local_config={"tools": {"lightroom_cli": "/custom/lr"}},
                engine="lightroom",
            )

            self.assertEqual(summary["engine"], "lightroom")
            self.assertEqual(summary["rendered"], 1)
            self.assertFalse((output_dir / "profiles").exists())

            records = json.loads((output_dir / "processing_records.json").read_text(encoding="utf-8"))
            self.assertEqual(records[0]["engine"], "lightroom")
            self.assertEqual(records[0]["photo_id"], "123")
            self.assertEqual(records[0]["status"], "dry_run")
            self.assertEqual(records[0]["output"], str(output_dir / "IMG_0001_best.jpg"))
            self.assertEqual(records[0]["lightroom_settings"]["Exposure"], 0.35)
            self.assertIn("/custom/lr develop apply --photo-id 123", records[0]["command"])
            self.assertIn("/custom/lr export photo 123", records[0]["command"])
            self.assertIn("--filename-suffix _best", records[0]["command"])

    def test_resolve_photo_id_from_json_response(self) -> None:
        self.assertEqual(render_lightroom.photo_id_from_response('{"result": {"id": "77"}}'), "77")
        self.assertEqual(render_lightroom.photo_id_from_response('{"result": {"photoId": 88}}'), "88")
        self.assertEqual(render_lightroom.photo_id_from_response('{"id": "99"}'), "99")


if __name__ == "__main__":
    unittest.main()
