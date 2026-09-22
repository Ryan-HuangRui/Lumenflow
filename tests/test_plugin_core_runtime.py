from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)


class PluginCoreRuntimeTests(unittest.TestCase):
    def _source_package_env(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        return environment

    def test_setuptools_finds_nested_runtime_subpackages(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('include = ["lumenflow*"]', pyproject)

    def test_runtime_subpackages_import_without_scripts_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    str(PYTHON),
                    "-c",
                    (
                        "from lumenflow.core import edit_intent, preview, review; "
                        "from lumenflow.execution import render; "
                        "from lumenflow.backends.rawtherapee import pp3; "
                        "from lumenflow.backends.darktable import codec; "
                        "assert edit_intent.EDIT_INTENT_SCHEMA_VERSION == 'lumenflow.edit_intent.v2'; "
                        "assert callable(edit_intent.validate_edit_intent); "
                        "assert preview.PREVIEW_ARTIFACT_SCHEMA_VERSION == 'lumenflow.preview_artifact.v1'; "
                        "assert callable(preview.file_fingerprint); "
                        "assert review.REVIEW_SESSION_SCHEMA_VERSION == 'lumenflow.review_session.v1'; "
                        "assert callable(review.validate_review_result); "
                        "assert render.DARKTABLE_ICC_TYPES; "
                        "assert callable(render.build_rawtherapee_command); "
                        "assert pp3.PP3_COMPILER_VERSION == 'lumenflow.rawtherapee-pp3.v4'; "
                        "assert callable(pp3.compile_profile_text); "
                        "assert codec.CODEC_SCHEMA_VERSION == 'lumenflow.darktable_codec.v2'; "
                        "assert callable(codec.compile_xmp)"
                    ),
                ],
                cwd=directory,
                env=self._source_package_env(),
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_edit_intent_cli_remains_checkout_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [str(PYTHON), str(ROOT / "scripts" / "edit_intent.py"), "--help"],
                cwd=directory,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("compile", result.stdout)
        self.assertIn("execute", result.stdout)

    def test_core_modules_do_not_modify_import_path(self) -> None:
        package_root = ROOT / "src" / "lumenflow"
        for module in package_root.rglob("*.py"):
            self.assertNotIn("sys.path", module.read_text(encoding="utf-8"), module.name)


if __name__ == "__main__":
    unittest.main()
