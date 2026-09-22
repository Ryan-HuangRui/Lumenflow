from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)


class PluginPackageTests(unittest.TestCase):
    def test_photo_skills_are_mcp_first_with_cli_only_as_debug_fallback(self) -> None:
        expectations = {
            "curate-photos": (
                "lumenflow.status",
                "lumenflow.prepare_curation",
                "lumenflow.finalize_curation",
                "scripts/curate_photos.py",
            ),
            "develop-photos": (
                "lumenflow.status",
                "lumenflow.create_previews",
                "lumenflow.compile_edit",
                "lumenflow.execute_edit",
                "lumenflow.start_review",
                "lumenflow.advance_review",
                "scripts/edit_intent.py",
            ),
        }
        for skill_name, phrases in expectations.items():
            with self.subTest(skill=skill_name):
                text = (ROOT / "skills" / skill_name / "SKILL.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("## Runtime Routing (MCP First)", text)
                self.assertIn("developer/debug fallback only", text)
                for phrase in phrases:
                    self.assertIn(phrase, text)
                self.assertLess(text.index(phrases[1]), text.index(phrases[-1]))

    def test_project_declares_installable_src_layout_package(self) -> None:
        pyproject = ROOT / "pyproject.toml"
        self.assertTrue(pyproject.exists(), "PR1 must provide an installable pyproject.toml")
        text = pyproject.read_text(encoding="utf-8")
        self.assertIn('requires-python = ">=3.11"', text)
        self.assertIn('package-dir = {"" = "src"}', text)
        self.assertIn('include = ["lumenflow*"]', text)

    def test_package_modules_do_not_modify_import_path(self) -> None:
        package_root = ROOT / "src" / "lumenflow"
        self.assertTrue(package_root.is_dir())
        for module in package_root.glob("*.py"):
            self.assertNotIn("sys.path", module.read_text(encoding="utf-8"), module.name)

    def test_package_imports_from_arbitrary_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(ROOT / "src")
            result = subprocess.run(
                [
                    str(PYTHON),
                    "-c",
                    (
                        "import lumenflow; "
                        "from lumenflow import backend_capabilities, config, driver_adapter, task_store; "
                        "assert lumenflow.__version__; "
                        "assert backend_capabilities.backend_capabilities_for('rawtherapee').backend_id == 'rawtherapee'; "
                        "assert config.DEFAULT_LOCAL_CONFIG_PATH.name == 'lumenflow.local.json'; "
                        "assert driver_adapter.REQUIRED_PROTOCOL_VERSION == '2'; "
                        "assert callable(task_store.state_fingerprint)"
                    ),
                ],
                cwd=directory,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_backend_capabilities_script_runs_from_arbitrary_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [str(PYTHON), str(ROOT / "scripts" / "backend_capabilities.py"), "rawtherapee"],
                cwd=directory,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"backend_id": "rawtherapee"', result.stdout)


if __name__ == "__main__":
    unittest.main()
