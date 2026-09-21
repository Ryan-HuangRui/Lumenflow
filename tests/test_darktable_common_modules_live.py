from __future__ import annotations

import os
import hashlib
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
import render_raw  # noqa: E402


LIVE_ENV = "LUMENFLOW_DARKTABLE_LIVE_RAW_DIR"


@unittest.skipUnless(os.environ.get(LIVE_ENV), f"set {LIVE_ENV} to local RAW fixture copies")
class DarktableCommonModulesLiveTests(unittest.TestCase):
    """Live contract for the Phase 2 common-module codec slice.

    Every export uses a fresh isolated darktable runtime and a copied RAW.  A
    minimal XMP render is the pixel baseline; two identical Phase 2 renders
    prove both that the requested modules change pixels and that the bounded
    command is deterministic under CPU-only settings.
    """

    MODULES = [
        {"operation": "highlights", "params": {"mode": 5, "clip": 1.0, "iterations": 8, "recovery": 5}},
        {"operation": "demosaic", "params": {"demosaicing_method": 5, "cs_enabled": 0}},
        {"operation": "denoiseprofile", "params": {"strength": 0.6, "a_0": -1.0}},
        {"operation": "lens", "params": {"method": 0, "modify_flags": 7, "scale": 1.0}},
        {"operation": "sharpen", "params": {"radius": 2.0, "amount": 0.5}},
        {"operation": "diffuse", "params": {"iterations": 1, "radius": 8, "first": -0.05, "second": 0.02}},
        {"operation": "toneequal", "params": {"shadows": 0.15, "highlights": -0.15, "details": 0, "method": 2}},
        {"operation": "colorequal", "params": {"sat_red": 1.1, "bright_blue": 0.95}},
        {"operation": "ashift", "params": {"rotation": 1.0, "cropmode": 0}},
    ]

    def _render(
        self,
        raw: Path,
        xmp: Path,
        output: Path,
        runtime: Path,
        *,
        small: bool = False,
        output_format: str | None = None,
        bit_depth: int | None = None,
        pixel_check: bool = True,
        icc_type: str | None = None,
        icc_intent: str | None = None,
    ) -> dict[str, object]:
        config = runtime / "config"
        cache = runtime / "cache"
        config.mkdir(parents=True)
        cache.mkdir(parents=True)
        command = render_raw.build_darktable_command(
            raw,
            output,
            xmp=xmp,
            configdir=config,
            cachedir=cache,
            library=":memory:",
            write_sidecars=False,
            max_width=256 if small else None,
            max_height=256 if small else None,
            output_format=output_format,
            bit_depth=bit_depth,
            icc_type=icc_type,
            icc_intent=icc_intent,
        )
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertTrue(output.is_file())
        self.assertGreater(output.stat().st_size, 1024)
        file_fingerprint = preview_provider.file_fingerprint(output)
        if not pixel_check:
            return {**file_fingerprint, "pixel_sha256": None}
        # darktable writes output filename/mtime metadata, so byte-for-byte
        # JPEG hashes are not a valid determinism contract.  Compare decoded
        # RGB pixels and retain the file fingerprint for audit diagnostics.
        try:
            from PIL import Image

            with Image.open(output) as image:
                pixels = hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()
        except ImportError as error:  # pragma: no cover - test environment guard
            self.fail(f"Pillow is required for pixel determinism verification: {error}")
        return {**file_fingerprint, "pixel_sha256": pixels}

    def test_phase2_modules_change_pixels_and_are_deterministic_for_three_raws(self) -> None:
        fixture_dir = Path(os.environ[LIVE_ENV]).resolve()
        fixtures = sorted(fixture_dir.glob("*.RW2"))[:3]
        self.assertEqual(len(fixtures), 3)
        base_xmp, encoded = darktable_codec.compile_xmp(
            darktable_codec.minimal_xmp(), self.MODULES
        )
        self.assertEqual({item["operation"] for item in encoded}, {
            "highlights", "demosaic", "denoiseprofile", "lens", "sharpen",
            "diffuse", "toneequal", "colorequal", "ashift",
        })

        with tempfile.TemporaryDirectory(prefix="lumenflow-darktable-common-live-") as directory:
            root = Path(directory)
            xmp = root / "phase2.xmp"
            base = root / "base.xmp"
            xmp.write_text(base_xmp, encoding="utf-8")
            base.write_text(darktable_codec.minimal_xmp(), encoding="utf-8")
            for index, fixture in enumerate(fixtures):
                raw = root / fixture.name
                shutil.copyfile(fixture, raw)
                before = preview_provider.file_fingerprint(raw)
                baseline = self._render(raw, base, root / f"baseline-{index}.jpg", root / f"baseline-{index}")
                first = self._render(raw, xmp, root / f"phase2-{index}-a.jpg", root / f"phase2-{index}-a")
                second = self._render(raw, xmp, root / f"phase2-{index}-b.jpg", root / f"phase2-{index}-b")
                self.assertNotEqual(first["pixel_sha256"], baseline["pixel_sha256"], fixture.name)
                self.assertEqual(first["pixel_sha256"], second["pixel_sha256"], fixture.name)
                self.assertEqual(preview_provider.file_fingerprint(raw), before)
                self.assertFalse(raw.with_suffix(".xmp").exists())
                self.assertFalse(raw.with_name(raw.name + ".xmp").exists())

    def test_each_phase2_operation_has_an_independent_pixel_delta(self) -> None:
        fixture_dir = Path(os.environ[LIVE_ENV]).resolve()
        fixture = sorted(fixture_dir.glob("*.RW2"))[0]
        requests = {
            "highlights": {"operation": "highlights", "params": {"mode": 0, "clip": 0.01, "iterations": 8, "recovery": 5}},
            "demosaic": {"operation": "demosaic", "params": {"demosaicing_method": 1}},
            "denoiseprofile": {"operation": "denoiseprofile", "params": {"strength": 0.5, "a_0": -1.0}},
            "lens": {"operation": "lens", "params": {"method": 0, "modify_flags": 7, "v_strength": 0.65}},
            "sharpen": {"operation": "sharpen", "params": {"radius": 2.0, "amount": 1.5}},
            "diffuse": {"operation": "diffuse", "params": {"iterations": 2, "radius": 8, "first": -0.25, "second": 0.125}},
            "toneequal": {"operation": "toneequal", "params": {"shadows": 0.5, "highlights": -0.5, "details": 0, "method": 2}},
            "colorequal": {"operation": "colorequal", "params": {"sat_red": 1.5, "bright_blue": 0.8}},
            "ashift": {"operation": "ashift", "params": {"rotation": 5.0, "cropmode": 0}},
        }
        with tempfile.TemporaryDirectory(prefix="lumenflow-darktable-common-delta-") as directory:
            root = Path(directory)
            raw = root / fixture.name
            shutil.copyfile(fixture, raw)
            source_before = preview_provider.file_fingerprint(raw)
            base = root / "base.xmp"
            base.write_text(darktable_codec.minimal_xmp(), encoding="utf-8")
            baseline = self._render(raw, base, root / "baseline.jpg", root / "baseline", small=True)
            for operation, request in requests.items():
                xmp = root / f"{operation}.xmp"
                xmp.write_text(
                    darktable_codec.compile_xmp(darktable_codec.minimal_xmp(), [request])[0],
                    encoding="utf-8",
                )
                rendered = self._render(
                    raw, xmp, root / f"{operation}.jpg", root / operation, small=True
                )
                self.assertNotEqual(
                    rendered["pixel_sha256"], baseline["pixel_sha256"], operation
                )
            self.assertEqual(preview_provider.file_fingerprint(raw), source_before)

    def test_output_formats_and_icc_are_created_with_expected_pixel_types(self) -> None:
        fixture_dir = Path(os.environ[LIVE_ENV]).resolve()
        fixture = sorted(fixture_dir.glob("*.RW2"))[0]
        cases = (
            ("jpeg", "jpg", 8, "mjpeg", None),
            ("png", "png", 8, "png", "rgb24"),
            ("png", "png", 16, "png", "rgb48be"),
            ("tiff", "tif", 8, "tiff", "rgb24"),
            ("tiff", "tif", 16, "tiff", "rgb48le"),
            ("tiff", "tif", 32, "tiff", "rgbf32le"),
            ("openexr", "exr", 16, "exr", "gbrpf16le"),
            ("openexr", "exr", 32, "exr", "gbrpf32le"),
        )
        with tempfile.TemporaryDirectory(prefix="lumenflow-darktable-output-live-") as directory:
            root = Path(directory)
            raw = root / fixture.name
            shutil.copyfile(fixture, raw)
            base = root / "base.xmp"
            base.write_text(darktable_codec.minimal_xmp(), encoding="utf-8")
            for index, (output_format, suffix, depth, codec, expected_pix_fmt) in enumerate(cases):
                output = root / f"output-{index}.{suffix}"
                runtime = root / f"runtime-{index}"
                self._render(
                    raw,
                    base,
                    output,
                    runtime,
                    small=True,
                    output_format=output_format,
                    bit_depth=depth,
                    pixel_check=False,
                    icc_type="SRGB" if output_format == "jpeg" else None,
                    icc_intent="PERCEPTUAL" if output_format == "jpeg" else None,
                )
                self.assertEqual(output.suffix, f".{suffix}")
                probe = subprocess.run(
                    [
                        "ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=codec_name,pix_fmt", "-of", "default=nw=1",
                        str(output),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
                self.assertIn(f"codec_name={codec}", probe)
                if expected_pix_fmt is not None:
                    self.assertIn(f"pix_fmt={expected_pix_fmt}", probe)
                if output_format == "jpeg":
                    from PIL import Image

                    with Image.open(output) as image:
                        self.assertGreater(len(image.info.get("icc_profile", b"")), 0)


if __name__ == "__main__":
    unittest.main()
