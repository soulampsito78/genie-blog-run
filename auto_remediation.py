"""Bounded automatic remediation of reviewable natural-run output.

The owner should not have to press "reissue" for a defect the system itself
detected. When a NATURAL scheduled run lands in REVIEW_REQUIRED or
PRODUCT_REVIEW_REQUIRED and the defect is one an existing bounded reissue path
can repair, the system performs **exactly one** remediation attempt on its own,
creates a child artifact, and sends a corrected owner-review email.

Three invariants hold no matter what happens here:

* **Customer send is never performed.** Remediation produces owner-review
  output only; ``can_approve_customer_send`` still gates every customer email,
  and the child needs its own fresh owner approval.
* **At most one automatic attempt per natural parent.** The attempt counter
  lives on the parent artifact and is stamped *before* the runner is invoked,
  so a crash mid-attempt cannot yield a second one. Children are never
  auto-remediated, so no child-of-child can be generated.
* **Fail closed.** Hard fails, corrupt artifacts, safety/finance issues,
  missing evidence and unclassifiable issue codes all stop remediation and
  leave the owner the manual reissue path plus a failure report.
"""
from __future__ import annotations

import html
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

NON_REMEDIABLE_ISSUE_CODES = (
    frozenset(FINANCE_SAFETY_CODES) | _TERMINAL_REGISTRY_CODES | _INFRASTRUCTURE_CODES
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


def plan_auto_remediation(meta: Optional[Dict[str, Any]]) -> AutoRemediationPlan:
    """Decide whether this artifact earns exactly one automatic remediation."""
    if not isinstance(meta, dict):
        return AutoRemediationPlan(False, stop_reason="artifact_unreadable")
    if not _auto_remediation_enabled():
        return AutoRemediationPlan(False, stop_reason="auto_remediation_disabled")

    mode = str(meta.get("mode") or meta.get("program_id") or "").strip()
    if mode != TODAY_MODE and mode not in KEYSURI_MODES:
        return AutoRemediationPlan(False, stop_reason="unsupported_mode")

    # Only natural scheduled owner-review production runs are in scope (§9).
    if str(meta.get("execution_class") or "").strip() != "natural_scheduled":
        if not _manual_runs_allowed():
            return AutoRemediationPlan(False, stop_reason="not_a_natural_scheduled_run")
    if str(meta.get("verification_mode") or "").strip() == "no_send_verification":
        return AutoRemediationPlan(False, stop_reason="no_send_verification_run")
    if meta.get("admin_reissue_dry_run"):
        return AutoRemediationPlan(False, stop_reason="dry_run_artifact")

    # A child is never auto-remediated: that is what forbids child-of-child (§3).
    if str(meta.get("parent_run_id") or "").strip():
        return AutoRemediationPlan(False, stop_reason="already_a_remediation_child")
    if int(meta.get("automatic_remediation_attempt_count") or 0) >= AUTO_REMEDIATION_MAX_ATTEMPTS:
        return AutoRemediationPlan(False, stop_reason="attempt_budget_exhausted")

    review_class = reissue_parent_review_class(meta)
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
    parent = meta if isinstance(meta, dict) else load_run_artifact(run_id)
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

    try:
        result = runner(run_id, **kwargs)
    except Exception:  # noqa: BLE001
        logger.exception(
            "auto_remediation: runner raised run_id=%s mode=%s scope=%s", run_id, mode, scope
        )
        result = {"ok": False, "error": "auto_remediation_runner_exception"}

    child_run_id = str((result or {}).get("run_id") or "").strip()
    runner_error = str((result or {}).get("error") or "").strip()
    child_meta = load_run_artifact(child_run_id) if child_run_id else None

    if not (result or {}).get("ok") or not child_run_id:
        _stamp(
            run_id,
            {
                "automatic_remediation_child_run_id": child_run_id or None,
                "automatic_remediation_result": RESULT_FAILED,
                "automatic_remediation_stop_reason": runner_error or "remediation_failed",
                "automatic_remediation_completed_at": now_kst_iso(),
            },
        )
        summary["automatic_remediation_child_run_id"] = child_run_id or None
        summary["automatic_remediation_result"] = RESULT_FAILED
        summary["stop_reason"] = runner_error or "remediation_failed"
        _send_remediation_report(
            parent_run_id=run_id,
            child_run_id=child_run_id or None,
            scope=scope,
            attempted=True,
            stop_reason=runner_error or "remediation_failed",
            remaining_issue_codes=artifact_issue_codes(child_meta or {}) or plan.issue_codes,
            report_fn=report_fn,
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
        },
    )
    _stamp(
        run_id,
        {
            "automatic_remediation_child_run_id": child_run_id,
            "automatic_remediation_result": outcome,
            "automatic_remediation_completed_at": now_kst_iso(),
        },
    )
    summary["automatic_remediation_child_run_id"] = child_run_id
    summary["automatic_remediation_result"] = outcome
    summary["child_current_result"] = current_label
    summary["child_remaining_issue_codes"] = remaining

    if outcome != RESULT_SUCCEEDED:
        # STOP: no second automatic attempt, owner gets the report instead (§3).
        _send_remediation_report(
            parent_run_id=run_id,
            child_run_id=child_run_id,
            scope=scope,
            attempted=True,
            stop_reason=f"child_{current_label.lower()}",
            remaining_issue_codes=remaining,
            report_fn=report_fn,
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


def build_remediation_report_html(
    *,
    parent_run_id: str,
    child_run_id: Optional[str],
    scope: Optional[str],
    attempted: bool,
    stop_reason: str,
    remaining_issue_codes: Sequence[str],
) -> str:
    """Owner-facing incident report for a remediation that did not finish (§3)."""
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
    return (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;'
        'padding:20px;background:#ffffff;">'
        '<h1 style="margin:0 0 14px 0;font-size:18px;color:#b91c1c;">자동 교정 실패</h1>'
        '<p style="margin:0 0 14px 0;font-size:13px;line-height:1.7;color:#334155;">'
        "이 실행은 고객 발송 가능 상태에 도달하지 못했습니다. 자동 교정은 실행당 1회만 "
        "수행되며, 추가 자동 재시도는 하지 않습니다. 필요하면 Admin에서 수동 재발행을 "
        "사용하세요.</p>"
        + row.format(label="Parent run", value=_esc(parent_run_id))
        + row.format(label="Child run", value=_esc(child_run_id or "생성되지 않음"))
        + row.format(
            label="Remediation",
            value=_esc(_SCOPE_LABELS_KO.get(str(scope), scope or "시도하지 않음")),
        )
        + row.format(label="Attempted", value="예" if attempted else "아니오")
        + row.format(label="Remaining issue codes", value=_esc(codes))
        + row.format(label="Why not customer-ready", value=_esc(stop_reason))
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
) -> bool:
    """Email the owner-facing remediation report. Owner recipients only."""
    html_body = build_remediation_report_html(
        parent_run_id=parent_run_id,
        child_run_id=child_run_id,
        scope=scope,
        attempted=attempted,
        stop_reason=stop_reason,
        remaining_issue_codes=remaining_issue_codes,
    )
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
