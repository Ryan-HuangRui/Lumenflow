"""Opt-in real-RAW proof of the bounded Agent render/review loop.

This test verifies evidence plumbing, not aesthetic judgment.  The review
payloads stand in for decisions authored by a host model after it inspects the
exact receipt-bound JPEGs.  Run with::

    LUMENFLOW_RAW_AUTONOMY_LIVE_FIXTURES=/path/to/three-raw-directory \
      python3 -m unittest tests.test_raw_engine_autonomy_live -v
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import create_previews  # noqa: E402
import edit_intent  # noqa: E402
import preview_provider  # noqa: E402
import review_loop  # noqa: E402


LIVE_ENV = "LUMENFLOW_RAW_AUTONOMY_LIVE_FIXTURES"
RAWTHERAPEE_BASE_PROFILE_ENV = "RAWTHERAPEE_BASE_PROFILE"
DEFAULT_RAWTHERAPEE_BASE_PROFILE = Path(
    "/Applications/RawTherapee.app/Contents/Resources/share/profiles/"
    "Standard Film Curve - ISO Medium.pp3"
)
RAW_NAMES = ("P1034631.RW2", "P1034748.RW2", "P1034812.RW2")


@unittest.skipUnless(os.environ.get(LIVE_ENV), f"set {LIVE_ENV} to run live checks")
class RawEngineAutonomyLiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_root = Path(os.environ[LIVE_ENV]).resolve()
        missing = [name for name in RAW_NAMES if not (self.fixture_root / name).is_file()]
        if missing:
            self.fail(f"missing live RAW fixtures: {', '.join(missing)}")

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _rawtherapee_style(*, revised: bool) -> dict:
        return {
            "style_id": "street_light_shadow_cinematic",
            "rationale": "Preserve believable Bangkok color while strengthening street light structure.",
            "rawtherapee": {
                "profile_version": 349,
                "sections": {
                    "Exposure": {
                        "Compensation": 0.55 if revised else 0.35,
                        "Contrast": 16 if revised else 12,
                        "HighlightCompr": 28,
                        "ShadowCompr": 22 if revised else 16,
                    },
                    "White Balance": {
                        "Enabled": True,
                        "Setting": "Custom",
                        "Temperature": 5250,
                        "Green": 1.0,
                    },
                    "Local Contrast": {
                        "Enabled": True,
                        "Radius": 80,
                        "Amount": 0.35 if revised else 0.25,
                        "Darkness": 1.0,
                        "Lightness": 1.0,
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
                    "Vibrance": {"Enabled": True, "Pastels": 12, "Saturated": 5},
                    "Sharpening": {
                        "Enabled": True,
                        "Method": "usm",
                        "Radius": 0.7,
                        "Amount": 80,
                    },
                },
            },
        }

    @staticmethod
    def _darktable_style(*, revised: bool) -> dict:
        return {
            "style_id": "street_light_shadow_cinematic",
            "rationale": "Use only version-pinned darktable modules for a restrained street grade.",
            "darktable": {
                "modules": [
                    {
                        "operation": "highlights",
                        "params": {"mode": 5, "clip": 1.0, "iterations": 8, "recovery": 5},
                        "replace": True,
                    },
                    {
                        "operation": "demosaic",
                        "params": {"demosaicing_method": 5, "cs_enabled": 0},
                        "replace": True,
                    },
                    {
                        "operation": "denoiseprofile",
                        "params": {"strength": 0.45, "a_0": -1.0},
                        "replace": True,
                    },
                    {
                        "operation": "lens",
                        "params": {"method": 0, "modify_flags": 7, "scale": 1.0},
                        "replace": True,
                    },
                    {
                        "operation": "sharpen",
                        "params": {"radius": 1.4, "amount": 0.35},
                        "replace": True,
                    },
                    {
                        "operation": "toneequal",
                        "params": {
                            "shadows": 0.22 if revised else 0.12,
                            "highlights": -0.16,
                            "details": 0,
                            "method": 2,
                        },
                        "replace": True,
                    },
                    {
                        "operation": "colorequal",
                        "params": {"sat_red": 1.04, "bright_blue": 0.97},
                        "replace": True,
                    },
                    {
                        "operation": "ashift",
                        "params": {"rotation": 0.0, "cropmode": 0},
                        "replace": True,
                    },
                ]
            },
        }

    def _intent(
        self,
        *,
        backend: str,
        raw: Path,
        artifact: preview_provider.PreviewArtifact,
        index: int,
    ) -> dict:
        style = (
            self._rawtherapee_style(revised=False)
            if backend == "rawtherapee"
            else self._darktable_style(revised=False)
        )
        return {
            "schema_version": "lumenflow.edit_intent.v2",
            "intent_id": f"live-{backend}-{index}",
            "revision": 1,
            "authorization": {
                "kind": "explicit_user_request",
                "reference_id": "bangkok-live-autonomy-proof",
            },
            "source": {
                "path": str(raw),
                "fingerprint": preview_provider.file_fingerprint(raw),
            },
            "preview_basis": preview_provider.preview_basis_from_artifact(artifact),
            "purpose": "Validate an autonomous Bangkok travel-photo development loop.",
            "style": style,
            "global_adjustments": (
                {}
                if backend == "rawtherapee"
                else {"exposure_ev": 0.28, "contrast": 10, "saturation": 3}
            ),
            "composition": {
                "decision": "preserve_existing_crop" if backend == "darktable" else "no_crop",
                "reason": "Keep the full scene context for this backend proof.",
            },
            "local_adjustments": {
                "decision": "none",
                "reason": "This proof exercises globally bounded modules; arbitrary masks remain fail-closed.",
                "masks": [],
            },
        }

    @staticmethod
    def _review(
        *,
        intent: dict,
        plan: dict,
        receipt: dict,
        review_id: str,
        decision: str,
        changes: dict,
    ) -> dict:
        issues = []
        summary = "The verified second render is accepted."
        if decision == "revise":
            issues = [
                {
                    "category": "shadows",
                    "severity": "minor",
                    "observation": "The first render leaves foreground shadow separation too compressed.",
                    "recommendation": "Lift the bounded shadow control and local contrast slightly.",
                }
            ]
            summary = "Revise the receipt-bound first render once before final acceptance."
        return {
            "schema_version": "lumenflow.review_result.v1",
            "review_id": review_id,
            "intent_id": intent["intent_id"],
            "intent_revision": intent["revision"],
            "plan_id": plan["plan_id"],
            "receipt_id": receipt["receipt_id"],
            "output_fingerprint": receipt["output_fingerprint"],
            "decision": decision,
            "summary": summary,
            "issues": issues,
            "changes": changes,
        }

    def _exercise_backend(self, backend: str) -> None:
        executable = shutil.which(f"{backend}-cli")
        if backend == "rawtherapee":
            executable = shutil.which("rawtherapee-cli")
        if executable is None:
            self.skipTest(f"{backend} CLI is not installed")

        retained_root = os.environ.get("LUMENFLOW_RAW_AUTONOMY_EVIDENCE_DIR")
        if retained_root:
            requested_root = Path(retained_root).resolve() / backend
            if requested_root.exists():
                self.fail(f"refusing to overwrite retained live evidence: {requested_root}")
            requested_root.mkdir(parents=True)
            workspace = contextlib.nullcontext(requested_root)
        else:
            workspace = tempfile.TemporaryDirectory(prefix=f"lumenflow-{backend}-autonomy-")

        with workspace as directory:
            root = Path(directory)
            input_dir = root / "input"
            preview_dir = root / "previews"
            input_dir.mkdir()
            preview_dir.mkdir()
            base_profile = None
            if backend == "rawtherapee":
                base_profile = Path(
                    os.environ.get(
                        RAWTHERAPEE_BASE_PROFILE_ENV,
                        DEFAULT_RAWTHERAPEE_BASE_PROFILE,
                    )
                )
                if not base_profile.is_file():
                    self.skipTest(
                        "RawTherapee base profile not found; set "
                        f"{RAWTHERAPEE_BASE_PROFILE_ENV}: {base_profile}"
                    )
            else:
                base_profile = create_previews.resolve_preview_base_profile(
                    provider_name="darktable",
                    base_profile=None,
                    output_dir=preview_dir,
                )

            provider = preview_provider.create_preview_provider(backend)
            source_hashes: dict[str, dict] = {}
            for index, name in enumerate(RAW_NAMES, start=1):
                raw = input_dir / name
                shutil.copy2(self.fixture_root / name, raw)
                source_hashes[name] = preview_provider.file_fingerprint(raw)
                artifact = provider.create_preview(
                    preview_provider.PreviewRequest(
                        source=raw,
                        output=preview_dir / f"{raw.stem}.jpg",
                        base_profile=base_profile,
                        dry_run=False,
                        timeout=300,
                        selection_reason="explicit live fixture",
                    )
                )
                self.assertEqual(artifact.status, "success", artifact.failure_reason)
                self.assertEqual(artifact.state_completeness, "complete")

                output_dir = root / "renders" / raw.stem
                evidence_dir = root / "evidence" / raw.stem
                self._write_json(evidence_dir / "preview_artifact.json", artifact.to_dict())
                intent = self._intent(
                    backend=backend,
                    raw=raw,
                    artifact=artifact,
                    index=index,
                )
                session = review_loop.start_review_session(intent, max_revisions=2)
                self._write_json(evidence_dir / "intent.r1.json", intent)
                plan = edit_intent.compile_intent(
                    intent,
                    backend_id=backend,
                    output_dir=output_dir,
                )
                receipt = edit_intent.execute_plan(
                    plan,
                    dry_run=False,
                    timeout=300,
                    allowed_output_dir=output_dir,
                )
                self.assertEqual(receipt["status"], "success", receipt["failure_reason"])
                self._write_json(evidence_dir / "plan.r1.json", plan)
                self._write_json(evidence_dir / "receipt.r1.json", receipt)

                revised_style = (
                    self._rawtherapee_style(revised=True)
                    if backend == "rawtherapee"
                    else self._darktable_style(revised=True)
                )
                first_review = self._review(
                    intent=intent,
                    plan=plan,
                    receipt=receipt,
                    review_id=f"review-{backend}-{index}-r1",
                    decision="revise",
                    changes={
                        "style": revised_style,
                        "output": (
                            {
                                "format": "tiff",
                                "bit_depth": "16",
                                "rawtherapee": {"tiff_compression": True},
                            }
                            if backend == "rawtherapee"
                            else {
                                "format": "openexr",
                                "bit_depth": "32",
                                "darktable": {
                                    "icc_type": "LIN_REC2020",
                                    "icc_intent": "RELATIVE_COLORIMETRIC",
                                },
                            }
                        ),
                    },
                )
                transition = review_loop.advance_review_session(
                    session,
                    plan,
                    receipt,
                    first_review,
                )
                revised_intent = transition["next_intent"]
                self.assertIsNotNone(revised_intent)
                session = transition["session"]
                self._write_json(evidence_dir / "review.r1.json", first_review)
                self._write_json(evidence_dir / "intent.r2.json", revised_intent)
                revised_plan = edit_intent.compile_intent(
                    revised_intent,
                    backend_id=backend,
                    output_dir=output_dir,
                )
                revised_receipt = edit_intent.execute_plan(
                    revised_plan,
                    dry_run=False,
                    timeout=300,
                    allowed_output_dir=output_dir,
                )
                self.assertEqual(
                    revised_receipt["status"], "success", revised_receipt["failure_reason"]
                )
                self._write_json(evidence_dir / "plan.r2.json", revised_plan)
                self._write_json(evidence_dir / "receipt.r2.json", revised_receipt)
                final_review = self._review(
                    intent=revised_intent,
                    plan=revised_plan,
                    receipt=revised_receipt,
                    review_id=f"review-{backend}-{index}-r2",
                    decision="accept",
                    changes={},
                )
                accepted = review_loop.advance_review_session(
                    session,
                    revised_plan,
                    revised_receipt,
                    final_review,
                )
                self.assertEqual(accepted["session"]["status"], "accepted")
                self.assertEqual(accepted["session"]["revisions_used"], 1)
                self.assertIsNone(accepted["next_intent"])
                self.assertEqual(preview_provider.file_fingerprint(raw), source_hashes[name])
                self._write_json(evidence_dir / "review.r2.json", final_review)
                self._write_json(evidence_dir / "review_session.final.json", accepted["session"])

    def test_rawtherapee_preview_compile_render_review_revise_final_for_three_raws(self) -> None:
        self._exercise_backend("rawtherapee")

    def test_darktable_preview_compile_render_review_revise_final_for_three_raws(self) -> None:
        self._exercise_backend("darktable")


if __name__ == "__main__":
    unittest.main()
