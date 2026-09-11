from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import task_store  # noqa: E402


class TaskStoreTests(unittest.TestCase):
    def test_binds_catalog_instance_and_records_state_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = task_store.TaskStore(Path(directory) / "tasks.sqlite3")
            store.create_task("task-1", purpose="city story", input_scope={"collection_id": "10"})
            instance = store.bind_photo_instance(
                "task-1",
                catalog_binding="catalog-fingerprint",
                photo_id="123",
                asset_id="asset-sha256",
                is_virtual_copy=True,
                parent_instance_id="source-instance",
            )
            repeated = store.bind_photo_instance(
                "task-1",
                catalog_binding="catalog-fingerprint",
                photo_id="123",
                asset_id="asset-sha256",
                is_virtual_copy=True,
                parent_instance_id="source-instance",
            )
            snapshot = store.record_state_snapshot(
                "task-1",
                instance_id=instance["instance_id"],
                state={"Exposure": 0.25, "Contrast": 5},
                completeness="partial",
            )

            self.assertEqual(instance["instance_id"], repeated["instance_id"])
            self.assertTrue(instance["is_virtual_copy"])
            self.assertEqual(snapshot["state_hash"], task_store.state_fingerprint(snapshot["state"]))
            self.assertEqual(snapshot["completeness"], "partial")
            store.close()

    def test_records_task_proposal_and_immutable_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = task_store.TaskStore(Path(directory) / "tasks.sqlite3")
            store.create_task("task-1", purpose="city story", input_scope={"collection_id": "10"})
            store.save_proposal("task-1", revision=1, payload={"photo_ids": ["1", "2"]})
            approval = store.freeze_approval(
                "task-1",
                proposal_revision=1,
                members=[{"photo_id": "1", "state_hash": "abc"}],
                allowed_operations=["initial_adjustment"],
            )

            self.assertEqual(approval["proposal_revision"], 1)
            self.assertEqual(approval["members"][0]["photo_id"], "1")
            with self.assertRaises(task_store.ImmutableApprovalError):
                store.freeze_approval(
                    "task-1",
                    proposal_revision=1,
                    members=[{"photo_id": "2", "state_hash": "def"}],
                    allowed_operations=["initial_adjustment"],
                )
            store.close()

    def test_cannot_freeze_approval_for_unknown_proposal_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = task_store.TaskStore(Path(directory) / "tasks.sqlite3")
            store.create_task("task-1", purpose="city story", input_scope={"collection_id": "10"})

            with self.assertRaises(KeyError):
                store.freeze_approval(
                    "task-1",
                    proposal_revision=99,
                    members=[{"photo_id": "1", "state_hash": "abc"}],
                    allowed_operations=["initial_adjustment"],
                )
            store.close()

    def test_operation_idempotency_reuses_same_intent_and_rejects_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = task_store.TaskStore(Path(directory) / "tasks.sqlite3")
            store.create_task("task-1", purpose="portrait", input_scope={"collection_id": "10"})

            first = store.begin_operation(
                "task-1",
                idempotency_key="approval-1:photo-2:plan-3:revision-1",
                kind="apply_adjustments",
                request={"photo_id": "2", "Exposure": 0.25},
            )
            repeated = store.begin_operation(
                "task-1",
                idempotency_key="approval-1:photo-2:plan-3:revision-1",
                kind="apply_adjustments",
                request={"Exposure": 0.25, "photo_id": "2"},
            )

            self.assertEqual(first["operation_id"], repeated["operation_id"])
            self.assertEqual(repeated["status"], "pending")
            with self.assertRaises(task_store.IdempotencyConflictError):
                store.begin_operation(
                    "task-1",
                    idempotency_key="approval-1:photo-2:plan-3:revision-1",
                    kind="apply_adjustments",
                    request={"photo_id": "2", "Exposure": 0.5},
                )
            store.close()

    def test_unknown_operation_is_not_retried_as_new_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = task_store.TaskStore(Path(directory) / "tasks.sqlite3")
            store.create_task("task-1", purpose="travel", input_scope={"collection_id": "10"})
            operation = store.begin_operation(
                "task-1",
                idempotency_key="key-1",
                kind="create_virtual_copy",
                request={"source_photo_id": "9"},
            )
            store.mark_operation_unknown(operation["operation_id"], "response lost")

            repeated = store.begin_operation(
                "task-1",
                idempotency_key="key-1",
                kind="create_virtual_copy",
                request={"source_photo_id": "9"},
            )

            self.assertEqual(repeated["status"], "unknown")
            self.assertEqual(repeated["error"], "response lost")
            store.close()

    def test_completed_operation_persists_structured_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = task_store.TaskStore(Path(directory) / "tasks.sqlite3")
            store.create_task("task-1", purpose="travel", input_scope={"collection_id": "10"})
            operation = store.begin_operation(
                "task-1",
                idempotency_key="key-1",
                kind="export",
                request={"photo_id": "9"},
            )

            completed = store.complete_operation(
                operation["operation_id"],
                result={"photo_id": "9", "output": "/tmp/9.jpg", "verified": True},
            )

            self.assertEqual(completed["status"], "completed")
            self.assertTrue(completed["result"]["verified"])
            self.assertEqual(store.begin_operation(
                "task-1",
                idempotency_key="key-1",
                kind="export",
                request={"photo_id": "9"},
            )["status"], "completed")
            store.close()

    def test_state_fingerprint_is_canonical(self) -> None:
        self.assertEqual(
            task_store.state_fingerprint({"Exposure": 0.25, "Contrast": 5}),
            task_store.state_fingerprint({"Contrast": 5, "Exposure": 0.25}),
        )


if __name__ == "__main__":
    unittest.main()
