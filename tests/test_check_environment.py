from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_environment


class CheckEnvironmentTests(unittest.TestCase):
    def test_command_check_marks_missing_required_tool(self) -> None:
        result = check_environment.check_command(
            name="rawtherapee-cli",
            phase="phase1_photos",
            required=True,
            command=["rawtherapee-cli", "-v"],
            timeout_seconds=1,
            which=lambda _name: None,
            runner=None,
        )

        self.assertEqual(result["status"], "missing_required")
        self.assertEqual(result["name"], "rawtherapee-cli")

    def test_command_check_marks_available_tool_and_captures_version(self) -> None:
        def fake_which(_name: str) -> str:
            return "/usr/local/bin/darktable-cli"

        def fake_runner(command: list[str], timeout: int) -> check_environment.CommandResult:
            self.assertEqual(command, ["darktable-cli", "--help"])
            self.assertEqual(timeout, 2)
            return check_environment.CommandResult(0, "darktable 5.4.1\nUsage:", "")

        result = check_environment.check_command(
            name="darktable-cli",
            phase="phase1_photos",
            required=True,
            command=["darktable-cli", "--help"],
            timeout_seconds=2,
            which=fake_which,
            runner=fake_runner,
        )

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["path"], "/usr/local/bin/darktable-cli")
        self.assertEqual(result["version"], "darktable 5.4.1")

    def test_command_check_accepts_custom_success_returncode(self) -> None:
        def fake_which(_name: str) -> str:
            return "/usr/local/bin/rawtherapee-cli"

        def fake_runner(command: list[str], timeout: int) -> check_environment.CommandResult:
            return check_environment.CommandResult(255, "RawTherapee, version 5.12, command line.\n", "")

        result = check_environment.check_command(
            name="rawtherapee-cli",
            phase="phase1_photos",
            required=False,
            command=["rawtherapee-cli", "-v"],
            timeout_seconds=2,
            success_returncodes=(0, 255),
            which=fake_which,
            runner=fake_runner,
        )

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["version"], "RawTherapee, version 5.12, command line.")

    def test_command_check_marks_unresponsive_tool_as_unavailable(self) -> None:
        def fake_which(_name: str) -> str:
            return "/usr/local/bin/rawtherapee-cli"

        def fake_runner(command: list[str], timeout: int) -> check_environment.CommandResult:
            raise TimeoutError("timed out")

        result = check_environment.check_command(
            name="rawtherapee-cli",
            phase="phase1_photos",
            required=False,
            command=["rawtherapee-cli", "-v"],
            timeout_seconds=1,
            which=fake_which,
            runner=fake_runner,
        )

        self.assertEqual(result["status"], "unavailable_optional")
        self.assertIn("timed out", result["message"])

    def test_python_module_check_reports_missing_optional(self) -> None:
        result = check_environment.check_python_module(
            module_name="does_not_exist_lumenflow",
            phase="phase3_tutorials",
            required=False,
        )

        self.assertEqual(result["status"], "missing_optional")
        self.assertEqual(result["name"], "does_not_exist_lumenflow")

    def test_collect_environment_summary_counts_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "knowledge" / "source_records").mkdir(parents=True)
            (root / "knowledge" / "source_records" / "x_sources.json").write_text(
                "{}",
                encoding="utf-8",
            )

            checks = check_environment.collect_environment(
                repo_root=root,
                env={"X_BEARER_TOKEN": "token"},
                command_specs=[],
                module_specs=[],
            )

        self.assertEqual(checks["summary"]["missing_required"], 0)
        config_names = {item["name"] for item in checks["config"]}
        self.assertIn("X_BEARER_TOKEN", config_names)
        self.assertIn("knowledge/source_records/x_sources.json", config_names)

    def test_local_tool_config_rewrites_configured_commands(self) -> None:
        specs = [
            check_environment.CommandSpec(
                "rawtherapee-cli",
                "phase1_photos",
                True,
                ["rawtherapee-cli", "-v"],
            )
        ]

        resolved = check_environment.apply_local_tool_config(
            specs,
            {"tools": {"rawtherapee_cli": "/custom/rawtherapee-cli"}},
        )

        self.assertEqual(resolved[0].name, "/custom/rawtherapee-cli")
        self.assertEqual(resolved[0].command, ["/custom/rawtherapee-cli", "-v"])

    def test_main_outputs_json(self) -> None:
        with mock.patch.object(
            check_environment,
            "collect_environment",
            return_value={"summary": {"available": 1}, "tools": [], "python": [], "config": []},
        ):
            with tempfile.TemporaryDirectory() as directory:
                output = check_environment.render_environment_json(Path(directory), os.environ)

        parsed = json.loads(output)
        self.assertEqual(parsed["summary"]["available"], 1)


if __name__ == "__main__":
    unittest.main()
