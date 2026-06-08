"""Kee-Suri offline owner-review HTML renderer (no LLM, no email, no live fetch)."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from keysuri_news_contract import SECTION_TOP5_GLOBAL, SECTION_TOP5_KOREA
from keysuri_generated_briefing import (
    GENERATED_STATUS_REQUIRED,
    validate_keysuri_generated_briefing,
)
from keysuri_private_briefing import (
    SECTION_CLOSING,
    SECTION_DEEP_DIVE,
    SECTION_ONE_LINE,
)

IDENTITY_TITLE = "테크 비서 키수리"
IDENTITY_SUBTITLE = "프라이빗 테크 인사이트 브리핑"

PROGRAM_DISPLAY: Dict[str, str] = {
    "keysuri_global_tech": "Kee-Suri Global Tech",
    "keysuri_korea_tech": "Kee-Suri Korea Tech",
}

ACTIVE_SCHEDULER_ROWS: List[tuple[str, str]] = [
    ("Today_Geenee", "06:30 KST"),
    ("Kee-Suri Global Tech", "12:30 KST"),
    ("Kee-Suri Korea Tech", "18:30 KST"),
]

EXTRA_IDENTITY_GUARDRAILS: List[str] = [
    "공개 방송형 브리핑 톤 금지",
    "진행자형 공개 뉴스 데스크 톤 금지",
    "테크/비즈니스 비서가 아닌 앵커형 표현 금지",
]

GENERATION_PENDING_LABEL = "generation_pending"
PreviewMode = Literal["offline", "live_smoke"]


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def load_keysuri_prompt_input_fixture(path: str) -> dict:
    """Load a prompt_input JSON fixture from disk."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Fixture must be a JSON object: {path}")
    return data


def _top5_block(prompt_input: dict) -> Optional[Dict[str, Any]]:
    top = prompt_input.get("top_5_news")
    if isinstance(top, dict) and isinstance(top.get("items"), list):
        return top
    sel = prompt_input.get("top_5_selection_result")
    if isinstance(sel, dict):
        nested = sel.get("top_5_news")
        if isinstance(nested, dict):
            return nested
    return None


def _source_pack_stats(prompt_input: dict) -> Dict[str, Any]:
    pack = prompt_input.get("source_pack") if isinstance(prompt_input.get("source_pack"), dict) else {}
    sources = pack.get("sources") if isinstance(pack.get("sources"), list) else []
    claims = pack.get("claims") if isinstance(pack.get("claims"), list) else []
    return {
        "generated_at": pack.get("generated_at"),
        "notes": pack.get("notes"),
        "source_count": len(sources),
        "claim_count": len(claims),
    }


def render_keysuri_top5_section(prompt_input: dict) -> str:
    """Render TOP 5 news cards from prompt_input."""
    heading = _esc(prompt_input.get("section_heading") or "")
    top = _top5_block(prompt_input)
    prompt_status = str(prompt_input.get("prompt_status") or "").strip()

    parts: List[str] = [
        f'<section class="card top5-section" id="top5">',
        f'<h2 class="top5-section-heading">{heading}</h2>',
    ]

    if not top or not top.get("items"):
        parts.append(
            '<p class="muted">TOP 5 항목 없음 — '
            f'prompt_status={_esc(prompt_status or "unknown")}. '
            "Gemini 호출 전 또는 hold_review_required 상태일 수 있습니다.</p>"
        )
        parts.append("</section>")
        return "\n".join(parts)

    items = top.get("items") or []
    parts.append(f'<p class="meta">news_scope: {_esc(top.get("news_scope"))} · items: {len(items)}</p>')
    for item in items:
        if not isinstance(item, dict):
            continue
        rank = _esc(item.get("rank"))
        headline = _esc(item.get("headline"))
        category = _esc(item.get("category"))
        summary = _esc(item.get("summary"))
        why = _esc(item.get("why_it_matters"))
        biz = _esc(item.get("business_implication"))
        confidence = _esc(item.get("confidence_label"))
        source_ids = item.get("source_ids") if isinstance(item.get("source_ids"), list) else []
        sources_txt = _esc(", ".join(str(s) for s in source_ids))
        risk = item.get("risk_note")
        risk_html = ""
        if risk and str(risk).strip():
            risk_html = f'<p class="risk"><strong>risk_note:</strong> {_esc(risk)}</p>'

        parts.extend(
            [
                f'<article class="news-card" data-rank="{rank}">',
                f'<header class="news-card-header"><span class="rank">#{rank}</span>'
                f'<h3 class="headline">{headline}</h3></header>',
                f'<p class="category"><strong>category:</strong> {category}</p>',
                f'<p class="summary">{summary}</p>',
                f'<p class="why"><strong>why_it_matters:</strong> {why}</p>',
                f'<p class="biz"><strong>business_implication:</strong> {biz}</p>',
                f'<p class="confidence"><strong>confidence:</strong> {confidence}</p>',
                f'<p class="sources"><strong>source_ids:</strong> {sources_txt}</p>',
                risk_html,
                "</article>",
            ]
        )

    parts.append("</section>")
    return "\n".join(parts)


def render_keysuri_source_audit_section(prompt_input: dict) -> str:
    """Render source gate and TOP 5 selection audit."""
    stats = _source_pack_stats(prompt_input)
    gate_result = _esc(prompt_input.get("source_gate_result"))
    gate_issues = prompt_input.get("source_gate_issues")
    sel = prompt_input.get("top_5_selection_result")
    sel_verdict = ""
    sel_issues: List[Any] = []
    if isinstance(sel, dict):
        sel_verdict = _esc(sel.get("verdict"))
        raw_issues = sel.get("issues")
        if isinstance(raw_issues, list):
            sel_issues = raw_issues

    issue_rows: List[str] = []
    if isinstance(gate_issues, list):
        for issue in gate_issues:
            if isinstance(issue, dict):
                issue_rows.append(
                    f"<li><code>{_esc(issue.get('code'))}</code> — {_esc(issue.get('message'))}</li>"
                )
    if not issue_rows:
        issue_rows.append("<li class='muted'>source_gate_issues: none</li>")

    sel_rows: List[str] = []
    for issue in sel_issues:
        if isinstance(issue, dict):
            sel_rows.append(
                f"<li><code>{_esc(issue.get('code'))}</code> — {_esc(issue.get('message'))}</li>"
            )
    if not sel_rows:
        sel_rows.append("<li class='muted'>top_5_selection issues: none</li>")

    return "\n".join(
        [
            '<section class="card audit-section" id="audit">',
            "<h2>Source Gate / TOP 5 Selection Audit</h2>",
            "<dl class='audit-dl'>",
            f"<dt>source_gate_result</dt><dd>{gate_result}</dd>",
            f"<dt>top_5_selection_result.verdict</dt><dd>{sel_verdict}</dd>",
            f"<dt>source_pack.generated_at</dt><dd>{_esc(stats.get('generated_at'))}</dd>",
            f"<dt>source count</dt><dd>{stats['source_count']}</dd>",
            f"<dt>claim count</dt><dd>{stats['claim_count']}</dd>",
            "</dl>",
            f"<p class='pack-notes muted'>{_esc(stats.get('notes'))}</p>",
            "<h3>source_gate_issues</h3><ul>",
            *issue_rows,
            "</ul>",
            "<h3>top_5_selection_result.issues</h3><ul>",
            *sel_rows,
            "</ul>",
            "</section>",
        ]
    )


def render_keysuri_placeholder_sections(
    prompt_input: dict,
    *,
    preview_mode: PreviewMode = "offline",
) -> str:
    """Render generation_pending placeholders for sections not yet generated."""
    labels = prompt_input.get("fixed_section_labels")
    if not isinstance(labels, dict):
        labels = {}

    placeholder_sections = [
        (labels.get("deep_dive") or SECTION_DEEP_DIVE, "deep-dive"),
        (labels.get("one_line_checkpoint") or SECTION_ONE_LINE, "one-line"),
        (labels.get("closing_sources") or SECTION_CLOSING, "closing"),
    ]
    parts: List[str] = []
    if preview_mode == "live_smoke":
        pending_note = (
            "<p class='muted'>Live source smoke — source-led cards only · 최종 문안이 아님</p>"
        )
        pending_body = (
            "<p>키수리 프라이빗 비서 문안은 generation 단계 이후 채워집니다. "
            "이 preview는 live source smoke owner-review 화면입니다.</p>"
        )
    else:
        pending_note = "<p class='muted'>Gemini 호출 전 · 최종 문안이 아님</p>"
        pending_body = (
            "<p>키수리 프라이빗 비서 문안은 generation 단계 이후 채워집니다. "
            "이 preview는 prompt_input 기반 owner-review 화면입니다.</p>"
        )
    for title, slug in placeholder_sections:
        parts.extend(
            [
                f'<section class="card placeholder-section" id="{slug}">',
                f"<h2>{_esc(title)}</h2>",
                f'<p class="badge-pending">{GENERATION_PENDING_LABEL}</p>',
                pending_note,
                pending_body,
                "</section>",
            ]
        )
    return "\n".join(parts)


def render_keysuri_generated_sections(generated_briefing: dict) -> str:
    """Render validated generated deep_dive, one_line, and closing_sources sections."""
    deep = generated_briefing.get("deep_dive") if isinstance(generated_briefing.get("deep_dive"), dict) else {}
    one_line = (
        generated_briefing.get("one_line_checkpoint")
        if isinstance(generated_briefing.get("one_line_checkpoint"), dict)
        else {}
    )
    closing = (
        generated_briefing.get("closing_sources")
        if isinstance(generated_briefing.get("closing_sources"), dict)
        else {}
    )

    implications = deep.get("key_implications") if isinstance(deep.get("key_implications"), list) else []
    impl_html = "".join(f"<li>{_esc(item)}</li>" for item in implications if str(item).strip())

    deep_sids = deep.get("source_ids") if isinstance(deep.get("source_ids"), list) else []
    deep_sources = _esc(", ".join(str(s) for s in deep_sids))

    source_list = closing.get("source_list") if isinstance(closing.get("source_list"), list) else []
    source_cards: List[str] = []
    for entry in source_list:
        if not isinstance(entry, dict):
            continue
        url = entry.get("url")
        url_line = f'<p class="src-url">{_esc(url)}</p>' if _is_non_empty_str(url) else ""
        tier = entry.get("tier")
        tier_line = f'<p class="src-tier">tier: {_esc(tier)}</p>' if _is_non_empty_str(tier) else ""
        note = entry.get("note")
        note_line = f'<p class="src-note">{_esc(note)}</p>' if _is_non_empty_str(note) else ""
        source_cards.extend(
            [
                '<article class="source-card">',
                f'<p class="src-id"><strong>{_esc(entry.get("source_id"))}</strong></p>',
                f'<p class="src-label">{_esc(entry.get("label"))}</p>',
                url_line,
                tier_line,
                note_line,
                "</article>",
            ]
        )

    return "\n".join(
        [
            f'<section class="card generated-section" id="deep-dive">',
            f"<h2>{_esc(deep.get('section_heading') or SECTION_DEEP_DIVE)}</h2>",
            f'<p class="badge-generated">{_esc(GENERATED_STATUS_REQUIRED)}</p>',
            f'<p class="generated-body">{_esc(deep.get("body"))}</p>',
            "<h3>key_implications</h3>",
            f"<ul>{impl_html}</ul>",
            f'<p class="meta">source_ids: {deep_sources} · confidence: {_esc(deep.get("confidence_label"))}</p>',
            "</section>",
            f'<section class="card generated-section" id="one-line">',
            f"<h2>{_esc(one_line.get('section_heading') or SECTION_ONE_LINE)}</h2>",
            f'<p class="badge-generated">{_esc(GENERATED_STATUS_REQUIRED)}</p>',
            f'<p class="generated-body">{_esc(one_line.get("body"))}</p>',
            "</section>",
            f'<section class="card generated-section" id="closing">',
            f"<h2>{_esc(closing.get('section_heading') or SECTION_CLOSING)}</h2>",
            f'<p class="badge-generated">{_esc(GENERATED_STATUS_REQUIRED)}</p>',
            f'<p class="generated-body">{_esc(closing.get("closing_message"))}</p>',
            "<h3>source_list</h3>",
            *source_cards,
            "</section>",
        ]
    )


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def render_keysuri_review_status_section(
    prompt_input: dict,
    generated_briefing: dict | None = None,
) -> str:
    """Render badges, guardrails, and scheduler summary (no content placeholders)."""
    program_id = str(prompt_input.get("program_id") or "").strip()
    program_display = _esc(PROGRAM_DISPLAY.get(program_id, program_id))

    forbidden = prompt_input.get("forbidden_outputs")
    forbidden_list: List[str] = []
    if isinstance(forbidden, list):
        forbidden_list = [str(x) for x in forbidden if str(x).strip()]
    forbidden_list = forbidden_list + EXTRA_IDENTITY_GUARDRAILS

    forbidden_html = "".join(f"<li>{_esc(item)}</li>" for item in forbidden_list)

    scheduler_html = "".join(
        f"<li><strong>{_esc(name)}</strong> — {_esc(time)}</li>"
        for name, time in ACTIVE_SCHEDULER_ROWS
    )

    cross_forbidden = SECTION_TOP5_KOREA if program_id == "keysuri_global_tech" else SECTION_TOP5_GLOBAL

    gen_status_row = ""
    if generated_briefing is not None:
        gen_status_row = (
            f"<dt>generated_status</dt>"
            f"<dd class='badge'>{_esc(generated_briefing.get('generated_status'))}</dd>"
        )

    return "\n".join(
        [
            '<section class="card status-section" id="status">',
            "<h2>Review Status &amp; Guardrails</h2>",
            "<dl class='badge-dl'>",
            f"<dt>program</dt><dd>{program_display}</dd>",
            f"<dt>prompt_status</dt><dd class='badge'>{_esc(prompt_input.get('prompt_status'))}</dd>",
            gen_status_row,
            f"<dt>operational_status</dt><dd class='badge'>{_esc(prompt_input.get('operational_status'))}</dd>",
            f"<dt>news_scope</dt><dd>{_esc(prompt_input.get('news_scope'))}</dd>",
            f"<dt>output_contract</dt><dd>{_esc(prompt_input.get('output_contract'))}</dd>",
            f"<dt>cross-scope heading forbidden</dt><dd>{_esc(cross_forbidden)}</dd>",
            "</dl>",
            "<h3>Forbidden outputs / guardrails</h3>",
            f"<ul class='forbidden-list'>{forbidden_html}</ul>",
            "<h3>Active scheduler (GENIE)</h3>",
            f"<ul class='scheduler-list'>{scheduler_html}</ul>",
            "</section>",
        ]
    )


def _base_styles() -> str:
    return """
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 32px 24px 48px;
      font-family: "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
      font-size: 15px;
      line-height: 1.65;
      color: #e8eaed;
      background: linear-gradient(160deg, #0f172a 0%, #1e293b 45%, #111827 100%);
    }
    .wrap { max-width: 920px; margin: 0 auto; }
    .card {
      background: #f8f6f0;
      color: #1a1f2e;
      border-radius: 12px;
      padding: 22px 24px;
      margin-bottom: 20px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.25);
    }
    .header-card {
      background: linear-gradient(135deg, #1e3a5f 0%, #0f172a 100%);
      color: #f1f5f9;
      border: 1px solid #94a3b8;
    }
    .header-card h1 { margin: 0 0 6px; font-size: 1.75rem; letter-spacing: -0.02em; }
    .subtitle { margin: 0 0 16px; color: #cbd5e1; font-size: 1rem; }
    .badge-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .badge {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 0.8rem;
      background: #334155;
      color: #e2e8f0;
    }
    .header-card .badge { background: rgba(255,255,255,0.12); }
    .notice {
      background: #fffbeb;
      border-left: 4px solid #b45309;
      padding: 14px 16px;
      margin-bottom: 20px;
      color: #422006;
      border-radius: 0 8px 8px 0;
    }
    .notice ul { margin: 8px 0 0; padding-left: 1.2rem; }
    h2 { margin: 0 0 14px; font-size: 1.2rem; color: #0f172a; border-bottom: 2px solid #cbd5e1; padding-bottom: 8px; }
    .top5-section-heading { color: #1e3a5f; }
    h3.headline { margin: 0; font-size: 1.05rem; flex: 1; }
    .news-card {
      border: 1px solid #d1d5db;
      border-radius: 10px;
      padding: 14px 16px;
      margin-bottom: 12px;
      background: #ffffff;
    }
    .news-card-header { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; }
    .rank { font-weight: 700; color: #1e40af; min-width: 2rem; }
    .muted { color: #64748b; font-size: 0.9rem; }
    .meta { margin: 0 0 12px; font-size: 0.85rem; color: #475569; }
    .audit-dl, .badge-dl { display: grid; grid-template-columns: 180px 1fr; gap: 6px 12px; margin: 0 0 12px; }
    .audit-dl dt, .badge-dl dt { font-weight: 600; color: #475569; }
    .forbidden-list, .scheduler-list { margin: 0; padding-left: 1.2rem; }
    .placeholder-section { border: 2px dashed #94a3b8; background: #f1f5f9; }
    .badge-pending {
      display: inline-block;
      padding: 4px 10px;
      background: #fef3c7;
      color: #92400e;
      border-radius: 6px;
      font-weight: 600;
      font-size: 0.85rem;
    }
    .generated-section { border: 1px solid #cbd5e1; background: #ffffff; }
    .badge-generated {
      display: inline-block;
      padding: 4px 10px;
      background: #dbeafe;
      color: #1e3a8a;
      border-radius: 6px;
      font-weight: 600;
      font-size: 0.85rem;
      margin-bottom: 10px;
    }
    .generated-body { margin: 0 0 12px; }
    .source-card {
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      padding: 10px 12px;
      margin-bottom: 8px;
      background: #f8fafc;
    }
    .error-section {
      background: #fef2f2;
      border: 2px solid #dc2626;
      color: #7f1d1d;
    }
    .footer {
      text-align: center;
      font-size: 0.8rem;
      color: #94a3b8;
      margin-top: 28px;
      padding-top: 16px;
      border-top: 1px solid #334155;
    }
    .footer p { margin: 4px 0; }
    """


def render_keysuri_owner_review_html(
    prompt_input: dict,
    generated_briefing: dict | None = None,
    *,
    preview_mode: PreviewMode = "offline",
) -> str:
    """Render a complete standalone owner-review HTML page from prompt_input."""
    if not isinstance(prompt_input, dict):
        raise ValueError("prompt_input must be a dict")

    program_id = str(prompt_input.get("program_id") or "").strip()
    program_display = _esc(PROGRAM_DISPLAY.get(program_id, program_id))

    if generated_briefing is not None:
        issues = validate_keysuri_generated_briefing(
            program_id, generated_briefing, prompt_input
        )
        if issues:
            messages = "; ".join(
                f"{i.get('code')}: {i.get('message')}" for i in issues[:5]
            )
            raise ValueError(f"Invalid generated briefing for {program_id}: {messages}")

    if preview_mode == "live_smoke":
        notice = """
    <section class="notice" role="note">
      <p><strong>Owner-review 사전 검토 화면</strong></p>
      <ul>
        <li>이 화면은 테크 비서 키수리의 owner-review용 사전 검토 화면입니다.</li>
        <li>아직 고객에게 발송되지 않았습니다.</li>
        <li>Live source smoke preview — public RSS metadata fetch only.</li>
        <li>최종 고객 발송 문안이 아니며 owner-review 검수용입니다.</li>
        <li>프라이빗 테크 비서 톤 — 공개 방송형 브리핑 톤이 아닙니다.</li>
      </ul>
    </section>
    """
    elif generated_briefing is not None:
        notice_extra = (
            "<li>staged sample generated briefing이 로드되었습니다. "
            "최종 고객 발송 문안이 아니며 owner-review 검수용입니다.</li>"
        )
        notice = f"""
    <section class="notice" role="note">
      <p><strong>Owner-review 사전 검토 화면</strong></p>
      <ul>
        <li>이 화면은 테크 비서 키수리의 owner-review용 사전 검토 화면입니다.</li>
        <li>아직 고객에게 발송되지 않았습니다.</li>
        <li>실시간 뉴스 수집 결과가 아니라 staged sample source pack 기반 preview입니다.</li>
        {notice_extra}
        <li>프라이빗 테크 비서 톤 — 공개 방송형 브리핑 톤이 아닙니다.</li>
      </ul>
    </section>
    """
    else:
        notice_extra = "<li>Gemini 호출 전 단계이며 최종 문안이 아닙니다.</li>"
        notice = f"""
    <section class="notice" role="note">
      <p><strong>Owner-review 사전 검토 화면</strong></p>
      <ul>
        <li>이 화면은 테크 비서 키수리의 owner-review용 사전 검토 화면입니다.</li>
        <li>아직 고객에게 발송되지 않았습니다.</li>
        <li>실시간 뉴스 수집 결과가 아니라 staged sample source pack 기반 preview입니다.</li>
        {notice_extra}
        <li>프라이빗 테크 비서 톤 — 공개 방송형 브리핑 톤이 아닙니다.</li>
      </ul>
    </section>
    """

    gen_badge = ""
    if generated_briefing is not None:
        gen_badge = (
            f'<span class="badge">generated_status: '
            f'{_esc(generated_briefing.get("generated_status"))}</span>'
        )

    header = f"""
    <header class="card header-card">
      <h1>{IDENTITY_TITLE}</h1>
      <p class="subtitle">{IDENTITY_SUBTITLE}</p>
      <p class="program-line"><strong>Program:</strong> {program_display}</p>
      <div class="badge-row">
        <span class="badge">operational_status: {_esc(prompt_input.get('operational_status'))}</span>
        <span class="badge">prompt_status: {_esc(prompt_input.get('prompt_status'))}</span>
        {gen_badge}
        <span class="badge">news_scope: {_esc(prompt_input.get('news_scope'))}</span>
        <span class="badge">prompt_profile: {_esc(prompt_input.get('prompt_profile'))}</span>
      </div>
    </header>
    """

    if preview_mode == "live_smoke":
        footer = """
    <footer class="footer">
      <p>Owner Review Preview</p>
      <p>Live source smoke · review_required · No email sent</p>
      <p>Private Tech Secretary Preview</p>
    </footer>
    """
    else:
        footer = """
    <footer class="footer">
      <p>Owner Review Preview</p>
      <p>No email sent · No live fetch · No Gemini call</p>
      <p>review_required · Private Tech Secretary Preview</p>
    </footer>
    """

    body_parts = [
        render_keysuri_top5_section(prompt_input),
        render_keysuri_source_audit_section(prompt_input),
        render_keysuri_review_status_section(prompt_input, generated_briefing),
    ]
    if generated_briefing is not None:
        body_parts.append(render_keysuri_generated_sections(generated_briefing))
    else:
        body_parts.append(
            render_keysuri_placeholder_sections(prompt_input, preview_mode=preview_mode)
        )

    body = "\n".join(body_parts)

    return (
        "<!DOCTYPE html>\n<html lang=\"ko\">\n<head>\n"
        "<meta charset=\"utf-8\"/>\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"/>\n"
        "<title>"
        + _esc(IDENTITY_TITLE)
        + " — Owner Review Preview</title>\n"
        "<style>"
        + _base_styles()
        + "</style>\n</head>\n<body>\n<div class=\"wrap\">\n"
        + header
        + notice
        + body
        + footer
        + "\n</div>\n</body>\n</html>"
    )
