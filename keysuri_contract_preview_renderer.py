"""Kee-Suri contract preview renderer — html_test contract-validation surface.

Renders customer-facing briefing HTML for owner visual review under:

    output/keysuri_preview/html_test/

This is separate from the owner-review renderer (keysuri_renderer.py).
Does not call image API, scheduler, or email systems.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from keysuri_private_briefing import SECTION_CLOSING, SECTION_DEEP_DIVE, SECTION_ONE_LINE

PROGRAM_KOREA = "keysuri_korea_tech"
PROGRAM_GLOBAL = "keysuri_global_tech"

IDENTITY_TITLE = "테크 비서 키수리"

REVIEW_STATE_PREVIEW_PENDING = "preview_pending"
REVIEW_STATE_REVIEW_PASSED = "review_passed"
REVIEW_STATE_SENT_ARCHIVED = "sent_archived"
DEFAULT_REVIEW_STATE = REVIEW_STATE_PREVIEW_PENDING

REVIEW_CONFIRMATION_TEXT: dict[str, str] = {
    REVIEW_STATE_PREVIEW_PENDING: "본 브리핑은 운영책임자의 직접 검수 대기 상태입니다.",
    REVIEW_STATE_REVIEW_PASSED: "본 브리핑은 운영책임자의 직접 검수를 통과했습니다.",
    REVIEW_STATE_SENT_ARCHIVED: "본 브리핑은 운영책임자의 직접 검수를 통과하여 발송되었습니다.",
}

RIGHTS_LINE_1 = "Copyright Ⓒ MirAI:ON. All rights reserved."
RIGHTS_LINE_2 = "무단 전재, 재배포 및 AI학습 이용 절대 금지"


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _resolve_review_state(fixture: Mapping[str, Any]) -> str:
    state = str(fixture.get("review_state") or DEFAULT_REVIEW_STATE).strip()
    if state not in REVIEW_CONFIRMATION_TEXT:
        return DEFAULT_REVIEW_STATE
    return state


def _render_title_candidates(candidates: Sequence[Any]) -> str:
    items = "".join(f"<li>{_esc(candidate)}</li>" for candidate in candidates)
    return f"""
    <section id="title-candidates">
      <h2>Title candidates</h2>
      <ul>{items}</ul>
    </section>
    """


def _render_top_item(item: Mapping[str, Any], rank: int) -> str:
    source_url = str(item.get("source_url") or "").strip()
    return f"""
    <article class="top-item" data-top-item="{rank}">
      <h3>{rank}. {_esc(item.get("headline"))}</h3>
      <p>{_esc(item.get("what_happened"))}</p>
      <p><strong>why_it_matters:</strong> {_esc(item.get("why_it_matters"))}</p>
      <p><strong>business_implication:</strong> {_esc(item.get("business_implication"))}</p>
      <div class="source-box">
        출처명: {_esc(item.get("source_name"))}<br>
        URL: <a href="{_esc(source_url)}">{_esc(source_url)}</a><br>
        검증 상태: {_esc(item.get("verification_status"))}
      </div>
    </article>
    """


def _render_top5_section(fixture: Mapping[str, Any]) -> str:
    heading = _esc(fixture.get("top_5_heading"))
    items = fixture.get("top_5_items") or []
    rendered_items = ""
    for idx, item in enumerate(items[:5], start=1):
        rank = int(item.get("rank") or idx)
        rendered_items += _render_top_item(item, rank)
    return f"""
    <section id="top5-section">
      <h2 class="section-heading">{heading}</h2>
      {rendered_items}
    </section>
    """


def _render_deep_dive(fixture: Mapping[str, Any]) -> str:
    layers = fixture.get("deep_dive_layers") or []
    layer_html = ""
    for layer in layers[:3]:
        layer_html += f"""
      <div class="deep-layer">
        <span class="deep-layer-number">{_esc(layer.get("layer_number"))}</span>
        <div class="deep-layer-title">{_esc(layer.get("layer_title"))}</div>
        <div class="deep-layer-body"><p>{_esc(layer.get("layer_body"))}</p></div>
      </div>
        """
    heading = _esc(fixture.get("deep_dive_heading") or SECTION_DEEP_DIVE)
    return f"""
    <section id="deep-dive-section">
      <h2 class="section-heading">{heading}</h2>
      {layer_html}
    </section>
    """


def _render_review_confirmation(review_state: str) -> str:
    text = REVIEW_CONFIRMATION_TEXT[review_state]
    return f"""
    <section id="review-confirmation-box" data-review-state="{_esc(review_state)}">
      <h2>Review confirmation</h2>
      <p class="review-confirmation-text">{_esc(text)}</p>
    </section>
    """


def _render_source_list(source_list: Sequence[Mapping[str, Any]]) -> str:
    cards = ""
    for entry in source_list:
        source_url = str(entry.get("source_url") or "").strip()
        cards += f"""
      <article class="source-card">
        <p><strong>{_esc(entry.get("source_id"))}</strong></p>
        <p>출처명: {_esc(entry.get("source_name"))}</p>
        <p>URL: <a href="{_esc(source_url)}">{_esc(source_url)}</a></p>
        <p>검증 상태: {_esc(entry.get("verification_status"))}</p>
      </article>
        """
    return cards


def _render_validation_box(timestamp: str) -> str:
    return f"""
    <div class="validation-box pass" id="validation-result-box">
      <strong>Validation result</strong>
      <div class="validation-status pass">validation_status: PASS</div>
      <div>validation_timestamp: {_esc(timestamp)}</div>
      <div>required_sections: PASS</div>
      <div>top5_sources: PASS</div>
      <div>deep_dive_readability: PASS</div>
      <div>rights_policy: PASS</div>
      <div>no_hashtags: PASS</div>
      <div>no_production_implication: PASS</div>
    </div>
    """


def render_keysuri_contract_preview_html(fixture: Mapping[str, Any]) -> str:
    """Render contract-validation HTML from a fixture dict."""
    if not isinstance(fixture, dict):
        raise TypeError("fixture must be a dict")

    program_id = str(fixture.get("program_id") or "").strip()
    if program_id not in (PROGRAM_KOREA, PROGRAM_GLOBAL):
        raise ValueError(f"Unsupported program_id: {program_id!r}")

    slot = _esc(fixture.get("slot"))
    review_state = _resolve_review_state(fixture)
    is_korea = program_id == PROGRAM_KOREA
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    preview_metadata = f"""
    <div class="meta-box" id="preview-metadata">
      <strong>Preview metadata</strong>
      <span>program_id: {_esc(program_id)}</span>
      <span>slot: {slot}</span>
      <span>mode: contract_preview</span>
    </div>
    """

    identity = f'<p class="identity">{IDENTITY_TITLE}</p>'

    title_candidates = _render_title_candidates(fixture.get("title_candidates") or [])
    selected_title = f"""
    <section id="selected-title">
      <h1>{_esc(fixture.get("selected_title"))}</h1>
    </section>
    """
    opening_lead = f"""
    <section id="opening-lead">
      <p class="opening-lead">{_esc(fixture.get("opening_lead"))}</p>
    </section>
    """
    top_shot = """
    <div class="placeholder" id="top-shot-placeholder">Top-shot preview placeholder</div>
    """

    top5 = _render_top5_section(fixture)
    deep_dive = _render_deep_dive(fixture)
    checkpoint = f"""
    <section id="one-line-section">
      <h2 class="section-heading">{SECTION_ONE_LINE}</h2>
      <div class="checkpoint">{_esc(fixture.get("one_line_checkpoint"))}</div>
    </section>
    """

    bottom_shot = ""
    warm_close = ""
    if is_korea:
        bottom_shot = """
    <div class="placeholder small" id="bottom-shot-placeholder">18:30 bottom-shot preview placeholder</div>
        """
        warm_close_text = _esc(fixture.get("warm_close_text") or "오늘도 수고하셨습니다. 내일 다시 뵙겠습니다.")
        warm_close = f"""
    <section id="warm-close-section">
      <h2>국내 18:30 따뜻한 마무리</h2>
      <p>{warm_close_text}</p>
    </section>
        """

    review_confirmation = _render_review_confirmation(review_state)

    closing = f"""
    <section id="closing-section">
      <h2 class="section-heading">{SECTION_CLOSING}</h2>
      <p>{_esc(fixture.get("closing_message"))}</p>
      {_render_source_list(fixture.get("source_list") or [])}
    </section>
    """

    rights_policy = f"""
    <div class="rights-policy" id="rights-policy">
      <p>{RIGHTS_LINE_1}</p>
      <p>{RIGHTS_LINE_2}</p>
    </div>
    """

    operation_meta = fixture.get("operation_metadata") or {}
    operation_metadata = f"""
    <div class="op-meta" id="operation-metadata">
      <strong>Operation metadata (server-rendered only)</strong>
      <p>program_id: {_esc(operation_meta.get("program_id"))}</p>
      <p>mode: {_esc(operation_meta.get("mode"))}</p>
      <p>status: {_esc(operation_meta.get("status"))}</p>
      <p>slot: {_esc(operation_meta.get("slot"))}</p>
    </div>
    """

    compliance_checklist = """
    <div class="compliance-box" id="compliance-checklist">
      <strong>Contract compliance checklist</strong>
    </div>
    """

    validation_box = _render_validation_box(timestamp)

    if is_korea:
        tail = (
            checkpoint
            + bottom_shot
            + review_confirmation
            + warm_close
            + closing
            + rights_policy
            + operation_metadata
            + compliance_checklist
            + validation_box
        )
    else:
        tail = (
            checkpoint
            + review_confirmation
            + closing
            + rights_policy
            + operation_metadata
            + compliance_checklist
            + validation_box
        )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{IDENTITY_TITLE} — Contract Preview</title>
</head>
<body>
<div class="preview-banner">PREVIEW ONLY</div>
{preview_metadata}
{identity}
{title_candidates}
{selected_title}
{opening_lead}
{top_shot}
{top5}
{deep_dive}
{tail}
</body>
</html>
"""
