"""KST scheduling policy shared by scheduler endpoints and runtime entrypoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
WEEKEND_SKIP_REASON = "weekend_kst"

_SCHEDULED_TRIGGER_SOURCES = frozenset(
    {
        "scheduler",
        "cloud_scheduler",
        "internal_job",
        "scheduled_owner_review",
        "scheduled_service_full_run",
    }
)


def get_kst_now(now: Optional[datetime] = None) -> datetime:
    if now is None:
        return datetime.now(KST)
    if now.tzinfo is None:
        return now.replace(tzinfo=KST)
    return now.astimezone(KST)


def is_weekday_kst(now: Optional[datetime] = None) -> bool:
    return get_kst_now(now).weekday() < 5


def is_scheduled_trigger_source(trigger_source: Optional[str]) -> bool:
    normalized = str(trigger_source or "").strip().lower()
    return normalized in _SCHEDULED_TRIGGER_SOURCES or normalized.startswith("scheduled_")


def today_genie_weekend_skip_payload(
    *,
    trigger_source: Optional[str],
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    kst_now = get_kst_now(now)
    if not is_scheduled_trigger_source(trigger_source) or is_weekday_kst(kst_now):
        return None
    return {
        "ok": True,
        "skipped": True,
        "skipped_reason": WEEKEND_SKIP_REASON,
        "mode": "today_genie",
        "trigger_source": str(trigger_source or ""),
        "kst_date": kst_now.date().isoformat(),
        "kst_weekday": kst_now.strftime("%A"),
        "email_sent": False,
        "image_generation_skipped": True,
        "artifact_created": False,
    }


class ScheduledWeekendSkip(RuntimeError):
    def __init__(self, payload: Dict[str, Any]) -> None:
        super().__init__(WEEKEND_SKIP_REASON)
        self.payload = dict(payload)
