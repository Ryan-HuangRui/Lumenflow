from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backend_capabilities  # noqa: E402
import darktable_codec  # noqa: E402
import edit_intent  # noqa: E402
import preview_provider  # noqa: E402


class EditIntentExecutionTests(unittest.TestCase):
    def _intent(self, raw: Path, *, crop: bool = False) -> dict:
        fingerprint = preview_provider.file_fingerprint(raw)
        composition: dict[str, object] = {
            "decision": "no_crop",
            "reason": "The source framing already supports the story.",
        }
        if crop:
            composition = {
                "decision": "crop",
                "reason": "Remove a distracting edge.",
                "crop": {
                    "unit": "pixels",
                    "x": 10,
                    "y": 20,
                    "width": 1200,
                    "height": 800,
                    "fixed_ratio": True,
                    "ratio": "3:2",
                },
            }
        return {
            "schema_version": "lumenflow.edit_intent.v2",
            "intent_id": "intent-bangkok-001",
            "revision": 1,
            "authorization": {
                "kind": "user_confirmed_selection",
                "reference_id": "approval-bangkok-001",
            },
            "source": {
                "path": str(raw),
                "fingerprint": fingerprint,
            },
            "preview_basis": {
                "artifact_id": "preview_" + "a" * 32,
                "starting_state_hash": "b" * 64,
                "state_completeness": "complete",
            },
            "purpose": "Bangkok travel story",
            "style": {
                "style_id": "street_light_shadow_cinematic",
                "rationale": "Keep the humid night atmosphere while preserving readable faces.",
            },
            "global_adjustments": {
                "exposure_ev": 0.35,
                "contrast": 12,
                "highlight_recovery": 24,
                "shadow_lift": 18,
                "black_point": 220,
                "saturation": -4,
                "temperature_k": 5200,
                "green_multiplier": 1.01,
            },
            "composition": composition,
            "local_adjustments": {
                "decision": "none",
                "reason": "The first pass only needs global adjustments.",
                "masks": [],
            },
        }

    def test_compile_rawtherapee_plan_is_deterministic_and_side_effect_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            output_dir = root / "output"
            raw.write_bytes(b"raw-bangkok")
            intent = self._intent(raw, crop=True)

            first = edit_intent.compile_intent(
                intent,
                backend_id="rawtherapee",
                output_dir=output_dir,
                local_config={"tools": {"rawtherapee_cli": "/custom/rawtherapee-cli"}},
            )
            second = edit_intent.compile_intent(
                intent,
                backend_id="rawtherapee",
                output_dir=output_dir,
                local_config={"tools": {"rawtherapee_cli": "/custom/rawtherapee-cli"}},
            )

            self.assertEqual(first["schema_version"], "lumenflow.execution_plan.v1")
            self.assertEqual(first["plan_id"], second["plan_id"])
            self.assertEqual(first["backend"]["id"], "rawtherapee")
            self.assertEqual(
                first["required_capabilities"],
                ["intent.compile.v2", "render", "composition.crop"],
            )
            profile_operation = first["operations"][0]
            self.assertEqual(profile_operation["kind"], "materialize_profile")
            self.assertIn("Compensation=0.35", profile_operation["payload"]["content"])
            self.assertIn("HighlightCompr=24", profile_operation["payload"]["content"])
            self.assertIn("ShadowCompr=18", profile_operation["payload"]["content"])
            self.assertIn("[Crop]", profile_operation["payload"]["content"])
            self.assertEqual(first["operations"][1]["command_argv"][0], "/custom/rawtherapee-cli")
            self.assertFalse(output_dir.exists())

    def test_compile_rawtherapee_applies_bounded_native_sections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            output_dir = root / "output"
            raw.write_bytes(b"raw-bangkok")
            intent = self._intent(raw)
            intent["style"]["rawtherapee"] = {
                "profile_version": 349,
                "sections": {
                    "RAW": {"CA": True, "CAAutoIterations": 2},
                    "Exposure": {
                        "CurveMode": "Standard",
                        "Curve": "3;0;0;0.35;0.2;0.7;0.85;1;1;",
                    },
                    "Sharpening": {"Enabled": True, "Radius": 1.0, "Amount": 250},
                    "Rotation": {"Degree": 2.0},
                },
            }

            first = edit_intent.compile_intent(
                intent,
                backend_id="rawtherapee",
                output_dir=output_dir,
                local_config={"tools": {"rawtherapee_cli": "/custom/rawtherapee-cli"}},
            )
            second = edit_intent.compile_intent(
                intent,
                backend_id="rawtherapee",
                output_dir=output_dir,
                local_config={"tools": {"rawtherapee_cli": "/custom/rawtherapee-cli"}},
            )

            content = first["operations"][0]["payload"]["content"]
            self.assertIn("Compiler=lumenflow.rawtherapee-pp3.v3", content)
            self.assertIn("CAAutoIterations=2", content)
            self.assertIn("Curve=3;0;0;0.35;0.2;0.7;0.85;1;1;", content)
            self.assertIn("Amount=250", content)
            self.assertIn("Degree=2", content)
            self.assertEqual(first["plan_id"], second["plan_id"])
            self.assertEqual(
                first["operations"][0]["payload"]["sha256"],
                second["operations"][0]["payload"]["sha256"],
            )

    def test_native_sections_are_rejected_by_darktable_compiler(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            raw.write_bytes(b"raw-bangkok")
            intent = self._intent(raw)
            intent["style"]["rawtherapee"] = {
                "profile_version": 349,
                "sections": {"RAW": {"CA": True}},
            }
            intent["global_adjustments"] = {}
            intent["composition"] = {
                "decision": "preserve_existing_crop",
                "reason": "Replay the approved darktable history stack.",
            }
            with self.assertRaises(edit_intent.IntentValidationError):
                edit_intent.compile_intent(
                    intent,
                    backend_id="darktable",
                    output_dir=root / "output",
                    local_config={"tools": {"darktable_cli": "/custom/darktable-cli"}},
                )

    def test_darktable_modules_are_rejected_by_rawtherapee_compiler(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            raw.write_bytes(b"raw-bangkok")
            intent = self._intent(raw)
            intent["style"]["darktable"] = {
                "modules": [{"operation": "exposure", "params": {}}],
            }
            with self.assertRaises(edit_intent.IntentValidationError):
                edit_intent.compile_intent(
                    intent,
                    backend_id="rawtherapee",
                    output_dir=root / "output",
                    local_config={"tools": {"rawtherapee_cli": "/custom/rawtherapee-cli"}},
                )

    def test_native_section_conflicts_with_semantic_field_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            raw.write_bytes(b"raw-bangkok")
            intent = self._intent(raw)
            intent["style"]["rawtherapee"] = {
                "profile_version": 349,
                "sections": {"Exposure": {"Compensation": 1.25}},
            }
            with self.assertRaises(edit_intent.IntentValidationError) as error:
                edit_intent.compile_intent(
                    intent,
                    backend_id="rawtherapee",
                    output_dir=root / "output",
                    local_config={"tools": {"rawtherapee_cli": "/custom/rawtherapee-cli"}},
                )
            self.assertIn("Conflicting RawTherapee overrides", str(error.exception))

    def test_compile_darktable_replays_only_the_preview_bound_xmp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            xmp = root / "bangkok.DNG.xmp"
            output_dir = root / "output"
            raw.write_bytes(b"raw-bangkok")
            xmp.write_text(darktable_codec.minimal_xmp(), encoding="utf-8")
            preview = preview_provider.DarktablePreviewProvider().create_preview(
                preview_provider.PreviewRequest(
                    source=raw,
                    output=root / "preview.jpg",
                    base_profile=xmp,
                    dry_run=True,
                    timeout=10,
                )
            )
            intent = self._intent(raw)
            intent["global_adjustments"] = {}
            intent["composition"] = {
                "decision": "preserve_existing_crop",
                "reason": "Replay the approved darktable history stack.",
            }
            intent["preview_basis"] = {
                "artifact_id": preview.artifact_id,
                "starting_state_hash": preview.starting_state_hash,
                "state_completeness": preview.state_completeness,
            }

            plan = edit_intent.compile_intent(
                intent,
                backend_id="darktable",
                output_dir=output_dir,
                local_config={"tools": {"darktable_cli": "/custom/darktable-cli"}},
            )

            self.assertEqual(plan["backend"]["id"], "darktable")
            self.assertEqual(plan["compiler"], {"id": "lumenflow.darktable-xmp-replay", "version": "1"})
            self.assertEqual(plan["required_capabilities"], ["intent.compile.v2", "render"])
            self.assertEqual(plan["operations"][0]["payload"]["content"], xmp.read_text(encoding="utf-8"))
            command = plan["operations"][1]["command_argv"]
            self.assertEqual(command[0], "/custom/darktable-cli")
            self.assertEqual(command[1], str(raw))
            self.assertEqual(command[2], plan["artifacts"]["profile"]["path"])
            self.assertIn(":memory:", command)
            self.assertIn("write_sidecar_files=never", command)
            self.assertFalse(output_dir.exists())

            receipt = edit_intent.execute_plan(
                plan,
                dry_run=True,
                timeout=10,
                allowed_output_dir=output_dir,
                local_config={"tools": {"darktable_cli": "/custom/darktable-cli"}},
            )
            self.assertEqual(receipt["status"], "dry_run")
            self.assertFalse(output_dir.exists())

    def test_darktable_compiler_rejects_unmapped_adjustments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            xmp = root / "bangkok.DNG.xmp"
            raw.write_bytes(b"raw-bangkok")
            xmp.write_text(darktable_codec.minimal_xmp(), encoding="utf-8")
            preview = preview_provider.DarktablePreviewProvider().create_preview(
                preview_provider.PreviewRequest(raw, root / "preview.jpg", xmp, True, 10)
            )
            intent = self._intent(raw)
            intent["composition"] = {
                "decision": "preserve_existing_crop",
                "reason": "Keep existing crop.",
            }
            intent["preview_basis"] = {
                "artifact_id": preview.artifact_id,
                "starting_state_hash": preview.starting_state_hash,
                "state_completeness": preview.state_completeness,
            }

            with self.assertRaises(edit_intent.IntentValidationError) as error:
                edit_intent.compile_intent(intent, backend_id="darktable", output_dir=root / "output")

            self.assertIn("does not map dynamic adjustments", str(error.exception))

    def test_execute_plan_dry_run_writes_nothing_and_returns_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            output_dir = root / "output"
            raw.write_bytes(b"raw-bangkok")
            plan = edit_intent.compile_intent(
                self._intent(raw),
                backend_id="rawtherapee",
                output_dir=output_dir,
            )

            receipt = edit_intent.execute_plan(
                plan,
                dry_run=True,
                timeout=10,
                allowed_output_dir=output_dir,
            )

            self.assertEqual(receipt["schema_version"], "lumenflow.execution_receipt.v1")
            self.assertEqual(receipt["status"], "dry_run")
            self.assertTrue(receipt["source_unchanged"])
            self.assertIsNone(receipt["output_fingerprint"])
            self.assertEqual(
                [operation["status"] for operation in receipt["operations"]],
                ["dry_run", "dry_run"],
            )
            self.assertFalse(output_dir.exists())

    def test_execute_plan_records_verified_output_and_preserves_raw(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            output_dir = root / "output"
            raw.write_bytes(b"raw-bangkok")
            plan = edit_intent.compile_intent(
                self._intent(raw),
                backend_id="rawtherapee",
                output_dir=output_dir,
            )

            def fake_runner(command: list[str], *, dry_run: bool, timeout: int | None) -> int:
                self.assertFalse(dry_run)
                self.assertEqual(timeout, 10)
                Path(command[2]).write_bytes(b"rendered-jpeg")
                return 0

            receipt = edit_intent.execute_plan(
                plan,
                dry_run=False,
                timeout=10,
                runner=fake_runner,
                allowed_output_dir=output_dir,
            )

            self.assertEqual(receipt["status"], "success")
            self.assertTrue(receipt["source_unchanged"])
            self.assertEqual(
                receipt["output_fingerprint"],
                {
                    "sha256": hashlib.sha256(b"rendered-jpeg").hexdigest(),
                    "size_bytes": len(b"rendered-jpeg"),
                },
            )
            self.assertTrue(Path(plan["artifacts"]["profile"]["path"]).exists())
            self.assertTrue(Path(plan["artifacts"]["output"]["path"]).exists())
            self.assertEqual(raw.read_bytes(), b"raw-bangkok")

    def test_source_precondition_mismatch_blocks_all_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            output_dir = root / "output"
            raw.write_bytes(b"raw-bangkok")
            plan = edit_intent.compile_intent(
                self._intent(raw),
                backend_id="rawtherapee",
                output_dir=output_dir,
            )
            raw.write_bytes(b"changed-after-intent")

            with self.assertRaises(edit_intent.ExecutionPreconditionError) as error:
                edit_intent.execute_plan(
                    plan,
                    dry_run=False,
                    timeout=10,
                    allowed_output_dir=output_dir,
                )

            self.assertEqual(error.exception.code, "SOURCE_FINGERPRINT_MISMATCH")
            self.assertEqual(
                error.exception.to_dict(),
                {
                    "code": "SOURCE_FINGERPRINT_MISMATCH",
                    "reason": "The source bytes no longer match the execution plan",
                },
            )
            self.assertFalse(output_dir.exists())

    def test_unsupported_backend_fails_with_capability_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            raw.write_bytes(b"raw-bangkok")

            with self.assertRaises(backend_capabilities.UnsupportedCapabilityError) as error:
                edit_intent.compile_intent(
                    self._intent(raw),
                    backend_id="lightroom",
                    output_dir=root / "output",
                )

            self.assertEqual(error.exception.capability_name, "intent.compile.v2")

    def test_intent_validation_rejects_unknown_fields_and_out_of_range_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "bangkok.DNG"
            raw.write_bytes(b"raw-bangkok")
            intent = self._intent(raw)
            intent["backend"] = "rawtherapee"

            with self.assertRaises(edit_intent.IntentValidationError) as unknown_error:
                edit_intent.compile_intent(
                    intent,
                    backend_id="rawtherapee",
                    output_dir=Path(directory) / "output",
                )
            self.assertIn("unknown fields", str(unknown_error.exception))

            intent = self._intent(raw)
            intent["global_adjustments"]["exposure_ev"] = 99
            with self.assertRaises(edit_intent.IntentValidationError) as range_error:
                edit_intent.compile_intent(
                    intent,
                    backend_id="rawtherapee",
                    output_dir=Path(directory) / "output",
                )
            self.assertIn("exposure_ev", str(range_error.exception))

    def test_tampered_command_is_rejected_before_runner_or_file_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            output_dir = root / "output"
            raw.write_bytes(b"raw-bangkok")
            plan = edit_intent.compile_intent(
                self._intent(raw),
                backend_id="rawtherapee",
                output_dir=output_dir,
            )
            plan["operations"][1]["command_argv"] = ["/bin/sh", "-c", "touch /tmp/lumenflow-pwned"]
            calls: list[list[str]] = []

            def runner(command: list[str], *, dry_run: bool, timeout: int | None) -> int:
                calls.append(command)
                return 0

            with self.assertRaises(edit_intent.ExecutionPreconditionError) as error:
                edit_intent.execute_plan(
                    plan,
                    dry_run=False,
                    timeout=10,
                    runner=runner,
                    allowed_output_dir=output_dir,
                )

            self.assertEqual(error.exception.code, "PLAN_COMMAND_MISMATCH")
            self.assertEqual(calls, [])
            self.assertFalse(output_dir.exists())

    def test_failed_render_receipt_marks_failing_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            output_dir = root / "output"
            raw.write_bytes(b"raw-bangkok")
            plan = edit_intent.compile_intent(
                self._intent(raw),
                backend_id="rawtherapee",
                output_dir=output_dir,
            )

            def failed_runner(command: list[str], *, dry_run: bool, timeout: int | None) -> int:
                raise OSError("renderer unavailable")

            receipt = edit_intent.execute_plan(
                plan,
                dry_run=False,
                timeout=10,
                runner=failed_runner,
                allowed_output_dir=output_dir,
            )

            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(
                [operation["status"] for operation in receipt["operations"]],
                ["success", "failed"],
            )
            self.assertIn("renderer unavailable", receipt["failure_reason"])

    def test_profile_path_outside_allowed_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            output_dir = root / "output"
            raw.write_bytes(b"raw-bangkok")
            plan = edit_intent.compile_intent(
                self._intent(raw),
                backend_id="rawtherapee",
                output_dir=output_dir,
            )
            escaped_profile = root / "escaped.pp3"
            plan["artifacts"]["profile"]["path"] = str(escaped_profile)
            plan["operations"][0]["payload"]["path"] = str(escaped_profile)

            with self.assertRaises(edit_intent.ExecutionPreconditionError) as error:
                edit_intent.execute_plan(
                    plan,
                    dry_run=False,
                    timeout=10,
                    allowed_output_dir=output_dir,
                )

            self.assertEqual(error.exception.code, "OUTPUT_PATH_OUTSIDE_ALLOWED_ROOT")
            self.assertFalse(escaped_profile.exists())

    def test_allowed_output_root_must_match_compiled_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            output_dir = root / "output"
            raw.write_bytes(b"raw-bangkok")
            plan = edit_intent.compile_intent(
                self._intent(raw),
                backend_id="rawtherapee",
                output_dir=output_dir,
            )

            with self.assertRaises(edit_intent.ExecutionPreconditionError) as error:
                edit_intent.execute_plan(
                    plan,
                    dry_run=True,
                    timeout=10,
                    allowed_output_dir=root / "different-output",
                )

            self.assertEqual(error.exception.code, "OUTPUT_ROOT_MISMATCH")
            self.assertFalse(output_dir.exists())

    def test_existing_output_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            output_dir = root / "output"
            raw.write_bytes(b"raw-bangkok")
            plan = edit_intent.compile_intent(
                self._intent(raw),
                backend_id="rawtherapee",
                output_dir=output_dir,
            )
            output_path = Path(plan["artifacts"]["output"]["path"])
            output_path.parent.mkdir(parents=True)
            output_path.write_bytes(b"existing-render")

            with self.assertRaises(edit_intent.ExecutionPreconditionError) as error:
                edit_intent.execute_plan(
                    plan,
                    dry_run=False,
                    timeout=10,
                    allowed_output_dir=output_dir,
                )

            self.assertEqual(error.exception.code, "OUTPUT_ALREADY_EXISTS")
            self.assertEqual(output_path.read_bytes(), b"existing-render")

    def test_unverified_masks_are_rejected_by_backend_capability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            raw.write_bytes(b"raw-bangkok")
            intent = self._intent(raw)
            intent["local_adjustments"] = {
                "decision": "use_masks",
                "reason": "Lift the subject locally.",
                "masks": [
                    {
                        "type": "subject",
                        "rationale": "Keep the background dark.",
                        "adjustments": {"exposure_ev": 0.25},
                    }
                ],
            }

            with self.assertRaises(backend_capabilities.UnsupportedCapabilityError) as error:
                edit_intent.compile_intent(
                    intent,
                    backend_id="rawtherapee",
                    output_dir=root / "output",
                )

            self.assertEqual(error.exception.capability_name, "mask.ai")

    def test_cli_compiles_and_dry_runs_with_explicit_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            output_dir = root / "output"
            intent_path = root / "intent.json"
            plan_path = root / "execution_plan.json"
            receipt_path = root / "execution_receipt.json"
            raw.write_bytes(b"raw-bangkok")
            intent_path.write_text(json.dumps(self._intent(raw)), encoding="utf-8")

            with patch(
                "sys.argv",
                [
                    "edit_intent.py",
                    "compile",
                    str(intent_path),
                    "--backend",
                    "rawtherapee",
                    "--output-dir",
                    str(output_dir),
                    "--plan-output",
                    str(plan_path),
                ],
            ):
                edit_intent.main()

            with patch(
                "sys.argv",
                [
                    "edit_intent.py",
                    "execute",
                    str(plan_path),
                    "--allowed-output-dir",
                    str(output_dir),
                    "--receipt-output",
                    str(receipt_path),
                    "--dry-run",
                ],
            ):
                edit_intent.main()

            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["plan_id"], plan["plan_id"])
            self.assertEqual(receipt["status"], "dry_run")

    def test_vertical_slice_binds_preview_to_plan_and_verified_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            sidecar = root / "bangkok.DNG.pp3"
            preview_path = root / "preview.jpg"
            output_dir = root / "output"
            raw.write_bytes(b"raw-bangkok")
            sidecar.write_text("[Exposure]\nCompensation=0.1\n", encoding="utf-8")
            preview = preview_provider.RawTherapeePreviewProvider().create_preview(
                preview_provider.PreviewRequest(
                    source=raw,
                    output=preview_path,
                    base_profile=None,
                    dry_run=True,
                    timeout=10,
                )
            )
            intent = self._intent(raw)
            intent["preview_basis"] = {
                "artifact_id": preview.artifact_id,
                "starting_state_hash": preview.starting_state_hash,
                "state_completeness": preview.state_completeness,
            }
            plan = edit_intent.compile_intent(
                intent,
                backend_id="rawtherapee",
                output_dir=output_dir,
            )

            def fake_runner(command: list[str], *, dry_run: bool, timeout: int | None) -> int:
                Path(command[2]).write_bytes(b"vertical-slice-jpeg")
                return 0

            receipt = edit_intent.execute_plan(
                plan,
                dry_run=False,
                timeout=10,
                runner=fake_runner,
                allowed_output_dir=output_dir,
            )

            self.assertEqual(plan["preview_basis"]["artifact_id"], preview.artifact_id)
            self.assertEqual(plan["preview_basis"]["starting_state_hash"], preview.starting_state_hash)
            self.assertEqual(receipt["plan_id"], plan["plan_id"])
            self.assertEqual(receipt["status"], "success")
            self.assertTrue(receipt["source_unchanged"])

    def test_rawtherapee_compiler_embeds_explicit_preview_profile_stack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            base = root / "base.pp3"
            sidecar = root / "bangkok.DNG.pp3"
            raw.write_bytes(b"raw-bangkok")
            base.write_text(
                "[Exposure]\nCompensation=0.1\n[Future Module]\nOpaque=preserve\n",
                encoding="utf-8",
            )
            sidecar.write_text("[Exposure]\nContrast=3\n[Future Sidecar]\nNative=keep\n", encoding="utf-8")
            preview = preview_provider.RawTherapeePreviewProvider().create_preview(
                preview_provider.PreviewRequest(raw, root / "preview.jpg", base, True, 10)
            )
            intent = self._intent(raw)
            intent["preview_basis"] = preview_provider.preview_basis_from_artifact(preview)
            plan = edit_intent.compile_intent(intent, backend_id="rawtherapee", output_dir=root / "output")
            content = plan["operations"][0]["payload"]["content"]
            self.assertIn("Opaque=preserve", content)
            self.assertIn("Native=keep", content)
            self.assertIn("Compensation=0.35", content)
            self.assertIn("Compiler=lumenflow.rawtherapee-pp3.v3", content)

            sidecar.write_text("[Exposure]\nContrast=99\n", encoding="utf-8")
            with self.assertRaises(edit_intent.ExecutionPreconditionError) as error:
                edit_intent.compile_intent(intent, backend_id="rawtherapee", output_dir=root / "other-output")
            self.assertEqual(error.exception.code, "PREVIEW_STATE_INPUT_MISMATCH")

    def test_contract_schemas_are_strict_and_versioned(self) -> None:
        expectations = {
            "edit_intent.schema.json": "lumenflow.edit_intent.v2",
            "execution_plan.schema.json": "lumenflow.execution_plan.v1",
            "execution_receipt.schema.json": "lumenflow.execution_receipt.v1",
        }
        for filename, version in expectations.items():
            with self.subTest(filename=filename):
                schema = json.loads(
                    (ROOT / "knowledge" / "schemas" / filename).read_text(encoding="utf-8")
                )
                self.assertEqual(schema["properties"]["schema_version"]["const"], version)
                self.assertIs(schema["additionalProperties"], False)

        intent_schema = json.loads(
            (ROOT / "knowledge" / "schemas" / "edit_intent.schema.json").read_text(
                encoding="utf-8"
            )
        )
        native = intent_schema["properties"]["style"]["properties"]["rawtherapee"]
        self.assertIs(native["additionalProperties"], False)
        self.assertEqual(native["properties"]["profile_version"]["const"], 349)
        self.assertIs(native["properties"]["sections"]["additionalProperties"], False)


if __name__ == "__main__":
    unittest.main()
