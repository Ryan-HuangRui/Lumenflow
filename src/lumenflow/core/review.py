#!/usr/bin/env python3
"""Bind visual review to verified renders and advance a bounded edit loop."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from . import edit_intent
from . import preview as preview_provider

REVIEW_RESULT_SCHEMA_VERSION = "lumenflow.review_result.v1"
REVIEW_SESSION_SCHEMA_VERSION = "lumenflow.review_session.v1"
EDITABLE_INTENT_FIELDS = {
    "style",
    "global_adjustments",
    "composition",
    "local_adjustments",
    "output",
}
ISSUE_CATEGORIES = {
    "exposure",
    "highlights",
    "shadows",
    "color",
    "style",
    "composition",
    "artifact",
    "other",
}


class ReviewLoopError(RuntimeError):
    def __init__(self, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "reason": self.reason}


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _intent_content_hash(intent: dict[str, Any]) -> str:
    content = copy.deepcopy(intent)
    content.pop("revision", None)
    return _canonical_hash(content)


def _require_exact_fields(value: Any, expected: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReviewLoopError("INVALID_REVIEW_CONTRACT", f"{field} must be an object")
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing or unknown:
        raise ReviewLoopError(
            "INVALID_REVIEW_CONTRACT",
            f"{field} fields do not match the contract; missing={sorted(missing)}, unknown={sorted(unknown)}",
        )
    return value


def _validate_fingerprint(value: Any, field: str) -> dict[str, Any]:
    fingerprint = _require_exact_fields(value, {"sha256", "size_bytes"}, field)
    if not re.fullmatch(r"[0-9a-f]{64}", str(fingerprint["sha256"])):
        raise ReviewLoopError("INVALID_REVIEW_CONTRACT", f"{field}.sha256 is invalid")
    if (
        isinstance(fingerprint["size_bytes"], bool)
        or not isinstance(fingerprint["size_bytes"], int)
        or fingerprint["size_bytes"] < 0
    ):
        raise ReviewLoopError("INVALID_REVIEW_CONTRACT", f"{field}.size_bytes is invalid")
    return fingerprint


def validate_review_result(review: dict[str, Any]) -> None:
    expected = {
        "schema_version",
        "review_id",
        "intent_id",
        "intent_revision",
        "plan_id",
        "receipt_id",
        "output_fingerprint",
        "decision",
        "summary",
        "issues",
        "changes",
    }
    _require_exact_fields(review, expected, "ReviewResult")
    if review["schema_version"] != REVIEW_RESULT_SCHEMA_VERSION:
        raise ReviewLoopError("INVALID_REVIEW_CONTRACT", "Unsupported ReviewResult version")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(review["review_id"])):
        raise ReviewLoopError("INVALID_REVIEW_CONTRACT", "review_id is invalid")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(review["intent_id"])):
        raise ReviewLoopError("INVALID_REVIEW_CONTRACT", "intent_id is invalid")
    if not isinstance(review["intent_revision"], int) or review["intent_revision"] < 1:
        raise ReviewLoopError("INVALID_REVIEW_CONTRACT", "intent_revision is invalid")
    if not re.fullmatch(r"plan_[0-9a-f]{32}", str(review["plan_id"])):
        raise ReviewLoopError("INVALID_REVIEW_CONTRACT", "plan_id is invalid")
    if not re.fullmatch(r"receipt_[0-9a-f]{32}", str(review["receipt_id"])):
        raise ReviewLoopError("INVALID_REVIEW_CONTRACT", "receipt_id is invalid")
    _validate_fingerprint(review["output_fingerprint"], "output_fingerprint")
    if review["decision"] not in {"accept", "revise", "reject"}:
        raise ReviewLoopError("INVALID_REVIEW_CONTRACT", "decision is invalid")
    if not isinstance(review["summary"], str) or not review["summary"].strip():
        raise ReviewLoopError("INVALID_REVIEW_CONTRACT", "summary is required")
    if not isinstance(review["issues"], list) or len(review["issues"]) > 50:
        raise ReviewLoopError("INVALID_REVIEW_CONTRACT", "issues must be an array of at most 50 items")
    for index, issue in enumerate(review["issues"]):
        issue = _require_exact_fields(
            issue,
            {"category", "severity", "observation", "recommendation"},
            f"issues[{index}]",
        )
        if issue["category"] not in ISSUE_CATEGORIES:
            raise ReviewLoopError("INVALID_REVIEW_CONTRACT", f"issues[{index}].category is invalid")
        if issue["severity"] not in {"minor", "major", "blocking"}:
            raise ReviewLoopError("INVALID_REVIEW_CONTRACT", f"issues[{index}].severity is invalid")
        if not isinstance(issue["observation"], str) or not issue["observation"].strip():
            raise ReviewLoopError("INVALID_REVIEW_CONTRACT", f"issues[{index}].observation is required")
        if not isinstance(issue["recommendation"], str) or not issue["recommendation"].strip():
            raise ReviewLoopError("INVALID_REVIEW_CONTRACT", f"issues[{index}].recommendation is required")

    changes = review["changes"]
    if not isinstance(changes, dict) or set(changes) - EDITABLE_INTENT_FIELDS:
        raise ReviewLoopError(
            "INVALID_REVIEW_CONTRACT",
            "changes may contain only editable EditIntent fields",
        )
    if review["decision"] == "revise":
        if not review["issues"] or not changes:
            raise ReviewLoopError(
                "INVALID_REVIEW_CONTRACT",
                "revise requires at least one issue and one proposed change",
            )
    elif changes:
        raise ReviewLoopError(
            "INVALID_REVIEW_CONTRACT",
            "accept and reject cannot carry proposed changes",
        )
    if review["decision"] == "reject" and not review["issues"]:
        raise ReviewLoopError("INVALID_REVIEW_CONTRACT", "reject requires at least one issue")


def validate_review_session(session: dict[str, Any]) -> None:
    expected = {
        "schema_version",
        "session_id",
        "intent_id",
        "initial_revision",
        "max_revisions",
        "revisions_used",
        "status",
        "current_intent",
        "seen_review_ids",
        "seen_intent_hashes",
        "history",
    }
    _require_exact_fields(session, expected, "ReviewSession")
    if session["schema_version"] != REVIEW_SESSION_SCHEMA_VERSION:
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "Unsupported ReviewSession version")
    if not re.fullmatch(r"review_session_[0-9a-f]{32}", str(session["session_id"])):
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "session_id is invalid")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(session["intent_id"])):
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "intent_id is invalid")
    if not isinstance(session["initial_revision"], int) or session["initial_revision"] < 1:
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "initial_revision is invalid")
    if not isinstance(session["max_revisions"], int) or not 0 <= session["max_revisions"] <= 5:
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "max_revisions must be between 0 and 5")
    if not isinstance(session["revisions_used"], int) or not 0 <= session["revisions_used"] <= 5:
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "revisions_used is invalid")
    if session["revisions_used"] > session["max_revisions"]:
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "revisions_used exceeds max_revisions")
    if session["status"] not in {"active", "accepted", "rejected", "revision_limit_reached"}:
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "status is invalid")
    try:
        edit_intent.validate_edit_intent(session["current_intent"])
    except edit_intent.IntentValidationError as error:
        raise ReviewLoopError("INVALID_REVIEW_SESSION", str(error)) from error
    if session["intent_id"] != session["current_intent"]["intent_id"]:
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "current intent identity changed")
    if session["current_intent"]["revision"] != (
        session["initial_revision"] + session["revisions_used"]
    ):
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "current intent revision is inconsistent")
    if not isinstance(session["seen_review_ids"], list) or len(session["seen_review_ids"]) != len(
        set(session["seen_review_ids"])
    ):
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "seen_review_ids are invalid")
    if not isinstance(session["seen_intent_hashes"], list) or any(
        not re.fullmatch(r"[0-9a-f]{64}", str(item)) for item in session["seen_intent_hashes"]
    ):
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "seen_intent_hashes are invalid")
    if (
        len(session["seen_intent_hashes"]) != session["revisions_used"] + 1
        or len(session["seen_intent_hashes"]) != len(set(session["seen_intent_hashes"]))
        or session["seen_intent_hashes"][-1] != _intent_content_hash(session["current_intent"])
    ):
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "intent hash history is inconsistent")
    if not isinstance(session["history"], list):
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "history must be an array")
    expected_history_length = session["revisions_used"]
    if session["status"] != "active":
        expected_history_length += 1
    if len(session["history"]) != expected_history_length:
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "review history length is inconsistent")
    history_ids = []
    resulting_hashes = []
    for index, item in enumerate(session["history"]):
        item = _require_exact_fields(
            item,
            {
                "review_id",
                "decision",
                "intent_revision",
                "plan_id",
                "receipt_id",
                "resulting_intent_hash",
            },
            f"history[{index}]",
        )
        if item["decision"] not in {"accept", "revise", "reject"}:
            raise ReviewLoopError("INVALID_REVIEW_SESSION", "history decision is invalid")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(item["review_id"])):
            raise ReviewLoopError("INVALID_REVIEW_SESSION", "history review_id is invalid")
        if (
            not isinstance(item["intent_revision"], int)
            or not session["initial_revision"]
            <= item["intent_revision"]
            <= session["current_intent"]["revision"]
            or not re.fullmatch(r"plan_[0-9a-f]{32}", str(item["plan_id"]))
            or not re.fullmatch(r"receipt_[0-9a-f]{32}", str(item["receipt_id"]))
        ):
            raise ReviewLoopError("INVALID_REVIEW_SESSION", "history evidence identity is invalid")
        result_hash = item["resulting_intent_hash"]
        if result_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", str(result_hash)):
            raise ReviewLoopError("INVALID_REVIEW_SESSION", "history intent hash is invalid")
        if item["decision"] != "revise" and result_hash is not None:
            raise ReviewLoopError("INVALID_REVIEW_SESSION", "terminal review cannot create an intent hash")
        if result_hash is not None:
            resulting_hashes.append(result_hash)
        history_ids.append(item["review_id"])
    if history_ids != session["seen_review_ids"]:
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "review id history is inconsistent")
    if resulting_hashes != session["seen_intent_hashes"][1:]:
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "review and intent hash histories diverge")
    if session["status"] == "active" and any(
        item["decision"] != "revise" for item in session["history"]
    ):
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "active history contains a terminal decision")
    if session["status"] == "accepted" and session["history"][-1]["decision"] != "accept":
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "accepted session lacks an accept decision")
    if session["status"] == "rejected" and session["history"][-1]["decision"] != "reject":
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "rejected session lacks a reject decision")
    if (
        session["status"] == "revision_limit_reached"
        and (
            session["history"][-1]["decision"] != "revise"
            or session["history"][-1]["resulting_intent_hash"] is not None
        )
    ):
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "revision-limit history is invalid")


def start_review_session(intent: dict[str, Any], *, max_revisions: int = 2) -> dict[str, Any]:
    try:
        edit_intent.validate_edit_intent(intent)
    except edit_intent.IntentValidationError as error:
        raise ReviewLoopError("INVALID_REVIEW_INTENT", str(error)) from error
    if isinstance(max_revisions, bool) or not isinstance(max_revisions, int) or not 0 <= max_revisions <= 5:
        raise ReviewLoopError("INVALID_REVIEW_SESSION", "max_revisions must be between 0 and 5")
    current = copy.deepcopy(intent)
    return {
        "schema_version": REVIEW_SESSION_SCHEMA_VERSION,
        "session_id": "review_session_" + uuid.uuid4().hex,
        "intent_id": intent["intent_id"],
        "initial_revision": intent["revision"],
        "max_revisions": max_revisions,
        "revisions_used": 0,
        "status": "active",
        "current_intent": current,
        "seen_review_ids": [],
        "seen_intent_hashes": [_intent_content_hash(current)],
        "history": [],
    }


def _verify_bindings(
    intent: dict[str, Any],
    plan: dict[str, Any],
    receipt: dict[str, Any],
    review: dict[str, Any],
) -> None:
    if (
        plan.get("schema_version") != edit_intent.EXECUTION_PLAN_SCHEMA_VERSION
        or plan.get("intent_id") != intent["intent_id"]
        or plan.get("intent_revision") != intent["revision"]
        or plan.get("authorization") != intent["authorization"]
        or plan.get("source") != intent["source"]
        or plan.get("preview_basis") != intent["preview_basis"]
    ):
        raise ReviewLoopError(
            "REVIEW_BINDING_MISMATCH",
            "Execution plan is not bound to the current EditIntent revision",
        )
    if (
        receipt.get("schema_version") != edit_intent.EXECUTION_RECEIPT_SCHEMA_VERSION
        or receipt.get("plan_id") != plan.get("plan_id")
        or receipt.get("intent_id") != intent["intent_id"]
        or receipt.get("backend_id") != plan.get("backend", {}).get("id")
    ):
        raise ReviewLoopError(
            "REVIEW_BINDING_MISMATCH",
            "Execution receipt is not bound to the current plan",
        )
    if (
        receipt.get("status") != "success"
        or receipt.get("source_unchanged") is not True
        or receipt.get("output_fingerprint") is None
    ):
        raise ReviewLoopError(
            "REVIEW_RECEIPT_NOT_VERIFIED",
            "Review requires a successful receipt with unchanged RAW bytes and a verified output",
        )
    _validate_fingerprint(receipt["output_fingerprint"], "receipt.output_fingerprint")
    try:
        output_root = Path(plan["output_root"]).resolve()
        output_path_value = plan["artifacts"]["output"]["path"]
        output_path = Path(output_path_value)
        output_path.resolve().relative_to(output_root)
    except (KeyError, TypeError, ValueError):
        raise ReviewLoopError(
            "REVIEW_BINDING_MISMATCH",
            "Rendered output path is not contained by the execution plan output root",
        ) from None
    if output_path.is_symlink() or not output_path.is_file():
        raise ReviewLoopError("REVIEW_OUTPUT_DRIFT", "Rendered output is missing or is a symbolic link")
    if output_path.stat().st_size > 512 * 1024 * 1024:
        raise ReviewLoopError("REVIEW_OUTPUT_DRIFT", "Rendered output exceeds the review size limit")
    if preview_provider.file_fingerprint(output_path) != receipt["output_fingerprint"]:
        raise ReviewLoopError(
            "REVIEW_OUTPUT_DRIFT",
            "Rendered output bytes no longer match the execution receipt",
        )
    if (
        review["intent_id"] != intent["intent_id"]
        or review["intent_revision"] != intent["revision"]
        or review["plan_id"] != plan["plan_id"]
        or review["receipt_id"] != receipt.get("receipt_id")
        or review["output_fingerprint"] != receipt["output_fingerprint"]
    ):
        raise ReviewLoopError(
            "REVIEW_BINDING_MISMATCH",
            "ReviewResult does not reference the exact rendered output evidence",
        )


def advance_review_session(
    session: dict[str, Any],
    plan: dict[str, Any],
    receipt: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    validate_review_session(session)
    if session["status"] != "active":
        raise ReviewLoopError("REVIEW_SESSION_CLOSED", "Only an active review session can advance")
    if (
        receipt.get("status") != "success"
        or receipt.get("source_unchanged") is not True
        or receipt.get("output_fingerprint") is None
    ):
        raise ReviewLoopError(
            "REVIEW_RECEIPT_NOT_VERIFIED",
            "Review requires a successful receipt with unchanged RAW bytes and a verified output",
        )
    validate_review_result(review)
    if review["review_id"] in session["seen_review_ids"]:
        raise ReviewLoopError("REVIEW_ALREADY_APPLIED", "review_id has already been applied")
    current_intent = session["current_intent"]
    _verify_bindings(current_intent, plan, receipt, review)

    updated = copy.deepcopy(session)
    updated["seen_review_ids"].append(review["review_id"])
    history_entry = {
        "review_id": review["review_id"],
        "decision": review["decision"],
        "intent_revision": current_intent["revision"],
        "plan_id": plan["plan_id"],
        "receipt_id": receipt["receipt_id"],
        "resulting_intent_hash": None,
    }

    if review["decision"] == "accept":
        updated["status"] = "accepted"
        updated["history"].append(history_entry)
        return {"session": updated, "next_intent": None}
    if review["decision"] == "reject":
        updated["status"] = "rejected"
        updated["history"].append(history_entry)
        return {"session": updated, "next_intent": None}
    if updated["revisions_used"] >= updated["max_revisions"]:
        updated["status"] = "revision_limit_reached"
        updated["history"].append(history_entry)
        return {"session": updated, "next_intent": None}

    revised = copy.deepcopy(current_intent)
    revised.update(copy.deepcopy(review["changes"]))
    revised["revision"] = current_intent["revision"] + 1
    try:
        edit_intent.validate_edit_intent(revised)
    except edit_intent.IntentValidationError as error:
        raise ReviewLoopError("INVALID_REVISED_INTENT", str(error)) from error
    content_hash = _intent_content_hash(revised)
    if content_hash == _intent_content_hash(current_intent):
        raise ReviewLoopError("REVIEW_NO_EFFECT", "Proposed changes do not alter the EditIntent")
    if content_hash in updated["seen_intent_hashes"]:
        raise ReviewLoopError("REVIEW_CYCLE_DETECTED", "Proposed changes repeat an earlier EditIntent")

    updated["revisions_used"] += 1
    updated["current_intent"] = revised
    updated["seen_intent_hashes"].append(content_hash)
    history_entry["resulting_intent_hash"] = content_hash
    updated["history"].append(history_entry)
    return {"session": updated, "next_intent": revised}


def _read_json(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError(f"JSON contract file is too large: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Advance a bounded Lumenflow render-review loop.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start")
    start.add_argument("intent", type=Path)
    start.add_argument("--max-revisions", type=int, default=2)
    start.add_argument("--state-output", type=Path, required=True)

    advance = subparsers.add_parser("advance")
    advance.add_argument("session", type=Path)
    advance.add_argument("plan", type=Path)
    advance.add_argument("receipt", type=Path)
    advance.add_argument("review", type=Path)
    advance.add_argument("--state-output", type=Path, required=True)
    advance.add_argument("--next-intent-output", type=Path)

    args = parser.parse_args()
    if args.command == "start":
        state = start_review_session(_read_json(args.intent), max_revisions=args.max_revisions)
        _write_json(args.state_output, state)
        print(json.dumps({"session_id": state["session_id"], "status": state["status"]}, indent=2))
        return

    transition = advance_review_session(
        _read_json(args.session),
        _read_json(args.plan),
        _read_json(args.receipt),
        _read_json(args.review),
    )
    if transition["next_intent"] is not None and args.next_intent_output is None:
        raise SystemExit("--next-intent-output is required when decision=revise")
    if transition["next_intent"] is not None:
        _write_json(args.next_intent_output, transition["next_intent"])
    _write_json(args.state_output, transition["session"])
    print(
        json.dumps(
            {
                "session_id": transition["session"]["session_id"],
                "status": transition["session"]["status"],
                "next_revision": (
                    transition["next_intent"]["revision"] if transition["next_intent"] else None
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
