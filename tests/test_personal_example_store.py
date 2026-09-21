from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import edit_intent  # noqa: E402
import personal_example_store  # noqa: E402
import preview_provider  # noqa: E402
import review_loop  # noqa: E402


class PersonalExampleStoreTests(unittest.TestCase):
    def _accepted_artifacts(
        self,
        root: Path,
        *,
        marker: str = "001",
        purpose: str = "Bangkok travel story",
        style_id: str = "clean_natural",
    ) -> tuple[dict, dict, dict]:
        raw = root / f"bangkok-{marker}.DNG"
        raw.write_bytes(f"raw-{marker}".encode())
        intent = {
            "schema_version": "lumenflow.edit_intent.v2",
            "intent_id": f"intent-example-{marker}",
            "revision": 1,
            "authorization": {"kind": "explicit_user_request", "reference_id": "example-test"},
            "source": {"path": str(raw), "fingerprint": preview_provider.file_fingerprint(raw)},
            "preview_basis": {
                "artifact_id": "preview_" + marker[-1] * 32,
                "starting_state_hash": marker[-1] * 64,
                "state_completeness": "complete",
            },
            "purpose": purpose,
            "style": {"style_id": style_id, "rationale": "Fits the scene and purpose."},
            "global_adjustments": {"exposure_ev": 0.25, "contrast": 8, "saturation": -2},
            "composition": {"decision": "no_crop", "reason": "Keep the environmental context."},
            "local_adjustments": {"decision": "none", "reason": "Global edit is sufficient.", "masks": []},
        }
        output_dir = root / f"output-{marker}"
        plan = edit_intent.compile_intent(intent, backend_id="rawtherapee", output_dir=output_dir)

        def runner(command: list[str], *, dry_run: bool, timeout: int | None) -> int:
            Path(command[2]).write_bytes(f"jpeg-{marker}".encode())
            return 0

        receipt = edit_intent.execute_plan(
            plan,
            dry_run=False,
            timeout=None,
            runner=runner,
            allowed_output_dir=output_dir,
        )
        review = {
            "schema_version": "lumenflow.review_result.v1",
            "review_id": f"review-example-{marker}",
            "intent_id": intent["intent_id"],
            "intent_revision": 1,
            "plan_id": plan["plan_id"],
            "receipt_id": receipt["receipt_id"],
            "output_fingerprint": receipt["output_fingerprint"],
            "decision": "accept",
            "summary": "Accepted as a useful personal reference.",
            "issues": [],
            "changes": {},
        }
        session = review_loop.start_review_session(intent)
        session = review_loop.advance_review_session(session, plan, receipt, review)["session"]
        return session, plan, receipt

    def test_build_example_requires_accepted_evidence_and_redacts_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, plan, receipt = self._accepted_artifacts(root)
            example = personal_example_store.build_personal_example(
                session,
                plan,
                receipt,
                tags=["travel", "night", "Bangkok"],
            )

        serialized = json.dumps(example, ensure_ascii=False)
        self.assertEqual(example["schema_version"], "lumenflow.personal_edit_example.v1")
        self.assertEqual(example["accepted_review_id"], "review-example-001")
        self.assertEqual(example["tags"], ["bangkok", "night", "travel"])
        self.assertNotIn("bangkok-001.DNG", serialized)
        self.assertNotIn("output-001", serialized)
        self.assertNotIn("authorization", example)

    def test_active_or_nonaccepted_session_cannot_enter_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, plan, receipt = self._accepted_artifacts(root)
            session["status"] = "rejected"
            session["history"][-1]["decision"] = "reject"

            with self.assertRaises(personal_example_store.ExampleStoreError) as error:
                personal_example_store.build_personal_example(session, plan, receipt, tags=[])

        self.assertEqual(error.exception.code, "EXAMPLE_NOT_ACCEPTED")

    def test_output_drift_blocks_example_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session, plan, receipt = self._accepted_artifacts(root)
            Path(plan["artifacts"]["output"]["path"]).write_bytes(b"changed")

            with self.assertRaises(personal_example_store.ExampleStoreError) as error:
                personal_example_store.build_personal_example(session, plan, receipt, tags=[])

        self.assertEqual(error.exception.code, "EXAMPLE_OUTPUT_DRIFT")

    def test_store_is_private_idempotent_searchable_and_removable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session1, plan1, receipt1 = self._accepted_artifacts(
                root,
                marker="001",
                purpose="Bangkok night market travel story",
                style_id="clean_natural",
            )
            session2, plan2, receipt2 = self._accepted_artifacts(
                root,
                marker="002",
                purpose="Daylight family portrait",
                style_id="soft_portrait",
            )
            first = personal_example_store.build_personal_example(
                session1, plan1, receipt1, tags=["bangkok", "night", "market"]
            )
            second = personal_example_store.build_personal_example(
                session2, plan2, receipt2, tags=["portrait", "daylight"]
            )
            database = root / "private" / "examples.sqlite3"

            with personal_example_store.PersonalExampleStore(database) as store:
                stored = store.add(first)
                repeated = store.add(first)
                store.add(second)
                matches = store.search(
                    purpose="Bangkok night travel",
                    tags=["market", "night"],
                    style_id="clean_natural",
                    limit=5,
                )
                listed = store.list_examples(limit=10)
                removed = store.remove(first["example_id"])
                remaining = store.list_examples(limit=10)

            mode = stat.S_IMODE(os.stat(database).st_mode)

        self.assertEqual(stored["example_id"], repeated["example_id"])
        self.assertEqual(matches[0]["example"]["example_id"], first["example_id"])
        self.assertTrue(matches[0]["matched"]["style"])
        self.assertEqual(matches[0]["matched"]["tags"], ["market", "night"])
        self.assertEqual(len(listed), 2)
        self.assertTrue(removed)
        self.assertEqual([item["example_id"] for item in remaining], [second["example_id"]])
        self.assertEqual(mode & 0o077, 0)

    def test_search_requires_a_signal_and_caps_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with personal_example_store.PersonalExampleStore(
                Path(directory) / "examples.sqlite3"
            ) as store:
                with self.assertRaises(personal_example_store.ExampleStoreError):
                    store.search(purpose="", tags=[], style_id=None)
                with self.assertRaises(personal_example_store.ExampleStoreError):
                    store.search(purpose="travel", tags=[], style_id=None, limit=100)

    def test_contract_schema_is_strict_and_versioned(self) -> None:
        schema = json.loads(
            (ROOT / "knowledge" / "schemas" / "personal_edit_example.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            schema["properties"]["schema_version"]["const"],
            "lumenflow.personal_edit_example.v1",
        )
        self.assertIs(schema["additionalProperties"], False)


if __name__ == "__main__":
    unittest.main()
