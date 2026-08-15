"""One canonical graded quality adjudicator for KeeSuri Global/Korea.

Detectors and deterministic producers report findings.  This module is the
only content-quality component allowed to convert those findings into owner or
customer delivery behavior.  It never calls SMTP and never mutates source
content; it returns the exact owner surface selected by the delivery matrix.
"""
from __future__ import annotations

import hashlib
import html
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from issue_code_registry import (
    FINDING_SEVERITY_BLOCK,
    FINDING_SEVERITY_INFO,
    FINDING_SEVERITY_REVIEW,
    SAFETY_FAMILY_EDITORIAL,
    get_graded_issue_policy,
)

SAFETY_SAFE = "SAFE"
SAFETY_UNSAFE = "UNSAFE"
SAFETY_INCONCLUSIVE = "INCONCLUSIVE"

EDITORIAL_READY = "READY"
EDITORIAL_REVIEW = "REVIEW"
EDITORIAL_POOR = "POOR"

FINDING_DETECTED = "DETECTED"
FINDING_REPAIRED = "REPAIRED"
FINDING_RESIDUAL = "RESIDUAL"
FINDING_TERMINAL = "TERMINAL"

OWNER_SEND_READY = "SEND_OWNER_REVIEW"
OWNER_SEND_WARNING = "SEND_OWNER_REVIEW_WARNING"
OWNER_SEND_POOR_NOTICE = "SEND_OWNER_QUALITY_NOTICE"
OWNER_HOLD_INCIDENT = "HOLD_INCIDENT"

CUSTOMER_STANDARD_APPROVAL = "STANDARD_APPROVAL"
CUSTOMER_WARNING_CONFIRMATION = "WARNING_CONFIRMATION_REQUIRED"
CUSTOMER_APPROVAL_UNAVAILABLE = "UNAVAILABLE"

_POOR_REVIEW_FINDING_THRESHOLD = 6
_STYLE_SCRIPT_RE = re.compile(
    r"<(?:style|script)[^>]*>.*?</(?:style|script)>", re.IGNORECASE | re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def _bounded_text(value: Any, limit: int = 180) -> str:
    return _SPACE_RE.sub(" ", str(value or "")).strip()[:limit]


def extract_visible_text(html_body: str) -> str:
    text = _STYLE_SCRIPT_RE.sub(" ", str(html_body or ""))
    text = _TAG_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", html.unescape(text)).strip()


def visible_surface_sha256(subject: str, html_body: str) -> str:
    visible = f"{str(subject or '').strip()}\n{extract_visible_text(html_body)}"
    return hashlib.sha256(visible.encode("utf-8")).hexdigest()


def _finding_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("issue_code") or ""),
        str(row.get("field") or row.get("section") or row.get("path") or ""),
        str(row.get("before") or row.get("excerpt") or row.get("sample") or "")[:120],
    )


def _append_unique(
    rows: List[Dict[str, Any]], row: Mapping[str, Any]
) -> Optional[Dict[str, Any]]:
    compact = {
        "issue_code": _bounded_text(row.get("issue_code"), 120),
        "field": _bounded_text(
            row.get("field") or row.get("section") or row.get("path"), 180
        ),
        "rank": row.get("rank"),
        "source_id": _bounded_text(row.get("source_id"), 160),
        "before": _bounded_text(
            row.get("before") or row.get("excerpt") or row.get("sample"), 180
        ),
        "after": _bounded_text(
            row.get("after") or row.get("repaired_sample") or row.get("repair_after"),
            180,
        ),
        "detail": _bounded_text(row.get("detail") or row.get("message"), 220),
        "reported_state": _bounded_text(
            row.get("reported_state") or row.get("finding_state"), 24
        ),
    }
    compact = {key: value for key, value in compact.items() if value not in (None, "")}
    if not compact.get("issue_code"):
        return None
    key = _finding_key(compact)
    if any(_finding_key(existing) == key for existing in rows):
        return None
    if len(rows) < 48:
        rows.append(compact)
        return compact
    return None


def _post_render_findings(result: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    detector_rows = [
        *list(getattr(result, "issues", None) or []),
        *list(getattr(result, "warnings", None) or []),
    ]
    for issue in detector_rows:
        _append_unique(
            rows,
            {
                "issue_code": getattr(issue, "code", ""),
                "section": getattr(issue, "section", ""),
                "rank": (
                    int(getattr(issue, "item_index")) + 1
                    if getattr(issue, "item_index", None) is not None
                    else None
                ),
                "excerpt": getattr(issue, "excerpt", ""),
                "message": getattr(issue, "message", ""),
            },
        )
    diagnostics = getattr(result, "diagnostics", None)
    if isinstance(diagnostics, Mapping):
        for finding in diagnostics.get("visible_surface_review_findings") or []:
            if isinstance(finding, Mapping):
                _append_unique(rows, finding)
    return rows


def _visible_quality_findings(fields: Mapping[str, Any]) -> List[Dict[str, Any]]:
    samples = [row for row in fields.get("visible_text_quality_samples") or [] if isinstance(row, Mapping)]
    sample_by_result: Dict[str, List[Mapping[str, Any]]] = {}
    for sample in samples:
        sample_by_result.setdefault(str(sample.get("validator_result") or ""), []).append(sample)

    rows: List[Dict[str, Any]] = []
    repaired_codes = [
        str(code) for code in fields.get("visible_text_quality_issue_codes") or []
        if get_graded_issue_policy(str(code)) is not None
        and get_graded_issue_policy(str(code)).severity == FINDING_SEVERITY_INFO
    ]
    repaired_samples = list(fields.get("repair_history") or []) or sample_by_result.get("repaired", [])
    for code in repaired_codes:
        matching = repaired_samples or [{}]
        for sample in matching[:6]:
            _append_unique(
                rows,
                {
                    "issue_code": code,
                    "reported_state": FINDING_REPAIRED,
                    **dict(sample),
                },
            )

    terminal_codes = [str(code) for code in fields.get("terminal_issue_codes") or []]
    residual_samples = sample_by_result.get("block", []) or samples
    for code in terminal_codes:
        matching = residual_samples or [{}]
        for sample in matching[:6]:
            residual = dict(sample)
            # A rendered-surface detector may show the repair it *could* have
            # made.  The renderer is immutable at this stage, so that sample is
            # not a completed producer repair.
            residual.pop("repaired_sample", None)
            residual.pop("repair_after", None)
            residual.pop("after", None)
            _append_unique(
                rows,
                {"issue_code": code, "reported_state": FINDING_DETECTED, **residual},
            )

    for code in fields.get("pre_repair_findings") or []:
        _append_unique(
            rows,
            {
                "issue_code": str(code),
                "reported_state": FINDING_DETECTED,
                "detail": "repair input finding",
            },
        )
    return rows


def collect_keysuri_findings(
    *,
    visible_quality_fields: Optional[Mapping[str, Any]] = None,
    post_render_result: Any = None,
    extra_findings: Optional[Sequence[Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Collect bounded detector output without deciding delivery."""
    rows: List[Dict[str, Any]] = []
    if isinstance(visible_quality_fields, Mapping):
        for row in _visible_quality_findings(visible_quality_fields):
            _append_unique(rows, row)
    if post_render_result is not None:
        for row in _post_render_findings(post_render_result):
            _append_unique(rows, row)
    for row in extra_findings or []:
        if isinstance(row, Mapping):
            _append_unique(rows, row)
    return rows


def _cross_field_context_findings(
    program_id: str,
    structured_briefing: Optional[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Detect one bounded REVIEW finding per contradictory Korea TOP5 item.

    The canonical adjudicator owns the verdict.  This detector compares strong
    source/title/what-happened vertical evidence with the item's category,
    selection reason, owner view and follow-up fields.  It does not mutate the
    candidate and never turns an editorial mismatch into a safety block.
    """
    if not str(program_id or "").startswith("keysuri_korea"):
        return []
    if not isinstance(structured_briefing, Mapping):
        return []
    top = structured_briefing.get("top_5_news")
    if not isinstance(top, Mapping) or not isinstance(top.get("items"), list):
        return []

    from keysuri_briefing_content_enricher import (
        _KOREA_VERTICAL_MARKERS,
        _korea_vertical_domains,
    )

    findings: List[Dict[str, Any]] = []
    for index, raw_item in enumerate(top.get("items") or []):
        if not isinstance(raw_item, Mapping):
            continue
        nested = raw_item.get("briefing_item")
        nested = nested if isinstance(nested, Mapping) else {}

        def _field(*names: str) -> str:
            for name in names:
                value = raw_item.get(name)
                if value in (None, ""):
                    value = nested.get(name)
                if value not in (None, ""):
                    return _bounded_text(value, 4_000)
            return ""

        identity_text = " ".join(
            value
            for value in (
                _field("korean_title", "headline", "title"),
                _field("what_happened", "summary"),
            )
            if value
        )
        identity_domains = _korea_vertical_domains(identity_text)
        if not identity_domains:
            continue

        context_fields = {
            "category": _field("primary_category", "category"),
            "category_label": _field("category_label_ko"),
            "selection_reason": _field("selection_reason", "selection_rationale"),
            "owner_view": _field("owner_angle", "business_implication"),
            "follow_up": " ".join(
                value
                for value in (
                    _field("next_watch", "next_check_point", "follow_up"),
                    _field("owner_action_line"),
                )
                if value
            ),
        }
        foreign_domains: Set[str] = set()
        affected_fields: List[str] = []
        declared = context_fields["category"]
        if declared in _KOREA_VERTICAL_MARKERS and declared not in identity_domains:
            foreign_domains.add(declared)
            affected_fields.append("category")
        for field, value in context_fields.items():
            if field == "category" or not value:
                continue
            foreign = _korea_vertical_domains(value) - identity_domains
            if foreign:
                foreign_domains.update(foreign)
                affected_fields.append(field)
        if not foreign_domains:
            continue
        expected = ",".join(sorted(identity_domains))
        foreign = ",".join(sorted(foreign_domains))
        findings.append(
            {
                "issue_code": "keysuri_cross_field_context_mismatch",
                "field": f"top_5_news.items[{index}].context",
                "rank": raw_item.get("rank") or index + 1,
                "source_id": _field("news_id"),
                "before": " / ".join(affected_fields),
                "detail": f"identity={expected}; foreign_context={foreign}",
            }
        )
    return findings


def _warning_panel(findings: Sequence[Mapping[str, Any]]) -> str:
    items: List[str] = []
    for finding in findings[:8]:
        policy = get_graded_issue_policy(str(finding.get("issue_code") or ""))
        label = policy.label_ko if policy is not None else "추가 확인 필요"
        field = _bounded_text(finding.get("field"), 80)
        before = _bounded_text(finding.get("before"), 100)
        context = " · ".join(part for part in (field, before) if part)
        items.append(
            f"<li><strong>{html.escape(label)}</strong>"
            f"{': ' + html.escape(context) if context else ''}</li>"
        )
    body = "".join(items) or "<li>고객 발송 전 운영자 확인이 필요합니다.</li>"
    return (
        '<div data-keysuri-review-warning="true" style="margin:12px 0;padding:12px 14px;'
        'border:1px solid #d97706;background:#fffbeb;color:#78350f;border-radius:10px;'
        'font-family:Arial,sans-serif;font-size:13px;line-height:1.55;">'
        '<strong>검토 필요 · 고객 발송 전 확인</strong><ul style="margin:8px 0 0 18px;'
        f'padding:0;">{body}</ul></div>'
    )


def _insert_after_body_open(html_body: str, panel: str) -> str:
    if 'data-keysuri-review-warning="true"' in html_body:
        return html_body
    match = re.search(r"<body\b[^>]*>", html_body, flags=re.IGNORECASE)
    if match:
        return html_body[: match.end()] + panel + html_body[match.end() :]
    return panel + html_body


def _review_subject(subject: str) -> str:
    value = str(subject or "").strip()
    if "[운영자 검토][주의]" in value:
        return value
    if "[운영자 검토]" in value:
        return value.replace("[운영자 검토]", "[운영자 검토][주의]", 1)
    return f"[운영자 검토][주의] {value}".strip()


def _poor_notice(subject: str, owner_review_url: str, findings: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    notice_subject = _review_subject(subject).replace("[주의]", "[품질 확인]", 1)
    labels: List[str] = []
    for row in findings[:8]:
        policy = get_graded_issue_policy(str(row.get("issue_code") or ""))
        labels.append(policy.label_ko if policy is not None else "추가 확인 필요")
    summary = "".join(f"<li>{html.escape(label)}</li>" for label in labels)
    link = (
        f'<p><a href="{html.escape(owner_review_url, quote=True)}">Admin에서 전체 후보 확인</a></p>'
        if owner_review_url
        else "<p>Admin 실행 상세에서 전체 후보를 확인해 주세요.</p>"
    )
    body = (
        '<html><body><div style="font-family:Arial,sans-serif;line-height:1.6;">'
        '<h2>브리핑 품질 확인이 필요합니다</h2>'
        '<p>안전성 차단 사유는 없지만 편집 품질이 낮아 완성본처럼 발송하지 않았습니다.</p>'
        f'<ul>{summary}</ul>{link}</div></body></html>'
    )
    return notice_subject, body


def _canonical_delivery_matrix(safety_verdict: str, editorial_verdict: str) -> Dict[str, Any]:
    """The sole content-quality block decision in KeeSuri delivery."""
    owner_review_suppressed = safety_verdict != SAFETY_SAFE
    if owner_review_suppressed:
        return {
            "owner_delivery_behavior": OWNER_HOLD_INCIDENT,
            "customer_approval_policy": CUSTOMER_APPROVAL_UNAVAILABLE,
            "customer_approval_available": False,
        }
    if editorial_verdict == EDITORIAL_READY:
        behavior = OWNER_SEND_READY
        customer_policy = CUSTOMER_STANDARD_APPROVAL
        available = True
    elif editorial_verdict == EDITORIAL_REVIEW:
        behavior = OWNER_SEND_WARNING
        customer_policy = CUSTOMER_WARNING_CONFIRMATION
        available = True
    else:
        behavior = OWNER_SEND_POOR_NOTICE
        customer_policy = CUSTOMER_APPROVAL_UNAVAILABLE
        available = False
    return {
        "owner_delivery_behavior": behavior,
        "customer_approval_policy": customer_policy,
        "customer_approval_available": available,
    }


def adjudicate_keysuri_quality(
    *,
    program_id: str,
    subject: str,
    email_html: str,
    findings: Sequence[Mapping[str, Any]],
    owner_review_url: str = "",
) -> Dict[str, Any]:
    """Evaluate one final candidate and return the exact owner delivery surface."""
    normalized: List[Dict[str, Any]] = []
    repaired_codes: List[str] = []
    review_codes: List[str] = []
    terminal_codes: List[str] = []
    unknown_codes: List[str] = []

    for raw in findings:
        row = dict(raw)
        code = str(row.get("issue_code") or "").strip()
        policy = get_graded_issue_policy(code)
        repaired = row.get("reported_state") == FINDING_REPAIRED or (
            policy is not None and policy.severity == FINDING_SEVERITY_INFO
        )
        if repaired:
            severity = FINDING_SEVERITY_INFO
            state = FINDING_REPAIRED
            if code and code not in repaired_codes:
                repaired_codes.append(code)
            family = policy.family if policy is not None else SAFETY_FAMILY_EDITORIAL
            label_ko = policy.label_ko if policy is not None else "자동 수정 완료"
        elif policy is None:
            severity = FINDING_SEVERITY_BLOCK
            state = FINDING_TERMINAL
            family = "UNCLASSIFIED"
            label_ko = "분류되지 않은 품질 위험"
            if code and code not in unknown_codes:
                unknown_codes.append(code)
            if code and code not in terminal_codes:
                terminal_codes.append(code)
        elif policy.severity == FINDING_SEVERITY_BLOCK:
            severity = FINDING_SEVERITY_BLOCK
            state = FINDING_TERMINAL
            family = policy.family
            label_ko = policy.label_ko
            if code and code not in terminal_codes:
                terminal_codes.append(code)
        else:
            severity = FINDING_SEVERITY_REVIEW
            state = FINDING_RESIDUAL
            family = policy.family
            label_ko = policy.label_ko
            if code and code not in review_codes:
                review_codes.append(code)
        row.update(
            {
                "issue_code": code,
                "severity": severity,
                "finding_state": state,
                "family": family,
                "label_ko": label_ko,
            }
        )
        appended = _append_unique(normalized, row)
        if appended is not None:
            appended.update(
                {
                    key: row[key]
                    for key in ("severity", "finding_state", "family", "label_ko")
                }
            )

    if unknown_codes:
        safety = SAFETY_INCONCLUSIVE
    elif terminal_codes:
        safety = SAFETY_UNSAFE
    else:
        safety = SAFETY_SAFE

    residual_count = sum(1 for row in normalized if row.get("finding_state") == FINDING_RESIDUAL)
    if residual_count == 0:
        editorial = EDITORIAL_READY
    elif residual_count >= _POOR_REVIEW_FINDING_THRESHOLD:
        editorial = EDITORIAL_POOR
    else:
        editorial = EDITORIAL_REVIEW

    matrix = _canonical_delivery_matrix(safety, editorial)
    candidate_subject = str(subject or "").strip()
    candidate_html = str(email_html or "")
    delivery_subject = candidate_subject
    delivery_html = candidate_html
    if matrix["owner_delivery_behavior"] == OWNER_SEND_WARNING:
        residuals = [row for row in normalized if row.get("finding_state") == FINDING_RESIDUAL]
        delivery_subject = _review_subject(candidate_subject)
        delivery_html = _insert_after_body_open(candidate_html, _warning_panel(residuals))
    elif matrix["owner_delivery_behavior"] == OWNER_SEND_POOR_NOTICE:
        residuals = [row for row in normalized if row.get("finding_state") == FINDING_RESIDUAL]
        delivery_subject, delivery_html = _poor_notice(
            candidate_subject, owner_review_url, residuals
        )
    elif matrix["owner_delivery_behavior"] == OWNER_HOLD_INCIDENT:
        delivery_subject = ""
        delivery_html = ""

    issue_codes = list(dict.fromkeys([*terminal_codes, *review_codes, *repaired_codes]))
    out: Dict[str, Any] = {
        "quality_adjudicator": "keysuri_canonical_v1",
        "quality_adjudicator_count": 1,
        "program_id": str(program_id or ""),
        "safety_verdict": safety,
        "editorial_verdict": editorial,
        "findings": normalized,
        "terminal_issue_codes": terminal_codes,
        "review_issue_codes": review_codes,
        "repaired_issue_codes": repaired_codes,
        "issue_codes": issue_codes,
        "unknown_issue_codes": unknown_codes,
        "candidate_visible_surface_sha256": visible_surface_sha256(
            candidate_subject, candidate_html
        ),
        "candidate_email_subject": candidate_subject,
        "owner_email_subject": delivery_subject,
        "owner_email_html": delivery_html,
        "owner_email_visible_surface_sha256": (
            visible_surface_sha256(delivery_subject, delivery_html)
            if delivery_html
            else ""
        ),
        "adjudicated_visible_surface_sha256": (
            visible_surface_sha256(delivery_subject, delivery_html)
            if delivery_html
            else ""
        ),
        **matrix,
    }
    out["warning_confirmation_required"] = (
        matrix["customer_approval_policy"] == CUSTOMER_WARNING_CONFIRMATION
    )
    return out


def adjudicate_keysuri_owner_surface(
    *,
    program_id: str,
    subject: str,
    email_html: str,
    visible_quality_fields: Optional[Mapping[str, Any]] = None,
    post_render_result: Any = None,
    extra_findings: Optional[Sequence[Mapping[str, Any]]] = None,
    structured_briefing: Optional[Mapping[str, Any]] = None,
    owner_review_url: str = "",
) -> Dict[str, Any]:
    """The single public KeeSuri content-adjudication entrypoint.

    Callers may run as many finding-only detectors as needed, but every Global
    and Korea owner/customer delivery path must enter here exactly once with
    the final immutable subject and HTML surface.
    """
    structured_findings = _cross_field_context_findings(
        program_id, structured_briefing
    )
    result = adjudicate_keysuri_quality(
        program_id=program_id,
        subject=subject,
        email_html=email_html,
        findings=collect_keysuri_findings(
            visible_quality_fields=visible_quality_fields,
            post_render_result=post_render_result,
            extra_findings=[*(extra_findings or []), *structured_findings],
        ),
        owner_review_url=owner_review_url,
    )
    source_fields = (
        visible_quality_fields if isinstance(visible_quality_fields, Mapping) else {}
    )
    result["pre_repair_findings"] = [
        _bounded_text(code, 120)
        for code in list(source_fields.get("pre_repair_findings") or [])[:48]
        if _bounded_text(code, 120)
    ]
    history: List[Dict[str, Any]] = []
    repaired_codes = list(result.get("repaired_issue_codes") or [])
    for row in list(source_fields.get("repair_history") or [])[:24]:
        if isinstance(row, Mapping):
            compact = {
                "issue_code": _bounded_text(
                    row.get("issue_code")
                    or (repaired_codes[0] if len(repaired_codes) == 1 else ""),
                    120,
                ),
                "field": _bounded_text(
                    row.get("field") or row.get("path"), 180
                ),
                "rank": row.get("rank"),
                "source_id": _bounded_text(row.get("source_id"), 160),
                "before": _bounded_text(
                    row.get("before") or row.get("sample") or row.get("repair_before"),
                    180,
                ),
                "after": _bounded_text(
                    row.get("after")
                    or row.get("repaired_sample")
                    or row.get("repair_after"),
                    180,
                ),
            }
            compact = {
                key: value
                for key, value in compact.items()
                if value not in (None, "")
            }
            if compact.get("before") and compact.get("after"):
                history_key = (
                    str(compact.get("issue_code") or ""),
                    str(compact.get("field") or ""),
                    str(compact.get("before") or ""),
                    str(compact.get("after") or ""),
                )
                if not any(
                    (
                        str(existing.get("issue_code") or ""),
                        str(existing.get("field") or ""),
                        str(existing.get("before") or ""),
                        str(existing.get("after") or ""),
                    )
                    == history_key
                    for existing in history
                ):
                    history.append(compact)
    result["repair_history"] = history
    return result


def adjudication_artifact_fields(result: Mapping[str, Any]) -> Dict[str, Any]:
    """Bounded artifact view; excludes the duplicated HTML candidate."""
    keys = (
        "quality_adjudicator",
        "quality_adjudicator_count",
        "safety_verdict",
        "editorial_verdict",
        "terminal_issue_codes",
        "review_issue_codes",
        "repaired_issue_codes",
        "issue_codes",
        "unknown_issue_codes",
        "findings",
        "pre_repair_findings",
        "repair_history",
        "owner_delivery_behavior",
        "customer_approval_policy",
        "customer_approval_available",
        "warning_confirmation_required",
        "candidate_visible_surface_sha256",
        "candidate_email_subject",
        "owner_email_visible_surface_sha256",
        "adjudicated_visible_surface_sha256",
    )
    return {key: result.get(key) for key in keys}


def run_keysuri_graded_validation_no_send_proof() -> Dict[str, Any]:
    """Pure deployed-image proof for the canonical matrix and producer repairs.

    This function performs no I/O and owns no delivery capability. The
    protected internal endpoint uses it after deployment to prove the exact
    loaded revision without model, image, SMTP, customer, natural-run, or
    Scheduler side effects.
    """
    from keysuri_briefing_content_enricher import (
        _build_what_happened,
        enrich_korea_top5_item_content,
    )
    from keysuri_korea_signal_scoring import (
        CATEGORY_KO_LABELS,
        classify_korea_tech_category,
    )
    from keysuri_korea_longform_ux import sanitize_korea_customer_prose
    from keysuri_visible_text import contains_dangling_quoted_title_fragment

    def _case(name: str, program_id: str, codes: Sequence[str]) -> Dict[str, Any]:
        result = adjudicate_keysuri_owner_surface(
            program_id=program_id,
            subject="[운영자 검토] 배포 무발송 증명",
            email_html="<html><body><p>배포 무발송 품질 증명 표면</p></body></html>",
            extra_findings=[
                {"issue_code": code, "field": "deployed_no_send_proof"}
                for code in codes
            ],
        )
        return {
            "name": name,
            "safety_verdict": result["safety_verdict"],
            "editorial_verdict": result["editorial_verdict"],
            "owner_delivery_behavior": result["owner_delivery_behavior"],
            "customer_approval_policy": result["customer_approval_policy"],
            "review_issue_codes": result["review_issue_codes"],
            "terminal_issue_codes": result["terminal_issue_codes"],
        }

    def _structured_case(name: str, item: Mapping[str, Any]) -> Dict[str, Any]:
        result = adjudicate_keysuri_owner_surface(
            program_id="keysuri_korea_tech",
            subject="[운영자 검토] 배포 무발송 증명",
            email_html="<html><body><p>배포 무발송 품질 증명 표면</p></body></html>",
            structured_briefing={"top_5_news": {"items": [dict(item)]}},
        )
        return {
            "name": name,
            "safety_verdict": result["safety_verdict"],
            "editorial_verdict": result["editorial_verdict"],
            "owner_delivery_behavior": result["owner_delivery_behavior"],
            "customer_approval_policy": result["customer_approval_policy"],
            "review_issue_codes": result["review_issue_codes"],
            "terminal_issue_codes": result["terminal_issue_codes"],
        }

    bad_global_codes = (
        "global_visible_subject_integrity_blocked",
        "global_visible_raw_english_prose_blocked",
        "global_visible_internal_template_leak_blocked",
        "global_visible_semantic_truncation_blocked",
        "global_visible_repeated_template_skeleton_blocked",
        "global_visible_deep_dive_duplication_blocked",
        "global_visible_category_grounding_mismatch",
        "global_visible_korean_particle_defect",
    )
    slash_before = "국내 AI/로봇 시장을 함께 확인합니다."
    slash_after = sanitize_korea_customer_prose(slash_before)
    canonical_title = '\'美 투자 압박\' 보도에 靑 "통상현안 수시로 대응"'
    damaged_title = '美 투자 압박\' 보도에 靑 "통상현안 수시로 대응'
    grounded_title_sentence, _thin = _build_what_happened(
        {
            "rank": 2,
            "news_id": "claim-live-yna-industry-b25233e153",
            "korean_title": damaged_title,
            "what_happened": "첫 문장입니다. 둘째 문장입니다.",
        },
        {
            "statement": canonical_title,
            "source_name": "연합뉴스 산업",
            "primary_category": "korea_policy_regulation",
            "category_display_label": "국내 정책 / 규제 / 공공",
        },
    )
    deepx_source = (
        "딥엑스 NPU 양산 1년 수주. 국산 온디바이스 AI 반도체 DX-M1이 "
        "9개 국가에서 구매주문을 확보했고 초저전력 AI 반도체 양산을 확대했다."
    )
    deepx_category, _, _, deepx_reason = classify_korea_tech_category(deepx_source)
    deepx_meta = {
        "statement": "딥엑스 NPU, 양산 1년 만에 9개국서 수주 77건",
        "summary": deepx_source,
        "source_name": "공개 기술 매체",
        "primary_category": deepx_category,
        "category_label_ko": CATEGORY_KO_LABELS[deepx_category],
        "category_display_label": CATEGORY_KO_LABELS[deepx_category],
        "owner_action_line": (
            "내일 국내 반도체 / 장비 / 소재 관련 파트너·고객·입찰·정책 일정을 점검하세요."
        ),
        "next_day_impact_line": "내일 국내 반도체 공급망과 양산 일정을 확인하세요.",
    }
    deepx_broken = {
        "rank": 3,
        "news_id": "claim-live-platum-sanitized",
        "korean_title": "딥엑스, 온디바이스 AI 반도체 NPU 양산 1년 만에 9개국서 77건 수주",
        "what_happened": deepx_source,
        "why_now": "국내 시스템 반도체 생태계와 후공정 기업에 의미 있는 신호입니다.",
        "owner_angle": (
            "딥엑스의 실제 납품과 양산 확대를 확인해야 합니다. "
            "내일은 배터리·에너지 관련 파트너·고객·입찰 움직임만 보면 됩니다."
        ),
        "next_watch": "NPU 추가 수주와 파운드리·패키징 양산 일정을 확인하세요.",
        "selection_reason": "배터리·에너지 관점에서 오늘 한국에서 의미 있는 신호로 선정했습니다.",
        "category": "korea_battery_energy",
        "primary_category": "korea_battery_energy",
        "category_label_ko": "국내 배터리 / EV / 에너지",
        "owner_action_line": "내일 국내 배터리 / EV / 에너지 일정을 점검하세요.",
    }
    deepx_repaired = enrich_korea_top5_item_content(deepx_broken, meta=deepx_meta)
    deepx_repaired_twice = enrich_korea_top5_item_content(deepx_repaired, meta=deepx_meta)
    cases = [
        _case("good_global", "keysuri_global_tech", ()),
        _case("bad_global_20260814_1231", "keysuri_global_tech", bad_global_codes),
        _case("korea_ai_robot_after_repair", "keysuri_korea_tech", ()),
        _case("korea_dangling_title_after_grounded_repair", "keysuri_korea_tech", ()),
        _case(
            "ungrounded_semantic_truncation",
            "keysuri_korea_tech",
            ("keysuri_ungrounded_semantic_truncation",),
        ),
        _case("unsupported_claim", "keysuri_global_tech", ("unsupported_claim",)),
        _case(
            "safe_review_owner_path",
            "keysuri_global_tech",
            ("global_visible_raw_english_prose_blocked",),
        ),
        _structured_case("deepx_original_wrong_domain", deepx_broken),
        _structured_case("deepx_after_producer_repair", deepx_repaired),
    ]
    expected = {
        "good_global": (SAFETY_SAFE, EDITORIAL_READY, OWNER_SEND_READY),
        "bad_global_20260814_1231": (
            SAFETY_SAFE,
            EDITORIAL_POOR,
            OWNER_SEND_POOR_NOTICE,
        ),
        "korea_ai_robot_after_repair": (
            SAFETY_SAFE,
            EDITORIAL_READY,
            OWNER_SEND_READY,
        ),
        "korea_dangling_title_after_grounded_repair": (
            SAFETY_SAFE,
            EDITORIAL_READY,
            OWNER_SEND_READY,
        ),
        "ungrounded_semantic_truncation": (
            SAFETY_UNSAFE,
            EDITORIAL_READY,
            OWNER_HOLD_INCIDENT,
        ),
        "unsupported_claim": (
            SAFETY_UNSAFE,
            EDITORIAL_READY,
            OWNER_HOLD_INCIDENT,
        ),
        "safe_review_owner_path": (
            SAFETY_SAFE,
            EDITORIAL_REVIEW,
            OWNER_SEND_WARNING,
        ),
        "deepx_original_wrong_domain": (
            SAFETY_SAFE,
            EDITORIAL_REVIEW,
            OWNER_SEND_WARNING,
        ),
        "deepx_after_producer_repair": (
            SAFETY_SAFE,
            EDITORIAL_READY,
            OWNER_SEND_READY,
        ),
    }
    case_pass = all(
        (
            row["safety_verdict"],
            row["editorial_verdict"],
            row["owner_delivery_behavior"],
        )
        == expected[row["name"]]
        for row in cases
    )
    producer_pass = (
        slash_after == sanitize_korea_customer_prose(slash_after)
        and "AI/로봇" not in slash_after
        and canonical_title in grounded_title_sentence
        and f"「{damaged_title}」" not in grounded_title_sentence
        and not contains_dangling_quoted_title_fragment(grounded_title_sentence)
        and deepx_category == "korea_semiconductor"
        and "keyword_hits" in deepx_reason
        and deepx_repaired == deepx_repaired_twice
        and "배터리" not in str(deepx_repaired)
        and "NPU" in str(deepx_repaired)
    )
    return {
        "ok": bool(case_pass and producer_pass),
        "quality_adjudicator": "keysuri_canonical_v1",
        "cases": cases,
        "producer_repairs": {
            "ai_robot_idempotent": slash_after
            == sanitize_korea_customer_prose(slash_after),
            "ai_robot_repaired": "AI/로봇" not in slash_after,
            "dangling_title_grounded": canonical_title in grounded_title_sentence,
            "dangling_title_resolved": not contains_dangling_quoted_title_fragment(
                grounded_title_sentence
            ),
            "deepx_category": deepx_category,
            "deepx_category_reason": deepx_reason,
            "deepx_wrong_domain_removed": "배터리" not in str(deepx_repaired),
            "deepx_semiconductor_context_preserved": "NPU" in str(deepx_repaired),
            "deepx_repair_idempotent": deepx_repaired == deepx_repaired_twice,
        },
        "side_effects": {
            "model": 0,
            "image": 0,
            "smtp": 0,
            "customer": 0,
            "natural_mutation": 0,
            "scheduler_mutation": 0,
        },
        "customer_send": 0,
    }
