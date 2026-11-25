"""Narrow, inspect-only claim-scope checks. No rewriting or fact certification."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Mapping

CLAIM_SCOPE_UNVERIFIED = "customer_surface_claim_scope_unverified"
EVENT_DESTINATION_UNVERIFIED = "customer_surface_event_destination_unverified"


def selected_source_evidence(prompt_input: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Keep only selected, ID-bound source metadata; never call it article text."""
    pack = prompt_input.get("source_pack") or {}
    sources = pack.get("sources", []) if isinstance(pack, Mapping) else []
    top = prompt_input.get("top_5_news") or {}
    items = top.get("items", []) if isinstance(top, Mapping) else []
    result = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        ids = set(item.get("source_ids") or [])
        matched = [s for s in sources if isinstance(s, Mapping) and s.get("source_id") in ids]
        for source in matched:
            result.append({
                "news_id": item.get("news_id"), "source_id": source.get("source_id"),
                "source_url": source.get("source_url"),
                "title": str(source.get("title") or "")[:1000],
                "snippet": str(source.get("snippet") or "")[:4000],
                "evidence_scope": "RSS_METADATA_ONLY",
            })
    return result


def _source_text(source: Mapping[str, Any]) -> str:
    return " ".join(str(source.get(k) or "") for k in ("title", "headline", "summary", "snippet"))


def _reported_usd(source: str) -> set[Decimal]:
    values = set()
    for match in re.finditer(r"(?:reported|reportedly|estimated).{0,24}\$\s*(\d[\d,]*(?:\.\d+)?)\s*(billion|million|bn|b\b|m\b)?", source, re.I):
        value = Decimal(match[1].replace(",", "").rstrip("."))
        unit = (match[2] or "").lower()
        values.add(value * (10**9 if unit in {"billion", "bn", "b"} else 10**6 if unit in {"million", "m"} else 1))
    return values


def _visible_usd(text: str) -> set[Decimal]:
    return {Decimal(m[1].replace(",", "")) * {"조": 10**12, "억": 10**8, "만": 10**4, "천": 1000, None: 1}[m[2]]
            for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(조|억|만|천)?\s*달러", text)}


def inspect_source_scope(fields, *, mode: str, payload: Mapping[str, Any], source_input=None):
    """Return (code,path,reason,card_index) for observed scope escalations only.

    A finding requests source-backed review. An empty result is NOT a factual
    PASS. Source facts cannot be supplied by the generated payload itself.
    """
    source_input = source_input if isinstance(source_input, Mapping) else {}
    evidence = selected_source_evidence(source_input)
    top = payload.get("top_5_news") or {}
    items = top.get("items", []) if isinstance(top, Mapping) else []
    today_sources = source_input.get("top_market_news") or []
    findings = []
    for field in fields:
        if mode == "today_genie":
            # "Washington" or "the president" in the headline is not a
            # destination for a named corporate executive's reinstatement.
            wrong_destination = re.search(r"(?:CEO|젠슨\s*황)(?:의|가|는|이)?\s*(?:백악관|대통령실|청와대)\s*복귀", field.text, re.I)
            if wrong_destination:
                # The presence of another article about the White House must
                # not clear a CEO card. Reuse the producer's canonical news ID.
                source = ""
                cards = payload.get("key_watchpoints") or []
                if 0 < field.card_index <= len(cards) and isinstance(cards[field.card_index - 1], Mapping):
                    from today_genie_top3_assembly import canonical_news_id
                    identity = cards[field.card_index - 1].get("news_id")
                    matches = [s for s in today_sources if isinstance(s, Mapping)
                               and identity and canonical_news_id(dict(s)) == identity]
                    if len(matches) == 1:
                        source = _source_text(matches[0])
                explicit = re.search(r"return(?:ed|ing)?\s+to\s+the\s+White\s+House|백악관(?:으로|에)\s*복귀", source, re.I)
                if not explicit:
                    findings.append((EVENT_DESTINATION_UNVERIFIED, field.path,
                                     "기업 CEO의 복귀 목적지를 정부 기관으로 바꿀 입력 근거가 없습니다.", field.card_index))
            continue
        if mode not in {"keysuri_global_tech", "keysuri_korea_tech"}:
            continue
        bound = evidence
        if field.card_index > 0:
            if field.card_index > len(items) or not isinstance(items[field.card_index - 1], Mapping):
                continue
            identity = items[field.card_index - 1].get("news_id")
            bound = [s for s in evidence if identity and s["news_id"] == identity]
        source = " ".join(_source_text(s) for s in bound)
        if not source:
            continue
        for clause in re.split(r"(?<!\d)[.!?。](?!\d)|\n|하지만|그러나|다만|(?<=했)지만", field.text):
            # A statement that completion is unknown or a future checkpoint
            # must not be mistaken for an assertion of completion.
            if re.search(r"아닌|아니다|미확인|확인되지|여부|예정|계획|할\s*수|경우", clause):
                continue
            reason = None
            if mode == "keysuri_korea_tech" and re.search(r"수주(?:액|금액)", clause):
                # A counterparty/project batch is not a company-wide total.
                # This requests review even if the RSS itself omitted the scope.
                batch = re.search(r"\d+\s*(?:건|개\s*프로젝트)", source)
                if batch and re.search(r"공급|협력사|생산라인", source):
                    if re.search(r"(?:올해|연간)\s*누적\s*수주", clause) and not re.search(r"프로젝트|계약.{0,12}합산|고객사.{0,12}대상", clause):
                        reason = "거래 상대방·프로젝트 묶음의 수주액을 회사 전체 누적으로 확대할 수 있어 원문 범위 확인이 필요합니다."
            deal = re.search(r"acquir|acquisition|purchase|인수|매입", source, re.I)
            if deal and re.search(r"인수(?:를)?\s*(?:단행|완료|확정)|인수했", clause):
                if not re.search(r"completed\s+(?:the\s+)?acquisition|closed\s+(?:the\s+)?deal|인수\s*완료", source, re.I):
                    reason = "거래 종결 근거 없이 인수 완료를 단정했습니다."
            if deal and re.search(r"(?:기업|회사|스타트업).{0,45}인수", clause):
                asset_object = re.search(r"(?:acquir\w*|purchas\w*).{0,80}(?:technology|tech\b|intellectual\s+property|stack)|기술\s*매입", source, re.I)
                if asset_object or not re.search(r"acquir\w*.{0,80}(?:company|startup)|(?:company|startup).{0,80}acquir", source, re.I):
                    reason = "입력 메타데이터만으로 회사 전체 인수를 특정할 수 없습니다."
            if _reported_usd(source) & _visible_usd(clause):
                if not re.search(r"보도|추정|전해|reported", clause, re.I):
                    reason = "보도·추정 금액의 출처상 한정이 빠졌습니다."
            if re.search(r"repositor|저장소", source, re.I) and re.search(
                r"전면\s*(?:도입|배포)|성공적으로.{0,20}(?:이식|도입|배포)|코드\s*리뷰.{0,12}자동화", clause
            ):
                if not re.search(r"fully\s+deployed|all.{0,30}automatically\s+(?:approved|deployed)|전면\s*도입\s*완료", source, re.I):
                    reason = "저장소 범위를 전면 도입·일반 코드 리뷰 자동화 성공으로 확대했습니다."
            if reason:
                findings.append((CLAIM_SCOPE_UNVERIFIED, field.path, reason, field.card_index))
    return tuple(dict.fromkeys(findings))
