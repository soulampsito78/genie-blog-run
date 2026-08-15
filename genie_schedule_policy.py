"""KST scheduling policy shared by scheduler endpoints and runtime entrypoints.

This module is the single publishing-day authority for scheduled editorial
programs. Korean public holidays are non-publishing days
(``docs/BUSINESS_BRAND_SSOT_v1.md``); the Scheduler cron stays weekday-only and
the application declines the run deterministically before any expensive work.
Holiday *data* lives in ``korea_public_holidays``; the decision lives here.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from korea_public_holidays import (
    COVERAGE_END_YEAR,
    COVERAGE_START_YEAR,
    KOREA_EXTRA_NON_PUBLISHING_DAYS,
    KOREA_PUBLIC_HOLIDAYS,
)

KST = ZoneInfo("Asia/Seoul")
WEEKEND_SKIP_REASON = "weekend_kst"
HOLIDAY_SKIP_REASON = "korean_public_holiday"
SKIPPED_HOLIDAY_STATUS = "SKIPPED_HOLIDAY"
# The preflight endpoint carries no trigger_source: it is Scheduler-only and its
# canary execution class is itself the scheduled trigger.
SCHEDULED_PREFLIGHT_TRIGGER_SOURCE = "scheduled_preflight_canary"

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


def _as_kst_date(value: Optional[Any] = None) -> date:
    """Accept a date, a datetime, an ISO string, or None (= now in KST)."""
    if value is None:
        return get_kst_now().date()
    if isinstance(value, datetime):
        return get_kst_now(value).date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


def holiday_calendar_covers(value: Optional[Any] = None) -> bool:
    """True when the curated table can answer for this date's year."""
    return COVERAGE_START_YEAR <= _as_kst_date(value).year <= COVERAGE_END_YEAR


def korean_public_holiday_name(value: Optional[Any] = None) -> Optional[str]:
    """Holiday name for a KST date, or None when it is an ordinary day.

    Outside the curated coverage window this returns None (publishing continues)
    rather than silently halting every program; the coverage tripwire test fails
    first so the table is refreshed before the window lapses.
    """
    key = _as_kst_date(value).isoformat()
    return KOREA_EXTRA_NON_PUBLISHING_DAYS.get(key) or KOREA_PUBLIC_HOLIDAYS.get(key)


def is_korean_public_holiday(value: Optional[Any] = None) -> bool:
    return korean_public_holiday_name(value) is not None


def is_korean_publishing_day(value: Optional[Any] = None) -> bool:
    """Scheduled editorial publication is allowed on this KST date."""
    target = _as_kst_date(value)
    return target.weekday() < 5 and not is_korean_public_holiday(target)


def scheduled_holiday_skip_payload(
    *,
    program_id: str,
    trigger_source: Optional[str],
    scheduled_slot: Optional[str] = None,
    execution_class: Optional[str] = None,
    dry_run: bool = False,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Deterministic skip for a scheduled run landing on a Korean holiday.

    Returns ``None`` when the run may proceed. Only scheduled triggers are
    gated: manual, recovery, reissue, smoke and canary semantics are unchanged.
    ``dry_run`` publishes nothing, so it stays available on a holiday and is not
    gated. This is an intentional schedule state, never a content or
    infrastructure failure, so callers must surface it as HTTP 200.
    """
    if dry_run or not is_scheduled_trigger_source(trigger_source):
        return None
    kst_now = get_kst_now(now)
    holiday_name = korean_public_holiday_name(kst_now)
    if holiday_name is None:
        return None
    payload: Dict[str, Any] = {
        "ok": True,
        "skipped": True,
        "skipped_reason": HOLIDAY_SKIP_REASON,
        "skip_reason": HOLIDAY_SKIP_REASON,
        "publishing_day": False,
        "operational_status": SKIPPED_HOLIDAY_STATUS,
        "program_id": str(program_id or ""),
        "mode": str(program_id or ""),
        "trigger_source": str(trigger_source or ""),
        "target_date_kst": kst_now.date().isoformat(),
        "kst_date": kst_now.date().isoformat(),
        "kst_weekday": kst_now.strftime("%A"),
        "holiday_name": holiday_name,
        "called_gemini": False,
        "called_image_api": False,
        "email_sent": False,
        "smtp_attempted": False,
        "image_generation_skipped": True,
        "artifact_created": False,
        "customer_send": 0,
    }
    if scheduled_slot:
        payload["scheduled_slot"] = str(scheduled_slot)
    if execution_class:
        payload["execution_class"] = str(execution_class)
    return payload


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
