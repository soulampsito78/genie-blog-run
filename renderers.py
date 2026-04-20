from __future__ import annotations

import json
import re
from html import escape as html_escape
from typing import Any, Dict, List, Optional

# Email: one-line finance discipline (server-owned, not model output)
TODAY_EMAIL_CLOSING_CRITERION = (
    "오늘의 판단 기준: 입력·공시 범위 밖의 수치·종목·뉴스는 본문에 넣지 않았습니다. "
    "불확실할수록 설명을 짧게 유지하는 편이 안전합니다."
)

# today_genie: deterministic legal disclaimer (server-owned; not model-generated)
TODAY_GENIE_LEGAL_DISCLAIMER = (
    "본 브리핑은 정보 제공 목적이며, 최종 판단과 책임은 투자자 본인에게 있습니다."
)

TODAY_GENIE_HASHTAG_COUNT = 7
TODAY_GENIE_BRAND_TAG = "#오늘의지니"
TODAY_GENIE_UTILITY_FALLBACK = "#오늘증시체크"

# Empty search-value / generic-only tags (normalized, no #)
GENERIC_HASHTAG_BAN_BODY = frozenset(
    {
        "브리핑",
        "뉴스",
        "정보",
        "투자",
        "주식",
        "증시",
        "오늘",
        "데일리",
        "시장",
        "경제",
        "금융",
        "아침",
        "글로벌",
        "데일리브리핑",
        "모닝",
        "속보",
    }
)


def _tag_body(tag: str) -> str:
    t = str(tag).strip()
    if t.startswith("#"):
        t = t[1:]
    return t.replace(" ", "").replace("\u3000", "").strip()


def _with_hash(body: str) -> str:
    b = _tag_body(body)
    return f"#{b}" if b else "#"


def _norm_hashtag_key(tag: str) -> str:
    return _tag_body(tag).lower()


def _hangul_count(s: str) -> int:
    return sum(1 for c in s if "\uac00" <= c <= "\ud7a3")


def _is_allowed_ascii_macro(body: str) -> bool:
    u = body.upper()
    return len(body) <= 8 and body.isascii() and u == body


def _is_korean_first_tag(tag: str) -> bool:
    body = _tag_body(tag)
    if not body:
        return False
    if _is_allowed_ascii_macro(body):
        return True
    letters = sum(1 for c in body if c.isalnum() or ("\uac00" <= c <= "\ud7a3"))
    if letters == 0:
        return False
    return _hangul_count(body) >= max(1, letters // 2)


def _is_generic_hashtag(tag: str) -> bool:
    return _norm_hashtag_key(tag) in GENERIC_HASHTAG_BAN_BODY


def _headline_to_hashtag(headline: str, max_body: int = 10) -> str:
    if not headline or not isinstance(headline, str):
        return ""
    parts = re.findall(r"[\w가-힣·/%]+", headline)
    if not parts:
        return ""
    raw = parts[0]
    if _hangul_count(raw) < 2 and len(parts) > 1:
        raw = parts[0] + parts[1]
    raw = re.sub(r"[^\w가-힣/%]", "", raw)[:max_body]
    if len(raw) < 2:
        return ""
    return _with_hash(raw)


def _market_slot_tags(runtime_input: Dict[str, Any], data: Dict[str, Any]) -> tuple[str, str]:
    first = "#장전브리핑"
    title_l = str(data.get("title") or "").lower()
    summary_l = str(data.get("summary") or "").lower()
    blob = title_l + " " + summary_l
    overnight = runtime_input.get("overnight_us_market")
    second = "#미국증시"
    if isinstance(overnight, dict):
        txt = json.dumps(overnight, ensure_ascii=False).lower()
        if any(k in txt for k in ("kosdaq", "kospi", "코스피", "코스닥", "krx")) or any(
            k in blob for k in ("코스피", "코스닥", "원달러", "환율")
        ):
            second = "#국내증시"
    elif any(k in blob for k in ("코스피", "코스닥", "원달러")):
        second = "#국내증시"
    return first, second


def _risk_slot_tag(data: Dict[str, Any]) -> str:
    for r in data.get("risk_check") or []:
        if isinstance(r, dict):
            hx = _headline_to_hashtag(str(r.get("risk") or ""))
            if hx:
                return hx
    macro = json.dumps(data.get("market_snapshot") or [], ensure_ascii=False)
    if re.search(r"cpi|pce|금리|채권|유가|달러", macro, re.I):
        return "#매크로리스크"
    return "#지정학리스크"


def _dedupe_hashtag_list(tags: List[str]) -> List[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        k = _norm_hashtag_key(t)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(_with_hash(_tag_body(t)))
    return out


def finalize_today_genie_hashtag_list(
    data: Dict[str, Any],
    runtime_input: Dict[str, Any],
) -> List[str]:
    """Deterministic exactly-7 hashtags: brand + 2 market + 2 topic + risk + utility."""
    m1, m2 = _market_slot_tags(runtime_input, data)
    wps = [w for w in (data.get("key_watchpoints") or []) if isinstance(w, dict)]
    t1 = (
        _headline_to_hashtag(str(wps[0].get("headline") or ""))
        if len(wps) > 0
        else _headline_to_hashtag(str(data.get("title") or "")[:48])
    ) or "#이슈브리핑"
    t2 = (
        _headline_to_hashtag(str(wps[1].get("headline") or ""))
        if len(wps) > 1
        else _headline_to_hashtag(str(data.get("summary") or "")[:56])
    ) or "#시장체크"
    r1 = _risk_slot_tag(data)
    u1 = TODAY_GENIE_UTILITY_FALLBACK
    base = [TODAY_GENIE_BRAND_TAG, m1, m2, t1, t2, r1, u1]

    pool: list[str] = []
    raw = data.get("hashtags")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, str):
                continue
            tag = _with_hash(item)
            if len(_tag_body(tag)) < 2:
                continue
            if _is_generic_hashtag(tag):
                continue
            if not _is_korean_first_tag(tag):
                continue
            pool.append(tag)

    merged: List[str | None] = [None] * TODAY_GENIE_HASHTAG_COUNT
    merged[0] = TODAY_GENIE_BRAND_TAG

    def take_from_pool(predicate) -> Optional[str]:
        for i, t in enumerate(pool):
            if t is None:
                continue
            b = _tag_body(t).lower()
            if predicate(b, t):
                pool[i] = ""  # type: ignore[assignment]
                return _with_hash(t)
        return None

    # Market / briefing slots (1–2)
    m1p = take_from_pool(
        lambda b, _: any(
            k in b for k in ("장전", "브리핑", "오프닝", "아침", "모닝", "증시체크")
        )
    )
    merged[1] = m1p or m1
    m2p = take_from_pool(
        lambda b, _: any(
            k in b
            for k in (
                "미국",
                "나스닥",
                "다우",
                "코스피",
                "코스닥",
                "증시",
                "국내",
                "글로벌",
                "환율",
                "금리",
                "유가",
                "cpi",
                "연준",
            )
        )
    )
    merged[2] = m2p or m2

    # Topic slots (3–4) — prefer model tags not yet used
    used: set[str] = {_norm_hashtag_key(x) for x in merged if x}
    for idx in (3, 4):
        pick: Optional[str] = None
        for i, t in enumerate(pool):
            if not t or not isinstance(t, str):
                continue
            nk = _norm_hashtag_key(t)
            if nk in used:
                continue
            if _is_generic_hashtag(t):
                continue
            pick = _with_hash(t)
            pool[i] = ""
            break
        merged[idx] = pick or (t1 if idx == 3 else t2)
        used.add(_norm_hashtag_key(merged[idx] or ""))

    # Risk (5)
    rp = take_from_pool(
        lambda b, _: any(
            k in b for k in ("리스크", "변동성", "지정학", "매크로", "금리", "유가", "cpi", "이벤트")
        )
    )
    merged[5] = rp or r1

    # Utility (6)
    up = take_from_pool(lambda b, _: "체크" in b or "한눈" in b or "스탑" in b)
    merged[6] = up or u1

    out = [_with_hash(_tag_body(x or "")) for x in merged]
    out[0] = TODAY_GENIE_BRAND_TAG

    out = _dedupe_hashtag_list(out)
    # If dedupe shortened, refill from base defaults
    fallback_chain = [
        TODAY_GENIE_BRAND_TAG,
        m1,
        m2,
        t1,
        t2,
        r1,
        u1,
    ]
    i_fb = 0
    while len(out) < TODAY_GENIE_HASHTAG_COUNT:
        cand = fallback_chain[i_fb % len(fallback_chain)]
        i_fb += 1
        if _norm_hashtag_key(cand) not in {_norm_hashtag_key(x) for x in out}:
            out.append(cand)
    out = out[:TODAY_GENIE_HASHTAG_COUNT]

    # Near-duplicate collapse: replace shorter if one contains another (same first 4 chars)
    fixed: list[str] = []
    keys: set[str] = set()
    for t in out:
        k = _norm_hashtag_key(t)
        dup = False
        for ex in fixed:
            ek = _norm_hashtag_key(ex)
            if k == ek or (len(k) >= 4 and len(ek) >= 4 and (k.startswith(ek[:4]) or ek.startswith(k[:4]))):
                dup = True
                break
        if not dup:
            fixed.append(_with_hash(t))
            keys.add(k)
    while len(fixed) < TODAY_GENIE_HASHTAG_COUNT:
        for c in fallback_chain:
            if len(fixed) >= TODAY_GENIE_HASHTAG_COUNT:
                break
            if _norm_hashtag_key(c) not in keys:
                fixed.append(c)
                keys.add(_norm_hashtag_key(c))
    return fixed[:TODAY_GENIE_HASHTAG_COUNT]


def today_genie_hashtag_key(tag: str) -> str:
    """Normalized comparison key for validation (body, lowercased, no #)."""
    return _norm_hashtag_key(tag)


def today_genie_hashtag_passes_locale_rule(tag: str) -> bool:
    """True if tag meets Korean-first / allowed-symbol rules for today_genie."""
    return _is_korean_first_tag(tag)


def today_genie_is_generic_hashtag(tag: str) -> bool:
    return _is_generic_hashtag(tag)


def _today_genie_basis_label_ko(basis: Any) -> str:
    """Map JSON basis tokens to Korean for customer-facing render (no raw fact/interpretation)."""
    b = str(basis or "").strip().lower()
    if b == "fact":
        return "사실"
    if b == "interpretation":
        return "해석"
    if b == "speculation":
        return "추정"
    return str(basis or "").strip() or "근거"


def _safe(text: Any) -> str:
    if text is None:
        return ""
    return html_escape(str(text))


def render_web_html(mode: str, data: Dict[str, Any]) -> str:
    title = _safe(data.get("title", ""))
    summary = _safe(data.get("summary", ""))
    greeting = _safe(data.get("greeting", ""))
    closing = _safe(data.get("closing_message", ""))

    if mode == "today_genie":
        market_setup = _safe(data.get("market_setup", ""))
        market_snapshot_items = "".join(
            f"<li><strong>{_safe(item.get('label'))}</strong>: {_safe(item.get('value'))} "
            f"({_safe(_today_genie_basis_label_ko(item.get('basis')))})</li>"
            for item in data.get("market_snapshot", [])
            if isinstance(item, dict)
        )
        watch_items = "".join(
            f"<li><strong>{_safe(item.get('headline'))}</strong><br>{_safe(item.get('detail'))}</li>"
            for item in data.get("key_watchpoints", [])
            if isinstance(item, dict)
        )
        opportunities = "".join(
            f"<li><strong>{_safe(item.get('theme'))}</strong><br>{_safe(item.get('reason'))} "
            f"({_safe(_today_genie_basis_label_ko(item.get('basis')))})</li>"
            for item in data.get("opportunities", [])
            if isinstance(item, dict)
        )
        risks = "".join(
            f"<li><strong>{_safe(item.get('risk'))}</strong><br>{_safe(item.get('detail'))}</li>"
            for item in data.get("risk_check", [])
            if isinstance(item, dict)
        )
        numbers_block = ""
        if market_setup:
            numbers_block += f"<h3>맥락·셋업</h3><p>{market_setup}</p>"
        if market_snapshot_items:
            numbers_block += f"<h3>지표·시세 스냅샷</h3><ul>{market_snapshot_items}</ul>"
        if opportunities:
            numbers_block += f"<h3>오늘의 시장 관점</h3><ul>{opportunities}</ul>"
        if not numbers_block:
            numbers_block = "<p>(작성된 숫자·맥락 블록이 없습니다.)</p>"
        hashtags_section = _hashtags_block_html("today_genie", data.get("hashtags", []))

        return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
</head>
<body>
  <main>
    <h1>{title}</h1>
    <section>
      <h2>오늘의 핵심 요약</h2>
      <p>{greeting}</p>
      <p>{summary}</p>
    </section>

    <section>
      <h2>오늘의 TOP 3 뉴스 브리핑</h2>
      <ul>{watch_items}</ul>
    </section>

    <section>
      <h2>오늘 보는 숫자</h2>
      {numbers_block}
    </section>

    <section>
      <h2>오늘의 리스크</h2>
      <ul>{risks}</ul>
    </section>

    <section>
      <h2>오늘의 한 줄 기준</h2>
      <p>{closing}</p>
    </section>
    {hashtags_section}
    <footer>
      <p style="font-size:13px;line-height:1.65;color:#555;margin-top:12px;">{_safe(TODAY_GENIE_LEGAL_DISCLAIMER)}</p>
    </footer>
  </main>
</body>
</html>"""

    weather_summary_block = _safe(data.get("weather_summary_block", ""))
    weather_briefing = _safe(data.get("weather_briefing", ""))
    outfit = _safe(data.get("outfit_recommendation", ""))
    lifestyle_notes = "".join(f"<li>{_safe(item)}</li>" for item in data.get("lifestyle_notes", []))
    zodiac_items = "".join(
        f"<li><strong>{_safe(item.get('sign'))}</strong>: {_safe(item.get('fortune'))}</li>"
        for item in data.get("zodiac_fortunes", [])
        if isinstance(item, dict)
    )

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
</head>
<body>
  <main>
    <h1>{title}</h1>
    <p>{greeting}</p>
    <p>{summary}</p>

    <section>
      <h2>내일 날씨 한눈에</h2>
      <p>{weather_summary_block}</p>
    </section>

    <section>
      <h2>날씨 브리핑</h2>
      <p>{weather_briefing}</p>
    </section>

    <section>
      <h2>옷차림 추천</h2>
      <p>{outfit}</p>
    </section>

    <section>
      <h2>생활 팁</h2>
      <ul>{lifestyle_notes}</ul>
    </section>

    <section>
      <h2>별자리 운세</h2>
      <ul>{zodiac_items}</ul>
    </section>

    <footer>
      <p>{closing}</p>
    </footer>
  </main>
</body>
</html>"""


def _email_wrapper_inner(content: str, footer_html: str = "") -> str:
    """Conservative mobile-first email body wrapper (no external CSS)."""
    return (
        '<div style="margin:0;padding:0;background:#ffffff;">'
        '<div style="max-width:640px;width:100%;margin:0 auto;background:#ffffff;'
        'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Arial,sans-serif;'
        'font-size:15px;line-height:1.75;color:#1a1a1a;">'
        '<div style="padding:24px;">'
        f"{content}"
        "</div>"
        f"{footer_html}"
        "</div>"
        "</div>"
    )


def _email_img_block(absolute_url: str, alt: str) -> str:
    """Single email-safe image block; absolute URL required for clients."""
    return (
        '<div style="margin:0 0 20px 0;text-align:center;">'
        f'<img src="{_safe(absolute_url)}" alt="{_safe(alt)}" width="592" '
        'style="max-width:100%;height:auto;display:block;margin:0 auto;border:0;outline:none;" />'
        "</div>"
    )


def email_image_slots_html(mode: str, public_base_url: str) -> tuple[str, str]:
    """
    Email-purpose images under /static/email/ (served by API).
    today_genie: separate derived top/bottom assets; tomorrow_genie: same ref file, distinct alts.
    Returns (top_slot_html, bottom_slot_html); empty strings if no base URL.
    """
    base = (public_base_url or "").strip().rstrip("/")
    if not base:
        return "", ""

    if mode == "today_genie":
        top_path = "static/email/GENIE_EMAIL_today_genie_top_v1.jpg"
        bot_path = "static/email/GENIE_EMAIL_today_genie_bottom_v1.jpg"
        top_alt = "Genie — 스튜디오 인사 컷 (장전 브리핑)"
        bot_alt = "Genie — 야외 편안한 휴식 컷 (장전 브리핑, 동일 인물)"
        return (
            _email_img_block(f"{base}/{top_path}", top_alt),
            _email_img_block(f"{base}/{bot_path}", bot_alt),
        )

    path = "static/email/GENIE_REF_tomorrow_genie_master_v1.jpg"
    top_alt = "Genie — 스튜디오 인사 컷 (내일 준비)"
    bot_alt = "Genie — 야외 OOTD·편안한 휴식 컷 (내일 준비)"
    url = f"{base}/{path}"
    return _email_img_block(url, top_alt), _email_img_block(url, bot_alt)


_REVISION_REQUEST_REASONS = (
    "제목 수정 요청",
    "요약 수정 요청",
    "문장 표현 수정 요청",
    "이미지 품질 이슈",
    "구성 품질 이슈",
    "기타",
)


def render_email_operational_box(meta: Dict[str, Any]) -> str:
    """
    Read-only 운영 안내 + staged 재발행 요청 (internal_state revision_request).
    JS: (1) 재발행 요청 → show reason dropdown (2) reason chosen → show 재발행 요청 제출.
    POST URL is server-owned (main.py); not an immediate rerun.
    """
    mode_line = _safe(meta.get("mode_label", ""))
    status_line = _safe(meta.get("status_label", ""))
    exec_kst = _safe(meta.get("execution_time_kst", ""))
    summary_line = _safe(meta.get("result_summary", ""))
    send_line = _safe(meta.get("email_delivery_label", ""))
    mode_code = _safe(meta.get("mode_code", ""))
    post_raw = str(meta.get("revision_request_post_url", "") or "").strip()
    post_action = html_escape(post_raw, quote=True) if post_raw else "#"

    row = (
        '<p style="margin:0 0 8px 0;font-size:13px;line-height:1.6;color:#334155;">'
        '<span style="display:inline-block;min-width:8em;color:#475569;font-weight:700;">{label}</span>'
        "<span style=\"color:#1e293b;\">{value}</span></p>"
    )
    notice = (
        '<p style="margin:0 0 6px 0;font-size:12px;line-height:1.6;color:#64748b;">최대 2회까지 요청할 수 있습니다.</p>'
        '<p style="margin:0 0 6px 0;font-size:12px;line-height:1.6;color:#64748b;">요청 내용과 입력 데이터 상태를 검토한 뒤 재발행 여부가 결정됩니다.</p>'
        '<p style="margin:0;font-size:12px;line-height:1.6;color:#64748b;">반영이 어려운 경우에는 사유와 처리 과정을 함께 안내해 드립니다.</p>'
    )
    reason_opts = "".join(
        f'<option value="{_safe(l)}">{_safe(l)}</option>' for l in _REVISION_REQUEST_REASONS
    )
    return f"""
<section id="genie-operational-handoff" aria-label="운영 안내" style="margin-top:32px;padding:20px 20px 22px 20px;border:1px solid #cbd5e1;border-radius:10px;background:#f1f5f9;">
  <p style="margin:0 0 16px 0;padding-bottom:12px;border-bottom:1px solid #cbd5e1;font-size:13px;line-height:1.45;color:#334155;font-weight:800;letter-spacing:-0.01em;">운영 안내</p>
  <div style="margin:0 0 12px 0;padding:0;">
    {row.format(label="모드", value=mode_line)}
    {row.format(label="현재 상태", value=status_line)}
    {row.format(label="실행 시각", value=exec_kst)}
    {row.format(label="핵심 결과 요약", value=summary_line)}
    {row.format(label="이메일 발송 여부", value=send_line)}
  </div>
  <div id="genie-rr-notice" style="margin:0 0 18px 0;padding:12px 14px;border:1px solid #e2e8f0;border-radius:8px;background:#f8fafc;">
    {notice}
  </div>
  <button type="button" id="genie-rr-start-btn" style="display:inline-block;padding:12px 26px;background:#0f172a;color:#ffffff;font-size:14px;font-weight:800;line-height:1.35;border-radius:8px;border:1px solid #020617;box-shadow:0 1px 2px rgba(15,23,42,0.12);cursor:pointer;">재발행 요청</button>
  <div id="genie-rr-reason-stage" style="display:none;margin-top:14px;">
    <form id="genie-rr-form" method="post" action="{post_action}" enctype="application/x-www-form-urlencoded" target="_blank" style="margin:0;padding:0;">
      <input type="hidden" name="internal_state" value="revision_request" />
      <input type="hidden" name="mode" value="{mode_code}" />
      <input type="hidden" name="execution_time_kst" value="{exec_kst}" />
      <label for="genie-rr-reason" style="display:block;margin:0 0 6px 0;font-size:12px;font-weight:700;color:#475569;">사유 선택</label>
      <select id="genie-rr-reason" name="reason" required style="width:100%;max-width:100%;box-sizing:border-box;padding:10px 12px;font-size:14px;line-height:1.4;color:#1e293b;border:1px solid #cbd5e1;border-radius:6px;background:#ffffff;">
        <option value="">사유를 선택하세요</option>
        {reason_opts}
      </select>
      <div id="genie-rr-submit-stage" style="display:none;margin-top:14px;">
        <button type="submit" id="genie-rr-submit-btn" style="padding:12px 26px;background:#0f172a;color:#ffffff;font-size:14px;font-weight:800;line-height:1.35;border-radius:8px;border:1px solid #020617;cursor:pointer;">재발행 요청 제출</button>
      </div>
    </form>
  </div>
  <script type="text/javascript">
  (function () {{
    var root = document.getElementById("genie-operational-handoff");
    if (!root) return;
    var start = root.querySelector("#genie-rr-start-btn");
    var reasonStage = root.querySelector("#genie-rr-reason-stage");
    var sel = root.querySelector("#genie-rr-reason");
    var submitStage = root.querySelector("#genie-rr-submit-stage");
    if (!start || !reasonStage || !sel || !submitStage) return;
    start.addEventListener("click", function () {{
      reasonStage.style.display = "block";
    }});
    sel.addEventListener("change", function () {{
      submitStage.style.display = sel.value ? "block" : "none";
    }});
  }})();
  </script>
</section>
""".strip()


def _paragraphs_html(text: Any, compact: bool = False) -> str:
    raw = _safe(text)
    if not raw:
        return ""
    if "\n\n" in raw:
        parts = [p.strip() for p in raw.split("\n\n") if p.strip()]
    else:
        parts = [p.strip() for p in raw.split("\n") if p.strip()] or [raw.strip()]
    if compact and len(parts) > 3:
        parts = parts[:3]
    return "".join(
        f'<p style="margin:0 0 14px 0;font-size:15px;line-height:1.75;color:#1a1a1a;">{p}</p>'
        for p in parts
    )


def _summary_html(text: Any) -> str:
    raw = _safe(text)
    if not raw:
        return ""
    if "\n\n" in raw:
        parts = [p.strip() for p in raw.split("\n\n") if p.strip()]
    else:
        parts = [p.strip() for p in raw.split("\n") if p.strip()] or [raw.strip()]
    parts = parts[:3]
    return "".join(
        f'<p style="margin:0 0 14px 0;font-size:16px;line-height:1.7;font-weight:400;color:#1a1a1a;">{p}</p>'
        for p in parts
    )


def _build_email_hashtags(mode: str, hashtags: Any) -> list[str]:
    if mode == "today_genie":
        tags: list[str] = []
        if isinstance(hashtags, list):
            for item in hashtags:
                if isinstance(item, str) and item.strip():
                    tags.append(_with_hash(item))
        if len(tags) == TODAY_GENIE_HASHTAG_COUNT:
            return tags
        return finalize_today_genie_hashtag_list({"hashtags": hashtags if isinstance(hashtags, list) else []}, {})

    content_tags: list[str] = []
    if isinstance(hashtags, list):
        for item in hashtags:
            if not isinstance(item, str):
                continue
            t = item.strip()
            if not t:
                continue
            if not t.startswith("#"):
                t = f"#{t}"
            content_tags.append(t)
    fixed_bottom = ["#지니브리핑", "#내일의지니", "#GENIE"]
    content_tags = [t for t in content_tags if t not in fixed_bottom]
    content_tags = content_tags[:7]
    return content_tags + fixed_bottom


def _hashtags_block_html(mode: str, hashtags: Any) -> str:
    tags = _build_email_hashtags(mode, hashtags)
    if not tags:
        return ""
    lines = "".join(
        f'<p style="margin:0 0 4px 0;font-size:14px;line-height:1.8;color:#666;">{_safe(tag)}</p>'
        for tag in tags
    )
    return (
        '<section style="margin-top:0;margin-bottom:0;">'
        '<h2 style="margin:36px 0 14px 0;font-size:20px;line-height:1.4;font-weight:700;color:#1a1a1a;">해시태그</h2>'
        f"{lines}"
        "</section>"
    )


def _build_today_genie_email_editorial_html(data: Dict[str, Any]) -> str:
    """today_genie email body only (no image slots); Korean section headings; basis shown in Korean."""
    title = _safe(data.get("title", ""))
    summary_html = _summary_html(data.get("summary", ""))
    greeting_html = _paragraphs_html(data.get("greeting", ""))
    closing = _safe(data.get("closing_message", ""))
    header_label = (
        '<p style="margin:0 0 10px 0;font-size:12px;line-height:1.6;color:#666;"><strong>[장전 브리핑]</strong></p>'
    )
    h2 = 'style="margin:36px 0 14px 0;font-size:20px;line-height:1.4;font-weight:700;color:#1a1a1a;"'
    h3 = 'style="margin:28px 0 10px 0;font-size:17px;line-height:1.4;font-weight:700;color:#1a1a1a;"'
    watch_items = "".join(
        '<li style="margin:0 0 12px 0;">'
        f'<p style="margin:0 0 6px 0;font-size:16px;line-height:1.5;font-weight:700;color:#1a1a1a;">{_safe(item.get("headline"))}</p>'
        f'<p style="margin:0;font-size:15px;line-height:1.7;color:#1a1a1a;">{_safe(item.get("detail"))}</p>'
        "</li>"
        for item in data.get("key_watchpoints", [])
        if isinstance(item, dict)
    )
    risks = "".join(
        '<li style="margin:0 0 12px 0;">'
        f'<p style="margin:0 0 6px 0;font-size:16px;line-height:1.5;font-weight:700;color:#1a1a1a;">{_safe(item.get("risk"))}</p>'
        f'<p style="margin:0;font-size:15px;line-height:1.7;color:#1a1a1a;">{_safe(item.get("detail"))}</p>'
        "</li>"
        for item in data.get("risk_check", [])
        if isinstance(item, dict)
    )
    market_setup_html = _paragraphs_html(data.get("market_setup", ""))
    market_snapshot_items = "".join(
        '<li style="margin:0 0 12px 0;">'
        f'<p style="margin:0 0 6px 0;font-size:16px;line-height:1.5;font-weight:700;color:#1a1a1a;">{_safe(item.get("label"))}</p>'
        f'<p style="margin:0;font-size:15px;line-height:1.7;color:#1a1a1a;">{_safe(item.get("value"))} '
        f'<span style="font-size:12px;line-height:1.6;color:#666;">({_safe(_today_genie_basis_label_ko(item.get("basis")))})</span></p>'
        "</li>"
        for item in data.get("market_snapshot", [])
        if isinstance(item, dict)
    )
    opportunities = "".join(
        '<li style="margin:0 0 12px 0;">'
        f'<p style="margin:0 0 6px 0;font-size:16px;line-height:1.5;font-weight:700;color:#1a1a1a;">{_safe(item.get("theme"))}</p>'
        f'<p style="margin:0;font-size:15px;line-height:1.7;color:#1a1a1a;">{_safe(item.get("reason"))} '
        f'<span style="font-size:12px;line-height:1.6;color:#666;">({_safe(_today_genie_basis_label_ko(item.get("basis")))})</span></p>'
        "</li>"
        for item in data.get("opportunities", [])
        if isinstance(item, dict)
    )
    numbers_inner = ""
    if market_setup_html:
        numbers_inner += f'<h3 {h3}>맥락·셋업</h3>{market_setup_html}'
    if market_snapshot_items:
        numbers_inner += (
            f'<h3 {h3}>지표·시세 스냅샷</h3>'
            f'<ul style="margin:0 0 14px 18px;padding:0;">{market_snapshot_items}</ul>'
        )
    if opportunities:
        numbers_inner += (
            f'<h3 {h3}>오늘의 시장 관점</h3>'
            f'<ul style="margin:0 0 14px 18px;padding:0;">{opportunities}</ul>'
        )
    if not numbers_inner:
        numbers_inner = (
            '<p style="margin:0 0 14px 0;font-size:15px;line-height:1.75;color:#1a1a1a;">'
            "(작성된 숫자·맥락 블록이 없습니다.)</p>"
        )
    hashtags_html = _hashtags_block_html("today_genie", data.get("hashtags", []))
    return f"""
{header_label}
<h1 style="margin:0 0 16px 0;font-size:28px;line-height:1.35;font-weight:700;color:#1a1a1a;">{title}</h1>
<section>
  <h2 {h2}>오늘의 핵심 요약</h2>
  {greeting_html}
  {summary_html}
</section>
<section>
  <h2 {h2}>오늘의 TOP 3 뉴스 브리핑</h2>
  <ul style="margin:0 0 14px 18px;padding:0;">{watch_items or '<li style="margin:0 0 12px 0;"><p style="margin:0;font-size:15px;line-height:1.7;color:#1a1a1a;">(체크포인트 없음)</p></li>'}</ul>
</section>
<section>
  <h2 {h2}>오늘 보는 숫자</h2>
  {numbers_inner}
</section>
<section>
  <h2 {h2}>오늘의 리스크</h2>
  <ul style="margin:0 0 14px 18px;padding:0;">{risks or '<li style="margin:0 0 12px 0;"><p style="margin:0;font-size:15px;line-height:1.7;color:#1a1a1a;">(리스크 항목 없음)</p></li>'}</ul>
</section>
<section>
  <h2 {h2}>오늘의 한 줄 기준</h2>
  <div style="margin:32px 0 32px 0;padding:16px 18px;border:1px solid #d9d9d9;background:#fafafa;">
    <p style="margin:0;font-size:16px;line-height:1.7;font-weight:700;color:#1a1a1a;">{closing}</p>
  </div>
</section>
<p style="margin:0 0 14px 0;font-size:12px;line-height:1.6;color:#666;">{_safe(TODAY_EMAIL_CLOSING_CRITERION)}</p>
<p style="margin:0 0 14px 0;font-size:12px;line-height:1.65;color:#555;">{_safe(TODAY_GENIE_LEGAL_DISCLAIMER)}</p>
{hashtags_html}
""".strip()


def render_email_html(
    mode: str,
    data: Dict[str, Any],
    operational_meta: Optional[Dict[str, Any]] = None,
    email_asset_base_url: str = "",
) -> str:
    title = _safe(data.get("title", ""))
    summary_html = _summary_html(data.get("summary", ""))
    closing = _safe(data.get("closing_message", ""))

    if mode == "today_genie":
        editorial = _build_today_genie_email_editorial_html(data)

    else:
        header_label = '<p style="margin:0 0 10px 0;font-size:12px;line-height:1.6;color:#666;"><strong>[내일 준비]</strong></p>'
        weather_sum = _safe(data.get("weather_summary_block", ""))
        weather_briefing_html = _paragraphs_html(data.get("weather_briefing", ""))
        outfit_html = _paragraphs_html(data.get("outfit_recommendation", ""))
        lifestyle_notes = "".join(
            f"<li style='margin:0 0 12px 0;'><p style='margin:0;font-size:15px;line-height:1.7;color:#1a1a1a;'>{_safe(item)}</p></li>"
            for item in data.get("lifestyle_notes", [])
        )
        zodiac_items = "".join(
            '<li style="margin:0 0 12px 0;">'
            f'<p style="margin:0;font-size:15px;line-height:1.7;color:#1a1a1a;"><span style="font-size:16px;line-height:1.5;font-weight:700;">{_safe(item.get("sign"))}</span> · {_safe(item.get("fortune"))}</p>'
            "</li>"
            for item in data.get("zodiac_fortunes", [])
            if isinstance(item, dict)
        )
        hashtags_html = _hashtags_block_html(mode, data.get("hashtags", []))
        editorial = f"""
{header_label}
<h1 style="margin:0 0 16px 0;font-size:28px;line-height:1.35;font-weight:700;color:#1a1a1a;">{title}</h1>
<section>
  {summary_html}
</section>
<section>
  <h2 style="margin:36px 0 14px 0;font-size:20px;line-height:1.4;font-weight:700;color:#1a1a1a;">내일 날씨 한눈에</h2>
  <p style="margin:0 0 14px 0;font-size:15px;line-height:1.75;color:#1a1a1a;">{weather_sum}</p>
</section>
<section>
  <h2 style="margin:36px 0 14px 0;font-size:20px;line-height:1.4;font-weight:700;color:#1a1a1a;">날씨 브리핑</h2>
  {weather_briefing_html}
</section>
<section>
  <h2 style="margin:36px 0 14px 0;font-size:20px;line-height:1.4;font-weight:700;color:#1a1a1a;">옷차림 추천</h2>
  {outfit_html}
</section>
<section>
  <h2 style="margin:36px 0 14px 0;font-size:20px;line-height:1.4;font-weight:700;color:#1a1a1a;">생활 팁</h2>
  <ul style="margin:0 0 14px 18px;padding:0;">{lifestyle_notes or '<li style="margin:0 0 12px 0;"><p style="margin:0;font-size:15px;line-height:1.7;color:#1a1a1a;">(팁 없음)</p></li>'}</ul>
</section>
<section>
  <h2 style="margin:36px 0 14px 0;font-size:20px;line-height:1.4;font-weight:700;color:#1a1a1a;">별자리 운세</h2>
  <ul style="margin:0 0 14px 18px;padding:0;">{zodiac_items or '<li style="margin:0 0 12px 0;"><p style="margin:0;font-size:15px;line-height:1.7;color:#1a1a1a;">(운세 없음)</p></li>'}</ul>
</section>
<section>
  <h2 style="margin:36px 0 14px 0;font-size:20px;line-height:1.4;font-weight:700;color:#1a1a1a;">내일의 한 줄 기준</h2>
  <div style="margin:32px 0 32px 0;padding:16px 18px;border:1px solid #d9d9d9;background:#fafafa;">
    <p style="margin:0;font-size:16px;line-height:1.7;font-weight:700;color:#1a1a1a;">{closing}</p>
  </div>
</section>
{hashtags_html}
""".strip()

    top_img, bottom_img = email_image_slots_html(mode, email_asset_base_url)
    # Order: top image → editorial (through hashtags / decision) → admin handoff → bottom decorative image.
    op_block = (
        render_email_operational_box(operational_meta) if operational_meta else ""
    )
    return _email_wrapper_inner(f"{top_img}{editorial}{op_block}{bottom_img}", "")


def render_naver_body_html(mode: str, data: Dict[str, Any]) -> str:
    title = _safe(data.get("title", ""))
    summary = _safe(data.get("summary", ""))
    closing = _safe(data.get("closing_message", ""))

    if mode == "today_genie":
        greeting = _safe(data.get("greeting", ""))
        market_setup = _safe(data.get("market_setup", ""))
        market_snapshot_items = "".join(
            f"<li><strong>{_safe(item.get('label'))}</strong>: {_safe(item.get('value'))} "
            f"({_safe(_today_genie_basis_label_ko(item.get('basis')))})</li>"
            for item in data.get("market_snapshot", [])
            if isinstance(item, dict)
        )
        watch_items = "".join(
            f"<li><strong>{_safe(item.get('headline'))}</strong><br>{_safe(item.get('detail'))}</li>"
            for item in data.get("key_watchpoints", [])
            if isinstance(item, dict)
        )
        opportunities = "".join(
            f"<li><strong>{_safe(item.get('theme'))}</strong><br>{_safe(item.get('reason'))} "
            f"({_safe(_today_genie_basis_label_ko(item.get('basis')))})</li>"
            for item in data.get("opportunities", [])
            if isinstance(item, dict)
        )
        risks = "".join(
            f"<li><strong>{_safe(item.get('risk'))}</strong><br>{_safe(item.get('detail'))}</li>"
            for item in data.get("risk_check", [])
            if isinstance(item, dict)
        )
        numbers_block = ""
        if market_setup:
            numbers_block += f"<h3>맥락·셋업</h3><p>{market_setup}</p>"
        if market_snapshot_items:
            numbers_block += f"<h3>지표·시세 스냅샷</h3><ul>{market_snapshot_items}</ul>"
        if opportunities:
            numbers_block += f"<h3>오늘의 시장 관점</h3><ul>{opportunities}</ul>"
        if not numbers_block:
            numbers_block = "<p>(작성된 숫자·맥락 블록이 없습니다.)</p>"
        hashtag_lines = _build_email_hashtags("today_genie", data.get("hashtags", []))
        ht_block = "".join(f"<p>{_safe(ht)}</p>" for ht in hashtag_lines)
        return f"""
<h2>{title}</h2>
<section>
<h3>오늘의 핵심 요약</h3>
<p>{greeting}</p>
<p>{summary}</p>
</section>
<section>
<h3>오늘의 TOP 3 뉴스 브리핑</h3>
<ul>{watch_items}</ul>
</section>
<section>
<h3>오늘 보는 숫자</h3>
{numbers_block}
</section>
<section>
<h3>오늘의 리스크</h3>
<ul>{risks}</ul>
</section>
<section>
<h3>오늘의 한 줄 기준</h3>
<p>{closing}</p>
</section>
<section>
<h3>해시태그</h3>
{ht_block}
</section>
<p>{_safe(TODAY_GENIE_LEGAL_DISCLAIMER)}</p>
""".strip()

    weather_briefing = _safe(data.get("weather_briefing", ""))
    outfit = _safe(data.get("outfit_recommendation", ""))
    lifestyle_notes = "".join(f"<li>{_safe(item)}</li>" for item in data.get("lifestyle_notes", []))
    return f"""
<h2>{title}</h2>
<p>{summary}</p>
<h3>내일 날씨</h3>
<p>{weather_briefing}</p>
<h3>옷차림</h3>
<p>{outfit}</p>
<h3>생활 팁</h3>
<ul>{lifestyle_notes}</ul>
<p>{closing}</p>
""".strip()

