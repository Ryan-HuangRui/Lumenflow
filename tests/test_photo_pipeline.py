from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import develop_photos
import render_raw
import scan_raws


class PhotoPipelineTests(unittest.TestCase):
    def test_scan_reads_darktable_xmp_rating_and_color_labels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            raw = tmp_path / "IMG_0001.NEF"
            raw.write_bytes(b"fake raw")
            raw.with_name(raw.name + ".xmp").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description
      xmlns:xmp="http://ns.adobe.com/xap/1.0/"
      xmlns:darktable="http://darktable.sf.net/"
      xmp:Rating="4"
      darktable:colorlabels="0,2" />
  </rdf:RDF>
</x:xmpmeta>
""",
                encoding="utf-8",
            )

            raws = scan_raws.scan_raws(tmp_path, selected_only=True, min_rating=3)

            self.assertEqual(len(raws), 1)
            self.assertEqual(raws[0]["rating"], 4)
            self.assertIs(raws[0]["selected"], True)
            self.assertEqual(raws[0]["color_labels"], ["red", "green"])
            self.assertTrue(raws[0]["sidecars"]["darktable_xmp"].endswith("IMG_0001.NEF.xmp"))

    def test_scan_reads_rawtherapee_pp3_rank(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            raw = tmp_path / "IMG_0002.ARW"
            raw.write_bytes(b"fake raw")
            raw.with_name(raw.name + ".pp3").write_text("[General]\nRank=5\n", encoding="utf-8")

            raws = scan_raws.scan_raws(tmp_path, selected_only=True, min_rating=5)

            self.assertEqual(len(raws), 1)
            self.assertEqual(raws[0]["rating"], 5)
            self.assertTrue(raws[0]["sidecars"]["rawtherapee_pp3"].endswith("IMG_0002.ARW.pp3"))

    def test_scan_selected_only_filters_unrated_and_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            selected = tmp_path / "selected.CR3"
            rejected = tmp_path / "rejected.CR3"
            unrated = tmp_path / "unrated.CR3"
            for path in [selected, rejected, unrated]:
                path.write_bytes(b"fake raw")
            selected.with_name(selected.name + ".xmp").write_text(
                '<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:Rating="3" />',
                encoding="utf-8",
            )
            rejected.with_name(rejected.name + ".xmp").write_text(
                '<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:Rating="-1" />',
                encoding="utf-8",
            )

            raws = scan_raws.scan_raws(tmp_path, selected_only=True, min_rating=1)

            self.assertEqual([Path(item["path"]).name for item in raws], ["selected.CR3"])

    def test_scan_selected_only_includes_color_labeled_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            raw = tmp_path / "green-label.NEF"
            raw.write_bytes(b"fake raw")
            raw.with_name(raw.name + ".xmp").write_text(
                """<rdf:Description
  xmlns:xmp="http://ns.adobe.com/xap/1.0/"
  xmlns:darktable="http://darktable.sf.net/"
  xmp:Rating="0"
  darktable:colorlabels="2" />""",
                encoding="utf-8",
            )

            raws = scan_raws.scan_raws(tmp_path, selected_only=True, min_rating=1)

            self.assertEqual([Path(item["path"]).name for item in raws], ["green-label.NEF"])
            self.assertEqual(raws[0]["selection_reason"], "color_label")

    def test_build_darktable_command_uses_sidecar_and_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            raw = tmp_path / "IMG_0003.RAF"
            xmp = tmp_path / "IMG_0003.RAF.xmp"
            output = tmp_path / "out" / "IMG_0003_clean_natural.jpg"

            command = render_raw.build_darktable_command(
                raw=raw,
                output=output,
                xmp=xmp,
                style_name="clean-natural",
                jpeg_quality=92,
            )

            self.assertEqual(command[:4], ["darktable-cli", str(raw), str(xmp), str(output)])
            self.assertIn("--style", command)
            self.assertIn("clean-natural", command)
            self.assertIn("--conf", command)
            self.assertIn("plugins/imageio/format/jpeg/quality=92", command)

    def test_develop_photos_dry_run_writes_records_for_selected_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            source_dir = tmp_path / "source"
            output_dir = tmp_path / "output"
            style_dir = tmp_path / "styles"
            profile_dir = tmp_path / "profiles"
            source_dir.mkdir()
            style_dir.mkdir()
            profile_dir.mkdir()

            selected = source_dir / "keeper.DNG"
            skipped = source_dir / "skip.DNG"
            selected.write_bytes(b"fake raw")
            skipped.write_bytes(b"fake raw")
            selected.with_name(selected.name + ".xmp").write_text(
                '<rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmp:Rating="4" />',
                encoding="utf-8",
            )
            (profile_dir / "clean.pp3").write_text("[Version]\nVersion=349\n", encoding="utf-8")
            (style_dir / "clean_natural.json").write_text(
                json.dumps(
                    {
                        "style_id": "clean_natural",
                        "style_name": "Clean Natural",
                        "raw_profiles": [str(profile_dir / "clean.pp3")],
                    }
                ),
                encoding="utf-8",
            )

            summary = develop_photos.run(
                source_dir=source_dir,
                output_dir=output_dir,
                style_cards_dir=style_dir,
                engine="darktable",
                selected_only=True,
                min_rating=1,
                style_id="clean_natural",
                dry_run=True,
                limit=None,
                render_timeout=10,
            )

            self.assertEqual(summary["processed"], 1)
            self.assertEqual(summary["skipped"], 1)
            records = json.loads((output_dir / "processing_records.json").read_text(encoding="utf-8"))
            self.assertTrue(records[0]["source"].endswith("keeper.DNG"))
            self.assertEqual(records[0]["engine"], "darktable")
            self.assertEqual(records[0]["status"], "dry_run")
            self.assertTrue((output_dir / "processing_report.md").exists())


if __name__ == "__main__":
    unittest.main()
