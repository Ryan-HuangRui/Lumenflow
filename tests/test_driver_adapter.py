from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import driver_adapter  # noqa: E402


class DriverAdapterTests(unittest.TestCase):
    def test_assess_bridge_accepts_only_verified_contract(self) -> None:
        assessment = driver_adapter.assess_bridge_status(
            {
                "connected": True,
                "bridge_contract": {
                    "plugin_version": "1.3.0",
                    "cli_version": "1.3.0",
                    "protocol_version": "2",
                    "version_match": True,
                    "capabilities": {
                        "safe_object_develop_write": True,
                        "verified_export_result": True,
                    },
                },
            }
        )

        self.assertTrue(assessment.ready)
        self.assertEqual(assessment.issues, ())

    def test_assess_bridge_rejects_unverified_write_capability(self) -> None:
        assessment = driver_adapter.assess_bridge_status(
            {
                "connected": True,
                "bridge_contract": {
                    "plugin_version": "1.2.2",
                    "cli_version": "1.2.2",
                    "protocol_version": "2",
                    "version_match": True,
                    "capabilities": {
                        "safe_object_develop_write": False,
                        "verified_export_result": False,
                    },
                },
            }
        )

        self.assertFalse(assessment.ready)
        self.assertIn("missing verified capability: safe_object_develop_write", assessment.issues)
        self.assertIn("missing verified capability: verified_export_result", assessment.issues)

    def test_assess_bridge_rejects_protocol_and_version_mismatch(self) -> None:
        assessment = driver_adapter.assess_bridge_status(
            {
                "connected": True,
                "bridge_contract": {
                    "plugin_version": "1.2.1",
                    "cli_version": "1.2.2",
                    "protocol_version": "1",
                    "version_match": False,
                    "capabilities": {},
                },
            }
        )

        self.assertFalse(assessment.ready)
        self.assertIn("unsupported bridge protocol: 1 (expected 2)", assessment.issues)
        self.assertIn("CLI and loaded plugin versions do not match", assessment.issues)

    def test_read_bridge_status_parses_json_and_uses_configured_cli(self) -> None:
        calls: list[tuple[list[str], int]] = []

        def runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
            calls.append((command, timeout))
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "connected": True,
                        "bridge_contract": {
                            "plugin_version": "1.3.0",
                            "cli_version": "1.3.0",
                            "protocol_version": "2",
                            "version_match": True,
                            "capabilities": {
                                "safe_object_develop_write": True,
                                "verified_export_result": True,
                            },
                        },
                    }
                ),
                stderr="",
            )

        status = driver_adapter.read_bridge_status("/custom/lr", timeout=7, runner=runner)

        self.assertTrue(status["connected"])
        self.assertEqual(calls, [(["/custom/lr", "-o", "json", "system", "status"], 7)])

    def test_read_bridge_status_rejects_failed_or_invalid_output(self) -> None:
        def failed(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 3, stdout="", stderr="bridge unavailable")

        with self.assertRaises(driver_adapter.BridgeSafetyError) as failed_error:
            driver_adapter.read_bridge_status("lr", runner=failed)
        self.assertIn("bridge unavailable", str(failed_error.exception))

        def invalid(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 0, stdout="not-json", stderr="")

        with self.assertRaises(driver_adapter.BridgeSafetyError) as invalid_error:
            driver_adapter.read_bridge_status("lr", runner=invalid)
        self.assertIn("not valid JSON", str(invalid_error.exception))

    def test_assess_bridge_rejects_missing_contract(self) -> None:
        assessment = driver_adapter.assess_bridge_status({"connected": True})

        self.assertFalse(assessment.ready)
        self.assertEqual(assessment.issues, ("bridge safety contract is missing",))

    def test_require_safe_bridge_raises_with_all_reasons(self) -> None:
        with self.assertRaises(driver_adapter.BridgeSafetyError) as error:
            driver_adapter.require_safe_bridge(
                {
                    "connected": False,
                    "bridge_contract": {
                        "protocol_version": "2",
                        "version_match": True,
                        "capabilities": {},
                    },
                }
            )

        self.assertIn("Lightroom bridge is not connected", str(error.exception))
        self.assertIn("safe_object_develop_write", str(error.exception))


if __name__ == "__main__":
    unittest.main()
