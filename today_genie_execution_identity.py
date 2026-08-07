"""Today_Geenee execution-class and natural-slot identity.

Prevents QA/manual/reissue/preview runs from silently satisfying the natural
06:30 KST scheduled-run obligation. Legacy artifacts without execution_class
never qualify as natural-slot completers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

PROGRAM_TODAY = "today_genie"
TODAY_NATURAL_SCHEDULED_SLOT = "06:30"

EXECUTION_CLASS_NATURAL_SCHEDULED = "natural_scheduled"
EXECUTION_CLASS_QA_MANUAL = "qa_manual"
EXECUTION_CLASS_ADMIN_REISSUE = "admin_reissue"
EXECUTION_CLASS_PREVIEW = "preview"
EXECUTION_CLASS_RECOVERY = "recovery"
EXECUTION_CLASS_CUSTOMER_DELIVERY = "customer_delivery"
# Isolated probes — never satisfy natural_scheduled slot identity.
EXECUTION_CLASS_RELIABILITY_CANARY = "reliability_canary"
EXECUTION_CLASS_PREFLIGHT_CANARY = "preflight_canary"
EXECUTION_CLASS_SMOKE = "smoke"
EXECUTION_CLASS_VERIFICATION = "verification"

KNOWN_EXECUTION_CLASSES = frozenset(
    {
        EXECUTION_CLASS_NATURAL_SCHEDULED,
        EXECUTION_CLASS_QA_MANUAL,
        EXECUTION_CLASS_ADMIN_REISSUE,
        EXECUTION_CLASS_PREVIEW,
        EXECUTION_CLASS_RECOVERY,
        EXECUTION_CLASS_CUSTOMER_DELIVERY,
        EXECUTION_CLASS_RELIABILITY_CANARY,
        EXECUTION_CLASS_PREFLIGHT_CANARY,
        EXECUTION_CLASS_SMOKE,
        EXECUTION_CLASS_VERIFICATION,
    }
)

NON_NATURAL_PROBE_CLASSES = frozenset(
    {
        EXECUTION_CLASS_QA_MANUAL,
        EXECUTION_CLASS_ADMIN_REISSUE,
        EXECUTION_CLASS_PREVIEW,
        EXECUTION_CLASS_RECOVERY,
        EXECUTION_CLASS_CUSTOMER_DELIVERY,
        EXECUTION_CLASS_RELIABILITY_CANARY,
        EXECUTION_CLASS_PREFLIGHT_CANARY,
        EXECUTION_CLASS_SMOKE,
        EXECUTION_CLASS_VERIFICATION,
    }
)

GATE_ACTION_ADMIT = "admit"
GATE_ACTION_SKIP_LEGITIMATE_DUPLICATE = "skip_legitimate_duplicate"
GATE_ACTION_REJECT_INVALID_MATCH = "reject_invalid_match"
GATE_ACTION_FAIL_CLOSED = "fail_closed"

FIRST_FAILED_STAGE_EXECUTION_CLASSIFICATION = "execution_classification"
FIRST_FAILED_STAGE_NATURAL_SLOT_GATE = "natural_slot_duplicate_gate"

_TERMINAL_OWNER_STATUSES = frozenset({"pending_review", "approved", "reopened"})


@dataclass(frozen=True)
class TodayExecutionIdentity:
    program_id: str
    execution_class: str
    scheduled_slot: str
    trigger_source: str
    kst_date: str  # YYYY-MM-DD


@dataclass
class NaturalSlotMatch:
    run_id: str
    execution_class: str
    scheduled_slot: str
    terminal_status: str
    artifact_status: str
    email_sent: bool
    trigger_source: str
    qualifies: bool
    disqualify_reason: str = ""


@dataclass
class NaturalSlotGateDecision:
    action: str
    identity: Optional[TodayExecutionIdentity] = None
    match: Optional[NaturalSlotMatch] = None
    error_code: str = ""
    issue_codes: List[str] = field(default_factory=list)
    message: str = ""
    duplicate: bool = False
    duplicate_reason: str = ""

    def diagnostic_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "duplicate": bool(self.duplicate),
            "duplicate_reason": self.duplicate_reason or None,
            "gate_action": self.action,
            "error_code": self.error_code or None,
            "issue_codes": list(self.issue_codes),
            "message": self.message or None,
        }
        if self.identity is not None:
            payload.update(
                {
                    "program_id": self.identity.program_id,
                    "execution_class": self.identity.execution_class,
                    "scheduled_slot": self.identity.scheduled_slot,
                    "trigger_source": self.identity.trigger_source,
                    "kst_schedule_date": self.identity.kst_date,
                    "current_request_execution_class": self.identity.execution_class,
                    "current_requested_slot": self.identity.scheduled_slot,
                }
            )
        if self.match is not None:
            payload.update(
                {
                    "matched_run_id": self.match.run_id,
                    "matched_execution_class": self.match.execution_class,
                    "matched_slot": self.match.scheduled_slot,
                    "matched_terminal_status": self.match.terminal_status,
                    "matched_artifact_status": self.match.artifact_status,
                    "matched_email_sent": self.match.email_sent,
                    "matched_trigger_source": self.match.trigger_source,
                    "matched_qualifies": self.match.qualifies,
                    "matched_disqualify_reason": self.match.disqualify_reason or None,
                }
            )
        return {k: v for k, v in payload.items() if v is not None}


def normalize_scheduled_slot(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    # Accept "06:30", "6:30", "0630", "06:30 KST"
    cleaned = text.upper().replace("KST", "").strip()
    digits = "".join(ch for ch in cleaned if ch.isdigit())
    if len(digits) == 3:
        digits = f"0{digits}"
    if len(digits) == 4:
        return f"{digits[:2]}:{digits[2:]}"
    if ":" in cleaned:
        parts = cleaned.split(":")
        if len(parts) >= 2 and parts[0].strip().isdigit() and parts[1].strip()[:2].isdigit():
            hh = int(parts[0].strip())
            mm = int(parts[1].strip()[:2])
            return f"{hh:02d}:{mm:02d}"
    return cleaned


def kst_date_str(now: Optional[datetime] = None) -> str:
    if now is None:
        now = datetime.now(KST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=KST)
    else:
        now = now.astimezone(KST)
    return now.date().isoformat()


def natural_slot_key(
    *,
    program_id: str,
    kst_date: str,
    scheduled_slot: str,
    execution_class: str = EXECUTION_CLASS_NATURAL_SCHEDULED,
) -> str:
    return "|".join(
        [
            str(program_id or "").strip(),
            str(kst_date or "").strip(),
            normalize_scheduled_slot(scheduled_slot),
            str(execution_class or "").strip(),
        ]
    )


def resolve_today_execution_identity(
    *,
    execution_class: Optional[str],
    scheduled_slot: Optional[str],
    trigger_source: Optional[str],
    now: Optional[datetime] = None,
    program_id: str = PROGRAM_TODAY,
) -> tuple[Optional[TodayExecutionIdentity], Optional[str], List[str]]:
    """Return (identity, error_code, issue_codes).

    Missing or unknown execution_class / trigger_source fails closed.
    Natural scheduled requests require the canonical 06:30 slot (or explicit
    equal normalized value).
    """
    issues: List[str] = []
    cls = str(execution_class or "").strip()
    trigger = str(trigger_source or "").strip()
    slot = normalize_scheduled_slot(scheduled_slot)

    if not cls:
        issues.append("missing_execution_class")
        return None, "execution_class_required", issues
    if cls not in KNOWN_EXECUTION_CLASSES:
        issues.append("unknown_execution_class")
        return None, "execution_class_invalid", issues
    if not trigger:
        issues.append("missing_trigger_source")
        return None, "trigger_source_required", issues

    if cls == EXECUTION_CLASS_NATURAL_SCHEDULED:
        if not slot:
            issues.append("missing_scheduled_slot")
            return None, "scheduled_slot_required", issues
        if slot != TODAY_NATURAL_SCHEDULED_SLOT:
            issues.append("noncanonical_natural_slot")
            return None, "scheduled_slot_invalid", issues

    identity = TodayExecutionIdentity(
        program_id=str(program_id or PROGRAM_TODAY).strip() or PROGRAM_TODAY,
        execution_class=cls,
        scheduled_slot=slot if cls == EXECUTION_CLASS_NATURAL_SCHEDULED else (slot or ""),
        trigger_source=trigger,
        kst_date=kst_date_str(now),
    )
    return identity, None, issues


def _terminal_status(meta: Mapping[str, Any]) -> str:
    owner = str(meta.get("owner_review_status") or "").strip()
    if owner:
        return owner
    if bool(meta.get("email_sent")):
        return "emailed"
    return str(meta.get("workflow_status") or meta.get("artifact_status") or "unknown")


def natural_slot_completer_qualification(
    meta: Mapping[str, Any],
    *,
    program_id: str = PROGRAM_TODAY,
    kst_date: str,
    scheduled_slot: str = TODAY_NATURAL_SCHEDULED_SLOT,
) -> NaturalSlotMatch:
    """Decide whether an artifact may satisfy the natural scheduled slot."""
    run_id = str(meta.get("run_id") or "").strip()
    mode = str(meta.get("mode") or meta.get("program_id") or "").strip()
    cls = str(meta.get("execution_class") or "").strip()
    slot = normalize_scheduled_slot(meta.get("scheduled_slot"))
    email_sent = bool(meta.get("email_sent"))
    artifact_status = str(meta.get("artifact_status") or "").strip()
    validation_result = str(meta.get("validation_result") or "").strip()
    trigger = str(meta.get("trigger_source") or "").strip()
    owner_status = str(meta.get("owner_review_status") or "").strip()
    terminal = _terminal_status(meta)
    parent = str(meta.get("parent_run_id") or "").strip()
    verification_mode = str(meta.get("verification_mode") or "").strip()

    disqualify = ""
    if mode and mode != program_id:
        disqualify = "cross_program"
    elif not run_id:
        disqualify = "missing_run_id"
    elif parent:
        disqualify = "reissue_child"
    elif not cls:
        disqualify = "legacy_missing_execution_class"
    elif cls != EXECUTION_CLASS_NATURAL_SCHEDULED:
        disqualify = f"execution_class_{cls}"
    elif slot != normalize_scheduled_slot(scheduled_slot):
        disqualify = "slot_mismatch"
    elif not run_id.startswith(kst_date.replace("-", "") + "_"):
        disqualify = "kst_date_mismatch"
    elif validation_result == "block" and not email_sent:
        disqualify = "failed_or_blocked"
    elif artifact_status == "failed":
        disqualify = "artifact_failed"
    elif verification_mode == "no_send_verification":
        disqualify = "no_send_verification"
    elif str(meta.get("safe_fail") or "").strip().lower() in {"1", "true", "yes"}:
        disqualify = "safe_fail"
    elif not email_sent and owner_status not in _TERMINAL_OWNER_STATUSES:
        # Natural success requires owner-review SMTP acceptance (or an explicit
        # pending/approved terminal after a completed natural path). Artifact
        # existence alone never qualifies.
        disqualify = "not_terminal_success"
    elif email_sent and artifact_status not in {"emailed", "validated", "reissued", "review_required", ""}:
        # emailed/validated are success; empty allowed when derive not run yet
        if artifact_status in {"failed", "generated"} and not email_sent:
            disqualify = "incomplete_artifact"
        elif artifact_status == "failed":
            disqualify = "artifact_failed"

    # SMTP-failed natural: email_sent false with explicit smtp failure markers.
    if not disqualify and not email_sent:
        smtp_status = str(
            meta.get("owner_email_delivery_status")
            or meta.get("smtp_status")
            or ""
        ).strip().lower()
        if smtp_status in {"failed", "smtp_failed", "error"}:
            disqualify = "smtp_failed"
        elif owner_status not in _TERMINAL_OWNER_STATUSES:
            disqualify = "not_terminal_success"

    qualifies = disqualify == ""
    # Final success rule: must have email_sent True for natural slot completion.
    if qualifies and not email_sent:
        qualifies = False
        disqualify = "smtp_or_email_incomplete"

    return NaturalSlotMatch(
        run_id=run_id,
        execution_class=cls or "",
        scheduled_slot=slot,
        terminal_status=terminal,
        artifact_status=artifact_status,
        email_sent=email_sent,
        trigger_source=trigger,
        qualifies=qualifies,
        disqualify_reason=disqualify,
    )


def find_natural_slot_completer(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    program_id: str = PROGRAM_TODAY,
    kst_date: str,
    scheduled_slot: str = TODAY_NATURAL_SCHEDULED_SLOT,
) -> Optional[NaturalSlotMatch]:
    """Return the first artifact that legitimately completes the natural slot."""
    for raw in artifacts:
        match = natural_slot_completer_qualification(
            raw,
            program_id=program_id,
            kst_date=kst_date,
            scheduled_slot=scheduled_slot,
        )
        if match.qualifies:
            return match
    return None


def evaluate_today_natural_slot_gate(
    *,
    identity: Optional[TodayExecutionIdentity],
    identity_error: Optional[str],
    identity_issues: Sequence[str],
    artifacts: Sequence[Mapping[str, Any]],
    # Adversarial / test hooks — production callers leave these False.
    force_date_only_match: bool = False,
    force_treat_emailed_qa_as_natural: bool = False,
    force_accept_failed_as_success: bool = False,
    force_silent_skip_without_diagnostics: bool = False,
    force_ignore_slot: bool = False,
    force_cross_mode: bool = False,
) -> NaturalSlotGateDecision:
    """Production natural-slot gate with optional adversarial mutation hooks."""
    if identity is None:
        return NaturalSlotGateDecision(
            action=GATE_ACTION_FAIL_CLOSED,
            error_code=str(identity_error or "execution_identity_invalid"),
            issue_codes=list(identity_issues),
            message="today_natural_execution_identity_required",
        )

    # Non-natural requests never consume or skip on the natural slot.
    if identity.execution_class != EXECUTION_CLASS_NATURAL_SCHEDULED:
        return NaturalSlotGateDecision(
            action=GATE_ACTION_ADMIT,
            identity=identity,
            message="non_natural_request_admitted",
        )

    program_id = identity.program_id
    kst_date = identity.kst_date
    slot = identity.scheduled_slot

    # --- adversarial mutations (harness only) ---
    if force_date_only_match or force_treat_emailed_qa_as_natural or force_accept_failed_as_success or force_ignore_slot or force_cross_mode:
        invalid = _adversarial_false_match(
            artifacts,
            program_id=program_id,
            kst_date=kst_date,
            scheduled_slot=slot,
            force_date_only_match=force_date_only_match,
            force_treat_emailed_qa_as_natural=force_treat_emailed_qa_as_natural,
            force_accept_failed_as_success=force_accept_failed_as_success,
            force_ignore_slot=force_ignore_slot,
            force_cross_mode=force_cross_mode,
        )
        if invalid is not None:
            if force_silent_skip_without_diagnostics:
                # Harness proves wrapper must not allow this path in production.
                return NaturalSlotGateDecision(
                    action=GATE_ACTION_SKIP_LEGITIMATE_DUPLICATE,
                    identity=identity,
                    match=invalid,
                    duplicate=True,
                    duplicate_reason="adversarial_silent_skip",
                    message="adversarial_silent_skip",
                )
            return NaturalSlotGateDecision(
                action=GATE_ACTION_REJECT_INVALID_MATCH,
                identity=identity,
                match=invalid,
                duplicate=True,
                duplicate_reason="invalid_natural_slot_match",
                error_code="invalid_natural_slot_duplicate_match",
                issue_codes=["invalid_natural_slot_match", invalid.disqualify_reason or "unqualified_match"],
                message="invalid_natural_slot_match",
            )

    match = find_natural_slot_completer(
        artifacts,
        program_id=program_id,
        kst_date=kst_date,
        scheduled_slot=slot,
    )
    if match is None:
        return NaturalSlotGateDecision(
            action=GATE_ACTION_ADMIT,
            identity=identity,
            message="natural_slot_open",
        )

    if not match.qualifies:
        return NaturalSlotGateDecision(
            action=GATE_ACTION_REJECT_INVALID_MATCH,
            identity=identity,
            match=match,
            duplicate=True,
            duplicate_reason="invalid_natural_slot_match",
            error_code="invalid_natural_slot_duplicate_match",
            issue_codes=["invalid_natural_slot_match", match.disqualify_reason or "unqualified"],
            message="invalid_natural_slot_match",
        )

    return NaturalSlotGateDecision(
        action=GATE_ACTION_SKIP_LEGITIMATE_DUPLICATE,
        identity=identity,
        match=match,
        duplicate=True,
        duplicate_reason="natural_slot_already_completed",
        message="natural_slot_already_completed",
        issue_codes=["natural_slot_already_completed"],
    )


def _adversarial_false_match(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    program_id: str,
    kst_date: str,
    scheduled_slot: str,
    force_date_only_match: bool,
    force_treat_emailed_qa_as_natural: bool,
    force_accept_failed_as_success: bool,
    force_ignore_slot: bool,
    force_cross_mode: bool,
) -> Optional[NaturalSlotMatch]:
    date_prefix = kst_date.replace("-", "") + "_"
    for raw in artifacts:
        run_id = str(raw.get("run_id") or "").strip()
        mode = str(raw.get("mode") or raw.get("program_id") or "").strip()
        if not force_cross_mode and mode and mode != program_id:
            continue
        if force_date_only_match and not run_id.startswith(date_prefix):
            continue
        if not force_date_only_match and not run_id.startswith(date_prefix):
            continue
        cls = str(raw.get("execution_class") or "").strip()
        slot = normalize_scheduled_slot(raw.get("scheduled_slot"))
        email_sent = bool(raw.get("email_sent"))
        artifact_status = str(raw.get("artifact_status") or "").strip()
        validation_result = str(raw.get("validation_result") or "").strip()

        if force_treat_emailed_qa_as_natural and cls == EXECUTION_CLASS_QA_MANUAL and email_sent:
            return NaturalSlotMatch(
                run_id=run_id,
                execution_class=cls,
                scheduled_slot=slot,
                terminal_status=_terminal_status(raw),
                artifact_status=artifact_status,
                email_sent=email_sent,
                trigger_source=str(raw.get("trigger_source") or ""),
                qualifies=False,
                disqualify_reason="execution_class_qa_manual",
            )
        if force_accept_failed_as_success and (
            artifact_status == "failed" or validation_result == "block"
        ):
            return NaturalSlotMatch(
                run_id=run_id,
                execution_class=cls,
                scheduled_slot=slot,
                terminal_status=_terminal_status(raw),
                artifact_status=artifact_status,
                email_sent=email_sent,
                trigger_source=str(raw.get("trigger_source") or ""),
                qualifies=False,
                disqualify_reason="artifact_failed",
            )
        if force_ignore_slot and email_sent and mode == program_id:
            return NaturalSlotMatch(
                run_id=run_id,
                execution_class=cls or EXECUTION_CLASS_QA_MANUAL,
                scheduled_slot=slot,
                terminal_status=_terminal_status(raw),
                artifact_status=artifact_status,
                email_sent=email_sent,
                trigger_source=str(raw.get("trigger_source") or ""),
                qualifies=False,
                disqualify_reason="slot_mismatch" if slot != scheduled_slot else "legacy_missing_execution_class",
            )
        if force_date_only_match and email_sent:
            return NaturalSlotMatch(
                run_id=run_id,
                execution_class=cls,
                scheduled_slot=slot,
                terminal_status=_terminal_status(raw),
                artifact_status=artifact_status,
                email_sent=email_sent,
                trigger_source=str(raw.get("trigger_source") or ""),
                qualifies=False,
                disqualify_reason="legacy_missing_execution_class" if not cls else f"execution_class_{cls}",
            )
        if force_cross_mode and mode and mode != program_id and email_sent:
            return NaturalSlotMatch(
                run_id=run_id,
                execution_class=cls,
                scheduled_slot=slot,
                terminal_status=_terminal_status(raw),
                artifact_status=artifact_status,
                email_sent=email_sent,
                trigger_source=str(raw.get("trigger_source") or ""),
                qualifies=False,
                disqualify_reason="cross_program",
            )
    return None


def identity_fields_for_artifact(identity: TodayExecutionIdentity) -> Dict[str, Any]:
    return {
        "execution_class": identity.execution_class,
        "scheduled_slot": identity.scheduled_slot,
        "natural_slot_key": natural_slot_key(
            program_id=identity.program_id,
            kst_date=identity.kst_date,
            scheduled_slot=identity.scheduled_slot or TODAY_NATURAL_SCHEDULED_SLOT,
            execution_class=identity.execution_class,
        )
        if identity.execution_class == EXECUTION_CLASS_NATURAL_SCHEDULED
        else None,
        "kst_schedule_date": identity.kst_date,
    }
