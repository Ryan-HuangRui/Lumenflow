from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

from mcp.client import Client


ROOT = Path(__file__).resolve().parents[1]


class PluginWorkflowToolTests(unittest.TestCase):
    def test_mcp_surface_contains_all_eleven_workflow_tools(self) -> None:
        from lumenflow.mcp.server import create_server

        async def scenario() -> None:
            async with Client(create_server(workspace_root=ROOT)) as client:
                response = await client.list_tools()
            self.assertEqual(
                {tool.name for tool in response.tools},
                {
                    "lumenflow.status",
                    "lumenflow.prepare_curation",
                    "lumenflow.finalize_curation",
                    "lumenflow.create_previews",
                    "lumenflow.search_styles",
                    "lumenflow.search_examples",
                    "lumenflow.store_example",
                    "lumenflow.compile_edit",
                    "lumenflow.execute_edit",
                    "lumenflow.start_review",
                    "lumenflow.advance_review",
                },
            )

        asyncio.run(scenario())

    def test_resource_templates_are_stable_and_style_resource_is_readable(self) -> None:
        from lumenflow.mcp.server import create_server

        async def scenario() -> None:
            async with Client(create_server(workspace_root=ROOT)) as client:
                templates = await client.list_resource_templates()
                style = await client.read_resource("lumenflow://styles/clean_natural")
            self.assertEqual(
                {str(item.uri_template) for item in templates.resource_templates},
                {
                    "lumenflow://styles/{style_id}",
                    "lumenflow://workspaces/{workspace_id}",
                    "lumenflow://previews/{artifact_id}",
                    "lumenflow://receipts/{receipt_id}",
                    "lumenflow://reviews/{session_id}",
                    "lumenflow://backends/{backend_id}",
                },
            )
            payload = json.loads(style.contents[0].text)
            self.assertEqual(payload["style_id"], "clean_natural")

        asyncio.run(scenario())

    def test_search_styles_returns_ranked_resource_references(self) -> None:
        from lumenflow.mcp.server import create_server

        async def scenario() -> None:
            async with Client(create_server(workspace_root=ROOT)) as client:
                response = await client.call_tool(
                    "lumenflow.search_styles",
                    {
                        "query": "natural travel true color",
                        "purpose": "Bangkok travel story",
                        "limit": 3,
                    },
                )
            self.assertFalse(response.is_error, response.content)
            self.assertTrue(response.structured_content["ok"])
            matches = response.structured_content["result"]
            self.assertGreaterEqual(len(matches), 1)
            self.assertTrue(matches[0]["resource_uri"].startswith("lumenflow://styles/"))
            self.assertIn("style_id", matches[0])
            self.assertNotIn("raw_profiles", matches[0])

        asyncio.run(scenario())

    def test_bundled_style_fallback_works_without_checkout_knowledge(self) -> None:
        from lumenflow.mcp.server import create_server

        async def scenario(workspace: Path) -> None:
            async with Client(create_server(workspace_root=workspace)) as client:
                style = await client.read_resource("lumenflow://styles/clean_natural")
            payload = json.loads(style.contents[0].text)
            self.assertEqual(payload["style_id"], "clean_natural")

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_example_search_validates_query_without_creating_an_empty_store(self) -> None:
        from lumenflow.mcp.server import create_server

        async def scenario(workspace: Path) -> None:
            async with Client(create_server(workspace_root=workspace)) as client:
                response = await client.call_tool("lumenflow.search_examples", {})
            self.assertFalse(response.structured_content["ok"])
            self.assertEqual(
                response.structured_content["error"]["code"], "INVALID_QUERY"
            )
            self.assertFalse((workspace / "local" / "personal_edit_examples.sqlite3").exists())

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(scenario(Path(directory)))

    def test_style_library_rejects_duplicate_ids_and_path_traversal_is_not_used(self) -> None:
        from lumenflow.style_library import StyleLibrary, StyleLibraryError

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "a.json"
            second = root / "nested" / "b.json"
            second.parent.mkdir()
            payload = {
                "style_id": "safe_style",
                "style_name": "Safe Style",
                "intent": "Natural color",
            }
            first.write_text(json.dumps(payload), encoding="utf-8")
            second.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(StyleLibraryError):
                StyleLibrary([root])

            second.unlink()
            library = StyleLibrary([root])
            with self.assertRaises(StyleLibraryError):
                library.get("../../etc/passwd")

    def test_personal_example_legacy_module_is_a_package_wrapper(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import personal_example_store as legacy
            from lumenflow.memory import personal_examples
        finally:
            sys.path.pop(0)
        self.assertIs(legacy.PersonalExampleStore, personal_examples.PersonalExampleStore)
        self.assertIs(legacy.build_personal_example, personal_examples.build_personal_example)


if __name__ == "__main__":
    unittest.main()
