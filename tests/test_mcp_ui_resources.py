from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp.client import Client


UI_MIME = "text/html;profile=mcp-app"
STATUS_UI = "ui://lumenflow/runtime-status/v1.html"
CURATION_UI = "ui://lumenflow/curation/v1.html"
REVIEW_UI = "ui://lumenflow/review/v1.html"


class McpUiResourceTests(unittest.TestCase):
    def test_selected_tools_link_versioned_ui_resources_without_growing_surface(self) -> None:
        from lumenflow.mcp.server import create_server

        async def scenario() -> None:
            async with Client(create_server()) as client:
                response = await client.list_tools()

            tools = {tool.name: tool for tool in response.tools}
            self.assertEqual(len(tools), 11)
            expected = {
                "lumenflow.status": STATUS_UI,
                "lumenflow.prepare_curation": CURATION_UI,
                "lumenflow.finalize_curation": CURATION_UI,
                "lumenflow.start_review": REVIEW_UI,
                "lumenflow.advance_review": REVIEW_UI,
            }
            for name, uri in expected.items():
                self.assertEqual(tools[name].meta["ui"]["resourceUri"], uri)
                self.assertEqual(tools[name].meta["openai/outputTemplate"], uri)
            self.assertIsNone(tools["lumenflow.compile_edit"].meta)
            self.assertIsNone(tools["lumenflow.execute_edit"].meta)

        asyncio.run(scenario())

    def test_review_transition_exposes_verified_evidence_for_ui(self) -> None:
        from lumenflow.mcp.runtime import LumenflowRuntime

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "source"
            output_root = root / "output"
            source_root.mkdir()
            output_root.mkdir()
            raw = source_root / "bangkok.dng"
            raw.write_bytes(b"raw")
            profile = output_root / "profiles" / "bangkok.pp3"
            rendered = output_root / "bangkok.jpg"
            runtime = LumenflowRuntime(
                local_config={
                    "security": {
                        "allowed_source_roots": [str(source_root)],
                        "allowed_output_roots": [str(output_root)],
                    }
                }
            )
            plan = {
                "plan_id": "plan_" + "a" * 32,
                "source": {"path": str(raw)},
                "output_root": str(output_root),
                "artifacts": {
                    "profile": {"path": str(profile)},
                    "output": {"path": str(rendered)},
                },
            }
            receipt = {
                "receipt_id": "receipt_" + "b" * 32,
                "source_unchanged": True,
                "output_fingerprint": {"sha256": "c" * 64, "size_bytes": 10},
            }
            updated_session = {"session_id": "review_session_" + "d" * 32}

            with patch(
                "lumenflow.mcp.runtime.review.advance_review_session",
                return_value={"session": updated_session, "next_intent": None},
            ):
                result = runtime.advance_review(
                    session={},
                    plan=plan,
                    receipt=receipt,
                    review_result={"decision": "accept"},
                )

            self.assertTrue(result["ok"])
            self.assertEqual(
                result["result"]["evidence"],
                {
                    "decision": "accept",
                    "plan_id": plan["plan_id"],
                    "receipt_id": receipt["receipt_id"],
                    "source_unchanged": True,
                    "output_fingerprint": receipt["output_fingerprint"],
                },
            )

    def test_ui_resources_are_self_contained_mcp_apps_documents(self) -> None:
        from lumenflow.mcp.server import create_server

        async def scenario() -> None:
            async with Client(create_server()) as client:
                listed = await client.list_resources()
                payloads = {
                    uri: await client.read_resource(uri)
                    for uri in (STATUS_UI, CURATION_UI, REVIEW_UI)
                }

            self.assertEqual(
                {str(resource.uri) for resource in listed.resources},
                {STATUS_UI, CURATION_UI, REVIEW_UI},
            )
            for uri, response in payloads.items():
                content = response.contents[0]
                self.assertEqual(str(content.uri), uri)
                self.assertEqual(content.mime_type, UI_MIME)
                self.assertIn("ui/notifications/tool-result", content.text)
                self.assertIn("ui/initialize", content.text)
                self.assertEqual(
                    content.meta,
                    {
                        "ui": {
                            "prefersBorder": True,
                            "csp": {
                                "connectDomains": [],
                                "resourceDomains": [],
                                "frameDomains": [],
                            },
                        }
                    },
                )

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
