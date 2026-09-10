"""Received-email second-pass shadow contract. This module cannot authorize send.

Inputs are consistency-checked attestations, not authenticated proof of inspection.
No model, SMTP, generation, admin approval or mutation of run artifacts occurs here.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

POLICY_VERSION = "genie-keesuri-second-pass-shadow-v1"
ACTIVE_MODES = frozenset({"today_genie", "keysuri_global_tech", "keysuri_korea_tech"})
EXPECTED_IMAGE_ROLES = {
    "today_genie": frozenset({"top", "bottom"}),
    "keysuri_global_tech": frozenset({"top"}),
    "keysuri_korea_tech": frozenset({"top", "bottom"}),
}
REQUIRED_CHECKS = frozenset({"content", "sources", "images", "render", "operations"})
VERDICTS = frozenset({"PASS", "HOLD", "REVIEW_UNAVAILABLE", "REVIEW_INCOMPLETE", "WORK_REVIEW_ERROR"})
_HASH = re.compile(r"^[a-f0-9]{64}$")
_BINDINGS = ("run_id", "mode", "publication_date", "subject_sha256", "body_sha256", "image_sha256")
_RUN_ID = re.compile(r"^(\d{8})_\d{6}_(today_genie|keysuri_global_tech|keysuri_korea_tech)_[a-f0-9]{8}$")


def _timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone_required")
    return parsed.astimezone(timezone.utc)


def _hashes_valid(value: Any) -> bool:
    return isinstance(value, dict) and bool(value) and all(
        isinstance(key, str) and key and isinstance(digest, str) and _HASH.fullmatch(digest)
        for key, digest in value.items()
    )


def evaluate_shadow_review(
    candidate: Mapping[str, Any],
    review: Mapping[str, Any] | None,
    *,
    now: datetime,
    max_email_age: timedelta = timedelta(hours=6),
    max_review_age: timedelta = timedelta(minutes=30),
) -> dict[str, Any]:
    """Classify an attestation without upgrading it into delivery authority.

Candidate fields must come from an independently recovered artifact/message
binding. This legacy shadow API does not authenticate them; the separate staged
``delegated_gate`` worker implements the authenticated v2 boundary. All time
limits here are shadow-evaluation parameters, not live schedule promises.
"""
    result: dict[str, Any] = {
        "schema_version": 1,
        "policy_version": POLICY_VERSION,
        "run_id": str(candidate.get("run_id") or "") if isinstance(candidate, Mapping) else "",
        "mode": str(candidate.get("mode") or "") if isinstance(candidate, Mapping) else "",
        "decision_kind": "SECOND_PASS_SHADOW",
        "approval_authority": "NONE",
        "customer_send_authorized": False,
        "authenticity_verified": False,
        "reason_codes": [],
    }

    def outcome(verdict: str, *reasons: str) -> dict[str, Any]:
        return {**result, "verdict": verdict, "reason_codes": list(reasons)}

    try:
        if not isinstance(candidate, Mapping):
            return outcome("WORK_REVIEW_ERROR", "MALFORMED_CANDIDATE")
        current = _timestamp(now.isoformat())
        result["evaluated_at"] = current.isoformat()
        if max_email_age.total_seconds() <= 0 or max_review_age.total_seconds() <= 0:
            return outcome("WORK_REVIEW_ERROR", "INVALID_TIME_WINDOW")
        if candidate.get("mode") not in ACTIVE_MODES:
            return outcome("HOLD", "UNSUPPORTED_MODE")
        from admin_store import validate_run_id

        if not validate_run_id(str(candidate.get("run_id") or "")):
            return outcome("HOLD", "INVALID_RUN_ID")
        date.fromisoformat(str(candidate.get("publication_date") or ""))
        identity = _RUN_ID.fullmatch(str(candidate["run_id"]))
        if not identity or identity.group(2) != candidate["mode"] or identity.group(1) != str(candidate["publication_date"]).replace("-", ""):
            return outcome("HOLD", "RUN_PRODUCT_DATE_MISMATCH")
        if candidate["publication_date"] != current.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat():
            return outcome("HOLD", "PUBLICATION_OUTSIDE_CURRENT_KST_DATE")
        run_time = datetime.strptime(str(candidate["run_id"])[:15], "%Y%m%d_%H%M%S").replace(tzinfo=ZoneInfo("Asia/Seoul"))
        if not all(_HASH.fullmatch(str(candidate.get(field) or "")) for field in ("subject_sha256", "body_sha256")) or not _hashes_valid(candidate.get("image_sha256")):
            return outcome("REVIEW_INCOMPLETE", "CANDIDATE_EVIDENCE_MISSING")
        if set(candidate["image_sha256"]) != EXPECTED_IMAGE_ROLES[candidate["mode"]]:
            return outcome("REVIEW_INCOMPLETE", "EXPECTED_IMAGE_ROLES_MISSING_OR_UNEXPECTED")
        if candidate.get("first_pass_verdict") != "PASS":
            return outcome("HOLD", "FIRST_PASS_NOT_PASS")
        if candidate.get("artifact_status") not in {"emailed", "validated", "reissued"}:
            return outcome("HOLD", "ARTIFACT_NOT_READY")
        if candidate.get("owner_review_status") not in {"pending_review", "reopened"}:
            return outcome("HOLD", "OWNER_REVIEW_STATE_CONFLICT")
        if candidate.get("reissue_requested") or candidate.get("last_reissue_child_run_id") or candidate.get("superseded_by_run_id"):
            return outcome("HOLD", "PUBLICATION_SUPERSEDED_OR_REISSUE_PENDING")
        from product_surface_contract import CUSTOMER_SURFACE_PASS

        if candidate.get("customer_surface_status") != CUSTOMER_SURFACE_PASS:
            return outcome("HOLD", "PRODUCT_SURFACE_NOT_READY")
        if candidate["mode"] in {"keysuri_global_tech", "keysuri_korea_tech"} and (
            candidate.get("safety_verdict") != "SAFE" or candidate.get("editorial_verdict") != "READY"
        ):
            return outcome("HOLD", "FIRST_PASS_SAFETY_OR_EDITORIAL_NOT_READY")
        if candidate.get("customer_delivery_status") != "not_sent":
            return outcome("HOLD", "DELIVERY_RECONCILIATION_REQUIRED")
        if review is None:
            return outcome("REVIEW_UNAVAILABLE", "NO_REVIEW")
        if not isinstance(review, Mapping):
            return outcome("WORK_REVIEW_ERROR", "MALFORMED_REVIEW")
        if review.get("verdict") in {"REVIEW_UNAVAILABLE", "REVIEW_INCOMPLETE", "WORK_REVIEW_ERROR"}:
            return outcome(str(review["verdict"]), "REVIEWER_REPORTED_FAILURE")
        if review.get("verdict") not in VERDICTS:
            return outcome("REVIEW_INCOMPLETE", "VERDICT_MISSING_OR_UNKNOWN")
        if any(review.get(key) != candidate.get(key) for key in _BINDINGS):
            return outcome("HOLD", "CANDIDATE_MESSAGE_BINDING_MISMATCH")
        if review.get("policy_version") != POLICY_VERSION:
            return outcome("HOLD", "REVIEW_POLICY_MISMATCH")
        if not str(review.get("reviewer_agent") or "").strip() or not str(review.get("reviewer_model") or "").lower().startswith("gpt-"):
            return outcome("REVIEW_INCOMPLETE", "INDEPENDENT_REVIEWER_IDENTITY_MISSING")
        message = review.get("received_message")
        if not isinstance(message, dict) or not all(str(message.get(key) or "").strip() for key in ("mailbox_id", "message_id", "internet_message_id", "received_at")):
            return outcome("REVIEW_UNAVAILABLE", "RECEIVED_EMAIL_UNAVAILABLE")
        if not _HASH.fullmatch(str(message.get("raw_mime_sha256") or "")) or not _HASH.fullmatch(str(message.get("render_capture_sha256") or "")):
            return outcome("REVIEW_INCOMPLETE", "RECEIVED_RENDER_EVIDENCE_MISSING")
        if message.get("message_id") != candidate.get("received_message_id"):
            return outcome("HOLD", "RECEIVED_MESSAGE_ID_MISMATCH")
        expected_message = candidate.get("received_message")
        if not isinstance(expected_message, dict):
            return outcome("REVIEW_INCOMPLETE", "INDEPENDENT_RECEIPT_BINDING_MISSING")
        if any(message.get(key) != expected_message.get(key) for key in (
            "mailbox_id", "message_id", "internet_message_id", "received_at", "raw_mime_sha256", "render_capture_sha256"
        )):
            return outcome("HOLD", "RECEIVED_ENVELOPE_EVIDENCE_MISMATCH")
        if candidate.get("parent_run_id") != review.get("parent_run_id"):
            return outcome("HOLD", "REISSUE_LINEAGE_MISMATCH")
        received = _timestamp(message["received_at"])
        reviewed = _timestamp(review.get("reviewed_at"))
        if run_time > received:
            return outcome("HOLD", "RECEIPT_PRECEDES_RUN")
        if received > reviewed or reviewed > current or current - received > max_email_age or current - reviewed > max_review_age:
            return outcome("REVIEW_UNAVAILABLE", "STALE_OR_INVALID_REVIEW_WINDOW")
        checks = review.get("checks")
        # Optional checks may discover an anomaly beyond the initial taxonomy.
        # Completing the five required dimensions must never hide that finding.
        if isinstance(checks, dict) and any(
            isinstance(value, str) and value in {"ANOMALY", "FAIL", "HOLD"}
            for value in checks.values()
        ):
            return outcome("HOLD", "REVIEW_DIMENSIONS_NOT_COMPLETE")
        if not isinstance(checks, dict) or any(checks.get(key) != "PASS" for key in REQUIRED_CHECKS):
            return outcome("REVIEW_INCOMPLETE", "REVIEW_DIMENSIONS_NOT_COMPLETE")
        evidence = review.get("evidence")
        if not isinstance(evidence, dict) or any(not isinstance(evidence.get(key), list) or not evidence[key] or not all(isinstance(ref, str) and ref.strip() for ref in evidence[key]) for key in REQUIRED_CHECKS):
            return outcome("REVIEW_INCOMPLETE", "REVIEW_EVIDENCE_MISSING")
        if review.get("critical_sources_checked") is not True:
            return outcome("REVIEW_INCOMPLETE", "CRITICAL_SOURCE_CHECK_INCOMPLETE")
        if review.get("anomalies") or review.get("verdict") == "HOLD":
            return outcome("HOLD", "REVIEW_ANOMALY")
        result["reviewer_agent"] = review["reviewer_agent"]
        result["reviewer_model"] = review["reviewer_model"]
        result["reviewed_at"] = reviewed.isoformat()
        result["received_message_id"] = message["message_id"]
        return outcome("PASS", "SHADOW_COMPLETE_ATTESTATION_ONLY")
    except (TypeError, ValueError, AttributeError, KeyError):
        return outcome("WORK_REVIEW_ERROR", "MALFORMED_REVIEW_EVIDENCE")


def record_shadow_review(candidate: Mapping[str, Any], review: Mapping[str, Any] | None, *, now: datetime) -> dict[str, Any]:
    """Append immutable shadow evidence via the existing durable safety backend."""
    from admin_safety_store import _create_json_once

    outcome = evaluate_shadow_review(candidate, review, now=now)
    # Preserve exact evidence, including unsuccessful reviews, without touching
    # owner approval fields. Inputs must contain references/hashes, never secrets.
    try:
        evidence = {"candidate": dict(candidate) if isinstance(candidate, Mapping) else None, "review": dict(review) if isinstance(review, Mapping) else None}
        canonical = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        evidence_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        record = {**outcome, "evidence_sha256": evidence_hash, "evidence": evidence}
        record_hash = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        record["shadow_record_id"] = record_hash
        created = _create_json_once(f"delegated_shadow_reviews/{record_hash}.json", record)
        return {**record, "record_created": created}
    except Exception:
        # No successful review-record assertion survives failed durable storage.
        return {**outcome, "verdict": "WORK_REVIEW_ERROR", "reason_codes": ["SHADOW_EVIDENCE_STORE_FAILED"], "record_created": False}


def delegated_send_gate(*, operating_mode: str = "manual", **_untrusted_inputs: Any) -> dict[str, Any]:
    """Legacy shadow API cannot authorize send; use the authenticated worker."""
    return {
        "allowed": False,
        "operating_mode": operating_mode,
        "reason_code": "SHADOW_API_HAS_NO_SEND_AUTHORITY",
    }
