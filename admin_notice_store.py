"""Admin operational customer notices: storage and state machine.

Fully separate from briefing run artifacts (admin_store.py / output/admin_runs).
Notices never reference sent_news_log and never read or write briefing run
fields (customer_sent/email_sent/smtp_accepted on a run artifact).

Notice JSON never stores the actual recipient email address list — only a
count and a human-readable source label, to keep PII out of disk artifacts.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

NOTICE_TYPES = (
    "delay_notice",
    "quality_check_notice",
    "resolved_notice",
    "incident_notice",
    "custom_notice",
)

NOTICE_STATUSES = frozenset({"draft", "previewed", "sent", "failed"})

VISIBLE_RECIPIENT_POLICY = "undisclosed_recipients_bcc_envelope_only"

_NOTICE_ID_RE = re.compile(
    r"^notice_(?:delay_notice|quality_check_notice|resolved_notice|incident_notice|custom_notice)"
    r"_[0-9]{8}_[a-f0-9]{8}$"
)

# Default subject/body templates. custom_notice has no default body (free text).
NOTICE_TEMPLATES: Dict[str, Dict[str, str]] = {
    "quality_check_notice": {
        "subject": "[키수리 글로벌테크] 오늘 브리핑 품질 점검 안내",
        "body_text": (
            "오늘 키수리 글로벌테크 브리핑은 품질 점검으로 인해 평소보다 발송이 지연되고 있습니다.\n"
            "검수 완료 후 발송하겠습니다.\n"
            "기다려 주셔서 감사합니다."
        ),
    },
    "delay_notice": {
        "subject": "[키수리 글로벌테크] 오늘 브리핑 발송 지연 안내",
        "body_text": (
            "오늘 키수리 글로벌테크 브리핑은 품질 확인 과정으로 인해 발송이 지연되었습니다.\n"
            "정확한 내용을 보내드리기 위해 검수 후 발송하겠습니다."
        ),
    },
    "resolved_notice": {
        "subject": "[키수리 글로벌테크] 지연된 브리핑 발송 완료 안내",
        "body_text": (
            "품질 점검으로 지연되었던 오늘 키수리 글로벌테크 브리핑 발송이 완료되었습니다.\n"
            "기다려 주셔서 감사합니다."
        ),
    },
    "incident_notice": {
        "subject": "[키수리 글로벌테크] 서비스 장애 안내",
        "body_text": "",
    },
    "custom_notice": {
        "subject": "",
        "body_text": "",
    },
}


def repo_root() -> Path:
    return Path(__file__).resolve().parent


def admin_notices_dir() -> Path:
    d = repo_root() / "output" / "admin_notices"
    d.mkdir(parents=True, exist_ok=True)
    return d


def now_kst_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat()


def validate_notice_id(notice_id: str) -> bool:
    return bool(_NOTICE_ID_RE.match(str(notice_id or "")))


def generate_notice_id(notice_type: str) -> str:
    if notice_type not in NOTICE_TYPES:
        raise ValueError(f"unknown notice_type: {notice_type!r}")
    date_part = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    return f"notice_{notice_type}_{date_part}_{secrets.token_hex(4)}"


def _notice_path(notice_id: str) -> Path:
    return admin_notices_dir() / f"{notice_id}.json"


def save_notice(notice: Dict[str, Any]) -> None:
    notice_id = str(notice.get("notice_id") or "")
    if not validate_notice_id(notice_id):
        raise ValueError(f"invalid notice_id: {notice_id!r}")
    path = _notice_path(notice_id)
    path.write_text(json.dumps(notice, ensure_ascii=False, indent=2), encoding="utf-8")


def load_notice(notice_id: str) -> Optional[Dict[str, Any]]:
    if not validate_notice_id(notice_id):
        return None
    path = _notice_path(notice_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def list_notices(limit: int = 50) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in admin_notices_dir().glob("notice_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            rows.append(data)
    rows.sort(key=lambda n: str(n.get("created_at") or ""), reverse=True)
    return rows[:limit]


def create_notice_draft(
    *,
    notice_type: str,
    program_id: str,
    related_run_id: Optional[str],
    subject: str,
    body_text: str,
    body_html: str,
) -> Dict[str, Any]:
    """Build and persist a new draft notice. Never touches run artifacts."""
    if notice_type not in NOTICE_TYPES:
        raise ValueError(f"unknown notice_type: {notice_type!r}")
    notice_id = generate_notice_id(notice_type)
    notice: Dict[str, Any] = {
        "notice_id": notice_id,
        "notice_type": notice_type,
        "program_id": str(program_id or "").strip(),
        "related_run_id": str(related_run_id).strip() if related_run_id else None,
        "subject": str(subject or "").strip(),
        "body_text": str(body_text or "").strip(),
        "body_html": str(body_html or ""),
        "recipients_count": 0,
        "recipient_source": "",
        "created_at": now_kst_iso(),
        "previewed_at": None,
        "sent_at": None,
        "sent_by": None,
        "status": "draft",
        "smtp_accepted": None,
        "send_error": None,
        "visible_recipient_policy": VISIBLE_RECIPIENT_POLICY,
        "pii_safe_delivery": True,
    }
    save_notice(notice)
    return notice


def mark_previewed(notice: Dict[str, Any], *, recipients_count: int, recipient_source: str) -> Dict[str, Any]:
    """Record a preview render. Never sends email."""
    notice = dict(notice)
    notice["recipients_count"] = int(recipients_count)
    notice["recipient_source"] = str(recipient_source or "")
    notice["previewed_at"] = now_kst_iso()
    notice["status"] = "previewed"
    save_notice(notice)
    return notice


def mark_sent(notice: Dict[str, Any], *, sent_by: str) -> Dict[str, Any]:
    notice = dict(notice)
    notice["status"] = "sent"
    notice["sent_at"] = now_kst_iso()
    notice["sent_by"] = str(sent_by or "admin")
    notice["smtp_accepted"] = True
    notice["send_error"] = None
    save_notice(notice)
    return notice


def mark_failed(notice: Dict[str, Any], *, send_error: str, sent_by: str) -> Dict[str, Any]:
    notice = dict(notice)
    notice["status"] = "failed"
    notice["sent_at"] = now_kst_iso()
    notice["sent_by"] = str(sent_by or "admin")
    notice["smtp_accepted"] = False
    notice["send_error"] = str(send_error or "send_failed")
    save_notice(notice)
    return notice
