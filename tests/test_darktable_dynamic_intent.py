from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import edit_intent  # noqa: E402
import preview_provider  # noqa: E402


class DarktableDynamicIntentTests(unittest.TestCase):
    def _intent(self, raw: Path, xmp: Path, preview: preview_provider.PreviewArtifact) -> dict:
        return {
            "schema_version": "lumenflow.edit_intent.v2",
            "intent_id": "darktable-dynamic-001",
            "revision": 1,
            "authorization": {"kind": "explicit_user_request", "reference_id": "test"},
            "source": {"path": str(raw), "fingerprint": preview_provider.file_fingerprint(raw)},
            "preview_basis": {
                "artifact_id": preview.artifact_id,
                "starting_state_hash": preview.starting_state_hash,
                "state_completeness": preview.state_completeness,
            },
            "purpose": "codec test",
            "style": {
                "style_id": "darktable-verified-modules",
                "rationale": "Use only version-checked module structs.",
                "darktable": {
                    "modules": [
                        {"operation": "filmicrgb", "params": {"contrast": 1.1, "saturation": 4.0}},
                        {"operation": "colorbalancergb", "params": {"contrast": 0.05}},
                        {"operation": "crop", "params": {"cx": 0.05, "cy": 0.05, "cw": 0.95, "ch": 0.95}},
                    ]
                },
            },
            "global_adjustments": {"exposure_ev": 0.35},
            "composition": {"decision": "crop", "reason": "fixture crop", "crop": {
                "unit": "pixels", "x": 300, "y": 200, "width": 5400, "height": 3600
            }},
            "local_adjustments": {"decision": "none", "reason": "none", "masks": []},
        }

    def test_dynamic_module_plan_materializes_and_validates_from_original_preview_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            xmp = root / "bangkok.DNG.xmp"
            raw.write_bytes(b"raw-bangkok")
            xmp.write_text(
                (ROOT / "tests" / "fixtures" / "darktable_profile.xmp").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            preview = preview_provider.DarktablePreviewProvider().create_preview(
                preview_provider.PreviewRequest(raw, root / "preview.jpg", xmp, True, 10)
            )
            plan = edit_intent.compile_intent(
                self._intent(raw, xmp, preview),
                backend_id="darktable",
                output_dir=root / "execution",
            )
            self.assertEqual(
                plan["compiler"],
                {"id": "lumenflow.darktable-xmp-modules", "version": "1"},
            )
            content = plan["operations"][0]["payload"]["content"]
            self.assertIn('darktable:operation="filmicrgb"', content)
            self.assertIn('darktable:operation="colorbalancergb"', content)
            self.assertIn('darktable:operation="crop"', content)

            def fake_runner(command: list[str], *, dry_run: bool, timeout: int | None) -> int:
                self.assertFalse(dry_run)
                Path(command[3]).write_bytes(b"dynamic-render")
                return 0

            receipt = edit_intent.execute_plan(
                plan,
                dry_run=False,
                timeout=10,
                runner=fake_runner,
                allowed_output_dir=root / "execution",
            )
            self.assertEqual(receipt["status"], "success")
            self.assertTrue(receipt["source_unchanged"])


if __name__ == "__main__":
    unittest.main()
