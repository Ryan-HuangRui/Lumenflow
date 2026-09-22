from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORTABLE_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
LAUNCHER = "./scripts/launch_lumenflow_mcp"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PluginManifestTests(unittest.TestCase):
    def test_root_plugin_manifest_uses_closed_portable_shape(self) -> None:
        manifest = read_json(ROOT / "plugin.json")

        self.assertEqual(
            set(manifest),
            {
                "$schema",
                "name",
                "version",
                "description",
                "author",
                "homepage",
                "repository",
                "license",
                "keywords",
                "extensions",
            },
        )
        self.assertEqual(manifest["$schema"], PORTABLE_SCHEMA)
        self.assertEqual(manifest["name"], "lumenflow")

        openai = manifest["extensions"]["com.openai"]
        interface = openai["interface"]
        self.assertTrue(interface["websiteURL"].startswith("https://"))
        self.assertIn("defaultPrompt", interface)
        self.assertNotIn("privacyPolicyURL", interface)
        self.assertNotIn("termsOfServiceURL", interface)

    def test_portable_mcp_manifest_is_single_launcher_stdio_server(self) -> None:
        manifest = read_json(ROOT / "mcp.json")

        self.assertEqual(set(manifest), {"$schema", "mcpServers"})
        self.assertEqual(manifest["$schema"], MCP_SCHEMA)
        server = manifest["mcpServers"]["lumenflow"]
        self.assertEqual(server["type"], "stdio")
        self.assertEqual(server["command"], LAUNCHER)
        self.assertEqual(server["command"].split(), [LAUNCHER])
        self.assertEqual(server["cwd"], "${PLUGIN_ROOT}")
        self.assertEqual(
            server["env"],
            {
                "LUMENFLOW_CONFIG": "${PLUGIN_DATA}/lumenflow.local.json",
                "LUMENFLOW_DATA_ROOT": "${PLUGIN_DATA}",
            },
        )

    def test_codex_compat_manifest_and_mcp_overlay_point_to_same_components(self) -> None:
        manifest = read_json(ROOT / ".codex-plugin" / "plugin.json")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")

        compat_mcp = read_json(ROOT / ".mcp.json")
        server = compat_mcp["mcpServers"]["lumenflow"]
        self.assertEqual(server["command"], LAUNCHER)
        self.assertEqual(server["cwd"], "${PLUGIN_ROOT}")
        self.assertEqual(
            server["env"],
            {
                "LUMENFLOW_CONFIG": "${PLUGIN_DATA}/lumenflow.local.json",
                "LUMENFLOW_DATA_ROOT": "${PLUGIN_DATA}",
            },
        )

    def test_launcher_is_executable_and_bootstraps_checkout_src(self) -> None:
        launcher = ROOT / "scripts" / "launch_lumenflow_mcp"
        self.assertTrue(launcher.is_file())
        self.assertTrue(launcher.stat().st_mode & stat.S_IXUSR)
        source = launcher.read_text(encoding="utf-8")
        self.assertIn("PLUGIN_DATA", source)
        self.assertIn("PLUGIN_ROOT", source)
        self.assertIn("PYTHONPATH", source)
        self.assertIn("python3", source)
        self.assertIn("exec", source)
        self.assertIn("install", source.lower())

    def test_compat_validator_accepts_local_manifest(self) -> None:
        validator = (
            Path.home()
            / ".codex"
            / "skills"
            / ".system"
            / "plugin-creator"
            / "scripts"
            / "validate_plugin.py"
        )
        if not validator.is_file():
            self.skipTest("local Codex plugin validator is unavailable")
        validator_python = sys.executable
        try:
            import yaml  # noqa: F401
        except ModuleNotFoundError:
            fallback_python = shutil.which("python3")
            if fallback_python is None:
                self.skipTest("local Codex plugin validator dependencies are unavailable")
            probe = subprocess.run(
                [fallback_python, "-c", "import yaml"],
                check=False,
                capture_output=True,
            )
            if probe.returncode != 0:
                self.skipTest("local Codex plugin validator dependencies are unavailable")
            validator_python = fallback_python
        result = subprocess.run(
            [os.fspath(Path(validator_python)), os.fspath(validator), os.fspath(ROOT)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
