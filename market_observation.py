"""Canonical market observation identity and numeric invariants.

Shared by every briefing program that publishes index numbers. The contract it
enforces exists because correct source data became incorrect reader-visible
truth on 2026-08-28: a pre-open Naver quote reported KOSPI 6912.37 with a
0.00 change, and every downstream stage faithfully carried a "flat tape" that
never happened.

The failure was not arithmetic. The pipeline had no notion of *which session*
an observation described, so a live or not-yet-started session was
indistinguishable from a settled one. These are the rules that make that
distinction explicit and checkable:

- an observation belongs to exactly one session, identified by ``market_date``
- a briefing that reports a *previous* close may only publish an observation
  whose session closed before the briefing's target date
- unknown is unknown; it never becomes 0, "보합" or "변동 없음"
- a zero change is a factual claim and needs evidence like any other number
- close, previous_close, point_change and pct_change must agree, and are
  repaired from the authoritative raw fields when they do not
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Status values. Only SETTLED may reach a reader as a number.
SETTLED = "settled"
UNSETTLED_SESSION = "unsettled_session"
UNVERIFIABLE_ZERO = "unverifiable_zero"
INCOHERENT = "incoherent"
UNAVAILABLE = "unavailable"

PUBLISHABLE_STATUSES = frozenset({SETTLED})

# Rate agreement tolerance, in percentage points. Sources round differently;
# this is wide enough for rounding and far narrower than any real move.
RATE_TOLERANCE_PP = 0.05
# A daily index move beyond this is treated as a parse failure, not a market.
ABSURD_MOVE_PP = 40.0

# Session-state tokens a source may supply. Anything that means "this session
# is still running or has not started" makes the quote's change meaningless as
# a settled-session fact.
_LIVE_SESSION_TOKENS = frozenset(
    {
        "reg_mkt",
        "regular",
        "open",
        "live",
        "pre_mkt",
        "pre",
        "premarket",
        "pre_market",
        "intraday",
        "trading",
    }
)
_CLOSED_SESSION_TOKENS = frozenset(
    {
        "closed",
        "close",
        "post_mkt",
        "post",
        "postmarket",
        "post_market",
        "after_hours",
        "settled",
        "final",
    }
)


def _numeric(raw: Any) -> Optional[float]:
    """Signed finite number, or None. A blank or absent field is None, never 0."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        text = str(raw).strip().replace(",", "")
        if text.endswith("%"):
            text = text[:-1].strip()
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _iso_date(raw: Any) -> Optional[date]:
    if raw is None:
        return None
    text = str(raw).strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _session_state(slot: Dict[str, Any]) -> Optional[str]:
    """'live' / 'closed' / None from whatever session marker the source supplies."""
    for key in ("session_state", "market_status", "curmktstatus", "quote_status"):
        raw = slot.get(key)
        if raw is None:
            continue
        token = str(raw).strip().lower()
        if not token:
            continue
        if token in _LIVE_SESSION_TOKENS:
            return "live"
        if token in _CLOSED_SESSION_TOKENS:
            return "closed"
    return None


def _first_numeric(slot: Dict[str, Any], keys: Sequence[str]) -> Tuple[Optional[float], str]:
    for key in keys:
        if key not in slot:
            continue
        value = _numeric(slot.get(key))
        if value is not None:
            return value, key
    return None, ""


def normalize_market_observation(
    instrument: str,
    slot: Any,
    *,
    target_date: Any,
    feed_as_of: Any = None,
    require_prior_session: bool = True,
) -> Dict[str, Any]:
    """One index row reduced to a single coherent observation identity.

    ``require_prior_session`` encodes the product contract: a "전일 마감" /
    "밤사이 마감" row may only carry a session that closed before the briefing
    date. Programs that legitimately report a live tape pass False.

    The returned dict always carries ``observation_status``. Callers must treat
    anything outside :data:`PUBLISHABLE_STATUSES` as "no number available" —
    never as zero.
    """
    repairs: List[str] = []
    result: Dict[str, Any] = {
        "instrument": instrument,
        "market_date": None,
        "close": None,
        "previous_close": None,
        "point_change": None,
        "pct_change": None,
        "session_state": None,
        "observation_status": UNAVAILABLE,
        "observation_reason": "slot_absent",
        "observation_repairs": repairs,
    }
    if not isinstance(slot, dict):
        return result

    result["session_state"] = _session_state(slot)

    close = _numeric(slot.get("close"))
    if close is None or close <= 0:
        result["observation_reason"] = f"close_not_positive_number({slot.get('close')!r})"
        return result
    result["close"] = close

    # --- observation identity -------------------------------------------------
    # The slot's own date wins. A feed-level date is a fallback only: it is the
    # aggregate over several instruments, and borrowing it lets one instrument
    # inherit another's session.
    market_date = _iso_date(slot.get("market_date") or slot.get("as_of"))
    inherited = False
    if market_date is None:
        market_date = _iso_date(feed_as_of)
        inherited = market_date is not None
    if market_date is None:
        result["observation_reason"] = "market_date_unknown"
        return result
    result["market_date"] = market_date.isoformat()
    if inherited:
        repairs.append("market_date_inherited_from_feed")

    target = _iso_date(target_date)
    if require_prior_session:
        if target is None:
            result["observation_reason"] = "target_date_unknown"
            return result
        if market_date >= target:
            # The session this quote describes has not completed as of the
            # briefing date. Its close is a live or pre-open print and its
            # change is not a settled-session change.
            result["observation_status"] = UNSETTLED_SESSION
            result["observation_reason"] = (
                f"session {market_date.isoformat()} is not a completed session "
                f"before target {target.isoformat()}"
            )
            return result
    if result["session_state"] == "live" and not (
        require_prior_session and target is not None and market_date < target
    ):
        # Session state describes the market, not the quote. Once the quote's own
        # session date is strictly in the past, that date is the stronger
        # evidence: a US close carried at 03:29 ET is settled even though the
        # next session has already been flagged pre-market. A live status over a
        # stale timestamp is caught instead by the coherence and zero-evidence
        # rules below, which is where it actually shows up.
        result["observation_status"] = UNSETTLED_SESSION
        result["observation_reason"] = "source reports the session as still trading"
        return result

    # --- numeric coherence ----------------------------------------------------
    prev, prev_key = _first_numeric(slot, ("previous_close", "prev_close", "prior_close"))
    prev_sourced = prev is not None
    pts, _ = _first_numeric(slot, ("point_change", "change_pts", "change_points"))
    pct, _ = _first_numeric(slot, ("pct_change", "change_pct", "change_rate"))

    if prev is None and pts is not None:
        prev = close - pts
        repairs.append("previous_close_derived_from_point_change")
    if prev is not None and prev <= 0:
        result["observation_status"] = INCOHERENT
        result["observation_reason"] = f"previous_close_not_positive({prev})"
        return result

    derived_pts: Optional[float] = None
    derived_pct: Optional[float] = None
    if prev is not None:
        derived_pts = close - prev
        derived_pct = derived_pts / prev * 100.0

    # previous_close carried by the source is authoritative: it and the close
    # are two independently published prints of the same observation, so a
    # disagreeing rate is repaired rather than trusted.
    if derived_pct is not None and prev_sourced:
        if pct is not None and abs(pct - derived_pct) > RATE_TOLERANCE_PP:
            repairs.append(
                f"pct_change_repaired_from_{prev_key}:{pct:+.2f}->{derived_pct:+.2f}"
            )
            pct = derived_pct
        elif pct is None:
            repairs.append(f"pct_change_derived_from_{prev_key}")
            pct = derived_pct
        if pts is not None and abs(pts - derived_pts) > max(abs(derived_pts) * 0.01, 0.05):
            repairs.append("point_change_repaired_from_previous_close")
            pts = derived_pts
        elif pts is None:
            pts = derived_pts
    elif pct is None and derived_pct is not None:
        repairs.append("pct_change_derived_from_point_change")
        pct = derived_pct

    if pct is None:
        # Unknown stays unknown. This is the branch that used to yield 0.
        result["observation_status"] = UNAVAILABLE
        result["observation_reason"] = "change_rate_unknown"
        return result

    if not prev_sourced and pts is not None and pct != 0:
        # Only a magnitude was published for one of the two; make sure they at
        # least agree in direction before either reaches a reader.
        if (pts > 0) != (pct > 0):
            result["observation_status"] = INCOHERENT
            result["observation_reason"] = f"point_change {pts} contradicts rate {pct}"
            return result

    if abs(pct) >= ABSURD_MOVE_PP:
        result["observation_status"] = INCOHERENT
        result["observation_reason"] = f"rate {pct}% outside plausible daily range"
        return result

    # --- zero needs evidence like any other number ---------------------------
    if _is_zero(pct):
        if not _zero_is_evidenced(slot, close=close, prev=prev, prev_sourced=prev_sourced):
            # A quote snapshot whose change reads 0.00 is exactly what a market
            # that has not traded yet looks like. Without a settled previous
            # close that independently proves the flat print, publishing "보합"
            # would be asserting a fact the source never established.
            result["observation_status"] = UNVERIFIABLE_ZERO
            result["observation_reason"] = (
                "zero change carries no settled previous close to corroborate it"
            )
            return result

    result["previous_close"] = None if prev is None else round(prev, 4)
    result["point_change"] = None if pts is None else round(pts, 4)
    result["pct_change"] = round(pct, 2)
    result["observation_status"] = SETTLED
    result["observation_reason"] = ""
    return result


def _is_zero(value: float) -> bool:
    return abs(value) < 1e-9


def _zero_is_evidenced(
    slot: Dict[str, Any],
    *,
    close: float,
    prev: Optional[float],
    prev_sourced: bool,
) -> bool:
    """Whether a 0.00% change is an established fact rather than an unmoved quote.

    Only a source that publishes a dated, completed session may assert a flat
    close. A quote's own previous_close is not evidence: when a provider rolls
    its reference forward at the pre-market open it sets previous_day_closing
    equal to the last settled close, so `previous_close == close` with a zero
    change is precisely the shape of a quote that has not traded — observed on
    CNBC's US indices at 03:29 ET on 2026-08-28, reproducing the same defect
    that shipped from Naver's pre-open KOSPI quote that morning.
    """
    return bool(str(slot.get("settlement_evidence") or "").strip())


def normalize_index_feed(
    feed: Any,
    *,
    target_date: Any,
    require_prior_session: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Normalize every index in one feed and strip unpublishable numbers.

    Returns ``(feed, report)``. Rows that fail the contract keep their identity
    and their diagnostic status but lose the numeric fields, so that no later
    stage — prompt, model, producer or renderer — can read a number the
    contract rejected.
    """
    report: Dict[str, Any] = {
        "observations": {},
        "unpublishable": [],
        "repairs": [],
        "all_zero_change": False,
    }
    if not isinstance(feed, dict):
        return {}, report
    indices = feed.get("indices")
    if not isinstance(indices, dict):
        return dict(feed), report

    feed_as_of = feed.get("as_of")
    normalized_indices: Dict[str, Any] = {}
    settled_dates: List[str] = []
    zero_rates = 0
    rated = 0

    for instrument, slot in indices.items():
        obs = normalize_market_observation(
            str(instrument),
            slot,
            target_date=target_date,
            feed_as_of=feed_as_of,
            require_prior_session=require_prior_session,
        )
        report["observations"][str(instrument)] = {
            key: obs[key]
            for key in (
                "market_date",
                "close",
                "previous_close",
                "point_change",
                "pct_change",
                "session_state",
                "observation_status",
                "observation_reason",
            )
        }
        for repair in obs["observation_repairs"]:
            report["repairs"].append(f"{instrument}: {repair}")

        row = dict(slot) if isinstance(slot, dict) else {}
        row["market_date"] = obs["market_date"]
        row["observation_status"] = obs["observation_status"]
        if obs["observation_reason"]:
            row["observation_reason"] = obs["observation_reason"]

        if obs["observation_status"] in PUBLISHABLE_STATUSES:
            row["close"] = obs["close"]
            row["change_pct"] = obs["pct_change"]
            row["change_pts"] = obs["point_change"]
            row["previous_close"] = obs["previous_close"]
            row["change_direction"] = _signum(obs["pct_change"])
            if obs["market_date"]:
                settled_dates.append(obs["market_date"])
            rated += 1
            if _is_zero(obs["pct_change"]):
                zero_rates += 1
        else:
            # Identity and provenance survive; the numbers do not.
            for key in ("change_pct", "change_pts", "previous_close", "change_direction"):
                row.pop(key, None)
            if obs["observation_status"] != UNAVAILABLE or obs["close"] is not None:
                row["close"] = obs["close"]
            report["unpublishable"].append(
                f"{instrument}: {obs['observation_status']} — {obs['observation_reason']}"
            )
        normalized_indices[instrument] = row

    normalized = dict(feed)
    normalized["indices"] = normalized_indices
    if settled_dates:
        normalized["as_of"] = max(settled_dates)
    # Several independent instruments printing an exact 0.00 at once is the
    # signature of a pre-session snapshot, not of a market.
    report["all_zero_change"] = rated >= 2 and zero_rates == rated
    return normalized, report


def _signum(value: Optional[float]) -> Optional[int]:
    if value is None:
        return None
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


MAX_HISTORY_REPAIR_AGE_DAYS = 5


def repair_feed_from_history(
    feed: Dict[str, Any],
    report: Dict[str, Any],
    *,
    target_date: Any,
    history: Dict[str, Dict[str, Any]],
    max_age_days: int = MAX_HISTORY_REPAIR_AGE_DAYS,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Restore unpublishable rows from previously captured settled observations.

    Only observations that already satisfied the settlement contract are stored,
    so this reinstates a fact that was established earlier — it never creates
    one. A stored observation is refused when it is not older than the briefing
    date, or when it has aged past ``max_age_days`` and would misrepresent "the
    last completed session".
    """
    target = _iso_date(target_date)
    indices = feed.get("indices")
    if target is None or not isinstance(indices, dict):
        return feed, report

    repaired: List[str] = []
    still_unpublishable: List[str] = []
    for entry in report.get("unpublishable", []):
        instrument = str(entry).split(":", 1)[0].strip()
        stored = history.get(instrument)
        row = indices.get(instrument)
        if not isinstance(stored, dict) or not isinstance(row, dict):
            still_unpublishable.append(entry)
            continue
        stored_date = _iso_date(stored.get("market_date"))
        pct = _numeric(stored.get("pct_change"))
        close = _numeric(stored.get("close"))
        if stored_date is None or pct is None or close is None:
            still_unpublishable.append(entry)
            continue
        if stored_date >= target or (target - stored_date).days > max_age_days:
            still_unpublishable.append(
                f"{entry} (stored settled session {stored_date.isoformat()} not usable)"
            )
            continue

        row["close"] = close
        row["change_pct"] = pct
        row["change_pts"] = stored.get("point_change")
        row["previous_close"] = stored.get("previous_close")
        row["change_direction"] = _signum(pct)
        row["market_date"] = stored_date.isoformat()
        row["as_of"] = stored_date.isoformat()
        row["observation_status"] = SETTLED
        row["observation_reason"] = ""
        row["observation_repaired_from_history"] = stored_date.isoformat()
        observations = report.setdefault("observations", {})
        observations[instrument] = {
            **{k: stored.get(k) for k in ("market_date", "close", "previous_close",
                                          "point_change", "pct_change")},
            "session_state": "closed",
            "observation_status": SETTLED,
            "observation_reason": "",
        }
        repaired.append(f"{instrument}: restored settled session {stored_date.isoformat()}")

    report["unpublishable"] = still_unpublishable
    if repaired:
        report.setdefault("history_repairs", []).extend(repaired)
        settled_dates = [
            str(obs.get("market_date"))
            for obs in report.get("observations", {}).values()
            if isinstance(obs, dict)
            and obs.get("observation_status") in PUBLISHABLE_STATUSES
            and obs.get("market_date")
        ]
        if settled_dates:
            feed["as_of"] = max(settled_dates)
    return feed, report


# --- post-generation fact consistency ---------------------------------------

# Reader-visible claims of a flat tape. Generated prose may not assert any of
# these about an instrument whose canonical change is non-zero.
FLAT_CLAIM_PHRASES: Tuple[str, ...] = (
    "변동 없이",
    "변동 없음",
    "변동이 없",
    "변동없이",
    "보합",
    "제자리",
    "unchanged",
    "flat",
)

_RISE_PHRASES: Tuple[str, ...] = ("상승", "급등", "올랐", "오른", "강세", "뛰었")
_FALL_PHRASES: Tuple[str, ...] = ("하락", "급락", "내렸", "내린", "약세", "빠졌")


def prose_fact_conflicts(
    text: Any,
    observations: Dict[str, Dict[str, Any]],
    labels: Dict[str, Sequence[str]],
) -> List[str]:
    """Generated statements that contradict the canonical observations.

    ``labels`` maps an instrument key to the reader-facing names that may refer
    to it. A conflict is reported only when the sentence mentioning the
    instrument makes a directional claim the canonical number rules out, so a
    correct sentence about a different index is never blamed.
    """
    conflicts: List[str] = []
    blob = str(text or "")
    if not blob.strip():
        return conflicts

    for sentence in _split_sentences(blob):
        for instrument, names in labels.items():
            if not any(name and name in sentence for name in names):
                continue
            obs = observations.get(instrument)
            if not isinstance(obs, dict):
                continue
            if obs.get("observation_status") not in PUBLISHABLE_STATUSES:
                continue
            pct = obs.get("pct_change")
            if not isinstance(pct, (int, float)):
                continue
            if not _is_zero(float(pct)):
                if any(phrase in sentence for phrase in FLAT_CLAIM_PHRASES):
                    conflicts.append(
                        f"{instrument}: 실제 등락률 {float(pct):+.2f}% 인데 본문이 보합·변동 없음으로 서술"
                    )
                    continue
                if float(pct) > 0 and _mentions(sentence, _FALL_PHRASES) and not _mentions(
                    sentence, _RISE_PHRASES
                ):
                    conflicts.append(
                        f"{instrument}: 실제 등락률 {float(pct):+.2f}% 인데 본문이 하락으로 서술"
                    )
                elif float(pct) < 0 and _mentions(sentence, _RISE_PHRASES) and not _mentions(
                    sentence, _FALL_PHRASES
                ):
                    conflicts.append(
                        f"{instrument}: 실제 등락률 {float(pct):+.2f}% 인데 본문이 상승으로 서술"
                    )
    return conflicts


def _mentions(sentence: str, phrases: Sequence[str]) -> bool:
    return any(phrase in sentence for phrase in phrases)


def _split_sentences(blob: str) -> List[str]:
    out: List[str] = []
    current: List[str] = []
    for ch in blob:
        current.append(ch)
        if ch in ".!?\n":
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return [s for s in out if s.strip()]
