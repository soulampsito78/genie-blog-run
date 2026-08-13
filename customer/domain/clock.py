"""Injectable clock.

Every auth/session decision in this package is time-dependent, so time is a
dependency rather than an ambient call. Services take a `Clock` and never call
`datetime.now()` directly; tests pass a `FixedClock` and advance it explicitly
instead of sleeping.

All internal timestamps are timezone-aware UTC. KST is a presentation concern
and is applied only at output boundaries.
"""

import datetime as dt
from typing import Optional

UTC = dt.timezone.utc


class Clock:
    """Source of the current instant."""

    def now(self) -> dt.datetime:  # pragma: no cover - interface
        raise NotImplementedError


class SystemClock(Clock):
    """Real wall clock, always timezone-aware UTC."""

    def now(self) -> dt.datetime:
        return dt.datetime.now(UTC)


class FixedClock(Clock):
    """Deterministic clock for tests.

    `advance()` moves time forward explicitly, which is what lets session
    expiry, inactivity, and fresh-auth windows be tested exactly at their
    boundaries without a single `sleep`.
    """

    def __init__(self, start: Optional[dt.datetime] = None) -> None:
        self._now = start or dt.datetime(2026, 8, 11, 0, 0, 0, tzinfo=UTC)
        if self._now.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")

    def now(self) -> dt.datetime:
        return self._now

    def advance(self, delta: dt.timedelta) -> dt.datetime:
        self._now = self._now + delta
        return self._now

    def set(self, moment: dt.datetime) -> dt.datetime:
        if moment.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._now = moment
        return self._now


def ensure_utc(moment: dt.datetime) -> dt.datetime:
    """Normalise a datetime to timezone-aware UTC.

    PostgreSQL returns `timestamptz` as aware datetimes, but a value that has
    round-tripped through a naive source would otherwise compare incorrectly
    against clock output. Fail loudly rather than guessing an offset.
    """
    if moment.tzinfo is None:
        raise ValueError("naive datetime in customer auth domain: {0!r}".format(moment))
    return moment.astimezone(UTC)
