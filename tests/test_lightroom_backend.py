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

    def test_maps_advanced_lightroom_color_adjustments(self) -> None:
        settings = render_lightroom.lightroom_settings_from_adjustments(
            {
                "hsl": {
                    "orange": {"saturation": -5, "luminance": 8},
                    "green": {"hue": -10, "saturation": -20},
                },
                "color_mixer": {
                    "blue": {"saturation": -12, "luminance": -8},
                },
                "tone_curve": {
                    "parametric": {
                        "shadows": -8,
                        "lights": 6,
                        "highlight_split": 75,
                    },
                    "point": [[0, 0], [64, 58], [128, 132], [255, 255]],
                    "blue": [[0, 4], [128, 128], [255, 250]],
                    "curve_refine_saturation": 5,
                },
                "color_grading": {
                    "shadows": {"hue": 210, "saturation": 8},
                    "highlights": {"hue": 42, "saturation": 10},
                    "midtones": {"hue": 35, "saturation": 4, "luminance": -2},
                    "global": {"hue": 38, "saturation": 3},
                    "blending": 50,
                    "balance": 5,
                },
                "calibration": {
                    "shadow_tint": 4,
                    "red": {"hue": 5, "saturation": -3},
                    "blue": {"hue": -8, "saturation": 12},
                },
            }
        )

        self.assertEqual(settings["SaturationAdjustmentOrange"], -5)
        self.assertEqual(settings["LuminanceAdjustmentOrange"], 8)
        self.assertEqual(settings["HueAdjustmentGreen"], -10)
        self.assertEqual(settings["SaturationAdjustmentBlue"], -12)
        self.assertEqual(settings["ParametricShadows"], -8)
        self.assertEqual(settings["ParametricLights"], 6)
        self.assertEqual(settings["ParametricHighlightSplit"], 75)
        self.assertEqual(settings["ToneCurvePV2012"], [0, 0, 64, 58, 128, 132, 255, 255])
        self.assertEqual(settings["ToneCurvePV2012Blue"], [0, 4, 128, 128, 255, 250])
        self.assertEqual(settings["CurveRefineSaturation"], 5)
        self.assertEqual(settings["SplitToningShadowHue"], 210)
        self.assertEqual(settings["SplitToningHighlightSaturation"], 10)
        self.assertEqual(settings["ColorGradeMidtoneHue"], 35)
        self.assertEqual(settings["ColorGradeGlobalSat"], 3)
        self.assertEqual(settings["ColorGradeBlending"], 50)
        self.assertEqual(settings["SplitToningBalance"], 5)
        self.assertEqual(settings["ShadowTint"], 4)
        self.assertEqual(settings["RedHue"], 5)
        self.assertEqual(settings["BlueSaturation"], 12)

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
                                    "hsl": {
                                        "green": {"saturation": -20},
                                    },
                                    "tone_curve": {
                                        "point": [[0, 0], [128, 132], [255, 255]],
                                    },
                                    "color_grading": {
                                        "shadows": {"hue": 210, "saturation": 8},
                                    },
                                    "calibration": {
                                        "blue": {"hue": -8, "saturation": 12},
                                    },
                                },
                                "composition": {
                                    "decision": "no_crop",
                                    "reason": "The source framing is already intentional.",
                                },
                                "mask_decision": {
                                    "decision": "none",
                                    "reason": "Global Lightroom settings are sufficient for this frame.",
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
            self.assertEqual(records[0]["lightroom_settings"]["SaturationAdjustmentGreen"], -20)
            self.assertEqual(records[0]["lightroom_settings"]["ToneCurvePV2012"], [0, 0, 128, 132, 255, 255])
            self.assertEqual(records[0]["lightroom_settings"]["SplitToningShadowHue"], 210)
            self.assertEqual(records[0]["lightroom_settings"]["BlueSaturation"], 12)
            self.assertIn("/custom/lr develop apply --photo-id 123", records[0]["command"])
            self.assertIn("ToneCurvePV2012", records[0]["command"])
            self.assertIn("SaturationAdjustmentGreen", records[0]["command"])
            self.assertIn("/custom/lr export photo 123", records[0]["command"])
            self.assertIn("--filename-suffix _best", records[0]["command"])

    def test_builds_ai_mask_command_for_photo_id(self) -> None:
        command = render_lightroom.ai_mask_command(
            "123",
            {
                "type": "sky",
                "settings": {
                    "highlights": -35,
                    "dehaze": 12,
                    "temperature": 4800,
                },
            },
            executable="/custom/lr",
        )

        self.assertEqual(command[:6], ["/custom/lr", "develop", "ai", "batch", "sky", "--photos"])
        self.assertEqual(command[6], "123")
        self.assertIn("--adjust", command)
        adjustment_json = command[command.index("--adjust") + 1]
        self.assertEqual(
            json.loads(adjustment_json),
            {
                "Highlights": -35,
                "Dehaze": 12,
                "Temperature": 4800,
            },
        )

    def test_render_plan_lightroom_dry_run_writes_mask_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            raw = tmp_path / "IMG_0002.DNG"
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
                                "style_id": "landscape_blue_green_epic",
                                "rationale": "Darken sky locally after global tone.",
                                "adjustments": {
                                    "exposure_compensation": 0.2,
                                },
                                "composition": {
                                    "decision": "no_crop",
                                    "reason": "Keep the original framing while testing mask execution.",
                                },
                                "mask_decision": {
                                    "decision": "use_masks",
                                    "reason": "The sky needs local recovery.",
                                },
                                "masks": [
                                    {
                                        "type": "sky",
                                        "rationale": "Recover bright sky detail.",
                                        "settings": {
                                            "highlights": -35,
                                            "dehaze": 12,
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            render_adjustment_plan.run(
                plan_path=plan_path,
                output_dir=output_dir,
                dry_run=True,
                render_timeout=10,
                local_config={"tools": {"lightroom_cli": "/custom/lr"}},
                engine="lightroom",
            )

            records = json.loads((output_dir / "processing_records.json").read_text(encoding="utf-8"))
            self.assertEqual(records[0]["lightroom_masks"][0]["type"], "sky")
            self.assertEqual(records[0]["lightroom_masks"][0]["settings"]["Highlights"], -35)
            self.assertEqual(records[0]["mask_decision"]["decision"], "use_masks")
            self.assertIn("/custom/lr develop ai batch sky --photos 123", records[0]["command"])
            self.assertIn("--adjust", records[0]["command"])
            self.assertLess(
                records[0]["command"].index("develop apply"),
                records[0]["command"].index("develop ai batch sky"),
            )
            self.assertLess(
                records[0]["command"].index("develop ai batch sky"),
                records[0]["command"].index("export photo"),
            )
            report = (output_dir / "processing_report.md").read_text(encoding="utf-8")
            self.assertIn("- Lightroom 蒙版：sky", report)
            self.assertIn("Highlights=-35", report)

    def test_lightroom_backend_rejects_executable_crop(self) -> None:
        variant = {
            "variant_id": "best",
            "style_id": "clean_natural",
            "rationale": "Lightroom crop should be guarded.",
            "adjustments": {"exposure_compensation": 0.2},
            "composition": {
                "decision": "crop",
                "reason": "Would improve framing, but Lightroom backend cannot execute it yet.",
                "crop": {
                    "enabled": True,
                    "unit": "pixels",
                    "x": 100,
                    "y": 50,
                    "width": 2000,
                    "height": 1500,
                    "reason": "Remove edge clutter.",
                },
            },
            "mask_decision": {
                "decision": "none",
                "reason": "No local adjustment needed.",
            },
        }

        with self.assertRaises(ValueError) as error:
            render_lightroom.ensure_lightroom_composition_supported(variant)
        self.assertIn("does not execute crop", str(error.exception))

    def test_resolve_photo_id_from_json_response(self) -> None:
        self.assertEqual(render_lightroom.photo_id_from_response('{"result": {"id": "77"}}'), "77")
        self.assertEqual(render_lightroom.photo_id_from_response('{"result": {"photoId": 88}}'), "88")
        self.assertEqual(render_lightroom.photo_id_from_response('{"id": "99"}'), "99")


if __name__ == "__main__":
    unittest.main()
