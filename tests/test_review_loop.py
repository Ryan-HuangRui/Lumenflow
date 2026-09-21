from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import edit_intent  # noqa: E402
import preview_provider  # noqa: E402
import review_loop  # noqa: E402


class ReviewLoopTests(unittest.TestCase):
    def _intent(self, raw: Path) -> dict:
        return {
            "schema_version": "lumenflow.edit_intent.v2",
            "intent_id": "intent-bangkok-review-001",
            "revision": 1,
            "authorization": {
                "kind": "user_confirmed_selection",
                "reference_id": "approval-bangkok-001",
            },
            "source": {
                "path": str(raw),
                "fingerprint": preview_provider.file_fingerprint(raw),
            },
            "preview_basis": {
                "artifact_id": "preview_" + "a" * 32,
                "starting_state_hash": "b" * 64,
                "state_completeness": "complete",
            },
            "purpose": "Bangkok travel story",
            "style": {
                "style_id": "street_light_shadow_cinematic",
                "rationale": "Keep the humid night atmosphere.",
            },
            "global_adjustments": {
                "exposure_ev": 0.2,
                "contrast": 10,
                "highlight_recovery": 20,
                "shadow_lift": 12,
            },
            "composition": {
                "decision": "no_crop",
                "reason": "The framing supports the story.",
            },
            "local_adjustments": {
                "decision": "none",
                "reason": "Global controls are sufficient.",
                "masks": [],
            },
        }

    def _execute(self, intent: dict, output_dir: Path) -> tuple[dict, dict]:
        plan = edit_intent.compile_intent(
            intent,
            backend_id="rawtherapee",
            output_dir=output_dir,
        )

        def fake_runner(command: list[str], *, dry_run: bool, timeout: int | None) -> int:
            Path(command[2]).write_bytes(f"render-{intent['revision']}".encode())
            return 0

        receipt = edit_intent.execute_plan(
            plan,
            allowed_output_dir=output_dir,
            runner=fake_runner,
            dry_run=False,
            timeout=None,
        )
        return plan, receipt

    def _review(
        self,
        intent: dict,
        plan: dict,
        receipt: dict,
        *,
        decision: str,
        review_id: str = "review_bangkok_001",
        changes: dict | None = None,
    ) -> dict:
        issues = []
        if decision != "accept":
            issues = [
                {
                    "category": "exposure",
                    "severity": "major",
                    "observation": "The subject remains too dark.",
                    "recommendation": "Lift exposure without losing highlights.",
                }
            ]
        return {
            "schema_version": "lumenflow.review_result.v1",
            "review_id": review_id,
            "intent_id": intent["intent_id"],
            "intent_revision": intent["revision"],
            "plan_id": plan["plan_id"],
            "receipt_id": receipt["receipt_id"],
            "output_fingerprint": receipt["output_fingerprint"],
            "decision": decision,
            "summary": "Rendered output review completed.",
            "issues": issues,
            "changes": changes or {},
        }

    def test_accept_binds_verified_output_and_closes_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            raw.write_bytes(b"raw")
            intent = self._intent(raw)
            plan, receipt = self._execute(intent, root / "output")
            session = review_loop.start_review_session(intent, max_revisions=2)
            review = self._review(intent, plan, receipt, decision="accept")

            transition = review_loop.advance_review_session(session, plan, receipt, review)

        self.assertEqual(transition["session"]["status"], "accepted")
        self.assertIsNone(transition["next_intent"])
        self.assertEqual(transition["session"]["seen_review_ids"], ["review_bangkok_001"])
        self.assertEqual(transition["session"]["history"][0]["decision"], "accept")

    def test_revise_changes_only_editable_fields_and_increments_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            raw.write_bytes(b"raw")
            intent = self._intent(raw)
            plan, receipt = self._execute(intent, root / "output")
            session = review_loop.start_review_session(intent, max_revisions=2)
            review = self._review(
                intent,
                plan,
                receipt,
                decision="revise",
                changes={
                    "global_adjustments": {
                        "exposure_ev": 0.45,
                        "contrast": 8,
                        "highlight_recovery": 26,
                        "shadow_lift": 18,
                    }
                },
            )

            transition = review_loop.advance_review_session(session, plan, receipt, review)

        revised = transition["next_intent"]
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(revised["global_adjustments"]["exposure_ev"], 0.45)
        self.assertEqual(revised["source"], intent["source"])
        self.assertEqual(revised["authorization"], intent["authorization"])
        self.assertEqual(transition["session"]["revisions_used"], 1)
        self.assertEqual(transition["session"]["status"], "active")

    def test_dry_run_or_tampered_receipt_cannot_be_reviewed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            raw.write_bytes(b"raw")
            intent = self._intent(raw)
            plan = edit_intent.compile_intent(
                intent,
                backend_id="rawtherapee",
                output_dir=root / "output",
            )
            receipt = edit_intent.execute_plan(
                plan,
                allowed_output_dir=root / "output",
                dry_run=True,
                timeout=None,
            )
            session = review_loop.start_review_session(intent)
            review = self._review(intent, plan, receipt, decision="accept")

            with self.assertRaises(review_loop.ReviewLoopError) as error:
                review_loop.advance_review_session(session, plan, receipt, review)

        self.assertEqual(error.exception.code, "REVIEW_RECEIPT_NOT_VERIFIED")

    def test_review_binding_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            raw.write_bytes(b"raw")
            intent = self._intent(raw)
            plan, receipt = self._execute(intent, root / "output")
            review = self._review(intent, plan, receipt, decision="accept")
            review["plan_id"] = "plan_" + "0" * 32

            with self.assertRaises(review_loop.ReviewLoopError) as error:
                review_loop.advance_review_session(
                    review_loop.start_review_session(intent),
                    plan,
                    receipt,
                    review,
                )

        self.assertEqual(error.exception.code, "REVIEW_BINDING_MISMATCH")

    def test_output_drift_after_receipt_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            raw.write_bytes(b"raw")
            intent = self._intent(raw)
            plan, receipt = self._execute(intent, root / "output")
            review = self._review(intent, plan, receipt, decision="accept")
            Path(plan["artifacts"]["output"]["path"]).write_bytes(b"replaced-after-receipt")

            with self.assertRaises(review_loop.ReviewLoopError) as error:
                review_loop.advance_review_session(
                    review_loop.start_review_session(intent),
                    plan,
                    receipt,
                    review,
                )

        self.assertEqual(error.exception.code, "REVIEW_OUTPUT_DRIFT")

    def test_revision_limit_stops_third_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            raw.write_bytes(b"raw")
            intent = self._intent(raw)
            session = review_loop.start_review_session(intent, max_revisions=2)

            for index, exposure in enumerate((0.3, 0.4), start=1):
                plan, receipt = self._execute(intent, root / "output")
                review = self._review(
                    intent,
                    plan,
                    receipt,
                    decision="revise",
                    review_id=f"review_bangkok_00{index}",
                    changes={"global_adjustments": {**intent["global_adjustments"], "exposure_ev": exposure}},
                )
                transition = review_loop.advance_review_session(session, plan, receipt, review)
                session = transition["session"]
                intent = transition["next_intent"]

            plan, receipt = self._execute(intent, root / "output")
            review = self._review(
                intent,
                plan,
                receipt,
                decision="revise",
                review_id="review_bangkok_003",
                changes={"global_adjustments": {**intent["global_adjustments"], "exposure_ev": 0.5}},
            )
            transition = review_loop.advance_review_session(session, plan, receipt, review)

        self.assertEqual(transition["session"]["status"], "revision_limit_reached")
        self.assertIsNone(transition["next_intent"])
        self.assertEqual(transition["session"]["revisions_used"], 2)

    def test_noop_revisions_and_reused_review_ids_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            raw.write_bytes(b"raw")
            intent = self._intent(raw)
            plan, receipt = self._execute(intent, root / "output")
            session = review_loop.start_review_session(intent)
            review = self._review(
                intent,
                plan,
                receipt,
                decision="revise",
                changes={"global_adjustments": copy.deepcopy(intent["global_adjustments"])},
            )

            with self.assertRaises(review_loop.ReviewLoopError) as noop_error:
                review_loop.advance_review_session(session, plan, receipt, review)

            valid_revision = self._review(
                intent,
                plan,
                receipt,
                decision="revise",
                changes={"global_adjustments": {**intent["global_adjustments"], "exposure_ev": 0.3}},
            )
            transition = review_loop.advance_review_session(
                session,
                plan,
                receipt,
                valid_revision,
            )
            revised = transition["next_intent"]
            next_plan, next_receipt = self._execute(revised, root / "output")
            reused = self._review(
                revised,
                next_plan,
                next_receipt,
                decision="accept",
                review_id=valid_revision["review_id"],
            )
            with self.assertRaises(review_loop.ReviewLoopError) as reused_error:
                review_loop.advance_review_session(
                    transition["session"],
                    next_plan,
                    next_receipt,
                    reused,
                )

        self.assertEqual(noop_error.exception.code, "REVIEW_NO_EFFECT")
        self.assertEqual(reused_error.exception.code, "REVIEW_ALREADY_APPLIED")

    def test_session_state_cannot_be_tampered_to_reset_revision_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "bangkok.DNG"
            raw.write_bytes(b"raw")
            intent = self._intent(raw)
            session = review_loop.start_review_session(intent, max_revisions=2)
            session["revisions_used"] = 1

            with self.assertRaises(review_loop.ReviewLoopError) as error:
                review_loop.advance_review_session(session, {}, {}, {})

        self.assertEqual(error.exception.code, "INVALID_REVIEW_SESSION")

    def test_revision_cannot_cycle_back_to_an_earlier_intent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "bangkok.DNG"
            raw.write_bytes(b"raw")
            original = self._intent(raw)
            plan, receipt = self._execute(original, root / "output")
            first_review = self._review(
                original,
                plan,
                receipt,
                decision="revise",
                changes={"global_adjustments": {**original["global_adjustments"], "exposure_ev": 0.3}},
            )
            transition = review_loop.advance_review_session(
                review_loop.start_review_session(original),
                plan,
                receipt,
                first_review,
            )
            revised = transition["next_intent"]
            next_plan, next_receipt = self._execute(revised, root / "output")
            cycle_review = self._review(
                revised,
                next_plan,
                next_receipt,
                decision="revise",
                review_id="review_bangkok_002",
                changes={"global_adjustments": original["global_adjustments"]},
            )

            with self.assertRaises(review_loop.ReviewLoopError) as error:
                review_loop.advance_review_session(
                    transition["session"],
                    next_plan,
                    next_receipt,
                    cycle_review,
                )

        self.assertEqual(error.exception.code, "REVIEW_CYCLE_DETECTED")

    def test_contract_schemas_are_strict_and_versioned(self) -> None:
        review_schema = json.loads(
            (ROOT / "knowledge" / "schemas" / "review_result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        session_schema = json.loads(
            (ROOT / "knowledge" / "schemas" / "review_session.schema.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            review_schema["properties"]["schema_version"]["const"],
            "lumenflow.review_result.v1",
        )
        self.assertEqual(
            session_schema["properties"]["schema_version"]["const"],
            "lumenflow.review_session.v1",
        )
        self.assertIs(review_schema["additionalProperties"], False)
        self.assertIs(session_schema["additionalProperties"], False)


if __name__ == "__main__":
    unittest.main()
