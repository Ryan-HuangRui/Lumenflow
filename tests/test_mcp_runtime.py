from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import StdioServerParameters
from mcp.client import Client


ROOT = Path(__file__).resolve().parents[1]


class McpRuntimeTests(unittest.TestCase):
    def _intent(self, raw: Path) -> dict:
        fingerprint = {
            "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
            "size_bytes": raw.stat().st_size,
        }
        return {
            "schema_version": "lumenflow.edit_intent.v2",
            "intent_id": "intent-mcp-001",
            "revision": 1,
            "authorization": {
                "kind": "user_confirmed_selection",
                "reference_id": "approval-mcp-001",
            },
            "source": {"path": str(raw), "fingerprint": fingerprint},
            "preview_basis": {
                "artifact_id": "preview_" + "a" * 32,
                "starting_state_hash": "b" * 64,
                "state_completeness": "complete",
            },
            "purpose": "Bangkok travel story",
            "style": {
                "style_id": "street_light_shadow_cinematic",
                "rationale": "Preserve the humid night atmosphere.",
            },
            "global_adjustments": {
                "exposure_ev": 0.25,
                "contrast": 8,
                "highlight_recovery": 20,
                "shadow_lift": 12,
                "black_point": 180,
                "saturation": -3,
                "temperature_k": 5150,
                "green_multiplier": 1.01,
            },
            "composition": {
                "decision": "no_crop",
                "reason": "The approved framing already supports the story.",
            },
            "local_adjustments": {
                "decision": "none",
                "reason": "Global controls are sufficient.",
                "masks": [],
            },
        }

    def test_server_preserves_the_six_raw_vertical_slice_tools(self) -> None:
        from lumenflow.mcp.server import create_server

        async def scenario() -> None:
            async with Client(create_server()) as client:
                response = await client.list_tools()
                tools = {tool.name: tool for tool in response.tools}
                self.assertTrue(
                    {
                        "lumenflow.status",
                        "lumenflow.create_previews",
                        "lumenflow.compile_edit",
                        "lumenflow.execute_edit",
                        "lumenflow.start_review",
                        "lumenflow.advance_review",
                    }.issubset(tools),
                )
                self.assertEqual(
                    tools["lumenflow.compile_edit"].input_schema["required"],
                    ["intent", "backend_id", "output_dir"],
                )
                self.assertFalse(
                    tools["lumenflow.status"].annotations.destructive_hint
                )
                self.assertFalse(
                    tools["lumenflow.execute_edit"].annotations.destructive_hint
                )

        asyncio.run(scenario())

    def test_compile_and_dry_run_execute_preserve_contracts_and_source(self) -> None:
        from lumenflow.mcp.server import create_server

        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                raw = root / "bangkok.DNG"
                output_dir = root / "output"
                raw.write_bytes(b"bangkok-raw")
                source_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
                intent = self._intent(raw)
                runtime_config = {
                    "security": {
                        "allowed_source_roots": [str(root)],
                        "allowed_output_roots": [str(root)],
                    },
                    "tools": {"rawtherapee_cli": sys.executable},
                }

                async with Client(create_server(local_config=runtime_config)) as client:
                    compiled = await client.call_tool(
                        "lumenflow.compile_edit",
                        {
                            "intent": intent,
                            "backend_id": "rawtherapee",
                            "output_dir": str(output_dir),
                        },
                    )
                    self.assertFalse(compiled.is_error, compiled.content)
                    self.assertTrue(compiled.structured_content["ok"])
                    plan = compiled.structured_content["result"]
                    self.assertEqual(
                        plan["schema_version"], "lumenflow.execution_plan.v1"
                    )

                    executed = await client.call_tool(
                        "lumenflow.execute_edit",
                        {
                            "plan": plan,
                            "allowed_output_dir": str(output_dir),
                            "dry_run": True,
                        },
                    )
                    self.assertFalse(executed.is_error, executed.content)
                    receipt = executed.structured_content["result"]
                    self.assertEqual(receipt["status"], "dry_run")
                    self.assertTrue(receipt["source_unchanged"])
                    self.assertEqual(
                        hashlib.sha256(raw.read_bytes()).hexdigest(), source_hash
                    )
                    self.assertFalse(output_dir.exists())

        asyncio.run(scenario())

    def test_execute_rejects_tampered_plan_with_stable_error_code(self) -> None:
        from lumenflow.mcp.server import create_server

        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                raw = root / "bangkok.DNG"
                output_dir = root / "output"
                raw.write_bytes(b"bangkok-raw")
                runtime_config = {
                    "security": {
                        "allowed_source_roots": [str(root)],
                        "allowed_output_roots": [str(root)],
                    },
                    "tools": {"rawtherapee_cli": sys.executable},
                }

                async with Client(create_server(local_config=runtime_config)) as client:
                    compiled = await client.call_tool(
                        "lumenflow.compile_edit",
                        {
                            "intent": self._intent(raw),
                            "backend_id": "rawtherapee",
                            "output_dir": str(output_dir),
                        },
                    )
                    plan = compiled.structured_content["result"]
                    plan["operations"][1]["command_argv"][0] = "/tmp/evil"
                    executed = await client.call_tool(
                        "lumenflow.execute_edit",
                        {
                            "plan": plan,
                            "allowed_output_dir": str(output_dir),
                            "dry_run": True,
                        },
                    )

                self.assertFalse(executed.is_error, executed.content)
                self.assertFalse(executed.structured_content["ok"])
                self.assertEqual(
                    executed.structured_content["error"]["code"],
                    "PLAN_COMMAND_MISMATCH",
                )
                self.assertFalse(output_dir.exists())

        asyncio.run(scenario())

    def test_relative_paths_fail_closed_before_core_execution(self) -> None:
        from lumenflow.mcp.server import create_server

        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config = {
                    "security": {
                        "allowed_source_roots": [str(root)],
                        "allowed_output_roots": [str(root)],
                    },
                    "tools": {"rawtherapee_cli": sys.executable},
                }
                async with Client(create_server(local_config=config)) as client:
                    result = await client.call_tool(
                        "lumenflow.create_previews",
                        {
                            "backend_id": "rawtherapee",
                            "source_paths": ["relative.DNG"],
                            "output_dir": "relative-output",
                            "dry_run": True,
                        },
                    )
            self.assertFalse(result.structured_content["ok"])
            self.assertEqual(
                result.structured_content["error"]["code"], "ABSOLUTE_PATH_REQUIRED"
            )

        asyncio.run(scenario())

    def test_real_stdio_server_handshake_and_status_call(self) -> None:
        async def scenario() -> None:
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(ROOT / "src")
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "lumenflow.mcp.server"],
                cwd=ROOT,
                env=environment,
            )
            async with Client(parameters, read_timeout_seconds=10) as client:
                tools = await client.list_tools()
                status = await client.call_tool("lumenflow.status", {})
            self.assertIn("lumenflow.status", {tool.name for tool in tools.tools})
            self.assertFalse(status.is_error, status.content)
            self.assertTrue(status.structured_content["ok"])
            self.assertEqual(
                status.structured_content["result"]["protocol"], "stdio"
            )

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
