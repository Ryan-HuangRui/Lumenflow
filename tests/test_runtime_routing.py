from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from mcp.client import Client

from lumenflow.mcp.runtime import LumenflowRuntime


class RuntimeRoutingTests(unittest.TestCase):
    @staticmethod
    def _intent(raw: Path) -> dict:
        return {
            "schema_version": "lumenflow.edit_intent.v2",
            "intent_id": "intent-routing-001",
            "revision": 1,
            "authorization": {
                "kind": "user_confirmed_selection",
                "reference_id": "approval-routing-001",
            },
            "source": {
                "path": str(raw),
                "fingerprint": {
                    "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                    "size_bytes": raw.stat().st_size,
                },
            },
            "preview_basis": {
                "artifact_id": "preview_" + "a" * 32,
                "starting_state_hash": "b" * 64,
                "state_completeness": "complete",
            },
            "purpose": "Bangkok travel story",
            "style": {"style_id": "clean_natural", "rationale": "Natural color."},
            "global_adjustments": {
                "exposure_ev": 0.2,
                "contrast": 5,
                "highlight_recovery": 10,
                "shadow_lift": 8,
                "black_point": 120,
                "saturation": 0,
                "temperature_k": 5200,
                "green_multiplier": 1.0,
            },
            "composition": {"decision": "no_crop", "reason": "Keep framing."},
            "local_adjustments": {
                "decision": "none",
                "reason": "Global edits are sufficient.",
                "masks": [],
            },
        }

    def test_no_allowed_roots_defaults_to_lite_and_blocks_photo_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.dng"
            raw.write_bytes(b"raw")
            runtime = LumenflowRuntime(
                local_config={"tools": {"rawtherapee_cli": sys.executable}}
            )

            status = runtime.status()["result"]
            result = runtime.compile_edit(
                intent=self._intent(raw),
                backend_id="rawtherapee",
                output_dir=str(root / "output"),
            )

            self.assertEqual(status["mode"], "lite")
            self.assertFalse(status["path_policy"]["configured"])
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], "ALLOWED_ROOTS_REQUIRED")

    def test_configured_roots_and_available_engine_enable_full_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "source"
            output_root = root / "output"
            source_root.mkdir()
            output_root.mkdir()
            raw = source_root / "bangkok.dng"
            raw.write_bytes(b"raw")
            runtime = LumenflowRuntime(
                local_config={
                    "security": {
                        "allowed_source_roots": [str(source_root)],
                        "allowed_output_roots": [str(output_root)],
                    },
                    "tools": {"rawtherapee_cli": sys.executable},
                }
            )

            status = runtime.status()["result"]
            result = runtime.compile_edit(
                intent=self._intent(raw),
                backend_id="rawtherapee",
                output_dir=str(output_root / "edit"),
            )

            self.assertEqual(status["mode"], "full")
            self.assertTrue(status["path_policy"]["configured"])
            self.assertTrue(result["ok"], result)

    def test_source_outside_allowlist_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowed = root / "allowed"
            output = root / "output"
            outside = root / "outside"
            allowed.mkdir()
            output.mkdir()
            outside.mkdir()
            raw = outside / "bangkok.dng"
            raw.write_bytes(b"raw")
            runtime = LumenflowRuntime(
                local_config={
                    "security": {
                        "allowed_source_roots": [str(allowed)],
                        "allowed_output_roots": [str(output)],
                    },
                    "tools": {"rawtherapee_cli": sys.executable},
                }
            )

            result = runtime.compile_edit(
                intent=self._intent(raw),
                backend_id="rawtherapee",
                output_dir=str(output / "edit"),
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], "PATH_NOT_ALLOWED")

    @unittest.skipIf(os.name == "nt", "symlink semantics differ on Windows")
    def test_symlink_escape_is_rejected_after_realpath_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowed = root / "allowed"
            output = root / "output"
            outside = root / "outside"
            allowed.mkdir()
            output.mkdir()
            outside.mkdir()
            raw = outside / "bangkok.dng"
            raw.write_bytes(b"raw")
            link = allowed / "linked.dng"
            link.symlink_to(raw)
            runtime = LumenflowRuntime(
                local_config={
                    "security": {
                        "allowed_source_roots": [str(allowed)],
                        "allowed_output_roots": [str(output)],
                    },
                    "tools": {"rawtherapee_cli": sys.executable},
                }
            )

            result = runtime.compile_edit(
                intent=self._intent(link),
                backend_id="rawtherapee",
                output_dir=str(output / "edit"),
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], "PATH_NOT_ALLOWED")

    def test_environment_roots_are_supported_for_plugin_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            output = root / "output"
            source.mkdir()
            output.mkdir()
            runtime = LumenflowRuntime(
                local_config={"tools": {"rawtherapee_cli": sys.executable}},
                environment={
                    "LUMENFLOW_ALLOWED_SOURCE_ROOTS": str(source),
                    "LUMENFLOW_ALLOWED_OUTPUT_ROOTS": str(output),
                },
            )

            status = runtime.status()["result"]

            self.assertEqual(status["mode"], "full")
            self.assertEqual(
                status["path_policy"]["source_roots"], [str(source.resolve())]
            )
            self.assertEqual(
                status["path_policy"]["output_roots"], [str(output.resolve())]
            )

    def test_finalize_rejects_manifest_paths_outside_allowed_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            output = root / "output"
            outside = root / "outside"
            source.mkdir()
            output.mkdir()
            outside.mkdir()
            raw = source / "bangkok.dng"
            raw.write_bytes(b"raw")
            preview = outside / "preview.jpg"
            preview.write_bytes(b"jpeg")
            manifest = output / "candidate_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "asset_id": "bangkok.dng",
                                "source": str(raw),
                                "preview": str(preview),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            plan = output / "selection_plan.json"
            plan.write_text("{}", encoding="utf-8")
            runtime = LumenflowRuntime(
                local_config={
                    "security": {
                        "allowed_source_roots": [str(source)],
                        "allowed_output_roots": [str(output)],
                    }
                }
            )

            result = runtime.finalize_curation(
                manifest_path=str(manifest),
                plan_path=str(plan),
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], "PATH_NOT_ALLOWED")

    def test_server_loads_plugin_data_config_from_environment(self) -> None:
        from lumenflow.mcp.server import create_server

        async def scenario(root: Path) -> None:
            source = root / "source"
            output = root / "output"
            data = root / "plugin-data"
            source.mkdir()
            output.mkdir()
            data.mkdir()
            config = data / "lumenflow.local.json"
            config.write_text(
                json.dumps(
                    {
                        "security": {
                            "allowed_source_roots": [str(source)],
                            "allowed_output_roots": [str(output)],
                        },
                        "tools": {"rawtherapee_cli": sys.executable},
                    }
                ),
                encoding="utf-8",
            )
            environment = {
                "LUMENFLOW_CONFIG": str(config),
                "LUMENFLOW_DATA_ROOT": str(data),
                "LUMENFLOW_WORKSPACE_ROOT": str(root),
            }
            async with Client(create_server(environment=environment)) as client:
                response = await client.call_tool("lumenflow.status", {})

            self.assertTrue(response.structured_content["ok"])
            status = response.structured_content["result"]
            self.assertEqual(status["mode"], "full")
            self.assertEqual(
                status["path_policy"]["source_roots"], [str(source.resolve())]
            )

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))


if __name__ == "__main__":
    unittest.main()
