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

    @staticmethod
    def _phase3_contracts() -> dict[str, dict[str, object]]:
        return {
            "tone-detail": {
                "profile_version": rawtherapee_pp3.RAWTHERAPEE_NATIVE_PROFILE_VERSION,
                "sections": {
                    "Local Contrast": {
                        "Enabled": True,
                        "Radius": 100,
                        "Amount": 0.5,
                        "Darkness": 1,
                        "Lightness": 1,
                    },
                    "Retinex": {
                        "Enabled": True,
                        "Str": 35,
                        "Scal": 3,
                        "Iter": 1,
                        "Gam": 1.3,
                        "Median": False,
                        "Neigh": 80,
                    },
                    "ToneEqualizer": {
                        "Enabled": True,
                        "Band0": 1,
                        "Band1": 1,
                        "Band2": 0,
                        "Band3": 0,
                        "Band4": -1,
                        "Band5": -1,
                    },
                },
            },
            "curves-color": {
                "profile_version": rawtherapee_pp3.RAWTHERAPEE_NATIVE_PROFILE_VERSION,
                "sections": {
                    "Luminance Curve": {
                        "Enabled": True,
                        "LCurve": "3;0;0;0.25;0.15;0.75;0.85;1;1;",
                    },
                    "RGB Curves": {
                        "Enabled": True,
                        "LumaMode": False,
                        "rCurve": "3;0;0;0.5;0.3;1;1;",
                        "gCurve": "0;",
                        "bCurve": "0;",
                    },
                    "Channel Mixer": {
                        "Enabled": True,
                        "Red": "1000;150;0;",
                        "Green": "0;1000;0;",
                        "Blue": "0;0;1000;",
                    },
                    "Black & White": {
                        "Enabled": True,
                        "Method": "ChannelMixer",
                        "Auto": False,
                        "ComplementaryColors": True,
                        "Setting": "RGB-Rel",
                        "Filter": "None",
                        "MixerRed": 30,
                        "MixerOrange": 40,
                        "MixerYellow": 50,
                        "MixerGreen": 20,
                        "MixerCyan": 33,
                        "MixerBlue": 33,
                        "MixerMagenta": 33,
                        "MixerPurple": 33,
                    },
                    "HSV Equalizer": {
                        "Enabled": True,
                        "HCurve": "0;",
                        # HSV Equalizer curves use the serialized 1 + 4n
                        # control-point form emitted by RawTherapee 5.11.
                        "SCurve": (
                            "1;0.09;0.78;0.35;0.35;0.17;0.5;0.35;0.35;"
                            "0.29;0.5;0.35;0.35;0.51;0.5;0.35;0.35;"
                            "0.67;0.54;0.33;0.33;0.85;0.5;0.27;0.27;"
                        ),
                        "VCurve": "0;",
                    },
                },
            },
            "regional": {
                "profile_version": rawtherapee_pp3.RAWTHERAPEE_NATIVE_PROFILE_VERSION,
                "sections": {
                    "Gradient": {
                        "Enabled": True,
                        "Degree": 15,
                        "Feather": 40,
                        "Strength": 1,
                        "CenterX": 0,
                        "CenterY": 0,
                    },
                    "PCVignette": {
                        "Enabled": True,
                        "Strength": 1,
                        "Feather": 50,
                        "Roundness": 50,
                    },
                },
            },
        }

    @staticmethod
    def _phase3_section_contracts() -> dict[str, dict[str, object]]:
        """Return one independently enabled contract for every Phase 3 section.

        The grouped contracts below prove that the sections compose and remain
        deterministic across all three fixtures.  These single-section probes
        are deliberately separate so a strong effect from (for example) B&W
        cannot mask a PP3 key that RawTherapee silently ignores.
        """
        return {
            "Local Contrast": {
                "Enabled": True,
                "Radius": 100,
                "Amount": 0.5,
                "Darkness": 1,
                "Lightness": 1,
            },
            "Retinex": {
                "Enabled": True,
                "Str": 35,
                "Scal": 3,
                "Iter": 1,
                "Gam": 1.3,
                "Median": False,
                "Neigh": 80,
            },
            "ToneEqualizer": {
                "Enabled": True,
                "Band0": 1,
                "Band1": 1,
                "Band2": 0,
                "Band3": 0,
                "Band4": -1,
                "Band5": -1,
            },
            "Luminance Curve": {
                "Enabled": True,
                "LCurve": "3;0;0;0.25;0.15;0.75;0.85;1;1;",
            },
            "RGB Curves": {
                "Enabled": True,
                "LumaMode": False,
                "rCurve": "3;0;0;0.5;0.3;1;1;",
                "gCurve": "0;",
                "bCurve": "0;",
            },
            "Channel Mixer": {
                "Enabled": True,
                "Red": "1000;150;0;",
                "Green": "0;1000;0;",
                "Blue": "0;0;1000;",
            },
            "Black & White": {
                "Enabled": True,
                "Method": "ChannelMixer",
                "Auto": False,
                "ComplementaryColors": True,
                "Setting": "RGB-Rel",
                "Filter": "None",
                "MixerRed": 30,
                "MixerOrange": 40,
                "MixerYellow": 50,
                "MixerGreen": 20,
                "MixerCyan": 33,
                "MixerBlue": 33,
                "MixerMagenta": 33,
                "MixerPurple": 33,
            },
            "HSV Equalizer": {
                "Enabled": True,
                "HCurve": "0;",
                "SCurve": (
                    "1;0.09;0.78;0.35;0.35;0.17;0.5;0.35;0.35;"
                    "0.29;0.5;0.35;0.35;0.51;0.5;0.35;0.35;"
                    "0.67;0.54;0.33;0.33;0.85;0.5;0.27;0.27;"
                ),
                "VCurve": "0;",
            },
            "Gradient": {
                "Enabled": True,
                "Degree": 15,
                "Feather": 40,
                "Strength": 1,
                "CenterX": 0,
                "CenterY": 0,
            },
            "PCVignette": {
                "Enabled": True,
                "Strength": 1,
                "Feather": 50,
                "Roundness": 50,
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

    def test_phase3_advanced_groups_change_pixels_deterministically_for_all_fixtures(self) -> None:
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
        contracts = self._phase3_contracts()

        with tempfile.TemporaryDirectory(prefix="lumenflow-rawtherapee-phase3-live-") as directory:
            output_root = Path(directory)
            baseline_outputs: dict[Path, Path] = {}
            for source in sources:
                baseline_output = output_root / f"{source.stem}-baseline.jpg"
                self._run(
                    executable,
                    render_raw.build_rawtherapee_command(
                        source, baseline_output, [base_profile], executable=str(executable)
                    ),
                )
                baseline_outputs[source] = baseline_output

            for group_name, contract in contracts.items():
                overrides = rawtherapee_pp3.native_sections_to_overrides(contract)
                native_profile = output_root / f"{group_name}.pp3"
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
                    native_output = output_root / f"{source.stem}-{group_name}.jpg"
                    repeat_output = output_root / f"{source.stem}-{group_name}-repeat.jpg"
                    command = render_raw.build_rawtherapee_command(
                        source, native_output, [native_profile], executable=str(executable)
                    )
                    self._run(executable, command)
                    self._run(
                        executable,
                        render_raw.build_rawtherapee_command(
                            source,
                            repeat_output,
                            [native_profile],
                            executable=str(executable),
                        ),
                    )
                    self.assertTrue(native_output.is_file())
                    self.assertTrue(repeat_output.is_file())
                    self.assertTrue(
                        self._has_pixel_difference(baseline_outputs[source], native_output),
                        f"{group_name} did not change pixels for {source.name}",
                    )
                    self.assertEqual(
                        self._pixel_sha256(native_output),
                        self._pixel_sha256(repeat_output),
                        f"{group_name} was not deterministic for {source.name}",
                    )

        self.assertEqual(source_hashes, {path: self._sha256(path) for path in sources})
        self.assertEqual(source_entries, set(fixture_root.iterdir()))

    def test_phase3_each_section_changes_pixels_on_first_fixture(self) -> None:
        """Prove each advanced section is effective, not merely accepted.

        This is intentionally a one-shot pixel-delta check per section.  The
        grouped live test above supplies the more expensive three-fixture
        repeatability coverage.
        """
        fixture_root = Path(os.environ[FIXTURE_ENV]).expanduser()
        executable = Path(os.environ.get("RAWTHERAPEE_CLI", DEFAULT_CLI))
        base_profile = Path(os.environ.get("RAWTHERAPEE_BASE_PROFILE", DEFAULT_BASE_PROFILE))
        if not executable.is_file():
            self.skipTest(f"RawTherapee CLI not found: {executable}")
        if not base_profile.is_file():
            self.skipTest(f"RawTherapee base profile not found: {base_profile}")
        source = fixture_root / RAW_NAMES[0]
        if not source.is_file():
            self.skipTest(f"fixture RAW missing: {source}")

        source_hash = self._sha256(source)
        source_entries = set(fixture_root.iterdir())
        contracts = self._phase3_section_contracts()

        with tempfile.TemporaryDirectory(prefix="lumenflow-rawtherapee-phase3-sections-") as directory:
            output_root = Path(directory)
            baseline_output = output_root / "baseline.jpg"
            self._run(
                executable,
                render_raw.build_rawtherapee_command(
                    source, baseline_output, [base_profile], executable=str(executable)
                ),
            )
            for section_index, (section_name, section) in enumerate(contracts.items()):
                contract = {
                    "profile_version": rawtherapee_pp3.RAWTHERAPEE_NATIVE_PROFILE_VERSION,
                    "sections": {section_name: section},
                }
                # Keep output/profile basenames opaque: RawTherapee can find
                # same-named sidecars in a working directory, so a human
                # section name must not become an implicit input.
                profile = output_root / f"section-{section_index}.pp3"
                profile.write_text(
                    rawtherapee_pp3.compile_profile_text(
                        [base_profile],
                        overrides=rawtherapee_pp3.native_sections_to_overrides(contract),
                        app_version="5.11",
                        profile_version=rawtherapee_pp3.RAWTHERAPEE_NATIVE_PROFILE_VERSION,
                    ),
                    encoding="utf-8",
                )
                output = output_root / f"section-{section_index}.jpg"
                self._run(
                    executable,
                    render_raw.build_rawtherapee_command(
                        source, output, [profile], executable=str(executable)
                    ),
                )
                self.assertTrue(output.is_file())
                self.assertTrue(
                    self._has_pixel_difference(baseline_output, output),
                    f"{section_name} did not change pixels for {source.name}",
                )

        self.assertEqual(source_hash, self._sha256(source))
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
