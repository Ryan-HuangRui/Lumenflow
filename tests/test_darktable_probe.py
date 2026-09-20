from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import darktable_probe  # noqa: E402


class DarktableProbeTests(unittest.TestCase):
    def test_full_probe_uses_isolated_state_and_verifies_source_unchanged(self) -> None:
        commands: list[list[str]] = []

        def fake_runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            if command[-1] == "--version":
                return subprocess.CompletedProcess(command, 0, "this is darktable-cli 5.4.1\n", "")
            Path(command[2]).write_bytes(b"jpeg output")
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "IMG_0001.NEF"
            raw.write_bytes(b"immutable raw bytes")
            report = darktable_probe.probe_darktable(
                executable="/usr/local/bin/darktable-cli",
                raw=raw,
                output_dir=root / "probe-output",
                runner=fake_runner,
            )

        self.assertEqual(report["schema_version"], "lumenflow.darktable_probe.v1")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["version"], "5.4.1")
        self.assertTrue(report["source_unchanged"])
        self.assertIsNotNone(report["output_fingerprint"])
        self.assertEqual([stage["name"] for stage in report["stages"]], ["version", "isolated_export"])
        export_command = commands[1]
        self.assertIn("--configdir", export_command)
        self.assertIn("--cachedir", export_command)
        self.assertIn("--library", export_command)
        self.assertIn(":memory:", export_command)
        self.assertIn("write_sidecar_files=never", export_command)

    def test_probe_fails_closed_when_executable_wrapper_is_broken(self) -> None:
        commands: list[list[str]] = []

        def fake_runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return subprocess.CompletedProcess(command, 127, "", "missing app bundle")

        report = darktable_probe.probe_darktable(
            executable="/opt/homebrew/bin/darktable-cli",
            runner=fake_runner,
        )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(len(commands), 1)
        self.assertEqual(report["stages"][0]["status"], "failed")
        self.assertIn("missing app bundle", report["failure_reason"])

    def test_version_only_probe_is_inconclusive_for_first_class_backend(self) -> None:
        def fake_runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 0, "this is darktable 5.4.1\n", "")

        report = darktable_probe.probe_darktable(executable="darktable-cli", runner=fake_runner)

        self.assertEqual(report["status"], "inconclusive")
        self.assertIn("RAW export was not exercised", report["failure_reason"])
        self.assertIsNone(report["source_unchanged"])

    def test_unparseable_version_fails_instead_of_promoting_unknown_installation(self) -> None:
        def fake_runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 0, "usage text only\n", "")

        report = darktable_probe.probe_darktable(executable="darktable-cli", runner=fake_runner)

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["stages"][0]["status"], "failed")
        self.assertEqual(report["failure_reason"], "darktable version was not parseable")

    def test_probe_detects_raw_or_sidecar_mutation_even_after_successful_export(self) -> None:
        call_count = 0

        def fake_runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return subprocess.CompletedProcess(command, 0, "darktable 5.4.1\n", "")
            raw = Path(command[1])
            raw.write_bytes(b"mutated raw")
            raw.with_name(raw.name + ".xmp").write_text("unexpected", encoding="utf-8")
            Path(command[2]).write_bytes(b"jpeg output")
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "IMG_0002.NEF"
            raw.write_bytes(b"original raw")
            report = darktable_probe.probe_darktable(
                raw=raw,
                output_dir=root / "probe-output",
                runner=fake_runner,
            )

        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["source_unchanged"])
        self.assertFalse(report["sidecars_unchanged"])
        self.assertIn("RAW source changed", report["failure_reason"])
        self.assertIn("sidecar state changed", report["failure_reason"])

    def test_probe_rejects_non_raw_input_before_export(self) -> None:
        commands: list[list[str]] = []

        def fake_runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, "darktable 5.4.1\n", "")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "notes.txt"
            source.write_text("not a raw", encoding="utf-8")
            report = darktable_probe.probe_darktable(
                raw=source,
                output_dir=root / "probe-output",
                runner=fake_runner,
            )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(len(commands), 1)
        self.assertEqual(report["stages"][-1]["name"], "preflight")
        self.assertEqual(report["failure_reason"], "Unsupported RAW extension")

    def test_probe_report_schema_is_strict_and_versioned(self) -> None:
        schema = json.loads(
            (ROOT / "knowledge" / "schemas" / "darktable_probe.schema.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            schema["properties"]["schema_version"]["const"],
            "lumenflow.darktable_probe.v1",
        )
        self.assertIs(schema["additionalProperties"], False)
        self.assertIs(schema["$defs"]["stage"]["additionalProperties"], False)


if __name__ == "__main__":
    unittest.main()
