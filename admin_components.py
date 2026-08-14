"""Reusable server-rendered components for the owner Admin surface.

This module is deliberately presentation-only. It does not read stores, mutate
run state, or call operational services.
"""
from __future__ import annotations

import html
import json
from typing import Any, Iterable, Mapping


PRIMARY_NAV = (
    ("operations", "/admin/operations", "운영 홈", "Operations"),
    ("reviews", "/admin/reviews", "검수함", "Review Queue"),
    ("incidents", "/admin/incidents", "장애·복구", "Incidents"),
    ("delivery", "/admin/delivery", "발송", "Delivery"),
    ("system", "/admin/system", "시스템 상태", "System"),
)

SECONDARY_NAV = (
    ("history", "/admin/history", "실행 이력"),
    ("settings", "/admin/settings", "설정"),
)


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def badge(label: object, tone: str = "neutral") -> str:
    return f'<span class="status status--{esc(tone)}">{esc(label)}</span>'


def page_header(title: str, description: str = "", eyebrow: str = "OWNER ADMIN") -> str:
    desc = f'<p class="page-description">{esc(description)}</p>' if description else ""
    return (
        '<div class="page-head"><header class="page-title">'
        f'<p class="eyebrow">{esc(eyebrow)}</p>'
        f'<h1>{esc(title)}</h1>{desc}'
        '</header></div>'
    )


def empty_state(title: str, description: str) -> str:
    return (
        '<div class="empty-state">'
        f'<strong>{esc(title)}</strong><p>{esc(description)}</p>'
        '</div>'
    )


def metric(label: str, value: object, helper: str = "") -> str:
    helper_html = f'<span>{esc(helper)}</span>' if helper else ""
    return (
        '<div class="metric">'
        f'<span class="metric__label">{esc(label)}</span>'
        f'<strong>{esc(value)}</strong>{helper_html}'
        '</div>'
    )


def technical_details(
    meta: Mapping[str, Any],
    rows: Iterable[tuple[str, object]],
    *,
    title: str = "기술 세부정보 보기",
) -> str:
    summary = "".join(
        '<div class="diagnostic-row">'
        f'<span>{esc(label)}</span><code>{esc(value if value not in (None, "") else "미기록")}</code>'
        '</div>'
        for label, value in rows
    )
    raw = esc(json.dumps(dict(meta), ensure_ascii=False, indent=2, default=str))
    return f"""
<details class="technical-details">
  <summary>{esc(title)}</summary>
  <div class="technical-details__body">
    <div class="diagnostic-grid">{summary}</div>
    <details class="raw-details">
      <summary>원본 JSON 보기</summary>
      <pre>{raw}</pre>
    </details>
  </div>
</details>
"""


def email_preview(content: str | None, *, title: str = "고객에게 보이는 브리핑") -> str:
    if not str(content or "").strip():
        return empty_state("저장된 브리핑 없음", "고객 발송용 HTML이 없어 승인할 수 없습니다.")
    srcdoc = html.escape(str(content), quote=True)
    return f"""
<section class="briefing-section" aria-labelledby="briefing-preview-title">
  <div class="section-heading">
    <div><p class="eyebrow">FINAL CONTENT</p><h2 id="briefing-preview-title">{esc(title)}</h2></div>
    <span class="evidence-label">저장된 실제 HTML</span>
  </div>
  <iframe class="briefing-frame" title="저장된 고객 브리핑 미리보기" sandbox srcdoc="{srcdoc}"></iframe>
</section>
"""


def _navigation(active: str) -> str:
    primary = "".join(
        f'<a class="nav-link{" is-active" if key == active else ""}" href="{href}">'
        f'<span>{esc(ko)}</span><small>{esc(en)}</small></a>'
        for key, href, ko, en in PRIMARY_NAV
    )
    secondary = "".join(
        f'<a class="utility-link{" is-active" if key == active else ""}" href="{href}">{esc(label)}</a>'
        for key, href, label in SECONDARY_NAV
    )
    return f"""
<header class="admin-header">
  <a class="brand" href="/admin/operations" aria-label="Genie Owner Admin 운영 홈">
    <span class="brand-mark">G</span><span><strong>GENIE × KEESURI</strong><small>OWNER ADMIN</small></span>
  </a>
  <div class="header-utilities">{secondary}
    <form method="post" action="/admin/logout"><button type="submit" class="text-button">로그아웃</button></form>
  </div>
</header>
<nav class="primary-nav" aria-label="주요 운영 메뉴">{primary}</nav>
"""


def layout(title: str, inner: str, *, active: str = "", authenticated: bool = True) -> str:
    navigation = _navigation(active) if authenticated else ""
    shell_class = "admin-shell" if authenticated else "login-shell"
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>
:root{{--ink:#122018;--muted:#657168;--line:#dce4dd;--canvas:#f3f6f2;--card:#fff;--green:#145c3b;--green-soft:#e7f3ec;--amber:#9a5700;--amber-soft:#fff2d9;--red:#a72d2d;--red-soft:#fde9e7;--blue:#285a88;--blue-soft:#e9f1f8;--shadow:0 14px 35px rgba(23,47,31,.07);}}
*{{box-sizing:border-box;}}
html{{background:var(--canvas);}}
body{{margin:0;background:var(--canvas);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:16px;line-height:1.55;overflow-wrap:break-word;}}
a{{color:inherit;}}
button,input,select,textarea{{font:inherit;}}
button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,summary:focus-visible{{outline:3px solid #65a87f;outline-offset:3px;}}
.admin-shell{{width:min(1180px,calc(100% - 32px));margin:0 auto 64px;}}
.login-shell{{width:min(520px,calc(100% - 32px));margin:8vh auto;}}
.admin-header{{min-height:82px;display:flex;align-items:center;justify-content:space-between;gap:24px;}}
.brand{{display:flex;align-items:center;gap:12px;text-decoration:none;}}
.brand-mark{{display:grid;place-items:center;width:38px;height:38px;border-radius:11px;background:var(--ink);color:white;font-weight:850;}}
.brand strong,.brand small{{display:block;letter-spacing:.04em;}}
.brand small{{font-size:11px;color:var(--muted);margin-top:1px;}}
.header-utilities{{display:flex;align-items:center;gap:18px;font-size:14px;}}
.header-utilities form{{margin:0;}}
.utility-link,.text-button{{color:var(--muted);text-decoration:none;border:0;background:none;padding:6px 0;cursor:pointer;}}
.utility-link.is-active{{color:var(--ink);font-weight:750;}}
.primary-nav{{display:grid;grid-template-columns:repeat(5,1fr);background:#e8ede8;padding:5px;border-radius:14px;gap:4px;position:sticky;top:8px;z-index:10;box-shadow:0 6px 18px rgba(23,47,31,.05);}}
.nav-link{{display:flex;align-items:baseline;justify-content:center;gap:7px;padding:11px 10px;border-radius:10px;color:#536158;text-decoration:none;font-weight:720;white-space:nowrap;}}
.nav-link small{{font-size:10px;font-weight:650;opacity:.75;}}
.nav-link.is-active{{background:white;color:var(--ink);box-shadow:0 2px 8px rgba(23,47,31,.08);}}
main{{padding-top:34px;}}
.page-title{{margin:0 0 26px;}}
.eyebrow{{margin:0 0 7px;color:var(--green);font-size:11px;font-weight:850;letter-spacing:.13em;}}
h1{{font-size:clamp(1.75rem,4vw,2.55rem);line-height:1.15;margin:0;letter-spacing:-.035em;}}
h2{{font-size:1.25rem;line-height:1.3;margin:0;letter-spacing:-.015em;}}
h3{{font-size:1rem;margin:0;}}
.page-description{{max-width:720px;color:var(--muted);margin:10px 0 0;font-size:15px;}}
.section-heading{{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin:28px 0 12px;}}
.section-heading p{{margin:0 0 4px;}}
.section-heading h2{{margin:0;}}
.card,.surface{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px;box-shadow:var(--shadow);}}
.card-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;}}
.stack{{display:grid;gap:14px;}}
.action-card{{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:20px;background:white;border:1px solid var(--line);border-left:5px solid var(--amber);border-radius:14px;padding:18px 20px;}}
.action-card p,.program-card p,.empty-state p{{margin:4px 0 0;color:var(--muted);}}
.program-card{{background:white;border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:var(--shadow);min-width:0;}}
.program-card__top,.run-card__top{{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;}}
.program-card__time{{font-size:13px;color:var(--muted);margin-top:2px;}}
.program-card__state{{font-size:1.2rem;font-weight:820;margin:28px 0 4px;}}
.program-card__impact{{min-height:48px;color:var(--muted);font-size:14px;}}
.program-card__footer{{display:flex;align-items:center;justify-content:space-between;gap:12px;border-top:1px solid var(--line);padding-top:14px;margin-top:16px;font-size:13px;}}
.status{{display:inline-flex;align-items:center;min-height:27px;padding:4px 9px;border-radius:999px;font-size:12px;font-weight:800;letter-spacing:.01em;white-space:nowrap;background:#eef1ee;color:#526058;}}
.status--good{{background:var(--green-soft);color:var(--green);}}
.status--warn{{background:var(--amber-soft);color:var(--amber);}}
.status--danger{{background:var(--red-soft);color:var(--red);}}
.status--info{{background:var(--blue-soft);color:var(--blue);}}
.btn{{display:inline-flex;align-items:center;justify-content:center;min-height:46px;padding:11px 16px;border:0;border-radius:10px;background:var(--ink);color:#fff;text-decoration:none;font-weight:780;cursor:pointer;}}
.btn:hover{{filter:brightness(1.08);}}
.btn--secondary{{background:#edf1ed;color:var(--ink);}}
.btn--danger{{background:var(--red);}}
.btn--warning{{background:var(--amber);}}
.btn[disabled]{{background:#aab3ac;cursor:not-allowed;}}
.actions{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;}}
.actions form{{margin:0;}}
.danger-zone{{border:1px solid #efc5c0;background:#fff9f8;border-radius:14px;padding:18px;}}
.danger-zone .btn{{background:var(--red);}}
.notice,.warn{{border:1px solid #e8c780;background:var(--amber-soft);color:#65400b;border-radius:12px;padding:14px 16px;}}
.notice--danger{{border-color:#efc5c0;background:var(--red-soft);color:#762323;}}
.notice--good{{border-color:#b9ddc7;background:var(--green-soft);color:#174e34;}}
.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;}}
.metric{{background:#f7f9f7;border:1px solid var(--line);border-radius:12px;padding:14px;min-width:0;}}
.metric__label,.metric span{{display:block;color:var(--muted);font-size:12px;}}
.metric strong{{display:block;font-size:1.05rem;margin:5px 0 2px;overflow-wrap:anywhere;}}
.run-card{{background:white;border:1px solid var(--line);border-radius:14px;padding:18px;}}
.run-card__meta{{display:flex;flex-wrap:wrap;gap:8px 16px;color:var(--muted);font-size:13px;margin:8px 0 14px;}}
.run-card__flow{{font-weight:720;margin:8px 0;}}
.briefing-section{{margin:24px 0;}}
.briefing-frame{{display:block;width:100%;height:680px;border:1px solid var(--line);border-radius:14px;background:white;}}
.evidence-label{{font-size:12px;color:var(--muted);}}
.validation-list{{list-style:none;padding:0;margin:14px 0 0;display:grid;gap:9px;}}
.validation-list li{{display:flex;align-items:flex-start;gap:10px;padding:10px 12px;border-radius:10px;background:#f7f9f7;}}
.validation-list .marker{{width:9px;height:9px;margin-top:7px;flex:0 0 auto;border-radius:999px;background:var(--green);}}
.validation-list li.is-warn .marker{{background:var(--amber);}}
.validation-list li.is-danger .marker{{background:var(--red);}}
.technical-details{{margin-top:22px;border:1px solid var(--line);border-radius:13px;background:#eef2ee;}}
.technical-details>summary,.raw-details>summary{{cursor:pointer;font-weight:780;padding:15px 17px;}}
.technical-details__body{{padding:0 17px 17px;}}
.technical-details:not([open])>.technical-details__body,.raw-details:not([open])>pre{{display:none;}}
.diagnostic-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;}}
.diagnostic-row{{background:white;border:1px solid var(--line);border-radius:9px;padding:11px;min-width:0;}}
.diagnostic-row span{{display:block;font-size:11px;color:var(--muted);margin-bottom:4px;}}
.diagnostic-row code{{font-size:12px;word-break:break-all;}}
.raw-details{{margin-top:12px;background:#17201a;color:#e7eee8;border-radius:10px;}}
.raw-details pre{{margin:0;padding:0 16px 16px;max-height:480px;overflow:auto;white-space:pre-wrap;font-size:12px;}}
.empty-state{{padding:32px;border:1px dashed #bac5bc;border-radius:14px;text-align:center;background:#f8faf8;}}
.form-grid{{display:grid;gap:14px;}}
.history-filter{{grid-template-columns:repeat(3,minmax(0,1fr)) auto;align-items:end;}}
label{{font-weight:720;}}
input[type=password],input[type=text],input[type=date],select,textarea{{display:block;width:100%;max-width:560px;margin-top:6px;padding:11px 12px;border:1px solid #bac5bc;border-radius:9px;background:white;font-size:16px;}}
input[type=checkbox],input[type=radio]{{width:20px;height:20px;vertical-align:middle;}}
.radio-scope{{display:flex;align-items:flex-start;gap:10px;margin:0 0 10px;padding:14px 16px;border:1px solid var(--line);border-radius:10px;background:#f8faf8;cursor:pointer;}}
.radio-scope:has(input:checked){{border-color:var(--green);box-shadow:inset 0 0 0 1px var(--green);background:white;}}
.radio-scope--disabled{{opacity:.55;cursor:not-allowed;}}
.radio-scope__control{{padding-top:2px;}}
.radio-scope__body{{flex:1;min-width:0;}}
.radio-helper{{display:block;color:var(--muted);font-size:12px;margin-top:5px;}}
.table-wrap{{overflow-x:auto;-webkit-overflow-scrolling:touch;}}
table{{width:100%;border-collapse:collapse;font-size:14px;}}
th,td{{padding:10px;border-top:1px solid var(--line);text-align:left;vertical-align:top;}}
th{{background:#f1f4f1;}}
.break-long,code{{overflow-wrap:anywhere;word-break:break-word;}}
.timeline{{display:grid;gap:0;}}
.timeline-item{{position:relative;padding:0 0 20px 30px;}}
.timeline-item:before{{content:"";position:absolute;left:5px;top:7px;width:10px;height:10px;border-radius:50%;background:var(--green);}}
.timeline-item:after{{content:"";position:absolute;left:9px;top:20px;bottom:0;width:2px;background:var(--line);}}
.timeline-item:last-child:after{{display:none;}}
.timeline-item p{{margin:3px 0;color:var(--muted);}}
@media(max-width:820px){{
  .admin-shell{{width:min(100% - 22px,1180px);}}
  .admin-header{{min-height:68px;}}
  .header-utilities{{gap:10px;}} .utility-link{{display:none;}}
  .brand strong{{font-size:13px;}}
  .primary-nav{{grid-template-columns:repeat(3,minmax(0,1fr));position:static;}}
  .nav-link{{display:block;text-align:center;padding:10px 7px;font-size:13px;}}
  .nav-link small{{display:none;}}
  main{{padding-top:24px;}}
  .card-grid,.metrics{{grid-template-columns:1fr;}}
  .action-card{{grid-template-columns:1fr;}}
  .action-card .btn{{width:100%;}}
  .diagnostic-grid{{grid-template-columns:1fr;}}
  .briefing-frame{{height:620px;}}
  .history-filter{{grid-template-columns:1fr;}}
}}
@media(max-width:520px){{
  body{{font-size:16px;}}
  .admin-shell{{width:100%;padding:0 12px;}}
  .brand-mark{{width:34px;height:34px;}}
  .header-utilities{{font-size:13px;}}
  .primary-nav{{margin:0 -4px;}}
  .page-title{{margin-bottom:20px;}}
  .card,.surface,.program-card{{padding:17px;}}
  .section-heading{{align-items:flex-start;flex-direction:column;gap:4px;}}
  .actions{{display:grid;grid-template-columns:1fr;width:100%;}}
  .actions .btn,.actions form,.actions form .btn{{width:100%;}}
  .briefing-frame{{height:560px;}}
}}
</style></head><body><div class="{shell_class}">{navigation}<main>{inner}</main></div></body></html>"""
