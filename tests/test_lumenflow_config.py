from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import lumenflow_config


class LumenflowConfigTests(unittest.TestCase):
    def test_read_local_config_requires_json_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local.json"
            path.write_text(json.dumps({"tools": {"ffmpeg": "ffmpeg"}}), encoding="utf-8")

            self.assertEqual(
                lumenflow_config.read_local_config(path),
                {"tools": {"ffmpeg": "ffmpeg"}},
            )

    def test_config_path_expands_home_and_env(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            os.environ["LUMENFLOW_TEST_ROOT"] = directory
            config = {"bilibili": {"cookie_file": "$LUMENFLOW_TEST_ROOT/cookie.txt"}}

            self.assertEqual(
                lumenflow_config.config_path(config, "bilibili", "cookie_file"),
                Path(directory) / "cookie.txt",
            )

    def test_tool_command_falls_back_when_unconfigured(self) -> None:
        self.assertEqual(
            lumenflow_config.tool_command({}, "rawtherapee_cli", "rawtherapee-cli"),
            "rawtherapee-cli",
        )

    def test_photo_output_dir_uses_source_parent_directory_name(self) -> None:
        config = {"photos": {"output_root": "/photo-output-root"}}
        raw = Path("/photo-source/negative_raw/2026五一港珠澳/P1034473.RW2")

        self.assertEqual(
            lumenflow_config.photo_output_dir(config, raw),
            Path("/photo-output-root/2026五一港珠澳"),
        )

    def test_photo_output_dir_can_add_workflow_subdir(self) -> None:
        config = {"photos": {"output_root": "/tmp/lumenflow-output"}}
        source_dir = Path("/photos/session-a")

        self.assertEqual(
            lumenflow_config.photo_output_dir(config, source_dir, subdir="previews"),
            Path("/tmp/lumenflow-output/session-a/previews"),
        )

    def test_explicit_photo_output_dir_overrides_config(self) -> None:
        self.assertEqual(
            lumenflow_config.resolve_photo_output_dir(
                {"photos": {"output_root": "/tmp/lumenflow-output"}},
                Path("/photos/session-a"),
                explicit_output_dir=Path("/tmp/manual"),
            ),
            Path("/tmp/manual"),
        )


if __name__ == "__main__":
    unittest.main()
