from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import darktable_codec  # noqa: E402


class DarktableCodecTests(unittest.TestCase):
    def test_registry_contains_only_structs_verified_for_541(self) -> None:
        self.assertEqual(darktable_codec.DARKTABLE_VERSION, "5.4.1")
        self.assertEqual(
            set(darktable_codec.supported_operations()),
            {"exposure", "temperature", "sigmoid", "filmicrgb", "colorbalancergb", "crop"},
        )
        self.assertEqual(
            {name: len(spec.template) for name, spec in darktable_codec.MODULE_SPECS.items()},
            {
                "exposure": 28,
                "temperature": 20,
                "sigmoid": 56,
                "filmicrgb": 116,
                "colorbalancergb": 132,
                "crop": 24,
            },
        )

    def test_compile_replaces_one_instance_and_preserves_other_history(self) -> None:
        base = (ROOT / "tests" / "fixtures" / "darktable_profile.xmp").read_text(encoding="utf-8")
        rendered, modules = darktable_codec.compile_xmp(
            base,
            [
                {"operation": "exposure", "params": {"exposure": 0.5}},
                {"operation": "temperature", "params": {"red": 1.2, "green": 1.0, "blue": 0.9}},
                {"operation": "crop", "params": {"cx": 0.1, "cy": 0.1, "cw": 0.9, "ch": 0.9}},
            ],
        )
        self.assertEqual([item["operation"] for item in modules], ["exposure", "temperature", "crop"])
        self.assertIn("darktable:operation=\"basecurve\"", rendered)
        self.assertIn("darktable:operation=\"exposure\"", rendered)
        self.assertIn("darktable:operation=\"temperature\"", rendered)
        self.assertIn("darktable:operation=\"crop\"", rendered)
        self.assertIn('darktable:history_end="4"', rendered)

    def test_explicit_module_fields_are_encoded_deterministically(self) -> None:
        module = darktable_codec.encode_module(
            {
                "operation": "colorbalancergb",
                "params": {"contrast": 0.1, "saturation_global": -0.05},
            }
        )
        self.assertEqual(len(module["params"]), 264)
        self.assertEqual(module, darktable_codec.encode_module(
            {
                "operation": "colorbalancergb",
                "params": {"contrast": 0.1, "saturation_global": -0.05},
            }
        ))

    def test_global_mapping_is_explicit_and_fail_closed(self) -> None:
        modules = darktable_codec.modules_from_global_adjustments(
            {"exposure_ev": 0.4, "black_point": -0.01, "contrast": 12, "saturation": -5}
        )
        self.assertEqual([item["operation"] for item in modules], ["exposure", "colorbalancergb"])
        with self.assertRaises(darktable_codec.DarktableCodecError):
            darktable_codec.modules_from_global_adjustments({"highlight_recovery": 20})

    def test_unsupported_operations_and_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(darktable_codec.DarktableCodecError, "not verified"):
            darktable_codec.encode_module({"operation": "denoiseprofile", "params": {}})
        with self.assertRaisesRegex(darktable_codec.DarktableCodecError, "unverified fields"):
            darktable_codec.encode_module(
                {"operation": "exposure", "params": {"unknown_slider": 1}}
            )
        with self.assertRaisesRegex(darktable_codec.DarktableCodecError, "must be an integer"):
            darktable_codec.encode_module({"operation": "exposure", "params": {"mode": 0.5}})

    def test_malformed_or_non_darktable_xmp_is_rejected(self) -> None:
        with self.assertRaises(darktable_codec.DarktableCodecError):
            darktable_codec.compile_xmp("<xmpmeta />", [{"operation": "exposure", "params": {}}])


if __name__ == "__main__":
    unittest.main()
