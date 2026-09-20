from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import preview_provider  # noqa: E402


class PreviewProviderTests(unittest.TestCase):
    def test_rawtherapee_artifact_binds_source_and_starting_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "keeper.DNG"
            base = root / "base.pp3"
            sidecar = root / "keeper.DNG.pp3"
            output = root / "keeper_preview.jpg"
            raw.write_bytes(b"raw-v1")
            base.write_text("[Version]\nVersion=349\n", encoding="utf-8")
            sidecar.write_text("[Exposure]\nCompensation=0.25\n", encoding="utf-8")

            provider = preview_provider.RawTherapeePreviewProvider(
                local_config={"tools": {"rawtherapee_cli": "/custom/rawtherapee-cli"}}
            )
            artifact = provider.create_preview(
                preview_provider.PreviewRequest(
                    source=raw,
                    output=output,
                    base_profile=base,
                    dry_run=True,
                    timeout=10,
                    selection_reason="rating>=3",
                )
            ).to_dict()

            self.assertEqual(artifact["schema_version"], "lumenflow.preview_artifact.v1")
            self.assertEqual(artifact["provider"]["id"], "rawtherapee")
            self.assertEqual(
                artifact["provider"]["capability_contract_version"],
                "lumenflow.backend_capabilities.v1",
            )
            self.assertEqual(artifact["source_fingerprint"]["sha256"], hashlib.sha256(b"raw-v1").hexdigest())
            self.assertEqual(
                [item["role"] for item in artifact["starting_state"]["profile_stack"]],
                ["base_profile", "source_sidecar"],
            )
            self.assertNotIn("path", artifact["starting_state"]["profile_stack"][0])
            self.assertEqual(
                [item["path"] for item in artifact["state_inputs"]],
                [str(base), str(sidecar)],
            )
            self.assertEqual(
                artifact["starting_state_hash"],
                preview_provider.canonical_hash(artifact["starting_state"]),
            )
            self.assertEqual(artifact["state_completeness"], "complete")
            self.assertEqual(artifact["status"], "dry_run")
            self.assertIsNone(artifact["preview_fingerprint"])
            self.assertEqual(artifact["command_argv"][0], "/custom/rawtherapee-cli")
            self.assertIn(str(base), artifact["command_argv"])
            self.assertIn(str(sidecar), artifact["command_argv"])
            self.assertEqual(artifact["source"], str(raw))
            self.assertEqual(artifact["preview"], str(output))

    def test_starting_state_hash_changes_when_sidecar_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "keeper.DNG"
            sidecar = root / "keeper.DNG.pp3"
            raw.write_bytes(b"raw")
            sidecar.write_text("[Exposure]\nCompensation=0.25\n", encoding="utf-8")
            provider = preview_provider.RawTherapeePreviewProvider()
            request = preview_provider.PreviewRequest(
                source=raw,
                output=root / "preview.jpg",
                base_profile=None,
                dry_run=True,
                timeout=10,
            )

            first = provider.create_preview(request)
            sidecar.write_text("[Exposure]\nCompensation=0.75\n", encoding="utf-8")
            second = provider.create_preview(request)

            self.assertNotEqual(first.starting_state_hash, second.starting_state_hash)
            self.assertNotEqual(first.artifact_id, second.artifact_id)

    def test_successful_preview_records_output_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "keeper.DNG"
            output = root / "preview.jpg"
            raw.write_bytes(b"raw")

            def fake_runner(command: list[str], *, dry_run: bool, timeout: int | None) -> int:
                self.assertFalse(dry_run)
                self.assertEqual(timeout, 10)
                output.write_bytes(b"jpeg-result")
                return 0

            artifact = preview_provider.RawTherapeePreviewProvider(runner=fake_runner).create_preview(
                preview_provider.PreviewRequest(
                    source=raw,
                    output=output,
                    base_profile=None,
                    dry_run=False,
                    timeout=10,
                )
            )

            self.assertEqual(artifact.status, "success")
            self.assertEqual(
                artifact.preview_fingerprint,
                {
                    "sha256": hashlib.sha256(b"jpeg-result").hexdigest(),
                    "size_bytes": len(b"jpeg-result"),
                },
            )
            self.assertEqual(artifact.state_completeness, "partial")

    def test_lightroom_provider_fails_closed_without_verified_preview_capabilities(self) -> None:
        calls: list[list[str]] = []

        def fake_status_runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "connected": True,
                        "bridge_contract": {
                            "protocol_version": "2",
                            "version_match": True,
                            "capabilities": {
                                "safe_object_develop_read": False,
                                "verified_state_bound_preview": False,
                            },
                        },
                    }
                ),
                stderr="",
            )

        provider = preview_provider.LightroomPreviewProvider(status_runner=fake_status_runner)
        with self.assertRaises(preview_provider.PreviewCapabilityError) as error:
            provider.create_preview(
                preview_provider.PreviewRequest(
                    source=Path("/photos/keeper.DNG"),
                    output=Path("/previews/keeper.jpg"),
                    base_profile=None,
                    dry_run=True,
                    timeout=10,
                )
            )

        self.assertIn("safe_object_develop_read", str(error.exception))
        self.assertIn("verified_state_bound_preview", str(error.exception))
        self.assertEqual(calls, [["lr", "-o", "json", "system", "status"]])

    def test_preview_artifact_schema_is_strict_and_versioned(self) -> None:
        schema = json.loads(
            (ROOT / "knowledge" / "schemas" / "preview_artifact.schema.json").read_text(encoding="utf-8")
        )

        self.assertEqual(schema["properties"]["schema_version"]["const"], "lumenflow.preview_artifact.v1")
        self.assertIs(schema["additionalProperties"], False)
        self.assertIn("starting_state_hash", schema["required"])
        self.assertIn("source_fingerprint", schema["required"])


if __name__ == "__main__":
    unittest.main()
