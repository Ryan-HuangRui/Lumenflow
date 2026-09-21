from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import darktable_codec  # noqa: E402
import preview_provider  # noqa: E402


RAW_DIR_ENV = "LUMENFLOW_DARKTABLE_LIVE_RAW_DIR"
RAW_DIR = os.environ.get(RAW_DIR_ENV)


@unittest.skipUnless(RAW_DIR, f"set {RAW_DIR_ENV} to local RAW fixture copies")
class DarktableCodecLiveTests(unittest.TestCase):
    """Exercise every codec module through the installed darktable-cli.

    This test is opt-in because it takes tens of seconds per RAW and requires
    the locally installed 5.4.1 runtime.  The fixture path must contain copied
    RAWs only; no test ever writes beside a source file.
    """

    def test_all_verified_modules_render_three_or_more_real_raws(self) -> None:
        source_dir = Path(RAW_DIR).resolve()
        raws = sorted(source_dir.glob("*.RW2"))
        self.assertGreaterEqual(len(raws), 3)
        base = (Path("/Applications/darktable.app/Contents/MacOS/profiling-shot.xmp")).read_text(
            encoding="utf-8"
        )
        xmp, encoded = darktable_codec.compile_xmp(
            base,
            [
                {"operation": "exposure", "params": {"exposure": 0.45, "black": -0.01}},
                {
                    "operation": "temperature",
                    "params": {"red": 1.2, "green": 1.0, "blue": 0.85, "various": -2.0, "preset": 2},
                },
                {"operation": "sigmoid", "params": {"middle_grey_contrast": 1.6, "contrast_skewness": -0.2}},
                {"operation": "filmicrgb", "params": {"contrast": 1.1, "saturation": 4.0, "balance": -3.0}},
                {"operation": "colorbalancergb", "params": {"contrast": 0.08, "saturation_global": -0.04}},
                {"operation": "crop", "params": {"cx": 0.05, "cy": 0.05, "cw": 0.95, "ch": 0.95}},
            ],
        )
        self.assertEqual(
            {item["operation"] for item in encoded},
            {"exposure", "temperature", "sigmoid", "filmicrgb", "colorbalancergb", "crop"},
        )

        with tempfile.TemporaryDirectory(prefix="lumenflow-darktable-codec-live-") as directory:
            root = Path(directory)
            xmp_path = root / "generated.xmp"
            xmp_path.write_text(xmp, encoding="utf-8")
            for raw in raws:
                before = preview_provider.file_fingerprint(raw)
                runtime = root / raw.stem
                config = runtime / "config"
                cache = runtime / "cache"
                config.mkdir(parents=True)
                cache.mkdir()
                output = runtime / "output.jpg"
                command = [
                    "darktable-cli",
                    str(raw),
                    str(xmp_path),
                    str(output),
                    "--core",
                    "--configdir",
                    str(config),
                    "--cachedir",
                    str(cache),
                    "--library",
                    ":memory:",
                    "--conf",
                    "write_sidecar_files=never",
                ]
                result = subprocess.run(command, capture_output=True, text=True, timeout=180)
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                self.assertTrue(output.is_file())
                self.assertGreater(output.stat().st_size, 1024)
                self.assertEqual(preview_provider.file_fingerprint(raw), before)
                self.assertFalse(any(raw.parent.glob(raw.name + ".xmp")))


if __name__ == "__main__":
    unittest.main()
