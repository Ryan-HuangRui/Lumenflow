from __future__ import annotations

import json
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import curate_photos


JPEG_BUFFER = BytesIO()
Image.new("RGB", (2, 2), "white").save(JPEG_BUFFER, format="JPEG")
JPEG_1X1 = JPEG_BUFFER.getvalue()


class CuratePhotosTests(unittest.TestCase):
    def test_prepare_workspace_filters_capture_date_and_builds_contact_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            output = root / "curation"
            source.mkdir()
            june = source / "P1000001.RW2"
            july = source / "P1000002.RW2"
            june.write_bytes(b"raw-june")
            july.write_bytes(b"raw-july")

            capture_times = {
                june.name: "2026:06:12 10:15:30",
                july.name: "2026:07:01 09:00:00",
            }

            def metadata_reader(path: Path) -> dict[str, str]:
                return {"capture_time": capture_times[path.name]}

            def preview_extractor(_raw: Path, destination: Path) -> None:
                destination.write_bytes(JPEG_1X1)

            manifest = curate_photos.prepare_workspace(
                source_dir=source,
                output_dir=output,
                date_from="2026-06-01",
                date_to="2026-06-30",
                metadata_reader=metadata_reader,
                preview_extractor=preview_extractor,
                per_sheet=20,
                columns=5,
            )

            self.assertEqual(manifest["schema_version"], "lumenflow.candidate_manifest.v1")
            self.assertEqual(manifest["candidate_count"], 1)
            self.assertEqual(manifest["candidates"][0]["asset_id"], "P1000001.RW2")
            self.assertEqual(manifest["candidates"][0]["capture_time"], "2026-06-12T10:15:30")
            self.assertTrue((output / "candidate_manifest.json").exists())
            contact_sheet = output / "contact_sheets" / "contact_sheet_001.jpg"
            self.assertTrue(contact_sheet.exists())
            with Image.open(contact_sheet) as sheet:
                self.assertEqual(sheet.height, 296)
            self.assertEqual(june.read_bytes(), b"raw-june")
            self.assertEqual(july.read_bytes(), b"raw-july")

    def test_validate_selection_plan_accepts_model_authored_roles_and_sequence(self) -> None:
        manifest = self._manifest()
        plan = self._plan()

        normalized = curate_photos.validate_selection_plan(plan, manifest)

        self.assertEqual([item["asset_id"] for item in normalized["selection"]], ["A.RW2", "B.RW2"])
        self.assertEqual(normalized["status"]["decision"], "agent_recommended_pending_user_confirmation")

    def test_validate_selection_plan_rejects_unknown_duplicate_and_non_contiguous_assets(self) -> None:
        manifest = self._manifest()
        invalid_plans = []

        unknown = self._plan()
        unknown["selection"][1]["asset_id"] = "UNKNOWN.RW2"
        invalid_plans.append(unknown)

        duplicate = self._plan()
        duplicate["selection"][1]["asset_id"] = "A.RW2"
        invalid_plans.append(duplicate)

        gap = self._plan()
        gap["selection"][1]["order"] = 3
        invalid_plans.append(gap)

        selected_as_alternate = self._plan()
        selected_as_alternate["alternates"][0]["asset_ids"] = ["A.RW2"]
        invalid_plans.append(selected_as_alternate)

        for plan in invalid_plans:
            with self.subTest(plan=plan):
                with self.assertRaises(curate_photos.SelectionPlanError):
                    curate_photos.validate_selection_plan(plan, manifest)

    def test_validate_selection_plan_rejects_raw_mutation_claim(self) -> None:
        plan = self._plan()
        plan["status"]["raw_files_modified"] = True

        with self.assertRaisesRegex(curate_photos.SelectionPlanError, "raw_files_modified"):
            curate_photos.validate_selection_plan(plan, self._manifest())

    def test_finalize_packages_ordered_previews_and_report_without_touching_raws(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            workspace = root / "workspace"
            previews = workspace / "previews"
            source.mkdir()
            previews.mkdir(parents=True)

            raw_a = source / "A.RW2"
            raw_b = source / "B.RW2"
            raw_a.write_bytes(b"raw-a")
            raw_b.write_bytes(b"raw-b")
            (previews / "0001_A.jpg").write_bytes(JPEG_1X1)
            (previews / "0002_B.jpg").write_bytes(JPEG_1X1)

            manifest = self._manifest(source=source, workspace=workspace)
            manifest_path = workspace / "candidate_manifest.json"
            plan_path = workspace / "selection_plan.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            plan_path.write_text(json.dumps(self._plan()), encoding="utf-8")

            result = curate_photos.finalize_selection(
                manifest_path=manifest_path,
                plan_path=plan_path,
                output_dir=workspace,
            )

            self.assertEqual(result["selected_count"], 2)
            self.assertEqual(
                [item["role"] for item in result["selection_plan"]["selection"]],
                ["Opening", "Detail"],
            )
            self.assertTrue((workspace / "selected_previews" / "01_A.jpg").exists())
            self.assertTrue((workspace / "selected_previews" / "02_B.jpg").exists())
            report = (workspace / "selection_report.md").read_text(encoding="utf-8")
            self.assertIn("Opening", report)
            self.assertIn("A.RW2", report)
            self.assertEqual(raw_a.read_bytes(), b"raw-a")
            self.assertEqual(raw_b.read_bytes(), b"raw-b")

    @staticmethod
    def _manifest(source: Path | None = None, workspace: Path | None = None) -> dict:
        source = source or Path("/photos")
        workspace = workspace or Path("/workspace")
        return {
            "schema_version": "lumenflow.candidate_manifest.v1",
            "source_dir": str(source),
            "preview_basis": "embedded_camera_jpeg",
            "candidate_count": 3,
            "candidates": [
                {
                    "asset_id": "A.RW2",
                    "source": str(source / "A.RW2"),
                    "preview": str(workspace / "previews" / "0001_A.jpg"),
                    "capture_time": "2026-06-11T08:00:00",
                },
                {
                    "asset_id": "B.RW2",
                    "source": str(source / "B.RW2"),
                    "preview": str(workspace / "previews" / "0002_B.jpg"),
                    "capture_time": "2026-06-11T08:01:00",
                },
                {
                    "asset_id": "C.RW2",
                    "source": str(source / "C.RW2"),
                    "preview": str(workspace / "previews" / "0003_C.jpg"),
                    "capture_time": "2026-06-11T08:02:00",
                },
            ],
            "failures": [],
        }

    @staticmethod
    def _plan() -> dict:
        return {
            "schema_version": "lumenflow.selection_plan.v1",
            "purpose": "A concise Bangkok travel story",
            "selection": [
                {
                    "order": 1,
                    "asset_id": "A.RW2",
                    "role": "Opening",
                    "reason": "Establishes place and atmosphere.",
                },
                {
                    "order": 2,
                    "asset_id": "B.RW2",
                    "role": "Detail",
                    "reason": "Adds a human-scale visual beat.",
                },
            ],
            "alternates": [
                {
                    "for_asset_id": "B.RW2",
                    "asset_ids": ["C.RW2"],
                    "tradeoff": "Stronger geometry, less intimacy.",
                }
            ],
            "edit_experiments": [
                {
                    "asset_id": "A.RW2",
                    "tests": ["warm documentary", "cool night contrast"],
                }
            ],
            "status": {
                "decision": "agent_recommended_pending_user_confirmation",
                "raw_files_modified": False,
            },
        }


if __name__ == "__main__":
    unittest.main()
