from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


class CurationPackageTests(unittest.TestCase):
    def test_package_exposes_public_workflow_api(self) -> None:
        from lumenflow.curation import (
            CurationError,
            SelectionPlanError,
            finalize_selection,
            prepare_workspace,
            scan_raws,
        )

        self.assertTrue(callable(prepare_workspace))
        self.assertTrue(callable(finalize_selection))
        self.assertTrue(callable(scan_raws))
        self.assertTrue(issubclass(SelectionPlanError, CurationError))

    def test_legacy_scripts_delegate_to_package_implementations(self) -> None:
        from lumenflow.curation import curate_photos as package_curate_photos
        from lumenflow.curation import scan_raws as package_scan_raws

        import curate_photos as legacy_curate_photos
        import scan_raws as legacy_scan_raws

        self.assertIs(legacy_curate_photos.prepare_workspace, package_curate_photos.prepare_workspace)
        self.assertIs(legacy_curate_photos.finalize_selection, package_curate_photos.finalize_selection)
        self.assertIs(legacy_curate_photos.scan_raws, package_scan_raws)
        self.assertIs(legacy_scan_raws.scan_raws, package_scan_raws)


if __name__ == "__main__":
    unittest.main()
