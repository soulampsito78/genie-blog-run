from __future__ import annotations

from html import escape
from typing import Any, Dict


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


def render_email_html(mode: str, data: Dict[str, Any]) -> str:
    title = _safe(data.get("title", ""))
    summary = _safe(data.get("summary", ""))
    closing = _safe(data.get("closing_message", ""))

    if mode == "today_genie":
        body_core = _safe(data.get("market_setup", ""))
    else:
        body_core = _safe(data.get("weather_briefing", ""))

    return f"""<div>
  <h1>{title}</h1>
  <p>{summary}</p>
  <p>{body_core}</p>
  <p>{closing}</p>
</div>"""


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

