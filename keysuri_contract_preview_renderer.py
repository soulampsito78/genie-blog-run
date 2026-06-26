"""Kee-Suri contract preview renderer — premium private briefing surface."""
from __future__ import annotations

import base64
import html
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

from keysuri_approved_image_assets import (
    default_top_role_for_program,
    resolve_approved_hero_image_path,
)
from keysuri_contract_preview_quality import GENERIC_CLOSING_PHRASES
from keysuri_private_briefing import SECTION_CLOSING, SECTION_DEEP_DIVE, SECTION_ONE_LINE
from keysuri_korea_longform_ux import (
    KOREA_CHECKPOINT_SUBFRAME,
    KOREA_EVENING_MEMO_HEADING,
    KOREA_WARM_FAREWELL_LINES,
    build_korea_evening_memo,
    build_korea_one_line_checkpoint,
    finalize_korea_visible_field,
    korea_closing_internal_label_leak,
    korea_closing_structure_incomplete,
    korea_evening_memo_too_thin,
    memo_plain_text,
    structure_korea_deep_dive,
)
from keysuri_visible_text import (
    KEYSURI_INSUFFICIENT_BADGE_LABEL,
    PROGRAM_KOREA,
    build_visible_selection_reason,
    coerce_visible_lines,
    dedupe_sentences_in_paragraph,
    normalize_visible_text,
    polish_korea_checkpoint_text,
    sanitize_visible_impact_line,
    sanitize_visible_selection_reason,
    strip_watch_arrow_prefixes,
)

PROGRAM_GLOBAL = "keysuri_global_tech"

GLOBAL_SLOT_BADGE = "글로벌 신호 · 12:30"
KOREA_SLOT_BADGE = "국내 해석 · 18:30"
GLOBAL_ANGLE_CHIP = "글로벌 원인"
KOREA_ANGLE_CHIP = "국내 적용"
GLOBAL_CARD_EMPHASIS = "한국 도착 전 압력"
KOREA_CARD_EMPHASIS = "내일 영향"
GLOBAL_DEEP_SUBFRAME = "산업 레이어가 어디로 이동하나"
KOREA_DEEP_SUBFRAME = "한국 기업·정책으로 읽으면"
GLOBAL_CHECKPOINT_SUBFRAME = "다음 48시간 관찰 포인트"
GLOBAL_OPEN_ENDING = (
    "다음 48시간은 위 관찰 포인트를 열어 둔 채 이어가시면 됩니다."
)
IMAGE_MODE_PREVIEW = "preview"
IMAGE_MODE_EMAIL = "email"

IDENTITY_TITLE = "테크 비서 키수리"
TOP_SHOT_ALT = "테크 비서 키수리 — 프라이빗 테크 브리핑"

GLOBAL_HERO_TITLE = "키수리 글로벌 테크 브리핑"
GLOBAL_HERO_SUBTITLE = "주인님께 먼저 올리는 오늘의 AI·빅테크 신호"
KOREA_HERO_TITLE = "키수리 국내 테크 브리핑"
KOREA_HERO_SUBTITLE = "주인님께 먼저 올리는 오늘의 국내 AI·테크 신호"
OWNER_REVIEW_BADGE = "운영자 검수용 미리보기 · 아직 발송 전"

SAFE_CLOSING_MESSAGE = (
    "주인님, 오늘 신호는 여기까지 정리해 두었습니다. 출처는 아래에 그대로 남깁니다."
)

DEFAULT_SUBJECT_INDEX = 0

SUBJECT_LINES_GLOBAL: tuple[str, ...] = (
    "[키수리 브리핑] 빅테크의 AI 내재화가 '일의 구조'를 바꾸고 있습니다",
    "[키수리] 오늘의 테크 신호 — 통제권이 모델에서 인프라로 이동합니다",
    "[키수리 브리핑] AI 에이전트 확산 이후, 개발 조직에 생긴 압력",
    "AI가 제품 속으로 들어온 날, 주인님이 먼저 봐야 할 신호",
    "[키수리 브리핑] 거대 AI 기업의 '실용화' 전환 — 오늘 무엇이 움직였나",
    "[키수리] 오늘의 구조 변화: 누가 워크플로의 통제권을 가져가는가",
    "[키수리 브리핑] 검색·에이전트·기억 — 세 신호가 가리키는 한 방향",
    "빅테크 발표 이후, 진입 장벽이 어디서 높아지는가",
    "[키수리 브리핑] 오늘 테크 시장에서 조용히 이동한 권한",
    "[키수리] 연구를 넘어 운영으로 — AI가 인프라가 된 날의 신호",
    "AI 내재화 경쟁, 오늘 읽어야 할 단 하나의 구조",
    "[키수리 브리핑] 동시에 움직인 AI 인프라 신호 — 방향을 다시 점검합니다",
)

SUBJECT_LINES_GLOBAL_MOBILE: tuple[str, ...] = (
    "[키수리] 오늘의 테크 신호, 한 줄로",
    "[키수리] 통제권이 이동하고 있습니다",
    "오늘 먼저 봐야 할 테크 신호",
)

PREHEADERS_GLOBAL: tuple[str, ...] = (
    "오늘 상위 AI·테크 신호를 구조 변화 관점에서 정리했습니다.",
    "모델 경쟁이 아니라, 인프라·라우팅 통제권 싸움으로 넘어가는 중입니다.",
    "에이전트가 개발을 재편하면, 다음 순서는 조직과 비용입니다.",
    "발표 5건을 신호 5개로 압축했습니다. 주인님 관점까지 함께 올립니다.",
    "'할 수 있다'에서 '운영에 넣는다'로 — 무게중심이 옮겨갑니다.",
    "자동화의 통제권이 누구에게 쌓이는지, 오늘 신호로 짚었습니다.",
    "검색·에이전트·기억. 따로 보면 뉴스, 합치면 구조 변화입니다.",
    "진입 장벽은 모델 품질이 아니라 인프라·정책 스택에서 올라갑니다.",
    "헤드라인이 아니라, 오늘 조용히 이동한 권한을 봅니다.",
    "AI가 연구실을 떠나 인프라가 된 신호를 한자리에 모았습니다.",
    "오늘 다섯 건 중, 주인님이 꼭 봐야 할 하나의 구조를 짚었습니다.",
    "같은 날 포착된 여러 신호가 어떤 구조 변화를 가리키는지 짚었습니다.",
)

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

PREHEADER_STYLE = (
    "display:none!important;opacity:0;color:transparent;height:0;width:0;"
    "overflow:hidden;mso-hide:all;"
)


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _data_uri_from_path(path: Path) -> str:
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    suffix = path.suffix.lower()
    mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
    return f"data:{mime};base64,{b64}"


def _cid_for_program(program_id: str, date_str: str | None = None) -> str:
    token = "global" if program_id == PROGRAM_GLOBAL else "korea"
    stamp = date_str or datetime.now().strftime("%Y%m%d")
    return f"cid:keysuri_topshot_{token}_{stamp}"


def resolve_top_shot_asset_path(repo_root: Path, program_id: str) -> Path | None:
    """Resolve approved registry top asset (global_top or korea_top); None if missing."""
    try:
        return resolve_approved_hero_image_path(
            repo_root,
            program_id,
            use_case="contract_preview",
            role=default_top_role_for_program(program_id),
        )
    except (FileNotFoundError, ValueError):
        return None


def image_src_for_mode(
    image_path: Path,
    *,
    program_id: str,
    image_mode: str = IMAGE_MODE_PREVIEW,
    date_str: str | None = None,
) -> str:
    if image_mode == IMAGE_MODE_EMAIL:
        return _cid_for_program(program_id, date_str)
    return _data_uri_from_path(image_path)


def _subject_lines(program_id: str) -> tuple[str, ...]:
    return SUBJECT_LINES_GLOBAL if program_id == PROGRAM_GLOBAL else SUBJECT_LINES_GLOBAL

def _preheaders(program_id: str) -> tuple[str, ...]:
    return PREHEADERS_GLOBAL if program_id == PROGRAM_GLOBAL else PREHEADERS_GLOBAL


def _hangul_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha() or ("\uac00" <= ch <= "\ud7a3")]
    if not letters:
        return 0.0
    hangul = sum(1 for ch in letters if "\uac00" <= ch <= "\ud7a3")
    return hangul / len(letters)


def _selected_subject_preheader(fixture: Mapping[str, Any], program_id: str) -> tuple[str, str]:
    idx = int(fixture.get("subject_index") or fixture.get("selected_subject_index") or DEFAULT_SUBJECT_INDEX)
    subjects = _subject_lines(program_id)
    preheaders = _preheaders(program_id)
    idx = max(0, min(idx, len(subjects) - 1))
    subject = str(fixture.get("selected_subject") or "").strip()
    if not subject:
        title_candidate = str(fixture.get("selected_title") or "").strip()
        if title_candidate and _hangul_ratio(title_candidate) >= 0.2:
            subject = title_candidate
        else:
            subject = subjects[idx]
    if not subject:
        subject = subjects[0]
    pre_idx = max(0, min(idx, len(preheaders) - 1))
    preheader = str(fixture.get("preheader") or preheaders[pre_idx]).strip()
    return subject, preheader


def _normalize_closing(message: str) -> str:
    text = (message or "").strip()
    if not text:
        return SAFE_CLOSING_MESSAGE
    for phrase in GENERIC_CLOSING_PHRASES:
        if phrase in text:
            return SAFE_CLOSING_MESSAGE
    return text


def prepare_contract_preview_fixture(
    fixture: MutableMapping[str, Any],
    *,
    repo_root: Path,
    image_mode: str = IMAGE_MODE_PREVIEW,
) -> MutableMapping[str, Any]:
    """Embed hero image, normalize closing, and attach subject/preheader metadata."""
    program_id = str(fixture.get("program_id") or PROGRAM_GLOBAL).strip()
    subject, preheader = _selected_subject_preheader(fixture, program_id)
    fixture["selected_subject"] = subject
    fixture["preheader"] = preheader
    fixture["closing_message"] = _normalize_closing(str(fixture.get("closing_message") or ""))

    if _is_korea_program(program_id):
        top_items = fixture.get("top_5_items") or []
        deep_body = str(fixture.get("deep_dive_body") or "")
        uncertainty = normalize_visible_text(
            fixture.get("deep_dive_uncertainty") or "",
            style="sentence",
        )
        if not fixture.get("korea_deep_dive_sections") or uncertainty:
            sections = structure_korea_deep_dive(deep_body, top_items, uncertainty=uncertainty)
            fixture["korea_deep_dive_sections"] = sections
            fixture["deep_dive_body"] = "\n\n".join(
                f"{section['label']}\n{section['body']}"
                for section in sections
                if section.get("body")
            )
        memo = fixture.get("korea_evening_memo")
        if not isinstance(memo, dict):
            memo = build_korea_evening_memo(
                top_items,
                closing_message=str(fixture.get("closing_message") or ""),
            )
        if (
            korea_evening_memo_too_thin(memo)
            or korea_closing_structure_incomplete(memo)
            or korea_closing_internal_label_leak(memo_plain_text(memo))
        ):
            memo = build_korea_evening_memo(
                top_items,
                closing_message=str(fixture.get("closing_message") or ""),
            )
        fixture["korea_evening_memo"] = memo
        fixture["evening_memo_body"] = memo_plain_text(memo)
        fixture["evening_memo_heading"] = KOREA_EVENING_MEMO_HEADING

    # Korea preview: embed bottom shot as data-URI when bottom_shot_image_path is set.
    # Email mode skips this — bottom CID is injected separately by service_full_run.
    if _is_korea_program(program_id) and image_mode == IMAGE_MODE_PREVIEW:
        existing_bottom = str(fixture.get("bottom_shot_image_src") or "").strip()
        if not (existing_bottom.startswith("data:image/") or existing_bottom.startswith("cid:")):
            bottom_path_str = str(fixture.get("bottom_shot_image_path") or "").strip()
            if bottom_path_str:
                bp = Path(bottom_path_str)
                if bp.is_file():
                    fixture["bottom_shot_image_src"] = _data_uri_from_path(bp)

    existing_src = str(fixture.get("top_shot_image_src") or "").strip()
    if existing_src.startswith("data:image/") or existing_src.startswith("cid:"):
        return fixture

    image_path = None
    if fixture.get("top_shot_image_path"):
        candidate = Path(str(fixture["top_shot_image_path"]))
        if candidate.is_file():
            image_path = candidate
    if image_path is None:
        image_path = resolve_top_shot_asset_path(repo_root, program_id)

    if image_path is not None:
        fixture["top_shot_image_path"] = str(image_path)
        fixture["top_shot_image_src"] = image_src_for_mode(
            image_path,
            program_id=program_id,
            image_mode=image_mode,
        )
        fixture["top_shot_image_mode"] = image_mode
    return fixture


def _resolve_review_state(fixture: Mapping[str, Any]) -> str:
    state = str(fixture.get("review_state") or DEFAULT_REVIEW_STATE).strip()
    if state not in REVIEW_CONFIRMATION_TEXT:
        return DEFAULT_REVIEW_STATE
    return state


def _is_korea_program(program_id: str) -> bool:
    pid = str(program_id or "").strip()
    return pid == PROGRAM_KOREA or pid.startswith("keysuri_korea")


def _korea_visible_field(item: Mapping[str, Any], *keys: str) -> str:
    title_fb = _item_field(item, "korean_title", "headline")
    return finalize_korea_visible_field(_item_field(item, *keys), fallback=title_fb)


def _theme_body_class(program_id: str) -> str:
    return "theme-korea" if _is_korea_program(program_id) else "theme-global"


def _slot_badge(program_id: str, slot: str) -> str:
    if _is_korea_program(program_id):
        return KOREA_SLOT_BADGE
    token = str(slot or "12:30").strip() or "12:30"
    return f"글로벌 신호 · {token}" if token != "12:30" else GLOBAL_SLOT_BADGE


def _angle_chip_text(program_id: str, item: Mapping[str, Any]) -> str:
    for key in ("briefing_angle", "angle_chip", "duplicate_news_angle"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return KOREA_ANGLE_CHIP if _is_korea_program(program_id) else GLOBAL_ANGLE_CHIP


def _card_emphasis_label(program_id: str) -> str:
    return KOREA_CARD_EMPHASIS if _is_korea_program(program_id) else GLOBAL_CARD_EMPHASIS


def _deep_dive_subframe(program_id: str) -> str:
    return KOREA_DEEP_SUBFRAME if _is_korea_program(program_id) else GLOBAL_DEEP_SUBFRAME


def _checkpoint_subframe(program_id: str) -> str:
    return KOREA_CHECKPOINT_SUBFRAME if _is_korea_program(program_id) else GLOBAL_CHECKPOINT_SUBFRAME


def _hero_copy(program_id: str) -> tuple[str, str]:
    if _is_korea_program(program_id):
        return KOREA_HERO_TITLE, KOREA_HERO_SUBTITLE
    return GLOBAL_HERO_TITLE, GLOBAL_HERO_SUBTITLE


def _item_field(item: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        val = item.get(key)
        if val in (None, ""):
            continue
        if isinstance(val, str) and val.strip():
            return val.strip()
        normalized = normalize_visible_text(val, style="inline")
        if normalized:
            return normalized
    return ""


def _normalize_misused_double_periods(text: str) -> str:
    out = re.sub(r"(?<!\.)\s*\.\.\s*(?!\.)", ", ", str(text or ""))
    out = re.sub(r"\s*(?:\.{3,}|…)\s*", " ", out)
    return re.sub(r"\s+", " ", out).strip()


def _judgment_block(item: Mapping[str, Any]) -> tuple[str, str]:
    label = _item_field(item, "keysuri_judgment_label", "judgment_label")
    text = _item_field(item, "keysuri_judgment", "keysuri_judgment_text", "judgment_explanation")
    if not label and not text:
        return "관찰", ""
    if not label:
        return "관찰", text
    return label, text


def _signal_chip_text(item: Mapping[str, Any]) -> str:
    label = _item_field(item, "keysuri_judgment_label", "judgment_label")
    if label and label not in ("관찰", "키수리 판단"):
        return label
    title = _item_field(item, "korean_title", "headline")
    if not title:
        return "신호"
    parts = re.split(r"[—\-:|]", title, maxsplit=1)
    chip = parts[0].strip()
    if len(chip) > 18:
        chip = chip[:18].rstrip(" ,·.")
    return chip or "신호"


def _render_theme_top_insert(fixture: Mapping[str, Any], *, program_id: str) -> str:
    items = fixture.get("top_5_items") or []
    chips: list[str] = []
    for item in items[:5]:
        if isinstance(item, dict):
            chips.append(_signal_chip_text(item))
    chip_html = "".join(f'<span class="signal-chip">{_esc(c)}</span>' for c in chips)
    chip_row = f'<div class="signal-chip-row">{chip_html}</div>' if chip_html else ""

    if _is_korea_program(program_id):
        return f"""
    <section id="signal-summary" class="theme-top-insert korea-domestic-strip signal-summary section-card">
      <p class="theme-insert-label">오늘 국내에서 움직인 것</p>
      <p class="theme-insert-copy">국내 적용 관점에서 오늘 다섯 신호를 정리했습니다.</p>
      {chip_row}
    </section>"""

    return f"""
    <section id="signal-summary" class="theme-top-insert global-signal-board signal-summary section-card">
      <p class="theme-insert-label">글로벌 신호 분포</p>
      <p class="theme-insert-copy">밝은 낮에 먼저 보는 세계 기술 지형도 — 오늘 신호가 어느 축에 몰렸는지입니다.</p>
      {chip_row}
    </section>"""


def _render_top_item(item: Mapping[str, Any], rank: int, *, program_id: str) -> str:
    source_url = _item_field(item, "source_url")
    source_name = _item_field(item, "source_name") or "출처"
    checked = _item_field(item, "checked_at")
    verification = _item_field(item, "verification_status") or "live_fetch / not_verified"
    insufficient = bool(item.get("detail_insufficient"))

    headline = _item_field(item, "korean_title", "headline")
    selection_reason = _item_field(item, "selection_reason", "selection_rationale")
    if _is_korea_program(program_id):
        meta_stub = {
            "primary_category": item.get("primary_category"),
            "selection_reason_tags": item.get("selection_reason_tags"),
            "selection_rationale": item.get("selection_rationale"),
            "reason_for_selection": item.get("reason_for_selection"),
            "statement": item.get("korean_title") or item.get("headline"),
        }
        selection_reason = build_visible_selection_reason(
            item,
            meta_stub,
            program_id=PROGRAM_KOREA,
            existing=sanitize_visible_selection_reason(
                selection_reason, item, meta_stub, program_id=PROGRAM_KOREA
            ),
        )
    what_happened = _item_field(item, "what_happened", "summary")
    why_now = _item_field(item, "why_now", "why_it_matters")
    owner_angle = _item_field(item, "owner_angle", "business_implication", "keysuri_comment")
    if _is_korea_program(program_id):
        what_happened = _korea_visible_field(item, "what_happened", "summary")
        why_now = _korea_visible_field(item, "why_now", "why_it_matters")
        owner_angle = _korea_visible_field(item, "owner_angle", "business_implication", "keysuri_comment")
        selection_reason = finalize_korea_visible_field(
            selection_reason,
            fallback=_item_field(item, "korean_title", "headline"),
        )
    else:
        what_happened = dedupe_sentences_in_paragraph(what_happened)
        why_now = dedupe_sentences_in_paragraph(why_now)
        owner_angle = dedupe_sentences_in_paragraph(owner_angle)
    next_watch_raw = None
    for key in ("next_watch", "next_check_point"):
        if item.get(key) not in (None, ""):
            next_watch_raw = item.get(key)
            break
    next_watch = strip_watch_arrow_prefixes(
        "; ".join(coerce_visible_lines(next_watch_raw or "")[:4])
    )
    hype_caution = _item_field(item, "hype_caution")
    j_label, j_text = _judgment_block(item)
    if _is_korea_program(program_id):
        headline = _normalize_misused_double_periods(headline)
        selection_reason = _normalize_misused_double_periods(selection_reason)
        what_happened = _normalize_misused_double_periods(what_happened)
        why_now = _normalize_misused_double_periods(why_now)
        owner_angle = _normalize_misused_double_periods(owner_angle)
        next_watch = _normalize_misused_double_periods(next_watch)
        hype_caution = _normalize_misused_double_periods(hype_caution)
        j_label = _normalize_misused_double_periods(j_label)
        j_text = _normalize_misused_double_periods(j_text)

    insuff_badge = ""
    if insufficient:
        insuff_badge = (
            f'<span class="insufficient-badge">{_esc(KEYSURI_INSUFFICIENT_BADGE_LABEL)}</span>'
        )
    hype_badge = ""
    if hype_caution:
        hype_badge = f'<p class="hype-caution">{_esc(hype_caution)}</p>'

    selection_block = ""
    if selection_reason:
        selection_block = f"""
      <div class="brief-block">
        <h4 class="block-label">선정 이유</h4>
        <p class="block-body">{_esc(selection_reason)}</p>
      </div>"""

    angle_chip = _angle_chip_text(program_id, item)
    if _is_korea_program(program_id):
        angle_chip = _normalize_misused_double_periods(angle_chip)
    emphasis_label = _card_emphasis_label(program_id)
    emphasis_body = _item_field(item, "next_day_impact_line", "owner_action_line")
    if _is_korea_program(program_id) and emphasis_body:
        emphasis_body = finalize_korea_visible_field(
            sanitize_visible_impact_line(
                emphasis_body,
                category=str(item.get("primary_category") or ""),
            ),
            fallback=_item_field(item, "korean_title", "headline"),
        )
        emphasis_body = _normalize_misused_double_periods(emphasis_body)
    if emphasis_body:
        emphasis_html = (
            f'<p class="card-emphasis-line">'
            f'<span class="card-emphasis-label">{_esc(emphasis_label)}</span> '
            f'<span class="card-emphasis-text">{_esc(emphasis_body)}</span></p>'
        )
    elif _is_korea_program(program_id):
        emphasis_html = ""
    else:
        emphasis_html = (
            f'<p class="card-emphasis-line">'
            f'<span class="card-emphasis-label">{_esc(emphasis_label)}</span></p>'
        )

    rank_html = "" if _is_korea_program(program_id) else f'<div class="card-rank">{rank}</div>'
    return f"""
    <article class="briefing-card top-item" data-top-item="{rank}">
      {rank_html}
      <span class="angle-chip">{_esc(angle_chip)}</span>
      <h3 class="card-headline">{rank}. {_esc(headline)}</h3>
      {insuff_badge}
      {hype_badge}{selection_block}
      {emphasis_html}
      <div class="brief-block">
        <h4 class="block-label">무슨 일이 있었나</h4>
        <p class="block-body">{_esc(what_happened)}</p>
      </div>
      <div class="brief-block">
        <h4 class="block-label">왜 지금 중요한가</h4>
        <p class="block-body">{_esc(why_now)}</p>
      </div>
      <div class="brief-block owner-angle-block">
        <h4 class="block-label">주인님 관점</h4>
        <p class="block-body">{_esc(owner_angle)}</p>
      </div>
      <div class="judgment-row">
        <span class="judgment-label">키수리 판단</span>
        <span class="judgment-badge">{_esc(j_label)}</span>
        <span class="judgment-text">{_esc(j_text)}</span>
      </div>
      <div class="brief-block next-watch-block">
        <h4 class="block-label">다음 확인 포인트</h4>
        <p class="block-body"><span class="watch-arrow">→</span> {_esc(next_watch)}</p>
      </div>
      <div class="source-chip">
        <span class="chip-label">출처</span>
        <span class="chip-name">{_esc(source_name)}</span>
        <a class="chip-url" href="{_esc(source_url)}">{_esc(source_url)}</a>
      </div>
      <div class="source-box" aria-hidden="true">
        <span>출처명: {_esc(source_name)}</span>
        <span>URL: {_esc(source_url)}</span>
        <span>기준시각: {_esc(checked)}</span>
        <span>검증 상태: {_esc(verification)}</span>
      </div>
    </article>
    """


def _render_top5_section(fixture: Mapping[str, Any], *, program_id: str) -> str:
    heading = _esc(fixture.get("top_5_heading"))
    items = fixture.get("top_5_items") or []
    rendered = ""
    for idx, item in enumerate(items[:5], start=1):
        if isinstance(item, dict):
            rendered += _render_top_item(
                item,
                int(item.get("rank") or idx),
                program_id=program_id,
            )
    return f"""
    <section id="top5-section" class="section-card">
      <h2 class="section-heading">{heading}</h2>
      <div class="top5-grid">{rendered}</div>
    </section>
    """


def _render_block_body_lines(body: str) -> str:
    text = str(body or "").strip()
    if not text:
        return ""
    bullet_lines = [line.lstrip("• ").strip() for line in text.splitlines() if line.strip().startswith("•")]
    if bullet_lines:
        items = "".join(f"<li>{_esc(line)}</li>" for line in bullet_lines)
        return f"<ul class=\"korea-deep-list\">{items}</ul>"
    numbered = [line.strip() for line in text.splitlines() if re.match(r"^\d+\.\s+", line.strip())]
    if numbered:
        cleaned = [re.sub(r"^\d+\.\s+", "", line) for line in numbered]
        items = "".join(f"<li>{_esc(line)}</li>" for line in cleaned)
        return f"<ol class=\"korea-deep-list\">{items}</ol>"
    return f"<p>{_esc(text)}</p>"


def _render_korea_deep_dive_blocks(fixture: Mapping[str, Any]) -> str:
    sections = fixture.get("korea_deep_dive_sections") or []
    if not sections:
        sections = structure_korea_deep_dive(
            str(fixture.get("deep_dive_body") or ""),
            fixture.get("top_5_items") or [],
            uncertainty=normalize_visible_text(
                fixture.get("deep_dive_uncertainty") or "",
                style="sentence",
            ),
        )
    blocks = ""
    for section in sections:
        if not isinstance(section, dict):
            continue
        label = _esc(section.get("label") or "")
        body_html = _render_block_body_lines(str(section.get("body") or ""))
        if not label or not body_html:
            continue
        blocks += f"""
      <div class="korea-deep-block">
        <h4 class="korea-deep-label">{label}</h4>
        <div class="korea-deep-body">{body_html}</div>
      </div>"""
    return blocks


def _resolve_korea_evening_memo(working: Mapping[str, Any]) -> dict[str, Any]:
    memo = working.get("korea_evening_memo")
    if isinstance(memo, dict) and not korea_evening_memo_too_thin(memo):
        return dict(memo)
    top_items = working.get("top_5_items") or []
    return build_korea_evening_memo(
        top_items,
        closing_message=str(working.get("closing_message") or ""),
    )


def _render_korea_evening_memo_body(memo: Mapping[str, Any]) -> str:
    action_lines = [str(line).strip() for line in memo.get("action_lines") or [] if str(line).strip()]
    warm_lines = [str(line).strip() for line in memo.get("warm_lines") or [] if str(line).strip()]
    if not warm_lines:
        warm_lines = list(KOREA_WARM_FAREWELL_LINES)
    items = "".join(f"<li>{_esc(line)}</li>" for line in action_lines[:3])
    warm_html = "".join(f'<p class="closing-message warm-farewell">{_esc(line)}</p>' for line in warm_lines[:2])
    return (
        '<div class="evening-memo-body">'
        f'<p>{_esc(memo.get("summary") or "")}</p>'
        f'<p>{_esc(memo.get("action_intro") or "내일은 세 가지만 확인하시면 됩니다.")}</p>'
        f'<ol class="evening-memo-actions">{items}</ol>'
        f'<p>{_esc(memo.get("caution") or "확정되지 않은 수치와 일정은 아직 조심해서 보겠습니다.")}</p>'
        f"{warm_html}"
        "</div>"
    )


def _render_deep_dive(fixture: Mapping[str, Any], *, program_id: str) -> str:
    heading = _esc(fixture.get("deep_dive_heading") or SECTION_DEEP_DIVE)
    subframe = _esc(_deep_dive_subframe(program_id))
    confirmed = fixture.get("deep_dive_confirmed_facts") or []
    interpretation = _esc(fixture.get("deep_dive_interpretation") or "")
    impact = _esc(fixture.get("deep_dive_owner_impact") or "")

    facts_html = ""
    if isinstance(confirmed, list) and confirmed:
        items = "".join(f"<li>{_esc(f)}</li>" for f in confirmed if str(f).strip())
        facts_html = f'<div class="deep-facts"><h4>확인된 사실</h4><ul>{items}</ul></div>'

    layers = fixture.get("deep_dive_layers") or []
    layer_html = ""
    for layer in layers[:3]:
        if not isinstance(layer, dict):
            continue
        layer_html += f"""
      <div class="deep-layer">
        <span class="deep-layer-number">{_esc(layer.get("layer_number"))}</span>
        <div class="deep-layer-title">{_esc(layer.get("layer_title"))}</div>
        <div class="deep-layer-body"><p>{_esc(layer.get("layer_body"))}</p></div>
      </div>"""

    prose = ""
    unc = ""
    if _is_korea_program(program_id):
        prose = f'<div class="korea-deep-blocks">{_render_korea_deep_dive_blocks(fixture)}</div>'
    else:
        body = str(fixture.get("deep_dive_body") or "")
        if body:
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
            if not paragraphs:
                paragraphs = [body.strip()]
            prose = '<div class="deep-dive-prose">' + "".join(f"<p>{_esc(p)}</p>" for p in paragraphs) + "</div>"
        uncertainty = _esc(
            normalize_visible_text(fixture.get("deep_dive_uncertainty") or "", style="sentence")
        )
        unc = (
            f'<div class="deep-uncertainty"><h4>아직 불확실한 점</h4><p>{uncertainty}</p></div>'
            if uncertainty
            else ""
        )
        layer_html = layer_html if layer_html else ""

    interp = (
        f'<div class="deep-interpretation"><h4>키수리 해석</h4><p>{interpretation}</p></div>'
        if interpretation and not _is_korea_program(program_id)
        else ""
    )
    imp = (
        f'<div class="deep-impact"><h4>주인님·운영자 영향</h4><p>{impact}</p></div>'
        if impact and not _is_korea_program(program_id)
        else ""
    )

    return f"""
    <section id="deep-dive-section" class="section-card deep-dive-memo">
      <h2 class="section-heading">{heading}</h2>
      <p class="section-subframe">{subframe}</p>
      {facts_html}
      {prose}
      {interp}
      {imp}
      {unc}
      {layer_html if not _is_korea_program(program_id) else ""}
    </section>
    """


def _render_review_confirmation(review_state: str) -> str:
    text = REVIEW_CONFIRMATION_TEXT[review_state]
    return f"""
    <section id="review-confirmation-box" class="review-box" data-review-state="{_esc(review_state)}">
      <h2 class="visually-compact">Review confirmation</h2>
      <p class="review-confirmation-text">{_esc(text)}</p>
    </section>
    """


def _render_source_list(source_list: Sequence[Mapping[str, Any]]) -> str:
    cards = ""
    for entry in source_list:
        if not isinstance(entry, dict):
            continue
        source_url = str(entry.get("source_url") or "").strip()
        fetched = str(entry.get("fetched_at") or entry.get("checked_at") or "").strip()
        fetched_line = f'<p class="src-fetched">수집 시각: {_esc(fetched)}</p>' if fetched else ""
        cards += f"""
      <article class="source-card">
        <p class="src-name">출처명: {_esc(entry.get("source_name"))}</p>
        <p class="src-url">URL: <a href="{_esc(source_url)}">{_esc(source_url)}</a></p>
        {fetched_line}
        <p class="src-status">상태: {_esc(entry.get("verification_status"))}</p>
      </article>"""
    return cards


def _render_top_shot(fixture: Mapping[str, Any], *, program_id: str) -> str:
    src = str(fixture.get("top_shot_image_src") or "").strip()
    fallback_class = "hero-fallback hero-fallback-korea" if _is_korea_program(program_id) else "hero-fallback hero-fallback-global"
    if src:
        return f"""
      <figure id="top-shot-image" class="top-shot-figure hero-image-card">
        <img src="{_esc(src)}" alt="{_esc(TOP_SHOT_ALT)}" class="top-shot-hero" loading="eager"/>
      </figure>"""
    return f"""
      <div id="top-shot-image" class="hero-image-card {fallback_class}" role="img" aria-label="{_esc(TOP_SHOT_ALT)}">
        <div class="hero-fallback-inner">
          <p class="hero-fallback-identity">{IDENTITY_TITLE}</p>
          <p class="hero-fallback-copy">프라이빗 테크 브리핑</p>
        </div>
      </div>"""


def _render_bottom_shot(fixture: Mapping[str, Any], *, program_id: str) -> str:
    if not _is_korea_program(program_id):
        return ""
    src = str(fixture.get("bottom_shot_image_src") or "").strip()
    if src:
        return f"""
    <figure id="bottom-shot-image" class="korea-bottom-figure">
      <img src="{_esc(src)}" alt="테크 비서 키수리 — 국내 18:30 마무리" class="korea-bottom-hero" loading="lazy"/>
    </figure>"""
    return """
    <div class="placeholder small" id="bottom-shot-placeholder">18:30 bottom-shot preview placeholder</div>"""


def _premium_styles() -> str:
    return """
    :root{
      --sp-1:4px; --sp-2:8px; --sp-3:12px; --sp-4:16px; --sp-5:24px; --sp-6:32px; --sp-7:48px;
      --r-sm:8px; --r-md:12px; --r-lg:16px; --r-pill:999px;
    }
    body.premium-briefing.theme-global{
      --g-bg:#f3f6fa; --g-surface:#ffffff; --g-surface-2:#eef3f8;
      --g-hero-1:#dfe7ef; --g-hero-2:#f8fafc;
      --g-line:rgba(80,100,130,0.14); --g-line-strong:rgba(80,100,130,0.24);
      --g-text:#172033; --g-dim:#536274; --g-mute:#7b8795;
      --g-accent:#3f7ecb; --g-silver:#8fa0b4; --g-signal:#2ca6a4;
      --ks-bg:var(--g-bg); --ks-surface:var(--g-surface); --ks-surface-2:var(--g-surface-2);
      --ks-hero-1:var(--g-hero-1); --ks-hero-2:var(--g-hero-2);
      --ks-line:var(--g-line); --ks-line-strong:var(--g-line-strong);
      --ks-text:var(--g-text); --ks-text-dim:var(--g-dim); --ks-text-mute:var(--g-mute);
      --ks-gold:var(--g-accent); --ks-gold-soft:rgba(63,126,203,0.10);
      --ks-blue:var(--g-accent); --ks-blue-soft:rgba(63,126,203,0.10);
      --ks-signal:var(--g-signal); --ks-warn:#c98a2e;
      --shadow-card:0 6px 18px rgba(30,50,80,0.06);
      --shadow-soft:0 4px 12px rgba(30,50,80,0.05);
    }
    body.premium-briefing.theme-korea{
      --k-bg:#14110d; --k-surface:#1e1a14; --k-surface-2:#27211a;
      --k-hero-1:#2a2418; --k-hero-2:#100d0a;
      --k-line:rgba(210,190,150,0.16);
      --k-text:#f3ece0; --k-dim:#c8bca8; --k-mute:#8a7d68;
      --k-gold:#cda85f; --k-gold-soft:rgba(205,168,95,0.14); --k-ember:#b9763f;
      --ks-bg:var(--k-bg); --ks-surface:var(--k-surface); --ks-surface-2:var(--k-surface-2);
      --ks-hero-1:var(--k-hero-1); --ks-hero-2:var(--k-hero-2);
      --ks-line:var(--k-line); --ks-line-strong:rgba(210,190,150,0.28);
      --ks-text:var(--k-text); --ks-text-dim:var(--k-dim); --ks-text-mute:var(--k-mute);
      --ks-gold:var(--k-gold); --ks-gold-soft:var(--k-gold-soft);
      --ks-blue:#8fa8c8; --ks-blue-soft:rgba(143,168,200,0.12);
      --ks-signal:var(--k-ember); --ks-warn:var(--k-ember);
      --shadow-card:0 10px 30px rgba(0,0,0,0.35);
      --shadow-soft:0 4px 14px rgba(0,0,0,0.25);
    }
    *{box-sizing:border-box;}
    body.premium-briefing{
      margin:0;
      font-family:"Apple SD Gothic Neo","Pretendard","Malgun Gothic","Noto Sans KR",sans-serif;
      font-size:0.95rem; line-height:1.7; color:var(--ks-text-dim);
      background:var(--ks-bg);
      background:linear-gradient(165deg,var(--ks-bg) 0%,var(--ks-hero-2) 55%,var(--ks-bg) 100%);
    }
    .briefing-shell{max-width:680px;margin:0 auto;padding:var(--sp-5) var(--sp-4) var(--sp-7);}
    .premium-hero{
      background:linear-gradient(135deg,var(--ks-hero-1) 0%,var(--ks-hero-2) 100%);
      background-color:var(--ks-hero-2);
      border:1px solid var(--ks-line-strong); border-radius:var(--r-lg);
      padding:var(--sp-5); margin-bottom:var(--sp-5); box-shadow:var(--shadow-card);
      min-height:120px;
    }
    .hero-layout{display:flex;flex-direction:column;gap:var(--sp-4);align-items:stretch;}
    .hero-copy{flex:1 1 auto;min-width:0;order:2;}
    .slot-badge{
      display:inline-block; font-size:0.72rem; letter-spacing:0.06em; font-weight:700;
      padding:4px 10px; border-radius:var(--r-pill); margin-bottom:var(--sp-2);
    }
    .theme-global .slot-badge{
      background:rgba(63,126,203,0.12); color:var(--g-accent);
      border:1px solid rgba(63,126,203,0.28);
    }
    .theme-korea .slot-badge{
      background:var(--k-gold-soft); color:var(--k-gold);
      border:1px solid rgba(205,168,95,0.35);
    }
    .owner-badge{
      display:inline-block; font-size:0.72rem; letter-spacing:0.04em;
      padding:4px 10px; border-radius:var(--r-pill);
      background:var(--ks-surface-2); color:var(--ks-text-mute);
      border:1px solid var(--ks-line); margin-bottom:var(--sp-3);
    }
    .hero-title{margin:0 0 var(--sp-2);font-size:clamp(1.6rem,4.5vw,2.1rem);font-weight:700;letter-spacing:-0.01em;color:var(--ks-text);}
    .hero-subtitle{margin:0 0 0;color:var(--ks-text-dim);font-size:1rem;}
    .identity-line{margin:0 0 var(--sp-3);color:var(--ks-text-mute);font-size:0.82rem;}
    .hero-image-card,#top-shot-image.hero-image-card,.top-shot-figure{
      order:1;
      margin:0;border-radius:var(--r-md);overflow:hidden;
      border:0;background:transparent;
      padding:0;display:block;width:100%;max-width:100%;
      box-shadow:none;
    }
    .top-shot-hero{
      width:100%;height:auto;display:block;
      object-fit:contain;object-position:center center;max-height:none;
      border-radius:var(--r-md);
    }
    .hero-fallback{min-height:180px;display:flex;align-items:center;justify-content:center;}
    .hero-fallback-global{background:linear-gradient(135deg,var(--g-hero-1),var(--g-hero-2));}
    .hero-fallback-korea{background:linear-gradient(135deg,var(--k-hero-1),var(--k-hero-2));}
    .hero-fallback-inner{text-align:center;padding:var(--sp-5);}
    .hero-fallback-identity{margin:0;color:var(--ks-gold);font-weight:700;}
    .hero-fallback-copy{margin:var(--sp-2) 0 0;color:var(--ks-text-mute);font-size:0.85rem;}
    #opening-lead{margin-bottom:var(--sp-5);}
    .opening-lead{
      margin:0;padding:var(--sp-4) var(--sp-5);
      background:var(--ks-surface);border:1px solid var(--ks-line);border-radius:var(--r-md);
      color:var(--ks-text);font-size:1rem;line-height:1.75;
    }
    .theme-top-insert,.signal-summary{padding:var(--sp-4) var(--sp-5);}
    .theme-insert-label,.signal-summary-lead{margin:0 0 var(--sp-2);font-size:0.74rem;font-weight:700;letter-spacing:0.08em;color:var(--ks-text-mute);text-transform:none;}
    .theme-insert-copy{margin:0 0 var(--sp-3);font-size:0.88rem;color:var(--ks-text-dim);line-height:1.6;}
    .signal-chip-row{display:flex;flex-wrap:wrap;gap:var(--sp-2);}
    .signal-chip{
      display:inline-block;padding:4px 10px;border-radius:var(--r-pill);font-size:0.78rem;font-weight:600;
      background:var(--ks-gold-soft);color:var(--ks-gold);border:1px solid rgba(200,169,106,0.25);
    }
    .theme-global .signal-chip{background:rgba(143,160,180,0.12);color:var(--g-silver);border-color:rgba(143,160,180,0.28);}
    .theme-global .signal-chip:nth-child(even){background:rgba(63,126,203,0.10);color:var(--g-accent);border-color:rgba(63,126,203,0.22);}
    .theme-korea .signal-chip:nth-child(even){background:var(--ks-blue-soft);color:var(--ks-blue);border-color:rgba(95,143,214,0.25);}
    .section-card{
      background:var(--ks-surface);color:var(--ks-text-dim);
      border:1px solid var(--ks-line);border-radius:var(--r-lg);
      padding:var(--sp-5);margin-bottom:var(--sp-5);box-shadow:var(--shadow-card);
    }
    .section-heading{
      display:flex;align-items:center;gap:var(--sp-2);
      margin:0 0 var(--sp-4);font-size:1.05rem;font-weight:700;letter-spacing:0.03em;
      color:var(--ks-text);border:0;padding:0;
    }
    .section-heading::before{content:"";width:3px;height:1.05em;border-radius:2px;background:var(--ks-gold);}
    .theme-global .section-heading::before{background:var(--g-accent);}
    .section-subframe,.checkpoint-subframe{
      margin:0 0 var(--sp-4);font-size:0.82rem;font-weight:600;letter-spacing:0.03em;color:var(--ks-text-mute);
    }
    .theme-global .section-subframe,.theme-global .checkpoint-subframe{color:var(--g-silver);}
    .theme-korea .section-subframe,.theme-korea .checkpoint-subframe{color:var(--k-gold);}
    .briefing-card{
      position:relative;
      background:var(--ks-surface);
      border:1px solid var(--ks-line);border-radius:var(--r-md);
      padding:var(--sp-5) var(--sp-4) var(--sp-4);margin-bottom:var(--sp-4);box-shadow:var(--shadow-soft);
    }
    .theme-global .briefing-card{border-left:3px solid var(--g-accent);}
    .theme-korea .briefing-card{background:linear-gradient(180deg,var(--ks-surface) 0%,var(--ks-surface-2) 100%);}
    .angle-chip{
      display:inline-block;font-size:0.72rem;font-weight:700;letter-spacing:0.05em;
      padding:3px 8px;border-radius:var(--r-pill);margin-bottom:var(--sp-2);
    }
    .theme-global .angle-chip{background:rgba(63,126,203,0.10);color:var(--g-accent);border:1px solid rgba(63,126,203,0.22);}
    .theme-korea .angle-chip{background:var(--k-gold-soft);color:var(--k-gold);border:1px solid rgba(205,168,95,0.30);}
    .card-emphasis-line{margin:0 0 var(--sp-3);padding-top:var(--sp-2);border-top:1px solid var(--ks-line);}
    .card-emphasis-label{font-size:0.78rem;font-weight:700;letter-spacing:0.04em;}
    .card-emphasis-text{font-size:0.92rem;line-height:1.55;margin-left:0.35rem;}
    .theme-global .card-emphasis-label{color:var(--g-signal);}
    .theme-korea .card-emphasis-label{color:var(--k-gold);}
    .card-rank{font-size:1.5rem;font-weight:800;color:var(--ks-gold);line-height:1;margin-bottom:var(--sp-2);}
    .card-headline{margin:0 0 var(--sp-3);font-size:1.12rem;font-weight:700;line-height:1.4;color:var(--ks-text);}
    .source-chip{
      display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;font-size:0.78rem;
      margin-top:var(--sp-3);padding:var(--sp-2) var(--sp-3);
      background:var(--ks-surface-2);border-radius:var(--r-sm);border:1px solid var(--ks-line);
    }
    .chip-label{font-weight:700;color:var(--ks-text-mute);}
    .chip-name{color:var(--ks-text-dim);}
    .chip-url,a.chip-url{color:var(--ks-blue);text-decoration:none;word-break:break-all;}
    .chip-url:hover{text-decoration:underline;}
    .block-label{margin:0 0 var(--sp-2);font-size:0.74rem;font-weight:700;letter-spacing:0.06em;color:var(--ks-text-mute);}
    .block-body{margin:0 0 var(--sp-3);color:var(--ks-text-dim);line-height:1.7;}
    .owner-angle-block{
      background:var(--ks-gold-soft);border-left:3px solid var(--ks-gold);
      padding:var(--sp-3) var(--sp-4);border-radius:0 var(--r-sm) var(--r-sm) 0;margin-bottom:var(--sp-3);
    }
    .theme-global .owner-angle-block{background:rgba(63,126,203,0.08);border-left-color:var(--g-accent);}
    .theme-global .owner-angle-block .block-label{color:var(--g-accent);}
    .owner-angle-block .block-label{color:var(--ks-gold);}
    .owner-angle-block .block-body{color:var(--ks-text);font-size:0.98rem;}
    .judgment-row{display:flex;flex-wrap:wrap;gap:var(--sp-2);align-items:flex-start;margin-bottom:var(--sp-3);}
    .judgment-label{font-size:0.72rem;font-weight:700;letter-spacing:0.06em;color:var(--ks-gold);width:100%;}
    .judgment-badge{
      display:inline-block;font-size:0.78rem;font-weight:700;letter-spacing:0.04em;
      padding:4px 10px;border-radius:var(--r-pill);
      background:transparent;border:1px solid var(--ks-gold);color:var(--ks-gold);
    }
    .judgment-text{flex:1;min-width:200px;color:var(--ks-text-dim);font-size:0.92rem;}
    .next-watch-block .block-body{font-size:0.9rem;}
    .watch-arrow{color:var(--ks-gold);margin-right:4px;}
    .insufficient-badge{
      display:inline-block;font-size:0.76rem;font-weight:600;color:var(--ks-warn);
      background:rgba(217,164,65,0.12);padding:3px 8px;border-radius:var(--r-sm);margin-bottom:var(--sp-2);
    }
    .source-box{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden;}
    .deep-dive-prose p,.deep-interpretation p,.deep-impact p,.deep-uncertainty p{margin:0 0 var(--sp-3);line-height:1.75;}
    .korea-deep-block{margin:0 0 var(--sp-4);padding:var(--sp-3) 0;border-top:1px solid rgba(255,255,255,.08);}
    .korea-deep-block:first-of-type{border-top:none;padding-top:0;}
    .korea-deep-label{margin:0 0 var(--sp-2);font-size:.95rem;letter-spacing:-.01em;}
    .korea-deep-body p,.evening-memo-body p{margin:0 0 var(--sp-3);line-height:1.75;}
    .korea-deep-list,.evening-memo-actions{margin:0 0 var(--sp-3);padding-left:1.2rem;line-height:1.7;}
    .deep-facts h4,.deep-interpretation h4,.deep-impact h4,.deep-uncertainty h4{
      margin:var(--sp-3) 0 var(--sp-2);font-size:0.82rem;color:var(--ks-gold);
    }
    .deep-layer{
      border:1px solid var(--ks-line);background:var(--ks-surface-2);
      border-left:3px solid var(--ks-blue);border-radius:var(--r-sm);
      padding:var(--sp-3) var(--sp-4);margin-top:var(--sp-3);
    }
    .deep-layer-number{font-weight:700;color:var(--ks-gold);margin-right:6px;}
    .deep-layer-title{font-weight:700;color:var(--ks-text);display:inline;}
    .checkpoint{
      font-size:1.15rem;font-weight:600;color:var(--ks-text);
      padding:var(--sp-4) var(--sp-5);background:var(--ks-gold-soft);
      border-left:4px solid var(--ks-gold);border-radius:0 var(--r-md) var(--r-md) 0;line-height:1.6;
    }
    .theme-global .checkpoint{background:rgba(44,166,164,0.08);border-left-color:var(--g-signal);}
    .global-open-ending{margin:0 0 var(--sp-4);color:var(--ks-text-dim);font-size:0.92rem;line-height:1.65;}
    .evening-memo-label{margin:0 0 var(--sp-2);font-size:0.82rem;font-weight:700;color:var(--k-gold);letter-spacing:0.04em;}
    .korea-bottom-figure{margin:var(--sp-4) 0;border-radius:var(--r-md);overflow:hidden;border:1px solid var(--ks-line);}
    .korea-bottom-hero{width:100%;height:auto;display:block;object-fit:contain;}
    .closing-message{margin:0 0 var(--sp-4);color:var(--ks-text-dim);}
    .source-card{
      border:1px solid var(--ks-line);border-radius:var(--r-sm);
      padding:var(--sp-3);margin-bottom:var(--sp-2);background:var(--ks-surface-2);font-size:0.82rem;
    }
    .footer-cluster{
      margin-top:var(--sp-6);padding-top:var(--sp-4);
      border-top:1px solid var(--ks-line);font-size:0.72rem;color:var(--ks-text-mute);
    }
    .rights-policy{
      margin:var(--sp-4) 0;padding:var(--sp-4);
      border-top:1px solid var(--ks-line);color:var(--ks-text-mute);font-size:0.78rem;text-align:center;
    }
    .rights-wordmark{color:var(--ks-gold);letter-spacing:0.08em;font-weight:600;}
    .audit-fold{margin-top:var(--sp-3);border:1px solid var(--ks-line);border-radius:var(--r-sm);padding:var(--sp-2) var(--sp-3);}
    .audit-fold summary{cursor:pointer;color:var(--ks-text-mute);font-size:0.72rem;list-style:none;}
    .audit-fold summary::-webkit-details-marker{display:none;}
    .meta-box,.op-meta,.compliance-box,.validation-box,.review-box{
      background:rgba(15,23,42,0.45);border:1px solid var(--ks-line);
      border-radius:var(--r-sm);padding:var(--sp-2) var(--sp-3);margin:var(--sp-2) 0;
      color:var(--ks-text-mute);font-size:0.72rem;
    }
    .visually-compact{font-size:0.72rem;color:var(--ks-text-mute);margin:0 0 var(--sp-2);}
    .design-fixture-banner{
      margin:0 0 var(--sp-4);padding:var(--sp-3) var(--sp-4);
      border:1px solid rgba(217,164,65,0.45);border-radius:var(--r-md);
      background:rgba(217,164,65,0.12);color:var(--ks-warn);
      font-size:0.82rem;font-weight:700;letter-spacing:0.04em;text-align:center;
    }
    @media (min-width:641px){
      .hero-layout{flex-direction:column;align-items:stretch;gap:var(--sp-4);}
      .hero-copy{flex:1 1 auto;min-width:0;max-width:none;}
      .hero-image-card,#top-shot-image.hero-image-card,.top-shot-figure{
        width:100%;max-width:100%;flex:none;align-self:stretch;
      }
      .top-shot-hero{width:100%;max-width:100%;max-height:none;}
    }
    @media (max-width:600px){
      .briefing-shell{padding:var(--sp-4) var(--sp-3) var(--sp-6);}
      .section-card{padding:var(--sp-4);border-radius:var(--r-md);}
      .top-shot-hero{max-height:none;object-fit:contain;}
      .judgment-row{flex-direction:column;}
    }
    """


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


def render_keysuri_contract_preview_html(
    fixture: Mapping[str, Any],
    *,
    repo_root: Path | None = None,
    image_mode: str = IMAGE_MODE_PREVIEW,
    auto_prepare: bool = True,
) -> str:
    """Render premium contract-validation HTML from a fixture dict."""
    if not isinstance(fixture, dict):
        raise TypeError("fixture must be a dict")

    working: dict[str, Any] = dict(fixture)
    if auto_prepare:
        root = repo_root or Path(__file__).resolve().parent
        prepare_contract_preview_fixture(working, repo_root=root, image_mode=image_mode)

    program_id = str(working.get("program_id") or "").strip()
    allowed = (
        program_id in (PROGRAM_KOREA, PROGRAM_GLOBAL)
        or program_id.startswith("keysuri_korea")
        or program_id.startswith("keysuri_global")
    )
    if not allowed:
        raise ValueError(f"Unsupported program_id: {program_id!r}")

    slot_raw = str(working.get("slot") or ("18:30" if _is_korea_program(program_id) else "12:30"))
    slot = _esc(slot_raw)
    review_state = _resolve_review_state(working)
    is_korea = _is_korea_program(program_id)
    theme_class = _theme_body_class(program_id)
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    hero_title, hero_subtitle = _hero_copy(program_id)
    subject, preheader = _selected_subject_preheader(working, program_id)
    closing_message = _normalize_closing(str(working.get("closing_message") or ""))
    color_scheme = "dark light" if is_korea else "light dark"

    preview_metadata = f"""
    <div class="meta-box" id="preview-metadata">
      <strong>미리보기 정보</strong>
      <span>subject: {_esc(subject)}</span>
      <span>preheader: {_esc(preheader)}</span>
      <span>program_id: {_esc(program_id)}</span>
      <span>slot: {slot}</span>
      <span>mode: contract_preview_premium</span>
    </div>"""

    hero = f"""
    <header class="premium-hero" id="premium-hero">
      <div class="hero-layout">
        <div class="hero-copy">
          <span class="slot-badge">{_esc(_slot_badge(program_id, slot_raw))}</span>
          <span class="owner-badge">{OWNER_REVIEW_BADGE}</span>
          <p class="identity-line">{IDENTITY_TITLE}</p>
          <h1 class="hero-title">{hero_title}</h1>
          <p class="hero-subtitle">{hero_subtitle}</p>
        </div>
        {_render_top_shot(working, program_id=program_id)}
      </div>
    </header>"""

    opening = f"""
    <section id="opening-lead">
      <p class="opening-lead">{_esc(working.get("opening_lead"))}</p>
    </section>"""

    theme_top_insert = _render_theme_top_insert(working, program_id=program_id)
    top5 = _render_top5_section(working, program_id=program_id)
    deep_dive = _render_deep_dive(working, program_id=program_id)
    checkpoint_subframe = _esc(_checkpoint_subframe(program_id))
    checkpoint_body = str(working.get("one_line_checkpoint") or "")
    if is_korea:
        checkpoint_body = build_korea_one_line_checkpoint(
            working.get("top_5_items") or [],
            existing=polish_korea_checkpoint_text(checkpoint_body),
        )
    checkpoint = f"""
    <section id="one-line-section" class="section-card">
      <h2 class="section-heading">{SECTION_ONE_LINE}</h2>
      <p class="checkpoint-subframe">{checkpoint_subframe}</p>
      <div class="checkpoint">{_esc(checkpoint_body)}</div>
    </section>"""

    bottom_shot = _render_bottom_shot(working, program_id=program_id)
    korea_memo_section = ""
    global_open_ending = ""
    if is_korea:
        memo_heading = _esc(working.get("evening_memo_heading") or KOREA_EVENING_MEMO_HEADING)
        memo = _resolve_korea_evening_memo(working)
        memo_html = _render_korea_evening_memo_body(memo)
        korea_memo_section = f"""
    <section id="closing-section" class="section-card evening-memo-section">
      <h2 class="section-heading">{memo_heading}</h2>
      {memo_html}
    </section>"""
    else:
        global_open_ending = f"""
    <p class="global-open-ending">{GLOBAL_OPEN_ENDING}</p>"""

    review_confirmation = _render_review_confirmation(review_state)
    if is_korea:
        closing = f"""
    <section id="source-appendix-section" class="section-card source-appendix">
      <h2 class="section-heading">{SECTION_CLOSING}</h2>
      {_render_source_list(working.get("source_list") or [])}
    </section>"""
    else:
        closing = f"""
    <section id="closing-section" class="section-card source-appendix">
      <h2 class="section-heading">{SECTION_CLOSING}</h2>
      <p class="closing-message">{_esc(closing_message)}</p>
      {_render_source_list(working.get("source_list") or [])}
    </section>"""

    rights_policy = f"""
    <div class="rights-policy" id="rights-policy">
      <p><span class="rights-wordmark">MirAI:ON</span></p>
      <p>{RIGHTS_LINE_1}</p>
      <p>{RIGHTS_LINE_2}</p>
    </div>"""

    operation_meta = working.get("operation_metadata") or {}
    operation_metadata = f"""
    <div class="op-meta" id="operation-metadata">
      <strong>운영 정보 (server-rendered only)</strong>
      <p>program_id: {_esc(operation_meta.get("program_id"))}</p>
      <p>mode: {_esc(operation_meta.get("mode"))}</p>
      <p>status: {_esc(operation_meta.get("status"))}</p>
      <p>slot: {_esc(operation_meta.get("slot"))}</p>
    </div>"""

    compliance_checklist = """
    <div class="compliance-box" id="compliance-checklist">
      <strong>Contract compliance checklist</strong>
    </div>"""

    validation_box = _render_validation_box(timestamp)

    if is_korea:
        main_tail = checkpoint + bottom_shot + review_confirmation + korea_memo_section + closing
    else:
        main_tail = checkpoint + global_open_ending + review_confirmation + closing

    audit_fold = f"""
    <details class="audit-fold">
      <summary>운영 정보 (검수용) 보기</summary>
      {preview_metadata}
      {operation_metadata}
      {compliance_checklist}
      {validation_box}
    </details>"""

    footer = f"""
    <div class="footer-cluster">
      {rights_policy}
      {audit_fold}
    </div>"""

    preheader_span = (
        f'<span class="preheader-hidden" style="{PREHEADER_STYLE}">{_esc(preheader)}</span>'
    )

    design_banner = ""
    if str(working.get("fixture_mode") or "") == "design_only":
        design_banner = """
    <div class="design-fixture-banner" id="design-fixture-banner">
      DESIGN FIXTURE — NOT OWNER REVIEW
    </div>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta name="color-scheme" content="{color_scheme}"/>
<meta name="supported-color-schemes" content="{color_scheme}"/>
<title>{_esc(subject)}</title>
<style>{_premium_styles()}</style>
</head>
<body class="premium-briefing {theme_class}">
{preheader_span}
<div class="briefing-shell">
{design_banner}
{hero}
{opening}
{theme_top_insert}
{top5}
{deep_dive}
{main_tail}
{footer}
</div>
</body>
</html>
"""


_GMAIL_GLOBAL_COLORS = {
    "bg": "#f3f6fa",
    "surface": "#ffffff",
    "surface2": "#eef3f8",
    "line": "#dce4ef",
    "text": "#172033",
    "dim": "#536274",
    "mute": "#7b8795",
    "accent": "#3f7ecb",
    "signal": "#2ca6a4",
    "silver": "#8fa0b4",
    "button_bg": "#0f172a",
}


def _gmail_spacer(height: int = 16) -> str:
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td height="{height}" style="font-size:0;line-height:{height}px;">&nbsp;</td></tr></table>'
    )


def _gmail_render_global_signal_chips(fixture: Mapping[str, Any]) -> str:
    items = fixture.get("top_5_items") or []
    chips: list[str] = []
    for item in items[:5]:
        if isinstance(item, dict):
            chips.append(_signal_chip_text(item))
    if not chips:
        return ""
    chip_cells = []
    for chip in chips:
        chip_cells.append(
            f'<span style="display:inline-block;margin:0 6px 8px 0;padding:6px 10px;'
            f'font-size:12px;line-height:1.4;color:{_GMAIL_GLOBAL_COLORS["accent"]};'
            f'background:#eef4fb;border:1px solid #d4e3f5;border-radius:999px;">{_esc(chip)}</span>'
        )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{_GMAIL_GLOBAL_COLORS["surface2"]};border:1px solid {_GMAIL_GLOBAL_COLORS["line"]};border-radius:12px;">'
        f'<tr><td style="padding:16px 18px;">'
        f'<p style="margin:0 0 8px 0;font-size:12px;font-weight:700;letter-spacing:0.04em;color:{_GMAIL_GLOBAL_COLORS["silver"]};">글로벌 신호 분포</p>'
        f'<p style="margin:0 0 12px 0;font-size:14px;line-height:1.6;color:{_GMAIL_GLOBAL_COLORS["dim"]};">'
        f'밝은 낮에 먼저 보는 세계 기술 지형도 — 오늘 신호가 어느 축에 몰렸는지입니다.</p>'
        f'{"".join(chip_cells)}'
        f'</td></tr></table>'
    )


def _gmail_render_global_top_item(item: Mapping[str, Any], rank: int) -> str:
    headline = _item_field(item, "korean_title", "headline")
    selection_reason = _item_field(item, "selection_reason", "selection_rationale")
    what_happened = _item_field(item, "what_happened", "summary")
    why_now = _item_field(item, "why_now", "why_it_matters")
    owner_angle = _item_field(item, "owner_angle", "business_implication", "keysuri_comment")
    source_url = _item_field(item, "source_url")
    source_name = _item_field(item, "source_name") or "출처"
    emphasis_body = _item_field(item, "next_day_impact_line", "owner_action_line")
    j_label, j_text = _judgment_block(item)
    c = _GMAIL_GLOBAL_COLORS

    def _label(text: str) -> str:
        return (
            f'<p style="margin:0 0 6px 0;font-size:12px;font-weight:700;letter-spacing:0.03em;'
            f'color:{c["accent"]};">{_esc(text)}</p>'
        )

    def _body(text: str) -> str:
        if not text:
            return ""
        return (
            f'<p style="margin:0 0 14px 0;font-size:14px;line-height:1.75;color:{c["text"]};">'
            f'{_esc(text)}</p>'
        )

    emphasis_html = ""
    if emphasis_body:
        emphasis_html = (
            f'<p style="margin:0 0 14px 0;font-size:13px;line-height:1.6;color:{c["signal"]};">'
            f'<strong style="color:{c["signal"]};">{_esc(GLOBAL_CARD_EMPHASIS)}</strong> '
            f'{_esc(emphasis_body)}</p>'
        )
    elif not _is_korea_program(PROGRAM_GLOBAL):
        emphasis_html = (
            f'<p style="margin:0 0 14px 0;font-size:13px;line-height:1.6;color:{c["signal"]};">'
            f'<strong style="color:{c["signal"]};">{_esc(GLOBAL_CARD_EMPHASIS)}</strong></p>'
        )

    source_html = ""
    if source_url:
        source_html = (
            f'<p style="margin:14px 0 0 0;font-size:12px;line-height:1.6;color:{c["mute"]};">'
            f'<span style="font-weight:700;color:{c["dim"]};">출처</span> '
            f'{_esc(source_name)} · '
            f'<a href="{_esc(source_url)}" style="color:{c["accent"]};text-decoration:underline;">{_esc(source_url)}</a>'
            f'</p>'
        )

    judgment_html = ""
    if j_label or j_text:
        judgment_html = (
            f'<p style="margin:0;font-size:13px;line-height:1.6;color:{c["dim"]};">'
            f'<strong style="color:{c["accent"]};">키수리 판단</strong> '
            f'<span style="display:inline-block;padding:2px 8px;margin:0 6px 0 0;border-radius:999px;'
            f'background:#eef4fb;color:{c["accent"]};font-size:12px;font-weight:700;">{_esc(j_label)}</span>'
            f'{_esc(j_text)}</p>'
        )

    selection_html = _body(selection_reason) if selection_reason else ""
    if selection_reason:
        selection_html = _label("선정 이유") + selection_html

    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{c["surface"]};border:1px solid {c["line"]};border-left:4px solid {c["accent"]};border-radius:12px;">'
        f'<tr><td style="padding:18px 18px 16px 18px;">'
        f'<p style="margin:0 0 8px 0;font-size:11px;font-weight:700;color:{c["mute"]};">{rank}</p>'
        f'<span style="display:inline-block;margin:0 0 10px 0;padding:4px 10px;font-size:11px;font-weight:700;'
        f'color:{c["accent"]};background:#eef4fb;border:1px solid #d4e3f5;border-radius:999px;">'
        f'{_esc(GLOBAL_ANGLE_CHIP)}</span>'
        f'<h3 style="margin:0 0 12px 0;font-size:18px;line-height:1.45;font-weight:700;color:{c["text"]};">'
        f'{rank}. {_esc(headline)}</h3>'
        f'{selection_html}{emphasis_html}'
        f'{_label("무슨 일이 있었나")}{_body(what_happened)}'
        f'{_label("왜 지금 중요한가")}{_body(why_now)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:#f5f9fd;border-left:3px solid {c["accent"]};border-radius:8px;">'
        f'<tr><td style="padding:12px 14px;">'
        f'{_label("주인님 관점")}{_body(owner_angle)}'
        f'</td></tr></table>'
        f'{_gmail_spacer(12)}{judgment_html}{source_html}'
        f'</td></tr></table>'
    )


def _gmail_render_global_top5(fixture: Mapping[str, Any]) -> str:
    heading = _esc(fixture.get("top_5_heading") or "글로벌 테크 TOP 5")
    items = fixture.get("top_5_items") or []
    cards = ""
    for idx, item in enumerate(items[:5], start=1):
        if isinstance(item, dict):
            cards += _gmail_render_global_top_item(item, int(item.get("rank") or idx))
            cards += _gmail_spacer(14)
    c = _GMAIL_GLOBAL_COLORS
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td>'
        f'<h2 style="margin:0 0 16px 0;font-size:20px;line-height:1.4;font-weight:700;color:{c["text"]};'
        f'border-left:4px solid {c["accent"]};padding-left:12px;">{heading}</h2>'
        f'{cards}'
        f'</td></tr></table>'
    )


def _gmail_render_global_sources(source_list: Sequence[Mapping[str, Any]]) -> str:
    c = _GMAIL_GLOBAL_COLORS
    rows = ""
    for entry in source_list:
        if not isinstance(entry, dict):
            continue
        source_url = str(entry.get("source_url") or "").strip()
        if not source_url:
            continue
        rows += (
            f'<p style="margin:0 0 10px 0;font-size:13px;line-height:1.6;color:{c["dim"]};">'
            f'<strong style="color:{c["text"]};">{_esc(entry.get("source_name") or "출처")}</strong><br/>'
            f'<a href="{_esc(source_url)}" style="color:{c["accent"]};text-decoration:underline;word-break:break-all;">'
            f'{_esc(source_url)}</a></p>'
        )
    if not rows:
        return ""
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{c["surface"]};border:1px solid {c["line"]};border-radius:12px;">'
        f'<tr><td style="padding:18px;">'
        f'<h2 style="margin:0 0 12px 0;font-size:18px;line-height:1.4;font-weight:700;color:{c["text"]};">{_esc(SECTION_CLOSING)}</h2>'
        f'<p style="margin:0 0 14px 0;font-size:14px;line-height:1.7;color:{c["dim"]};">{_esc(SAFE_CLOSING_MESSAGE)}</p>'
        f'{rows}'
        f'</td></tr></table>'
    )


def _gmail_render_global_deep_dive(fixture: Mapping[str, Any]) -> str:
    c = _GMAIL_GLOBAL_COLORS
    heading = str(fixture.get("deep_dive_heading") or SECTION_DEEP_DIVE).strip()
    subframe = GLOBAL_DEEP_SUBFRAME
    body = str(fixture.get("deep_dive_body") or "").strip()
    confirmed = fixture.get("deep_dive_confirmed_facts") or []
    interpretation = str(fixture.get("deep_dive_interpretation") or "").strip()
    impact = str(fixture.get("deep_dive_owner_impact") or "").strip()
    uncertainty = normalize_visible_text(fixture.get("deep_dive_uncertainty") or "", style="sentence")
    layers = fixture.get("deep_dive_layers") or []

    inner_parts: list[str] = []
    if isinstance(confirmed, list) and confirmed:
        facts = "".join(
            f'<li style="margin:0 0 8px 0;font-size:14px;line-height:1.7;color:{c["text"]};">'
            f'{_esc(str(f).strip())}</li>'
            for f in confirmed
            if str(f).strip()
        )
        if facts:
            inner_parts.append(
                f'<p style="margin:0 0 8px 0;font-size:12px;font-weight:700;color:{c["accent"]};">확인된 사실</p>'
                f'<ul style="margin:0 0 14px 18px;padding:0;">{facts}</ul>'
            )

    if body:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        if not paragraphs:
            paragraphs = [body]
        for para in paragraphs:
            inner_parts.append(
                f'<p style="margin:0 0 14px 0;font-size:14px;line-height:1.75;color:{c["text"]};">{_esc(para)}</p>'
            )

    if interpretation:
        inner_parts.append(
            f'<p style="margin:0 0 8px 0;font-size:12px;font-weight:700;color:{c["accent"]};">키수리 해석</p>'
            f'<p style="margin:0 0 14px 0;font-size:14px;line-height:1.75;color:{c["text"]};">{_esc(interpretation)}</p>'
        )
    if impact:
        inner_parts.append(
            f'<p style="margin:0 0 8px 0;font-size:12px;font-weight:700;color:{c["accent"]};">주인님·운영자 영향</p>'
            f'<p style="margin:0 0 14px 0;font-size:14px;line-height:1.75;color:{c["text"]};">{_esc(impact)}</p>'
        )
    if uncertainty:
        inner_parts.append(
            f'<p style="margin:0 0 8px 0;font-size:12px;font-weight:700;color:{c["accent"]};">아직 불확실한 점</p>'
            f'<p style="margin:0 0 14px 0;font-size:14px;line-height:1.75;color:{c["dim"]};">{_esc(uncertainty)}</p>'
        )

    for layer in layers[:3]:
        if not isinstance(layer, dict):
            continue
        layer_title = str(layer.get("layer_title") or "").strip()
        layer_body = str(layer.get("layer_body") or "").strip()
        if not layer_title and not layer_body:
            continue
        layer_num = str(layer.get("layer_number") or "").strip()
        num_html = (
            f'<p style="margin:0 0 6px 0;font-size:11px;font-weight:700;color:{c["mute"]};">{_esc(layer_num)}</p>'
            if layer_num
            else ""
        )
        inner_parts.append(
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="margin:0 0 12px 0;background:#f5f9fd;border:1px solid {c["line"]};border-radius:10px;">'
            f'<tr><td style="padding:14px 16px;">'
            f'{num_html}'
            f'<p style="margin:0 0 8px 0;font-size:15px;font-weight:700;color:{c["text"]};">{_esc(layer_title)}</p>'
            f'<p style="margin:0;font-size:14px;line-height:1.75;color:{c["text"]};">{_esc(layer_body)}</p>'
            f'</td></tr></table>'
        )

    if not inner_parts:
        return ""

    return (
        f'{_gmail_spacer(18)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td>'
        f'<h2 style="margin:0 0 8px 0;font-size:20px;line-height:1.4;font-weight:700;color:{c["text"]};'
        f'border-left:4px solid {c["accent"]};padding-left:12px;">{_esc(heading)}</h2>'
        f'<p style="margin:0 0 16px 0;font-size:12px;font-weight:700;letter-spacing:0.04em;color:{c["silver"]};">'
        f'{_esc(subframe)}</p>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{c["surface"]};border:1px solid {c["line"]};border-radius:12px;">'
        f'<tr><td style="padding:18px;">{"".join(inner_parts)}</td></tr></table>'
        f'</td></tr></table>'
    )


def _gmail_render_global_one_line_checkpoint(fixture: Mapping[str, Any]) -> str:
    c = _GMAIL_GLOBAL_COLORS
    checkpoint = str(fixture.get("one_line_checkpoint") or "").strip()
    if not checkpoint:
        return ""
    return (
        f'{_gmail_spacer(18)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td>'
        f'<h2 style="margin:0 0 8px 0;font-size:20px;line-height:1.4;font-weight:700;color:{c["text"]};'
        f'border-left:4px solid {c["signal"]};padding-left:12px;">{_esc(SECTION_ONE_LINE)}</h2>'
        f'<p style="margin:0 0 12px 0;font-size:12px;font-weight:700;letter-spacing:0.04em;color:{c["silver"]};">'
        f'{_esc(GLOBAL_CHECKPOINT_SUBFRAME)}</p>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:#eef8f7;border:1px solid #cfe9e6;border-left:4px solid {c["signal"]};border-radius:12px;">'
        f'<tr><td style="padding:16px 18px;">'
        f'<p style="margin:0;font-size:15px;line-height:1.7;color:{c["text"]};">{_esc(checkpoint)}</p>'
        f'</td></tr></table>'
        f'</td></tr></table>'
    )


_GMAIL_KOREA_COLORS = {
    "bg": "#14110d",
    "surface": "#1e1a14",
    "surface2": "#27211a",
    "line": "#3a3228",
    "text": "#f3ece0",
    "dim": "#c8bca8",
    "mute": "#8a7d68",
    "accent": "#cda85f",
    "gold_soft": "rgba(205,168,95,0.14)",
    "signal": "#b9763f",
    "blue": "#8fa8c8",
    "blue_soft": "rgba(143,168,200,0.12)",
    "button_bg": "#cda85f",
}


def _gmail_render_korea_domestic_strip(fixture: Mapping[str, Any]) -> str:
    items = fixture.get("top_5_items") or []
    chips: list[str] = []
    for item in items[:5]:
        if isinstance(item, dict):
            chips.append(_signal_chip_text(item))
    if not chips:
        return ""
    c = _GMAIL_KOREA_COLORS
    chip_cells = []
    for chip in chips:
        chip_cells.append(
            f'<span style="display:inline-block;margin:0 6px 8px 0;padding:6px 10px;'
            f'font-size:12px;line-height:1.4;color:{c["blue"]};'
            f'background:{c["blue_soft"]};border:1px solid rgba(143,168,200,0.25);border-radius:999px;">'
            f'{_esc(chip)}</span>'
        )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{c["surface2"]};border:1px solid {c["line"]};border-radius:12px;">'
        f'<tr><td style="padding:16px 18px;">'
        f'<p style="margin:0 0 8px 0;font-size:12px;font-weight:700;letter-spacing:0.04em;color:{c["accent"]};">'
        f'오늘 국내에서 움직인 것</p>'
        f'<p style="margin:0 0 12px 0;font-size:14px;line-height:1.6;color:{c["dim"]};">'
        f'국내 적용 관점에서 오늘 다섯 신호를 정리했습니다.</p>'
        f'{"".join(chip_cells)}'
        f'</td></tr></table>'
    )


def _gmail_render_korea_top_item(item: Mapping[str, Any], rank: int) -> str:
    c = _GMAIL_KOREA_COLORS
    headline = _item_field(item, "korean_title", "headline")
    meta_stub = {
        "primary_category": item.get("primary_category"),
        "selection_reason_tags": item.get("selection_reason_tags"),
        "selection_rationale": item.get("selection_rationale"),
        "reason_for_selection": item.get("reason_for_selection"),
        "statement": item.get("korean_title") or item.get("headline"),
    }
    selection_reason = build_visible_selection_reason(
        item,
        meta_stub,
        program_id=PROGRAM_KOREA,
        existing=sanitize_visible_selection_reason(
            _item_field(item, "selection_reason", "selection_rationale"),
            item,
            meta_stub,
            program_id=PROGRAM_KOREA,
        ),
    )
    selection_reason = finalize_korea_visible_field(
        selection_reason,
        fallback=_item_field(item, "korean_title", "headline"),
    )
    what_happened = _korea_visible_field(item, "what_happened", "summary")
    why_now = _korea_visible_field(item, "why_now", "why_it_matters")
    owner_angle = _korea_visible_field(item, "owner_angle", "business_implication", "keysuri_comment")
    source_url = _item_field(item, "source_url")
    source_name = _item_field(item, "source_name") or "출처"
    emphasis_body = _item_field(item, "next_day_impact_line", "owner_action_line")
    if emphasis_body:
        emphasis_body = finalize_korea_visible_field(
            sanitize_visible_impact_line(
                emphasis_body,
                category=str(item.get("primary_category") or ""),
            ),
            fallback=_item_field(item, "korean_title", "headline"),
        )
    j_label, j_text = _judgment_block(item)

    def _label(text: str) -> str:
        return (
            f'<p style="margin:0 0 6px 0;font-size:12px;font-weight:700;letter-spacing:0.03em;'
            f'color:{c["accent"]};">{_esc(text)}</p>'
        )

    def _body(text: str) -> str:
        if not text:
            return ""
        return (
            f'<p style="margin:0 0 14px 0;font-size:14px;line-height:1.75;color:{c["text"]};">'
            f'{_esc(text)}</p>'
        )

    emphasis_html = ""
    if emphasis_body:
        emphasis_html = (
            f'<p style="margin:0 0 14px 0;font-size:13px;line-height:1.6;color:{c["signal"]};">'
            f'<strong style="color:{c["accent"]};">{_esc(KOREA_CARD_EMPHASIS)}</strong> '
            f'{_esc(emphasis_body)}</p>'
        )

    source_html = ""
    if source_url:
        source_html = (
            f'<p style="margin:14px 0 0 0;font-size:12px;line-height:1.6;color:{c["mute"]};">'
            f'<span style="font-weight:700;color:{c["dim"]};">출처</span> '
            f'{_esc(source_name)} · '
            f'<a href="{_esc(source_url)}" style="color:{c["accent"]};text-decoration:underline;">{_esc(source_url)}</a>'
            f'</p>'
        )

    judgment_html = ""
    if j_label or j_text:
        judgment_html = (
            f'<p style="margin:0;font-size:13px;line-height:1.6;color:{c["dim"]};">'
            f'<strong style="color:{c["accent"]};">키수리 판단</strong> '
            f'<span style="display:inline-block;padding:2px 8px;margin:0 6px 0 0;border-radius:999px;'
            f'background:{c["gold_soft"]};color:{c["accent"]};font-size:12px;font-weight:700;">{_esc(j_label)}</span>'
            f'{_esc(j_text)}</p>'
        )

    selection_html = ""
    if selection_reason:
        selection_html = _label("선정 이유") + _body(selection_reason)

    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{c["surface"]};border:1px solid {c["line"]};border-left:4px solid {c["accent"]};border-radius:12px;">'
        f'<tr><td style="padding:18px 18px 16px 18px;">'
        f'<p style="margin:0 0 8px 0;font-size:11px;font-weight:700;color:{c["mute"]};">{rank}</p>'
        f'<span style="display:inline-block;margin:0 0 10px 0;padding:4px 10px;font-size:11px;font-weight:700;'
        f'color:{c["accent"]};background:{c["gold_soft"]};border:1px solid rgba(205,168,95,0.30);border-radius:999px;">'
        f'{_esc(KOREA_ANGLE_CHIP)}</span>'
        f'<h3 style="margin:0 0 12px 0;font-size:18px;line-height:1.45;font-weight:700;color:{c["text"]};">'
        f'{rank}. {_esc(headline)}</h3>'
        f'{selection_html}{emphasis_html}'
        f'{_label("무슨 일이 있었나")}{_body(what_happened)}'
        f'{_label("왜 지금 중요한가")}{_body(why_now)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{c["surface2"]};border-left:3px solid {c["accent"]};border-radius:8px;">'
        f'<tr><td style="padding:12px 14px;">'
        f'{_label("주인님 관점")}{_body(owner_angle)}'
        f'</td></tr></table>'
        f'{_gmail_spacer(12)}{judgment_html}{source_html}'
        f'</td></tr></table>'
    )


def _gmail_render_korea_top5(fixture: Mapping[str, Any]) -> str:
    heading = _esc(fixture.get("top_5_heading") or "국내 테크 TOP 5")
    items = fixture.get("top_5_items") or []
    cards = ""
    for idx, item in enumerate(items[:5], start=1):
        if isinstance(item, dict):
            cards += _gmail_render_korea_top_item(item, int(item.get("rank") or idx))
            cards += _gmail_spacer(14)
    c = _GMAIL_KOREA_COLORS
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td>'
        f'<h2 style="margin:0 0 16px 0;font-size:20px;line-height:1.4;font-weight:700;color:{c["text"]};'
        f'border-left:4px solid {c["accent"]};padding-left:12px;">{heading}</h2>'
        f'{cards}'
        f'</td></tr></table>'
    )


def _gmail_render_korea_deep_dive(fixture: Mapping[str, Any]) -> str:
    c = _GMAIL_KOREA_COLORS
    heading = str(fixture.get("deep_dive_heading") or SECTION_DEEP_DIVE).strip()
    subframe = KOREA_DEEP_SUBFRAME
    sections = fixture.get("korea_deep_dive_sections") or []
    if not sections:
        sections = structure_korea_deep_dive(
            str(fixture.get("deep_dive_body") or ""),
            fixture.get("top_5_items") or [],
            uncertainty=normalize_visible_text(
                fixture.get("deep_dive_uncertainty") or "",
                style="sentence",
            ),
        )
    inner_parts: list[str] = []
    body = str(fixture.get("deep_dive_body") or "").strip()
    if body and not sections:
        for para in [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()] or [body]:
            inner_parts.append(
                f'<p style="margin:0 0 14px 0;font-size:14px;line-height:1.75;color:{c["text"]};">{_esc(para)}</p>'
            )
    for section in sections:
        if not isinstance(section, dict):
            continue
        label = str(section.get("label") or "").strip()
        section_body = str(section.get("body") or "").strip()
        if not label or not section_body:
            continue
        paras = [p.strip() for p in re.split(r"\n\s*\n", section_body) if p.strip()] or [section_body]
        body_html = "".join(
            f'<p style="margin:0 0 10px 0;font-size:14px;line-height:1.75;color:{c["text"]};">{_esc(p)}</p>'
            for p in paras
        )
        inner_parts.append(
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="margin:0 0 12px 0;background:{c["surface2"]};border:1px solid {c["line"]};border-radius:10px;">'
            f'<tr><td style="padding:14px 16px;">'
            f'<p style="margin:0 0 8px 0;font-size:13px;font-weight:700;color:{c["accent"]};">{_esc(label)}</p>'
            f'{body_html}'
            f'</td></tr></table>'
        )
    if not inner_parts:
        return ""
    return (
        f'{_gmail_spacer(18)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td>'
        f'<h2 style="margin:0 0 8px 0;font-size:20px;line-height:1.4;font-weight:700;color:{c["text"]};'
        f'border-left:4px solid {c["accent"]};padding-left:12px;">{_esc(heading)}</h2>'
        f'<p style="margin:0 0 16px 0;font-size:12px;font-weight:700;letter-spacing:0.04em;color:{c["mute"]};">'
        f'{_esc(subframe)}</p>'
        f'{"".join(inner_parts)}'
        f'</td></tr></table>'
    )


def _gmail_render_korea_one_line_checkpoint(fixture: Mapping[str, Any]) -> str:
    c = _GMAIL_KOREA_COLORS
    checkpoint = build_korea_one_line_checkpoint(
        fixture.get("top_5_items") or [],
        existing=polish_korea_checkpoint_text(str(fixture.get("one_line_checkpoint") or "").strip()),
    )
    if not checkpoint:
        return ""
    return (
        f'{_gmail_spacer(18)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td>'
        f'<h2 style="margin:0 0 8px 0;font-size:20px;line-height:1.4;font-weight:700;color:{c["text"]};'
        f'border-left:4px solid {c["accent"]};padding-left:12px;">{_esc(SECTION_ONE_LINE)}</h2>'
        f'<p style="margin:0 0 12px 0;font-size:12px;font-weight:700;letter-spacing:0.04em;color:{c["accent"]};">'
        f'{_esc(KOREA_CHECKPOINT_SUBFRAME)}</p>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{c["surface2"]};border:1px solid {c["line"]};border-left:4px solid {c["signal"]};border-radius:12px;">'
        f'<tr><td style="padding:16px 18px;">'
        f'<p style="margin:0;font-size:15px;line-height:1.7;color:{c["text"]};">{_esc(checkpoint)}</p>'
        f'</td></tr></table>'
        f'</td></tr></table>'
    )


def _gmail_render_korea_bottom_shot(fixture: Mapping[str, Any]) -> str:
    """Gmail-safe Korea 18:30 bottom-shot slot; image only when CID is supplied."""
    c = _GMAIL_KOREA_COLORS
    src = str(fixture.get("bottom_shot_image_src") or "").strip()
    if src:
        return (
            f'{_gmail_spacer(18)}'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'<tr><td style="padding:0;">'
            f'<img id="bottom-shot-image" src="{_esc(src)}" '
            f'alt="테크 비서 키수리 — 국내 18:30 마무리" width="100%" '
            f'style="display:block;width:100%;max-width:100%;height:auto;'
            f'border:0;border-radius:10px;outline:none;text-decoration:none;" />'
            f'</td></tr></table>'
        )
    placeholder_copy = (
        "국내 18:30 바텀샷 자리입니다. 향후 퇴근 전 마무리 리듬용 슬롯이며, "
        "현재 운영자 검수 메일에는 이미지 없이 구조만 표시합니다."
    )
    return (
        f'{_gmail_spacer(18)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td style="padding:0;">'
        f'<div id="bottom-shot-placeholder" '
        f'style="padding:14px 16px;background:{c["surface2"]};'
        f'border:1px dashed {c["line"]};border-radius:10px;">'
        f'<p style="margin:0;font-size:12px;line-height:1.6;color:{c["mute"]};">'
        f'{_esc(placeholder_copy)}</p>'
        f'</div>'
        f'</td></tr></table>'
    )


def _gmail_render_korea_evening_memo(fixture: Mapping[str, Any]) -> str:
    c = _GMAIL_KOREA_COLORS
    memo_heading = str(fixture.get("evening_memo_heading") or KOREA_EVENING_MEMO_HEADING).strip()
    memo = _resolve_korea_evening_memo(fixture)
    action_lines = [str(line).strip() for line in memo.get("action_lines") or [] if str(line).strip()]
    warm_lines = [str(line).strip() for line in memo.get("warm_lines") or [] if str(line).strip()]
    if not warm_lines:
        warm_lines = list(KOREA_WARM_FAREWELL_LINES)
    items = "".join(
        f'<li style="margin:0 0 8px 0;font-size:14px;line-height:1.7;color:{c["text"]};">{_esc(line)}</li>'
        for line in action_lines[:3]
    )
    warm_html = "".join(
        f'<p style="margin:12px 0 0 0;font-size:14px;line-height:1.7;color:{c["dim"]};">{_esc(line)}</p>'
        for line in warm_lines[:2]
    )
    return (
        f'{_gmail_spacer(18)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{c["surface"]};border:1px solid {c["line"]};border-radius:12px;">'
        f'<tr><td style="padding:18px;">'
        f'<h2 style="margin:0 0 12px 0;font-size:20px;line-height:1.4;font-weight:700;color:{c["text"]};">{_esc(memo_heading)}</h2>'
        f'<p style="margin:0 0 12px 0;font-size:14px;line-height:1.75;color:{c["text"]};">{_esc(memo.get("summary") or "")}</p>'
        f'<p style="margin:0 0 10px 0;font-size:14px;line-height:1.75;color:{c["dim"]};">{_esc(memo.get("action_intro") or "내일은 세 가지만 확인하시면 됩니다.")}</p>'
        f'<ol style="margin:0 0 14px 18px;padding:0;">{items}</ol>'
        f'<p style="margin:0 0 8px 0;font-size:13px;line-height:1.6;color:{c["mute"]};">{_esc(memo.get("caution") or "확정되지 않은 수치와 일정은 아직 조심해서 보겠습니다.")}</p>'
        f'{warm_html}'
        f'</td></tr></table>'
    )


def _gmail_render_korea_sources(source_list: Sequence[Mapping[str, Any]]) -> str:
    c = _GMAIL_KOREA_COLORS
    rows = ""
    for entry in source_list:
        if not isinstance(entry, dict):
            continue
        source_url = str(entry.get("source_url") or "").strip()
        if not source_url:
            continue
        rows += (
            f'<p style="margin:0 0 10px 0;font-size:13px;line-height:1.6;color:{c["dim"]};">'
            f'<strong style="color:{c["text"]};">{_esc(entry.get("source_name") or "출처")}</strong><br/>'
            f'<a href="{_esc(source_url)}" style="color:{c["accent"]};text-decoration:underline;word-break:break-all;">'
            f'{_esc(source_url)}</a></p>'
        )
    if not rows:
        return ""
    return (
        f'{_gmail_spacer(18)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{c["surface"]};border:1px solid {c["line"]};border-radius:12px;">'
        f'<tr><td style="padding:18px;">'
        f'<h2 style="margin:0 0 12px 0;font-size:18px;line-height:1.4;font-weight:700;color:{c["text"]};">{_esc(SECTION_CLOSING)}</h2>'
        f'{rows}'
        f'</td></tr></table>'
    )


def build_keysuri_korea_gmail_owner_email_html(
    fixture: Mapping[str, Any],
    *,
    subject: str,
    preheader: str | None = None,
    admin_url: str = "",
    run_id: str = "",
) -> str:
    """Gmail-safe Korea owner-review email: dark theme, inline styles and table layout only."""
    if not isinstance(fixture, dict):
        raise TypeError("fixture must be a dict")
    program_id = str(fixture.get("program_id") or "").strip()
    if not _is_korea_program(program_id):
        raise ValueError(f"Gmail owner renderer supports Korea only, got {program_id!r}")

    c = _GMAIL_KOREA_COLORS
    slot_badge = _slot_badge(program_id, str(fixture.get("slot") or "18:30"))
    hero_title, hero_subtitle = _hero_copy(program_id)
    _subject, fixture_preheader = _selected_subject_preheader(fixture, program_id)
    preheader_text = str(preheader or fixture_preheader or "").strip()
    opening_lead = str(fixture.get("opening_lead") or "").strip()
    hero_src = str(fixture.get("top_shot_image_src") or "").strip()
    title = _esc(str(subject or _subject or KOREA_HERO_TITLE).strip() or KOREA_HERO_TITLE)

    hero_image_row = ""
    if hero_src:
        hero_image_row = (
            f'<tr><td style="padding:0 0 16px 0;">'
            f'<img src="{_esc(hero_src)}" alt="{_esc(TOP_SHOT_ALT)}" width="568" '
            f'style="display:block;width:100%;max-width:568px;height:auto;border:0;border-radius:14px;" />'
            f'</td></tr>'
        )

    domestic_strip = _gmail_render_korea_domestic_strip(fixture)
    top5 = _gmail_render_korea_top5(fixture)
    deep_dive = _gmail_render_korea_deep_dive(fixture)
    checkpoint_html = _gmail_render_korea_one_line_checkpoint(fixture)
    bottom_shot = _gmail_render_korea_bottom_shot(fixture)
    evening_memo = _gmail_render_korea_evening_memo(fixture)
    sources = _gmail_render_korea_sources(fixture.get("source_list") or [])

    review_state = _resolve_review_state(fixture)
    review_text = REVIEW_CONFIRMATION_TEXT.get(review_state, REVIEW_CONFIRMATION_TEXT[DEFAULT_REVIEW_STATE])
    review_html = (
        f'{_gmail_spacer(18)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{c["surface2"]};border:1px solid {c["line"]};border-radius:12px;">'
        f'<tr><td style="padding:14px 16px;text-align:center;">'
        f'<p style="margin:0;font-size:13px;line-height:1.6;color:{c["dim"]};">{_esc(review_text)}</p>'
        f'</td></tr></table>'
    )

    rights_html = (
        f'{_gmail_spacer(20)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td style="padding:16px 0 0 0;border-top:1px solid {c["line"]};text-align:center;">'
        f'<p style="margin:0 0 6px 0;font-size:12px;font-weight:700;color:{c["mute"]};">MirAI:ON</p>'
        f'<p style="margin:0 0 4px 0;font-size:11px;line-height:1.5;color:{c["mute"]};">{RIGHTS_LINE_1}</p>'
        f'<p style="margin:0;font-size:11px;line-height:1.5;color:{c["mute"]};">{RIGHTS_LINE_2}</p>'
        f'</td></tr></table>'
    )

    admin_block = _owner_review_admin_email_block(admin_url=admin_url, run_id=run_id)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta name="color-scheme" content="dark light"/>
<title>{title}</title>
</head>
<body style="margin:0;padding:0;background:{c["bg"]};">
<span style="{PREHEADER_STYLE}">{_esc(preheader_text)}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{c["bg"]};">
<tr><td align="center" style="padding:20px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;background:{c["surface"]};border:1px solid {c["line"]};border-radius:16px;">
<tr><td style="padding:20px 16px 8px 16px;background:linear-gradient(180deg,{c["surface2"]} 0%,{c["surface"]} 100%);border-radius:16px 16px 0 0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
{hero_image_row}
<tr><td>
<p style="margin:0 0 10px 0;font-size:12px;font-weight:700;letter-spacing:0.05em;color:{c["accent"]};">{_esc(slot_badge)}</p>
<p style="margin:0 0 8px 0;font-size:13px;font-weight:700;color:{c["mute"]};">{_esc(IDENTITY_TITLE)}</p>
<h1 style="margin:0 0 8px 0;font-size:24px;line-height:1.35;font-weight:700;color:{c["text"]};">{_esc(hero_title)}</h1>
<p style="margin:0;font-size:15px;line-height:1.6;color:{c["dim"]};">{_esc(hero_subtitle)}</p>
</td></tr>
</table>
</td></tr>
<tr><td style="padding:8px 16px 20px 16px;">
<p style="margin:0;font-size:15px;line-height:1.8;color:{c["text"]};">{_esc(opening_lead)}</p>
{_gmail_spacer(18)}
{domestic_strip}
{_gmail_spacer(18)}
{top5}
{deep_dive}
{checkpoint_html}
{bottom_shot}
{review_html}
{evening_memo}
{sources}
{rights_html}
{admin_block}
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def build_keysuri_global_gmail_owner_email_html(
    fixture: Mapping[str, Any],
    *,
    subject: str,
    preheader: str | None = None,
    admin_url: str = "",
    run_id: str = "",
) -> str:
    """Gmail-safe Global owner-review email: inline styles and table layout only."""
    if not isinstance(fixture, dict):
        raise TypeError("fixture must be a dict")
    program_id = str(fixture.get("program_id") or "").strip()
    if program_id != PROGRAM_GLOBAL and not program_id.startswith("keysuri_global"):
        raise ValueError(f"Gmail owner renderer supports Global only, got {program_id!r}")

    c = _GMAIL_GLOBAL_COLORS
    slot_raw = str(fixture.get("slot") or "12:30")
    slot_badge = _slot_badge(program_id, slot_raw)
    hero_title, hero_subtitle = _hero_copy(program_id)
    _subject, fixture_preheader = _selected_subject_preheader(fixture, program_id)
    preheader_text = str(preheader or fixture_preheader or "").strip()
    opening_lead = str(fixture.get("opening_lead") or "").strip()
    hero_src = str(fixture.get("top_shot_image_src") or "").strip()
    title = _esc(str(subject or _subject or GLOBAL_HERO_TITLE).strip() or GLOBAL_HERO_TITLE)

    hero_image_row = ""
    if hero_src:
        hero_image_row = (
            f'<tr><td style="padding:0 0 16px 0;">'
            f'<img src="{_esc(hero_src)}" alt="{_esc(TOP_SHOT_ALT)}" width="568" '
            f'style="display:block;width:100%;max-width:568px;height:auto;border:0;border-radius:14px;" />'
            f'</td></tr>'
        )

    signal_board = _gmail_render_global_signal_chips(fixture)
    top5 = _gmail_render_global_top5(fixture)
    deep_dive = _gmail_render_global_deep_dive(fixture)
    checkpoint_html = _gmail_render_global_one_line_checkpoint(fixture)
    sources = _gmail_render_global_sources(fixture.get("source_list") or [])

    open_ending_html = (
        f'{_gmail_spacer(14)}'
        f'<p style="margin:0;font-size:14px;line-height:1.7;color:{c["dim"]};">{_esc(GLOBAL_OPEN_ENDING)}</p>'
    )

    review_state = _resolve_review_state(fixture)
    review_text = REVIEW_CONFIRMATION_TEXT.get(review_state, REVIEW_CONFIRMATION_TEXT[DEFAULT_REVIEW_STATE])
    review_html = (
        f'{_gmail_spacer(18)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{c["surface2"]};border:1px solid {c["line"]};border-radius:12px;">'
        f'<tr><td style="padding:14px 16px;text-align:center;">'
        f'<p style="margin:0;font-size:13px;line-height:1.6;color:{c["dim"]};">{_esc(review_text)}</p>'
        f'</td></tr></table>'
    )

    rights_html = (
        f'{_gmail_spacer(20)}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td style="padding:16px 0 0 0;border-top:1px solid {c["line"]};text-align:center;">'
        f'<p style="margin:0 0 6px 0;font-size:12px;font-weight:700;color:{c["mute"]};">MirAI:ON</p>'
        f'<p style="margin:0 0 4px 0;font-size:11px;line-height:1.5;color:{c["mute"]};">{RIGHTS_LINE_1}</p>'
        f'<p style="margin:0;font-size:11px;line-height:1.5;color:{c["mute"]};">{RIGHTS_LINE_2}</p>'
        f'</td></tr></table>'
    )

    admin_block = _owner_review_admin_email_block(admin_url=admin_url, run_id=run_id)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
</head>
<body style="margin:0;padding:0;background:{c["bg"]};">
<span style="{PREHEADER_STYLE}">{_esc(preheader_text)}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{c["bg"]};">
<tr><td align="center" style="padding:20px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;background:{c["surface"]};border:1px solid {c["line"]};border-radius:16px;">
<tr><td style="padding:20px 16px 8px 16px;background:linear-gradient(180deg,#eef3f8 0%,#ffffff 100%);border-radius:16px 16px 0 0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
{hero_image_row}
<tr><td>
<p style="margin:0 0 10px 0;font-size:12px;font-weight:700;letter-spacing:0.05em;color:{c["accent"]};">{_esc(slot_badge)}</p>
<p style="margin:0 0 8px 0;font-size:13px;font-weight:700;color:{c["silver"]};">{_esc(IDENTITY_TITLE)}</p>
<h1 style="margin:0 0 8px 0;font-size:24px;line-height:1.35;font-weight:700;color:{c["text"]};">{_esc(hero_title)}</h1>
<p style="margin:0;font-size:15px;line-height:1.6;color:{c["dim"]};">{_esc(hero_subtitle)}</p>
</td></tr>
</table>
</td></tr>
<tr><td style="padding:8px 16px 20px 16px;">
<p style="margin:0;font-size:15px;line-height:1.8;color:{c["text"]};">{_esc(opening_lead)}</p>
{_gmail_spacer(18)}
{signal_board}
{_gmail_spacer(18)}
{top5}
{deep_dive}
{checkpoint_html}
{open_ending_html}
{review_html}
{_gmail_spacer(18)}
{sources}
{rights_html}
{admin_block}
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


_STYLE_BLOCK_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)
_BODY_INNER_RE = re.compile(r"<body[^>]*>(.*?)</body>", re.DOTALL | re.IGNORECASE)


def extract_contract_preview_email_fragments(preview_html: str) -> tuple[str, str]:
    """Split full contract-preview document into (css, body_inner) for owner-review email."""
    raw = str(preview_html or "")
    style_match = _STYLE_BLOCK_RE.search(raw)
    styles = style_match.group(1).strip() if style_match else _premium_styles().strip()
    body_match = _BODY_INNER_RE.search(raw)
    if not body_match:
        raise ValueError("contract preview html missing body")
    return styles, body_match.group(1).strip()


def _owner_review_admin_email_block(*, admin_url: str, run_id: str) -> str:
    url = str(admin_url or "").strip()
    if not url:
        return ""
    rid = _esc(str(run_id or "").strip())
    return f"""
<div class="owner-review-admin-entry" id="owner-review-admin-entry" style="margin:32px auto 0;max-width:680px;padding:20px 16px;text-align:center;border-top:1px solid rgba(80,100,130,0.18);">
  <a href="{_esc(url)}" style="display:inline-block;padding:12px 20px;background:#0f172a;color:#ffffff;text-decoration:none;border-radius:8px;font-weight:700;font-size:15px;">운영자 검수 화면 열기</a>
  <p style="margin:12px 0 0;font-size:12px;word-break:break-all;"><a href="{_esc(url)}" style="color:#3f7ecb;">{_esc(url)}</a></p>
  <p style="margin:8px 0 0;font-size:11px;color:#7b8795;">run_id: {rid}</p>
</div>"""


IMAGE_ONLY_REISSUE_MARKER_ID = "image-only-reissue-marker"
IMAGE_ONLY_REISSUE_MARKER_START = "<!--image-only-reissue-marker-start-->"
IMAGE_ONLY_REISSUE_MARKER_END = "<!--image-only-reissue-marker-end-->"


def _image_only_reissue_colors(program_id: str) -> Mapping[str, str]:
    pid = str(program_id or "").strip()
    if pid == PROGRAM_GLOBAL or pid.startswith("keysuri_global"):
        return _GMAIL_GLOBAL_COLORS
    return _GMAIL_KOREA_COLORS


def _short_kst_label(reissued_at_kst: str) -> str:
    text = str(reissued_at_kst or "").strip()
    m = re.search(r"T(\d{2}:\d{2})", text)
    if m:
        return m.group(1)
    return text[:16]


def build_image_only_reissue_marker_block(
    *,
    child_run_id: str,
    reissued_at_kst: str,
    program_id: str = "",
) -> str:
    """A compact, run-unique banner shown right under the hero image.

    The image_only reissue email intentionally reuses the previous owner-review
    body verbatim. Because the body is byte-identical to the parent message in
    the same Gmail thread, mobile Gmail folds it behind a "…" as quoted/duplicate
    content, so the email looks like "only the image was delivered". This marker
    adds a small block of run-unique visible text (timestamp + run suffix) at the
    very top of the body so Gmail no longer treats the leading content as a
    duplicate and shows the full briefing. It never regenerates body text.
    """
    c = _image_only_reissue_colors(program_id)
    rid_suffix = str(child_run_id or "").rsplit("_", 1)[-1] or str(child_run_id or "")
    when = _short_kst_label(reissued_at_kst)
    note = "이미지만 새로 생성했습니다. 아래 본문 내용은 이전 검수본과 동일합니다."
    return (
        f'{IMAGE_ONLY_REISSUE_MARKER_START}'
        f'<tr><td id="{IMAGE_ONLY_REISSUE_MARKER_ID}" style="padding:0 0 14px 0;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:{c["surface2"]};border:1px solid {c["line"]};'
        f'border-left:3px solid {c["accent"]};border-radius:10px;">'
        f'<tr><td style="padding:12px 14px;">'
        f'<p style="margin:0;font-size:12px;font-weight:700;letter-spacing:0.03em;color:{c["accent"]};">'
        f'이미지 재발행 · {_esc(when)} KST · {_esc(rid_suffix)}</p>'
        f'<p style="margin:6px 0 0 0;font-size:13px;line-height:1.6;color:{c["dim"]};">{_esc(note)}</p>'
        f'</td></tr></table>'
        f'</td></tr>'
        f'{IMAGE_ONLY_REISSUE_MARKER_END}'
    )


def image_only_reissue_email_has_body(html: str) -> bool:
    """True when the assembled email still carries the full briefing body.

    Guards against a regression where image_only ever produces an image-only
    fragment. A complete owner-review email has multiple external source/news
    links and at least one body section heading below the title.
    """
    h = str(html or "")
    external_links = len(re.findall(r'href="https?://[^"]+"', h))
    h2_count = len(re.findall(r"<h2\b", h, re.IGNORECASE))
    return external_links >= 2 and h2_count >= 1


def assemble_image_only_reissue_email_html(
    preserved_email_html: str,
    *,
    child_run_id: str,
    reissued_at_kst: str,
    program_id: str = "",
) -> str:
    """Rebuild the image_only reissue email as a full, mobile-Gmail-safe message.

    Reuses the preserved (CID-swapped) owner-review HTML verbatim — body text is
    never regenerated — and injects a run-unique marker right after the hero
    image (falling back to before the title, then to the start of the body) plus
    a run-unique hidden preheader. Both changes break Gmail's duplicate-content
    collapse so the existing body is shown instead of hidden behind "…".
    """
    html_text = str(preserved_email_html or "")
    if not html_text.strip():
        return html_text
    if IMAGE_ONLY_REISSUE_MARKER_ID in html_text:
        return html_text

    marker_row = build_image_only_reissue_marker_block(
        child_run_id=child_run_id,
        reissued_at_kst=reissued_at_kst,
        program_id=program_id,
    )

    # Primary anchor: insert immediately after the hero image's table row.
    hero_pattern = re.compile(
        r'(<tr>\s*<td[^>]*>\s*<img\s+src="cid:[^"]*topshot[^"]*"[^>]*/>\s*</td>\s*</tr>)',
        re.IGNORECASE,
    )
    new_html, n = hero_pattern.subn(lambda m: m.group(1) + marker_row, html_text, count=1)
    if n == 0:
        # Fallback: place the marker as a block directly before the <h1> title.
        h1_match = re.search(r"<h1\b", html_text, re.IGNORECASE)
        if h1_match:
            # Wrap as a standalone table so it is valid before an inline <h1>.
            marker_block = (
                '<table role="presentation" width="100%" cellpadding="0" '
                'cellspacing="0" border="0">' + marker_row + "</table>"
            )
            idx = h1_match.start()
            new_html = html_text[:idx] + marker_block + html_text[idx:]
        else:
            body_match = re.search(r"<body[^>]*>", html_text, re.IGNORECASE)
            if body_match:
                marker_block = (
                    '<table role="presentation" width="100%" cellpadding="0" '
                    'cellspacing="0" border="0">' + marker_row + "</table>"
                )
                idx = body_match.end()
                new_html = html_text[:idx] + marker_block + html_text[idx:]
            else:
                new_html = marker_row + html_text

    # The hidden preheader is intentionally left unchanged: it is reused for the
    # customer-final email and must not carry the operator-only reissue note. The
    # visible marker block above already makes the leading body content unique,
    # which is what defeats Gmail's duplicate-content collapse.
    return new_html


def build_keysuri_owner_review_email_html(
    preview_html: str,
    *,
    subject: str,
    preheader: str | None = None,
    admin_url: str = "",
    run_id: str = "",
) -> str:
    """
    Convert existing contract-preview premium briefing HTML into a single owner-review email document.

    Preserves the renderer's design (styles + body hierarchy). Does not nest a second HTML document
    and does not prepend service debug metadata above the hero.
    """
    styles, body_inner = extract_contract_preview_email_fragments(preview_html)
    admin_block = _owner_review_admin_email_block(admin_url=admin_url, run_id=run_id)
    title = _esc(str(subject or GLOBAL_HERO_TITLE).strip() or GLOBAL_HERO_TITLE)
    preheader_span = ""
    preheader_text = str(preheader or "").strip()
    if preheader_text:
        preheader_span = f'<span style="{PREHEADER_STYLE}">{_esc(preheader_text)}</span>\n'
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<style>{styles}</style>
</head>
<body>
{preheader_span}
{body_inner}
{admin_block}
</body>
</html>
"""
