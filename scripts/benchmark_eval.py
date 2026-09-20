#!/usr/bin/env python3
"""Build evidence-bound photo-agent benchmark observations and regression reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import edit_intent
import preview_provider
import review_loop


BENCHMARK_CASE_VERSION = "lumenflow.benchmark_case.v1"
VISUAL_ASSESSMENT_VERSION = "lumenflow.visual_assessment.v1"
BENCHMARK_OBSERVATION_VERSION = "lumenflow.benchmark_observation.v1"
BENCHMARK_REPORT_VERSION = "lumenflow.benchmark_report.v1"
SCORE_NAMES = (
    "technical_quality",
    "purpose_fit",
    "style_coherence",
    "composition",
    "naturalness",
)
CHECK_NAMES = (
    "highlight_detail",
    "shadow_detail",
    "color_integrity",
    "composition_intent",
    "artifacts_absent",
)
BACKEND_IDS = {"rawtherapee", "darktable", "lightroom"}


class BenchmarkError(RuntimeError):
    def __init__(self, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def observation_id_for(payload: dict[str, Any]) -> str:
    content = dict(payload)
    content.pop("schema_version", None)
    content.pop("observation_id", None)
    return "observation_" + _canonical_hash(content)[:32]


def report_id_for(payload: dict[str, Any]) -> str:
    identity = {
        "criteria": payload["criteria"],
        "observations": payload["observation_ids"],
        "backends": payload["backends"],
    }
    return "benchmark_report_" + _canonical_hash(identity)[:32]


def _exact_object(value: Any, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", f"{name} fields are invalid")
    return value


def _fingerprint(value: Any, name: str) -> dict[str, Any]:
    value = _exact_object(value, {"sha256", "size_bytes"}, name)
    if not re.fullmatch(r"[0-9a-f]{64}", str(value["sha256"])):
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", f"{name}.sha256 is invalid")
    if isinstance(value["size_bytes"], bool) or not isinstance(value["size_bytes"], int) or value[
        "size_bytes"
    ] < 0:
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", f"{name}.size_bytes is invalid")
    return value


def validate_case(case: dict[str, Any]) -> None:
    _exact_object(
        case,
        {
            "schema_version",
            "case_id",
            "purpose",
            "source_fingerprint",
            "preview_basis",
            "target_style_id",
            "tags",
        },
        "BenchmarkCase",
    )
    if case["schema_version"] != BENCHMARK_CASE_VERSION:
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "Unsupported BenchmarkCase version")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(case["case_id"])):
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "case_id is invalid")
    if not isinstance(case["purpose"], str) or not case["purpose"].strip():
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "purpose is required")
    _fingerprint(case["source_fingerprint"], "source_fingerprint")
    preview = _exact_object(
        case["preview_basis"],
        {"artifact_id", "starting_state_hash", "state_completeness"},
        "preview_basis",
    )
    if (
        not re.fullmatch(r"preview_[0-9a-f]{32}", str(preview["artifact_id"]))
        or not re.fullmatch(r"[0-9a-f]{64}", str(preview["starting_state_hash"]))
        or preview["state_completeness"] not in {"complete", "partial"}
    ):
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "preview_basis is invalid")
    if not isinstance(case["target_style_id"], str) or not case["target_style_id"].strip():
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "target_style_id is required")
    if (
        not isinstance(case["tags"], list)
        or len(case["tags"]) > 20
        or any(not isinstance(tag, str) or not tag.strip() for tag in case["tags"])
    ):
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "tags are invalid")


def validate_assessment(assessment: dict[str, Any]) -> None:
    _exact_object(
        assessment,
        {
            "schema_version",
            "assessment_id",
            "case_id",
            "output_fingerprint",
            "rubric_version",
            "model_id",
            "scores",
            "checks",
            "summary",
        },
        "VisualAssessment",
    )
    if assessment["schema_version"] != VISUAL_ASSESSMENT_VERSION:
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "Unsupported VisualAssessment version")
    for field in ("assessment_id", "case_id"):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(assessment[field])):
            raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", f"{field} is invalid")
    _fingerprint(assessment["output_fingerprint"], "assessment.output_fingerprint")
    if assessment["rubric_version"] != "photo-edit-v1":
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "rubric_version is invalid")
    if not isinstance(assessment["model_id"], str) or not assessment["model_id"].strip():
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "model_id is required")
    scores = _exact_object(assessment["scores"], set(SCORE_NAMES), "scores")
    for name, value in scores.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= value <= 5:
            raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", f"scores.{name} must be 1..5")
    checks = _exact_object(assessment["checks"], set(CHECK_NAMES), "checks")
    if any(not isinstance(value, bool) for value in checks.values()):
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "checks must be boolean")
    if not isinstance(assessment["summary"], str) or not assessment["summary"].strip():
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "assessment summary is required")


def _validate_runtime_binding(
    case: dict[str, Any],
    plan: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    if (
        plan.get("schema_version") != edit_intent.EXECUTION_PLAN_SCHEMA_VERSION
        or plan.get("source", {}).get("fingerprint") != case["source_fingerprint"]
        or plan.get("preview_basis") != case["preview_basis"]
        or plan.get("backend", {}).get("id") not in BACKEND_IDS
        or receipt.get("schema_version") != edit_intent.EXECUTION_RECEIPT_SCHEMA_VERSION
        or receipt.get("plan_id") != plan.get("plan_id")
        or receipt.get("intent_id") != plan.get("intent_id")
        or receipt.get("backend_id") != plan.get("backend", {}).get("id")
    ):
        raise BenchmarkError(
            "BENCHMARK_BINDING_MISMATCH",
            "Case, plan, and receipt do not describe the same execution",
        )
    if receipt.get("status") == "dry_run":
        raise BenchmarkError(
            "BENCHMARK_DRY_RUN_FORBIDDEN",
            "Dry-run receipts are not benchmark observations",
        )


def _verified_output(plan: dict[str, Any], receipt: dict[str, Any]) -> bool:
    try:
        output_root = Path(plan["output_root"]).resolve()
        output = Path(plan["artifacts"]["output"]["path"])
        output.resolve().relative_to(output_root)
    except (KeyError, TypeError, ValueError):
        return False
    if output.is_symlink() or not output.is_file() or output.stat().st_size > 512 * 1024 * 1024:
        return False
    return preview_provider.file_fingerprint(output) == receipt.get("output_fingerprint")


def build_observation(
    case: dict[str, Any],
    plan: dict[str, Any],
    receipt: dict[str, Any],
    *,
    session: dict[str, Any] | None = None,
    assessment: dict[str, Any] | None = None,
    runtime_ms: int,
) -> dict[str, Any]:
    validate_case(case)
    _validate_runtime_binding(case, plan, receipt)
    if isinstance(runtime_ms, bool) or not isinstance(runtime_ms, int) or runtime_ms < 0:
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "runtime_ms is invalid")

    base_identity = {
        "case_id": case["case_id"],
        "backend_id": plan["backend"]["id"],
        "plan_id": plan["plan_id"],
        "receipt_id": receipt["receipt_id"],
    }
    if receipt.get("status") != "success":
        if session is not None or assessment is not None:
            raise BenchmarkError(
                "INVALID_BENCHMARK_CONTRACT",
                "Failed executions cannot carry review sessions or visual scores",
            )
        observation = {
            "schema_version": BENCHMARK_OBSERVATION_VERSION,
            "observation_id": "",
            **base_identity,
            "session_id": None,
            "assessment_id": None,
            "outcome": "execution_failed",
            "integrity_passed": False,
            "source_unchanged": receipt.get("source_unchanged") is True,
            "output_fingerprint": None,
            "runtime_ms": runtime_ms,
            "revisions_used": 0,
            "scores": None,
            "checks": None,
        }
        observation["observation_id"] = observation_id_for(observation)
        return observation

    if session is None or assessment is None:
        raise BenchmarkError(
            "INVALID_BENCHMARK_CONTRACT",
            "Successful executions require terminal review and visual assessment evidence",
        )
    try:
        review_loop.validate_review_session(session)
    except review_loop.ReviewLoopError as error:
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", str(error)) from error
    validate_assessment(assessment)
    status_to_outcome = {
        "accepted": "accepted",
        "rejected": "rejected",
        "revision_limit_reached": "revision_limit_reached",
    }
    outcome = status_to_outcome.get(session.get("status"))
    history = session.get("history")
    current_intent = session.get("current_intent")
    if (
        outcome is None
        or not isinstance(history, list)
        or not history
        or history[-1].get("receipt_id") != receipt["receipt_id"]
        or not isinstance(current_intent, dict)
        or current_intent.get("intent_id") != plan.get("intent_id")
        or current_intent.get("revision") != plan.get("intent_revision")
        or current_intent.get("purpose") != case["purpose"]
        or current_intent.get("style", {}).get("style_id") != case["target_style_id"]
        or assessment["case_id"] != case["case_id"]
        or assessment["output_fingerprint"] != receipt.get("output_fingerprint")
    ):
        raise BenchmarkError(
            "BENCHMARK_BINDING_MISMATCH",
            "Review session or assessment does not bind the benchmark execution",
        )
    output_verified = _verified_output(plan, receipt)
    if not output_verified:
        raise BenchmarkError(
            "BENCHMARK_OUTPUT_DRIFT",
            "Rendered output no longer matches the benchmark receipt",
        )
    observation = {
        "schema_version": BENCHMARK_OBSERVATION_VERSION,
        "observation_id": "",
        **base_identity,
        "session_id": session["session_id"],
        "assessment_id": assessment["assessment_id"],
        "outcome": outcome,
        "integrity_passed": receipt.get("source_unchanged") is True and output_verified,
        "source_unchanged": receipt.get("source_unchanged") is True,
        "output_fingerprint": receipt["output_fingerprint"],
        "runtime_ms": runtime_ms,
        "revisions_used": session["revisions_used"],
        "scores": assessment["scores"],
        "checks": assessment["checks"],
    }
    observation["observation_id"] = observation_id_for(observation)
    return observation


def _validate_observation(observation: dict[str, Any]) -> None:
    fields = {
        "schema_version",
        "observation_id",
        "case_id",
        "backend_id",
        "plan_id",
        "receipt_id",
        "session_id",
        "assessment_id",
        "outcome",
        "integrity_passed",
        "source_unchanged",
        "output_fingerprint",
        "runtime_ms",
        "revisions_used",
        "scores",
        "checks",
    }
    _exact_object(observation, fields, "BenchmarkObservation")
    if observation["schema_version"] != BENCHMARK_OBSERVATION_VERSION:
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "Unsupported observation version")
    if not re.fullmatch(r"observation_[0-9a-f]{32}", str(observation["observation_id"])):
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "observation_id is invalid")
    if observation["observation_id"] != observation_id_for(observation):
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "observation content hash is invalid")
    if observation["backend_id"] not in BACKEND_IDS:
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "backend_id is invalid")
    if (
        not re.fullmatch(r"[A-Za-z0-9_.-]+", str(observation["case_id"]))
        or not re.fullmatch(r"plan_[0-9a-f]{32}", str(observation["plan_id"]))
        or not re.fullmatch(r"receipt_[0-9a-f]{32}", str(observation["receipt_id"]))
    ):
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "observation evidence ids are invalid")
    if observation["outcome"] not in {
        "accepted",
        "rejected",
        "revision_limit_reached",
        "execution_failed",
    }:
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "outcome is invalid")
    if not isinstance(observation["integrity_passed"], bool) or not isinstance(
        observation["source_unchanged"], bool
    ):
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "integrity flags are invalid")
    if isinstance(observation["runtime_ms"], bool) or not isinstance(
        observation["runtime_ms"], int
    ) or observation["runtime_ms"] < 0:
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "runtime_ms is invalid")
    if (
        not isinstance(observation["revisions_used"], int)
        or not 0 <= observation["revisions_used"] <= 5
    ):
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "revisions_used is invalid")
    if observation["outcome"] == "execution_failed":
        nullable = ("session_id", "assessment_id", "output_fingerprint", "scores", "checks")
        if any(observation[field] is not None for field in nullable) or observation[
            "integrity_passed"
        ]:
            raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "failed observation carries scores")
        return
    if (
        not re.fullmatch(r"review_session_[0-9a-f]{32}", str(observation["session_id"]))
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", str(observation["assessment_id"]))
        or observation["integrity_passed"] is not True
        or observation["source_unchanged"] is not True
    ):
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "scored observation integrity is invalid")
    _fingerprint(observation["output_fingerprint"], "output_fingerprint")
    scores = _exact_object(observation["scores"], set(SCORE_NAMES), "scores")
    checks = _exact_object(observation["checks"], set(CHECK_NAMES), "checks")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= value <= 5 for value in scores.values()):
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "observation scores are invalid")
    if any(not isinstance(value, bool) for value in checks.values()):
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "observation checks are invalid")


def build_report(
    observations: list[dict[str, Any]],
    *,
    minimum_cases: int = 5,
    minimum_acceptance_rate: float = 0.8,
    minimum_mean_score: float = 4.0,
    minimum_check_pass_rate: float = 1.0,
) -> dict[str, Any]:
    if not observations:
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "At least one observation is required")
    if minimum_cases < 1 or not 0 <= minimum_acceptance_rate <= 1 or not 1 <= minimum_mean_score <= 5 or not 0 <= minimum_check_pass_rate <= 1:
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "Benchmark criteria are invalid")
    for observation in observations:
        _validate_observation(observation)
    ids = [item["observation_id"] for item in observations]
    if len(ids) != len(set(ids)):
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "Duplicate observation_id")

    criteria = {
        "minimum_cases": minimum_cases,
        "minimum_acceptance_rate": minimum_acceptance_rate,
        "minimum_mean_score": minimum_mean_score,
        "minimum_check_pass_rate": minimum_check_pass_rate,
        "require_zero_integrity_failures": True,
    }
    backends: dict[str, Any] = {}
    for backend_id in sorted({item["backend_id"] for item in observations}):
        items = [item for item in observations if item["backend_id"] == backend_id]
        scored = [item for item in items if item["scores"] is not None]
        attempted = len(items)
        accepted = sum(item["outcome"] == "accepted" for item in items)
        integrity_failures = sum(not item["integrity_passed"] for item in items)
        acceptance_rate = round(accepted / attempted, 4)
        mean_score = None
        check_pass_rate = None
        if scored:
            per_item_scores = [sum(item["scores"].values()) / len(SCORE_NAMES) for item in scored]
            mean_score = round(sum(per_item_scores) / len(per_item_scores), 4)
            passed_checks = sum(sum(item["checks"].values()) for item in scored)
            check_pass_rate = round(passed_checks / (len(scored) * len(CHECK_NAMES)), 4)
        mean_runtime_ms = round(sum(item["runtime_ms"] for item in items) / attempted, 2)
        mean_revisions = round(sum(item["revisions_used"] for item in items) / attempted, 2)
        gate_passed = (
            attempted >= minimum_cases
            and acceptance_rate >= minimum_acceptance_rate
            and mean_score is not None
            and mean_score >= minimum_mean_score
            and check_pass_rate is not None
            and check_pass_rate >= minimum_check_pass_rate
            and integrity_failures == 0
        )
        backends[backend_id] = {
            "attempted": attempted,
            "accepted": accepted,
            "acceptance_rate": acceptance_rate,
            "integrity_failures": integrity_failures,
            "mean_score": mean_score,
            "check_pass_rate": check_pass_rate,
            "mean_runtime_ms": mean_runtime_ms,
            "mean_revisions": mean_revisions,
            "gate_passed": gate_passed,
        }
    report = {
        "schema_version": BENCHMARK_REPORT_VERSION,
        "report_id": "",
        "criteria": criteria,
        "observation_ids": sorted(ids),
        "backends": backends,
        "overall_passed": bool(backends) and all(item["gate_passed"] for item in backends.values()),
    }
    report["report_id"] = report_id_for(report)
    return report


def _validate_report(report: dict[str, Any]) -> None:
    _exact_object(
        report,
        {"schema_version", "report_id", "criteria", "observation_ids", "backends", "overall_passed"},
        "BenchmarkReport",
    )
    if report["schema_version"] != BENCHMARK_REPORT_VERSION:
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "Unsupported report version")
    if (
        not re.fullmatch(r"benchmark_report_[0-9a-f]{32}", str(report["report_id"]))
        or report["report_id"] != report_id_for(report)
    ):
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "report content hash is invalid")
    criteria = _exact_object(
        report["criteria"],
        {
            "minimum_cases",
            "minimum_acceptance_rate",
            "minimum_mean_score",
            "minimum_check_pass_rate",
            "require_zero_integrity_failures",
        },
        "criteria",
    )
    if (
        not isinstance(criteria["minimum_cases"], int)
        or criteria["minimum_cases"] < 1
        or not 0 <= criteria["minimum_acceptance_rate"] <= 1
        or not 1 <= criteria["minimum_mean_score"] <= 5
        or not 0 <= criteria["minimum_check_pass_rate"] <= 1
        or criteria["require_zero_integrity_failures"] is not True
    ):
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "report criteria are invalid")
    observation_ids = report["observation_ids"]
    if (
        not isinstance(observation_ids, list)
        or len(observation_ids) != len(set(observation_ids))
        or any(not re.fullmatch(r"observation_[0-9a-f]{32}", str(item)) for item in observation_ids)
    ):
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "report observation ids are invalid")
    if not isinstance(report["backends"], dict) or not report["backends"]:
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "report backends are invalid")
    summary_fields = {
        "attempted",
        "accepted",
        "acceptance_rate",
        "integrity_failures",
        "mean_score",
        "check_pass_rate",
        "mean_runtime_ms",
        "mean_revisions",
        "gate_passed",
    }
    for backend_id, summary in report["backends"].items():
        if backend_id not in BACKEND_IDS:
            raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "report backend id is invalid")
        summary = _exact_object(summary, summary_fields, f"backends.{backend_id}")
        if (
            not isinstance(summary["attempted"], int)
            or summary["attempted"] < 1
            or not isinstance(summary["accepted"], int)
            or not 0 <= summary["accepted"] <= summary["attempted"]
            or not 0 <= summary["acceptance_rate"] <= 1
            or not isinstance(summary["integrity_failures"], int)
            or not 0 <= summary["integrity_failures"] <= summary["attempted"]
            or summary["mean_score"] is not None
            and not 1 <= summary["mean_score"] <= 5
            or summary["check_pass_rate"] is not None
            and not 0 <= summary["check_pass_rate"] <= 1
            or summary["mean_runtime_ms"] < 0
            or summary["mean_revisions"] < 0
            or not isinstance(summary["gate_passed"], bool)
        ):
            raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "report backend summary is invalid")
    if not isinstance(report["overall_passed"], bool) or report["overall_passed"] != all(
        item["gate_passed"] for item in report["backends"].values()
    ):
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "overall_passed is inconsistent")


def compare_reports(
    candidate: dict[str, Any],
    baseline: dict[str, Any],
    *,
    maximum_acceptance_drop: float = 0.05,
    maximum_score_drop: float = 0.25,
) -> dict[str, Any]:
    if not 0 <= maximum_acceptance_drop <= 1 or not 0 <= maximum_score_drop <= 4:
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "Comparison tolerances are invalid")
    _validate_report(candidate)
    _validate_report(baseline)
    backend_ids = set(candidate.get("backends", {})) & set(baseline.get("backends", {}))
    if not backend_ids:
        raise BenchmarkError("INVALID_BENCHMARK_CONTRACT", "Reports have no backend in common")
    backends = {}
    for backend_id in sorted(backend_ids):
        current = candidate["backends"][backend_id]
        previous = baseline["backends"][backend_id]
        acceptance_delta = round(current["acceptance_rate"] - previous["acceptance_rate"], 4)
        current_score = current.get("mean_score")
        previous_score = previous.get("mean_score")
        score_delta = None
        if current_score is not None and previous_score is not None:
            score_delta = round(current_score - previous_score, 4)
        passed = (
            acceptance_delta >= -maximum_acceptance_drop
            and score_delta is not None
            and score_delta >= -maximum_score_drop
            and current.get("integrity_failures", 1) == 0
        )
        backends[backend_id] = {
            "acceptance_delta": acceptance_delta,
            "mean_score_delta": score_delta,
            "passed": passed,
        }
    return {
        "schema_version": "lumenflow.benchmark_comparison.v1",
        "maximum_acceptance_drop": maximum_acceptance_drop,
        "maximum_score_drop": maximum_score_drop,
        "backends": backends,
        "passed": all(item["passed"] for item in backends.values()),
    }


def _read_json(path: Path) -> Any:
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError(f"JSON file is too large: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and compare photo-agent benchmark evidence.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    record = subparsers.add_parser("record")
    record.add_argument("case", type=Path)
    record.add_argument("plan", type=Path)
    record.add_argument("receipt", type=Path)
    record.add_argument("--session", type=Path)
    record.add_argument("--assessment", type=Path)
    record.add_argument("--runtime-ms", type=int, required=True)
    record.add_argument("--output", type=Path, required=True)

    report = subparsers.add_parser("report")
    report.add_argument("observations", type=Path)
    report.add_argument("--minimum-cases", type=int, default=5)
    report.add_argument("--minimum-acceptance-rate", type=float, default=0.8)
    report.add_argument("--minimum-mean-score", type=float, default=4.0)
    report.add_argument("--minimum-check-pass-rate", type=float, default=1.0)
    report.add_argument("--output", type=Path, required=True)

    compare = subparsers.add_parser("compare")
    compare.add_argument("candidate", type=Path)
    compare.add_argument("baseline", type=Path)
    compare.add_argument("--maximum-acceptance-drop", type=float, default=0.05)
    compare.add_argument("--maximum-score-drop", type=float, default=0.25)
    compare.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "record":
        observation = build_observation(
            _read_json(args.case),
            _read_json(args.plan),
            _read_json(args.receipt),
            session=_read_json(args.session) if args.session else None,
            assessment=_read_json(args.assessment) if args.assessment else None,
            runtime_ms=args.runtime_ms,
        )
        _write_json(args.output, observation)
        print(json.dumps({"observation_id": observation["observation_id"]}, indent=2))
        return
    if args.command == "report":
        observations = _read_json(args.observations)
        if not isinstance(observations, list):
            raise SystemExit("observations must be a JSON array")
        result = build_report(
            observations,
            minimum_cases=args.minimum_cases,
            minimum_acceptance_rate=args.minimum_acceptance_rate,
            minimum_mean_score=args.minimum_mean_score,
            minimum_check_pass_rate=args.minimum_check_pass_rate,
        )
    else:
        result = compare_reports(
            _read_json(args.candidate),
            _read_json(args.baseline),
            maximum_acceptance_drop=args.maximum_acceptance_drop,
            maximum_score_drop=args.maximum_score_drop,
        )
    _write_json(args.output, result)
    print(json.dumps({"passed": result["overall_passed"] if "overall_passed" in result else result["passed"]}, indent=2))


if __name__ == "__main__":
    main()
