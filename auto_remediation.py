"""Bounded automatic remediation of reviewable natural-run output.

The owner should not have to press "reissue" for a defect the system itself
detected. When a NATURAL scheduled run lands in REVIEW_REQUIRED or
PRODUCT_REVIEW_REQUIRED and the defect is one an existing bounded reissue path
can repair, the system performs **exactly one** remediation attempt on its own,
creates a child artifact, and sends a corrected owner-review email.

Three invariants hold no matter what happens here:

* **Customer send is never performed.** Remediation produces owner-review
  output only; applicable manual/delegated safety gates cover customer email,
  and the child needs its own fresh applicable review authority.
* **At most one automatic attempt per natural parent.** The attempt counter
  lives on the parent artifact and is stamped *before* the runner is invoked,
  so a crash mid-attempt cannot yield a second one. Children are never
  auto-remediated, so no child-of-child can be generated.
* **Fail closed.** Hard fails, corrupt artifacts, safety/finance issues,
  missing evidence and unclassifiable issue codes all stop remediation and
  leave the owner the manual reissue path plus a failure report.
"""
from __future__ import annotations

import copy
import hashlib
import html
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from admin_store import (
    load_run_artifact,
    now_kst_iso,
    reissue_parent_block_reason,
    reissue_parent_review_class,
    update_run_artifact,
)
from admin_urls import build_owner_review_admin_url
from issue_code_registry import ISSUE_CODE_REGISTRY, REPAIRABILITY_TERMINAL_BLOCK
from publishing_policy import FINANCE_SAFETY_CODES

logger = logging.getLogger(__name__)

TODAY_MODE = "today_genie"
KEYSURI_MODES = ("keysuri_global_tech", "keysuri_korea_tech")
AUTO_REMEDIATION_MAX_ATTEMPTS = 1
AUTO_REMEDIATION_TRIGGER_SOURCE = "automatic_remediation"

# Artifact fields recorded on both sides of an attempt (cost / loop forensics).
AUTO_REMEDIATION_FIELDS = (
    "automatic_remediation_triggered",
    "automatic_remediation_scope",
    "automatic_remediation_attempt_count",
    "automatic_remediation_parent_run_id",
    "automatic_remediation_child_run_id",
    "automatic_remediation_result",
)

RESULT_SUCCEEDED = "succeeded"
RESULT_CHILD_STILL_REVIEWABLE = "child_still_reviewable"
RESULT_FAILED = "failed"
RESULT_SKIPPED = "skipped"

# --- issue class -> narrowest remediation scope ----------------------------
#
# Classification is drawn from the existing authorities rather than a hand-kept
# list, so a code cannot silently drift out of the mapping:
#   * issue_code_registry           — TERMINAL_BLOCK is never auto-remediable
#   * publishing_policy             — finance/safety codes are never auto-remediable
#   * product_surface_contract      — every code is prefixed customer_surface_
# An issue code that matches none of them stops remediation (fail closed)
# rather than guessing a scope.

_PRODUCT_SURFACE_CODE_PREFIX = "customer_surface_"

_TERMINAL_REGISTRY_CODES = frozenset(
    entry.code
    for entry in ISSUE_CODE_REGISTRY
    if entry.repairability == REPAIRABILITY_TERMINAL_BLOCK
)

# Infrastructure / delivery ambiguity: regenerating content cannot repair these.
_INFRASTRUCTURE_CODES = frozenset(
    {
        "feed_json_decode_failed",
        "smtp_outcome_ambiguous",
        "customer_send_ambiguity_blocked",
        "invalid_natural_slot_match",
        "invalid_natural_slot_duplicate_match",
        "qa_consumed_natural_slot",
        "weather_input_missing",
        "stale_feed_date",
        "stale_content_date_conflict",
    }
)

# Independent evidence cannot be created by regenerating the same source set.
# Keep the product REVIEW and its dated-evidence dependency unchanged.
_EVIDENCE_DEPENDENCY_CODES = frozenset({
    "customer_surface_current_office_context_unknown",
    # A factual role mismatch requires source-backed correction; regenerating
    # from the same inputs is not independent evidence and can repeat the error.
    "customer_surface_current_office_role_mismatch",
})

NON_REMEDIABLE_ISSUE_CODES = (
    frozenset(FINANCE_SAFETY_CODES) | _TERMINAL_REGISTRY_CODES
    | _INFRASTRUCTURE_CODES | _EVIDENCE_DEPENDENCY_CODES
)

# A ``*_repaired`` code records that the pipeline already fixed something. It is
# not an outstanding defect, so it neither selects a scope nor blocks one — and
# it must not be mistaken for an unknown code. Production Korea runs routinely
# carry several (connector ellipsis, particle, repeated token), and treating
# them as unclassified would refuse remediation on every one of them.
_INFORMATIONAL_CODE_SUFFIXES = ("_repaired",)


def _is_informational_code(code: str) -> bool:
    return code.endswith(_INFORMATIONAL_CODE_SUFFIXES)

# Image defects: the body is fine, only the imagery must be regenerated.
_IMAGE_ISSUE_CODES = frozenset(
    {
        "missing_image_prompt",
        "image_perception_open",
        "TODAY_GENIE_STATIC_IMAGE_FALLBACK",
        "today_genie_static_image_fallback",
        "keysuri_top_image_missing",
        "keysuri_bottom_image_missing",
        "keysuri_image_watermark_missing",
    }
)

# Reader prose / tone / internal-label / grounding defects: body_only repairs them.
_BODY_ISSUE_CODES = frozenset(
    {
        # Today editorial + grounding
        "unanchored_briefing_vs_input_news",
        "market_fact_narrative_conflict",
        "weak_opening",
        "weak_summary",
        "low_summary_density",
        "low_interpretation_density",
        "low_watchpoint_density",
        "low_risk_density",
        "repetitive_market_generalities",
        "generic_filler_despite_full_feeds",
        "risk_lecture_tail",
        "watchpoint_lecture_tail",
        "summary_lecture_tail",
        "closing_lecture_tail",
        "thin_input_briefing_inadequate",
        "overconfident_with_thin_input",
        "authority_exceeds_input_support",
        "risk_section_weak",
        "thin_input",
        "missing_decision_line",
        "deterministic_fortune",
        "hashtag_empty",
        "missing_hashtags",
    }
)

# This graded Global editorial residual is not in ISSUE_CODE_REGISTRY. Permit
# only this exact reader-prose defect to select body_only; never classify every
# global_visible_* code, because that prefix also includes hard blocks.
_GLOBAL_VISIBLE_BODY_ISSUE_CODES = frozenset(
    {"global_visible_repeated_low_information_label"}
)

# Registry stages whose defects live in generated text.
_BODY_REGISTRY_STAGES = frozenset(
    {
        "generation",
        "generation_validation",
        "parse_repair",
        "post_render_visible_text",
        "visible_text_quality",
        "selection",
    }
)

_BODY_REGISTRY_CODES = frozenset(
    entry.code
    for entry in ISSUE_CODE_REGISTRY
    if entry.repairability != REPAIRABILITY_TERMINAL_BLOCK
    and entry.stage in _BODY_REGISTRY_STAGES
)

SCOPE_BODY_ONLY = "body_only"
SCOPE_IMAGE_ONLY = "image_only"
SCOPE_BODY_AND_IMAGE = "body_and_image"


def _auto_remediation_enabled() -> bool:
    raw = os.getenv("GENIE_AUTO_REMEDIATION", "").strip().lower()
    if not raw:
        return True
    return raw not in {"0", "false", "no", "off"}


def _manual_runs_allowed() -> bool:
    """QA/manual runs stay out of scope unless explicitly configured (§9)."""
    raw = os.getenv("GENIE_AUTO_REMEDIATION_ALLOW_MANUAL", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _editorial_verdict_holds_for_review(meta: Dict[str, Any]) -> bool:
    """Runtime-pass artifacts can still be held by graded editorial review."""
    return str(meta.get("editorial_verdict") or "").strip().lower() == "review"


def artifact_issue_codes(meta: Dict[str, Any]) -> List[str]:
    """Every distinct issue code the artifact carries, order preserved."""
    codes: List[str] = []
    seen = set()
    for key in (
        "issue_codes",
        "validation_issue_codes",
        "terminal_issue_codes",
        "review_issue_codes",
        "product_surface_issue_codes",
    ):
        raw = meta.get(key)
        if not isinstance(raw, list):
            continue
        for value in raw:
            code = str(value or "").strip()
            if code and code not in seen:
                seen.add(code)
                codes.append(code)
    return codes


def classify_issue_codes(
    codes: Sequence[str],
) -> Tuple[Optional[str], List[str], List[str]]:
    """Return ``(scope, blocking_codes, unclassified_codes)``.

    ``scope`` is the narrowest remediation that covers every code, or None when
    any code is non-remediable or unclassifiable.
    """
    blocking: List[str] = []
    unclassified: List[str] = []
    needs_body = False
    needs_image = False

    for raw in codes:
        code = str(raw or "").strip()
        if not code:
            continue
        if _is_informational_code(code):
            continue
        if code in NON_REMEDIABLE_ISSUE_CODES:
            blocking.append(code)
            continue
        if code in _IMAGE_ISSUE_CODES:
            needs_image = True
            continue
        if (
            code.startswith(_PRODUCT_SURFACE_CODE_PREFIX)
            or code in _BODY_ISSUE_CODES
            or code in _GLOBAL_VISIBLE_BODY_ISSUE_CODES
            or code in _BODY_REGISTRY_CODES
        ):
            needs_body = True
            continue
        unclassified.append(code)

    if blocking or unclassified:
        return None, blocking, unclassified
    if needs_body and needs_image:
        return SCOPE_BODY_AND_IMAGE, [], []
    if needs_image:
        return SCOPE_IMAGE_ONLY, [], []
    if needs_body:
        return SCOPE_BODY_ONLY, [], []
    return None, [], []


@dataclass(frozen=True)
class AutoRemediationPlan:
    """Whether this artifact gets one automatic remediation, and how."""

    eligible: bool
    scope: Optional[str] = None
    stop_reason: Optional[str] = None
    review_class: str = ""
    issue_codes: List[str] = field(default_factory=list)
    blocking_codes: List[str] = field(default_factory=list)
    unclassified_codes: List[str] = field(default_factory=list)


def _delegated_review_repair_boundary(meta: Dict[str, Any]) -> Optional[str]:
    """Only unfrozen candidates may use automatic generation repair.

    The trusted received-mail binding survives a later verdict and a process
    restart. A Work-held or already-reviewed candidate must enter manual
    recovery; content changes can never inherit its old review.
    """
    if meta.get("delegated_review_status") or meta.get("delegated_review_id"):
        return "delegated_review_requires_manual_recovery"
    run_id = str(meta.get("run_id") or "")
    if not run_id:
        return None  # Existing structural eligibility checks handle this case.
    try:
        import admin_safety_store as store
        key = "delegated_received_bindings/" + hashlib.sha256(run_id.encode()).hexdigest() + ".json"
        exists = (store._get_gcs_bucket().blob(store.SAFETY_PREFIX + "/" + key).exists()
                  if store._uses_gcs_backend() else store._local_path(key).exists())
        if exists:
            return "delegated_candidate_frozen_manual_recovery_required"
    except Exception:
        return "delegated_review_boundary_unavailable"
    return None


def _parse_strict_positive_count(val: Any) -> Optional[int]:
    """Strictly parse integer count >= 0; booleans, floats, negatives, and non-digits raise ValueError."""
    if val in (None, "", False):
        return None
    if isinstance(val, bool):
        raise ValueError("boolean is not a count")
    if isinstance(val, (int, str)):
        s = str(val).strip()
        if not s.isdigit():
            raise ValueError(f"malformed count: {val!r}")
        n = int(s)
        return n if n > 0 else 0
    raise ValueError(f"malformed count type: {type(val)!r}")


def _durable_delivery_and_approval_boundaries(meta: Dict[str, Any]) -> Optional[str]:
    """Check approval, received binding, delivery claims, and publication boundaries.

    Authoritative boundaries fail closed on read errors, distinguish absent
    objects, and stop stale passed-in metadata from triggering remediation.
    """
    # 1. Lineage check: parent_run_id, regen_parent_run_id, automatic_remediation_parent_run_id, and automatic_remediation_is_child
    meta_run_id = str(meta.get("run_id") or "").strip()
    auto_parent_id = str(meta.get("automatic_remediation_parent_run_id") or "").strip()
    is_auto_child = bool(auto_parent_id and auto_parent_id != meta_run_id)
    if (
        str(meta.get("parent_run_id") or "").strip()
        or str(meta.get("regen_parent_run_id") or "").strip()
        or is_auto_child
        or bool(meta.get("automatic_remediation_is_child"))
    ):
        return "already_a_remediation_child"

    # 2. Human approval present on artifact or safety snapshot
    owner_status = str(meta.get("owner_review_status") or "").strip().lower()
    if (
        owner_status == "approved"
        or meta.get("approved_at")
        or meta.get("approved_by")
        or meta.get("approval_snapshot_id")
    ):
        return "human_approval_present"

    # 3. Delegated review and received mail binding
    delegated_boundary = _delegated_review_repair_boundary(meta)
    if delegated_boundary:
        return delegated_boundary

    run_id = str(meta.get("run_id") or "").strip()
    if not run_id:
        return None

    try:
        import admin_safety_store as store

        def _exists(key: str) -> bool:
            if store._uses_gcs_backend():
                return store._get_gcs_bucket().blob(f"{store.SAFETY_PREFIX}/{key}").exists()
            return store._local_path(key).is_file()

        # 4. Delivery run claims and delivery commands
        run_claim_key = f"delivery_run_claims/{hashlib.sha256(run_id.encode('utf-8')).hexdigest()}.json"
        if _exists(run_claim_key):
            return "delivery_command_already_claimed"

        cmd_id = str(meta.get("delivery_command_id") or "").strip()
        if cmd_id and _exists(f"delivery_commands/{cmd_id}.json"):
            return "delivery_command_already_claimed"

        # 5. Durable publication reservation / outcome / reconciliation
        mode = str(meta.get("mode") or meta.get("program_id") or "").strip()
        from delegated_delivery_safety import PRODUCTS, _digest
        product = PRODUCTS.get(mode)
        if product and len(run_id) >= 8 and run_id[:8].isdigit():
            day = f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}"
            attempt_id = "publication_" + _digest([product, day])
            attempt_key = f"publication_attempts/{attempt_id}.json"
            outcome_key = f"publication_outcomes/{attempt_id}.json"
            reconcil_key = f"publication_reconciliation/{_digest([product, day])}.json"
            if _exists(attempt_key) or _exists(outcome_key) or _exists(reconcil_key):
                return "publication_already_reserved_or_accepted"

        # 6. Delivery transition journal
        journal_key = f"run_delivery_transitions/{hashlib.sha256(run_id.encode()).hexdigest()}/000.json"
        if _exists(journal_key):
            try:
                from admin_store import run_delivery_transition
                transition = run_delivery_transition(run_id, action="READ")
                if not transition.get("allowed") or transition.get("state") == "SUBMITTED":
                    return "delivery_handoff_already_claimed"
            except Exception:
                return "delegated_review_boundary_unavailable"

    except Exception:
        logger.exception("auto_remediation: durable boundary check failed run_id=%s", run_id)
        return "delegated_review_boundary_unavailable"

    # 7. Customer delivery status, counts, and attempted flags on artifact
    delivery_statuses = {
        str(meta.get("customer_delivery_status") or "").strip().lower(),
        str(meta.get("customer_email_delivery_status") or "").strip().lower(),
    } - {"", "not_sent"}
    attempted_statuses = {
        "smtp_accepted",
        "sent_after_approval",
        "approved",
        "submitted",
        "accepted_all",
        "partial_refusal",
        "refused_all",
        "outcome_unknown",
        "send_attempted",
        "sending",
        "pending",
        "customer_sent_after_approval",
        "sent_after_owner_approval",
    }
    if delivery_statuses & attempted_statuses:
        return "customer_delivery_already_attempted"

    if (
        bool(meta.get("customer_email_smtp_attempted"))
        or bool(meta.get("smtp_attempted"))
        or bool(meta.get("customer_email_delivery_attempted"))
        or bool(meta.get("customer_delivery_attempted"))
    ):
        return "customer_delivery_already_attempted"

    for count_key in (
        "customer_delivery_accepted_count",
        "smtp_accepted_recipient_count",
        "customer_delivery_refused_count",
        "smtp_refused_recipient_count",
        "customer_delivery_unknown_count",
        "smtp_unknown_recipient_count",
        "customer_delivered_count",
        "delivered_count",
        "customer_delivery_recipient_count",
    ):
        raw_val = meta.get(count_key)
        if raw_val not in (None, "", False):
            try:
                c = _parse_strict_positive_count(raw_val)
                if c is not None and c > 0:
                    return "customer_delivery_already_attempted"
            except (TypeError, ValueError):
                # Malformed numeric value fails closed
                return "customer_delivery_already_attempted"

    return None


ALREADY_SETTLED_STOP_REASONS = frozenset({
    "human_approval_present",
    "delegated_review_requires_manual_recovery",
    "delegated_candidate_frozen_manual_recovery_required",
    "delivery_command_already_claimed",
    "delivery_handoff_already_claimed",
    "publication_already_reserved_or_accepted",
    "customer_delivery_already_attempted",
    "run_passed",
    "already_a_remediation_child",
    "not_a_natural_scheduled_run",
    "no_send_verification_run",
    "dry_run_artifact",
})


def plan_auto_remediation(meta: Optional[Dict[str, Any]]) -> AutoRemediationPlan:
    """Decide whether this artifact earns exactly one automatic remediation."""
    if not isinstance(meta, dict):
        return AutoRemediationPlan(False, stop_reason="artifact_unreadable")
    if not _auto_remediation_enabled():
        return AutoRemediationPlan(False, stop_reason="auto_remediation_disabled")

    mode = str(meta.get("mode") or meta.get("program_id") or "").strip()
    if mode != TODAY_MODE and mode not in KEYSURI_MODES:
        return AutoRemediationPlan(False, stop_reason="unsupported_mode")

    # Authoritative boundaries: approval, received bindings, delivery claims, publication
    boundary = _durable_delivery_and_approval_boundaries(meta)
    if boundary:
        return AutoRemediationPlan(False, stop_reason=boundary)

    # Only natural scheduled owner-review production runs are in scope (§9).
    if str(meta.get("execution_class") or "").strip() != "natural_scheduled":
        if not _manual_runs_allowed():
            return AutoRemediationPlan(False, stop_reason="not_a_natural_scheduled_run")
    if str(meta.get("verification_mode") or "").strip() == "no_send_verification":
        return AutoRemediationPlan(False, stop_reason="no_send_verification_run")
    if meta.get("admin_reissue_dry_run"):
        return AutoRemediationPlan(False, stop_reason="dry_run_artifact")

    # A child is never auto-remediated: that is what forbids child-of-child (§3).
    if (
        str(meta.get("parent_run_id") or "").strip()
        or str(meta.get("regen_parent_run_id") or "").strip()
        or bool(meta.get("automatic_remediation_is_child"))
    ):
        return AutoRemediationPlan(False, stop_reason="already_a_remediation_child")
    if int(meta.get("automatic_remediation_attempt_count") or 0) >= AUTO_REMEDIATION_MAX_ATTEMPTS:
        return AutoRemediationPlan(False, stop_reason="attempt_budget_exhausted")

    review_class = reissue_parent_review_class(meta)
    if review_class == "pass" and _editorial_verdict_holds_for_review(meta):
        # Planning-local: do not change the shared reissue eligibility authority.
        review_class = "review_required"
    if review_class == "pass":
        return AutoRemediationPlan(False, stop_reason="run_passed", review_class=review_class)
    if review_class not in ("review_required", "product_review_required"):
        return AutoRemediationPlan(
            False, stop_reason=f"review_class_{review_class}", review_class=review_class
        )

    codes = artifact_issue_codes(meta)
    scope, blocking, unclassified = classify_issue_codes(codes)
    if scope is None:
        reason = "non_remediable_issue_code" if blocking else "unclassified_issue_code"
        if not codes:
            reason = "no_issue_codes_to_remediate"
        return AutoRemediationPlan(
            False,
            stop_reason=reason,
            review_class=review_class,
            issue_codes=codes,
            blocking_codes=blocking,
            unclassified_codes=unclassified,
        )

    # Structural usability and preserved evidence, from the single eligibility
    # authority the manual reissue entry also uses.
    block = reissue_parent_block_reason(meta, scope=scope)
    if block is not None:
        return AutoRemediationPlan(
            False,
            stop_reason=block,
            review_class=review_class,
            issue_codes=codes,
        )

    return AutoRemediationPlan(
        True, scope=scope, review_class=review_class, issue_codes=codes
    )


# --- corrected owner-review notice ----------------------------------------
#
# Delimited by HTML comment sentinels, exactly like the existing image_only
# reissue banner, so customer delivery can strip it cleanly. It is owner-only
# copy and must never reach a customer surface.

AUTO_REMEDIATION_NOTICE_START = "<!--auto-remediation-notice-start-->"
AUTO_REMEDIATION_NOTICE_END = "<!--auto-remediation-notice-end-->"
AUTO_REMEDIATION_NOTICE_RE = re.compile(
    r"<!--auto-remediation-notice-start-->.*?<!--auto-remediation-notice-end-->",
    re.IGNORECASE | re.DOTALL,
)

_SCOPE_LABELS_KO = {
    SCOPE_BODY_ONLY: "본문만 재생성 (body_only)",
    SCOPE_IMAGE_ONLY: "이미지만 재생성 (image_only)",
    SCOPE_BODY_AND_IMAGE: "본문·이미지 재생성 (body_and_image)",
}


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def auto_remediation_owner_notice_html(
    *,
    parent_run_id: str,
    scope: str,
    original_issue_codes: Sequence[str],
    current_result: str,
) -> str:
    """The 자동 교정본 header the corrected owner-review email carries (§5)."""
    codes = ", ".join(str(c) for c in original_issue_codes if str(c or "").strip()) or "없음"
    row = (
        '<p style="margin:0 0 6px 0;font-size:13px;line-height:1.6;color:#334155;">'
        '<span style="display:inline-block;min-width:9em;color:#475569;font-weight:700;">{label}</span>'
        '<span style="color:#1e293b;">{value}</span></p>'
    )
    return (
        f"{AUTO_REMEDIATION_NOTICE_START}"
        '<section id="genie-auto-remediation-notice" aria-label="자동 교정본"'
        ' style="margin:0 0 20px 0;padding:16px 18px;border:1px solid #f59e0b;'
        'border-radius:10px;background:#fffbeb;">'
        '<p style="margin:0 0 10px 0;font-size:14px;font-weight:800;color:#92400e;">자동 교정본</p>'
        + row.format(label="Parent run", value=_esc(parent_run_id))
        + row.format(label="Remediation", value=_esc(_SCOPE_LABELS_KO.get(scope, scope)))
        + row.format(label="Original issue", value=_esc(codes))
        + row.format(label="Current result", value=_esc(current_result))
        + '<p style="margin:10px 0 0 0;font-size:12px;line-height:1.6;color:#92400e;">'
        "이전 고객 승인은 이 교정본으로 이전되지 않습니다. 고객 발송은 이 실행에 대한 "
        "새 운영자 승인 전까지 차단됩니다.</p>"
        "</section>"
        f"{AUTO_REMEDIATION_NOTICE_END}"
    )


def strip_auto_remediation_notice(html_text: str) -> str:
    """Remove the owner-only 자동 교정본 block before any customer surface."""
    return AUTO_REMEDIATION_NOTICE_RE.sub("", str(html_text or ""))


# --- execution -------------------------------------------------------------


def _stamp(run_id: str, fields: Dict[str, Any]) -> None:
    try:
        update_run_artifact(run_id, lambda m: m.update(fields))
    except Exception:  # noqa: BLE001 - never let bookkeeping break the run
        logger.exception("auto_remediation: metadata stamp failed run_id=%s", run_id)


def _default_runners() -> Dict[Tuple[str, str], Callable[..., Dict[str, Any]]]:
    from today_genie_reissue import (
        run_today_body_only_reissue,
        run_today_image_only_reissue,
    )
    from keysuri_service_full_run import (
        run_keysuri_image_only_reissue,
        run_keysuri_text_and_image_reissue,
        run_keysuri_text_only_reissue,
    )

    runners: Dict[Tuple[str, str], Callable[..., Dict[str, Any]]] = {
        (TODAY_MODE, SCOPE_BODY_ONLY): run_today_body_only_reissue,
        (TODAY_MODE, SCOPE_IMAGE_ONLY): run_today_image_only_reissue,
        (TODAY_MODE, SCOPE_BODY_AND_IMAGE): _today_full_reissue,
    }
    for mode in KEYSURI_MODES:
        runners[(mode, SCOPE_BODY_ONLY)] = run_keysuri_text_only_reissue
        runners[(mode, SCOPE_IMAGE_ONLY)] = run_keysuri_image_only_reissue
        runners[(mode, SCOPE_BODY_AND_IMAGE)] = run_keysuri_text_and_image_reissue
    return runners


def _today_full_reissue(
    parent_run_id: str,
    *,
    parent_meta: Optional[Dict[str, Any]] = None,
    reissue_reason_code: str = "",
    reissue_reason_note: str = "",
    send_owner_email: bool = True,
    owner_email_notice_html: Optional[str] = None,
    **_ignored: Any,
) -> Dict[str, Any]:
    """Today body_and_image goes through the normal orchestrator reissue path."""
    from orchestrator import execute_orchestrator_run

    reason = reissue_reason_code
    if reissue_reason_note:
        reason = f"{reason} — {reissue_reason_note}" if reason else reissue_reason_note
    child_run_id, _result, email_sent = execute_orchestrator_run(
        TODAY_MODE,
        parent_run_id=parent_run_id,
        reissue_reason=reason or None,
        admin_reissue=True,
        send_owner_email=send_owner_email,
        reissue_scope=SCOPE_BODY_AND_IMAGE,
        owner_email_notice_html=owner_email_notice_html,
    )
    return {"ok": bool(child_run_id), "run_id": child_run_id, "email_sent": bool(email_sent)}


def _child_outcome(child_meta: Optional[Dict[str, Any]]) -> Tuple[str, str, List[str]]:
    """Return ``(result, current_result_label, remaining_issue_codes)``."""
    if not isinstance(child_meta, dict):
        return RESULT_FAILED, "UNKNOWN", []
    review_class = reissue_parent_review_class(child_meta)
    remaining = artifact_issue_codes(child_meta)
    if review_class == "pass" and _editorial_verdict_holds_for_review(child_meta):
        return RESULT_CHILD_STILL_REVIEWABLE, "REVIEW_REQUIRED", remaining
    if review_class == "pass" and str(child_meta.get("editorial_verdict") or "").strip().upper() == "POOR":
        return RESULT_FAILED, "EDITORIAL_POOR", remaining
    if review_class == "pass":
        return RESULT_SUCCEEDED, "PASS", remaining
    if review_class in ("review_required", "product_review_required"):
        return RESULT_CHILD_STILL_REVIEWABLE, review_class.upper(), remaining
    return RESULT_FAILED, review_class.upper(), remaining


def run_auto_remediation(
    run_id: str,
    *,
    meta: Optional[Dict[str, Any]] = None,
    runners: Optional[Dict[Tuple[str, str], Callable[..., Dict[str, Any]]]] = None,
    report_fn: Optional[Callable[..., bool]] = None,
) -> Dict[str, Any]:
    """Perform at most one automatic remediation for a natural run.

    Returns a JSON-safe summary. Never raises: a natural run must not fail
    because its optional self-repair could not start.
    """
    authoritative = None
    try:
        authoritative = load_run_artifact(run_id)
    except Exception:
        logger.exception("auto_remediation: artifact load error run_id=%s", run_id)
        return {
            "automatic_remediation_triggered": False,
            "automatic_remediation_scope": None,
            "automatic_remediation_attempt_count": 0,
            "automatic_remediation_parent_run_id": run_id,
            "automatic_remediation_child_run_id": None,
            "automatic_remediation_result": RESULT_SKIPPED,
            "stop_reason": "artifact_read_error",
            "review_class": "hard_fail",
        }
    if not isinstance(authoritative, dict):
        return {
            "automatic_remediation_triggered": False,
            "automatic_remediation_scope": None,
            "automatic_remediation_attempt_count": 0,
            "automatic_remediation_parent_run_id": run_id,
            "automatic_remediation_child_run_id": None,
            "automatic_remediation_result": RESULT_SKIPPED,
            "stop_reason": "artifact_not_found",
            "review_class": "hard_fail",
        }
    parent = authoritative
    plan = plan_auto_remediation(parent)
    summary: Dict[str, Any] = {
        "automatic_remediation_triggered": False,
        "automatic_remediation_scope": plan.scope,
        "automatic_remediation_attempt_count": int(
            (parent or {}).get("automatic_remediation_attempt_count") or 0
        ),
        "automatic_remediation_parent_run_id": run_id,
        "automatic_remediation_child_run_id": None,
        "automatic_remediation_result": RESULT_SKIPPED,
        "stop_reason": plan.stop_reason,
        "review_class": plan.review_class,
    }

    if not plan.eligible:
        # Only record a stop on artifacts that were genuinely candidates; a
        # passing or out-of-scope run should not carry remediation bookkeeping.
        if plan.review_class in ("review_required", "product_review_required"):
            _stamp(
                run_id,
                {
                    "automatic_remediation_triggered": False,
                    "automatic_remediation_result": RESULT_SKIPPED,
                    "automatic_remediation_stop_reason": plan.stop_reason,
                    "automatic_remediation_attempt_count": summary[
                        "automatic_remediation_attempt_count"
                    ],
                },
            )
            if plan.stop_reason not in ALREADY_SETTLED_STOP_REASONS:
                _send_remediation_report(
                    parent_run_id=run_id,
                    child_run_id=None,
                    scope=None,
                    attempted=False,
                    stop_reason=plan.stop_reason or "not_eligible",
                    remaining_issue_codes=plan.issue_codes,
                    report_fn=report_fn,
                )
        logger.info(
            "auto_remediation: skipped run_id=%s reason=%s review_class=%s",
            run_id,
            plan.stop_reason,
            plan.review_class,
        )
        return summary

    scope = str(plan.scope)
    mode = str((parent or {}).get("mode") or (parent or {}).get("program_id") or "").strip()
    runner_map = runners if runners is not None else _default_runners()
    runner = runner_map.get((mode, scope))
    if runner is None:
        summary["stop_reason"] = "scope_not_supported_for_mode"
        _stamp(
            run_id,
            {
                "automatic_remediation_triggered": False,
                "automatic_remediation_result": RESULT_SKIPPED,
                "automatic_remediation_stop_reason": "scope_not_supported_for_mode",
            },
        )
        _send_remediation_report(
            parent_run_id=run_id,
            child_run_id=None,
            scope=scope,
            attempted=False,
            stop_reason="scope_not_supported_for_mode",
            remaining_issue_codes=plan.issue_codes,
            report_fn=report_fn,
        )
        return summary

    # Recheck authoritative parent before spending the attempt
    fresh_parent = None
    try:
        fresh_parent = load_run_artifact(run_id)
    except Exception:
        fresh_parent = None
    if not isinstance(fresh_parent, dict):
        summary["stop_reason"] = "artifact_not_found"
        return summary
    recheck_parent = fresh_parent
    recheck_plan = plan_auto_remediation(recheck_parent)
    if not recheck_plan.eligible:
        summary["stop_reason"] = recheck_plan.stop_reason
        summary["review_class"] = recheck_plan.review_class
        _stamp(
            run_id,
            {
                "automatic_remediation_triggered": False,
                "automatic_remediation_result": RESULT_SKIPPED,
                "automatic_remediation_stop_reason": recheck_plan.stop_reason,
                "automatic_remediation_attempt_count": summary[
                    "automatic_remediation_attempt_count"
                ],
            },
        )
        if recheck_plan.stop_reason not in ALREADY_SETTLED_STOP_REASONS:
            _send_remediation_report(
                parent_run_id=run_id,
                child_run_id=None,
                scope=None,
                attempted=False,
                stop_reason=recheck_plan.stop_reason or "not_eligible",
                remaining_issue_codes=recheck_plan.issue_codes,
                report_fn=report_fn,
            )
        return summary

    # Spend the single attempt BEFORE invoking the runner. A crash inside
    # generation must not leave a budget behind for a second automatic try.
    attempt_count = AUTO_REMEDIATION_MAX_ATTEMPTS
    _stamp(
        run_id,
        {
            "automatic_remediation_triggered": True,
            "automatic_remediation_scope": scope,
            "automatic_remediation_attempt_count": attempt_count,
            "automatic_remediation_parent_run_id": run_id,
            "automatic_remediation_child_run_id": None,
            "automatic_remediation_result": "in_progress",
            "automatic_remediation_started_at": now_kst_iso(),
            "automatic_remediation_original_issue_codes": list(plan.issue_codes),
            "automatic_remediation_stop_reason": None,
        },
    )
    summary["automatic_remediation_triggered"] = True
    summary["automatic_remediation_scope"] = scope
    summary["automatic_remediation_attempt_count"] = attempt_count

    notice = auto_remediation_owner_notice_html(
        parent_run_id=run_id,
        scope=scope,
        original_issue_codes=plan.issue_codes,
        current_result="자동 교정 실행 결과는 아래 검수 항목을 확인하세요",
    )

    kwargs: Dict[str, Any] = {
        "parent_meta": parent,
        "reissue_reason_code": "automatic_remediation",
        "reissue_reason_note": f"auto: {', '.join(plan.issue_codes) or 'review_required'}",
        "send_owner_email": True,
        "owner_email_notice_html": notice,
    }
    if mode in KEYSURI_MODES and scope == SCOPE_BODY_ONLY:
        # §4: never recollect news for a body-only defect when the parent's
        # own source snapshot is intact.
        kwargs["frozen_parent"] = True

    # Recheck fresh authoritative parent immediately before runner
    runner_preflight_parent = None
    try:
        runner_preflight_parent = load_run_artifact(run_id)
    except Exception:
        runner_preflight_parent = None
    if not isinstance(runner_preflight_parent, dict):
        summary["automatic_remediation_result"] = RESULT_SKIPPED
        summary["stop_reason"] = "artifact_not_found"
        return summary
    runner_parent = runner_preflight_parent
    final_boundary = _durable_delivery_and_approval_boundaries(runner_parent)
    if final_boundary:
        _stamp(
            run_id,
            {
                "automatic_remediation_result": RESULT_SKIPPED,
                "automatic_remediation_stop_reason": final_boundary,
                "automatic_remediation_completed_at": now_kst_iso(),
            },
        )
        summary["automatic_remediation_result"] = RESULT_SKIPPED
        summary["stop_reason"] = final_boundary
        return summary

    try:
        result = runner(run_id, **kwargs)
    except Exception:  # noqa: BLE001
        logger.exception(
            "auto_remediation: runner raised run_id=%s mode=%s scope=%s", run_id, mode, scope
        )
        result = {"ok": False, "error": "auto_remediation_runner_exception"}

    child_run_id = str((result or {}).get("run_id") or "").strip()
    runner_error = str((result or {}).get("error") or "").strip()
    failure_diagnostics: Dict[str, Any] = {}
    failed_sections = (result or {}).get("reissue_top5_repair_failed_sections")
    if isinstance(failed_sections, list):
        # Internal parser codes only; never raw model text, mail or exception detail.
        failure_diagnostics["automatic_remediation_failed_section_codes"] = [
            code for code in failed_sections
            if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_]{1,96}", code)
        ]
    generation_diagnostics = (result or {}).get("reissue_generation_diagnostics")
    if isinstance(generation_diagnostics, dict):
        # The service runner already applies its existing diagnostic allowlist.
        failure_diagnostics["automatic_remediation_generation_diagnostics"] = copy.deepcopy(
            generation_diagnostics
        )
    if (result or {}).get("reissue_generation_diagnostics_status") in {"AVAILABLE", "UNAVAILABLE"}:
        failure_diagnostics["automatic_remediation_generation_diagnostics_status"] = result[
            "reissue_generation_diagnostics_status"
        ]
    summary.update(failure_diagnostics)
    child_meta = load_run_artifact(child_run_id) if child_run_id else None

    if not (result or {}).get("ok") or not child_run_id:
        _stamp(
            run_id,
            {
                "automatic_remediation_child_run_id": child_run_id or None,
                "automatic_remediation_result": RESULT_FAILED,
                "automatic_remediation_stop_reason": runner_error or "remediation_failed",
                "automatic_remediation_completed_at": now_kst_iso(),
                **failure_diagnostics,
            },
        )
        summary["automatic_remediation_child_run_id"] = child_run_id or None
        summary["automatic_remediation_result"] = RESULT_FAILED
        summary["stop_reason"] = runner_error or "remediation_failed"

        (
            parent_already_accepted,
            parent_partial_or_unknown,
            parent_approved,
            stop_reason_report,
        ) = _evaluate_parent_for_remediation_report(run_id, summary["stop_reason"])

        _send_remediation_report(
            parent_run_id=run_id,
            child_run_id=child_run_id or None,
            scope=scope,
            attempted=True,
            stop_reason=stop_reason_report,
            remaining_issue_codes=artifact_issue_codes(child_meta or {}) or plan.issue_codes,
            report_fn=report_fn,
            parent_already_accepted=parent_already_accepted,
            parent_partial_or_unknown=parent_partial_or_unknown,
            parent_approved=parent_approved,
        )
        return summary

    outcome, current_label, remaining = _child_outcome(child_meta)

    # The child records its own provenance and is itself never auto-remediated
    # (plan_auto_remediation stops on parent_run_id), so no child-of-child.
    _stamp(
        child_run_id,
        {
            "automatic_remediation_triggered": True,
            "automatic_remediation_scope": scope,
            "automatic_remediation_attempt_count": attempt_count,
            "automatic_remediation_parent_run_id": run_id,
            "automatic_remediation_child_run_id": child_run_id,
            "automatic_remediation_result": outcome,
            "automatic_remediation_original_issue_codes": list(plan.issue_codes),
            "automatic_remediation_is_child": True,
            # A corrected child never inherits the parent's approval.
            "owner_review_status": "pending_review",
            "customer_delivery_status": "not_sent",
            "approved_at": None,
            "approved_by": None,
            "approval_snapshot_id": None,
            **failure_diagnostics,
        },
    )
    _stamp(
        run_id,
        {
            "automatic_remediation_child_run_id": child_run_id,
            "automatic_remediation_result": outcome,
            "automatic_remediation_completed_at": now_kst_iso(),
            **failure_diagnostics,
        },
    )
    summary["automatic_remediation_child_run_id"] = child_run_id
    summary["automatic_remediation_result"] = outcome
    summary["child_current_result"] = current_label
    summary["child_remaining_issue_codes"] = remaining

    if outcome != RESULT_SUCCEEDED:
        # STOP: no second automatic attempt, owner gets the report instead (§3).
        (
            parent_already_accepted,
            parent_partial_or_unknown,
            parent_approved,
            stop_reason_report,
        ) = _evaluate_parent_for_remediation_report(run_id, f"child_{current_label.lower()}")

        _send_remediation_report(
            parent_run_id=run_id,
            child_run_id=child_run_id,
            scope=scope,
            attempted=True,
            stop_reason=stop_reason_report,
            remaining_issue_codes=remaining,
            report_fn=report_fn,
            child_review_state=(outcome == RESULT_CHILD_STILL_REVIEWABLE),
            parent_already_accepted=parent_already_accepted,
            parent_partial_or_unknown=parent_partial_or_unknown,
            parent_approved=parent_approved,
        )
    logger.info(
        "auto_remediation: run_id=%s scope=%s child=%s result=%s remaining=%s",
        run_id,
        scope,
        child_run_id,
        outcome,
        remaining,
    )
    return summary


def _evaluate_parent_for_remediation_report(
    run_id: str,
    stop_reason_default: str,
) -> Tuple[bool, bool, bool, str]:
    """Inspect authoritative parent and durable publication outcomes for report notice.

    Returns (parent_already_accepted, parent_partial_or_unknown, parent_approved, stop_reason_report)
    """
    racing_parent = None
    authoritative_read_error = False
    try:
        racing_parent = load_run_artifact(run_id)
        if racing_parent is None:
            authoritative_read_error = True
    except Exception:
        racing_parent = None
        authoritative_read_error = True

    if authoritative_read_error:
        return (
            False,
            True,
            False,
            "authoritative_verification_unavailable_reconciliation_required",
        )

    racing_meta = racing_parent or {}
    owner_status = str(racing_meta.get("owner_review_status") or "").strip().lower()
    parent_approved = bool(
        owner_status == "approved"
        or racing_meta.get("approved_at")
        or racing_meta.get("approved_by")
    )

    parent_delivery_statuses = {
        str(racing_meta.get("customer_delivery_status") or "").strip().lower(),
        str(racing_meta.get("customer_email_delivery_status") or "").strip().lower(),
    } - {"", "not_sent"}

    accepted_statuses = {
        "smtp_accepted",
        "sent_after_approval",
        "accepted_all",
        "customer_sent_after_approval",
        "sent_after_owner_approval",
    }
    parent_accepted_status = bool(parent_delivery_statuses & accepted_statuses)

    partial_or_unknown_statuses = {
        "partial_refusal",
        "outcome_unknown",
        "unknown",
        "refused_all",
        "submitted",
        "send_attempted",
        "sending",
        "pending",
    }
    parent_partial_status = bool(parent_delivery_statuses & partial_or_unknown_statuses)

    has_smtp_attempt_flag = (
        bool(racing_meta.get("customer_email_smtp_attempted"))
        or bool(racing_meta.get("smtp_attempted"))
        or bool(racing_meta.get("customer_email_delivery_attempted"))
        or bool(racing_meta.get("customer_delivery_attempted"))
    )

    has_false_smtp_boolean = (
        racing_meta.get("customer_email_smtp_attempted") is False
        or racing_meta.get("smtp_attempted") is False
    )
    conflict = False
    try:
        from admin_store import customer_delivery_evidence_conflict
        if customer_delivery_evidence_conflict(racing_meta):
            conflict = True
    except Exception:
        pass
    contradictory_evidence = (has_false_smtp_boolean and parent_accepted_status) or conflict

    pos_accepted_count = False
    pos_refused_count = False
    pos_unknown_count = False
    malformed_count = False

    for count_key in (
        "customer_delivery_accepted_count",
        "smtp_accepted_recipient_count",
        "customer_delivered_count",
        "delivered_count",
    ):
        raw_c = racing_meta.get(count_key)
        if raw_c not in (None, "", False):
            try:
                c = _parse_strict_positive_count(raw_c)
                if c is not None and c > 0:
                    pos_accepted_count = True
            except (TypeError, ValueError):
                malformed_count = True

    for count_key in ("customer_delivery_refused_count", "smtp_refused_recipient_count"):
        raw_c = racing_meta.get(count_key)
        if raw_c not in (None, "", False):
            try:
                c = _parse_strict_positive_count(raw_c)
                if c is not None and c > 0:
                    pos_refused_count = True
            except (TypeError, ValueError):
                malformed_count = True

    for count_key in ("customer_delivery_unknown_count", "smtp_unknown_recipient_count"):
        raw_c = racing_meta.get(count_key)
        if raw_c not in (None, "", False):
            try:
                c = _parse_strict_positive_count(raw_c)
                if c is not None and c > 0:
                    pos_unknown_count = True
            except (TypeError, ValueError):
                malformed_count = True

    outcome_accepted = False
    outcome_unknown_or_refused = False
    durable_store_error = False
    try:
        import admin_safety_store as s_store
        from delegated_delivery_safety import PRODUCTS, _digest
        s_mode = str(racing_meta.get("mode") or racing_meta.get("program_id") or "").strip()
        s_product = PRODUCTS.get(s_mode)
        if s_product and len(run_id) >= 8 and run_id[:8].isdigit():
            s_day = f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}"
            s_att = "publication_" + _digest([s_product, s_day])
            def _s_exists(k: str) -> bool:
                if s_store._uses_gcs_backend():
                    return s_store._get_gcs_bucket().blob(f"{s_store.SAFETY_PREFIX}/{k}").exists()
                return s_store._local_path(k).is_file()

            outcome_key = f"publication_outcomes/{s_att}.json"
            attempt_key = f"publication_attempts/{s_att}.json"
            reconcil_key = f"publication_reconciliation/{_digest([s_product, s_day])}.json"

            if _s_exists(outcome_key):
                try:
                    if s_store._uses_gcs_backend():
                        raw_bytes = s_store._get_gcs_bucket().blob(f"{s_store.SAFETY_PREFIX}/{outcome_key}").download_as_text()
                    else:
                        raw_bytes = s_store._local_path(outcome_key).read_text(encoding="utf-8")
                    data = json.loads(raw_bytes)
                    if isinstance(data, dict):
                        data_att = str(data.get("attempt_id") or "").strip()
                        o_outcome = str(data.get("outcome") or data.get("status") or "").strip().upper()
                        o_deliv = str(data.get("customer_delivery_status") or "").strip().lower()
                        # Strict attempt_id match: cannot be missing or different
                        if not data_att or data_att != s_att:
                            outcome_unknown_or_refused = True
                        elif o_outcome in {"UNKNOWN_AFTER_SUBMIT", "UNKNOWN", "PROVIDER_REJECTED", "REFUSED_ALL", "NOT_SUBMITTED_FINAL_GUARD_BLOCKED"}:
                            outcome_unknown_or_refused = True
                        elif o_outcome == "PROVIDER_ACCEPTED":
                            # Verify attempt binding: publication_attempts/{s_att}.json must exist and match this run_id
                            attempt_matches_this_run = False
                            if _s_exists(attempt_key):
                                try:
                                    if s_store._uses_gcs_backend():
                                        att_bytes = s_store._get_gcs_bucket().blob(f"{s_store.SAFETY_PREFIX}/{attempt_key}").download_as_text()
                                    else:
                                        att_bytes = s_store._local_path(attempt_key).read_text(encoding="utf-8")
                                    att_data = json.loads(att_bytes)
                                    if (
                                        isinstance(att_data, dict)
                                        and str(att_data.get("run_id") or "").strip() == run_id
                                        and str(att_data.get("product_code") or "").strip() == s_product
                                        and str(att_data.get("publication_date") or "").strip() == s_day
                                    ):
                                        attempt_matches_this_run = True
                                except Exception:
                                    attempt_matches_this_run = False
                            if attempt_matches_this_run and o_deliv not in {"partial_refusal", "refused_all", "outcome_unknown", "unknown", "not_sent"}:
                                outcome_accepted = True
                            else:
                                outcome_unknown_or_refused = True
                        else:
                            outcome_unknown_or_refused = True
                    else:
                        outcome_unknown_or_refused = True
                except Exception:
                    outcome_unknown_or_refused = True
            elif _s_exists(reconcil_key) or _s_exists(attempt_key):
                outcome_unknown_or_refused = True
    except Exception:
        durable_store_error = True

    parent_refused_or_unknown_status = bool(
        parent_delivery_statuses & {"partial_refusal", "outcome_unknown", "unknown", "refused_all"}
    )
    if (
        durable_store_error
        or malformed_count
        or pos_refused_count
        or pos_unknown_count
        or outcome_unknown_or_refused
        or contradictory_evidence
        or (has_false_smtp_boolean and outcome_accepted)
        or parent_refused_or_unknown_status
        or (pos_accepted_count and pos_refused_count)
    ):
        parent_partial_or_unknown = True
        parent_already_accepted = False
        if durable_store_error:
            stop_reason_default = "authoritative_verification_unavailable_reconciliation_required"
    elif (parent_accepted_status or pos_accepted_count or outcome_accepted) and not has_false_smtp_boolean:
        parent_already_accepted = True
        parent_partial_or_unknown = False
    elif parent_partial_status or has_smtp_attempt_flag:
        parent_partial_or_unknown = True
        parent_already_accepted = False
    else:
        parent_already_accepted = False
        parent_partial_or_unknown = False

    return (
        parent_already_accepted,
        parent_partial_or_unknown,
        parent_approved,
        stop_reason_default,
    )


def build_remediation_report_html(
    *,
    parent_run_id: str,
    child_run_id: Optional[str],
    scope: Optional[str],
    attempted: bool,
    stop_reason: str,
    remaining_issue_codes: Sequence[str],
    child_review_state: bool = False,
    parent_already_accepted: bool = False,
    parent_partial_or_unknown: bool = False,
    parent_approved: bool = False,
) -> str:
    """Owner-facing incident/status report for a remediation that did not finish (§3)."""
    codes = ", ".join(str(c) for c in remaining_issue_codes if str(c or "").strip()) or "없음"
    parent_url = build_owner_review_admin_url(parent_run_id) or ""
    child_url = build_owner_review_admin_url(child_run_id) if child_run_id else ""
    row = (
        '<p style="margin:0 0 6px 0;font-size:13px;line-height:1.6;color:#334155;">'
        '<span style="display:inline-block;min-width:11em;color:#475569;font-weight:700;">{label}</span>'
        '<span style="color:#1e293b;">{value}</span></p>'
    )
    links = ""
    if parent_url:
        links += (
            f'<p style="margin:10px 0 0 0;font-size:13px;">'
            f'<a href="{_esc(parent_url)}" style="color:#2563eb;">원본 실행 열기</a></p>'
        )
    if child_url:
        links += (
            f'<p style="margin:6px 0 0 0;font-size:13px;">'
            f'<a href="{_esc(child_url)}" style="color:#2563eb;">교정본 열기</a></p>'
        )

    if parent_partial_or_unknown:
        title = "자동 교정 안내"
        color = "#1e293b"
        status_label = "Status note"
        lead_msg = (
            "원본 실행의 고객 발송 상태(시도/부분 거부/상태 불명 또는 원장 확인 불가)가 확인되었습니다. "
            "중복 발송 위험이 있으므로 즉각적인 수동 재발행을 하지 마시고, 발송 원장 상태를 먼저 확인하세요."
        )
    elif parent_already_accepted:
        title = "자동 교정 안내"
        color = "#1e293b"
        status_label = "Status note"
        lead_msg = (
            "원본 실행은 이미 고객에게 발송(SMTP 접수)되었거나 확정되었습니다. "
            "자동 교정 결과는 참고용이며, 추가 발송이나 재발행은 불필요합니다."
        )
    elif parent_approved:
        title = "자동 교정 안내"
        color = "#1e293b"
        status_label = "Status note"
        lead_msg = (
            "원본 실행은 이미 승인(검수 완료)되었습니다. "
            "교정본 생성 결과는 참고용이며, 추가적인 수동 재발행은 불필요합니다."
        )
    elif child_review_state:
        title = "자동 교정 검토 필요"
        color = "#b45309"
        status_label = "Review verdict / note"
        lead_msg = (
            "교정본이 생성되었으나 추가 운영자 검토가 필요합니다 (SAFE+REVIEW 권고). "
            "자동 교정은 실행당 1회만 수행되며 추가 자동 재시도는 하지 않습니다."
        )
    else:
        title = "자동 교정 실패"
        color = "#b91c1c"
        status_label = "Why not customer-ready"
        lead_msg = (
            "이 실행은 고객 발송 가능 상태에 도달하지 못했습니다. 자동 교정은 실행당 1회만 "
            "수행되며, 추가 자동 재시도는 하지 않습니다. 필요하면 Admin에서 수동 재발행을 "
            "사용하세요."
        )

    return (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;'
        'padding:20px;background:#ffffff;">'
        f'<h1 style="margin:0 0 14px 0;font-size:18px;color:{color};">{title}</h1>'
        f'<p style="margin:0 0 14px 0;font-size:13px;line-height:1.7;color:#334155;">{lead_msg}</p>'
        + row.format(label="Parent run", value=_esc(parent_run_id))
        + row.format(label="Child run", value=_esc(child_run_id or "생성되지 않음"))
        + row.format(
            label="Remediation",
            value=_esc(_SCOPE_LABELS_KO.get(str(scope), scope or "시도하지 않음")),
        )
        + row.format(label="Attempted", value="예" if attempted else "아니오")
        + row.format(label="Remaining issue codes", value=_esc(codes))
        + row.format(label=status_label, value=_esc(stop_reason))
        + links
        + "</div>"
    )


def _send_remediation_report(
    *,
    parent_run_id: str,
    child_run_id: Optional[str],
    scope: Optional[str],
    attempted: bool,
    stop_reason: str,
    remaining_issue_codes: Sequence[str],
    report_fn: Optional[Callable[..., bool]] = None,
    child_review_state: bool = False,
    parent_already_accepted: bool = False,
    parent_partial_or_unknown: bool = False,
    parent_approved: bool = False,
) -> bool:
    """Email the owner-facing remediation report. Owner recipients only."""
    html_body = build_remediation_report_html(
        parent_run_id=parent_run_id,
        child_run_id=child_run_id,
        scope=scope,
        attempted=attempted,
        stop_reason=stop_reason,
        remaining_issue_codes=remaining_issue_codes,
        child_review_state=child_review_state,
        parent_already_accepted=parent_already_accepted,
        parent_partial_or_unknown=parent_partial_or_unknown,
        parent_approved=parent_approved,
    )
    if parent_already_accepted or parent_partial_or_unknown or parent_approved:
        subject = f"[자동 교정 안내] {parent_run_id}"
    elif child_review_state:
        subject = f"[자동 교정 검토 필요] {parent_run_id}"
    else:
        subject = f"[자동 교정 실패] {parent_run_id}"
    sender = report_fn
    if sender is None:
        from email_sender import send_genie_email

        sender = send_genie_email
    try:
        return bool(sender(html_body, subject))
    except Exception:  # noqa: BLE001
        logger.exception(
            "auto_remediation: remediation report send failed parent=%s", parent_run_id
        )
        return False


# --- sweep -----------------------------------------------------------------
#
# Remediation runs on its own schedule, NOT inside the natural run's request.
# A natural run already takes 61-152s against a 300s Cloud Run timeout and a
# 300s scheduler deadline (measured 2026-09-06..09); a second full generation
# inline would exceed that on the tail, cutting the request mid-remediation and
# reporting a natural run that actually succeeded as a scheduler failure.

# Only very recent natural runs are swept, so enabling the mechanism can never
# stampede through a backlog of historical reviewable runs.
AUTO_REMEDIATION_SWEEP_MAX_AGE_DAYS = 1
AUTO_REMEDIATION_SWEEP_SCAN_LIMIT = 60
# One remediation per invocation keeps the sweep inside its own request budget.
AUTO_REMEDIATION_SWEEP_MAX_PER_RUN = 1


def _sweep_date_prefixes(now: Optional[Any] = None) -> List[str]:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    kst = now or datetime.now(ZoneInfo("Asia/Seoul"))
    return [
        (kst - timedelta(days=offset)).strftime("%Y%m%d_")
        for offset in range(AUTO_REMEDIATION_SWEEP_MAX_AGE_DAYS + 1)
    ]


def _sweep_shortlist(summaries: Sequence[Dict[str, Any]], prefixes: Sequence[str]) -> List[str]:
    """Cheap pre-filter over list summaries; the real decision reloads the artifact."""
    shortlist: List[str] = []
    for raw in summaries:
        if not isinstance(raw, dict):
            continue
        run_id = str(raw.get("run_id") or "").strip()
        if not run_id or not any(run_id.startswith(p) for p in prefixes):
            continue
        if str(raw.get("execution_class") or "").strip() != "natural_scheduled":
            continue
        meta_run_id = str(raw.get("run_id") or "").strip()
        auto_parent_id = str(raw.get("automatic_remediation_parent_run_id") or "").strip()
        is_auto_child = bool(auto_parent_id and auto_parent_id != meta_run_id)
        if (
            str(raw.get("parent_run_id") or "").strip()
            or str(raw.get("regen_parent_run_id") or "").strip()
            or is_auto_child
            or bool(raw.get("automatic_remediation_is_child"))
        ):
            continue
        if int(raw.get("automatic_remediation_attempt_count") or 0) >= AUTO_REMEDIATION_MAX_ATTEMPTS:
            continue
        shortlist.append(run_id)
    return shortlist


def sweep_auto_remediation(
    *,
    now: Optional[Any] = None,
    scan_limit: int = AUTO_REMEDIATION_SWEEP_SCAN_LIMIT,
    max_per_run: int = AUTO_REMEDIATION_SWEEP_MAX_PER_RUN,
    runners: Optional[Dict[Tuple[str, str], Callable[..., Dict[str, Any]]]] = None,
    report_fn: Optional[Callable[..., bool]] = None,
    list_fn: Optional[Callable[..., List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Remediate at most ``max_per_run`` recent reviewable natural runs."""
    if not _auto_remediation_enabled():
        return {
            "ok": True,
            "auto_remediation_enabled": False,
            "scanned": 0,
            "candidates": [],
            "remediated": [],
        }

    lister = list_fn
    if lister is None:
        from admin_store import list_run_artifacts

        lister = list_run_artifacts
    try:
        summaries = lister(limit=scan_limit)
    except Exception:  # noqa: BLE001
        logger.exception("auto_remediation: sweep listing failed")
        return {"ok": False, "error": "artifact_listing_failed", "remediated": []}

    prefixes = _sweep_date_prefixes(now)
    shortlist = _sweep_shortlist(summaries, prefixes)

    remediated: List[Dict[str, Any]] = []
    considered: List[Dict[str, Any]] = []
    for run_id in shortlist:
        if len(remediated) >= max_per_run:
            break
        meta = load_run_artifact(run_id)
        plan = plan_auto_remediation(meta)
        if not plan.eligible:
            considered.append({"run_id": run_id, "stop_reason": plan.stop_reason})
            continue
        summary = run_auto_remediation(
            run_id, meta=meta, runners=runners, report_fn=report_fn
        )
        remediated.append(
            {
                "run_id": run_id,
                "scope": summary.get("automatic_remediation_scope"),
                "child_run_id": summary.get("automatic_remediation_child_run_id"),
                "result": summary.get("automatic_remediation_result"),
            }
        )

    logger.info(
        "auto_remediation sweep: scanned=%s shortlisted=%s remediated=%s",
        len(summaries),
        len(shortlist),
        len(remediated),
    )
    return {
        "ok": True,
        "auto_remediation_enabled": True,
        "scanned": len(summaries),
        "shortlisted": len(shortlist),
        "candidates": considered,
        "remediated": remediated,
    }
