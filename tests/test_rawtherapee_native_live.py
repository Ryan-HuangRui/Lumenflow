"""Opt-in RawTherapee 5.11 native-module integration checks.

The test intentionally skips in normal CI because it needs the locally
installed RawTherapee binary and the private Bangkok RAW fixture copies.  Run
it with ``LUMENFLOW_RAWTHERAPEE_LIVE_FIXTURES=/path/to/bangkok-2026`` to prove
that the same bounded contract changes pixels, is deterministic, and never
mutates the RAW inputs.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import rawtherapee_pp3  # noqa: E402
import render_raw  # noqa: E402


FIXTURE_ENV = "LUMENFLOW_RAWTHERAPEE_LIVE_FIXTURES"
DEFAULT_CLI = shutil.which("rawtherapee-cli") or "/Applications/RawTherapee.app/Contents/MacOS/rawtherapee-cli"
DEFAULT_BASE_PROFILE = (
    "/Applications/RawTherapee.app/Contents/Resources/share/profiles/"
    "Standard Film Curve - ISO Medium.pp3"
)
RAW_NAMES = ("P1034631.RW2", "P1034748.RW2", "P1034812.RW2")


@unittest.skipUnless(os.environ.get(FIXTURE_ENV), f"set {FIXTURE_ENV} to run live checks")
class RawTherapeeNativeLiveTests(unittest.TestCase):
    @staticmethod
    def _native_contract() -> dict[str, object]:
        return {
            "profile_version": rawtherapee_pp3.RAWTHERAPEE_NATIVE_PROFILE_VERSION,
            "sections": {
                "RAW": {
                    "CA": True,
                    "CAAutoIterations": 2,
                    "CAAvoidColourshift": True,
                },
                "RAW Bayer": {"Method": "rcd"},
                "HLRecovery": {"Enabled": True, "Method": "Luminance"},
                "Exposure": {
                    "Compensation": 0.35,
                    "Brightness": 4,
                    "Contrast": 12,
                    "Saturation": -4,
                    "Black": 20,
                    "HighlightCompr": 24,
                    "HighlightComprThreshold": 18,
                    "ShadowCompr": 18,
                    "CurveMode": "Standard",
                    "Curve": "3;0;0;0.35;0.2;0.7;0.85;1;1;",
                },
                "White Balance": {
                    "Enabled": True,
                    "Setting": "Custom",
                    "Temperature": 5200,
                    "Green": 1.01,
                },
                "Color appearance": {
                    "Enabled": True,
                    "Q-Contrast": 20,
                    "Q-Bright": -10,
                    "J-Light": 10,
                    "C-Chroma": 12,
                },
                "Directional Pyramid Denoising": {
                    "Enabled": True,
                    "Luma": 35,
                    "Ldetail": 20,
                    "Chroma": 25,
                    "Gamma": 2.0,
                    "Passes": 1,
                },
                "Vibrance": {"Enabled": True, "Pastels": 20, "Saturated": 10},
                "Shadows & Highlights": {
                    "Enabled": True,
                    "Highlights": 15,
                    "HighlightTonalWidth": 70,
                    "Shadows": 20,
                    "ShadowTonalWidth": 30,
                    "Radius": 20,
                },
                "Sharpening": {
                    "Enabled": True,
                    "Method": "usm",
                    "Contrast": 50,
                    "Radius": 1.0,
                    "Amount": 250,
                },
                "SharpenEdge": {"Enabled": True, "Passes": 2, "Strength": 70},
                "SharpenMicro": {
                    "Enabled": True,
                    "Strength": 40,
                    "Contrast": 30,
                    "Uniformity": 5,
                },
                "Distortion": {"Amount": 35},
                "LensProfile": {
                    "LcMode": "lfauto",
                    "UseDistortion": True,
                    "UseVignette": True,
                    "UseCA": True,
                },
                "Rotation": {"Degree": 2.0},
                "Perspective": {"Horizontal": 5.0, "Vertical": -3.0},
                "Crop": {"Enabled": True, "X": 0, "Y": 0, "W": 4000, "H": 3000},
                "Resize": {"Enabled": True, "Scale": 0.5, "AllowUpscaling": False},
                "Color Management": {
                    "Gamut": True,
                    "OutputProfile": "RTv4_sRGB",
                    "OutputProfileIntent": "Relative",
                    "OutputBPC": True,
                },
            },
        }

    def test_native_modules_change_pixels_deterministically_for_all_fixtures(self) -> None:
        fixture_root = Path(os.environ[FIXTURE_ENV]).expanduser()
        executable = Path(os.environ.get("RAWTHERAPEE_CLI", DEFAULT_CLI))
        base_profile = Path(os.environ.get("RAWTHERAPEE_BASE_PROFILE", DEFAULT_BASE_PROFILE))
        if not executable.is_file():
            self.skipTest(f"RawTherapee CLI not found: {executable}")
        if not base_profile.is_file():
            self.skipTest(f"RawTherapee base profile not found: {base_profile}")
        sources = [fixture_root / name for name in RAW_NAMES]
        missing = [path for path in sources if not path.is_file()]
        if missing:
            self.skipTest(f"fixture RAW missing: {missing}")

        source_hashes = {path: self._sha256(path) for path in sources}
        source_entries = set(fixture_root.iterdir())
        native_contract = self._native_contract()
        overrides = rawtherapee_pp3.native_sections_to_overrides(native_contract)

        with tempfile.TemporaryDirectory(prefix="lumenflow-rawtherapee-live-") as directory:
            output_root = Path(directory)
            native_profile = output_root / "native.pp3"
            native_profile.write_text(
                rawtherapee_pp3.compile_profile_text(
                    [base_profile],
                    overrides=overrides,
                    app_version="5.11",
                    profile_version=rawtherapee_pp3.RAWTHERAPEE_NATIVE_PROFILE_VERSION,
                ),
                encoding="utf-8",
            )
            for source in sources:
                baseline_output = output_root / f"{source.stem}-baseline.jpg"
                native_output = output_root / f"{source.stem}-native.jpg"
                repeat_output = output_root / f"{source.stem}-native-repeat.jpg"
                self._run(executable, render_raw.build_rawtherapee_command(
                    source, baseline_output, [base_profile], executable=str(executable)
                ))
                native_command = render_raw.build_rawtherapee_command(
                    source, native_output, [native_profile], executable=str(executable)
                )
                self._run(executable, native_command)
                self._run(
                    executable,
                    render_raw.build_rawtherapee_command(
                        source, repeat_output, [native_profile], executable=str(executable)
                    ),
                )

                self.assertTrue(baseline_output.is_file())
                self.assertTrue(native_output.is_file())
                self.assertTrue(repeat_output.is_file())
                self.assertNotEqual(self._sha256(baseline_output), self._sha256(native_output))
                # JPEG container metadata can vary between CLI invocations;
                # the processing fingerprint is the decoded pixel bytes.
                self.assertEqual(self._pixel_sha256(native_output), self._pixel_sha256(repeat_output))
                self.assertTrue(self._has_pixel_difference(baseline_output, native_output))

        self.assertEqual(source_hashes, {path: self._sha256(path) for path in sources})
        self.assertEqual(source_entries, set(fixture_root.iterdir()))

    @staticmethod
    def _run(executable: Path, command: list[str]) -> None:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=240,
            env={**os.environ, "OMP_NUM_THREADS": "1"},
        )
        if completed.returncode:
            raise AssertionError(
                f"{executable} failed ({completed.returncode}): "
                f"{completed.stderr[-2000:]}"
            )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _has_pixel_difference(left: Path, right: Path) -> bool:
        from PIL import Image, ImageChops

        with Image.open(left) as left_image, Image.open(right) as right_image:
            if left_image.size != right_image.size or left_image.mode != right_image.mode:
                return True
            return ImageChops.difference(left_image, right_image).getbbox() is not None

    @staticmethod
    def _pixel_sha256(path: Path) -> str:
        import hashlib
        from PIL import Image

        with Image.open(path) as image:
            image.load()
            digest = hashlib.sha256()
            digest.update(str(image.mode).encode("ascii"))
            digest.update(str(image.size).encode("ascii"))
            digest.update(image.tobytes())
            return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()
