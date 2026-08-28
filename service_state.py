"""Canonical service state for one program, derived from one set of facts.

Before this module the system carried several disagreeing truths at once. On
2026-08-28 the 12:30 Global run collapsed at the model contract, its recovery
call failed, and the scaffold rebuilt the five cards straight out of the raw
claim pool — English RSS prose in customer-visible Korean fields. The delivery
gate behaved correctly: the owner got a short quality notice, customers got
nothing. But the run artifact still recorded ``validation_result: "pass"`` and
``artifact_status: "emailed"``, no incident record was written, and
``/admin/incidents`` therefore reported "현재 장애 없음" while that day's scheduled
Global briefing had produced nothing a customer could read.

"Nothing was mailed" is a safe failure, not a product success. This module
turns the facts a run already records — scheduled output, content quality,
delivery, incident and recovery state — into one state, so that a scheduled
briefing which is not customer-ready can only ever read DEGRADED.

Read-only and side-effect free: it derives, it never mutates a run.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from issue_code_registry import SEVERITY_BLOCK, get_issue_code

# --- service health -------------------------------------------------------
HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
INCIDENT = "INCIDENT"

# --- content status -------------------------------------------------------
CONTENT_READY = "ready"
CONTENT_QUALITY_DEGRADED = "quality_degraded"
CONTENT_UNUSABLE = "unusable"
CONTENT_MISSING = "missing"

# --- recovery -------------------------------------------------------------
RECOVERY_NOT_REQUIRED = "not_required"
RECOVERY_AVAILABLE = "available"
RECOVERY_ATTEMPTED_FAILED = "attempted_failed"
RECOVERY_COMPLETED = "completed"

# --- customer notice ------------------------------------------------------
NOTICE_NOT_REQUIRED = "not_required"
NOTICE_RECOMMENDED = "recommended"
NOTICE_REQUIRED = "required"
NOTICE_SENT = "sent"

_CUSTOMER_DELIVERED_STATUSES = frozenset(
    {"accepted_all", "delivered", "sent", "partial_refusal"}
)
_SAFE_VERDICTS = frozenset({"safe", ""})
_POOR_VERDICTS = frozenset({"poor", "unusable", "bad"})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _text(value).lower()


def _issue_codes(meta: Mapping[str, Any]) -> List[str]:
    """Every issue code a run recorded, from whichever field carries it."""
    out: List[str] = []
    for key in (
        "issue_codes",
        "review_issue_codes",
        "terminal_issue_codes",
        "initial_generation_issue_codes",
    ):
        raw = meta.get(key)
        if isinstance(raw, (list, tuple)):
            for code in raw:
                code = _text(code)
                if code and code not in out:
                    out.append(code)
    return out


def blocking_issue_codes(meta: Mapping[str, Any]) -> List[str]:
    """Codes the shared registry classifies as blocking.

    Severity comes from `issue_code_registry`, never from a phrase list here:
    a detector and the state it produces must not be able to drift apart.
    """
    blocking: List[str] = []
    for code in _issue_codes(meta):
        entry = get_issue_code(code)
        if entry is not None and entry.severity == SEVERITY_BLOCK:
            blocking.append(code)
    return blocking


def customer_delivered(meta: Mapping[str, Any]) -> bool:
    return _lower(meta.get("customer_delivery_status")) in _CUSTOMER_DELIVERED_STATUSES


def derive_content_status(meta: Mapping[str, Any]) -> Dict[str, Any]:
    """Whether this run produced something a customer could actually read."""
    reasons: List[str] = []

    if not meta:
        return {"content_status": CONTENT_MISSING, "reasons": ["예정된 실행 기록 없음"]}

    validation = _lower(meta.get("validation_result"))
    if isinstance(meta.get("validation_result"), dict):
        validation = _lower(meta["validation_result"].get("status"))
    artifact = _lower(meta.get("artifact_status"))
    safety = _lower(meta.get("safety_verdict"))
    editorial = _lower(meta.get("editorial_verdict"))
    approval_policy = _text(meta.get("customer_approval_policy")).upper()
    blocking = blocking_issue_codes(meta)

    if validation in {"block", "blocked", "fail", "failed", "invalid"} or artifact == "failed":
        reasons.append("검증 차단으로 발행 가능한 본문이 없습니다")
        return {"content_status": CONTENT_UNUSABLE, "reasons": reasons, "blocking": blocking}

    if safety and safety not in _SAFE_VERDICTS:
        reasons.append(f"안전 판정 {safety.upper()}")
        return {"content_status": CONTENT_UNUSABLE, "reasons": reasons, "blocking": blocking}

    if _text(meta.get("terminal_issue_codes")) and meta.get("terminal_issue_codes"):
        reasons.append("복구 불가 항목이 남아 있습니다")
        return {"content_status": CONTENT_UNUSABLE, "reasons": reasons, "blocking": blocking}

    # A reader-surface violation the registry calls blocking means the customer
    # surface is not readable, whatever the run's own summary field says.
    if blocking:
        reasons.append("독자 노출 면에 차단 등급 결함이 남아 있습니다: " + ", ".join(blocking[:6]))
        return {
            "content_status": CONTENT_QUALITY_DEGRADED,
            "reasons": reasons,
            "blocking": blocking,
        }

    # The reader-surface producer withheld a customer-visible field it could not
    # bind from authored prose. Whatever else the run reports, the cards on the
    # page are incomplete.
    if meta.get("reader_surface_enforced") and not meta.get("reader_surface_complete", True):
        withheld = meta.get("reader_surface_unavailable_fields") or []
        reasons.append(
            "독자 노출 필드가 생성되지 않아 보류 표시로 대체되었습니다: "
            + ", ".join(str(item) for item in list(withheld)[:6])
        )
        return {
            "content_status": CONTENT_QUALITY_DEGRADED,
            "reasons": reasons,
            "blocking": blocking,
        }

    # A scaffold may restore structure; it may not turn "the model produced no
    # article prose" into "generation succeeded". When the one budgeted
    # corrective call also failed, what remains on the reader surface is
    # source-pack material, whatever the run's own verdict fields say.
    if _scaffold_carried_the_generation(meta) and _recovery_failed(meta):
        reasons.append("모델 계약 실패 후 보정 생성이 실패해 스캐폴드 산출물만 남았습니다")
        return {
            "content_status": CONTENT_QUALITY_DEGRADED,
            "reasons": reasons,
            "blocking": blocking,
        }

    if editorial in _POOR_VERDICTS:
        reasons.append(f"편집 품질 판정 {editorial.upper()}")
        return {
            "content_status": CONTENT_QUALITY_DEGRADED,
            "reasons": reasons,
            "blocking": blocking,
        }

    if approval_policy == "UNAVAILABLE" and not customer_delivered(meta):
        reasons.append("고객 승인 경로가 열리지 않았습니다")
        return {
            "content_status": CONTENT_QUALITY_DEGRADED,
            "reasons": reasons,
            "blocking": blocking,
        }

    return {"content_status": CONTENT_READY, "reasons": reasons, "blocking": blocking}


_SCAFFOLD_CARRIED_GENERATION_CODES = frozenset(
    {"global_contract_scaffold_fabricated_top5"}
)


def _scaffold_carried_the_generation(meta: Mapping[str, Any]) -> bool:
    """The model contributed no article prose and a scaffold stood in for it."""
    codes = set(_issue_codes(meta))
    for key in ("global_recovery_error_codes", "recovery_generation_issue_codes"):
        raw = meta.get(key)
        if isinstance(raw, (list, tuple)):
            codes.update(_text(code) for code in raw)
    return bool(codes & _SCAFFOLD_CARRIED_GENERATION_CODES)


def _recovery_failed(meta: Mapping[str, Any]) -> bool:
    return any(
        _lower(meta.get(key)) in {"failed", "error"}
        for key in ("generation_recovery_result", "global_recovery_result", "recovery_result")
    )


def derive_recovery_state(meta: Mapping[str, Any], *, incident: Optional[Mapping[str, Any]] = None) -> str:
    if not meta:
        return RECOVERY_AVAILABLE
    for key in ("generation_recovery_result", "global_recovery_result", "recovery_result"):
        result = _lower(meta.get(key))
        if result in {"failed", "error"}:
            return RECOVERY_ATTEMPTED_FAILED
        if result in {"ok", "success", "succeeded", "passed"}:
            return RECOVERY_COMPLETED
    if incident:
        state = _lower(incident.get("recovery_state") or incident.get("state"))
        if state in {"recovered", "resolved", "closed"}:
            return RECOVERY_COMPLETED
    return RECOVERY_NOT_REQUIRED


def derive_service_state(
    meta: Optional[Mapping[str, Any]],
    *,
    program: Mapping[str, Any],
    incident: Optional[Mapping[str, Any]] = None,
    notices: Sequence[Mapping[str, Any]] = (),
    scheduled_expected: bool = True,
) -> Dict[str, Any]:
    """One state for one program, from all of its facts at once."""
    meta = meta or {}
    content = derive_content_status(meta)
    content_status = content["content_status"]
    reasons: List[str] = list(content["reasons"])

    delivered = customer_delivered(meta)
    customer_ready = content_status == CONTENT_READY

    if content_status == CONTENT_MISSING:
        service_health = INCIDENT if scheduled_expected else HEALTHY
    elif content_status == CONTENT_UNUSABLE:
        service_health = INCIDENT
    elif content_status == CONTENT_QUALITY_DEGRADED:
        # The scheduled slot produced output, but nothing a customer can be
        # sent. That is a degraded service, never "장애 없음".
        service_health = DEGRADED
    else:
        service_health = HEALTHY

    incident_state = _lower((incident or {}).get("state") or (incident or {}).get("status"))
    if incident and incident_state not in {"resolved", "closed", "recovered"}:
        service_health = INCIDENT if service_health != INCIDENT else service_health
        reasons.append("열린 장애 기록이 있습니다")

    recovery_state = derive_recovery_state(meta, incident=incident)

    notice_state = NOTICE_NOT_REQUIRED
    if service_health == INCIDENT:
        notice_state = NOTICE_REQUIRED
    elif service_health == DEGRADED:
        notice_state = NOTICE_RECOMMENDED
    if _notice_already_sent(notices, program_id=_text(program.get("id"))):
        notice_state = NOTICE_SENT

    return {
        "program_id": _text(program.get("id")),
        "program_display": _text(program.get("display")) or _text(program.get("id")),
        "program_name": _text(program.get("name")),
        "scheduled_time": _text(program.get("natural_time")),
        "run_id": _text(meta.get("run_id")),
        "content_status": content_status,
        "customer_ready": customer_ready,
        "customer_delivered": delivered,
        "service_health": service_health,
        "recovery_state": recovery_state,
        "customer_notice_state": notice_state,
        "blocking_issue_codes": content.get("blocking", []),
        "reasons": reasons,
        "owner_next_action": _owner_next_action(
            program=program,
            meta=meta,
            service_health=service_health,
            content_status=content_status,
            recovery_state=recovery_state,
            notice_state=notice_state,
            delivered=delivered,
        ),
    }


def _notice_already_sent(notices: Sequence[Mapping[str, Any]], *, program_id: str) -> bool:
    for notice in notices or ():
        if _lower(notice.get("status")) not in {"sent", "delivered"}:
            continue
        scope = _text(notice.get("program_id") or notice.get("program") or "all").lower()
        if scope in {"all", ""} or scope == program_id.lower():
            return True
    return False


def _owner_next_action(
    *,
    program: Mapping[str, Any],
    meta: Mapping[str, Any],
    service_health: str,
    content_status: str,
    recovery_state: str,
    notice_state: str,
    delivered: bool,
) -> Dict[str, str]:
    """The one thing the owner should do next, as a label and a destination."""
    pid = _text(program.get("id"))
    run_id = _text(meta.get("run_id"))

    if service_health == HEALTHY:
        if delivered:
            return {"label": "조치 불필요", "href": "", "kind": "none"}
        if run_id:
            return {
                "label": "검수하고 고객 발송 결정",
                "href": f"/admin/runs/{run_id}",
                "kind": "review",
            }
        return {"label": "조치 불필요", "href": "", "kind": "none"}

    if content_status == CONTENT_MISSING:
        return {
            "label": "예정 실행 누락 확인",
            "href": "/admin/incidents",
            "kind": "incident",
        }

    if recovery_state == RECOVERY_AVAILABLE and run_id:
        return {
            "label": "복구 실행 검토",
            "href": f"/admin/runs/{run_id}",
            "kind": "recovery",
        }

    # Recovery already failed, or the content is degraded with no automatic
    # path left: the owner's real next move is telling customers.
    if notice_state in {NOTICE_REQUIRED, NOTICE_RECOMMENDED}:
        return {
            "label": "고객 공지 작성",
            "href": f"/admin/notices/new?program_id={pid}",
            "kind": "notice",
        }
    if notice_state == NOTICE_SENT:
        return {"label": "공지 발송 완료 — 후속 확인", "href": "/admin/notices", "kind": "notice"}
    return {"label": "상태 확인", "href": "/admin/incidents", "kind": "incident"}
