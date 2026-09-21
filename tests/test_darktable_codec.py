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
            {
                "exposure", "temperature", "sigmoid", "filmicrgb", "colorbalancergb", "crop",
                "highlights", "demosaic", "denoiseprofile", "lens", "sharpen", "diffuse",
                "toneequal", "colorequal", "ashift",
            },
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
                "highlights": 48,
                "demosaic": 48,
                "denoiseprofile": 416,
                "lens": 356,
                "sharpen": 12,
                "diffuse": 60,
                "toneequal": 72,
                "colorequal": 128,
                "ashift": 892,
            },
        )

    def test_minimal_xmp_is_current_empty_history_base(self) -> None:
        base = darktable_codec.minimal_xmp()

        self.assertIn('darktable:xmp_version="5"', base)
        self.assertIn('darktable:history_end="0"', base)
        self.assertNotIn("darktable:operation=", base)
        darktable_codec.validate_xmp(base)

    def test_stale_darktable_xmp_version_is_rejected(self) -> None:
        stale = darktable_codec.minimal_xmp().replace(
            'darktable:xmp_version="5"', 'darktable:xmp_version="2"'
        )

        with self.assertRaisesRegex(darktable_codec.DarktableCodecError, "xmp_version"):
            darktable_codec.compile_xmp(
                stale,
                [{"operation": "exposure", "params": {}}],
            )

    def test_compile_replaces_one_instance_and_preserves_other_history(self) -> None:
        base, _ = darktable_codec.compile_xmp(
            darktable_codec.minimal_xmp(),
            [{"operation": "temperature", "params": {"red": 1.1, "green": 1.0, "blue": 0.9}}],
        )
        rendered, modules = darktable_codec.compile_xmp(
            base,
            [
                {"operation": "exposure", "params": {"exposure": 0.5}},
                {"operation": "temperature", "params": {"red": 1.2, "green": 1.0, "blue": 0.9}},
                {"operation": "crop", "params": {"cx": 0.1, "cy": 0.1, "cw": 0.9, "ch": 0.9}},
            ],
        )
        self.assertEqual([item["operation"] for item in modules], ["exposure", "temperature", "crop"])
        self.assertIn("darktable:operation=\"temperature\"", rendered)
        self.assertIn("darktable:operation=\"exposure\"", rendered)
        self.assertIn("darktable:operation=\"temperature\"", rendered)
        self.assertIn("darktable:operation=\"crop\"", rendered)
        self.assertIn('darktable:history_end="3"', rendered)

    def test_global_mapping_replaces_existing_adjustment_modules_only(self) -> None:
        base = darktable_codec.minimal_xmp()
        base, _ = darktable_codec.compile_xmp(
            base,
            [
                {"operation": "exposure", "params": {"exposure": -1.0}},
                {"operation": "colorbalancergb", "params": {"contrast": -0.2}},
            ],
        )
        rendered, modules = darktable_codec.compile_xmp(
            base,
            darktable_codec.modules_from_global_adjustments(
                {"exposure_ev": 0.4, "contrast": 12}
            ),
        )
        self.assertTrue(all(item["replace"] for item in modules))
        self.assertEqual(rendered.count('darktable:operation="exposure"'), 1)
        self.assertEqual(rendered.count('darktable:operation="colorbalancergb"'), 1)
        self.assertIn('darktable:history_end="2"', rendered)

    def test_replace_is_strict_boolean_and_priority_is_bounded(self) -> None:
        with self.assertRaisesRegex(darktable_codec.DarktableCodecError, "replace must be boolean"):
            darktable_codec.encode_module(
                {"operation": "exposure", "params": {}, "replace": "false"}
            )
        with self.assertRaisesRegex(darktable_codec.DarktableCodecError, "multi_priority.*range"):
            darktable_codec.encode_module(
                {"operation": "exposure", "params": {}, "multi_priority": 1001}
            )
        with self.assertRaisesRegex(darktable_codec.DarktableCodecError, "multi_priority.*range"):
            darktable_codec.encode_module(
                {"operation": "exposure", "params": {}, "multi_priority": -1}
            )

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
            darktable_codec.encode_module({"operation": "rotatepixels", "params": {}})
        with self.assertRaisesRegex(darktable_codec.DarktableCodecError, "unverified fields"):
            darktable_codec.encode_module(
                {"operation": "exposure", "params": {"unknown_slider": 1}}
            )
        with self.assertRaisesRegex(darktable_codec.DarktableCodecError, "must be an integer"):
            darktable_codec.encode_module({"operation": "exposure", "params": {"mode": 0.5}})

    def test_phase2_fields_are_bounded_and_lens_strings_are_binary_safe(self) -> None:
        highlights = darktable_codec.encode_module(
            {"operation": "highlights", "params": {"mode": 5, "iterations": 32, "recovery": 5}}
        )
        self.assertEqual(len(bytes.fromhex(highlights["params"])), 48)
        lens = darktable_codec.encode_module(
            {
                "operation": "lens",
                "params": {"method": 1, "camera": "DC-S5", "lens": "Lumix test lens"},
            }
        )
        self.assertEqual(len(bytes.fromhex(lens["params"])), 356)
        with self.assertRaisesRegex(darktable_codec.DarktableCodecError, "above the verified range"):
            darktable_codec.encode_module(
                {"operation": "demosaic", "params": {"cs_iter": 26}}
            )
        with self.assertRaisesRegex(darktable_codec.DarktableCodecError, "verified values"):
            darktable_codec.encode_module(
                {"operation": "demosaic", "params": {"demosaicing_method": 2052}}
            )
        with self.assertRaisesRegex(darktable_codec.DarktableCodecError, "NUL-free"):
            darktable_codec.encode_module(
                {"operation": "lens", "params": {"camera": "bad\x00camera"}}
            )

    def test_phase2_array_fields_are_explicit_not_arbitrary_payloads(self) -> None:
        module = darktable_codec.encode_module(
            {
                "operation": "denoiseprofile",
                "params": {"x_0_0": 0.0, "x_5_6": 1.0, "y_4_3": 0.25, "strength": 0.8},
            }
        )
        self.assertEqual(len(bytes.fromhex(module["params"])), 416)
        with self.assertRaisesRegex(darktable_codec.DarktableCodecError, "unverified fields"):
            darktable_codec.encode_module(
                {"operation": "colorequal", "params": {"curve": [1, 2, 3]}}
            )

    def test_malformed_or_non_darktable_xmp_is_rejected(self) -> None:
        with self.assertRaises(darktable_codec.DarktableCodecError):
            darktable_codec.compile_xmp("<xmpmeta />", [{"operation": "exposure", "params": {}}])


if __name__ == "__main__":
    unittest.main()
