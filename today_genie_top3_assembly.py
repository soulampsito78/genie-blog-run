"""Deterministic assembly of today_genie key_watchpoints from structured TOP3 extraction slots."""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple


def _norm_one_line(s: Any) -> str:
    if not isinstance(s, str):
        return ""
    return re.sub(r"\s+", " ", s).strip()


_INVALID_NEWS_HEADLINE_PATTERNS = (
    "추가 주요 뉴스 없음",
    "주요 뉴스 없음",
    "확인되지 않았",
    "해당 없음",
    "없음",
    "n/a",
)


def is_valid_major_overseas_news_item(item: Any) -> bool:
    """Explicit validity gate for counting major overseas market news headlines."""
    if not isinstance(item, dict):
        return False
    headline = _norm_one_line(item.get("headline"))
    if len(headline) < 8:
        return False
    low = headline.lower()
    if any(bad in low for bad in _INVALID_NEWS_HEADLINE_PATTERNS):
        return False
    if not re.search(r"[A-Za-z가-힣0-9]", headline):
        return False
    return True


def collect_valid_major_overseas_news(
    runtime_input: Dict[str, Any], max_items: int = 3
) -> List[Tuple[int, Dict[str, Any]]]:
    """Return (raw_index, news_item) for valid overseas market news, preserving input order."""
    raw = runtime_input.get("top_market_news")
    if not isinstance(raw, list):
        return []
    picked: List[Tuple[int, Dict[str, Any]]] = []
    for idx, item in enumerate(raw):
        if len(picked) >= max_items:
            break
        if is_valid_major_overseas_news_item(item):
            picked.append((idx, item))
    return picked


def _indices_summary_snippet(overnight: Dict[str, Any]) -> str:
    idx = overnight.get("indices")
    if not isinstance(idx, dict) or not idx:
        return ""
    parts: List[str] = []
    for key, slot in list(idx.items())[:4]:
        if not isinstance(slot, dict):
            continue
        close = slot.get("close")
        pct = slot.get("change_pct")
        if close is None:
            continue
        tail = ""
        if isinstance(pct, (int, float)):
            sign = "+" if pct > 0 else ""
            tail = f" ({sign}{pct}%)"
        parts.append(f"{key} {close}{tail}")
    return ", ".join(parts)


def _feed_watch_slot_fields(runtime_input: Dict[str, Any], variant: int) -> tuple[str, str, str, str]:
    """
    Build a real market-watch TOP3 slot from overnight/macro/risk feeds only.
    No fake 'no third headline' prose — always factual strings from runtime_input.
    """
    ov = runtime_input.get("overnight_us_market") if isinstance(runtime_input.get("overnight_us_market"), dict) else {}
    macro = runtime_input.get("macro_indicators") if isinstance(runtime_input.get("macro_indicators"), dict) else {}
    risks = runtime_input.get("risk_factors") if isinstance(runtime_input.get("risk_factors"), list) else []
    tmi = runtime_input.get("top_macro_issues")
    macro_blob = ""
    if isinstance(tmi, list):
        macro_blob = _norm_one_line(json.dumps(tmi, ensure_ascii=False)[:400])
    elif isinstance(tmi, str):
        macro_blob = _norm_one_line(tmi)

    summ = _norm_one_line(ov.get("summary"))
    macro_h = _norm_one_line(macro.get("headline"))
    rates = _norm_one_line(macro.get("rates_watch"))
    dxy = _norm_one_line(macro.get("dxy_note"))
    idx_line = _indices_summary_snippet(ov)

    risk_title = ""
    risk_detail = ""
    if risks:
        pick = risks[variant % len(risks)]
        if isinstance(pick, dict):
            risk_title = _norm_one_line(pick.get("risk"))
            risk_detail = _norm_one_line(pick.get("detail"))

    v = variant % 3
    if v == 0:
        hk = "야간 미국장·지수 흐름 점검"
        wh = summ or idx_line or macro_h
        if not wh:
            wh = "입력된 야간 미국 시장 스냅샷이 장전 대응의 기준선으로 남아 있다."
        wy = macro_h or rates or "오늘 장전에는 같은 매크로 축이 국내 시장 평가에 반영된다."
        wk = "국내에서는 코스피·코스닥, 원/달러, 외국인·기관 수급을 함께 확인한다."
    elif v == 1:
        hk = "금리·환율 톤 재확인"
        wh = " ".join(x for x in (macro_h, rates) if x).strip() or summ or idx_line
        if not wh:
            wh = "입력된 매크로 메모가 금리·환율 민감도를 정리해 둔 상태다."
        wy = dxy or macro_h or "오늘 장전에는 달러·위험선호 톤이 국내 변동성에 미칠 각도를 본다."
        wk = "국내에서는 금리 스프레드와 원화 변동, 외국인 선물·현물 흐름을 함께 본다."
    else:
        hk = (risk_title[:28] + "…") if len(risk_title) > 28 else (risk_title or "리스크 캘린더 점검")
        wh = risk_detail or summ or macro_h
        if not wh:
            wh = "입력된 리스크 요인 설명이 장전 체크리스트의 한 축으로 남아 있다."
        wy = macro_blob[:200] if macro_blob else (rates or dxy or "오늘 장전에는 동일 축이 국내 섹터별로 재평가된다.")
        wk = "국내에서는 관련 섹터·대형주 호가와 거래대금, 환율 변동을 함께 확인한다."

    if len(hk) < 4:
        hk = "장전 매크로 관전"
    return hk, wh, wy, wk


def normalize_top3_slots_payload(ext_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize model extraction payload to exactly 3 slot dicts (may be sparse)."""
    raw = ext_data.get("slots")
    if not isinstance(raw, list):
        return [{}, {}, {}]
    out: List[Dict[str, Any]] = []
    for i in range(3):
        if i < len(raw) and isinstance(raw[i], dict):
            slot = dict(raw[i])
        else:
            slot = {}
        slot["slot"] = i + 1
        out.append(slot)
    return out


def _finish_sentence(s: str) -> str:
    if not s:
        return ""
    if s[-1] in ".!?…":
        return s
    if s.endswith(("다", "요", "음", "임", "함", "씀", "죠")):
        return s + "."
    return s + "."


def _fallback_slot_fields(slot: Dict[str, Any], news_headline: str, idx: int) -> tuple[str, str, str, str]:
    hk = _norm_one_line(slot.get("headline_ko"))
    wh = _norm_one_line(slot.get("what_happened"))
    wy = _norm_one_line(slot.get("why_it_matters_today"))
    wk = _norm_one_line(slot.get("what_to_watch_in_korea"))
    nh = (news_headline or "").strip()

    if not wh and nh:
        wh = f"야간·장전 맥락에서 {nh[:200]} 흐름이 대응 축으로 남아 있다."
    if not wy:
        wy_opts = (
            "오늘 장전에는 앞선 야간 데이터가 체크리스트 상단에 남습니다.",
            "금일 개장 전에는 같은 변수가 대형주와 테마주에 다르게 반응할 수 있습니다.",
            "장 개시 직전까지는 헤드라인 축이 우선순위를 정합니다.",
        )
        wy = wy_opts[(max(idx, 1) - 1) % 3]
    if not wk:
        wk_opts = (
            "코스피 선물 베이시스와 대형주 호가를 먼저 본다.",
            "코스닥 변동성·테마주 분산을 다음 관전 축으로 본다.",
            "단기금리·원화 스왑과 기관 선물 순매수를 짝지어 본다.",
        )
        wk = wk_opts[(max(idx, 1) - 1) % 3]
    if len(hk) < 4:
        if wh:
            base = wh[:36].strip()
            hk = base + ("…" if len(wh) > 36 else "")
        else:
            hk = f"TOP{idx} 이슈"
    return hk, wh, wy, wk


_MEANING_MARKERS = ("영향", "의미", "시사", "관건", "때문", "경로", "전제")


def _polite_top3_tone(text: str) -> str:
    """Convert unintended blunt endings into polite customer-facing tone."""
    if not text:
        return ""
    patched = text
    replacements = (
        ("점검하면 된다", "점검해야 합니다"),
        ("확인하면 된다", "확인할 필요가 있습니다"),
        ("보면 된다", "확인할 필요가 있습니다"),
        ("조정한다", "조정할 필요가 있습니다"),
        ("유지한다", "유지하는 편이 좋습니다"),
    )
    for src, dst in replacements:
        patched = patched.replace(src, dst)
    return patched


_SLOT_CLOSERS = (
    "이 축에서는 코스피 선물 베이시스와 대형주 호가를 먼저 확인하는 편이 좋습니다.",
    "같은 이슈라도 코스닥은 테마·체결강도를 통해 따로 읽는 편이 좋습니다.",
    "단기물 금리·원화 스왑 톤이 이슈와 엇갈리면 그때 해석 프레임을 좁혀 보는 편이 좋습니다.",
)
_MEANING_TAIL = (
    " 체크 순서는 위에서 말한 이슈 축이 움직이는 순서와 맞추면 됩니다.",
    " 분기점은 프로그램·외국인 순매수가 같은 방향으로 갈 때입니다.",
    " 장전에는 거래대금과 첫 30분 변동성만으로도 우선순위를 재정렬할 수 있습니다.",
)
_DENSITY_PAD = (
    " 이슈별로 한 번만 우선순위를 정해 두면 장전 대응이 단순해집니다.",
    " 헤드라인 축이 바뀌지 않는 한 같은 해석 틀을 유지해도 됩니다.",
    " 동일 데이터가 연속으로 나오면 중복 설명은 줄이는 편이 좋습니다.",
)


def _compose_top3_detail(wh: str, wy: str, wk: str, slot_index: int) -> str:
    """Paragraph shape: fact → today → Korea watch → slot-specific closer (no shared boilerplate)."""
    parts: List[str] = []
    a = _finish_sentence(wh)
    if a:
        parts.append(a)
    b = _finish_sentence(wy)
    if b:
        if not any(x in b for x in ("오늘", "장전", "금일", "당일", "아침")):
            b = f"오늘 장전에서는 {b.lstrip()}"
        parts.append(b)
    c = wk.strip()
    if c:
        if not c.startswith("국내"):
            c = f"국내에서는 {c}"
        parts.append(_finish_sentence(c))
    parts.append(_SLOT_CLOSERS[slot_index % 3])
    base = " ".join(parts)
    if not any(m in base for m in _MEANING_MARKERS):
        base += _MEANING_TAIL[slot_index % 3]
    if len(base) < 96:
        base += _DENSITY_PAD[slot_index % 3]
    return _polite_top3_tone(base)


_FORBIDDEN_CROSS_SURFACE = (
    "장 초반에는 앞서 적은 국내 확인 포인트",
    "같은 축에서 환율·수급이 어긋나면",
    "시나리오를 즉시 조정할 필요가 있습니다",
    "시나리오를 바로 조정할 필요가 있습니다",
)


def _strip_forbidden_phrases(text: str) -> str:
    t = text
    for frag in _FORBIDDEN_CROSS_SURFACE:
        t = t.replace(frag, "")
    return re.sub(r"\s+", " ", t).strip()


def _split_sents(text: str) -> List[str]:
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]


def apply_briefing_repetition_guard(data: Dict[str, Any]) -> None:
    """
    Narrow guard: remove TOP3-style boilerplate from opening surfaces and
    drop duplicate sentences shared between summary and market_setup.
    """
    summary = data.get("summary")
    ms = data.get("market_setup")
    if isinstance(summary, str):
        data["summary"] = _strip_forbidden_phrases(summary)
    if isinstance(ms, str):
        data["market_setup"] = _strip_forbidden_phrases(ms)
    if not isinstance(data.get("summary"), str) or not isinstance(data.get("market_setup"), str):
        return
    ss = _split_sents(data["summary"])
    msents = _split_sents(data["market_setup"])
    if not ss or not msents:
        return
    summary_set = {s for s in ss if len(s) >= 28}
    filtered: List[str] = []
    for s in msents:
        if len(s) >= 28 and s in summary_set:
            continue
        filtered.append(s)
    if filtered and len(filtered) < len(msents):
        data["market_setup"] = " ".join(filtered).strip()

    # Last-sentence echo: summary lead vs indices briefing often ends on the same
    # "외국인·원/달러 확인" line — drop the redundant market_setup closer only.
    sum2 = data.get("summary")
    ms2 = data.get("market_setup")
    if isinstance(sum2, str) and isinstance(ms2, str):
        ss2 = _split_sents(sum2)
        ms2s = _split_sents(ms2)
        if len(ss2) >= 1 and len(ms2s) >= 2:
            ls, lm = ss2[-1], ms2s[-1]
            if len(ls) >= 25 and len(lm) >= 25 and SequenceMatcher(None, ls, lm).ratio() >= 0.45:
                trimmed_ms = " ".join(ms2s[:-1]).strip()
                if len(trimmed_ms) >= 220:
                    data["market_setup"] = trimmed_ms


def watchpoint_covers_feed_blobs(wp: Dict[str, Any], runtime_input: Dict[str, Any]) -> bool:
    """True if headline+detail visibly reuse tokens from overnight/macro/risk JSON (for synthetic TOP3 slots)."""
    chunks: List[str] = []
    for key in ("overnight_us_market", "macro_indicators", "risk_factors", "top_macro_issues"):
        val = runtime_input.get(key)
        if isinstance(val, (dict, list)):
            chunks.append(json.dumps(val, ensure_ascii=False))
        elif isinstance(val, str) and val.strip():
            chunks.append(val)
    blob = _norm_one_line(" ".join(chunks)).lower()
    if len(blob) < 12:
        return False
    text = (_norm_one_line(wp.get("headline", "")) + " " + _norm_one_line(wp.get("detail", ""))).lower()
    if len(text) < 16:
        return False
    toks = [t for t in re.split(r"[^\w가-힣]+", blob) if len(t) >= 3][:120]
    hits = sum(1 for t in toks if t and t in text)
    anchors = (
        "cpi",
        "inflation",
        "nasdaq",
        "spx",
        "s&p",
        "dow",
        "fed",
        "yield",
        "dollar",
        "geopolit",
        "ceasefire",
        "iran",
        "oil",
        "kosdaq",
        "kospi",
        "금리",
        "물가",
        "환율",
        "지수",
        "외국인",
        "인플레",
        "지정학",
        "유가",
        "채권",
        "달러",
        "니케이",
    )
    anchor_hits = sum(1 for a in anchors if a in text and a in blob)
    digit_overlap = len(set(re.findall(r"\d+\.?\d*", text)) & set(re.findall(r"\d+\.?\d*", blob)))
    return hits >= 1 or anchor_hits >= 1 or digit_overlap >= 1


def assemble_key_watchpoints_from_slots(
    slots: List[Dict[str, Any]],
    runtime_input: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Always emit exactly 3 watchpoints (fixed TOP3 product rule).
    Positions map to valid headlines in order; any remaining positions are
    feed-anchored market-watch slots (no absence filler).
    """
    valid = collect_valid_major_overseas_news(runtime_input, max_items=3)
    result: List[Dict[str, Any]] = []
    for position in range(3):
        if position < len(valid):
            raw_idx, item = valid[position]
            nh = str(item.get("headline") or "").strip()
            slot = slots[raw_idx] if raw_idx < len(slots) else {}
            hk, wh, wy, wk = _fallback_slot_fields(slot, nh, position + 1)
        else:
            fh, fw, fy, fk = _feed_watch_slot_fields(runtime_input, variant=position)
            slot = slots[position] if position < len(slots) else {}
            hk_m = _norm_one_line(slot.get("headline_ko"))
            wh_m = _norm_one_line(slot.get("what_happened"))
            wy_m = _norm_one_line(slot.get("why_it_matters_today"))
            wk_m = _norm_one_line(slot.get("what_to_watch_in_korea"))
            hk = hk_m if len(hk_m) >= 4 else fh
            wh = wh_m if len(wh_m) >= 28 else fw
            wy = wy_m if len(wy_m) >= 24 else fy
            wk = wk_m if len(wk_m) >= 20 else fk
        if len(hk) > 72:
            hk = hk[:69] + "…"
        detail = _compose_top3_detail(wh, wy, wk, position)
        result.append({"headline": hk, "detail": detail, "basis": "fact"})
    return result
