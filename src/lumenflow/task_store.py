"""Small local state store for safe, resumable Lumenflow tasks."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self


class ImmutableApprovalError(RuntimeError):
    """Raised when code attempts to replace a frozen approval revision."""


class IdempotencyConflictError(RuntimeError):
    """Raised when an idempotency key is reused for a different intent."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def state_fingerprint(state: dict[str, Any]) -> str:
    return hashlib.sha256(_json(state).encode("utf-8")).hexdigest()


class TaskStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                purpose TEXT NOT NULL,
                input_scope_json TEXT NOT NULL,
                stage TEXT NOT NULL,
                revision INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS proposals (
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                revision INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (task_id, revision)
            );
            CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                proposal_revision INTEGER NOT NULL,
                members_json TEXT NOT NULL,
                allowed_operations_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                invalidated_at TEXT,
                UNIQUE (task_id, proposal_revision)
            );
            CREATE TABLE IF NOT EXISTS photo_instances (
                instance_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                catalog_binding TEXT NOT NULL,
                photo_id TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                is_virtual_copy INTEGER NOT NULL,
                parent_instance_id TEXT,
                created_at TEXT NOT NULL,
                UNIQUE (task_id, catalog_binding, photo_id)
            );
            CREATE TABLE IF NOT EXISTS state_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                instance_id TEXT NOT NULL REFERENCES photo_instances(instance_id),
                state_json TEXT NOT NULL,
                state_hash TEXT NOT NULL,
                completeness TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS operations (
                operation_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                idempotency_key TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL,
                request_json TEXT NOT NULL,
                status TEXT NOT NULL,
                result_json TEXT,
                error TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def bind_photo_instance(
        self,
        task_id: str,
        *,
        catalog_binding: str,
        photo_id: str,
        asset_id: str,
        is_virtual_copy: bool,
        parent_instance_id: str | None = None,
    ) -> dict[str, Any]:
        existing = self.connection.execute(
            """SELECT * FROM photo_instances
               WHERE task_id = ? AND catalog_binding = ? AND photo_id = ?""",
            (task_id, catalog_binding, photo_id),
        ).fetchone()
        if existing is not None:
            expected = (asset_id, int(is_virtual_copy), parent_instance_id)
            actual = (existing["asset_id"], existing["is_virtual_copy"], existing["parent_instance_id"])
            if actual != expected:
                raise IdempotencyConflictError(
                    f"Photo {photo_id} in catalog {catalog_binding} is already bound to another identity"
                )
            return self._photo_instance(existing)

        instance_id = str(uuid.uuid4())
        self.connection.execute(
            """INSERT INTO photo_instances
               (instance_id, task_id, catalog_binding, photo_id, asset_id,
                is_virtual_copy, parent_instance_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                instance_id,
                task_id,
                catalog_binding,
                photo_id,
                asset_id,
                int(is_virtual_copy),
                parent_instance_id,
                _now(),
            ),
        )
        self.connection.commit()
        row = self.connection.execute(
            "SELECT * FROM photo_instances WHERE instance_id = ?", (instance_id,)
        ).fetchone()
        assert row is not None
        return self._photo_instance(row)

    def record_state_snapshot(
        self,
        task_id: str,
        *,
        instance_id: str,
        state: dict[str, Any],
        completeness: str,
    ) -> dict[str, Any]:
        if completeness not in {"complete", "partial"}:
            raise ValueError("Snapshot completeness must be 'complete' or 'partial'")
        snapshot_id = str(uuid.uuid4())
        created_at = _now()
        fingerprint = state_fingerprint(state)
        self.connection.execute(
            """INSERT INTO state_snapshots
               (snapshot_id, task_id, instance_id, state_json, state_hash, completeness, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (snapshot_id, task_id, instance_id, _json(state), fingerprint, completeness, created_at),
        )
        self.connection.commit()
        return {
            "snapshot_id": snapshot_id,
            "task_id": task_id,
            "instance_id": instance_id,
            "state": state,
            "state_hash": fingerprint,
            "completeness": completeness,
            "created_at": created_at,
        }

    def create_task(self, task_id: str, *, purpose: str, input_scope: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        self.connection.execute(
            """INSERT INTO tasks
               (task_id, purpose, input_scope_json, stage, revision, created_at, updated_at)
               VALUES (?, ?, ?, 'draft', 1, ?, ?)""",
            (task_id, purpose, _json(input_scope), now, now),
        )
        self.connection.commit()
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return {
            "task_id": row["task_id"],
            "purpose": row["purpose"],
            "input_scope": json.loads(row["input_scope_json"]),
            "stage": row["stage"],
            "revision": row["revision"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def save_proposal(self, task_id: str, *, revision: int, payload: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO proposals (task_id, revision, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (task_id, revision, _json(payload), _now()),
        )
        self.connection.commit()

    def freeze_approval(
        self,
        task_id: str,
        *,
        proposal_revision: int,
        members: list[dict[str, Any]],
        allowed_operations: list[str],
    ) -> dict[str, Any]:
        proposal = self.connection.execute(
            "SELECT 1 FROM proposals WHERE task_id = ? AND revision = ?",
            (task_id, proposal_revision),
        ).fetchone()
        if proposal is None:
            raise KeyError(f"Unknown proposal revision {proposal_revision} for task {task_id}")
        existing = self.connection.execute(
            "SELECT approval_id FROM approvals WHERE task_id = ? AND proposal_revision = ?",
            (task_id, proposal_revision),
        ).fetchone()
        if existing is not None:
            raise ImmutableApprovalError(
                f"Approval for task {task_id} proposal revision {proposal_revision} is already frozen"
            )
        approval_id = str(uuid.uuid4())
        created_at = _now()
        self.connection.execute(
            """INSERT INTO approvals
               (approval_id, task_id, proposal_revision, members_json, allowed_operations_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (approval_id, task_id, proposal_revision, _json(members), _json(allowed_operations), created_at),
        )
        self.connection.commit()
        return {
            "approval_id": approval_id,
            "task_id": task_id,
            "proposal_revision": proposal_revision,
            "members": members,
            "allowed_operations": allowed_operations,
            "created_at": created_at,
            "invalidated_at": None,
        }

    def begin_operation(
        self,
        task_id: str,
        *,
        idempotency_key: str,
        kind: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        request_json = _json(request)
        existing = self.connection.execute(
            "SELECT * FROM operations WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        if existing is not None:
            if existing["task_id"] != task_id or existing["kind"] != kind or existing["request_json"] != request_json:
                raise IdempotencyConflictError(f"Idempotency key {idempotency_key} is bound to another intent")
            return self._operation(existing)

        operation_id = str(uuid.uuid4())
        now = _now()
        self.connection.execute(
            """INSERT INTO operations
               (operation_id, task_id, idempotency_key, kind, request_json, status, error, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'pending', '', ?, ?)""",
            (operation_id, task_id, idempotency_key, kind, request_json, now, now),
        )
        self.connection.commit()
        return self.get_operation(operation_id)

    def get_operation(self, operation_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
        ).fetchone()
        if row is None:
            raise KeyError(operation_id)
        return self._operation(row)

    def mark_operation_unknown(self, operation_id: str, error: str) -> dict[str, Any]:
        self.connection.execute(
            "UPDATE operations SET status = 'unknown', error = ?, updated_at = ? WHERE operation_id = ?",
            (error, _now(), operation_id),
        )
        self.connection.commit()
        return self.get_operation(operation_id)

    def complete_operation(self, operation_id: str, *, result: dict[str, Any]) -> dict[str, Any]:
        current = self.get_operation(operation_id)
        if current["status"] == "completed":
            if current["result"] != result:
                raise IdempotencyConflictError(f"Operation {operation_id} already has a different result")
            return current
        self.connection.execute(
            """UPDATE operations
               SET status = 'completed', result_json = ?, error = '', updated_at = ?
               WHERE operation_id = ?""",
            (_json(result), _now(), operation_id),
        )
        self.connection.commit()
        return self.get_operation(operation_id)

    @staticmethod
    def _photo_instance(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "instance_id": row["instance_id"],
            "task_id": row["task_id"],
            "catalog_binding": row["catalog_binding"],
            "photo_id": row["photo_id"],
            "asset_id": row["asset_id"],
            "is_virtual_copy": bool(row["is_virtual_copy"]),
            "parent_instance_id": row["parent_instance_id"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _operation(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "operation_id": row["operation_id"],
            "task_id": row["task_id"],
            "idempotency_key": row["idempotency_key"],
            "kind": row["kind"],
            "request": json.loads(row["request_json"]),
            "status": row["status"],
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
