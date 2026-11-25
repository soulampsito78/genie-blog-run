"""Conservative event identity from source metadata, never a topical cluster."""
from __future__ import annotations

import re
from datetime import date


def event_identity(item):
    """Require a named event, a real date and an organizer; otherwise abstain.

    Explicit metadata works for any event. The bilingual fallback is deliberately
    limited to the observed AI Wave spelling variants, not all AI conferences.
    Publication time supplies only the month/year of an explicit event day.
    """
    name = str(item.get("event_name") or "").strip().casefold()
    when = str(item.get("event_date") or "").strip()
    organizer = str(item.get("event_organizer") or "").strip().casefold()
    if name and when and organizer:
        try:
            date.fromisoformat(when)
        except ValueError:
            return ""
        return "|".join((re.sub(r"\W+", "", name), when, organizer))
    text = " ".join(str(item.get(k) or "") for k in
                    ("headline", "title", "summary", "snippet", "statement"))
    event = re.search(r"(?:AI\s*Wave|AI\s*웨이브)\s*[:：]?\s*(?:Seoul|서울)\s*(20\d{2})", text, re.I)
    day = re.search(r"(?:지난\s*)?(?:(\d{1,2})\s*월\s*)?(\d{1,2})\s*일.{0,100}(?:개최|열고|열었)", text)
    if not event or not day or not re.search(r"킨드레드\s*벤처스|Kindred\s*Ventures", text, re.I):
        return ""
    published = str(item.get("published_at") or "")
    try:
        month = int(day[1]) if day[1] else date.fromisoformat(published[:10]).month
        when = date(int(event[1]), month, int(day[2])).isoformat()
    except (ValueError, TypeError):
        return ""
    return "|".join(("ai-wave-seoul", when, "kindred-ventures"))


def same_event(left, right):
    identity = event_identity(left)
    return bool(identity and identity == event_identity(right))
