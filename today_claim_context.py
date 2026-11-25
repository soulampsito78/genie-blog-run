"""Inspect known Today claim-scope risks; never rewrite or certify facts.

Independent source annotations belong in runtime input, bound to selected IDs.
RSS publication time is never substituted for the underlying event time.
"""
from datetime import datetime
import json
import re
from typing import Mapping

SESSION_CAUSALITY = "customer_surface_session_causality_unverified"
PERSON_SCOPE = "customer_surface_person_scope_unverified"
DOMESTIC_APPLICATION = "customer_surface_domestic_application_missing"
CONSENSUS_SCOPE = "customer_surface_consensus_scope_unverified"


def _time(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def bound_annotations(source_input):
    if not isinstance(source_input, Mapping):
        return []
    selected = {x.get("news_id") for x in (source_input.get("top_market_news") or [])
                if isinstance(x, Mapping) and x.get("news_id")}
    result = []
    for row in (source_input.get("primary_claim_context") or []):
        if not isinstance(row, Mapping) or row.get("news_id") not in selected:
            continue
        if (not str(row.get("source_url", "")).startswith("https://")
                or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("source_sha256", "")))
                or _time(row.get("observed_at")) is None
                or not isinstance(row.get("facts"), Mapping)):
            continue
        # This validates binding/shape, not the source annotation's truth.
        result.append(row)
    return result


def prompt_rule(source_input):
    return """[TODAY_CLAIM_CONTEXT — source and session boundaries]
Use only ID-bound, dated primary_claim_context annotations actually supplied.
An RSS publication timestamp is not an economic release timestamp. A release
after a market closes cannot explain that already completed market session.
Separate Asia closes from later US releases and the subsequent US session.
A personal-investigation statement is not company-wide legal clearance; retain
who said it, who was being discussed, and whether it is a reported assurance.
Preserve domestic applicability, proposal/final status, and net tariff scope.
Do not invent a consensus beat from an inflation level or a year-on-year rise.
Missing annotations are missing evidence, never permission to invent facts.
Headline and core PCE are different metrics. Compare each with its own forecast,
period and year-on-year/month-on-month basis. A headline reading matching its
forecast cannot borrow a core reading beating a different forecast. Preserve conditional tariff
alternatives separately from a base proposal; do not turn either into enacted law.
""" + json.dumps(bound_annotations(source_input), ensure_ascii=False)


def _sentences(text):
    return re.split(r"(?<!\d)[.!?;。](?!\d)|\n", text)


def _broad_clearance(text):
    return any(re.search(r"법적\s*(?:리스크|위험)\s*해소|엔비디아\s*관련\s*불확실성(?:을)?\s*해소|공식\s*종결", part)
               and not re.search(r"단정하지|의미하지|아니다|해소\s*시도|여부", part)
               for part in _sentences(text))


def _metadata_only_findings(fields, payload, source_input, rows):
    """Known risky assertions require source review even without enrichment.

This does not infer facts from an RSS timestamp or invent Korea applicability.
It diagnoses absent evidence instead of silently skipping unannotated inputs.
"""
    if not isinstance(source_input, Mapping):
        return []
    from today_genie_top3_assembly import canonical_news_id
    sources = [s for s in (source_input.get("top_market_news") or []) if isinstance(s, dict)]
    cards = payload.get("key_watchpoints") or []
    result = []
    for field in fields:
        bound = sources
        if field.card_index > 0:
            if field.card_index > len(cards) or not isinstance(cards[field.card_index - 1], Mapping):
                continue
            identity = cards[field.card_index - 1].get("news_id")
            bound = [s for s in sources if identity and canonical_news_id(s) == identity]
        for source in bound:
            identity = canonical_news_id(source)
            original = " ".join(str(source.get(k) or "") for k in ("headline", "title", "summary", "snippet"))
            kinds = {r["facts"].get("kind") for r in rows if r["news_id"] == identity}
            text = field.text
            pce_source = re.search(r"PCE|personal\s+consumption|preferred\s+inflation", original, re.I)
            if pce_source and "economic_release" not in kinds:
                if re.search(r"PCE|개인소비지출|선호\s*인플레이션", text, re.I):
                    if (re.search(r"코스피|코스닥|니케이|아시아", text)
                            and re.search(r"작용한\s*결과|때문에|영향으로|발표로.{0,30}하락", text)
                            and not re.search(r"PCE.{0,12}(?:이전|앞서)|아시아.{0,35}먼저", text, re.I)):
                        result.append((SESSION_CAUSALITY, field.path, "시장 마감과 실제 발표 시각을 결속할 근거가 없습니다. RSS 게시 시각을 발표 시각으로 대체하지 않습니다.", field.card_index))
                    if re.search(r"예상.{0,8}(?:웃도|상회|부합|높)|consensus", text, re.I) and not re.search(r"consensus|forecast|expected|estimate|예상", original, re.I):
                        result.append((CONSENSUS_SCOPE, field.path, "지표별 실제치와 예상치 근거가 입력에 없어 원문 확인이 필요합니다.", field.card_index))
            if ("personal_investigation" not in kinds and re.search(r"investigat", original, re.I)
                    and re.search(r"assur|says|told", original, re.I) and _broad_clearance(text)):
                result.append((PERSON_SCOPE, field.path, "조사 관련 전언을 전반적 법적 위험 해소로 확장할 근거가 없습니다.", field.card_index))
            if (field.card_index > 0 and "tariff_proposal" not in kinds
                    and re.search(r"tariff|관세", original, re.I) and re.search(r"partner|econom|교역|경제권", original, re.I)):
                result.append((DOMESTIC_APPLICATION, field.path, "광범위한 관세 제안의 한국 직접 적용과 조건·대안은 제목만으로 확인할 수 없어 원문 검수가 필요합니다.", field.card_index))
    return result


def inspect_today_claim_context(fields, *, mode, payload, source_input):
    if mode != "today_genie":
        return ()
    rows = bound_annotations(source_input)
    cards = payload.get("key_watchpoints") or []
    findings = _metadata_only_findings(fields, payload, source_input, rows)
    for field in fields:
        for row in rows:
            if field.card_index > 0:
                if (field.card_index > len(cards)
                        or cards[field.card_index - 1].get("news_id") != row["news_id"]):
                    continue
            facts = row["facts"]
            text = field.text
            kind = facts.get("kind")
            reason = code = None
            if kind == "economic_release" and re.search(
                    r"PCE|개인소비지출|연준(?:의)?\s*선호\s*인플레이션", text, re.I):
                release = _time(facts.get("released_at"))
                for session in (facts.get("market_sessions") or []):
                    if not isinstance(session, Mapping):
                        continue
                    close = _time(session.get("closed_at"))
                    names = [n for n in session.get("names", []) if isinstance(n, str) and n]
                    if not release or not close or release <= close or not any(n in text for n in names):
                        continue
                    causal = re.search(r"작용한\s*결과|때문에|영향으로|원인으로|발표로.{0,30}하락", text)
                    separated = re.search(r"PCE\s*발표\s*(?:이전|전)|아시아.{0,35}먼저.{0,20}마감", text, re.I)
                    direct = re.search(r"(?:코스피|코스닥|니케이|아시아).{0,55}PCE.{0,35}(?:때문에|영향으로|발표로).{0,20}(?:하락|급락)", text, re.I)
                    if causal and (direct or not separated):
                        code, reason = SESSION_CAUSALITY, "발표보다 먼저 종료된 시장의 하락 원인으로 연결했을 수 있습니다."
                metric = facts.get("indicator", "headline_pce")
                for clause in _sentences(text):
                    is_core = bool(re.search(r"근원|core", clause, re.I))
                    if (metric == "core_pce") != is_core:
                        continue
                    if facts.get("consensus_relation") == "inline" and re.search(r"예상(?:치)?(?:를)?\s*(?:웃도|웃돌|상회)|예상보다\s*높", clause):
                        if not re.search(r"예상(?:치)?.{0,12}(?:웃돈\s*것이\s*아니|상회하지|부합)", clause):
                            findings.append((CONSENSUS_SCOPE, field.path, "지표별 예상 부합과 전년 대비 상승을 구분해야 합니다.", field.card_index))
            elif kind == "personal_investigation" and re.search(r"엔비디아|NVIDIA|황|Huang", text, re.I):
                if _broad_clearance(text):
                    code, reason = PERSON_SCOPE, "개인에 관한 전언을 회사 전체의 위험 해소로 확대할 수 없습니다."
            elif kind == "tariff_proposal" and "Korea" in facts.get("economies", []) and re.search(r"관세|교역", text):
                # Require the direct application in the rendered news card,
                # not a hidden annotation or a caveat in an unrelated card.
                if field.card_index > 0:
                    card = cards[field.card_index - 1]
                    visible = " ".join(str(card.get(k) or "") for k in ("headline", "detail"))
                    maximum = str(facts.get("maximum_rate", 15))
                    required_rate = r"(?<![\d.])" + re.escape(maximum) + r"\s*%"
                    conditional = facts.get("conditional_rate")
                    conditional_ok = conditional is None or (re.search(r"(?<![\d.])" + re.escape(str(conditional)) + r"\s*%", visible)
                                                              and re.search(r"경우|조건|판단|불충분", visible))
                    if not ("한국" in visible and re.search(required_rate, visible) and conditional_ok
                            and re.search(r"제안|검토|미확정", visible)
                            and re.search(r"기존.{0,25}관세|MFN|301조", visible)
                            and re.search(r"예외|제외", visible)):
                        code, reason = DOMESTIC_APPLICATION, "한국 적용·최대율·기존 관세 고려·예외·제안 단계가 같은 카드에 필요합니다."
            if code:
                findings.append((code, field.path, reason, field.card_index))
    return tuple(dict.fromkeys(findings))
