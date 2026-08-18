"""KST trial bounds and first-delivery calendar calculations.

Trial duration is fourteen calendar days.  Delivery starts no earlier than the
next KST calendar day and uses the repository's existing Korean publication-
day authority; this module does not gain scheduler or send authority.
"""

import datetime as dt
from typing import Tuple
from zoneinfo import ZoneInfo

from customer.domain.catalog import TRIAL_CALENDAR_DAYS
from customer.domain.clock import UTC, ensure_utc
from genie_schedule_policy import is_korean_publishing_day


KST = ZoneInfo("Asia/Seoul")


def trial_bounds(moment: dt.datetime) -> Tuple[dt.datetime, dt.datetime]:
    """Return the exact start and the exclusive end fourteen KST days later."""
    start_at = ensure_utc(moment)
    end_kst = start_at.astimezone(KST) + dt.timedelta(days=TRIAL_CALENDAR_DAYS)
    return start_at, end_kst.astimezone(UTC)


def first_delivery_date(moment: dt.datetime) -> dt.date:
    """Return the first publication day after the KST application date."""
    candidate = ensure_utc(moment).astimezone(KST).date() + dt.timedelta(days=1)
    while not is_korean_publishing_day(candidate):
        candidate += dt.timedelta(days=1)
    return candidate
