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

_SEND_CONFIRM_PHRASE = "SEND"
_DEFAULT_EMAIL_SUBJECT = "[KEYSURI test] Kee-Suri Global Tech live owner-review smoke"


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


def _default_output_paths(program_id: str, out_dir: Path) -> Tuple[Path, Path]:
    stamp = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d_%H%M%S")
    slug = "global" if program_id == PROGRAM_GLOBAL else "korea"
    pack = out_dir / f"keysuri_{slug}_live_source_smoke_{stamp}.json"
    html = out_dir / f"keysuri_{slug}_live_source_smoke_owner_review_{stamp}.html"
    return pack, html


def _feeds_for_program(program_id: str) -> Tuple[Dict[str, str], ...]:
    if program_id == PROGRAM_GLOBAL:
        return GLOBAL_TECH_SMOKE_FEEDS
    raise ValueError(f"No live smoke feed list configured for {program_id!r}")


def run_keysuri_live_source_smoke(
    *,
    program_id: str = PROGRAM_GLOBAL,
    max_items: int = 5,
    allow_network: bool = True,
    use_gemini: bool = False,
    send: bool = False,
    send_confirm: Optional[str] = None,
    recipients: Optional[Sequence[str]] = None,
    html_out: Optional[Path] = None,
    source_pack_out: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    repo_root: Optional[Path] = None,
    email_subject: str = _DEFAULT_EMAIL_SUBJECT,
) -> LiveSourceSmokeResult:
    repo = repo_root or Path(__file__).resolve().parent
    preview_dir = out_dir or (repo / "output" / "keysuri_preview")
    preview_dir.mkdir(parents=True, exist_ok=True)

    pack_path, html_path = _default_output_paths(program_id, preview_dir)
    if source_pack_out is not None:
        pack_path = source_pack_out
    if html_out is not None:
        html_path = html_out

    side_effects = {
        "called_gemini": False,
        "fetched_live_news": False,
        "sent_email": False,
        "published_naver": False,
        "changed_scheduler": False,
        "called_image_api": False,
        "mutated_admin_runs": False,
    }

    if use_gemini:
        return LiveSourceSmokeResult(
            ok=False,
            program_id=program_id,
            source_pack_path=str(pack_path),
            html_path=str(html_path),
            fetched_item_count=0,
            feed_urls_used=[],
            sample_marker_pass=False,
            called_gemini=False,
            fetched_live_news=False,
            side_effects=side_effects,
            error="use_gemini is not wired for Kee-Suri live source smoke yet",
        )

    if not allow_network:
        return LiveSourceSmokeResult(
            ok=False,
            program_id=program_id,
            source_pack_path=str(pack_path),
            html_path=str(html_path),
            fetched_item_count=0,
            feed_urls_used=[],
            sample_marker_pass=False,
            fetched_live_news=False,
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
            fetched_live_news=len(fetched) > 0,
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
            fetched_live_news=True,
            side_effects=side_effects,
            error=f"prompt_status={prompt_input.get('prompt_status')!r} after live source pack",
        )

    html = render_keysuri_owner_review_html(prompt_input, preview_mode="live_smoke")
    html_path.write_text(html, encoding="utf-8")

    pack_text = pack_path.read_text(encoding="utf-8")
    marker_hits = scan_sample_markers(pack_text, html)
    marker_pass = len(marker_hits) == 0

    validation = validate_keysuri_html_preview(str(html_path), profile="owner_review")
    validation_pass = validation.is_pass()
    validation_issues = [f"{i.code}: {i.message}" for i in validation.issues]

    ok = marker_pass and validation_pass
    result = LiveSourceSmokeResult(
        ok=ok,
        program_id=program_id,
        source_pack_path=str(pack_path.resolve()),
        html_path=str(html_path.resolve()),
        fetched_item_count=len(fetched),
        feed_urls_used=feed_urls,
        sample_marker_pass=marker_pass,
        sample_marker_hits=marker_hits,
        validation_status=validation.validation_status,
        validation_issues=validation_issues,
        fetched_live_news=True,
        side_effects=side_effects,
    )

    if not send:
        result.send_block_reason = "send_not_requested"
        return result

    if send_confirm != _SEND_CONFIRM_PHRASE:
        result.send_block_reason = "confirm_send_missing"
        return result

    if not marker_pass:
        result.send_block_reason = "sample_marker_gate_failed"
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
        email_subject,
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

    result.email_subject = email_subject
    result.email_recipients = list(to_list)
    if result.send_success:
        side_effects["sent_email"] = True
    else:
        result.send_block_reason = result.send_block_reason or "smtp_send_failed"
        result.error = (stderr or stdout).strip()[:500] or "email harness failed"

    result.side_effects = side_effects
    result.ok = ok and result.send_success
    return result
