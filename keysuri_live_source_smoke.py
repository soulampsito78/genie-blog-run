"""Kee-Suri live public RSS source-pack smoke (minimal — not production automation)."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from keysuri_approved_image_assets import (
    classify_image_selection,
    default_top_role_for_program,
    match_registry_asset,
    resolve_approved_hero_image_path,
)
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
    build_keysuri_generation_prompt,
    extract_json_object_from_model_text,
    parse_keysuri_generated_response,
)
from keysuri_gemini_client import KeysuriGeminiError, call_keysuri_gemini_text
from keysuri_html_preview_validation import validate_keysuri_html_preview
from keysuri_prompt_input import build_keysuri_prompt_input
from keysuri_renderer import render_keysuri_owner_review_html

PROGRAM_GLOBAL = "keysuri_global_tech"
PROGRAM_KOREA = "keysuri_korea_tech"
SUPPORTED_PROGRAMS = (PROGRAM_GLOBAL, PROGRAM_KOREA)

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
    raw_response_path: Optional[str] = None
    generated_body: Dict[str, str] = field(default_factory=dict)
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
            "raw_response_path": self.raw_response_path,
            "generated_body": self.generated_body,
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
        }


def _now_kst_iso() -> str:
    return datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", cleaned).strip()


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
        title = _first_text(entry, ("title",))
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


def _infer_category(title: str, default_category: str) -> str:
    lower = title.lower()
    if any(token in lower for token in ("chip", "semiconductor", "hbm", "nvidia", "gpu")):
        return "semiconductor"
    if any(token in lower for token in ("policy", "regulation", "law", "government")):
        return "policy"
    if any(token in lower for token in ("startup", "seed", "series", "funding")):
        return "startup"
    if any(token in lower for token in ("security", "breach", "vulnerability")):
        return "security"
    if any(token in lower for token in ("platform", "app store", "developer")):
        return "platform"
    return default_category


def _business_implication(category: str) -> str:
    mapping = {
        "ai_product": "Enterprise AI product shifts may change vendor shortlists and procurement timing.",
        "bigtech": "Big-tech platform moves can reshape partner ecosystems and capex expectations.",
        "semiconductor": "Semiconductor supply signals may affect hardware roadmaps and vendor concentration.",
        "platform": "Platform policy changes can alter developer economics and distribution leverage.",
        "policy": "Policy movement may introduce compliance cost or market-access uncertainty.",
        "startup": "Startup funding and product launches can signal emerging competitive pressure.",
        "security": "Security incidents can trigger enterprise risk reviews and budget reallocation.",
        "market_signal": "Market-facing tech signals may influence near-term strategic watchpoints.",
    }
    return mapping.get(category, "Live public source metadata may affect near-term tech watch priorities.")


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

    stamp = generated_at or _now_kst_iso()
    sources: List[dict] = []
    claims: List[dict] = []
    seen_links: set[str] = set()

    for item in items:
        if item.link in seen_links:
            continue
        item_hits = scan_sample_markers(item.link, item.title, item.summary, item.feed_name)
        if item_hits:
            raise ValueError(
                f"Fixture-like live item rejected ({item_hits[0].marker!r}) for link {item.link!r}"
            )
        seen_links.add(item.link)
        sid = _source_id_for_link(item.feed_id, item.link)
        category = _infer_category(item.title, item.default_category)
        summary = item.summary[:500] if item.summary else item.title[:500]
        sources.append(
            {
                "source_id": sid,
                "source_name": item.feed_name,
                "source_url": item.link,
                "source_tier": item.source_tier,
                "fetched_at": stamp,
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
                "why_it_matters": f"Public tech source ({item.feed_name}) published: {item.title[:120]}",
                "business_implication": _business_implication(category),
            }
        )
        if len(sources) >= 5:
            break

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
    if program_id == PROGRAM_GLOBAL:
        return GLOBAL_TECH_SMOKE_FEEDS
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
    out_dir: Optional[Path] = None,
    repo_root: Optional[Path] = None,
    email_subject: Optional[str] = None,
    gemini_caller=None,
    top_shot_image_path: Optional[Path] = None,
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

    if not allow_network:
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

    feeds = _feeds_for_program(program_id)
    feed_urls = [f["feed_url"] for f in feeds]
    fetched: List[FetchedFeedItem] = []
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
    source_pack = build_live_source_pack(program_id, fetched)
    pack_path.write_text(json.dumps(source_pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    prompt_input = build_keysuri_prompt_input(program_id, source_pack)
    if prompt_input.get("prompt_status") != "ready_for_generation":
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
            error=f"prompt_status={prompt_input.get('prompt_status')!r} after live source pack",
        )

    generated_briefing = None
    parse_status: Optional[str] = None
    raw_response_path: Optional[str] = None
    generated_body: Dict[str, str] = {}

    if use_gemini:
        prompt_text = build_keysuri_generation_prompt(prompt_input)
        caller = gemini_caller or call_keysuri_gemini_text
        try:
            raw_text = caller(prompt_text, project_id=project_id, model=model)
            side_effects["called_gemini"] = True
        except KeysuriGeminiError as exc:
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
                error=str(exc),
            )

        stamp = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d_%H%M%S")
        raw_path = preview_dir / f"keysuri_live_gemini_raw_response_{stamp}.txt"
        raw_path.write_text(raw_text, encoding="utf-8")
        raw_response_path = str(raw_path.resolve())

        parse_result = parse_keysuri_generated_response(raw_text, program_id, prompt_input)
        if parse_result.get("parse_status") != "parsed_valid":
            try:
                parsed_obj = extract_json_object_from_model_text(raw_text)
                parsed_obj = normalize_generated_briefing_schema_aliases(parsed_obj, prompt_input)
                parse_result = parse_keysuri_generated_response(
                    json.dumps(parsed_obj, ensure_ascii=False),
                    program_id,
                    prompt_input,
                )
            except ValueError:
                pass
        parse_status = str(parse_result.get("parse_status") or "")
        if parse_status != "parsed_valid":
            issues = parse_result.get("issues") or []
            issue_text = "; ".join(
                f"{i.get('code')}: {i.get('message')}" for i in issues[:5] if isinstance(i, dict)
            )
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
                raw_response_path=raw_response_path,
                side_effects=side_effects,
                error=f"Gemini parse failed ({parse_status}): {issue_text}",
            )

        generated_briefing = parse_result.get("generated_briefing")
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
        raw_response_path=raw_response_path,
        generated_body=generated_body,
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
