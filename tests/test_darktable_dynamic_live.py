from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import edit_intent  # noqa: E402
import preview_provider  # noqa: E402


LIVE_ENV = "LUMENFLOW_DARKTABLE_LIVE_RAW_DIR"


@unittest.skipUnless(os.environ.get(LIVE_ENV), f"set {LIVE_ENV} to the Bangkok RAW fixture directory")
class DarktableDynamicLiveTests(unittest.TestCase):
    def test_preview_compile_execute_without_source_sidecars(self) -> None:
        fixture_dir = Path(os.environ[LIVE_ENV]).resolve()
        raws = sorted(fixture_dir.glob("*.RW2"))
        self.assertGreaterEqual(len(raws), 3)
        base_text = (ROOT / "tests" / "fixtures" / "darktable_profile.xmp").read_text(
            encoding="utf-8"
        )

        with tempfile.TemporaryDirectory(prefix="lumenflow-darktable-dynamic-live-") as directory:
            root = Path(directory)
            base_xmp = root / "preview-base.xmp"
            base_xmp.write_text(base_text, encoding="utf-8")
            for index, fixture in enumerate(raws[:3]):
                raw = root / fixture.name
                shutil.copyfile(fixture, raw)
                self.assertFalse(raw.with_suffix(".xmp").exists())
                self.assertFalse(raw.with_name(raw.name + ".xmp").exists())
                source_before = preview_provider.file_fingerprint(raw)
                preview = preview_provider.DarktablePreviewProvider().create_preview(
                    preview_provider.PreviewRequest(
                        source=raw,
                        output=root / "previews" / f"{index}.jpg",
                        base_profile=base_xmp,
                        dry_run=False,
                        timeout=180,
                        selection_reason="darktable dynamic no-sidecar live test",
                    )
                )
                self.assertEqual(preview.status, "success", preview.failure_reason)
                self.assertEqual(preview.state_completeness, "complete")
                self.assertEqual(preview.state_inputs[0]["role"], "base_profile")

                intent = {
                    "schema_version": "lumenflow.edit_intent.v2",
                    "intent_id": f"darktable-dynamic-live-{index}",
                    "revision": 1,
                    "authorization": {
                        "kind": "explicit_user_request",
                        "reference_id": "darktable-dynamic-live",
                    },
                    "source": {"path": str(raw), "fingerprint": source_before},
                    "preview_basis": {
                        "artifact_id": preview.artifact_id,
                        "starting_state_hash": preview.starting_state_hash,
                        "state_completeness": preview.state_completeness,
                        "state_inputs": [dict(preview.state_inputs[0])],
                    },
                    "purpose": "Exercise dynamic darktable modules without a source sidecar.",
                    "style": {
                        "style_id": "darktable-live-dynamic",
                        "rationale": "Use only the verified 5.4.1 module codec.",
                        "darktable": {
                            "modules": [
                                {"operation": "filmicrgb", "params": {"contrast": 1.1}},
                                {"operation": "sigmoid", "params": {"contrast_skewness": 0.1}},
                                {"operation": "colorbalancergb", "params": {"contrast": 0.05}},
                            ],
                        },
                    },
                    "global_adjustments": {"exposure_ev": 0.25},
                    "composition": {
                        "decision": "preserve_existing_crop",
                        "reason": "No vendor-neutral pixel crop is claimed for darktable.",
                    },
                    "local_adjustments": {
                        "decision": "none",
                        "reason": "No local masks in this live slice.",
                        "masks": [],
                    },
                }
                plan = edit_intent.compile_intent(
                    intent,
                    backend_id="darktable",
                    output_dir=root / "execution" / str(index),
                )
                self.assertEqual(plan["compiler"]["id"], "lumenflow.darktable-xmp-modules")
                self.assertEqual(plan["starting_state"]["xmp_content"], base_text)
                receipt = edit_intent.execute_plan(
                    plan,
                    dry_run=False,
                    timeout=180,
                    allowed_output_dir=root / "execution" / str(index),
                )
                self.assertEqual(receipt["status"], "success", receipt["failure_reason"])
                self.assertTrue(receipt["source_unchanged"])
                self.assertEqual(preview_provider.file_fingerprint(raw), source_before)
                self.assertFalse(raw.with_suffix(".xmp").exists())
                self.assertFalse(raw.with_name(raw.name + ".xmp").exists())


if __name__ == "__main__":
    unittest.main()
