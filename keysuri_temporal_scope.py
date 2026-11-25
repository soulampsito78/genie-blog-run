"""Inspect event dates separately from article dates and monitoring labels.

Callers must supply independently observed primary-source
annotations. It does not fetch, manufacture or certify those annotations.
"""
from datetime import date, timedelta
import re

TEMPORAL_SCOPE_UNVERIFIED = "customer_surface_temporal_scope_unverified"


def inspect_temporal_scope(fields, *, mode, payload, source_input):
    if mode != "keysuri_korea_tech" or not isinstance(source_input, dict):
        return ()
    try:
        today = date.fromisoformat(str(source_input.get("target_date"))[:10])
    except ValueError:
        return ()
    items = (payload.get("top_5_news") or {}).get("items", [])
    rows = source_input.get("primary_event_time_evidence") or []
    findings = []
    for field in fields:
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("source_sha256", ""))) or not row.get("observed_at") or not str(row.get("source_url", "")).startswith("https://"):
                continue
            identity = row.get("news_id")
            if field.card_index > 0:
                if field.card_index > len(items) or items[field.card_index - 1].get("news_id") != identity:
                    continue
            elif not any(tag in field.text for tag in row.get("event_names", []) if tag):
                continue
            try:
                event_date = date.fromisoformat(str(row["event_date"]))
                outcome_date = date.fromisoformat(str(row.get("outcome_date") or row["event_date"]))
            except (KeyError, ValueError):
                continue
            watch = "next_watch" in field.path or ".action_lines[" in field.path
            explicit_old_date = (event_date.isoformat() in field.text or re.search(
                rf"{event_date.month}월\s*{event_date.day}일", field.text))
            if row.get("event_kind") == "forecast_revision" and event_date < today - timedelta(days=7) and not watch:
                if re.search(r"매출|전망|forecast", field.text, re.I) and not explicit_old_date and not re.search(r"기존|배경|앞서|당시", field.text):
                    findings.append((TEMPORAL_SCOPE_UNVERIFIED, field.path,
                                     "새 기사 게시일과 기존 전망 공시일을 구분할 기준일이 빠졌습니다.", field.card_index))
            # A monitoring action can happen tomorrow; the future event cannot.
            conditional_notice = re.search(r"공식.{0,20}(?:예고|공지)|브리핑.{0,12}일정|추가\s*공시|발표\s*일정", field.text)
            if watch and outcome_date > today + timedelta(days=1) and not conditional_notice:
                if re.search(r"공개|사양|시연|실적|매출.*달성", field.text):
                    findings.append((TEMPORAL_SCOPE_UNVERIFIED, field.path,
                                     "미래 행사·회계기간의 결과와 익일 공지 확인 행동을 구분해야 합니다.", field.card_index))
    return tuple(dict.fromkeys(findings))
