from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import darktable_probe  # noqa: E402
import edit_intent  # noqa: E402
import preview_provider  # noqa: E402


SENTINEL_ENV = "LUMENFLOW_DARKTABLE_TEST_RAW"
SENTINEL_URL = "https://raw.githubusercontent.com/syoyo/tinydng/release/pixel3.dng"
SENTINEL_FINGERPRINT = {
    "sha256": "b8979553ec61b579c2600787e62d9e10885645358e07bafbd6c58cddc84cce4e",
    "size_bytes": 12234280,
}
MINIMAL_XMP = """<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="" xmlns:darktable="http://darktable.sf.net/"
    darktable:xmp_version="5" darktable:raw_params="0"
    darktable:auto_presets_applied="0" darktable:history_end="0"
    darktable:iop_order_version="2">
   <darktable:masks_history><rdf:Seq/></darktable:masks_history>
   <darktable:history><rdf:Seq/></darktable:history>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>
"""


@unittest.skipUnless(os.environ.get(SENTINEL_ENV), f"set {SENTINEL_ENV} to a public RAW fixture")
class DarktableLiveIntegrationTests(unittest.TestCase):
    def test_probe_preview_and_xmp_replay_receipt_preserve_inputs(self) -> None:
        sentinel = Path(os.environ[SENTINEL_ENV]).resolve()
        self.assertTrue(sentinel.is_file())
        self.assertEqual(
            preview_provider.file_fingerprint(sentinel),
            SENTINEL_FINGERPRINT,
            f"download the complete MIT fixture from {SENTINEL_URL}",
        )
        with tempfile.TemporaryDirectory(prefix="lumenflow-darktable-integration-") as directory:
            root = Path(directory)
            raw = root / ("sentinel" + sentinel.suffix.lower())
            shutil.copyfile(sentinel, raw)
            xmp = raw.with_name(raw.name + ".xmp")
            xmp.write_text(MINIMAL_XMP, encoding="utf-8")
            raw_before = preview_provider.file_fingerprint(raw)
            xmp_before = preview_provider.file_fingerprint(xmp)

            probe = darktable_probe.probe_darktable(raw=raw, output_dir=root / "probe", timeout=180)
            self.assertEqual(probe["status"], "passed")

            preview = preview_provider.DarktablePreviewProvider().create_preview(
                preview_provider.PreviewRequest(
                    source=raw,
                    output=root / "preview" / "sentinel.jpg",
                    base_profile=xmp,
                    dry_run=False,
                    timeout=180,
                    selection_reason="live integration sentinel",
                )
            )
            self.assertEqual(preview.status, "success")
            self.assertEqual(preview.state_completeness, "complete")

            intent = {
                "schema_version": "lumenflow.edit_intent.v2",
                "intent_id": "darktable-live-integration",
                "revision": 1,
                "authorization": {
                    "kind": "explicit_user_request",
                    "reference_id": "darktable-live-integration",
                },
                "source": {"path": str(raw), "fingerprint": raw_before},
                "preview_basis": {
                    "artifact_id": preview.artifact_id,
                    "starting_state_hash": preview.starting_state_hash,
                    "state_completeness": preview.state_completeness,
                },
                "purpose": "Exercise the verified isolated darktable slice",
                "style": {
                    "style_id": "existing_darktable_xmp",
                    "rationale": "Replay only the approved XMP state.",
                },
                "global_adjustments": {},
                "composition": {
                    "decision": "preserve_existing_crop",
                    "reason": "Dynamic crop compilation is not claimed.",
                },
                "local_adjustments": {
                    "decision": "none",
                    "reason": "Dynamic masks are not claimed.",
                    "masks": [],
                },
            }
            plan = edit_intent.compile_intent(
                intent,
                backend_id="darktable",
                output_dir=root / "execution",
            )
            receipt = edit_intent.execute_plan(
                plan,
                dry_run=False,
                timeout=180,
                allowed_output_dir=root / "execution",
            )

            self.assertEqual(receipt["status"], "success")
            self.assertTrue(receipt["source_unchanged"])
            self.assertIsNotNone(receipt["output_fingerprint"])
            self.assertEqual(preview_provider.file_fingerprint(raw), raw_before)
            self.assertEqual(preview_provider.file_fingerprint(xmp), xmp_before)


if __name__ == "__main__":
    unittest.main()
