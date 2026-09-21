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
    def test_darktable_preview_binds_explicit_xmp_and_isolates_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "keeper.DNG"
            xmp = root / "keeper.DNG.xmp"
            output = root / "previews" / "keeper.jpg"
            raw.write_bytes(b"raw-v1")
            xmp.write_text("<x:xmpmeta>develop-v1</x:xmpmeta>", encoding="utf-8")

            provider = preview_provider.DarktablePreviewProvider(
                local_config={"tools": {"darktable_cli": "/custom/darktable-cli"}}
            )
            artifact = provider.create_preview(
                preview_provider.PreviewRequest(
                    source=raw,
                    output=output,
                    base_profile=xmp,
                    dry_run=True,
                    timeout=10,
                    selection_reason="rating>=3",
                )
            ).to_dict()

            self.assertEqual(artifact["provider"]["id"], "darktable")
            self.assertEqual(artifact["state_completeness"], "complete")
            self.assertEqual(artifact["starting_state"]["kind"], "darktable_xmp")
            self.assertEqual(artifact["starting_state"]["xmp"]["sha256"], hashlib.sha256(xmp.read_bytes()).hexdigest())
            self.assertEqual(artifact["state_inputs"][0]["role"], "base_profile")
            self.assertEqual(artifact["state_inputs"][0]["path"], str(xmp))
            self.assertEqual(artifact["command_argv"][:4], ["/custom/darktable-cli", str(raw), str(xmp), str(output)])
            self.assertIn("--configdir", artifact["command_argv"])
            self.assertIn("--cachedir", artifact["command_argv"])
            self.assertIn(":memory:", artifact["command_argv"])
            self.assertIn("write_sidecar_files=never", artifact["command_argv"])
            self.assertFalse(output.parent.exists())

    def test_darktable_preview_fails_if_source_sidecar_changes_during_render(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "keeper.DNG"
            xmp = root / "keeper.DNG.xmp"
            output = root / "previews" / "keeper.jpg"
            raw.write_bytes(b"raw-v1")
            xmp.write_text("develop-v1", encoding="utf-8")

            def fake_runner(command: list[str], *, dry_run: bool, timeout: int | None) -> int:
                del command, dry_run, timeout
                xmp.write_text("develop-v2", encoding="utf-8")
                output.write_bytes(b"jpeg-result")
                return 0

            artifact = preview_provider.DarktablePreviewProvider(runner=fake_runner).create_preview(
                preview_provider.PreviewRequest(
                    source=raw,
                    output=output,
                    base_profile=xmp,
                    dry_run=False,
                    timeout=10,
                )
            )

            self.assertEqual(artifact.status, "failed")
            self.assertIn("state changed", artifact.failure_reason)
            self.assertIsNone(artifact.preview_fingerprint)

    def test_darktable_preview_refuses_to_overwrite_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "keeper.DNG"
            output = root / "keeper.jpg"
            raw.write_bytes(b"raw")
            output.write_bytes(b"existing")
            calls: list[list[str]] = []

            def fake_runner(command: list[str], *, dry_run: bool, timeout: int | None) -> int:
                del dry_run, timeout
                calls.append(command)
                return 0

            artifact = preview_provider.DarktablePreviewProvider(runner=fake_runner).create_preview(
                preview_provider.PreviewRequest(
                    source=raw,
                    output=output,
                    base_profile=None,
                    dry_run=False,
                    timeout=10,
                )
            )

            self.assertEqual(artifact.status, "failed")
            self.assertIn("overwrite", artifact.failure_reason.lower())
            self.assertEqual(output.read_bytes(), b"existing")
            self.assertEqual(calls, [])

    def test_darktable_factory_returns_the_live_verified_provider(self) -> None:
        provider = preview_provider.create_preview_provider("darktable")

        self.assertIsInstance(provider, preview_provider.DarktablePreviewProvider)

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

            basis = preview_provider.preview_basis_from_artifact(artifact)
            self.assertEqual(basis["artifact_id"], artifact["artifact_id"])
            self.assertEqual(
                [item["role"] for item in basis["state_inputs"]],
                ["base_profile", "source_sidecar"],
            )

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

    def test_rawtherapee_base_profile_alone_is_a_complete_explicit_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "keeper.DNG"
            base = root / "base.pp3"
            raw.write_bytes(b"raw")
            base.write_text("[Version]\nVersion=349\n", encoding="utf-8")

            artifact = preview_provider.RawTherapeePreviewProvider().create_preview(
                preview_provider.PreviewRequest(raw, root / "preview.jpg", base, True, 10)
            )

            self.assertEqual(artifact.state_completeness, "complete")
            self.assertEqual([item["role"] for item in artifact.state_inputs], ["base_profile"])

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
