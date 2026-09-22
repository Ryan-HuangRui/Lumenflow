"""Privacy-minimized store of user-accepted photo edit examples."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..core import edit_intent, preview, review


PERSONAL_EXAMPLE_VERSION = "lumenflow.personal_edit_example.v1"
MAX_EXAMPLE_BYTES = 1024 * 1024


class ExampleStoreError(RuntimeError):
    def __init__(self, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def example_id_for(example: dict[str, Any]) -> str:
    content = copy.deepcopy(example)
    for field in ("schema_version", "example_id", "created_at"):
        content.pop(field, None)
    digest = hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()
    return "edit_example_" + digest[:32]


def _normalize_tags(tags: list[str]) -> list[str]:
    if not isinstance(tags, list) or len(tags) > 20:
        raise ExampleStoreError("INVALID_EXAMPLE", "tags must contain at most 20 strings")
    normalized: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            raise ExampleStoreError("INVALID_EXAMPLE", "tags must contain strings")
        value = " ".join(tag.strip().lower().split())
        if not value or len(value) > 64 or any(ord(character) < 32 for character in value):
            raise ExampleStoreError(
                "INVALID_EXAMPLE", "tag is empty, too long, or contains control text"
            )
        normalized.append(value)
    return sorted(set(normalized))


def _validate_fingerprint(value: Any, name: str) -> None:
    if not isinstance(value, dict) or set(value) != {"sha256", "size_bytes"}:
        raise ExampleStoreError("INVALID_EXAMPLE", f"{name} is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(value["sha256"])):
        raise ExampleStoreError("INVALID_EXAMPLE", f"{name}.sha256 is invalid")
    size = value["size_bytes"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ExampleStoreError("INVALID_EXAMPLE", f"{name}.size_bytes is invalid")


def validate_personal_example(example: dict[str, Any]) -> None:
    fields = {
        "schema_version",
        "example_id",
        "intent_id",
        "intent_revision",
        "backend_id",
        "source_fingerprint",
        "preview_basis",
        "output_fingerprint",
        "purpose",
        "style",
        "global_adjustments",
        "composition",
        "local_adjustments",
        "tags",
        "plan_id",
        "receipt_id",
        "session_id",
        "accepted_review_id",
        "created_at",
    }
    if not isinstance(example, dict) or set(example) != fields:
        raise ExampleStoreError("INVALID_EXAMPLE", "Personal edit example fields are invalid")
    if example["schema_version"] != PERSONAL_EXAMPLE_VERSION:
        raise ExampleStoreError("INVALID_EXAMPLE", "Unsupported personal example version")
    if example["example_id"] != example_id_for(example):
        raise ExampleStoreError("INVALID_EXAMPLE", "example content hash is invalid")
    identity_patterns = {
        "intent_id": r"[A-Za-z0-9_.-]+",
        "plan_id": r"plan_[0-9a-f]{32}",
        "receipt_id": r"receipt_[0-9a-f]{32}",
        "session_id": r"review_session_[0-9a-f]{32}",
        "accepted_review_id": r"[A-Za-z0-9_.-]+",
    }
    if any(
        not re.fullmatch(pattern, str(example[field]))
        for field, pattern in identity_patterns.items()
    ):
        raise ExampleStoreError("INVALID_EXAMPLE", "example evidence identity is invalid")
    if (
        isinstance(example["intent_revision"], bool)
        or not isinstance(example["intent_revision"], int)
        or example["intent_revision"] < 1
    ):
        raise ExampleStoreError("INVALID_EXAMPLE", "intent_revision is invalid")
    if example["backend_id"] not in {"rawtherapee", "darktable", "lightroom"}:
        raise ExampleStoreError("INVALID_EXAMPLE", "backend_id is invalid")
    _validate_fingerprint(example["source_fingerprint"], "source_fingerprint")
    _validate_fingerprint(example["output_fingerprint"], "output_fingerprint")
    if example["tags"] != _normalize_tags(example["tags"]):
        raise ExampleStoreError("INVALID_EXAMPLE", "tags must be normalized and unique")
    try:
        edit_intent.validate_edit_intent(
            {
                "schema_version": edit_intent.EDIT_INTENT_SCHEMA_VERSION,
                "intent_id": example["intent_id"],
                "revision": example["intent_revision"],
                "authorization": {
                    "kind": "explicit_user_request",
                    "reference_id": "redacted",
                },
                "source": {
                    "path": "/redacted/source.DNG",
                    "fingerprint": example["source_fingerprint"],
                },
                "preview_basis": example["preview_basis"],
                "purpose": example["purpose"],
                "style": example["style"],
                "global_adjustments": example["global_adjustments"],
                "composition": example["composition"],
                "local_adjustments": example["local_adjustments"],
            }
        )
    except edit_intent.IntentValidationError as error:
        raise ExampleStoreError("INVALID_EXAMPLE", str(error)) from error
    try:
        created_at = datetime.fromisoformat(str(example["created_at"]).replace("Z", "+00:00"))
    except ValueError:
        raise ExampleStoreError("INVALID_EXAMPLE", "created_at is invalid") from None
    if created_at.tzinfo is None:
        raise ExampleStoreError("INVALID_EXAMPLE", "created_at must include a timezone")
    if len(_canonical_json(example).encode("utf-8")) > MAX_EXAMPLE_BYTES:
        raise ExampleStoreError("INVALID_EXAMPLE", "example exceeds the storage size limit")


def _verify_output(plan: dict[str, Any], receipt: dict[str, Any]) -> None:
    try:
        output_root = Path(plan["output_root"]).resolve()
        output = Path(plan["artifacts"]["output"]["path"])
        output.resolve().relative_to(output_root)
    except (KeyError, TypeError, ValueError):
        raise ExampleStoreError(
            "EXAMPLE_BINDING_MISMATCH", "Output path is outside its root"
        ) from None
    if output.is_symlink() or not output.is_file() or output.stat().st_size > 512 * 1024 * 1024:
        raise ExampleStoreError("EXAMPLE_OUTPUT_DRIFT", "Accepted output is missing or unsafe")
    if preview.file_fingerprint(output) != receipt.get("output_fingerprint"):
        raise ExampleStoreError(
            "EXAMPLE_OUTPUT_DRIFT", "Accepted output no longer matches its receipt"
        )


def build_personal_example(
    session: dict[str, Any],
    plan: dict[str, Any],
    receipt: dict[str, Any],
    *,
    tags: list[str],
) -> dict[str, Any]:
    try:
        review.validate_review_session(session)
    except review.ReviewLoopError as error:
        raise ExampleStoreError("INVALID_REVIEW_SESSION", str(error)) from error
    if session["status"] != "accepted":
        raise ExampleStoreError("EXAMPLE_NOT_ACCEPTED", "Only an accepted final edit may be stored")
    intent = session["current_intent"]
    history = session["history"]
    if (
        plan.get("schema_version") != edit_intent.EXECUTION_PLAN_SCHEMA_VERSION
        or plan.get("intent_id") != intent["intent_id"]
        or plan.get("intent_revision") != intent["revision"]
        or plan.get("source") != intent["source"]
        or plan.get("preview_basis") != intent["preview_basis"]
        or receipt.get("schema_version") != edit_intent.EXECUTION_RECEIPT_SCHEMA_VERSION
        or receipt.get("status") != "success"
        or receipt.get("source_unchanged") is not True
        or receipt.get("output_fingerprint") is None
        or receipt.get("plan_id") != plan.get("plan_id")
        or receipt.get("intent_id") != intent["intent_id"]
        or receipt.get("backend_id") != plan.get("backend", {}).get("id")
        or not history
        or history[-1]["receipt_id"] != receipt.get("receipt_id")
        or history[-1]["decision"] != "accept"
    ):
        raise ExampleStoreError(
            "EXAMPLE_BINDING_MISMATCH",
            "Session, intent, plan, and receipt do not describe the same accepted edit",
        )
    _verify_output(plan, receipt)
    example = {
        "schema_version": PERSONAL_EXAMPLE_VERSION,
        "example_id": "",
        "intent_id": intent["intent_id"],
        "intent_revision": intent["revision"],
        "backend_id": plan["backend"]["id"],
        "source_fingerprint": copy.deepcopy(intent["source"]["fingerprint"]),
        "preview_basis": copy.deepcopy(intent["preview_basis"]),
        "output_fingerprint": copy.deepcopy(receipt["output_fingerprint"]),
        "purpose": intent["purpose"],
        "style": copy.deepcopy(intent["style"]),
        "global_adjustments": copy.deepcopy(intent["global_adjustments"]),
        "composition": copy.deepcopy(intent["composition"]),
        "local_adjustments": copy.deepcopy(intent["local_adjustments"]),
        "tags": _normalize_tags(tags),
        "plan_id": plan["plan_id"],
        "receipt_id": receipt["receipt_id"],
        "session_id": session["session_id"],
        "accepted_review_id": history[-1]["review_id"],
        "created_at": _now(),
    }
    example["example_id"] = example_id_for(example)
    validate_personal_example(example)
    return example


def _semantic_example(example: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(example)
    payload.pop("created_at", None)
    return payload


class PersonalExampleStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ExampleStoreError("UNSAFE_STORE_PATH", "Store path must not be a symbolic link")
        if self.path.exists() and not self.path.is_file():
            raise ExampleStoreError("UNSAFE_STORE_PATH", "Store path must be a regular file")
        parent_existed = self.path.parent.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not parent_existed:
            os.chmod(self.path.parent, 0o700)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self.connection.execute("PRAGMA secure_delete = ON")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS personal_edit_examples (
                example_id TEXT PRIMARY KEY,
                schema_version TEXT NOT NULL,
                purpose TEXT NOT NULL,
                style_id TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self.connection.commit()
        os.chmod(self.path, 0o600)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "PersonalExampleStore":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        value = json.loads(row["payload_json"])
        validate_personal_example(value)
        return value

    def add(self, example: dict[str, Any]) -> dict[str, Any]:
        validate_personal_example(example)
        existing = self.connection.execute(
            "SELECT * FROM personal_edit_examples WHERE example_id = ?",
            (example["example_id"],),
        ).fetchone()
        if existing is not None:
            stored = self._decode(existing)
            if _semantic_example(stored) != _semantic_example(example):
                raise ExampleStoreError(
                    "EXAMPLE_ID_CONFLICT", "example_id is bound to other content"
                )
            return stored
        self.connection.execute(
            """
            INSERT INTO personal_edit_examples
            (example_id, schema_version, purpose, style_id, tags_json, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                example["example_id"],
                example["schema_version"],
                example["purpose"],
                example["style"]["style_id"],
                _canonical_json(example["tags"]),
                _canonical_json(example),
                example["created_at"],
            ),
        )
        self.connection.commit()
        return copy.deepcopy(example)

    def list_examples(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ExampleStoreError("INVALID_QUERY", "limit must be between 1 and 100")
        rows = self.connection.execute(
            "SELECT * FROM personal_edit_examples ORDER BY created_at DESC, example_id ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._decode(row) for row in rows]

    def search(
        self,
        *,
        purpose: str = "",
        tags: list[str] | None = None,
        style_id: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise ExampleStoreError("INVALID_QUERY", "search limit must be between 1 and 20")
        query_tags = set(_normalize_tags(tags or []))
        query_terms = set(re.findall(r"\w+", purpose.lower(), flags=re.UNICODE))
        normalized_style = style_id.strip() if isinstance(style_id, str) else ""
        if not query_terms and not query_tags and not normalized_style:
            raise ExampleStoreError(
                "INVALID_QUERY", "purpose, tags, or style_id is required"
            )
        matches: list[dict[str, Any]] = []
        for row in self.connection.execute("SELECT * FROM personal_edit_examples").fetchall():
            example = self._decode(row)
            example_terms = set(
                re.findall(r"\w+", example["purpose"].lower(), flags=re.UNICODE)
            )
            purpose_terms = sorted(query_terms & example_terms)
            matched_tags = sorted(query_tags & set(example["tags"]))
            style_match = bool(
                normalized_style and normalized_style == example["style"]["style_id"]
            )
            score = 0.0
            if query_terms:
                score += 3 * len(purpose_terms) / len(query_terms)
            if query_tags:
                score += 2 * len(matched_tags) / len(query_tags)
            if style_match:
                score += 3
            if score > 0:
                matches.append(
                    {
                        "schema_version": "lumenflow.personal_edit_example_match.v1",
                        "retrieval_score": round(score, 4),
                        "matched": {
                            "purpose_terms": purpose_terms,
                            "tags": matched_tags,
                            "style": style_match,
                        },
                        "example": example,
                    }
                )
        matches.sort(
            key=lambda item: (-item["retrieval_score"], item["example"]["example_id"])
        )
        return matches[:limit]

    def remove(self, example_id: str) -> bool:
        if not re.fullmatch(r"edit_example_[0-9a-f]{32}", str(example_id)):
            raise ExampleStoreError("INVALID_QUERY", "example_id is invalid")
        cursor = self.connection.execute(
            "DELETE FROM personal_edit_examples WHERE example_id = ?", (example_id,)
        )
        self.connection.commit()
        return cursor.rowcount > 0
