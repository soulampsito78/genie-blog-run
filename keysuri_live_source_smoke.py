"""Kee-Suri live public RSS source-pack smoke (minimal — not production automation)."""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, MutableMapping, Optional, Sequence, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from keysuri_approved_image_assets import (
    classify_image_selection,
    default_top_role_for_program,
    match_registry_asset,
    resolve_approved_hero_image_path,
)
from keysuri_briefing_content_enricher import enrich_generated_briefing_content
from keysuri_contract_preview_fixture import (
    build_contract_preview_fixture_from_generated,
    resolve_top_shot_image_path,
    top_shot_src_for_html,
)
from keysuri_contract_preview_quality import validate_contract_preview_visible_body
from keysuri_preview_validation_report import validate_keysuri_contract_preview
from keysuri_contract_preview_renderer import (
    IMAGE_MODE_PREVIEW,
    prepare_contract_preview_fixture,
    render_keysuri_contract_preview_html,
)
from keysuri_generation_prompt import (
    extract_json_object_from_model_text,
    generate_keysuri_body_raw_text,
    generation_contract_record,
    parse_keysuri_generated_response,
    sanitize_generation_contract_record,
)
from keysuri_gemini_client import KeysuriGeminiError, call_keysuri_gemini_text
from keysuri_html_preview_validation import validate_keysuri_html_preview
from keysuri_global_signal_scoring import (
    CATEGORY_KO_LABELS,
    apply_scored_selection_to_source_pack,
    classify_global_tech_category,
    score_candidates_from_source_pack,
    write_global_top5_selection_report,
)
from keysuri_korea_signal_scoring import (
    KOREA_TECH_CATEGORIES,
    apply_scored_selection_to_source_pack as apply_korea_scored_selection_to_source_pack,
    load_global_selection_report,
    score_candidates_from_source_pack as score_korea_candidates_from_source_pack,
    write_korea_top5_selection_report,
)
from keysuri_prompt_input import build_keysuri_prompt_input
from keysuri_news_contract import (
    _claim_is_qualified,
    _claim_to_news_item,
    validate_top_5_news_block,
)
from keysuri_renderer import render_keysuri_owner_review_html
from keysuri_source_text_normalization import (
    normalize_feed_source_text,
    normalize_keysuri_source_pack,
)
from sent_news_dedup_gate import (
    canonicalize_url,
    recent_log_duplicate_reason,
    select_with_diversity_caps,
)
from sent_news_log_store import recent_sent_news_log
from memory_observability import record_memory_stage

PROGRAM_GLOBAL = "keysuri_global_tech"
PROGRAM_KOREA = "keysuri_korea_tech"
SUPPORTED_PROGRAMS = (PROGRAM_GLOBAL, PROGRAM_KOREA)
logger = logging.getLogger(__name__)

DEFAULT_FETCH_TIMEOUT_SEC = 12
DEFAULT_ITEMS_PER_FEED = 3
DEFAULT_USER_AGENT = "GenieKeeSuriLiveSmoke/0.1 (+owner-review-smoke)"

# Smoke-only public RSS endpoints — no API keys; conservative fetch limits.
GLOBAL_TECH_SMOKE_FEEDS: Tuple[Dict[str, str], ...] = (
    {
        "feed_id": "google-ai-blog",
        "feed_name": "Google AI Blog",
        "feed_url": "https://blog.google/technology/ai/rss/",
        "source_tier": "T1_OFFICIAL_SECONDARY",
        "default_category": "ai_product",
    },
    {
        "feed_id": "openai-blog",
        "feed_name": "OpenAI News",
        "feed_url": "https://openai.com/blog/rss.xml",
        "source_tier": "T1_OFFICIAL_SECONDARY",
        "default_category": "ai_product",
    },
    {
        "feed_id": "microsoft-ai-blog",
        "feed_name": "Microsoft AI Blog",
        "feed_url": "https://blogs.microsoft.com/ai/feed/",
        "source_tier": "T1_OFFICIAL_SECONDARY",
        "default_category": "bigtech",
    },
    {
        "feed_id": "arstechnica-tech-lab",
        "feed_name": "Ars Technica Technology Lab",
        "feed_url": "https://feeds.arstechnica.com/arstechnica/technology-lab",
        "source_tier": "T3_QUALITY_PRESS",
        "default_category": "market_signal",
    },
    {
        "feed_id": "techcrunch-ai",
        "feed_name": "TechCrunch AI",
        "feed_url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "source_tier": "T3_QUALITY_PRESS",
        "default_category": "startup",
    },
    {
        "feed_id": "nvidia-blog",
        "feed_name": "NVIDIA Blog",
        "feed_url": "https://blogs.nvidia.com/feed/",
        "source_tier": "T1_OFFICIAL_SECONDARY",
        "default_category": "semiconductor_chip_infra",
    },
    {
        "feed_id": "ieee-spectrum",
        "feed_name": "IEEE Spectrum",
        "feed_url": "https://spectrum.ieee.org/rss/fulltext",
        "source_tier": "T3_QUALITY_PRESS",
        "default_category": "robotics_automation_manufacturing",
    },
    {
        "feed_id": "arstechnica-gadgets",
        "feed_name": "Ars Technica Gadgets",
        "feed_url": "https://feeds.arstechnica.com/arstechnica/gadgets",
        "source_tier": "T3_QUALITY_PRESS",
        "default_category": "hardware_device_display",
    },
    {
        "feed_id": "techcrunch-startups",
        "feed_name": "TechCrunch",
        "feed_url": "https://techcrunch.com/feed/",
        "source_tier": "T3_QUALITY_PRESS",
        "default_category": "policy_regulation_capital_supplychain",
    },
    {
        "feed_id": "datacenter-dynamics",
        "feed_name": "Datacenter Dynamics",
        "feed_url": "https://www.datacenterdynamics.com/en/rss/",
        "source_tier": "T3_QUALITY_PRESS",
        "default_category": "cybersecurity_cloud_datacenter",
    },
)

KOREA_TECH_ALLOWED_CATEGORIES: frozenset[str] = frozenset(
    {
        "korea_ai_enterprise",
        "korea_semiconductor",
        "korea_robotics_manufacturing",
        "korea_battery_energy",
        "korea_platform_cloud_saas",
        "korea_policy_regulation",
        "korea_startup_investment",
        "korea_big_company_strategy",
        "korea_consumer_mobility",
        "global_to_korea_translation",
    }
)

# Smoke-only public Korean RSS endpoints — verified fetch/parse in Unit 1 (2026-06-09).
KOREA_TECH_SMOKE_FEEDS: Tuple[Dict[str, str], ...] = (
    {
        "feed_id": "yna-industry",
        "feed_name": "연합뉴스 산업",
        "feed_url": "https://www.yna.co.kr/rss/industry.xml",
        "source_tier": "T2_TIER1_WIRE",
        "default_category": "korea_policy_regulation",
        "language": "ko",
        "region": "KR",
    },
    {
        "feed_id": "yna-economy",
        "feed_name": "연합뉴스 경제",
        "feed_url": "https://www.yna.co.kr/rss/economy.xml",
        "source_tier": "T2_TIER1_WIRE",
        "default_category": "korea_policy_regulation",
        "language": "ko",
        "region": "KR",
    },
    {
        "feed_id": "etnews-semiconductor",
        "feed_name": "전자신문 반도체",
        "feed_url": "https://www.etnews.com/rss/Section901.xml",
        "source_tier": "T2_TIER1_WIRE",
        "default_category": "korea_semiconductor",
        "language": "ko",
        "region": "KR",
    },
    {
        "feed_id": "thelec",
        "feed_name": "더lec",
        "feed_url": "https://www.thelec.kr/rss/allArticle.xml",
        "source_tier": "T2_TIER1_WIRE",
        "default_category": "korea_semiconductor",
        "language": "ko",
        "region": "KR",
    },
    {
        "feed_id": "electimes",
        "feed_name": "전기신문",
        "feed_url": "https://www.electimes.com/rss/allArticle.xml",
        "source_tier": "T2_TIER1_WIRE",
        "default_category": "korea_battery_energy",
        "language": "ko",
        "region": "KR",
    },
    {
        "feed_id": "irobotnews",
        "feed_name": "로봇신문",
        "feed_url": "https://www.irobotnews.com/rss/allArticle.xml",
        "source_tier": "T2_TIER1_WIRE",
        "default_category": "korea_robotics_manufacturing",
        "language": "ko",
        "region": "KR",
    },
    {
        "feed_id": "aitimes",
        "feed_name": "AI타임스",
        "feed_url": "https://www.aitimes.com/rss/allArticle.xml",
        "source_tier": "T3_QUALITY_PRESS",
        "default_category": "korea_ai_enterprise",
        "language": "ko",
        "region": "KR",
    },
    {
        "feed_id": "hankyung-it",
        "feed_name": "한국경제 IT",
        "feed_url": "https://www.hankyung.com/feed/it",
        "source_tier": "T3_QUALITY_PRESS",
        "default_category": "korea_platform_cloud_saas",
        "language": "ko",
        "region": "KR",
    },
    {
        "feed_id": "platum",
        "feed_name": "플래텀",
        "feed_url": "https://platum.kr/feed",
        "source_tier": "T3_QUALITY_PRESS",
        "default_category": "korea_startup_investment",
        "language": "ko",
        "region": "KR",
    },
    {
        "feed_id": "venturesquare",
        "feed_name": "벤처스퀘어",
        "feed_url": "https://www.venturesquare.net/feed",
        "source_tier": "T3_QUALITY_PRESS",
        "default_category": "korea_startup_investment",
        "language": "ko",
        "region": "KR",
    },
    {
        "feed_id": "samsung-newsroom",
        "feed_name": "삼성전자 뉴스룸",
        "feed_url": "https://news.samsung.com/kr/feed",
        "source_tier": "T1_OFFICIAL_SECONDARY",
        "default_category": "korea_big_company_strategy",
        "language": "ko",
        "region": "KR",
    },
    {
        "feed_id": "zdkorea",
        "feed_name": "ZDNet Korea",
        "feed_url": "https://feeds.feedburner.com/zdkorea",
        "source_tier": "T3_QUALITY_PRESS",
        "default_category": "global_to_korea_translation",
        "language": "ko",
        "region": "KR",
    },
)

SAMPLE_MARKER_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("Example Corp", "example_corp"),
    ("example.com", "example_com"),
    ("staged sample", "staged_sample"),
    ("sample source pack", "sample_source_pack"),
    ("sample only", "sample_only"),
    ("Do not treat as verified current news", "do_not_treat_verified"),
    ("No live fetch", "no_live_fetch"),
    ("No Gemini call", "no_gemini_call"),
    ("generated sample", "generated_sample"),
    ("global-t0-ai-official", "fixture_source_id_global_t0"),
    ("global-t2-market-wire", "fixture_source_id_market_wire"),
    ("global-t2-semi-wire", "fixture_source_id_semi_wire"),
    ("keysuri_global_sources.sample", "fixture_source_pack_path"),
    ("keysuri_korea_sources.sample", "fixture_source_pack_path_korea"),
)

GENERATION_PLACEHOLDER_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("generation_pending", "generation_pending"),
    ("source-led cards only", "source_led_cards_only"),
    ("generation 단계 이후 채워집니다", "generation_stage_placeholder"),
    ("Live source smoke — source-led cards only · 최종 문안이 아님", "live_source_led_notice"),
    ("Gemini 호출 전 · 최종 문안이 아님", "gemini_pending_notice"),
)

_SEND_CONFIRM_PHRASE = "SEND"
_DEFAULT_EMAIL_SUBJECT = "[KEYSURI test] Kee-Suri Global Tech live owner-review smoke"
_DEFAULT_GENERATED_EMAIL_SUBJECT = "[KEYSURI test] Kee-Suri Global Tech generated owner-review"


@dataclass
class FetchedFeedItem:
    feed_id: str
    feed_name: str
    feed_url: str
    source_tier: str
    default_category: str
    title: str
    link: str
    published_at: str
    summary: str


@dataclass
class SampleMarkerHit:
    code: str
    marker: str
    context: str


@dataclass
class LiveSourceSmokeResult:
    ok: bool
    program_id: str
    source_pack_path: str
    html_path: str
    fetched_item_count: int
    feed_urls_used: List[str]
    sample_marker_pass: bool
    sample_marker_hits: List[SampleMarkerHit] = field(default_factory=list)
    placeholder_gate_pass: bool = True
    placeholder_gate_hits: List[SampleMarkerHit] = field(default_factory=list)
    validation_status: str = "SKIP"
    validation_issues: List[str] = field(default_factory=list)
    send_attempted: bool = False
    send_success: bool = False
    send_block_reason: Optional[str] = None
    email_subject: Optional[str] = None
    email_recipients: List[str] = field(default_factory=list)
    email_report_path: Optional[str] = None
    called_gemini: bool = False
    fetched_live_news: bool = False
    use_gemini: bool = False
    parse_status: Optional[str] = None
    parse_meta: Dict[str, Any] = field(default_factory=dict)
    parse_diagnostics: Dict[str, Any] = field(default_factory=dict)
    generation_diagnostics: Dict[str, Any] = field(default_factory=dict)
    generation_contract: Dict[str, Any] = field(default_factory=dict)
    raw_response_path: Optional[str] = None
    generated_body: Dict[str, str] = field(default_factory=dict)
    generated_briefing: Optional[dict] = None
    contract_preview: bool = False
    image_path: Optional[str] = None
    image_source_mode: Optional[str] = None
    approved_asset_id: Optional[str] = None
    image_in_html: bool = False
    visible_body_quality_pass: bool = False
    visible_body_quality_issues: List[str] = field(default_factory=list)
    preview_validation: Dict[str, Any] = field(default_factory=dict)
    structural_gate_status: Optional[str] = None
    content_briefing_gate_status: Optional[str] = None
    visual_identity_gate_status: Optional[str] = None
    preview_overall_status: Optional[str] = None
    ready_for_owner_visual_review: bool = False
    ready_for_owner_manual_visual_inspection: bool = False
    side_effects: Dict[str, bool] = field(default_factory=dict)
    error: Optional[str] = None
    # Candidate selection funnel diagnostics (carried even on pre-Gemini holds so
    # the failure artifact can explain *why* candidates dropped below five).
    candidate_funnel_summary: Optional[Dict[str, Any]] = None
    hold_reason: Optional[str] = None
    exposure_dedup_backfill_used: bool = False
    internal_issue_codes: List[str] = field(default_factory=list)
    generation_attempt_count: int = 0
    generation_recovery_attempted: bool = False
    generation_recovery_family: Optional[str] = None
    generation_recovery_result: str = "not_needed"
    initial_generation_issue_codes: List[str] = field(default_factory=list)
    recovery_generation_issue_codes: List[str] = field(default_factory=list)
    # Token fields stay Optional[int]: None means unavailable, not zero usage.
    initial_input_tokens: Optional[int] = None
    initial_output_tokens: Optional[int] = None
    recovery_input_tokens: Optional[int] = None
    recovery_output_tokens: Optional[int] = None
    total_input_tokens: Optional[int] = None
    total_output_tokens: Optional[int] = None
    reconciled_top5: bool = False
    replaced_source_ids: List[str] = field(default_factory=list)
    replacement_source_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "program_id": self.program_id,
            "source_pack_path": self.source_pack_path,
            "html_path": self.html_path,
            "fetched_item_count": self.fetched_item_count,
            "feed_urls_used": self.feed_urls_used,
            "sample_marker_pass": self.sample_marker_pass,
            "sample_marker_hits": [
                {"code": h.code, "marker": h.marker, "context": h.context}
                for h in self.sample_marker_hits
            ],
            "placeholder_gate_pass": self.placeholder_gate_pass,
            "placeholder_gate_hits": [
                {"code": h.code, "marker": h.marker, "context": h.context}
                for h in self.placeholder_gate_hits
            ],
            "validation_status": self.validation_status,
            "validation_issues": self.validation_issues,
            "send_attempted": self.send_attempted,
            "send_success": self.send_success,
            "send_block_reason": self.send_block_reason,
            "email_subject": self.email_subject,
            "email_recipients": self.email_recipients,
            "email_report_path": self.email_report_path,
            "called_gemini": self.called_gemini,
            "fetched_live_news": self.fetched_live_news,
            "use_gemini": self.use_gemini,
            "parse_status": self.parse_status,
            "parse_meta": self.parse_meta,
            "parse_diagnostics": self.parse_diagnostics,
            "generation_diagnostics": self.generation_diagnostics,
            "generation_contract": self.generation_contract,
            "raw_response_path": self.raw_response_path,
            "generated_body": self.generated_body,
            "generated_briefing": self.generated_briefing,
            "contract_preview": self.contract_preview,
            "image_path": self.image_path,
            "image_source_mode": self.image_source_mode,
            "approved_asset_id": self.approved_asset_id,
            "image_in_html": self.image_in_html,
            "visible_body_quality_pass": self.visible_body_quality_pass,
            "visible_body_quality_issues": self.visible_body_quality_issues,
            "preview_validation": self.preview_validation,
            "structural_gate_status": self.structural_gate_status,
            "content_briefing_gate_status": self.content_briefing_gate_status,
            "visual_identity_gate_status": self.visual_identity_gate_status,
            "preview_overall_status": self.preview_overall_status,
            "ready_for_owner_visual_review": self.ready_for_owner_visual_review,
            "ready_for_owner_manual_visual_inspection": self.ready_for_owner_manual_visual_inspection,
            "side_effects": self.side_effects,
            "error": self.error,
            "candidate_funnel_summary": self.candidate_funnel_summary,
            "hold_reason": self.hold_reason,
            "exposure_dedup_backfill_used": self.exposure_dedup_backfill_used,
            "internal_issue_codes": list(self.internal_issue_codes),
            "generation_attempt_count": self.generation_attempt_count,
            "generation_recovery_attempted": self.generation_recovery_attempted,
            "generation_recovery_family": self.generation_recovery_family,
            "generation_recovery_result": self.generation_recovery_result,
            "initial_generation_issue_codes": list(self.initial_generation_issue_codes),
            "recovery_generation_issue_codes": list(self.recovery_generation_issue_codes),
            "initial_input_tokens": self.initial_input_tokens,
            "initial_output_tokens": self.initial_output_tokens,
            "recovery_input_tokens": self.recovery_input_tokens,
            "recovery_output_tokens": self.recovery_output_tokens,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "reconciled_top5": self.reconciled_top5,
            "replaced_source_ids": list(self.replaced_source_ids),
            "replacement_source_ids": list(self.replacement_source_ids),
        }


def _now_kst_iso() -> str:
    return datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")


def _prompt_input_diagnostic_snapshot(prompt_input: dict) -> Dict[str, Any]:
    top = prompt_input.get("top_5_news") if isinstance(prompt_input.get("top_5_news"), dict) else {}
    top_items = top.get("items") if isinstance(top.get("items"), list) else []
    selected_items = (
        prompt_input.get("selected_items")
        if isinstance(prompt_input.get("selected_items"), list)
        else []
    )
    selected_news_ids: List[str] = []
    selected_headlines: List[str] = []
    for item in top_items:
        if not isinstance(item, dict):
            continue
        nid = str(item.get("news_id") or "").strip()
        if nid:
            selected_news_ids.append(nid)
        headline = str(item.get("headline") or "").strip()
        if headline:
            selected_headlines.append(headline[:120])
    snapshot: Dict[str, Any] = {
        "program_id": prompt_input.get("program_id"),
        "news_scope": prompt_input.get("news_scope"),
        "prompt_status": prompt_input.get("prompt_status"),
        "top_5_news_item_count": len(top_items),
        "selected_items_count": len(selected_items),
        "selected_news_ids": selected_news_ids[:8],
        "selected_headlines": selected_headlines[:8],
        "hold_reason": prompt_input.get("hold_reason"),
        "exposure_dedup_backfill_used": bool(
            prompt_input.get("exposure_dedup_backfill_used")
        ),
    }
    funnel = prompt_input.get("candidate_funnel_summary")
    if isinstance(funnel, dict):
        snapshot["candidate_funnel_summary"] = funnel
    return snapshot


def _parse_failure_diagnostics(parse_result: dict, prompt_input: dict) -> Dict[str, Any]:
    parse_meta = parse_result.get("parse_meta") if isinstance(parse_result.get("parse_meta"), dict) else {}
    issues = parse_result.get("issues") if isinstance(parse_result.get("issues"), list) else []
    field = ""
    reason = ""
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        path = str(issue.get("path") or "")
        code = str(issue.get("code") or "")
        if path == "deep_dive.key_implications" or "key_implications" in code:
            field = path or "deep_dive.key_implications"
            reason = str(issue.get("message") or code)
            break
    if not field and issues and isinstance(issues[0], dict):
        field = str(issues[0].get("path") or "")
        reason = str(issues[0].get("message") or issues[0].get("code") or "")
    return {
        "prompt_input_diagnostic_snapshot": _prompt_input_diagnostic_snapshot(prompt_input),
        "raw_parsed_field_presence_summary": parse_meta.get(
            "raw_parsed_field_presence_summary"
        ),
        "parse_failure_field": field or None,
        "parse_failure_reason": reason or None,
        "repair_attempted": bool(
            parse_meta.get("deep_dive_key_implications_repair_attempted")
        ),
        "repair_success": bool(
            parse_meta.get("deep_dive_key_implications_repair_success")
        ),
        # Multi-JSON-object diagnostics (see keysuri_generation_prompt._parse_meta) —
        # surfaced here so an unrecoverable multi-object parse failure is
        # diagnosable from the safe-fail artifact/response alone.
        "json_object_count": parse_meta.get("json_object_count"),
        "candidate_index": parse_meta.get("candidate_index"),
        "candidate_top_level_keys": parse_meta.get("candidate_top_level_keys"),
        "missing_required_keys": parse_meta.get("missing_required_keys"),
        "schema_error_summary": parse_meta.get("schema_error_summary"),
        "schema_issue_codes": parse_meta.get("schema_issue_codes"),
        "news_scope_actual": parse_meta.get("news_scope_actual"),
        "section_heading_actual": parse_meta.get("section_heading_actual"),
        "news_scope_actual_before_repair": parse_meta.get(
            "news_scope_actual_before_repair"
        ),
        "section_heading_actual_before_repair": parse_meta.get(
            "section_heading_actual_before_repair"
        ),
        "repair_applied": parse_meta.get("repair_applied"),
        "repaired_fields": parse_meta.get("repaired_fields"),
        "first_300_chars_safe_excerpt": parse_meta.get("first_300_chars_safe_excerpt"),
        "parse_recovery_strategy": parse_meta.get("parse_recovery_strategy"),
        "parse_failure_stage": parse_meta.get("parse_failure_stage"),
    }


def _parse_internal_issue_codes(parse_result: dict) -> List[str]:
    parse_meta = parse_result.get("parse_meta") if isinstance(parse_result.get("parse_meta"), dict) else {}
    return [
        str(code)
        for code in (parse_meta.get("internal_issue_codes") or [])
        if str(code or "").strip()
    ]


def _strip_html(text: str) -> str:
    return normalize_feed_source_text(text, strip_markup=True).text


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug[:48] or "item"


def _source_id_for_link(feed_id: str, link: str) -> str:
    digest = hashlib.sha256(link.encode("utf-8")).hexdigest()[:10]
    return f"live-{_slugify(feed_id)}-{digest}"


def _parse_published(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return _now_kst_iso()
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError):
        return _now_kst_iso()


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _first_text(node: Optional[ET.Element], names: Sequence[str]) -> str:
    if node is None:
        return ""
    for name in names:
        child = node.find(f".//{name}")
        if child is not None and (child.text or "").strip():
            return (child.text or "").strip()
        for el in node.iter():
            if _local(el.tag) == name and (el.text or "").strip():
                return (el.text or "").strip()
    return ""


def _first_link(node: ET.Element) -> str:
    link = _first_text(node, ("link",))
    if link.startswith("http"):
        return link
    for el in node.iter():
        if _local(el.tag) == "link":
            href = (el.attrib.get("href") or "").strip()
            if href.startswith("http"):
                return href
            if (el.text or "").strip().startswith("http"):
                return (el.text or "").strip()
    return link


def parse_feed_xml(xml_bytes: bytes) -> List[Dict[str, str]]:
    """Parse RSS 2.0 or Atom entries from feed XML."""
    root = ET.fromstring(xml_bytes)
    entries: List[ET.Element] = []
    for el in root.iter():
        tag = _local(el.tag)
        if tag in ("item", "entry"):
            entries.append(el)

    parsed: List[Dict[str, str]] = []
    for entry in entries:
        title = normalize_feed_source_text(
            _first_text(entry, ("title",)), strip_markup=True
        ).text
        link = _first_link(entry)
        if not title or not link.startswith("http"):
            continue
        summary = _first_text(entry, ("description", "summary", "content"))
        published = _first_text(entry, ("pubDate", "published", "updated"))
        parsed.append(
            {
                "title": title,
                "link": link,
                "summary": _strip_html(summary),
                "published_at": _parse_published(published),
            }
        )
    return parsed


def fetch_feed_items(
    feed: Dict[str, str],
    *,
    max_items: int,
    timeout_sec: int = DEFAULT_FETCH_TIMEOUT_SEC,
    user_agent: str = DEFAULT_USER_AGENT,
) -> List[FetchedFeedItem]:
    req = Request(
        feed["feed_url"],
        headers={"User-Agent": user_agent, "Accept": "application/rss+xml, application/xml, text/xml"},
    )
    with urlopen(req, timeout=timeout_sec) as resp:
        xml_bytes = resp.read()
    raw_items = parse_feed_xml(xml_bytes)[: max(1, max_items)]
    out: List[FetchedFeedItem] = []
    for raw in raw_items:
        out.append(
            FetchedFeedItem(
                feed_id=feed["feed_id"],
                feed_name=feed["feed_name"],
                feed_url=feed["feed_url"],
                source_tier=feed["source_tier"],
                default_category=feed["default_category"],
                title=raw["title"],
                link=raw["link"],
                published_at=raw["published_at"],
                summary=raw["summary"] or raw["title"],
            )
        )
    return out


def _infer_category(title: str, summary: str, default_category: str) -> str:
    primary, _, _, _ = classify_global_tech_category(
        f"{title} {summary}",
        feed_default=default_category,
    )
    return primary


def _category_for_program_item(
    program_id: str,
    item: FetchedFeedItem,
    title: str,
    summary: str,
) -> str:
    if program_id == PROGRAM_KOREA or str(program_id).startswith("keysuri_korea"):
        default = (item.default_category or "").strip()
        if default in KOREA_TECH_CATEGORIES:
            return default
        return default or "korea_big_company_strategy"
    return _infer_category(title, summary, item.default_category)


# Reader-facing Global prose is Korean. These strings are contract placeholders
# for two required item fields (why_it_matters / business_implication) that the
# model and the enricher are expected to replace with same-item grounded prose.
#
# They used to be English implementation copy — "Public tech source (X)
# published: ..." and "AI/software/platform shifts may change vendor shortlists
# and workflow lock-in." Whenever the model returned nothing usable and the
# Global contract scaffold grafted the claim pool straight into the cards
# (2026-08-27 12:30 natural run), that English shipped to the owner verbatim.
# Blacklisting the phrases downstream would only have hidden the producer; the
# producer is here, so the placeholders are Korean and named as placeholders.
def _business_implication(category: str) -> str:
    label = CATEGORY_KO_LABELS.get(category, "")
    if label:
        return f"{label} 영역의 공개 발표로, 사업 영향은 후속 공식 발표에서 확인이 필요합니다."
    return "공개 출처 발표로, 사업 영향은 후속 공식 발표에서 확인이 필요합니다."


def _why_it_matters_placeholder(source_name: str, title: str) -> str:
    """Korean, grounded in this item's own source and headline — never another's."""
    name = str(source_name or "").strip()
    headline = str(title or "").strip()[:120]
    if name and headline:
        return f"{name} 공개 발표: 「{headline}」."
    if headline:
        return f"공개 출처 발표: 「{headline}」."
    return "공개 출처 발표 내용으로, 세부 사항은 원문 확인이 필요합니다."


def _build_source_entries_from_items(
    program_id: str,
    items: Sequence[FetchedFeedItem],
    *,
    generated_at: Optional[str] = None,
    max_items: Optional[int] = None,
) -> Tuple[List[dict], List[dict], str]:
    if program_id not in SUPPORTED_PROGRAMS:
        raise ValueError(f"Unsupported program_id: {program_id!r}")

    stamp = generated_at or _now_kst_iso()
    sources: List[dict] = []
    claims: List[dict] = []
    seen_links: set[str] = set()

    for item in items:
        if max_items is not None and len(sources) >= max_items:
            break
        if item.link in seen_links:
            continue
        item_hits = scan_sample_markers(item.link, item.title, item.summary, item.feed_name)
        if item_hits:
            raise ValueError(
                f"Fixture-like live item rejected ({item_hits[0].marker!r}) for link {item.link!r}"
            )
        seen_links.add(item.link)
        sid = _source_id_for_link(item.feed_id, item.link)
        summary = item.summary[:500] if item.summary else item.title[:500]
        category = _category_for_program_item(program_id, item, item.title, summary)
        sources.append(
            {
                "source_id": sid,
                "source_name": item.feed_name,
                "source_url": item.link,
                "source_tier": item.source_tier,
                "feed_id": item.feed_id,
                "fetched_at": stamp,
                "published_at": item.published_at,
                "title": item.title,
                "publisher": item.feed_name,
                "snippet": summary,
            }
        )
        claims.append(
            {
                "claim_id": f"claim-{sid}",
                "statement": item.title,
                "claim_type": "general",
                "source_ids": [sid],
                "confidence_label": "reported",
                "category": category,
                "headline": item.title[:160],
                "summary": summary,
                "why_it_matters": _why_it_matters_placeholder(item.feed_name, item.title),
                "business_implication": _business_implication(category),
            }
        )

    return sources, claims, stamp


def build_live_candidate_source_pack(
    program_id: str,
    items: Sequence[FetchedFeedItem],
    *,
    generated_at: Optional[str] = None,
) -> dict:
    """Build full candidate pool from fetched RSS items (no TOP5 trim)."""
    if len(items) < 5:
        raise ValueError(f"Need at least 5 fetched items for candidate pool, got {len(items)}")
    sources, claims, stamp = _build_source_entries_from_items(
        program_id, items, generated_at=generated_at
    )
    if len(sources) < 5:
        raise ValueError(f"Could not assemble 5 unique live sources, got {len(sources)}")
    return {
        "program_id": program_id,
        "generated_at": stamp,
        "notes": (
            f"Live source candidate pool — public RSS metadata fetch at {stamp}. "
            "Owner-review only; not customer-final."
        ),
        "sources": sources,
        "claims": claims,
    }


def build_live_source_pack(
    program_id: str,
    items: Sequence[FetchedFeedItem],
    *,
    generated_at: Optional[str] = None,
) -> dict:
    if program_id not in SUPPORTED_PROGRAMS:
        raise ValueError(f"Unsupported program_id: {program_id!r}")
    if len(items) < 5:
        raise ValueError(f"Need at least 5 fetched items for TOP 5 smoke, got {len(items)}")

    sources, claims, stamp = _build_source_entries_from_items(
        program_id, items, generated_at=generated_at, max_items=5
    )
    if len(sources) < 5:
        raise ValueError(f"Could not assemble 5 unique live sources, got {len(sources)}")

    return {
        "program_id": program_id,
        "generated_at": stamp,
        "notes": (
            f"Live source smoke — public RSS metadata fetch at {stamp}. "
            "Owner-review only; not customer-final."
        ),
        "sources": sources,
        "claims": claims,
    }


def _prompt_top5_item_maps(prompt_input: dict) -> Tuple[Dict[int, dict], Dict[str, dict]]:
    prompt_top = prompt_input.get("top_5_news") if isinstance(prompt_input.get("top_5_news"), dict) else {}
    items = prompt_top.get("items") if isinstance(prompt_top.get("items"), list) else []
    by_rank: Dict[int, dict] = {}
    by_news_id: Dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        rank_raw = item.get("rank")
        if isinstance(rank_raw, int):
            by_rank[rank_raw] = item
        news_id = str(item.get("news_id") or "").strip()
        if news_id:
            by_news_id[news_id] = item
    return by_rank, by_news_id


def _source_ids_from_news_id(news_id: str) -> List[str]:
    nid = str(news_id or "").strip()
    if not nid:
        return []
    if nid.startswith("claim-live-"):
        return [nid.replace("claim-live-", "live-", 1)]
    if nid.startswith("claim-"):
        return [nid.replace("claim-", "live-", 1)]
    return [nid]


def _normalize_generated_top5_item(
    item: dict,
    *,
    prompt_by_rank: Dict[int, dict],
    prompt_by_news_id: Dict[str, dict],
) -> dict:
    out = dict(item)
    briefing = item.get("briefing_item") if isinstance(item.get("briefing_item"), dict) else {}

    rank_raw = out.get("rank")
    rank = int(rank_raw) if isinstance(rank_raw, int) else 0
    news_id = str(out.get("news_id") or briefing.get("news_id") or "").strip()
    prompt_item = prompt_by_news_id.get(news_id) or prompt_by_rank.get(rank) or {}

    korean_title = str(
        out.get("korean_title") or briefing.get("korean_title") or out.get("headline") or ""
    ).strip()
    what_happened = str(
        out.get("what_happened") or briefing.get("what_happened") or out.get("summary") or ""
    ).strip()
    why_now = str(
        out.get("why_now")
        or briefing.get("why_now")
        or out.get("why_it_matters")
        or prompt_item.get("why_it_matters")
        or ""
    ).strip()
    owner_angle = str(
        out.get("owner_angle")
        or briefing.get("owner_angle")
        or out.get("business_implication")
        or prompt_item.get("business_implication")
        or ""
    ).strip()

    if not str(out.get("headline") or "").strip():
        out["headline"] = korean_title or str(prompt_item.get("headline") or "")
    if not str(out.get("summary") or "").strip():
        out["summary"] = what_happened or str(prompt_item.get("summary") or "")
    if not str(out.get("why_it_matters") or "").strip():
        out["why_it_matters"] = why_now
    if not str(out.get("business_implication") or "").strip():
        out["business_implication"] = owner_angle
    if not str(out.get("category") or "").strip():
        out["category"] = str(prompt_item.get("category") or "ai_product")
    if not str(out.get("news_id") or "").strip():
        out["news_id"] = str(prompt_item.get("news_id") or news_id or f"generated-rank-{rank}")
    if not isinstance(out.get("source_ids"), list) or not out.get("source_ids"):
        prompt_ids = prompt_item.get("source_ids")
        if isinstance(prompt_ids, list) and prompt_ids:
            out["source_ids"] = [str(x).strip() for x in prompt_ids if str(x).strip()]
        else:
            derived = _source_ids_from_news_id(str(out.get("news_id") or ""))
            out["source_ids"] = derived or [str(prompt_item.get("news_id") or "")]
    if not str(out.get("confidence_label") or "").strip():
        out["confidence_label"] = str(prompt_item.get("confidence_label") or "reported")
    return out


def normalize_generated_briefing_schema_aliases(
    generated: dict,
    prompt_input: dict,
) -> dict:
    """Normalize model schema drift (closing aliases, deep_dive key_implications, etc.)."""
    out = normalize_generated_briefing_closing_aliases(generated, prompt_input)

    top = out.get("top_5_news")
    prompt_top = prompt_input.get("top_5_news") if isinstance(prompt_input.get("top_5_news"), dict) else {}
    prompt_items = prompt_top.get("items") if isinstance(prompt_top.get("items"), list) else []
    if isinstance(top, dict) and isinstance(top.get("items"), list):
        by_rank, by_news_id = _prompt_top5_item_maps(prompt_input)
        generated_by_news: Dict[str, dict] = {}
        generated_by_rank: Dict[int, dict] = {}
        for item in top["items"]:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_generated_top5_item(
                item,
                prompt_by_rank=by_rank,
                prompt_by_news_id=by_news_id,
            )
            news_id = str(normalized.get("news_id") or "").strip()
            if news_id:
                generated_by_news[news_id] = normalized
            rank_raw = normalized.get("rank")
            if isinstance(rank_raw, int):
                generated_by_rank[rank_raw] = normalized

        if prompt_items:
            reordered: List[dict] = []
            for prompt_item in prompt_items:
                if not isinstance(prompt_item, dict):
                    continue
                expected_rank = int(prompt_item.get("rank") or 0)
                expected_news_id = str(prompt_item.get("news_id") or "").strip()
                picked = (
                    generated_by_news.get(expected_news_id)
                    or generated_by_rank.get(expected_rank)
                    or dict(prompt_item)
                )
                merged = _normalize_generated_top5_item(
                    picked,
                    prompt_by_rank=by_rank,
                    prompt_by_news_id=by_news_id,
                )
                merged["rank"] = expected_rank
                merged["news_id"] = expected_news_id
                reordered.append(merged)
            normalized_items = reordered
        else:
            normalized_items = [
                _normalize_generated_top5_item(
                    item,
                    prompt_by_rank=by_rank,
                    prompt_by_news_id=by_news_id,
                )
                if isinstance(item, dict)
                else item
                for item in top["items"]
            ]
        out = dict(out)
        out["top_5_news"] = {**top, "items": normalized_items}

    deep = out.get("deep_dive")
    if not isinstance(deep, dict):
        return out

    deep_out = dict(deep)
    implications = deep.get("key_implications")
    if not isinstance(implications, list) or not implications:
        candidates: List[str] = []
        confirmed = deep.get("confirmed_facts")
        if isinstance(confirmed, list):
            candidates.extend(str(x).strip() for x in confirmed if str(x).strip())
        interpretation = str(deep.get("interpretation") or deep.get("keysuri_interpretation") or "").strip()
        if interpretation:
            candidates.append(interpretation)
        owner_impact = str(deep.get("owner_impact") or deep.get("korean_operator_impact") or "").strip()
        if owner_impact:
            candidates.append(owner_impact)
        if candidates:
            deep_out["key_implications"] = candidates[:5]

    if not str(deep_out.get("uncertainty") or "").strip():
        open_q = deep.get("open_questions") or deep.get("uncertainty")
        if isinstance(open_q, list) and open_q:
            deep_out["uncertainty"] = " ".join(str(x).strip() for x in open_q[:3] if str(x).strip())
        elif isinstance(open_q, str) and open_q.strip():
            deep_out["uncertainty"] = open_q.strip()

    if not isinstance(deep_out.get("source_ids"), list) or not deep_out.get("source_ids"):
        source_ids: List[str] = []
        top_after = out.get("top_5_news") if isinstance(out.get("top_5_news"), dict) else {}
        for item in top_after.get("items") or []:
            if not isinstance(item, dict):
                continue
            for sid in item.get("source_ids") or []:
                s = str(sid).strip()
                if s and s not in source_ids:
                    source_ids.append(s)
        if source_ids:
            deep_out["source_ids"] = source_ids[:5]

    if not str(deep_out.get("confidence_label") or "").strip():
        deep_out["confidence_label"] = "reported"

    out = dict(out)
    out["deep_dive"] = deep_out
    return out


def normalize_generated_briefing_closing_aliases(
    generated: dict,
    prompt_input: dict,
) -> dict:
    """Map common model aliases (source_name/source_url) to contract label/url."""
    if not isinstance(generated, dict):
        return generated

    closing = generated.get("closing_sources")
    if not isinstance(closing, dict):
        return generated

    source_map: Dict[str, dict] = {}
    pack = prompt_input.get("source_pack") if isinstance(prompt_input.get("source_pack"), dict) else {}
    for src in pack.get("sources") if isinstance(pack.get("sources"), list) else []:
        if isinstance(src, dict):
            sid = str(src.get("source_id") or "").strip()
            if sid:
                source_map[sid] = src

    source_list = closing.get("source_list")
    if not isinstance(source_list, list):
        return generated

    normalized_list: List[dict] = []
    for entry in source_list:
        if not isinstance(entry, dict):
            continue
        item = dict(entry)
        if not str(item.get("label") or "").strip() and str(item.get("source_name") or "").strip():
            item["label"] = item["source_name"]
        if not str(item.get("url") or "").strip() and str(item.get("source_url") or "").strip():
            item["url"] = item["source_url"]
        sid = str(item.get("source_id") or "").strip()
        if sid in source_map:
            src = source_map[sid]
            item.setdefault("label", src.get("source_name"))
            item.setdefault("url", src.get("source_url"))
            item.setdefault("tier", src.get("source_tier"))
        normalized_list.append(item)

    out = dict(generated)
    out["closing_sources"] = {**closing, "source_list": normalized_list}
    return out


STRUCTURAL_CONTRACT_FAILURE = "STRUCTURAL_CONTRACT_FAILURE"
SEMANTIC_SCOPE_FAILURE = "SEMANTIC_SCOPE_FAILURE"
_STRUCTURAL_RECOVERY_CODES = frozenset(
    {
        "json_extract_failed",
        "parse_multiple_json_objects_unrecoverable",
        "parse_multiple_json_objects_ambiguous",
        "gemini_multiple_json_objects_no_valid_schema",
        "gemini_json_missing_required_keys",
        "gemini_json_recovery_failed",
    }
)
_SEMANTIC_RECOVERY_CODES = frozenset(
    {
        "korea_tech_top5_irrelevant_item",
        "news_scope_mismatch",
        "section_heading_mismatch",
        "top_5_news_scope_wrong",
        "top_5_news_heading_wrong",
        "top_5_sequence_mismatch",
        "top_5_fixed_source_ids_mismatch",
        "top_5_unapproved_url",
    }
)
# Global bounded full-contract repair targets (exact names + current aliases).
# The Global contract scaffold exists to complete a *partial* model output.
# When it has to graft the entire TOP5 from the prompt's claim pool, the model
# contributed no article prose at all and the "briefing" is really the source
# pack wearing a contract shape. That is a generation failure, not a repair, and
# it must buy the one budgeted corrective call rather than being waved through
# as parsed_valid (2026-08-27 12:30 Global: 645 output tokens, zero expected
# keys, scaffold applied, recovery recorded as "not_needed", owner received a
# template-only POOR notice).
GLOBAL_SCAFFOLD_FABRICATED_TOP5_CODE = "global_contract_scaffold_fabricated_top5"

_GLOBAL_CONTRACT_REPAIR_CODES = frozenset(
    {
        "gemini_json_missing_required_keys",
        "gemini_json_required_field_invalid",
        "gemini_json_schema_validation_failed",
        "top_5_count_invalid",
        "top_5_item_count_invalid",
        "top_5_item_missing_required_field",
        "top_5_news_item_invalid",
        "top_5_news_missing_or_invalid",
        "deep_dive_missing_required_field",
        "deep_dive_heading_invalid",
        "deep_dive_key_implications_invalid",
        GLOBAL_SCAFFOLD_FABRICATED_TOP5_CODE,
    }
)
# Ceiling of two total model attempts per Global run: the initial call plus at
# most one corrective call. A third call was previously possible when a
# MAX_TOKENS compact retry preceded a full-contract repair.
GLOBAL_GENERATION_CALL_BUDGET = 2
RECOVERY_RECONCILIATION_INSUFFICIENT = (
    "korea_generation_reconciliation_insufficient_valid_candidates"
)


def _is_global_program(program_id: str) -> bool:
    value = str(program_id or "").strip()
    return value == PROGRAM_GLOBAL or value.startswith("keysuri_global")


def _global_contract_repair_codes(issue_codes: Sequence[str]) -> List[str]:
    codes = {str(code) for code in issue_codes if code}
    return sorted(codes & _GLOBAL_CONTRACT_REPAIR_CODES)

def _parse_with_schema_alias_fallback(
    raw_text: str,
    program_id: str,
    prompt_input: dict,
) -> dict:
    result = parse_keysuri_generated_response(raw_text, program_id, prompt_input)
    if result.get("parse_status") == "parsed_valid":
        return _apply_fixed_selection_contract(result, prompt_input)
    try:
        parsed_obj = extract_json_object_from_model_text(raw_text)
        parsed_obj = normalize_generated_briefing_schema_aliases(parsed_obj, prompt_input)
        normalized_result = parse_keysuri_generated_response(
            json.dumps(parsed_obj, ensure_ascii=False),
            program_id,
            prompt_input,
        )
        contracted = _apply_fixed_selection_contract(normalized_result, prompt_input)
        return _attach_candidate_briefing_for_recovery(contracted, parsed_obj)
    except ValueError:
        return _attach_candidate_briefing_for_recovery(result, None, raw_text=raw_text, prompt_input=prompt_input)


def _attach_candidate_briefing_for_recovery(
    parse_result: dict,
    candidate: Optional[dict],
    *,
    raw_text: Optional[str] = None,
    prompt_input: Optional[dict] = None,
) -> dict:
    """Keep an invalid candidate briefing for news_id mapping only.

    ``generated_briefing`` stays ``None`` on parsed_invalid (existing contract).
    Recovery maps semantic issue indexes via ``parse_meta.candidate_generated_briefing``.
    """
    if parse_result.get("parse_status") == "parsed_valid":
        return parse_result
    if isinstance(parse_result.get("generated_briefing"), dict):
        return parse_result
    briefing = candidate if isinstance(candidate, dict) else None
    if briefing is None and raw_text:
        try:
            briefing = extract_json_object_from_model_text(raw_text)
            if prompt_input is not None and isinstance(briefing, dict):
                briefing = normalize_generated_briefing_schema_aliases(
                    briefing, prompt_input
                )
        except ValueError:
            briefing = None
    if not isinstance(briefing, dict):
        return parse_result
    out = dict(parse_result)
    meta = (
        dict(out["parse_meta"])
        if isinstance(out.get("parse_meta"), dict)
        else {}
    )
    meta["candidate_generated_briefing"] = briefing
    out["parse_meta"] = meta
    return out


def _approved_url_values_for_sources(
    source_ids: Sequence[str],
    source_map: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    """Build the approved URL set with both raw and canonical forms."""
    approved: set[str] = set()
    for source_id in source_ids:
        source = source_map.get(str(source_id))
        if not isinstance(source, dict):
            continue
        for candidate in (
            source.get("url"),
            source.get("source_url"),
            source.get("canonical_url"),
        ):
            value = str(candidate or "").strip()
            if not value:
                continue
            approved.add(value)
            canonical = canonicalize_url(value)
            if canonical:
                approved.add(canonical)
    return approved


def _url_is_approved(value: str, approved_urls: set[str]) -> bool:
    """Accept a URL when its raw or canonical form is in the approved set."""
    raw = str(value or "").strip()
    if not raw:
        return False
    if raw in approved_urls:
        return True
    canonical = canonicalize_url(raw)
    return bool(canonical) and canonical in approved_urls


def _apply_fixed_selection_contract(parse_result: dict, prompt_input: dict) -> dict:
    """Block generated TOP5 source IDs/URLs that are outside the fixed input."""
    if (
        parse_result.get("parse_status") != "parsed_valid"
        or str(prompt_input.get("program_id") or "") != PROGRAM_KOREA
    ):
        return parse_result
    generated = parse_result.get("generated_briefing")
    generated_top = generated.get("top_5_news") if isinstance(generated, dict) else {}
    generated_items = (
        generated_top.get("items") if isinstance(generated_top, dict) else []
    )
    expected_top = (
        prompt_input.get("top_5_news")
        if isinstance(prompt_input.get("top_5_news"), dict)
        else {}
    )
    expected_items = (
        expected_top.get("items") if isinstance(expected_top.get("items"), list) else []
    )
    source_pack = (
        prompt_input.get("source_pack")
        if isinstance(prompt_input.get("source_pack"), dict)
        else {}
    )
    source_map = _source_map_for_reconciliation(source_pack)
    issues: List[dict] = []
    for idx, expected in enumerate(expected_items):
        actual = generated_items[idx] if idx < len(generated_items) else None
        if not isinstance(expected, dict) or not isinstance(actual, dict):
            continue
        expected_ids = [
            str(source_id) for source_id in (expected.get("source_ids") or []) if source_id
        ]
        actual_ids = [
            str(source_id) for source_id in (actual.get("source_ids") or []) if source_id
        ]
        if actual_ids != expected_ids:
            issues.append(
                {
                    "code": "top_5_fixed_source_ids_mismatch",
                    "message": "Generated TOP5 source_ids must exactly match the fixed selection",
                    "path": f"top_5_news.items[{idx}].source_ids",
                }
            )
        allowed_urls = _approved_url_values_for_sources(expected_ids, source_map)
        for field_name in ("url", "canonical_url", "source_url"):
            value = str(actual.get(field_name) or "").strip()
            if value and not _url_is_approved(value, allowed_urls):
                issues.append(
                    {
                        "code": "top_5_unapproved_url",
                        "message": "Generated TOP5 URL is not present in the fixed source pack",
                        "path": f"top_5_news.items[{idx}].{field_name}",
                    }
                )
    if not issues:
        return parse_result
    parse_meta = (
        parse_result.get("parse_meta")
        if isinstance(parse_result.get("parse_meta"), dict)
        else {}
    )
    return {
        "parse_status": "parsed_invalid",
        "program_id": parse_result.get("program_id"),
        "issues": issues,
        "generated_briefing": None,
        "parse_meta": {
            **parse_meta,
            "parse_failure_stage": "fixed_selection_contract",
            "schema_issue_codes": [issue["code"] for issue in issues],
        },
    }


def _apply_fixed_deep_dive_contract(
    parse_result: dict,
    approved_source_ids: Sequence[str],
) -> dict:
    """Require deep_dive.source_ids to be a non-empty subset of TOP5 approved ids."""
    if parse_result.get("parse_status") != "parsed_valid":
        return parse_result
    generated = parse_result.get("generated_briefing")
    deep_dive = generated.get("deep_dive") if isinstance(generated, dict) else {}
    actual_ids = [
        str(source_id)
        for source_id in (
            deep_dive.get("source_ids") if isinstance(deep_dive, dict) else []
        )
        if source_id
    ]
    approved_ids = {
        str(source_id) for source_id in approved_source_ids if source_id
    }
    issue_message = ""
    if not actual_ids:
        issue_message = "deep_dive.source_ids must be a non-empty subset of approved TOP5 source ids"
    elif len(actual_ids) != len(set(actual_ids)):
        issue_message = "deep_dive.source_ids must not contain duplicates"
    elif any(source_id not in approved_ids for source_id in actual_ids):
        issue_message = "deep_dive.source_ids contains an id outside the approved TOP5 set"
    if not issue_message:
        return parse_result
    parse_meta = (
        parse_result.get("parse_meta")
        if isinstance(parse_result.get("parse_meta"), dict)
        else {}
    )
    return {
        "parse_status": "parsed_invalid",
        "program_id": parse_result.get("program_id"),
        "issues": [
            {
                "code": "deep_dive_fixed_source_ids_mismatch",
                "message": issue_message,
                "path": "deep_dive.source_ids",
            }
        ],
        "generated_briefing": None,
        "parse_meta": {
            **parse_meta,
            "parse_failure_stage": "fixed_deep_dive_contract",
            "schema_issue_codes": ["deep_dive_fixed_source_ids_mismatch"],
        },
    }


def _issue_codes(parse_result: dict) -> List[str]:
    return list(
        dict.fromkeys(
            str(issue.get("code"))
            for issue in (parse_result.get("issues") or [])
            if isinstance(issue, dict) and issue.get("code")
        )
    )


def _classify_generation_failure(issue_codes: Sequence[str]) -> Optional[str]:
    codes = {str(code) for code in issue_codes if code}
    if codes & _STRUCTURAL_RECOVERY_CODES:
        return STRUCTURAL_CONTRACT_FAILURE
    if codes & _SEMANTIC_RECOVERY_CODES:
        return SEMANTIC_SCOPE_FAILURE
    return None


def _optional_token_count(
    usage: Mapping[str, Any], *keys: str
) -> Optional[int]:
    """Return the first present token field as Optional[int].

    Missing keys and explicit ``None`` stay ``None``. Only an actual numeric
    value (including ``0``) is converted to ``int``.
    """
    for key in keys:
        if key not in usage:
            continue
        value = usage.get(key)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def _sum_optional_tokens(*values: Optional[int]) -> Optional[int]:
    """Exact sum only when every attempt value is a confirmed int.

    If any attempt is ``None``, return ``None`` so callers do not treat a
    partial sum as a complete total.
    """
    if not values:
        return None
    if any(value is None for value in values):
        return None
    return int(sum(values))


def _partial_sum_optional_tokens(*values: Optional[int]) -> Optional[int]:
    """Sum only the confirmed attempt values; never invent zeros."""
    present = [value for value in values if value is not None]
    if not present:
        return None
    return int(sum(present))


_USAGE_DIAGNOSTIC_OVERWRITE_KEYS = frozenset(
    {
        "initial_input_tokens",
        "initial_output_tokens",
        "recovery_input_tokens",
        "recovery_output_tokens",
        "total_input_tokens",
        "total_output_tokens",
        "partial_input_tokens",
        "partial_output_tokens",
        "input_tokens_complete",
        "output_tokens_complete",
        "usage_tokens_complete",
    }
)


def _merge_into_diagnostics(
    diagnostics: MutableMapping[str, Any],
    incoming: Mapping[str, Any],
    *,
    overwrite_keys: Optional[Sequence[str]] = None,
) -> None:
    """Merge diagnostics consistently for success and failure paths.

    Keys in ``overwrite_keys`` intentionally replace existing values (used for
    usage totals). Other colliding keys keep the existing value and record the
    collision name for operators.
    """
    overwrite = {str(key) for key in (overwrite_keys or ())}
    collisions: List[str] = []
    for key, value in incoming.items():
        if (
            key in diagnostics
            and key not in overwrite
            and diagnostics[key] != value
        ):
            collisions.append(str(key))
            continue
        diagnostics[key] = value
    if collisions:
        prior = diagnostics.get("diagnostics_collisions")
        merged = [str(item) for item in prior] if isinstance(prior, list) else []
        for key in collisions:
            if key not in merged:
                merged.append(key)
        diagnostics["diagnostics_collisions"] = merged


def _merge_generation_usage(
    outer: Optional[MutableMapping[str, Any]],
    initial: MutableMapping[str, Any],
    recovery: MutableMapping[str, Any],
) -> Dict[str, Any]:
    """Merge initial/recovery usage while preserving Optional[int] semantics.

    Exact ``total_*`` fields are set only when every executed attempt reports a
    confirmed integer for that metric. Confirmed partial sums are exposed via
    ``partial_*`` fields and never written into cost-facing ``*_token_count``
    totals when incomplete.
    """
    initial_input = _optional_token_count(initial, "prompt_token_count", "input_tokens")
    initial_output = _optional_token_count(
        initial, "candidates_token_count", "output_tokens"
    )
    initial_thoughts = _optional_token_count(initial, "thoughts_token_count")
    initial_total = _optional_token_count(initial, "total_token_count")

    recovery_executed = bool(recovery)
    if not recovery_executed:
        totals: Dict[str, Any] = {
            "initial_input_tokens": initial_input,
            "initial_output_tokens": initial_output,
            "recovery_input_tokens": None,
            "recovery_output_tokens": None,
            "total_input_tokens": initial_input,
            "total_output_tokens": initial_output,
            "partial_input_tokens": initial_input,
            "partial_output_tokens": initial_output,
            "input_tokens_complete": initial_input is not None,
            "output_tokens_complete": initial_output is not None,
            "usage_tokens_complete": initial_input is not None
            and initial_output is not None,
        }
        if outer is not None:
            outer.clear()
            outer.update(initial)
        return totals

    recovery_input = _optional_token_count(recovery, "prompt_token_count", "input_tokens")
    recovery_output = _optional_token_count(
        recovery, "candidates_token_count", "output_tokens"
    )
    recovery_thoughts = _optional_token_count(recovery, "thoughts_token_count")
    recovery_total = _optional_token_count(recovery, "total_token_count")

    total_input = _sum_optional_tokens(initial_input, recovery_input)
    total_output = _sum_optional_tokens(initial_output, recovery_output)
    total_thoughts = _sum_optional_tokens(initial_thoughts, recovery_thoughts)
    total_token_count = _sum_optional_tokens(initial_total, recovery_total)
    partial_input = _partial_sum_optional_tokens(initial_input, recovery_input)
    partial_output = _partial_sum_optional_tokens(initial_output, recovery_output)
    input_complete = initial_input is not None and recovery_input is not None
    output_complete = initial_output is not None and recovery_output is not None

    totals = {
        "initial_input_tokens": initial_input,
        "initial_output_tokens": initial_output,
        "recovery_input_tokens": recovery_input,
        "recovery_output_tokens": recovery_output,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "partial_input_tokens": partial_input,
        "partial_output_tokens": partial_output,
        "input_tokens_complete": input_complete,
        "output_tokens_complete": output_complete,
        "usage_tokens_complete": input_complete and output_complete,
    }
    if outer is not None:
        outer.clear()
        outer.update(initial)
        for key in ("model", "program_id", "max_output_tokens"):
            if recovery.get(key) not in (None, ""):
                outer[key] = recovery[key]
        # Cost estimators must only see exact totals. Incomplete metrics stay
        # None on the usage sink; partial sums live on diagnostic-only keys.
        outer["prompt_token_count_partial_sum"] = partial_input
        outer["candidates_token_count_partial_sum"] = partial_output
        if input_complete and output_complete:
            outer["prompt_token_count"] = total_input
            outer["candidates_token_count"] = total_output
            outer["thoughts_token_count"] = total_thoughts
            outer["total_token_count"] = total_token_count
            outer["usage_tokens_complete"] = True
        else:
            # Do not price a partial attempt mix as a complete generation total.
            outer["prompt_token_count"] = None
            outer["candidates_token_count"] = None
            outer["thoughts_token_count"] = None
            outer["total_token_count"] = None
            outer["usage_tokens_complete"] = False
            outer["cost_estimate_status_hint"] = "partial_usage_unpriced"
    return totals


def _optional_diag_int(
    diagnostics: Mapping[str, Any], key: str
) -> Optional[int]:
    """Read an Optional[int] diagnostic without coercing None to 0."""
    if key not in diagnostics:
        return None
    value = diagnostics.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_generation_event(event: str, **fields: Any) -> None:
    payload: Dict[str, Any] = {"event": event}
    for key in (
        "program_id",
        "failure_family",
        "generation_attempt_count",
        "issue_codes",
        "replaced_source_ids",
        "replacement_source_ids",
        "result",
    ):
        value = fields.get(key)
        if value not in (None, "", []):
            payload[key] = value
    logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _fixed_top5_context(prompt_input: dict) -> Tuple[List[dict], List[str]]:
    top = prompt_input.get("top_5_news") if isinstance(prompt_input.get("top_5_news"), dict) else {}
    items = [item for item in (top.get("items") or []) if isinstance(item, dict)]
    compact: List[dict] = []
    source_ids: List[str] = []
    for item in items:
        item_source_ids = [
            str(source_id) for source_id in (item.get("source_ids") or []) if source_id
        ]
        compact.append(
            {
                "rank": int(item.get("rank") or 0),
                "news_id": str(item.get("news_id") or ""),
                "source_ids": item_source_ids,
            }
        )
        for source_id in item_source_ids:
            if source_id not in source_ids:
                source_ids.append(source_id)
    return compact, source_ids


def _generated_top5_items(parse_result: dict) -> List[dict]:
    generated = parse_result.get("generated_briefing")
    if not isinstance(generated, dict):
        meta = (
            parse_result.get("parse_meta")
            if isinstance(parse_result.get("parse_meta"), dict)
            else {}
        )
        generated = meta.get("candidate_generated_briefing")
    if not isinstance(generated, dict):
        return []
    top = generated.get("top_5_news") if isinstance(generated.get("top_5_news"), dict) else {}
    items = top.get("items") if isinstance(top.get("items"), list) else []
    return [item for item in items if isinstance(item, dict)]


def _semantic_item_issue_generated_indexes(parse_result: dict) -> List[int]:
    """Extract generated-response indexes from item-level semantic validation issues."""
    indexes: List[int] = []
    for issue in parse_result.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        if str(issue.get("code") or "") not in {
            "korea_tech_top5_irrelevant_item",
            "top_5_fixed_source_ids_mismatch",
            "top_5_unapproved_url",
        }:
            continue
        match = re.search(
            r"top_5_news\.items\[(\d+)\]",
            str(issue.get("path") or issue.get("field") or ""),
        )
        if match:
            idx = int(match.group(1))
            if idx not in indexes:
                indexes.append(idx)
    return indexes


def _original_indexes_for_semantic_item_issues(
    parse_result: dict,
    prompt_input: dict,
) -> List[int]:
    """Map generated-response semantic issue indexes onto original TOP5 by news_id.

    Never falls back to treating a generated index as an original index. Issues
    that cannot be mapped safely are skipped so no arbitrary original slot is
    replaced.
    """
    generated_indexes = _semantic_item_issue_generated_indexes(parse_result)
    if not generated_indexes:
        return []

    original_top = (
        prompt_input.get("top_5_news")
        if isinstance(prompt_input.get("top_5_news"), dict)
        else {}
    )
    original_items = [
        item for item in (original_top.get("items") or []) if isinstance(item, dict)
    ]
    generated_items = _generated_top5_items(parse_result)

    original_by_news_id: Dict[str, List[int]] = {}
    for idx, item in enumerate(original_items):
        news_id = str(item.get("news_id") or "").strip()
        if not news_id:
            continue
        original_by_news_id.setdefault(news_id, []).append(idx)

    mapped: List[int] = []
    for generated_index in generated_indexes:
        if generated_index < 0 or generated_index >= len(generated_items):
            continue
        generated_item = generated_items[generated_index]
        news_id = str(generated_item.get("news_id") or "").strip()
        if not news_id:
            continue
        matches = original_by_news_id.get(news_id) or []
        if len(matches) != 1:
            # Missing or duplicate news_id — do not guess an original slot.
            continue
        original_index = matches[0]
        if original_index not in mapped:
            mapped.append(original_index)
    return sorted(mapped)


def _invalid_semantic_item_indexes(parse_result: dict, prompt_input: dict) -> List[int]:
    """Compatibility wrapper: original TOP5 indexes needing replacement."""
    return _original_indexes_for_semantic_item_issues(parse_result, prompt_input)


def _hydrate_diversity_source_fields(
    item: dict, source_map: Dict[str, dict]
) -> dict:
    """Copy source_name onto a TOP5 item when missing so diversity keys align."""
    if not isinstance(item, dict):
        return item
    if str(item.get("source_name") or "").strip():
        return item
    out = dict(item)
    for source_id in item.get("source_ids") or []:
        source = source_map.get(str(source_id))
        if not isinstance(source, dict):
            continue
        name = str(source.get("source_name") or "").strip()
        if name:
            out["source_name"] = name
            break
    return out


def _trial_passes_strict_diversity(
    trial: List[dict],
    *,
    candidate_news_id: Optional[str] = None,
    source_map: Optional[Dict[str, dict]] = None,
) -> bool:
    """Reject replacement trials that only admit the candidate via relaxation.

    The deterministic Korea sample TOP5 may already contain a pre-existing
    same-source relaxation among retained items. Do not reject a candidate
    solely for that baseline. Instead evaluate the candidate last against the
    retained set using the existing diversity gate; if the candidate itself is
    deferred then reintroduced (``diversity_relaxed``), reject it.
    """
    if not trial:
        return False
    hydrated = [
        _hydrate_diversity_source_fields(item, source_map or {})
        for item in trial
        if isinstance(item, dict)
    ]
    if candidate_news_id:
        retained = [
            item
            for item in hydrated
            if str(item.get("news_id") or "") != str(candidate_news_id)
        ]
        candidate_items = [
            item
            for item in hydrated
            if str(item.get("news_id") or "") == str(candidate_news_id)
        ]
        if len(candidate_items) != 1:
            return False
        ordered = retained + candidate_items
    else:
        ordered = list(hydrated)

    diversity = select_with_diversity_caps(ordered, required_count=len(ordered))
    selected_items = [
        item
        for item in (diversity.get("selected_items") or [])
        if isinstance(item, dict)
    ]
    if len(selected_items) != len(ordered):
        return False
    selected_ids = {str(item.get("news_id") or "") for item in selected_items}
    ordered_ids = {str(item.get("news_id") or "") for item in ordered}
    if not ordered_ids or selected_ids != ordered_ids:
        return False

    if candidate_news_id:
        for item in selected_items:
            if str(item.get("news_id") or "") != str(candidate_news_id):
                continue
            # Candidate only survived because caps were relaxed — reject.
            if item.get("diversity_relaxed"):
                return False
            return True
        return False

    summary = diversity.get("diversity_summary") if isinstance(diversity, dict) else {}
    if isinstance(summary, dict) and summary.get("relaxed_due_to_candidate_shortage"):
        return False
    if any(item.get("diversity_relaxed") for item in selected_items):
        return False
    return True


def _source_map_for_reconciliation(source_pack: dict) -> Dict[str, dict]:
    source_map: Dict[str, dict] = {}
    for key in ("sources", "backfill_sources"):
        for source in source_pack.get(key) if isinstance(source_pack.get(key), list) else []:
            if not isinstance(source, dict):
                continue
            source_id = str(source.get("source_id") or "").strip()
            if source_id:
                source_map[source_id] = source
    return source_map


def _fixed_prompt_input_for_top5(prompt_input: dict, top5: dict) -> dict:
    fixed = copy.deepcopy(prompt_input)
    fixed["top_5_news"] = copy.deepcopy(top5)
    fixed["selected_items"] = copy.deepcopy(top5.get("items") or [])
    pack = copy.deepcopy(fixed.get("source_pack") or {})
    all_sources = _source_map_for_reconciliation(pack)
    all_claims = [
        claim
        for key in ("claims", "backfill_claims")
        for claim in (pack.get(key) if isinstance(pack.get(key), list) else [])
        if isinstance(claim, dict)
    ]
    selected_items = [item for item in (top5.get("items") or []) if isinstance(item, dict)]
    selected_ids: List[str] = []
    for item in selected_items:
        for source_id in item.get("source_ids") or []:
            value = str(source_id)
            if value and value not in selected_ids:
                selected_ids.append(value)
    selected_news_ids = {str(item.get("news_id") or "") for item in selected_items}
    pack["sources"] = [
        copy.deepcopy(all_sources[source_id])
        for source_id in selected_ids
        if source_id in all_sources
    ]
    pack["claims"] = [
        copy.deepcopy(claim)
        for claim in all_claims
        if str(claim.get("claim_id") or "") in selected_news_ids
    ]
    pack["backfill_sources"] = []
    pack["backfill_claims"] = []
    fixed["source_pack"] = pack
    return fixed


def _reconcile_korea_top5(
    prompt_input: dict,
    parse_result: dict,
) -> Tuple[Optional[dict], List[str], List[str]]:
    """Replace bad generated slots from the original ranked backfill pool only."""
    generated_item_issue_indexes = _semantic_item_issue_generated_indexes(parse_result)
    invalid_indexes = _original_indexes_for_semantic_item_issues(parse_result, prompt_input)
    original_top = (
        prompt_input.get("top_5_news")
        if isinstance(prompt_input.get("top_5_news"), dict)
        else {}
    )
    original_items = [
        copy.deepcopy(item)
        for item in (original_top.get("items") or [])
        if isinstance(item, dict)
    ]
    if len(original_items) != 5:
        return None, [], []
    if not generated_item_issue_indexes:
        # Scope/heading/sequence-only semantic failures do not change article selection.
        return _fixed_prompt_input_for_top5(prompt_input, copy.deepcopy(original_top)), [], []
    if not invalid_indexes:
        # Item-level issues existed but could not be mapped safely by news_id.
        # Keep the deterministic original TOP5 and allow one fixed corrective call.
        return _fixed_prompt_input_for_top5(prompt_input, copy.deepcopy(original_top)), [], []

    source_pack = prompt_input.get("source_pack") if isinstance(prompt_input.get("source_pack"), dict) else {}
    source_map = _source_map_for_reconciliation(source_pack)
    backfill_claims = (
        source_pack.get("backfill_claims")
        if isinstance(source_pack.get("backfill_claims"), list)
        else []
    )
    sent_rows = [
        row for row in (recent_sent_news_log(PROGRAM_KOREA) or []) if isinstance(row, dict)
    ]
    used_news_ids = {str(item.get("news_id") or "") for item in original_items}
    replaced_source_ids: List[str] = []
    replacement_source_ids: List[str] = []
    cursor = 0

    for bad_index in invalid_indexes:
        if bad_index < 0 or bad_index >= len(original_items):
            return None, replaced_source_ids, replacement_source_ids
        bad_item = original_items[bad_index]
        chosen: Optional[dict] = None
        for candidate_index in range(cursor, len(backfill_claims)):
            cursor = candidate_index + 1
            claim = backfill_claims[candidate_index]
            if not isinstance(claim, dict):
                continue
            qualified, _reason = _claim_is_qualified(claim, source_map, PROGRAM_KOREA)
            if not qualified or not str(claim.get("business_implication") or "").strip():
                continue
            candidate = _claim_to_news_item(claim, rank=bad_index + 1, smap=source_map)
            news_id = str(candidate.get("news_id") or "")
            if not news_id or news_id in used_news_ids:
                continue
            if recent_log_duplicate_reason(candidate, sent_rows):
                continue
            retained = [
                item
                for idx, item in enumerate(original_items)
                if idx != bad_index and isinstance(item, dict)
            ]
            if recent_log_duplicate_reason(candidate, retained):
                continue
            trial = copy.deepcopy(original_items)
            trial[bad_index] = candidate
            for idx, item in enumerate(trial):
                item["rank"] = idx + 1
            if not _trial_passes_strict_diversity(
                trial,
                candidate_news_id=news_id,
                source_map=source_map,
            ):
                continue
            chosen = candidate
            break
        if chosen is None:
            return None, replaced_source_ids, replacement_source_ids
        for source_id in bad_item.get("source_ids") or []:
            value = str(source_id)
            if value and value not in replaced_source_ids:
                replaced_source_ids.append(value)
        for source_id in chosen.get("source_ids") or []:
            value = str(source_id)
            if value and value not in replacement_source_ids:
                replacement_source_ids.append(value)
        used_news_ids.discard(str(bad_item.get("news_id") or ""))
        used_news_ids.add(str(chosen.get("news_id") or ""))
        original_items[bad_index] = chosen

    for idx, item in enumerate(original_items):
        item["rank"] = idx + 1
    reconciled_top = {
        "news_scope": str(original_top.get("news_scope") or "korea"),
        "section_heading": str(original_top.get("section_heading") or "국내 테크 TOP 5"),
        "items": original_items,
    }
    if validate_top_5_news_block(PROGRAM_KOREA, reconciled_top):
        return None, replaced_source_ids, replacement_source_ids
    return (
        _fixed_prompt_input_for_top5(prompt_input, reconciled_top),
        replaced_source_ids,
        replacement_source_ids,
    )


def _default_global_recovery_diagnostics(
    *,
    call_state: Mapping[str, Any],
    attempted: bool = False,
    reason: Optional[str] = None,
    error_codes: Optional[Sequence[str]] = None,
    result: str = "not_needed",
) -> Dict[str, Any]:
    count = int(call_state.get("count") or 0)
    budget = int(call_state.get("budget") or GLOBAL_GENERATION_CALL_BUDGET)
    return {
        "global_recovery_attempted": attempted,
        "global_recovery_reason": reason,
        "global_recovery_error_codes": list(error_codes or []),
        "global_recovery_call_count": 1 if attempted else 0,
        "global_recovery_result": result,
        "global_generation_call_count": count,
        "global_generation_call_budget": budget,
        "global_generation_budget_exhausted": bool(call_state.get("exhausted")),
        "global_usage_by_attempt": [],
    }


def _preservable_fields_from_parse(parse_result: Mapping[str, Any]) -> List[str]:
    meta = (
        parse_result.get("parse_meta")
        if isinstance(parse_result.get("parse_meta"), dict)
        else {}
    )
    candidate = meta.get("candidate_generated_briefing")
    if not isinstance(candidate, dict):
        candidate = parse_result.get("generated_briefing")
    if not isinstance(candidate, dict):
        return []
    from keysuri_generation_prompt import KEYSURI_EXPECTED_TOP_LEVEL_KEYS

    present: List[str] = []
    for key in KEYSURI_EXPECTED_TOP_LEVEL_KEYS:
        value = candidate.get(key)
        if value not in (None, "", [], {}):
            present.append(str(key))
    return present


def _global_scaffold_fabricated_top5(parse_result: Mapping[str, Any]) -> bool:
    """True when the scaffold, not the model, produced the TOP5 articles."""
    meta = parse_result.get("parse_meta")
    if not isinstance(meta, Mapping):
        return False
    if not meta.get("global_contract_scaffold_applied"):
        return False
    repaired = meta.get("repaired_fields")
    if not isinstance(repaired, (list, tuple)):
        return False
    return "top_5_news" in {str(field) for field in repaired}


def _run_global_bounded_contract_repair(
    *,
    prompt_input: dict,
    program_id: str,
    raw_text: str,
    parse_result: dict,
    initial_codes: Sequence[str],
    initial_generation: Mapping[str, Any],
    initial_usage: MutableMapping[str, Any],
    gemini_caller: Any,
    project_id: Optional[str],
    model: Optional[str],
    usage_sink: Optional[MutableMapping[str, Any]],
    call_state: MutableMapping[str, Any],
    fallback_parse_result: Optional[dict] = None,
) -> Dict[str, Any]:
    """Bounded Global full-contract repair — never Korea item reconciliation.

    ``fallback_parse_result`` is a contract-valid parse that already exists and
    is merely low quality (today: a scaffold-completed one). When the corrective
    call cannot beat it, the run keeps it and lets the single canonical graded
    adjudicator rate it, instead of converting an editorial-quality problem into
    a hard generation block.
    """
    recovery_usage: Dict[str, Any] = {}
    repair_codes = _global_contract_repair_codes(initial_codes)
    diagnostics: Dict[str, Any] = {
        **initial_generation,
        "generation_attempt_count": 1,
        "generation_recovery_attempted": False,
        "generation_recovery_family": None,
        "generation_recovery_result": "not_needed",
        "initial_generation_issue_codes": list(initial_codes),
        "recovery_generation_issue_codes": [],
        "reconciled_top5": False,
        "replaced_source_ids": [],
        "replacement_source_ids": [],
        **_default_global_recovery_diagnostics(call_state=call_state),
        "global_usage_by_attempt": [
            {
                "attempt": "initial",
                "prompt_token_count": _optional_token_count(
                    initial_usage, "prompt_token_count", "input_tokens"
                ),
                "candidates_token_count": _optional_token_count(
                    initial_usage, "candidates_token_count", "output_tokens"
                ),
            }
        ],
    }
    if not repair_codes:
        diagnostics.update(
            _default_global_recovery_diagnostics(
                call_state=call_state,
                result="not_attempted_non_repairable",
            )
        )
        diagnostics["global_usage_by_attempt"] = diagnostics.get(
            "global_usage_by_attempt"
        ) or []
        _merge_into_diagnostics(
            diagnostics,
            _merge_generation_usage(usage_sink, initial_usage, recovery_usage),
            overwrite_keys=_USAGE_DIAGNOSTIC_OVERWRITE_KEYS,
        )
        return {
            "raw_text": raw_text,
            "parse_result": parse_result,
            "prompt_input": prompt_input,
            "generation_diagnostics": diagnostics,
        }

    remaining = int(call_state.get("budget") or GLOBAL_GENERATION_CALL_BUDGET) - int(
        call_state.get("count") or 0
    )
    if remaining < 1:
        call_state["exhausted"] = True
        diagnostics.update(
            _default_global_recovery_diagnostics(
                call_state=call_state,
                reason="budget_exhausted_before_repair",
                error_codes=repair_codes,
                result="not_attempted_budget_exhausted",
            )
        )
        diagnostics["global_generation_budget_exhausted"] = True
        _merge_into_diagnostics(
            diagnostics,
            _merge_generation_usage(usage_sink, initial_usage, recovery_usage),
            overwrite_keys=_USAGE_DIAGNOSTIC_OVERWRITE_KEYS,
        )
        return {
            "raw_text": raw_text,
            "parse_result": parse_result,
            "prompt_input": prompt_input,
            "generation_diagnostics": diagnostics,
        }

    from keysuri_generation_prompt import KEYSURI_EXPECTED_TOP_LEVEL_KEYS

    fixed_order, fixed_source_ids = _fixed_top5_context(prompt_input)
    missing_fields = list(
        (parse_result.get("parse_meta") or {}).get("missing_required_keys") or []
    )
    if not missing_fields:
        missing_fields = [
            key
            for key in KEYSURI_EXPECTED_TOP_LEVEL_KEYS
            if key
            not in set(_preservable_fields_from_parse(parse_result))
        ]
    corrective_context = {
        "failure_family": "GLOBAL_MALFORMED_CONTRACT",
        "initial_issue_codes": list(initial_codes),
        "missing_required_fields": missing_fields,
        "preservable_fields": _preservable_fields_from_parse(parse_result),
        "global_output_contract_keys": list(KEYSURI_EXPECTED_TOP_LEVEL_KEYS),
        "fixed_source_ids": fixed_source_ids,
        "fixed_top5_order": fixed_order,
        "fixed_deep_dive_source_ids": (
            list(fixed_order[0].get("source_ids") or []) if fixed_order else []
        ),
        "approved_deep_dive_source_ids": list(fixed_source_ids),
    }
    diagnostics["generation_recovery_attempted"] = True
    diagnostics["generation_recovery_family"] = "GLOBAL_MALFORMED_CONTRACT"
    diagnostics["generation_attempt_count"] = 2
    diagnostics["global_recovery_attempted"] = True
    diagnostics["global_recovery_reason"] = ",".join(repair_codes)
    diagnostics["global_recovery_error_codes"] = list(repair_codes)
    _safe_generation_event(
        "keysuri_global_contract_repair_attempted",
        program_id=program_id,
        failure_family="GLOBAL_MALFORMED_CONTRACT",
        generation_attempt_count=int(call_state.get("count") or 0) + 1,
        issue_codes=repair_codes,
    )
    calls_before_repair = int(call_state.get("count") or 0)
    fallback_raw_text = raw_text
    try:
        recovery_raw, recovery_generation = generate_keysuri_body_raw_text(
            prompt_input,
            gemini_caller=gemini_caller,
            project_id=project_id,
            model=model,
            usage_sink=recovery_usage,
            corrective_context=corrective_context,
            generation_call_state=call_state,
        )
        diagnostics["recovery_generation_diagnostics"] = recovery_generation
        recovery_parse = _parse_with_schema_alias_fallback(
            recovery_raw, program_id, prompt_input
        )
        recovery_codes = _issue_codes(recovery_parse)
        diagnostics["recovery_generation_issue_codes"] = recovery_codes
        raw_text = recovery_raw
        parse_result = recovery_parse
    except KeysuriGeminiError as exc:
        recovery_codes = list(
            dict.fromkeys(
                [
                    "generation_recovery_call_failed",
                    *[
                        str(code)
                        for code in (
                            (getattr(exc, "diagnostics", None) or {}).get("issue_codes")
                            or []
                        )
                        if code
                    ],
                ]
            )
        )
        diagnostics["recovery_generation_issue_codes"] = recovery_codes
        parse_result = {
            "parse_status": "parsed_invalid",
            "program_id": program_id,
            "issues": [
                {
                    "code": code,
                    "message": "Global contract repair failed safely",
                    "path": "generation",
                }
                for code in recovery_codes
            ],
            "generated_briefing": None,
            "parse_meta": {"parse_failure_stage": "global_contract_repair"},
        }

    # A corrective call that comes back as another display shell gets scaffolded
    # into a contract-valid payload just like the first one did. That is not a
    # recovery — it is the same empty briefing wearing the same contract — so it
    # must not be reported as "succeeded".
    recovery_scaffold_fabricated = _global_scaffold_fabricated_top5(parse_result)
    success = (
        parse_result.get("parse_status") == "parsed_valid"
        and not recovery_scaffold_fabricated
    )
    diagnostics["global_recovery_scaffold_fabricated_top5"] = bool(
        recovery_scaffold_fabricated
    )
    if not success and isinstance(fallback_parse_result, dict):
        # The corrective call did not beat the contract-valid output we already
        # held. Keep that one so the graded adjudicator still rates a real
        # candidate rather than the run collapsing to a generation block.
        parse_result = fallback_parse_result
        raw_text = fallback_raw_text
        diagnostics["global_recovery_fallback_to_prior_parse"] = True
    diagnostics.setdefault("global_recovery_fallback_to_prior_parse", False)
    repair_calls = max(
        0, int(call_state.get("count") or 0) - calls_before_repair
    )
    diagnostics["generation_recovery_result"] = "succeeded" if success else "failed"
    diagnostics["global_recovery_result"] = "succeeded" if success else "failed"
    diagnostics["global_recovery_call_count"] = repair_calls
    diagnostics["global_generation_call_count"] = int(call_state.get("count") or 0)
    diagnostics["global_generation_call_budget"] = int(
        call_state.get("budget") or GLOBAL_GENERATION_CALL_BUDGET
    )
    diagnostics["global_generation_budget_exhausted"] = bool(call_state.get("exhausted"))
    usage_attempts = list(diagnostics.get("global_usage_by_attempt") or [])
    usage_attempts.append(
        {
            "attempt": "contract_repair",
            "prompt_token_count": _optional_token_count(
                recovery_usage, "prompt_token_count", "input_tokens"
            ),
            "candidates_token_count": _optional_token_count(
                recovery_usage, "candidates_token_count", "output_tokens"
            ),
        }
    )
    diagnostics["global_usage_by_attempt"] = usage_attempts
    _merge_into_diagnostics(
        diagnostics,
        _merge_generation_usage(usage_sink, initial_usage, recovery_usage),
        overwrite_keys=_USAGE_DIAGNOSTIC_OVERWRITE_KEYS,
    )
    _safe_generation_event(
        "keysuri_global_contract_repair_succeeded"
        if success
        else "keysuri_global_contract_repair_failed",
        program_id=program_id,
        failure_family="GLOBAL_MALFORMED_CONTRACT",
        generation_attempt_count=int(call_state.get("count") or 0),
        issue_codes=diagnostics["recovery_generation_issue_codes"],
        result=diagnostics["global_recovery_result"],
    )
    return {
        "raw_text": raw_text,
        "parse_result": parse_result,
        "prompt_input": prompt_input,
        "generation_diagnostics": diagnostics,
    }


def _enrich_parse_generation_contract(
    parse_result: Dict[str, Any],
    *,
    program_id: str,
    diagnostics: Mapping[str, Any],
    model: Optional[str] = None,
    prompt_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach a bounded generation_contract onto parse_result (mutates and returns)."""
    base = sanitize_generation_contract_record(parse_result.get("generation_contract"))
    if not base:
        base = generation_contract_record(
            program_id,
            model=model,
            prompt_text=prompt_text,
        )
    attempt_count = int(
        diagnostics.get("generation_attempt_count")
        or diagnostics.get("global_generation_call_count")
        or base.get("actual_attempt_count")
        or 1
    )
    enriched = generation_contract_record(
        program_id,
        attempt=attempt_count,
        actual_attempt_count=attempt_count,
        retry_reason=str(
            diagnostics.get("retry_reason")
            or diagnostics.get("generation_recovery_family")
            or diagnostics.get("global_recovery_reason")
            or ""
        )
        or None,
        retry_reason_family=str(
            diagnostics.get("generation_recovery_family")
            or diagnostics.get("global_recovery_reason")
            or ""
        )
        or None,
        recovery_result=str(
            diagnostics.get("generation_recovery_result")
            or diagnostics.get("global_recovery_result")
            or "not_needed"
        ),
        model=model or base.get("model_identifier"),
        prompt_text=prompt_text,
    )
    # Preserve fingerprints from the parse-time contract when prompt_text absent.
    if not prompt_text and base.get("prompt_template_fingerprint"):
        enriched["prompt_template_fingerprint"] = base["prompt_template_fingerprint"]
    if base.get("schema_fingerprint"):
        enriched["schema_fingerprint"] = base["schema_fingerprint"]
    parse_result["generation_contract"] = sanitize_generation_contract_record(enriched)
    return parse_result


def generate_keysuri_with_bounded_recovery(
    prompt_input: dict,
    *,
    gemini_caller: Any,
    project_id: Optional[str] = None,
    model: Optional[str] = None,
    usage_sink: Optional[MutableMapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Run Kee-Suri generation with bounded recovery.

    Korea: at most one corrective attempt (semantic reconciliation + structural).
    Global: unified call budget of 2 (initial + at most one corrective call,
    either MAX_TOKENS compact or full-contract repair). Never copies Korea
    item-level reconciliation.
    """
    program_id = str(prompt_input.get("program_id") or "")
    is_global = _is_global_program(program_id)
    call_state: Dict[str, Any] = {
        "count": 0,
        "budget": GLOBAL_GENERATION_CALL_BUDGET if is_global else None,
        "exhausted": False,
    }
    initial_usage: Dict[str, Any] = {}
    recovery_usage: Dict[str, Any] = {}
    raw_text, initial_generation = generate_keysuri_body_raw_text(
        prompt_input,
        gemini_caller=gemini_caller,
        project_id=project_id,
        model=model,
        usage_sink=initial_usage,
        generation_call_state=call_state if is_global else None,
    )
    parse_result = _parse_with_schema_alias_fallback(raw_text, program_id, prompt_input)
    initial_codes = _issue_codes(parse_result)
    diagnostics: Dict[str, Any] = {
        **initial_generation,
        "generation_attempt_count": 1,
        "generation_recovery_attempted": False,
        "generation_recovery_family": None,
        "generation_recovery_result": "not_needed",
        "initial_generation_issue_codes": initial_codes,
        "recovery_generation_issue_codes": [],
        "reconciled_top5": False,
        "replaced_source_ids": [],
        "replacement_source_ids": [],
    }
    if is_global:
        diagnostics.update(
            _default_global_recovery_diagnostics(call_state=call_state)
        )
        diagnostics["global_usage_by_attempt"] = [
            {
                "attempt": "initial",
                "prompt_token_count": _optional_token_count(
                    initial_usage, "prompt_token_count", "input_tokens"
                ),
                "candidates_token_count": _optional_token_count(
                    initial_usage, "candidates_token_count", "output_tokens"
                ),
            }
        ]
        if initial_generation.get("retry_applied"):
            diagnostics["global_usage_by_attempt"].append(
                {
                    "attempt": "max_tokens_compact_retry",
                    "prompt_token_count": None,
                    "candidates_token_count": None,
                }
            )

    scaffold_fabricated = is_global and _global_scaffold_fabricated_top5(parse_result)
    if parse_result.get("parse_status") == "parsed_valid" and not scaffold_fabricated:
        _merge_into_diagnostics(
            diagnostics,
            _merge_generation_usage(usage_sink, initial_usage, recovery_usage),
            overwrite_keys=_USAGE_DIAGNOSTIC_OVERWRITE_KEYS,
        )
        _enrich_parse_generation_contract(
            parse_result,
            program_id=program_id,
            diagnostics=diagnostics,
            model=model,
        )
        return {
            "raw_text": raw_text,
            "parse_result": parse_result,
            "prompt_input": prompt_input,
            "generation_diagnostics": diagnostics,
        }

    if is_global:
        repair_codes = list(initial_codes)
        fallback_parse_result = None
        if scaffold_fabricated:
            # Structurally valid, editorially empty: spend the corrective call,
            # but keep this parse to fall back on.
            if GLOBAL_SCAFFOLD_FABRICATED_TOP5_CODE not in repair_codes:
                repair_codes.append(GLOBAL_SCAFFOLD_FABRICATED_TOP5_CODE)
            fallback_parse_result = copy.deepcopy(parse_result)
        return _run_global_bounded_contract_repair(
            prompt_input=prompt_input,
            program_id=program_id,
            raw_text=raw_text,
            parse_result=parse_result,
            initial_codes=repair_codes,
            initial_generation=initial_generation,
            initial_usage=initial_usage,
            gemini_caller=gemini_caller,
            project_id=project_id,
            model=model,
            usage_sink=usage_sink,
            call_state=call_state,
            fallback_parse_result=fallback_parse_result,
        )

    if program_id != PROGRAM_KOREA:
        _merge_into_diagnostics(
            diagnostics,
            _merge_generation_usage(usage_sink, initial_usage, recovery_usage),
            overwrite_keys=_USAGE_DIAGNOSTIC_OVERWRITE_KEYS,
        )
        return {
            "raw_text": raw_text,
            "parse_result": parse_result,
            "prompt_input": prompt_input,
            "generation_diagnostics": diagnostics,
        }

    failure_family = _classify_generation_failure(initial_codes)
    diagnostics["generation_recovery_family"] = failure_family
    _safe_generation_event(
        "keysuri_initial_generation_validation_failure",
        program_id=program_id,
        failure_family=failure_family,
        generation_attempt_count=1,
        issue_codes=initial_codes,
    )
    if failure_family is None:
        diagnostics["generation_recovery_result"] = "not_attempted_unknown_failure"
        _merge_into_diagnostics(
            diagnostics,
            _merge_generation_usage(usage_sink, initial_usage, recovery_usage),
            overwrite_keys=_USAGE_DIAGNOSTIC_OVERWRITE_KEYS,
        )
        return {
            "raw_text": raw_text,
            "parse_result": parse_result,
            "prompt_input": prompt_input,
            "generation_diagnostics": diagnostics,
        }

    corrective_input = prompt_input
    replaced_source_ids: List[str] = []
    replacement_source_ids: List[str] = []
    if failure_family == SEMANTIC_SCOPE_FAILURE:
        corrective_input, replaced_source_ids, replacement_source_ids = _reconcile_korea_top5(
            prompt_input, parse_result
        )
        diagnostics["reconciled_top5"] = bool(replaced_source_ids or replacement_source_ids)
        diagnostics["replaced_source_ids"] = replaced_source_ids
        diagnostics["replacement_source_ids"] = replacement_source_ids
        if corrective_input is None:
            parse_result = dict(parse_result)
            parse_result["issues"] = list(parse_result.get("issues") or []) + [
                {
                    "code": RECOVERY_RECONCILIATION_INSUFFICIENT,
                    "message": "Deterministic Korea TOP5 reconciliation could not produce five valid candidates",
                    "path": "top_5_news.items",
                }
            ]
            diagnostics["generation_recovery_result"] = "not_attempted_reconciliation_failed"
            diagnostics["recovery_generation_issue_codes"] = [
                RECOVERY_RECONCILIATION_INSUFFICIENT
            ]
            _merge_into_diagnostics(
                diagnostics,
                _merge_generation_usage(usage_sink, initial_usage, recovery_usage),
                overwrite_keys=_USAGE_DIAGNOSTIC_OVERWRITE_KEYS,
            )
            _safe_generation_event(
                "keysuri_generation_recovery_failed",
                program_id=program_id,
                failure_family=failure_family,
                generation_attempt_count=1,
                issue_codes=diagnostics["recovery_generation_issue_codes"],
                result=diagnostics["generation_recovery_result"],
            )
            return {
                "raw_text": raw_text,
                "parse_result": parse_result,
                "prompt_input": prompt_input,
                "generation_diagnostics": diagnostics,
            }

    fixed_order, fixed_source_ids = _fixed_top5_context(corrective_input)
    # Preferred deep-dive ids remain TOP1-first for the prompt hint, but the
    # approved validation set is the full TOP5 union (fixed_source_ids).
    preferred_deep_dive_source_ids = (
        list(fixed_order[0].get("source_ids") or []) if fixed_order else []
    )
    corrective_context = {
        "failure_family": failure_family,
        "initial_issue_codes": initial_codes,
        "missing_required_fields": list(
            (parse_result.get("parse_meta") or {}).get("missing_required_keys") or []
        ),
        "fixed_source_ids": fixed_source_ids,
        "fixed_top5_order": fixed_order,
        "fixed_deep_dive_source_ids": preferred_deep_dive_source_ids,
        "approved_deep_dive_source_ids": list(fixed_source_ids),
    }
    diagnostics["generation_recovery_attempted"] = True
    diagnostics["generation_attempt_count"] = 2
    _safe_generation_event(
        "keysuri_generation_recovery_attempted",
        program_id=program_id,
        failure_family=failure_family,
        generation_attempt_count=2,
        issue_codes=initial_codes,
        replaced_source_ids=replaced_source_ids,
        replacement_source_ids=replacement_source_ids,
    )
    try:
        recovery_raw, recovery_generation = generate_keysuri_body_raw_text(
            corrective_input,
            gemini_caller=gemini_caller,
            project_id=project_id,
            model=model,
            usage_sink=recovery_usage,
            corrective_context=corrective_context,
        )
        diagnostics["recovery_generation_diagnostics"] = recovery_generation
        recovery_parse = _parse_with_schema_alias_fallback(
            recovery_raw, program_id, corrective_input
        )
        recovery_parse = _apply_fixed_deep_dive_contract(
            recovery_parse, fixed_source_ids
        )
        recovery_codes = _issue_codes(recovery_parse)
        diagnostics["recovery_generation_issue_codes"] = recovery_codes
        raw_text = recovery_raw
        parse_result = recovery_parse
    except KeysuriGeminiError as exc:
        recovery_codes = list(
            dict.fromkeys(
                [
                    "generation_recovery_call_failed",
                    *[
                        str(code)
                        for code in (
                            (getattr(exc, "diagnostics", None) or {}).get("issue_codes")
                            or []
                        )
                        if code
                    ],
                ]
            )
        )
        diagnostics["recovery_generation_issue_codes"] = recovery_codes
        parse_result = {
            "parse_status": "parsed_invalid",
            "program_id": program_id,
            "issues": [
                {
                    "code": code,
                    "message": "Corrective generation failed safely",
                    "path": "generation",
                }
                for code in recovery_codes
            ],
            "generated_briefing": None,
            "parse_meta": {"parse_failure_stage": "corrective_generation"},
        }

    success = parse_result.get("parse_status") == "parsed_valid"
    diagnostics["generation_recovery_result"] = "succeeded" if success else "failed"
    _merge_into_diagnostics(
        diagnostics,
        _merge_generation_usage(usage_sink, initial_usage, recovery_usage),
        overwrite_keys=_USAGE_DIAGNOSTIC_OVERWRITE_KEYS,
    )
    _safe_generation_event(
        "keysuri_generation_recovery_succeeded"
        if success
        else "keysuri_generation_recovery_failed",
        program_id=program_id,
        failure_family=failure_family,
        generation_attempt_count=2,
        issue_codes=diagnostics["recovery_generation_issue_codes"],
        replaced_source_ids=replaced_source_ids,
        replacement_source_ids=replacement_source_ids,
        result=diagnostics["generation_recovery_result"],
    )
    return {
        "raw_text": raw_text,
        "parse_result": parse_result,
        "prompt_input": corrective_input,
        "generation_diagnostics": diagnostics,
    }

def scan_sample_markers(*texts: str) -> List[SampleMarkerHit]:
    hits: List[SampleMarkerHit] = []
    for text in texts:
        if not text:
            continue
        lower = text.lower()
        for marker, code in SAMPLE_MARKER_PATTERNS:
            idx = lower.find(marker.lower())
            if idx < 0:
                continue
            start = max(0, idx - 40)
            end = min(len(text), idx + len(marker) + 40)
            hits.append(
                SampleMarkerHit(
                    code=code,
                    marker=marker,
                    context=text[start:end].replace("\n", " "),
                )
            )
    return hits


def scan_placeholder_markers(*texts: str) -> List[SampleMarkerHit]:
    hits: List[SampleMarkerHit] = []
    for text in texts:
        if not text:
            continue
        lower = text.lower()
        for marker, code in GENERATION_PLACEHOLDER_PATTERNS:
            idx = lower.find(marker.lower())
            if idx < 0:
                continue
            start = max(0, idx - 40)
            end = min(len(text), idx + len(marker) + 40)
            hits.append(
                SampleMarkerHit(
                    code=code,
                    marker=marker,
                    context=text[start:end].replace("\n", " "),
                )
            )
    return hits


def extract_generated_body_text(generated_briefing: dict) -> Dict[str, str]:
    out: Dict[str, str] = {}
    top = generated_briefing.get("top_5_news") if isinstance(generated_briefing.get("top_5_news"), dict) else {}
    items = top.get("items") if isinstance(top.get("items"), list) else []
    headlines = []
    for item in items[:5]:
        if isinstance(item, dict):
            headlines.append(str(item.get("headline") or "").strip())
    out["top_5"] = " | ".join(h for h in headlines if h)

    deep = generated_briefing.get("deep_dive") if isinstance(generated_briefing.get("deep_dive"), dict) else {}
    out["deep_dive"] = str(deep.get("body") or "").strip()

    one = (
        generated_briefing.get("one_line_checkpoint")
        if isinstance(generated_briefing.get("one_line_checkpoint"), dict)
        else {}
    )
    out["one_line_checkpoint"] = str(one.get("body") or "").strip()

    closing = (
        generated_briefing.get("closing_sources")
        if isinstance(generated_briefing.get("closing_sources"), dict)
        else {}
    )
    out["closing_sources"] = str(closing.get("closing_message") or "").strip()
    return out


def _default_output_paths(
    program_id: str,
    out_dir: Path,
    *,
    generated: bool = False,
    contract_preview: bool = False,
) -> Tuple[Path, Path]:
    stamp = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d_%H%M%S")
    slug = "global" if program_id == PROGRAM_GLOBAL else "korea"
    if contract_preview and generated:
        html_test_dir = out_dir / "html_test"
        html_test_dir.mkdir(parents=True, exist_ok=True)
        pack = out_dir / f"keysuri_{slug}_live_source_smoke_generated_{stamp}.json"
        html = html_test_dir / f"keysuri_{slug}_live_generated_contract_preview_{stamp}.html"
    elif generated:
        pack = out_dir / f"keysuri_{slug}_live_source_smoke_generated_{stamp}.json"
        html = out_dir / f"keysuri_{slug}_live_source_smoke_generated_owner_review_{stamp}.html"
    else:
        pack = out_dir / f"keysuri_{slug}_live_source_smoke_{stamp}.json"
        html = out_dir / f"keysuri_{slug}_live_source_smoke_owner_review_{stamp}.html"
    return pack, html


def _feeds_for_program(program_id: str) -> Tuple[Dict[str, str], ...]:
    pid = str(program_id or "").strip()
    if pid == PROGRAM_GLOBAL or pid.startswith("keysuri_global"):
        return GLOBAL_TECH_SMOKE_FEEDS
    if pid == PROGRAM_KOREA or pid.startswith("keysuri_korea"):
        return KOREA_TECH_SMOKE_FEEDS
    raise ValueError(f"No live smoke feed list configured for {program_id!r}")


def extract_contract_visible_body_text(fixture: dict, generated_briefing: dict) -> Dict[str, str]:
    """Extract Korean visible body fields for owner review report."""
    out = extract_generated_body_text(generated_briefing)
    items = fixture.get("top_5_items") if isinstance(fixture.get("top_5_items"), list) else []

    card_lines: List[str] = []
    for idx, item in enumerate(items[:5], start=1):
        if not isinstance(item, dict):
            continue
        card_lines.append(
            "\n".join(
                [
                    f"[TOP {idx}]",
                    f"한국어 제목: {item.get('korean_title') or item.get('headline') or ''}",
                    f"무슨 일이 있었나: {item.get('what_happened') or ''}",
                    f"왜 지금 중요한가: {item.get('why_now') or item.get('why_it_matters') or ''}",
                    f"주인님 관점: {item.get('owner_angle') or item.get('business_implication') or ''}",
                    (
                        f"키수리 판단: "
                        f"{item.get('keysuri_judgment_label') or ''} — "
                        f"{item.get('keysuri_judgment') if isinstance(item.get('keysuri_judgment'), str) else ''}"
                    ).strip(" —"),
                    f"다음 확인 포인트: {item.get('next_watch') or ''}",
                    f"출처: {item.get('source_name') or ''} | {item.get('source_url') or ''}",
                ]
            )
        )
    out["top_5_cards"] = "\n\n".join(card_lines)
    out["top_5_korean_titles"] = " | ".join(
        str(i.get("korean_title") or i.get("headline") or "").strip()
        for i in items[:5]
        if isinstance(i, dict)
    )
    out["opening_lead"] = str(fixture.get("opening_lead") or "").strip()
    out["deep_dive_body"] = str(fixture.get("deep_dive_body") or "").strip()
    out["one_line_checkpoint"] = str(fixture.get("one_line_checkpoint") or "").strip()
    out["closing_message"] = str(fixture.get("closing_message") or "").strip()
    out["selected_title"] = str(fixture.get("selected_title") or "").strip()
    layers = fixture.get("deep_dive_layers") if isinstance(fixture.get("deep_dive_layers"), list) else []
    out["deep_dive_layers"] = " / ".join(
        str(layer.get("layer_title") or "") for layer in layers if isinstance(layer, dict)
    )
    src_list = fixture.get("source_list") if isinstance(fixture.get("source_list"), list) else []
    out["closing_source_list"] = "\n".join(
        f"- {s.get('source_name') or ''} | {s.get('source_url') or ''} | {s.get('fetched_at') or s.get('checked_at') or ''}"
        for s in src_list
        if isinstance(s, dict)
    )
    return out


def run_keysuri_live_source_smoke(
    *,
    program_id: str = PROGRAM_GLOBAL,
    max_items: int = 5,
    allow_network: bool = True,
    use_gemini: bool = False,
    contract_preview: bool = False,
    project_id: Optional[str] = None,
    model: Optional[str] = None,
    send: bool = False,
    send_confirm: Optional[str] = None,
    recipients: Optional[Sequence[str]] = None,
    html_out: Optional[Path] = None,
    source_pack_out: Optional[Path] = None,
    frozen_source_pack_path: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    repo_root: Optional[Path] = None,
    email_subject: Optional[str] = None,
    gemini_caller=None,
    top_shot_image_path: Optional[Path] = None,
    global_selection_report_path: Optional[Path] = None,
    trigger_source: Optional[str] = None,
    usage_sink: Optional[MutableMapping[str, Any]] = None,
) -> LiveSourceSmokeResult:
    repo = repo_root or Path(__file__).resolve().parent
    preview_dir = out_dir or (repo / "output" / "keysuri_preview")
    preview_dir.mkdir(parents=True, exist_ok=True)

    if contract_preview and not use_gemini:
        return LiveSourceSmokeResult(
            ok=False,
            program_id=program_id,
            source_pack_path="",
            html_path="",
            fetched_item_count=0,
            feed_urls_used=[],
            sample_marker_pass=False,
            placeholder_gate_pass=False,
            contract_preview=True,
            side_effects={
                "called_gemini": False,
                "fetched_live_news": False,
                "sent_email": False,
                "published_naver": False,
                "changed_scheduler": False,
                "called_image_api": False,
                "mutated_admin_runs": False,
            },
            error="--contract-preview requires --use-gemini",
        )

    pack_path, html_path = _default_output_paths(
        program_id,
        preview_dir,
        generated=use_gemini,
        contract_preview=contract_preview,
    )
    if source_pack_out is not None:
        pack_path = source_pack_out
    if html_out is not None:
        html_path = html_out

    subject = email_subject or (
        _DEFAULT_GENERATED_EMAIL_SUBJECT if use_gemini else _DEFAULT_EMAIL_SUBJECT
    )

    side_effects = {
        "called_gemini": False,
        "fetched_live_news": False,
        "sent_email": False,
        "published_naver": False,
        "changed_scheduler": False,
        "called_image_api": False,
        "mutated_admin_runs": False,
    }

    frozen_path = Path(frozen_source_pack_path) if frozen_source_pack_path else None
    if frozen_path is not None:
        # Reliability/preflight path: freeze selection, still allow Gemini.
        try:
            source_pack = json.loads(frozen_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return LiveSourceSmokeResult(
                ok=False,
                program_id=program_id,
                source_pack_path=str(frozen_path),
                html_path=str(html_path),
                fetched_item_count=0,
                feed_urls_used=[],
                sample_marker_pass=False,
                placeholder_gate_pass=False,
                fetched_live_news=False,
                use_gemini=use_gemini,
                side_effects=side_effects,
                error=f"frozen_source_pack_unreadable:{exc}",
            )
        if not isinstance(source_pack, dict):
            return LiveSourceSmokeResult(
                ok=False,
                program_id=program_id,
                source_pack_path=str(frozen_path),
                html_path=str(html_path),
                fetched_item_count=0,
                feed_urls_used=[],
                sample_marker_pass=False,
                placeholder_gate_pass=False,
                fetched_live_news=False,
                use_gemini=use_gemini,
                side_effects=side_effects,
                error="frozen_source_pack_not_object",
            )
        feed_urls = []
        src_n = len(source_pack.get("sources") or [])
        fetched = [object()] * src_n  # length only; no live fetch
        if source_pack_out is not None:
            pack_path = Path(source_pack_out)
            pack_path.parent.mkdir(parents=True, exist_ok=True)
            pack_path.write_text(
                json.dumps(source_pack, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        else:
            pack_path = frozen_path
    elif not allow_network:
        return LiveSourceSmokeResult(
            ok=False,
            program_id=program_id,
            source_pack_path=str(pack_path),
            html_path=str(html_path),
            fetched_item_count=0,
            feed_urls_used=[],
            sample_marker_pass=False,
            placeholder_gate_pass=False,
            fetched_live_news=False,
            use_gemini=use_gemini,
            side_effects=side_effects,
            error="Network disabled (--no-network) but live source smoke requires fetch",
        )
    else:
        feeds = _feeds_for_program(program_id)
        feed_urls = [f["feed_url"] for f in feeds]
        fetched = []
        per_feed = max(1, DEFAULT_ITEMS_PER_FEED)
        fetch_errors: List[str] = []

        for feed in feeds:
            try:
                fetched.extend(
                    fetch_feed_items(feed, max_items=per_feed, timeout_sec=DEFAULT_FETCH_TIMEOUT_SEC)
                )
            except (URLError, TimeoutError, ET.ParseError, ValueError) as exc:
                fetch_errors.append(f"{feed['feed_id']}: {exc}")

        if len(fetched) < max_items:
            return LiveSourceSmokeResult(
                ok=False,
                program_id=program_id,
                source_pack_path=str(pack_path),
                html_path=str(html_path),
                fetched_item_count=len(fetched),
                feed_urls_used=feed_urls,
                sample_marker_pass=False,
                placeholder_gate_pass=False,
                fetched_live_news=len(fetched) > 0,
                use_gemini=use_gemini,
                side_effects=side_effects,
                error=(
                    f"Insufficient live feed items ({len(fetched)}); fetch errors: "
                    + "; ".join(fetch_errors[:5])
                ),
            )

        side_effects["fetched_live_news"] = True
        if program_id == PROGRAM_GLOBAL:
            candidate_pack = build_live_candidate_source_pack(program_id, fetched)
            selection = score_candidates_from_source_pack(candidate_pack)
            source_pack = apply_scored_selection_to_source_pack(candidate_pack, selection)
            debug_dir = preview_dir / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            dbg_stamp = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d_%H%M%S")
            write_global_top5_selection_report(
                selection,
                debug_dir / f"global_top5_selection_{dbg_stamp}.json",
            )
        else:
            global_report: Optional[dict] = None
            if global_selection_report_path is not None:
                try:
                    global_report = load_global_selection_report(global_selection_report_path)
                except (FileNotFoundError, ValueError) as exc:
                    return LiveSourceSmokeResult(
                        ok=False,
                        program_id=program_id,
                        source_pack_path=str(pack_path),
                        html_path=str(html_path),
                        fetched_item_count=len(fetched),
                        feed_urls_used=feed_urls,
                        sample_marker_pass=False,
                        placeholder_gate_pass=False,
                        fetched_live_news=True,
                        use_gemini=use_gemini,
                        side_effects=side_effects,
                        error=str(exc),
                    )
            candidate_pack = build_live_candidate_source_pack(program_id, fetched)
            selection = score_korea_candidates_from_source_pack(
                candidate_pack,
                global_selection_report=global_report,
            )
            source_pack = apply_korea_scored_selection_to_source_pack(candidate_pack, selection)
            debug_dir = preview_dir / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            dbg_stamp = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d_%H%M%S")
            write_korea_top5_selection_report(
                selection,
                debug_dir / f"korea_top5_selection_{dbg_stamp}.json",
            )
        # Written below after source-text normalization so the persisted pack is
        # exactly what ranking/prompt generation consumes.

    source_pack = normalize_keysuri_source_pack(source_pack)
    if frozen_path is None or source_pack_out is not None:
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(
            json.dumps(source_pack, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    prompt_input = build_keysuri_prompt_input(
        program_id, source_pack, trigger_source=trigger_source
    )
    if prompt_input.get("prompt_status") != "ready_for_generation":
        funnel = prompt_input.get("candidate_funnel_summary")
        return LiveSourceSmokeResult(
            ok=False,
            program_id=program_id,
            source_pack_path=str(pack_path),
            html_path=str(html_path),
            fetched_item_count=len(fetched),
            feed_urls_used=feed_urls,
            sample_marker_pass=False,
            placeholder_gate_pass=False,
            fetched_live_news=bool(side_effects.get("fetched_live_news")),
            use_gemini=use_gemini,
            side_effects=side_effects,
            candidate_funnel_summary=funnel if isinstance(funnel, dict) else None,
            hold_reason=prompt_input.get("hold_reason"),
            error=f"prompt_status={prompt_input.get('prompt_status')!r} after source pack",
        )

    record_memory_stage("after_source_selection")

    generated_briefing = None
    parse_status: Optional[str] = None
    parse_meta: Dict[str, Any] = {}
    parse_internal_codes: List[str] = []
    raw_response_path: Optional[str] = None
    generated_body: Dict[str, str] = {}
    generation_diagnostics: Dict[str, Any] = {}
    generation_contract: Dict[str, Any] = {}

    if use_gemini:
        caller = gemini_caller or call_keysuri_gemini_text
        try:
            generation_result = generate_keysuri_with_bounded_recovery(
                prompt_input,
                gemini_caller=caller,
                project_id=project_id,
                model=model,
                usage_sink=usage_sink,
            )
            raw_text = str(generation_result["raw_text"])
            parse_result = generation_result["parse_result"]
            prompt_input = generation_result["prompt_input"]
            generation_diagnostics = generation_result["generation_diagnostics"]
            side_effects["called_gemini"] = True
            record_memory_stage("after_model_generation")
        except KeysuriGeminiError as exc:
            record_memory_stage("after_model_generation")
            gen_diag = dict(getattr(exc, "diagnostics", None) or {})
            issue_codes = []
            msg = str(exc)
            if "keysuri_gemini_max_tokens_no_text" in msg:
                issue_codes.append("keysuri_gemini_max_tokens_no_text")
            elif "keysuri_gemini_response_no_parts" in msg:
                issue_codes.append("keysuri_gemini_response_no_parts")
            for code in gen_diag.get("issue_codes") or []:
                if code and code not in issue_codes:
                    issue_codes.append(str(code))
            return LiveSourceSmokeResult(
                ok=False,
                program_id=program_id,
                source_pack_path=str(pack_path.resolve()),
                html_path=str(html_path.resolve()),
                fetched_item_count=len(fetched),
                feed_urls_used=feed_urls,
                sample_marker_pass=False,
                placeholder_gate_pass=False,
                fetched_live_news=True,
                use_gemini=True,
                side_effects=side_effects,
                generation_diagnostics=gen_diag,
                generation_attempt_count=1,
                validation_issues=issue_codes,
                candidate_funnel_summary=(
                    prompt_input.get("candidate_funnel_summary")
                    if isinstance(prompt_input.get("candidate_funnel_summary"), dict)
                    else None
                ),
                hold_reason=prompt_input.get("hold_reason"),
                exposure_dedup_backfill_used=bool(
                    prompt_input.get("exposure_dedup_backfill_used")
                ),
                error=str(exc),
            )

        stamp = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d_%H%M%S")
        raw_path = preview_dir / f"keysuri_live_gemini_raw_response_{stamp}.txt"
        raw_path.write_text(raw_text, encoding="utf-8")
        raw_response_path = str(raw_path.resolve())

        parse_status = str(parse_result.get("parse_status") or "")
        parse_meta = (
            parse_result.get("parse_meta")
            if isinstance(parse_result.get("parse_meta"), dict)
            else {}
        )
        if isinstance(parse_result, dict):
            _enrich_parse_generation_contract(
                parse_result,
                program_id=program_id,
                diagnostics=generation_diagnostics,
                model=model,
            )
        generation_contract = sanitize_generation_contract_record(
            parse_result.get("generation_contract") if isinstance(parse_result, dict) else {}
        )
        parse_internal_codes = _parse_internal_issue_codes(parse_result)
        if parse_status != "parsed_valid":
            issues = parse_result.get("issues") or []
            issue_text = "; ".join(
                f"{i.get('code')}: {i.get('message')}" for i in issues[:5] if isinstance(i, dict)
            )
            # Full issue-code list (not just the first-5 summary baked into
            # `error`) so a multi-JSON-object failure exposes every diagnostic
            # code (gemini_json_missing_required_keys, gemini_json_recovery_failed,
            # etc.) through validation_issues -> issue_codes in the safe-fail
            # response, instead of only one truncated string.
            validation_issue_codes = [
                str(i.get("code")) for i in issues if isinstance(i, dict) and i.get("code")
            ]
            prompt_internal_codes = [
                str(code) for code in (prompt_input.get("internal_issue_codes") or []) if code
            ]
            return LiveSourceSmokeResult(
                ok=False,
                program_id=program_id,
                source_pack_path=str(pack_path.resolve()),
                html_path=str(html_path.resolve()),
                fetched_item_count=len(fetched),
                feed_urls_used=feed_urls,
                sample_marker_pass=False,
                placeholder_gate_pass=False,
                fetched_live_news=True,
                use_gemini=True,
                called_gemini=True,
                parse_status=parse_status,
                parse_meta=parse_meta,
                parse_diagnostics=_parse_failure_diagnostics(parse_result, prompt_input),
                generation_diagnostics=generation_diagnostics,
                generation_contract=generation_contract,
                validation_issues=validation_issue_codes,
                raw_response_path=raw_response_path,
                side_effects=side_effects,
                candidate_funnel_summary=(
                    prompt_input.get("candidate_funnel_summary")
                    if isinstance(prompt_input.get("candidate_funnel_summary"), dict)
                    else None
                ),
                hold_reason=prompt_input.get("hold_reason"),
                exposure_dedup_backfill_used=bool(
                    prompt_input.get("exposure_dedup_backfill_used")
                ),
                internal_issue_codes=prompt_internal_codes + [
                    code for code in parse_internal_codes if code not in prompt_internal_codes
                ],
                generation_attempt_count=int(
                    generation_diagnostics.get("generation_attempt_count") or 0
                ),
                generation_recovery_attempted=bool(
                    generation_diagnostics.get("generation_recovery_attempted")
                ),
                generation_recovery_family=generation_diagnostics.get(
                    "generation_recovery_family"
                ),
                generation_recovery_result=str(
                    generation_diagnostics.get("generation_recovery_result") or "not_needed"
                ),
                initial_generation_issue_codes=list(
                    generation_diagnostics.get("initial_generation_issue_codes") or []
                ),
                recovery_generation_issue_codes=list(
                    generation_diagnostics.get("recovery_generation_issue_codes") or []
                ),
                initial_input_tokens=_optional_diag_int(
                    generation_diagnostics, "initial_input_tokens"
                ),
                initial_output_tokens=_optional_diag_int(
                    generation_diagnostics, "initial_output_tokens"
                ),
                recovery_input_tokens=_optional_diag_int(
                    generation_diagnostics, "recovery_input_tokens"
                ),
                recovery_output_tokens=_optional_diag_int(
                    generation_diagnostics, "recovery_output_tokens"
                ),
                total_input_tokens=_optional_diag_int(
                    generation_diagnostics, "total_input_tokens"
                ),
                total_output_tokens=_optional_diag_int(
                    generation_diagnostics, "total_output_tokens"
                ),
                reconciled_top5=bool(
                    generation_diagnostics.get("reconciled_top5")
                ),
                replaced_source_ids=list(
                    generation_diagnostics.get("replaced_source_ids") or []
                ),
                replacement_source_ids=list(
                    generation_diagnostics.get("replacement_source_ids") or []
                ),
                error=f"Gemini parse failed ({parse_status}): {issue_text}",
            )

        generated_briefing = parse_result.get("generated_briefing")
        if isinstance(generated_briefing, dict):
            generated_briefing = enrich_generated_briefing_content(
                generated_briefing,
                program_id,
                prompt_input,
            )
            deep_block = (
                generated_briefing.get("deep_dive")
                if isinstance(generated_briefing, dict)
                else None
            )
            if isinstance(deep_block, dict):
                linked = deep_block.get("linked_signal_titles") or []
                if isinstance(linked, list) and linked:
                    source_pack = {
                        **source_pack,
                        "deep_dive_linked_signals": [str(x) for x in linked if str(x).strip()],
                    }
        generated_body = extract_generated_body_text(generated_briefing or {})
        preview_mode = "live_smoke_generated"
    else:
        preview_mode = "live_smoke"

    image_path: Optional[Path] = None
    image_source_mode: Optional[str] = None
    approved_asset_id: Optional[str] = None
    image_in_html = False
    contract_fixture: Optional[dict] = None

    if contract_preview:
        assert generated_briefing is not None
        try:
            explicit_override = top_shot_image_path is not None
            if explicit_override:
                candidate = Path(top_shot_image_path).expanduser().resolve()
                if not candidate.is_file():
                    raise FileNotFoundError(f"Top-shot image not found: {candidate}")
                image_path = candidate
            else:
                top_role = default_top_role_for_program(program_id)
                image_path = resolve_approved_hero_image_path(
                    repo,
                    program_id,
                    use_case="contract_preview",
                    role=top_role,
                )
            top_role = default_top_role_for_program(program_id)
            image_source_mode = classify_image_selection(
                repo,
                image_path,
                program_id,
                explicit_override=explicit_override,
                use_case="contract_preview",
                role=top_role,
            )
            registry_match = match_registry_asset(
                repo,
                image_path,
                program_id,
                use_case="contract_preview",
                role=top_role,
            )
            if registry_match is not None:
                approved_asset_id = registry_match.asset_id
                image_source_mode = "approved_registry"
        except (FileNotFoundError, ValueError) as exc:
            return LiveSourceSmokeResult(
                ok=False,
                program_id=program_id,
                source_pack_path=str(pack_path.resolve()),
                html_path=str(html_path.resolve()),
                fetched_item_count=len(fetched),
                feed_urls_used=feed_urls,
                sample_marker_pass=False,
                placeholder_gate_pass=False,
                fetched_live_news=True,
                use_gemini=True,
                called_gemini=side_effects["called_gemini"],
                parse_status=parse_status,
                raw_response_path=raw_response_path,
                contract_preview=True,
                side_effects=side_effects,
                error=str(exc),
            )

        html_path.parent.mkdir(parents=True, exist_ok=True)
        contract_fixture = build_contract_preview_fixture_from_generated(
            program_id=program_id,
            prompt_input=prompt_input,
            generated_briefing=generated_briefing,
            source_pack=source_pack,
            top_shot_image_path=image_path,
        )
        contract_fixture["fixture_mode"] = "live_generated"
        prepare_contract_preview_fixture(
            contract_fixture,
            repo_root=repo,
            image_mode=IMAGE_MODE_PREVIEW,
        )
        html = render_keysuri_contract_preview_html(
            contract_fixture,
            repo_root=repo,
            image_mode=IMAGE_MODE_PREVIEW,
            auto_prepare=False,
        )
        image_in_html = 'id="top-shot-image"' in html
        generated_body = extract_contract_visible_body_text(contract_fixture, generated_briefing)
    else:
        html = render_keysuri_owner_review_html(
            prompt_input,
            generated_briefing,
            preview_mode=preview_mode,  # type: ignore[arg-type]
        )

    html_path.write_text(html, encoding="utf-8")
    record_memory_stage("after_render")

    pack_text = pack_path.read_text(encoding="utf-8")
    marker_hits = scan_sample_markers(pack_text, html)
    marker_pass = len(marker_hits) == 0

    placeholder_hits: List[SampleMarkerHit] = []
    placeholder_pass = True
    if use_gemini and not contract_preview:
        placeholder_hits = scan_placeholder_markers(html)
        placeholder_pass = len(placeholder_hits) == 0

    validation_profile = "contract_preview" if contract_preview else "owner_review"
    validation = validate_keysuri_html_preview(str(html_path), profile=validation_profile)
    validation_pass = validation.is_pass()
    validation_issues = [f"{i.code}: {i.message}" for i in validation.issues]

    visible_quality_pass = True
    visible_quality_issues: List[str] = []
    preview_validation: Dict[str, Any] = {}
    structural_gate_status: Optional[str] = None
    content_briefing_gate_status: Optional[str] = None
    visual_identity_gate_status: Optional[str] = None
    preview_overall_status: Optional[str] = None
    ready_for_owner_visual_review = False
    ready_for_owner_manual_visual_inspection = False
    if contract_preview:
        manifest_path: Optional[str] = None
        if image_path is not None:
            ip = Path(image_path)
            sidecar = ip.with_suffix(".manifest.json")
            if sidecar.is_file() and sidecar.suffix == ".json":
                manifest_path = str(sidecar)
            elif ip.name.endswith("_mirai_on_watermarked.jpg"):
                alt = ip.parent / ip.name.replace(
                    "_mirai_on_watermarked.jpg",
                    "_mirai_on_watermarked.manifest.json",
                )
                if alt.is_file():
                    manifest_path = str(alt)
        preview_report = validate_keysuri_contract_preview(
            html,
            html_path=str(html_path),
            program_id=program_id,
            image_path=str(image_path) if image_path else None,
            image_manifest_path=manifest_path,
            repo_root=repo,
            image_source_mode=image_source_mode,  # type: ignore[arg-type]
            briefing_source_metadata=source_pack,
        )
        preview_validation = preview_report.to_dict()
        structural_gate_status = preview_report.structural_gate.status
        content_briefing_gate_status = preview_report.content_briefing_gate.status
        visual_identity_gate_status = preview_report.visual_identity_gate.status
        preview_overall_status = preview_report.overall_status
        ready_for_owner_visual_review = preview_report.ready_for_owner_visual_review
        ready_for_owner_manual_visual_inspection = preview_report.ready_for_owner_manual_visual_inspection
        visible_quality_pass = preview_report.overall_status != "blocked"
        visible_quality_issues = [
            f"{gate.gate}/{i.code}: {i.message}"
            for gate in (
                preview_report.structural_gate,
                preview_report.content_briefing_gate,
                preview_report.visual_identity_gate,
            )
            for i in gate.issues
        ]
        vbody = validate_contract_preview_visible_body(html)
        if not vbody.ok:
            visible_quality_pass = False
            visible_quality_issues.extend(f"{i.code}: {i.message}" for i in vbody.issues)

    ok = marker_pass and validation_pass and visible_quality_pass
    if use_gemini and not contract_preview:
        ok = ok and placeholder_pass

    result = LiveSourceSmokeResult(
        ok=ok,
        program_id=program_id,
        source_pack_path=str(pack_path.resolve()),
        html_path=str(html_path.resolve()),
        fetched_item_count=len(fetched),
        feed_urls_used=feed_urls,
        sample_marker_pass=marker_pass,
        sample_marker_hits=marker_hits,
        placeholder_gate_pass=placeholder_pass if use_gemini else True,
        placeholder_gate_hits=placeholder_hits,
        validation_status=validation.validation_status,
        validation_issues=validation_issues,
        fetched_live_news=True,
        use_gemini=use_gemini,
        called_gemini=side_effects["called_gemini"],
        parse_status=parse_status,
        parse_meta=parse_meta,
        generation_diagnostics=generation_diagnostics if use_gemini else {},
        generation_contract=(
            generation_contract
            if use_gemini
            else sanitize_generation_contract_record({})
        ),
        raw_response_path=raw_response_path,
        generated_body=generated_body,
        generated_briefing=generated_briefing if isinstance(generated_briefing, dict) else None,
        contract_preview=contract_preview,
        image_path=str(image_path.resolve()) if image_path else None,
        image_source_mode=image_source_mode,
        approved_asset_id=approved_asset_id,
        image_in_html=image_in_html,
        visible_body_quality_pass=visible_quality_pass,
        visible_body_quality_issues=visible_quality_issues,
        preview_validation=preview_validation,
        structural_gate_status=structural_gate_status,
        content_briefing_gate_status=content_briefing_gate_status,
        visual_identity_gate_status=visual_identity_gate_status,
        preview_overall_status=preview_overall_status,
        ready_for_owner_visual_review=ready_for_owner_visual_review,
        ready_for_owner_manual_visual_inspection=ready_for_owner_manual_visual_inspection,
        side_effects=side_effects,
        candidate_funnel_summary=(
            prompt_input.get("candidate_funnel_summary")
            if isinstance(prompt_input.get("candidate_funnel_summary"), dict)
            else None
        ),
        exposure_dedup_backfill_used=bool(prompt_input.get("exposure_dedup_backfill_used")),
        internal_issue_codes=[
            str(code) for code in (prompt_input.get("internal_issue_codes") or []) if code
        ]
        + [
            code
            for code in parse_internal_codes
            if code
            not in [str(c) for c in (prompt_input.get("internal_issue_codes") or [])]
        ],
        generation_attempt_count=int(
            generation_diagnostics.get("generation_attempt_count") or 0
        ),
        generation_recovery_attempted=bool(
            generation_diagnostics.get("generation_recovery_attempted")
        ),
        generation_recovery_family=generation_diagnostics.get(
            "generation_recovery_family"
        ),
        generation_recovery_result=str(
            generation_diagnostics.get("generation_recovery_result") or "not_needed"
        ),
        initial_generation_issue_codes=list(
            generation_diagnostics.get("initial_generation_issue_codes") or []
        ),
        recovery_generation_issue_codes=list(
            generation_diagnostics.get("recovery_generation_issue_codes") or []
        ),
        initial_input_tokens=_optional_diag_int(
            generation_diagnostics, "initial_input_tokens"
        ),
        initial_output_tokens=_optional_diag_int(
            generation_diagnostics, "initial_output_tokens"
        ),
        recovery_input_tokens=_optional_diag_int(
            generation_diagnostics, "recovery_input_tokens"
        ),
        recovery_output_tokens=_optional_diag_int(
            generation_diagnostics, "recovery_output_tokens"
        ),
        total_input_tokens=_optional_diag_int(
            generation_diagnostics, "total_input_tokens"
        ),
        total_output_tokens=_optional_diag_int(
            generation_diagnostics, "total_output_tokens"
        ),
        reconciled_top5=bool(generation_diagnostics.get("reconciled_top5")),
        replaced_source_ids=list(
            generation_diagnostics.get("replaced_source_ids") or []
        ),
        replacement_source_ids=list(
            generation_diagnostics.get("replacement_source_ids") or []
        ),
    )

    if not send:
        result.send_block_reason = "send_not_requested"
        return result

    if contract_preview:
        result.send_block_reason = "contract_preview_no_email_in_smoke"
        return result

    if send_confirm != _SEND_CONFIRM_PHRASE:
        result.send_block_reason = "confirm_send_missing"
        return result

    if not use_gemini:
        result.send_block_reason = "generated_briefing_required_for_send"
        return result

    if not marker_pass:
        result.send_block_reason = "sample_marker_gate_failed"
        return result

    if not placeholder_pass:
        result.send_block_reason = "placeholder_gate_failed"
        return result

    if not validation_pass:
        result.send_block_reason = "owner_review_validator_failed"
        return result

    to_list = [r.strip() for r in (recipients or []) if r.strip()]
    if not to_list:
        result.send_block_reason = "recipient_missing"
        return result

    harness = repo / "scripts" / "send_keysuri_owner_review_email_test.py"
    cmd = [
        sys.executable,
        str(harness),
        "--html",
        str(html_path),
        "--subject",
        subject,
        "--send",
        "--confirm",
        _SEND_CONFIRM_PHRASE,
    ]
    for addr in to_list:
        cmd.extend(["--to", addr])

    result.send_attempted = True
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    combined = stdout + stderr
    if "send_success" in combined:
        try:
            payload_start = combined.rfind("{")
            payload = json.loads(combined[payload_start:])
            result.send_success = bool(payload.get("send_success"))
            result.email_report_path = payload.get("report_path")
        except (json.JSONDecodeError, ValueError):
            result.send_success = proc.returncode == 0
    else:
        result.send_success = proc.returncode == 0

    result.email_subject = subject
    result.email_recipients = list(to_list)
    if result.send_success:
        side_effects["sent_email"] = True
    else:
        result.send_block_reason = result.send_block_reason or "smtp_send_failed"
        result.error = (stderr or stdout).strip()[:500] or "email harness failed"

    result.side_effects = side_effects
    result.ok = ok and result.send_success
    return result
