from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import benchmark_eval  # noqa: E402
import edit_intent  # noqa: E402
import preview_provider  # noqa: E402
import review_loop  # noqa: E402


class BenchmarkEvalTests(unittest.TestCase):
    def _intent(self, raw: Path) -> dict:
        return {
            "schema_version": "lumenflow.edit_intent.v2",
            "intent_id": "intent-benchmark-001",
            "revision": 1,
            "authorization": {"kind": "explicit_user_request", "reference_id": "benchmark-run"},
            "source": {"path": str(raw), "fingerprint": preview_provider.file_fingerprint(raw)},
            "preview_basis": {
                "artifact_id": "preview_" + "a" * 32,
                "starting_state_hash": "b" * 64,
                "state_completeness": "complete",
            },
            "purpose": "Travel editorial hero",
            "style": {"style_id": "clean_natural", "rationale": "Natural travel color."},
            "global_adjustments": {"exposure_ev": 0.2, "contrast": 8},
            "composition": {"decision": "no_crop", "reason": "Framing is intentional."},
            "local_adjustments": {"decision": "none", "reason": "Not needed.", "masks": []},
        }

    def _case(self, intent: dict, *, case_id: str = "case-bangkok-001") -> dict:
        return {
            "schema_version": "lumenflow.benchmark_case.v1",
            "case_id": case_id,
            "purpose": intent["purpose"],
            "source_fingerprint": intent["source"]["fingerprint"],
            "preview_basis": intent["preview_basis"],
            "target_style_id": intent["style"]["style_id"],
            "tags": ["travel", "night"],
        }

    def _successful_artifacts(self, root: Path) -> tuple[dict, dict, dict, dict, dict]:
        raw = root / "bangkok.DNG"
        raw.write_bytes(b"raw-benchmark")
        intent = self._intent(raw)
        case = self._case(intent)
        plan = edit_intent.compile_intent(intent, backend_id="rawtherapee", output_dir=root / "out")

        def runner(command: list[str], *, dry_run: bool, timeout: int | None) -> int:
            Path(command[2]).write_bytes(b"benchmark-jpeg")
            return 0

        receipt = edit_intent.execute_plan(
            plan,
            dry_run=False,
            timeout=None,
            runner=runner,
            allowed_output_dir=root / "out",
        )
        session = review_loop.start_review_session(intent)
        review = {
            "schema_version": "lumenflow.review_result.v1",
            "review_id": "review-benchmark-001",
            "intent_id": intent["intent_id"],
            "intent_revision": 1,
            "plan_id": plan["plan_id"],
            "receipt_id": receipt["receipt_id"],
            "output_fingerprint": receipt["output_fingerprint"],
            "decision": "accept",
            "summary": "The render meets the purpose.",
            "issues": [],
            "changes": {},
        }
        session = review_loop.advance_review_session(session, plan, receipt, review)["session"]
        assessment = {
            "schema_version": "lumenflow.visual_assessment.v1",
            "assessment_id": "assessment-benchmark-001",
            "case_id": case["case_id"],
            "output_fingerprint": receipt["output_fingerprint"],
            "rubric_version": "photo-edit-v1",
            "model_id": "host-vision-model",
            "scores": {
                "technical_quality": 4.5,
                "purpose_fit": 4.7,
                "style_coherence": 4.4,
                "composition": 4.3,
                "naturalness": 4.6,
            },
            "checks": {
                "highlight_detail": True,
                "shadow_detail": True,
                "color_integrity": True,
                "composition_intent": True,
                "artifacts_absent": True,
            },
            "summary": "Clean, coherent travel rendering.",
        }
        return case, plan, receipt, session, assessment

    def test_build_observation_binds_runtime_and_model_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            case, plan, receipt, session, assessment = self._successful_artifacts(Path(directory))
            observation = benchmark_eval.build_observation(
                case,
                plan,
                receipt,
                session=session,
                assessment=assessment,
                runtime_ms=1250,
            )

        self.assertEqual(observation["schema_version"], "lumenflow.benchmark_observation.v1")
        self.assertEqual(observation["backend_id"], "rawtherapee")
        self.assertEqual(observation["outcome"], "accepted")
        self.assertTrue(observation["integrity_passed"])
        self.assertEqual(observation["scores"]["purpose_fit"], 4.7)
        self.assertEqual(observation["runtime_ms"], 1250)

    def test_output_or_assessment_fingerprint_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            case, plan, receipt, session, assessment = self._successful_artifacts(Path(directory))
            assessment["output_fingerprint"] = {"sha256": "0" * 64, "size_bytes": 1}

            with self.assertRaises(benchmark_eval.BenchmarkError) as error:
                benchmark_eval.build_observation(
                    case,
                    plan,
                    receipt,
                    session=session,
                    assessment=assessment,
                    runtime_ms=100,
                )

        self.assertEqual(error.exception.code, "BENCHMARK_BINDING_MISMATCH")

    def test_failed_execution_is_counted_and_cannot_receive_visual_scores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            raw.write_bytes(b"raw-benchmark")
            intent = self._intent(raw)
            case = self._case(intent)
            plan = edit_intent.compile_intent(intent, backend_id="rawtherapee", output_dir=root / "out")

            def runner(command: list[str], *, dry_run: bool, timeout: int | None) -> int:
                raise OSError("renderer failed")

            receipt = edit_intent.execute_plan(
                plan,
                dry_run=False,
                timeout=None,
                runner=runner,
                allowed_output_dir=root / "out",
            )
            observation = benchmark_eval.build_observation(
                case,
                plan,
                receipt,
                runtime_ms=300,
            )

            with self.assertRaises(benchmark_eval.BenchmarkError):
                benchmark_eval.build_observation(
                    case,
                    plan,
                    receipt,
                    session={},
                    assessment={"scores": {"technical_quality": 5}},
                    runtime_ms=300,
                )

        self.assertEqual(observation["outcome"], "execution_failed")
        self.assertFalse(observation["integrity_passed"])
        self.assertIsNone(observation["scores"])

    def test_report_gate_cannot_hide_failure_behind_high_visual_scores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case, plan, receipt, session, assessment = self._successful_artifacts(root)
            accepted = benchmark_eval.build_observation(
                case, plan, receipt, session=session, assessment=assessment, runtime_ms=1000
            )
            failed = copy.deepcopy(accepted)
            failed["observation_id"] = "observation_" + "f" * 32
            failed["case_id"] = "case-bangkok-002"
            failed["outcome"] = "execution_failed"
            failed["integrity_passed"] = False
            failed["output_fingerprint"] = None
            failed["scores"] = None
            failed["checks"] = None
            failed["session_id"] = None
            failed["assessment_id"] = None
            failed["observation_id"] = benchmark_eval.observation_id_for(failed)

            report = benchmark_eval.build_report(
                [accepted, failed],
                minimum_cases=2,
                minimum_acceptance_rate=0.5,
                minimum_mean_score=4.0,
            )

        backend = report["backends"]["rawtherapee"]
        self.assertEqual(backend["attempted"], 2)
        self.assertEqual(backend["integrity_failures"], 1)
        self.assertFalse(backend["gate_passed"])
        self.assertFalse(report["overall_passed"])

    def test_report_rejects_score_tampering_after_observation_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            case, plan, receipt, session, assessment = self._successful_artifacts(Path(directory))
            observation = benchmark_eval.build_observation(
                case, plan, receipt, session=session, assessment=assessment, runtime_ms=1000
            )
            observation["scores"]["technical_quality"] = 5

            with self.assertRaises(benchmark_eval.BenchmarkError) as error:
                benchmark_eval.build_report([observation], minimum_cases=1)

        self.assertEqual(error.exception.code, "INVALID_BENCHMARK_CONTRACT")
        self.assertIn("content hash", error.exception.reason)

    def test_comparison_detects_quality_or_acceptance_regression(self) -> None:
        def report(acceptance_rate: float, mean_score: float, marker: str) -> dict:
            payload = {
                "schema_version": "lumenflow.benchmark_report.v1",
                "report_id": "",
                "criteria": {
                    "minimum_cases": 1,
                    "minimum_acceptance_rate": 0,
                    "minimum_mean_score": 1,
                    "minimum_check_pass_rate": 0,
                    "require_zero_integrity_failures": True,
                },
                "observation_ids": ["observation_" + marker * 32],
                "backends": {
                    "rawtherapee": {
                        "attempted": 10,
                        "accepted": int(acceptance_rate * 10),
                        "acceptance_rate": acceptance_rate,
                        "integrity_failures": 0,
                        "mean_score": mean_score,
                        "check_pass_rate": 1.0,
                        "mean_runtime_ms": 1000,
                        "mean_revisions": 0.5,
                        "gate_passed": True,
                    }
                },
                "overall_passed": True,
            }
            payload["report_id"] = benchmark_eval.report_id_for(payload)
            return payload

        baseline = report(0.9, 4.5, "a")
        candidate = report(0.8, 4.1, "b")

        comparison = benchmark_eval.compare_reports(
            candidate,
            baseline,
            maximum_acceptance_drop=0.05,
            maximum_score_drop=0.25,
        )

        self.assertFalse(comparison["passed"])
        self.assertEqual(comparison["backends"]["rawtherapee"]["acceptance_delta"], -0.1)
        self.assertEqual(comparison["backends"]["rawtherapee"]["mean_score_delta"], -0.4)

    def test_contract_schemas_are_strict_and_versioned(self) -> None:
        expected = {
            "benchmark_case.schema.json": "lumenflow.benchmark_case.v1",
            "visual_assessment.schema.json": "lumenflow.visual_assessment.v1",
            "benchmark_observation.schema.json": "lumenflow.benchmark_observation.v1",
            "benchmark_report.schema.json": "lumenflow.benchmark_report.v1",
        }
        for filename, version in expected.items():
            with self.subTest(filename=filename):
                schema = json.loads(
                    (ROOT / "knowledge" / "schemas" / filename).read_text(encoding="utf-8")
                )
                self.assertEqual(schema["properties"]["schema_version"]["const"], version)
                self.assertIs(schema["additionalProperties"], False)


if __name__ == "__main__":
    unittest.main()
