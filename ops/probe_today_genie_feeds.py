#!/usr/bin/env python3
"""
Public-source probe for Today_Geenee feed JSON files (ops/feeds/*.json).

Fetches index quotes and market news from documented public pages only.
Does not call Gemini, does not invent index values, and does not update Cloud Run.

Usage:
  python3 ops/probe_today_genie_feeds.py --dry-run --strict
  python3 ops/probe_today_genie_feeds.py --write --target-date 2026-06-09 --strict
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

OPS_ROOT = Path(__file__).resolve().parent
FEEDS_DIR = OPS_ROOT / "feeds"
BACKUP_DIR = FEEDS_DIR / ".backup"

USER_AGENT = "GenieTodayFeedProbe/1.0 (+operator-public-source-probe)"
VERIFIED_BY = "operator_public_source_probe"
SOURCE_SCOPE = "public_web_collection_probe"
STALE_REFERENCE_DATE = "2026-05-29"
MAX_STALE_DAYS = 7

CNBC_QUOTES = {
    "SPX": "https://www.cnbc.com/quotes/.SPX",
    "NASDAQ": "https://www.cnbc.com/quotes/.IXIC",
    "DJI": "https://www.cnbc.com/quotes/.DJI",
    "NIKKEI": "https://www.cnbc.com/quotes/.N225",
}
NAVER_INDEX = {
    "KOSPI": "https://finance.naver.com/sise/sise_index.nhn?code=KOSPI",
    "KOSDAQ": "https://finance.naver.com/sise/sise_index.nhn?code=KOSDAQ",
}
CNBC_MARKET_NEWS_RSS = "https://www.cnbc.com/id/100003114/device/rss/rss.html"

FEED_FILES = {
    "overnight_us_market": "overnight_us_market.json",
    "macro_indicators": "macro_indicators.json",
    "korea_japan_indices": "korea_japan_indices.json",
    "top_market_news": "top_market_news.json",
    "risk_factors": "risk_factors.json",
}

FetchFn = Callable[[str, int], str]


class FeedProbeError(Exception):
    """Raised when a feed cannot be probed safely."""


def _utc_now_iso() -> str:
    return datetime.now(ZoneInfo("UTC")).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _kst_today_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()


def _parse_iso_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text or text.upper() == "UNCH":
        return 0.0
    try:
        return float(text)
    except ValueError:
        return None


def _explicit_sign(raw: Any) -> Optional[int]:
    """+1/-1 when the source text carried its own sign, else None (magnitude only)."""
    text = str(raw or "").strip()
    if text.startswith("-"):
        return -1
    if text.startswith("+"):
        return 1
    return None


def recompute_change_pct(
    close: Optional[float],
    change_pts: Optional[float],
) -> Optional[float]:
    """Percent change derived from close and point change; None when underivable.

    previous_close = close - change_pts, so this stays correct for both
    directions without ever assuming a sign.
    """
    if close is None or change_pts is None:
        return None
    previous_close = close - change_pts
    if previous_close <= 0:
        return None
    return round(change_pts / previous_close * 100.0, 2)


def _fmt_summary_pct(value: Optional[float]) -> str:
    """Summary-line percent. Never renders an unknown or a flat tape as a gain."""
    if value is None:
        return "n/a"
    if value == 0:
        return "0.00%"
    return f"{value:+.2f}%"


def default_fetch_url(url: str, timeout_sec: int = 20) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urlopen(req, timeout=timeout_sec) as resp:
        raw = resp.read()
    encoding = "euc-kr" if "finance.naver.com" in url else "utf-8"
    return raw.decode(encoding, errors="replace")


def parse_cnbc_quote_html(html: str, symbol: str) -> Dict[str, Any]:
    """Parse CNBC quote page JSON-LD price fields near the canonical quote block."""
    price_m = re.search(r'"price"\s*:\s*"([0-9,.]+)"', html)
    if not price_m:
        raise FeedProbeError(f"CNBC {symbol}: missing price")

    idx = html.find('"price"')
    chunk = html[idx : idx + 400] if idx >= 0 else html[:400]
    change_re = re.compile(r'"priceChange"\s*:\s*"([^"]+)"')
    pct_re = re.compile(r'"priceChangePercent"\s*:\s*"([^"]+)"')
    # The quote block layout varies; fall back to the whole document rather than
    # letting a narrow window turn a real move into a missing (then zeroed) rate.
    change_m = change_re.search(chunk) or change_re.search(html)
    pct_m = pct_re.search(chunk) or pct_re.search(html)
    time_m = re.search(r'"last_time"\s*:\s*"([^"]+)"', html)

    close = _parse_float(price_m.group(1))
    if close is None:
        raise FeedProbeError(f"CNBC {symbol}: invalid close")

    change_pts = _parse_float(change_m.group(1) if change_m else None)
    change_pct = _parse_float(pct_m.group(1) if pct_m else None)
    if change_pct is None:
        # Missing rate is recomputed from close/point change when possible, and
        # otherwise stays unknown. It is never silently substituted with 0.
        change_pct = recompute_change_pct(close, change_pts)

    as_of: Optional[str] = None
    if time_m:
        ts = time_m.group(1).strip()
        date_prefix_m = re.match(r"(\d{4}-\d{2}-\d{2})", ts)
        if date_prefix_m:
            as_of = date_prefix_m.group(1)
        elif re.match(r"^\d{4}-\d{2}-\d{2}$", ts):
            as_of = ts
        else:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                as_of = dt.date().isoformat()
            except ValueError:
                pass

    digits = 4 if symbol == "NASDAQ" else 2
    return {
        "close": round(close, digits),
        "change_pts": None if change_pts is None else round(change_pts, digits),
        "change_pct": None if change_pct is None else round(change_pct, 2),
        "as_of": as_of,
        "source_name": "CNBC",
        "source_url": CNBC_QUOTES[symbol],
        "confidence": "high",
        "accuracy_status": "verified",
        "notes": f"Parsed from CNBC public quote page for {symbol}.",
    }


NAVER_DIRECTION_SIGNS = {"상승": 1, "하락": -1, "보합": 0}
_NAVER_CHANGE_WINDOW_CHARS = 400


def _naver_change_scope(html: str) -> str:
    """Markup scope carrying Naver's change value, rate and direction marker.

    The container's closing tags vary between page revisions, so an unmatched
    anchor falls back to a bounded window instead of yielding an empty scope
    (which used to make every field parse as a missing, then zeroed, value).
    """
    block_m = re.search(r'id="change_value_and_rate"[^>]*>([\s\S]*?)</span>\s*</div>', html)
    if block_m and block_m.group(1).strip():
        return block_m.group(1)
    idx = html.find('id="change_value_and_rate"')
    if idx < 0:
        return ""
    return html[idx : idx + _NAVER_CHANGE_WINDOW_CHARS]


def _naver_direction_sign(scope: str) -> Optional[int]:
    """+1/-1/0 from Naver's 상승·하락·보합 marker; None when undetermined.

    Matched on the word alone so a changed wrapper element or class list does
    not silently drop the direction.
    """
    m = re.search(r"(상승|하락|보합)", scope)
    if not m:
        return None
    return NAVER_DIRECTION_SIGNS[m.group(1)]


def parse_naver_index_html(html: str, code: str) -> Dict[str, Any]:
    close_m = re.search(r'id="now_value"[^>]*>([0-9,.]+)', html)
    if not close_m:
        raise FeedProbeError(f"Naver {code}: missing close")

    scope = _naver_change_scope(html)
    pts_m = re.search(r"<span>\s*([-+]?[0-9,.]+)\s*</span>", scope)
    pct_m = re.search(r"([-+]?[0-9,.]+)\s*%", scope)
    time_m = re.search(r'id="time"[^>]*>([0-9.]+)', html)

    close = _parse_float(close_m.group(1))
    if close is None:
        raise FeedProbeError(f"Naver {code}: invalid close")

    raw_pct = pct_m.group(1) if pct_m else None
    raw_pts = pts_m.group(1) if pts_m else None
    change_pct = _parse_float(raw_pct)
    change_pts = _parse_float(raw_pts)
    if change_pct is None:
        raise FeedProbeError(f"Naver {code}: missing change rate")

    # Naver publishes the rate as an unsigned magnitude plus a separate
    # direction marker. Resolve the two into one signed number, and refuse to
    # emit a rate whose direction could not be established — an undetermined
    # direction must never fall through as a gain.
    direction_sign = _naver_direction_sign(scope)
    explicit_sign = _explicit_sign(raw_pct)
    if direction_sign is None and explicit_sign is None and change_pct != 0:
        raise FeedProbeError(
            f"Naver {code}: change direction undetermined for magnitude {change_pct}"
        )
    if direction_sign is not None and explicit_sign is not None and direction_sign != explicit_sign:
        raise FeedProbeError(
            f"Naver {code}: direction marker and signed rate conflict "
            f"(direction={direction_sign}, rate={change_pct})"
        )
    if direction_sign == 0 and change_pct != 0:
        raise FeedProbeError(
            f"Naver {code}: 보합 marker contradicts non-zero rate {change_pct}"
        )
    sign = direction_sign if direction_sign is not None else (explicit_sign or 0)

    change_pct = 0.0 if sign == 0 else sign * abs(change_pct)
    if change_pts is not None:
        pts_sign = _explicit_sign(raw_pts)
        if pts_sign is not None and sign != 0 and pts_sign != sign:
            raise FeedProbeError(
                f"Naver {code}: point change sign conflicts with rate direction"
            )
        change_pts = 0.0 if sign == 0 else sign * abs(change_pts)

    as_of: Optional[str] = None
    if time_m:
        parts = time_m.group(1).split(".")
        if len(parts) == 3:
            as_of = f"{parts[0]}-{parts[1]}-{parts[2]}"

    return {
        "close": round(close, 2),
        "change_pts": None if change_pts is None else round(change_pts, 2),
        "change_pct": round(change_pct, 2),
        "change_direction": sign,
        "as_of": as_of,
        "source_name": "Naver Finance",
        "source_url": NAVER_INDEX[code],
        "cross_check_url": NAVER_INDEX[code],
        "confidence": "high",
        "accuracy_status": "verified",
        "notes": f"Parsed from Naver Finance public index page for {code}.",
    }


def parse_cnbc_rss_xml(xml: str, *, min_items: int = 4, max_items: int = 6) -> List[Dict[str, str]]:
    items = re.findall(r"<item>(.*?)</item>", xml, re.S)
    out: List[Dict[str, str]] = []
    for item in items:
        title_m = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, re.S)
        if not title_m:
            continue
        headline = re.sub(r"\s+", " ", title_m.group(1).strip())
        headline = headline.replace("&apos;", "'").replace("&amp;", "&")
        if not headline or headline.lower() == "cnbc":
            continue
        pub_m = re.search(r"<pubDate>([^<]+)</pubDate>", item)
        item_date = ""
        if pub_m:
            try:
                item_date = parsedate_to_datetime(pub_m.group(1).strip()).date().isoformat()
            except (TypeError, ValueError, OverflowError):
                item_date = ""
        if not item_date:
            continue
        out.append({"headline": headline, "source": "CNBC", "date": item_date})
        if len(out) >= max_items:
            break
    if len(out) < min_items:
        raise FeedProbeError(f"CNBC RSS: insufficient recent news items ({len(out)} < {min_items})")
    return out


def _index_row(symbol: str, row: Dict[str, Any], *, session: str = "") -> Dict[str, Any]:
    payload = dict(row)
    if session and symbol == "NIKKEI":
        payload.setdefault("as_of", row.get("as_of"))
        payload.setdefault("session", session)
    payload.setdefault("cross_check_url", row.get("source_url", ""))
    return payload


def probe_overnight_us_market(
    target_date: str,
    fetch_fn: FetchFn = default_fetch_url,
    *,
    timeout_sec: int = 20,
) -> Dict[str, Any]:
    fetched_at = _utc_now_iso()
    indices: Dict[str, Any] = {}
    as_of_dates: List[str] = []

    for symbol in ("SPX", "NASDAQ", "DJI"):
        html = fetch_fn(CNBC_QUOTES[symbol], timeout_sec)
        row = parse_cnbc_quote_html(html, symbol)
        if row.get("as_of"):
            as_of_dates.append(str(row["as_of"]))
        indices[symbol] = _index_row(symbol, row)

    as_of = max(as_of_dates) if as_of_dates else target_date
    _assert_as_of_fresh(as_of, target_date, "overnight_us_market")

    parts = []
    for sym, label in (("SPX", "S&P 500"), ("NASDAQ", "Nasdaq"), ("DJI", "Dow")):
        r = indices[sym]
        parts.append(f"{label} {_fmt_summary_pct(r.get('change_pct'))}")
    summary = (
        f"US indexes closed on {as_of}: {', '.join(parts)}. "
        "Public-source draft only. Not a licensed automated market-data feed."
    )

    return {
        "as_of": as_of,
        "session": "US cash close (public CNBC quote probe)",
        "fetched_at": fetched_at,
        "verified_at": fetched_at,
        "verified_by": VERIFIED_BY,
        "source_scope": SOURCE_SCOPE,
        "indices": indices,
        "summary": summary,
    }


def probe_korea_japan_indices(
    target_date: str,
    fetch_fn: FetchFn = default_fetch_url,
    *,
    timeout_sec: int = 20,
) -> Dict[str, Any]:
    fetched_at = _utc_now_iso()
    indices: Dict[str, Any] = {}
    as_of_dates: List[str] = []

    for code in ("KOSPI", "KOSDAQ"):
        html = fetch_fn(NAVER_INDEX[code], timeout_sec)
        row = parse_naver_index_html(html, code)
        if row.get("as_of"):
            as_of_dates.append(str(row["as_of"]))
        indices[code] = _index_row(code, row)

    nikkei_html = fetch_fn(CNBC_QUOTES["NIKKEI"], timeout_sec)
    nikkei_row = parse_cnbc_quote_html(nikkei_html, "NIKKEI")
    if nikkei_row.get("as_of"):
        as_of_dates.append(str(nikkei_row["as_of"]))
    indices["NIKKEI"] = _index_row(
        "NIKKEI",
        nikkei_row,
        session="Japan cash close (JST, CNBC public quote probe)",
    )
    indices["NIKKEI"]["session"] = "Japan cash close (JST, CNBC public quote probe)"

    as_of = max(as_of_dates) if as_of_dates else target_date
    _assert_as_of_fresh(as_of, target_date, "korea_japan_indices")

    summary = (
        f"Asia indexes as of {as_of}: KOSPI {_fmt_summary_pct(indices['KOSPI'].get('change_pct'))}, "
        f"KOSDAQ {_fmt_summary_pct(indices['KOSDAQ'].get('change_pct'))}, "
        f"Nikkei {_fmt_summary_pct(indices['NIKKEI'].get('change_pct'))}. "
        "Public-source draft only. Not a licensed automated market-data feed."
    )

    return {
        "as_of": as_of,
        "session": "Asia market session (public source probe)",
        "fetched_at": fetched_at,
        "verified_at": fetched_at,
        "verified_by": VERIFIED_BY,
        "source_scope": SOURCE_SCOPE,
        "indices": indices,
        "summary": summary,
    }


def build_macro_indicators(
    overnight: Dict[str, Any],
    korea_japan: Dict[str, Any],
    target_date: str,
) -> Dict[str, Any]:
    as_of = max(
        str(overnight.get("as_of") or target_date),
        str(korea_japan.get("as_of") or target_date),
    )
    _assert_as_of_fresh(as_of, target_date, "macro_indicators")
    us = overnight.get("summary") or ""
    asia = korea_japan.get("summary") or ""
    headline = (
        f"Public probe snapshot for {as_of}: {us.split('.')[0]}. "
        f"{asia.split('.')[0]}."
    ).strip()
    return {
        "as_of": as_of,
        "headline": headline[:500],
        "rates_watch": (
            "No dedicated live UST/Fed page parsed in this probe; "
            "rates context deferred to owner review from public headlines."
        ),
        "dxy_note": (
            "No dedicated live DXY page parsed in this probe; "
            "FX tone should be cross-checked manually if needed."
        ),
    }


def probe_top_market_news(
    target_date: str,
    fetch_fn: FetchFn = default_fetch_url,
    *,
    timeout_sec: int = 20,
) -> List[Dict[str, str]]:
    xml = fetch_fn(CNBC_MARKET_NEWS_RSS, timeout_sec)
    items = parse_cnbc_rss_xml(xml)
    target = _parse_iso_date(target_date)
    if target is None:
        raise FeedProbeError("top_market_news: invalid target_date")
    for item in items:
        item_date = _parse_iso_date(item.get("date"))
        if item_date is None:
            raise FeedProbeError("top_market_news: missing item date")
        if (target - item_date).days > MAX_STALE_DAYS:
            raise FeedProbeError(
                f"top_market_news: stale item date {item_date.isoformat()} for target {target_date}"
            )
        if item_date.isoformat() == STALE_REFERENCE_DATE:
            raise FeedProbeError("top_market_news: stale reference date 2026-05-29")
    return items


def build_risk_factors(news_items: List[Dict[str, str]], macro: Dict[str, Any]) -> List[Dict[str, str]]:
    risks: List[Dict[str, str]] = []
    if news_items:
        top = news_items[0]
        risks.append(
            {
                "risk": "Headline / geopolitics",
                "detail": (
                    f"Sourced from CNBC RSS ({top.get('date')}): "
                    f"{top.get('headline', '')[:240]}"
                ),
            }
        )
    if len(news_items) > 1:
        second = news_items[1]
        risks.append(
            {
                "risk": "Policy / macro narrative",
                "detail": (
                    f"Sourced from CNBC RSS ({second.get('date')}): "
                    f"{second.get('headline', '')[:240]}"
                ),
            }
        )
    elif macro.get("headline"):
        risks.append(
            {
                "risk": "Macro / index tone",
                "detail": str(macro.get("headline"))[:300],
            }
        )
    if not risks:
        raise FeedProbeError("risk_factors: no sourced headlines available")
    return risks


def _assert_as_of_fresh(as_of: str, target_date: str, feed_name: str) -> None:
    as_of_d = _parse_iso_date(as_of)
    target_d = _parse_iso_date(target_date)
    if as_of_d is None or target_d is None:
        raise FeedProbeError(f"{feed_name}: invalid as_of or target_date")
    if as_of_d.isoformat() == STALE_REFERENCE_DATE:
        raise FeedProbeError(f"{feed_name}: stale reference date {STALE_REFERENCE_DATE}")
    if (target_d - as_of_d).days > MAX_STALE_DAYS:
        raise FeedProbeError(
            f"{feed_name}: as_of={as_of} stale for target_date={target_date}"
        )


def validate_today_genie_feed_files(target_date: str, feed_dir: Path) -> Dict[str, Any]:
    """Validate feed JSON files for syntax, schema, and stale-date safety."""
    result: Dict[str, Any] = {
        "ok": True,
        "target_date": target_date,
        "feeds": {},
        "errors": [],
    }
    target_d = _parse_iso_date(target_date)
    if target_d is None:
        result["ok"] = False
        result["errors"].append("invalid target_date")
        return result

    def _err(feed: str, msg: str) -> None:
        result["ok"] = False
        result["errors"].append(f"{feed}: {msg}")
        result["feeds"].setdefault(feed, {"ok": False, "errors": []})
        result["feeds"][feed]["ok"] = False
        result["feeds"][feed].setdefault("errors", []).append(msg)

    overnight_path = feed_dir / FEED_FILES["overnight_us_market"]
    macro_path = feed_dir / FEED_FILES["macro_indicators"]
    kj_path = feed_dir / FEED_FILES["korea_japan_indices"]
    news_path = feed_dir / FEED_FILES["top_market_news"]
    risk_path = feed_dir / FEED_FILES["risk_factors"]

    paths = {
        "overnight_us_market": overnight_path,
        "macro_indicators": macro_path,
        "korea_japan_indices": kj_path,
        "top_market_news": news_path,
        "risk_factors": risk_path,
    }

    loaded: Dict[str, Any] = {}
    for name, path in paths.items():
        feed_result: Dict[str, Any] = {"ok": True, "path": str(path), "errors": []}
        result["feeds"][name] = feed_result
        if not path.is_file():
            _err(name, "missing file")
            continue
        try:
            loaded[name] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            _err(name, f"invalid JSON: {exc}")

    if not result["ok"]:
        return result

    for feed_name in ("overnight_us_market", "macro_indicators", "korea_japan_indices"):
        obj = loaded.get(feed_name)
        if not isinstance(obj, dict):
            _err(feed_name, "must be object")
            continue
        as_of = obj.get("as_of")
        if not as_of:
            _err(feed_name, "missing as_of")
        else:
            as_of_d = _parse_iso_date(as_of)
            if as_of_d is None:
                _err(feed_name, "invalid as_of")
            elif as_of_d.isoformat() == STALE_REFERENCE_DATE:
                _err(feed_name, f"stale reference date {STALE_REFERENCE_DATE}")
            elif (target_d - as_of_d).days > MAX_STALE_DAYS:
                _err(feed_name, f"as_of {as_of} older than {MAX_STALE_DAYS} days")

    us = loaded.get("overnight_us_market", {})
    if isinstance(us, dict):
        idx = us.get("indices")
        if not isinstance(idx, dict):
            _err("overnight_us_market", "missing indices object")
        else:
            for sym in ("SPX", "NASDAQ", "DJI"):
                row = idx.get(sym)
                if not isinstance(row, dict):
                    _err("overnight_us_market", f"missing {sym}")
                elif row.get("close") is None or row.get("change_pct") is None:
                    _err("overnight_us_market", f"{sym} missing close/change_pct")

    kj = loaded.get("korea_japan_indices", {})
    if isinstance(kj, dict):
        idx = kj.get("indices")
        if not isinstance(idx, dict):
            _err("korea_japan_indices", "missing indices object")
        else:
            for sym in ("KOSPI", "KOSDAQ", "NIKKEI"):
                row = idx.get(sym)
                if not isinstance(row, dict):
                    _err("korea_japan_indices", f"missing {sym}")
                elif row.get("close") is None or row.get("change_pct") is None:
                    _err("korea_japan_indices", f"{sym} missing close/change_pct")

    macro = loaded.get("macro_indicators", {})
    if isinstance(macro, dict):
        for key in ("as_of", "headline", "rates_watch", "dxy_note"):
            if not str(macro.get(key) or "").strip():
                _err("macro_indicators", f"missing {key}")

    news = loaded.get("top_market_news")
    if not isinstance(news, list) or not news:
        _err("top_market_news", "must be non-empty array")
    else:
        for i, item in enumerate(news):
            if not isinstance(item, dict):
                _err("top_market_news", f"item[{i}] not object")
                continue
            for key in ("headline", "source", "date"):
                if not str(item.get(key) or "").strip():
                    _err("top_market_news", f"item[{i}] missing {key}")
            item_date = _parse_iso_date(item.get("date"))
            if item_date is None:
                _err("top_market_news", f"item[{i}] invalid date")
            elif item_date.isoformat() == STALE_REFERENCE_DATE:
                _err("top_market_news", f"item[{i}] stale date {STALE_REFERENCE_DATE}")
            elif (target_d - item_date).days > MAX_STALE_DAYS:
                _err("top_market_news", f"item[{i}] date too old")

    risks = loaded.get("risk_factors")
    if not isinstance(risks, list) or not risks:
        _err("risk_factors", "must be non-empty array")
    else:
        for i, item in enumerate(risks):
            if not isinstance(item, dict):
                _err("risk_factors", f"item[{i}] not object")
            else:
                for key in ("risk", "detail"):
                    if not str(item.get(key) or "").strip():
                        _err("risk_factors", f"item[{i}] missing {key}")

    return result


def probe_all_feeds(
    target_date: str,
    fetch_fn: FetchFn = default_fetch_url,
    *,
    timeout_sec: int = 20,
) -> Dict[str, Any]:
    overnight = probe_overnight_us_market(target_date, fetch_fn, timeout_sec=timeout_sec)
    korea_japan = probe_korea_japan_indices(target_date, fetch_fn, timeout_sec=timeout_sec)
    macro = build_macro_indicators(overnight, korea_japan, target_date)
    news = probe_top_market_news(target_date, fetch_fn, timeout_sec=timeout_sec)
    risks = build_risk_factors(news, macro)
    return {
        "overnight_us_market": overnight,
        "macro_indicators": macro,
        "korea_japan_indices": korea_japan,
        "top_market_news": news,
        "risk_factors": risks,
    }


def _backup_feed_files(feed_dir: Path) -> Path:
    stamp = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for fname in FEED_FILES.values():
        src = feed_dir / fname
        if src.is_file():
            shutil.copy2(src, dest / fname)
    return dest


def write_feed_files(feeds: Dict[str, Any], feed_dir: Path, *, backup: bool = True) -> Optional[Path]:
    if backup:
        backup_path = _backup_feed_files(feed_dir)
    else:
        backup_path = None
    feed_dir.mkdir(parents=True, exist_ok=True)
    for key, fname in FEED_FILES.items():
        payload = feeds[key]
        path = feed_dir / fname
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return backup_path


def _print_summary(feeds: Dict[str, Any], target_date: str) -> None:
    print(f"target_date={target_date}")
    us = feeds["overnight_us_market"]
    kj = feeds["korea_japan_indices"]
    print(f"overnight_us_market.as_of={us.get('as_of')}")
    for sym in ("SPX", "NASDAQ", "DJI"):
        row = us["indices"][sym]
        print(f"  {sym}: close={row.get('close')} change_pct={row.get('change_pct')}")
    print(f"korea_japan_indices.as_of={kj.get('as_of')}")
    for sym in ("KOSPI", "KOSDAQ", "NIKKEI"):
        row = kj["indices"][sym]
        print(f"  {sym}: close={row.get('close')} change_pct={row.get('change_pct')}")
    print(f"macro_indicators.as_of={feeds['macro_indicators'].get('as_of')}")
    print(f"top_market_news: {len(feeds['top_market_news'])} items")
    for item in feeds["top_market_news"][:4]:
        print(f"  - {item.get('date')} | {item.get('headline', '')[:90]}")
    print(f"risk_factors: {len(feeds['risk_factors'])} items")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Probe public sources for Today_Geenee feeds.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Fetch/validate only; do not write files.")
    mode.add_argument("--write", action="store_true", help="Write validated feeds to ops/feeds/.")
    parser.add_argument("--target-date", default=_kst_today_iso(), help="KST target date YYYY-MM-DD.")
    parser.add_argument("--strict", action="store_true", help="Fail if any required feed cannot be refreshed.")
    parser.add_argument("--allow-partial", action="store_true", help="Allow writing/feigning partial success.")
    parser.add_argument("--feed-dir", default=str(FEEDS_DIR), help="Feed directory (default: ops/feeds).")
    args = parser.parse_args(argv)

    target_date = str(args.target_date).strip()
    feed_dir = Path(args.feed_dir)

    try:
        feeds = probe_all_feeds(target_date)
    except (FeedProbeError, HTTPError, URLError, TimeoutError) as exc:
        print(f"FEED_SOURCE_UNAVAILABLE: {exc}", file=sys.stderr)
        return 2

    candidate_validation = {
        "overnight_us_market": feeds["overnight_us_market"],
        "macro_indicators": feeds["macro_indicators"],
        "korea_japan_indices": feeds["korea_japan_indices"],
        "top_market_news": feeds["top_market_news"],
        "risk_factors": feeds["risk_factors"],
    }
    tmp_dir = feed_dir / ".probe_validate_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        for key, fname in FEED_FILES.items():
            (tmp_dir / fname).write_text(
                json.dumps(candidate_validation[key], ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        candidate_check = validate_today_genie_feed_files(target_date, tmp_dir)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if not candidate_check.get("ok"):
        print("FEED_PROBE_UNSAFE_TO_WRITE:", candidate_check.get("errors"), file=sys.stderr)
        if args.strict:
            return 3

    _print_summary(feeds, target_date)

    if args.dry_run:
        print("dry-run: no files written")
        return 0

    if args.strict and not candidate_check.get("ok"):
        return 3

    if not args.write:
        return 0

    backup_path = write_feed_files(feeds, feed_dir, backup=True)
    post_check = validate_today_genie_feed_files(target_date, feed_dir)
    if not post_check.get("ok"):
        print("FEED_PROBE_UNSAFE_TO_WRITE after write:", post_check.get("errors"), file=sys.stderr)
        return 3
    if backup_path:
        print(f"backup: {backup_path}")
    print(f"wrote feeds under {feed_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
