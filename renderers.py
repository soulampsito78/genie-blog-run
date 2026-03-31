from __future__ import annotations

from html import escape
from typing import Any, Dict, Optional

# Email: one-line finance discipline (server-owned, not model output)
TODAY_EMAIL_CLOSING_CRITERION = (
    "오늘의 판단 기준: 입력·공시 범위 밖의 수치·종목·뉴스는 본문에 넣지 않았습니다. "
    "불확실할수록 설명을 짧게 유지하는 편이 안전합니다."
)


def _safe(text: Any) -> str:
    if text is None:
        return ""
    return escape(str(text))


def render_web_html(mode: str, data: Dict[str, Any]) -> str:
    title = _safe(data.get("title", ""))
    summary = _safe(data.get("summary", ""))
    greeting = _safe(data.get("greeting", ""))
    closing = _safe(data.get("closing_message", ""))

    if mode == "today_genie":
        market_setup = _safe(data.get("market_setup", ""))
        market_snapshot_items = "".join(
            f"<li><strong>{_safe(item.get('label'))}</strong>: {_safe(item.get('value'))} "
            f"({_safe(item.get('basis'))})</li>"
            for item in data.get("market_snapshot", [])
            if isinstance(item, dict)
        )
        watch_items = "".join(
            f"<li><strong>{_safe(item.get('headline'))}</strong><br>{_safe(item.get('detail'))}</li>"
            for item in data.get("key_watchpoints", [])
            if isinstance(item, dict)
        )
        opportunities = "".join(
            f"<li><strong>{_safe(item.get('theme'))}</strong><br>{_safe(item.get('reason'))}</li>"
            for item in data.get("opportunities", [])
            if isinstance(item, dict)
        )
        risks = "".join(
            f"<li><strong>{_safe(item.get('risk'))}</strong><br>{_safe(item.get('detail'))}</li>"
            for item in data.get("risk_check", [])
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
      <h2>시장 셋업</h2>
      <p>{market_setup}</p>
    </section>

    <section>
      <h2>시장 스냅샷</h2>
      <ul>{market_snapshot_items}</ul>
    </section>

    <section>
      <h2>핵심 체크포인트</h2>
      <ul>{watch_items}</ul>
    </section>

    <section>
      <h2>기회 요인</h2>
      <ul>{opportunities}</ul>
    </section>

    <section>
      <h2>리스크 체크</h2>
      <ul>{risks}</ul>
    </section>

    <footer>
      <p>{closing}</p>
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
        '<div style="max-width:600px;margin:0 auto;font-family:system-ui,Segoe UI,Helvetica,Arial,sans-serif;'
        'font-size:16px;line-height:1.55;color:#1a1a1a;">'
        f"{content}{footer_html}"
        "</div>"
    )


def _email_img_block(absolute_url: str, alt: str) -> str:
    """Single email-safe image block; absolute URL required for clients."""
    return (
        '<div style="margin:0 0 18px 0;text-align:center;">'
        f'<img src="{_safe(absolute_url)}" alt="{_safe(alt)}" width="560" '
        'style="max-width:100%;height:auto;display:block;margin:0 auto;border:0;outline:none;" />'
        "</div>"
    )


def email_image_slots_html(mode: str, public_base_url: str) -> tuple[str, str]:
    """
    Locked reference assets under /static/email/ (served by API).
    Same file URL may be used twice (studio vs outdoor) with different alt text — identity locked per mode.
    Returns (top_slot_html, bottom_slot_html); empty strings if no base URL.
    """
    base = (public_base_url or "").strip().rstrip("/")
    if not base:
        return "", ""

    if mode == "today_genie":
        path = "static/email/GENIE_REF_today_genie_master_v1.jpg"
        top_alt = "Genie — 스튜디오 인사 컷 (장전 브리핑)"
        bot_alt = "Genie — 야외 편안한 휴식 컷 (장전 브리핑, 동일 인물)"
    else:
        path = "static/email/GENIE_REF_tomorrow_genie_master_v1.jpg"
        top_alt = "Genie — 스튜디오 인사 컷 (내일 준비)"
        bot_alt = "Genie — 야외 OOTD·편안한 휴식 컷 (내일 준비)"

    url = f"{base}/{path}"
    return _email_img_block(url, top_alt), _email_img_block(url, bot_alt)


def render_email_operational_box(meta: Dict[str, Any]) -> str:
    """
    Deterministic operational footer: mode, workflow, time, summary, send note, reissue hint.
    Not model-generated.
    """
    mode = _safe(meta.get("mode", ""))
    vr = _safe(meta.get("validation_result", ""))
    wf = _safe(meta.get("workflow_status", ""))
    exec_kst = _safe(meta.get("execution_time_kst", ""))
    result_line = _safe(meta.get("result_summary_line", ""))
    send_note = _safe(
        meta.get(
            "email_send_status_note",
            "이 HTML은 API 생성 단계 산출물입니다. 실제 발송·수신은 오케스트레이터·SMTP 경로에 따릅니다.",
        )
    )
    return f"""
<section style="margin-top:28px;padding-top:20px;border-top:1px solid #ccc;">
  <p style="margin:0 0 8px 0;font-size:13px;color:#555;"><strong>[운영 · Genie]</strong></p>
  <ul style="margin:0;padding-left:18px;font-size:13px;color:#444;line-height:1.5;">
    <li><strong>모드</strong>: {mode}</li>
    <li><strong>상태</strong>: 검증={vr} · 워크플로={wf}</li>
    <li><strong>생성 시각 (KST)</strong>: {exec_kst}</li>
    <li><strong>결과 요약</strong>: {result_line}</li>
    <li><strong>이메일 발송</strong>: {send_note}</li>
  </ul>
  <div style="margin-top:14px;padding:12px;background:#f7f7f7;border-radius:4px;font-size:12px;color:#333;">
    <p style="margin:0 0 6px 0;"><strong>재발행 요청</strong> (내부 검토 후 처리)</p>
    <p style="margin:0;">제목·요약·문장·이미지·구성·기타 사유로 요청할 수 있습니다. 요청이 곧바로 재실행을 보장하지는 않으며,
    최대 횟수·반영 여부는 운영 정책에 따릅니다.</p>
  </div>
</section>
""".strip()


def render_email_html(
    mode: str,
    data: Dict[str, Any],
    operational_meta: Optional[Dict[str, Any]] = None,
    email_asset_base_url: str = "",
) -> str:
    title = _safe(data.get("title", ""))
    summary = _safe(data.get("summary", ""))
    closing = _safe(data.get("closing_message", ""))

    if mode == "today_genie":
        header_label = '<p style="margin:0 0 4px 0;font-size:13px;color:#666;"><strong>[장전 브리핑]</strong></p>'
        watch_items = "".join(
            f'<li style="margin-bottom:8px;"><strong>{_safe(item.get("headline"))}</strong><br/>'
            f'<span style="font-size:14px;">{_safe(item.get("detail"))}</span></li>'
            for item in data.get("key_watchpoints", [])
            if isinstance(item, dict)
        )
        risks = "".join(
            f'<li style="margin-bottom:8px;"><strong>{_safe(item.get("risk"))}</strong><br/>'
            f'<span style="font-size:14px;">{_safe(item.get("detail"))}</span></li>'
            for item in data.get("risk_check", [])
            if isinstance(item, dict)
        )
        market_setup = _safe(data.get("market_setup", ""))
        market_snapshot_items = "".join(
            f'<li><strong>{_safe(item.get("label"))}</strong>: {_safe(item.get("value"))} '
            f'<span style="color:#666;">({_safe(item.get("basis"))})</span></li>'
            for item in data.get("market_snapshot", [])
            if isinstance(item, dict)
        )
        opportunities = "".join(
            f'<li style="margin-bottom:8px;"><strong>{_safe(item.get("theme"))}</strong><br/>'
            f'{_safe(item.get("reason"))} <span style="color:#666;">({_safe(item.get("basis"))})</span></li>'
            for item in data.get("opportunities", [])
            if isinstance(item, dict)
        )
        supporting = ""
        if market_setup.strip():
            supporting += f'<section style="margin-top:18px;"><h2 style="font-size:17px;margin:0 0 8px 0;">장 셋업</h2><p style="margin:0;">{market_setup}</p></section>'
        if market_snapshot_items:
            supporting += (
                f'<section style="margin-top:18px;"><h2 style="font-size:17px;margin:0 0 8px 0;">시장 스냅샷</h2>'
                f'<ul style="margin:0;padding-left:18px;">{market_snapshot_items}</ul></section>'
            )
        if opportunities:
            supporting += (
                f'<section style="margin-top:18px;"><h2 style="font-size:17px;margin:0 0 8px 0;">기회 요인</h2>'
                f'<ul style="margin:0;padding-left:18px;">{opportunities}</ul></section>'
            )

        editorial = f"""
{header_label}
<h1 style="font-size:22px;line-height:1.25;margin:8px 0 12px 0;">{title}</h1>
<section><h2 style="font-size:17px;margin:0 0 8px 0;">핵심 요약</h2><p style="margin:0;">{summary}</p></section>
<section style="margin-top:18px;"><h2 style="font-size:17px;margin:0 0 8px 0;">핵심 체크포인트</h2>
<ul style="margin:0;padding-left:18px;">{watch_items or "<li>(체크포인트 없음)</li>"}</ul></section>
<section style="margin-top:18px;"><h2 style="font-size:17px;margin:0 0 8px 0;">리스크</h2>
<ul style="margin:0;padding-left:18px;">{risks or "<li>(리스크 항목 없음)</li>"}</ul></section>
{supporting}
<p style="margin-top:20px;font-size:13px;color:#444;border-left:3px solid #ccc;padding-left:10px;">{_safe(TODAY_EMAIL_CLOSING_CRITERION)}</p>
<section style="margin-top:18px;"><p style="margin:0;">{closing}</p></section>
""".strip()

    else:
        header_label = '<p style="margin:0 0 4px 0;font-size:13px;color:#666;"><strong>[내일 준비]</strong></p>'
        weather_sum = _safe(data.get("weather_summary_block", ""))
        weather_briefing = _safe(data.get("weather_briefing", ""))
        outfit = _safe(data.get("outfit_recommendation", ""))
        lifestyle_notes = "".join(
            f"<li style='margin-bottom:6px;'>{_safe(item)}</li>" for item in data.get("lifestyle_notes", [])
        )
        zodiac_items = "".join(
            f'<li style="margin-bottom:6px;font-size:14px;"><strong>{_safe(item.get("sign"))}</strong> · {_safe(item.get("fortune"))}</li>'
            for item in data.get("zodiac_fortunes", [])
            if isinstance(item, dict)
        )
        editorial = f"""
{header_label}
<h1 style="font-size:22px;line-height:1.25;margin:8px 0 12px 0;">{title}</h1>
<section><h2 style="font-size:17px;margin:0 0 8px 0;">핵심 요약</h2><p style="margin:0;">{summary}</p></section>
<section style="margin-top:18px;"><h2 style="font-size:17px;margin:0 0 8px 0;">내일 날씨 한눈에</h2><p style="margin:0;">{weather_sum}</p></section>
<section style="margin-top:18px;"><h2 style="font-size:17px;margin:0 0 8px 0;">날씨 브리핑</h2><p style="margin:0;">{weather_briefing}</p></section>
<section style="margin-top:18px;"><h2 style="font-size:17px;margin:0 0 8px 0;">옷차림 추천</h2><p style="margin:0;">{outfit}</p></section>
<section style="margin-top:18px;"><h2 style="font-size:17px;margin:0 0 8px 0;">생활 팁</h2><ul style="margin:0;padding-left:18px;">{lifestyle_notes or "<li>(팁 없음)</li>"}</ul></section>
<section style="margin-top:18px;"><h2 style="font-size:17px;margin:0 0 8px 0;">별자리 운세</h2><ul style="margin:0;padding-left:18px;">{zodiac_items or "<li>(운세 없음)</li>"}</ul></section>
<section style="margin-top:18px;"><p style="margin:0;">{closing}</p></section>
""".strip()

    top_img, bottom_img = email_image_slots_html(mode, email_asset_base_url)
    # Order: top image → editorial → bottom image → operational box (append via footer; never use
    # string replace on </div> — img blocks contain inner </div> and would break order).
    op_footer = (
        render_email_operational_box(operational_meta) if operational_meta else ""
    )
    return _email_wrapper_inner(f"{top_img}{editorial}{bottom_img}", op_footer)


def render_naver_body_html(mode: str, data: Dict[str, Any]) -> str:
    title = _safe(data.get("title", ""))
    summary = _safe(data.get("summary", ""))
    closing = _safe(data.get("closing_message", ""))

    if mode == "today_genie":
        market_setup = _safe(data.get("market_setup", ""))
        watch_items = "".join(
            f"<li>{_safe(item.get('headline'))} - {_safe(item.get('detail'))}</li>"
            for item in data.get("key_watchpoints", [])
            if isinstance(item, dict)
        )
        return f"""
<h2>{title}</h2>
<p>{summary}</p>
<h3>오늘 장 셋업</h3>
<p>{market_setup}</p>
<h3>핵심 체크포인트</h3>
<ul>{watch_items}</ul>
<p>{closing}</p>
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

