"""Common 5-day sent-news deduplication gate for briefing selection."""
from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "ref",
    "spm",
}
TITLE_NOISE_TOKENS = {
    "breaking",
    "exclusive",
    "속보",
    "단독",
    "종합",
    "업데이트",
    "뉴스",
}
TITLE_SIMILARITY_THRESHOLD = 0.88


def canonicalize_url(url: Any) -> str:
    """Normalize URLs enough for operational duplicate checks."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()
    path = re.sub(r"/+", "/", parts.path or "").rstrip("/")
    kept = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        low = key.lower()
        if low in TRACKING_QUERY_KEYS or any(low.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        kept.append((key, value))
    query = urlencode(kept, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def normalize_title(title: Any) -> str:
    raw = str(title or "").lower()
    raw = re.sub(r"[\[\](){}<>【】「」『』]", " ", raw)
    raw = re.sub(r"[^\w\s가-힣]", " ", raw)
    words = [w for w in re.sub(r"\s+", " ", raw).strip().split(" ") if w]
    words = [w for w in words if w not in TITLE_NOISE_TOKENS]
    return " ".join(words)


def normalize_topic_key(topic_key: Any) -> str:
    raw = str(topic_key or "").lower()
    raw = re.sub(r"[^\w\s가-힣-]", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def _first_text(item: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _source_name(item: Dict[str, Any]) -> str:
    source = item.get("source")
    if isinstance(source, dict):
        return _first_text(source, "source_name", "name", "title", "id", "source_id")
    return _first_text(item, "source", "source_name", "publisher", "provider")


def _short_summary(item: Dict[str, Any]) -> str:
    return _first_text(item, "short_summary", "summary", "why_it_matters", "detail")[:500]


def _summary_hash(item: Dict[str, Any]) -> str:
    text = _short_summary(item)
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _explicit_topic_key(item: Dict[str, Any]) -> str:
    """Return only explicitly supplied story/topic identifiers.

    Broad grouping fields such as category, program_id, section, or feed type are
    intentionally excluded because they collapse unrelated TOP 5 items.
    """
    return _first_text(
        item,
        "topic_key",
        "canonical_topic_key",
        "news_topic_key",
        "story_key",
        "story_id",
        "cluster_key",
        "cluster_id",
    )


def normalize_candidate(item: Dict[str, Any]) -> Dict[str, Any]:
    title = _first_text(item, "title", "headline", "headline_ko", "statement")
    url = _first_text(item, "canonical_url", "url", "source_url", "link")
    source = _source_name(item)
    topic_key = _explicit_topic_key(item)
    normalized = dict(item)
    normalized.setdefault("title", title)
    normalized.setdefault("url", url)
    normalized.setdefault("source", source)
    normalized.setdefault("topic_key", topic_key)
    normalized["canonical_url"] = canonicalize_url(url)
    normalized["normalized_title"] = normalize_title(title)
    normalized["normalized_source"] = normalize_title(source)
    normalized["normalized_topic_key"] = normalize_topic_key(topic_key)
    normalized["summary_hash"] = str(item.get("summary_hash") or "") or _summary_hash(item)
    return normalized


def _title_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def _is_title_similar(left: str, right: str) -> bool:
    return _title_similarity(left, right) >= TITLE_SIMILARITY_THRESHOLD


def _dedup_indexes(items: Iterable[Dict[str, Any]]) -> Dict[str, set[str]]:
    out = {
        "canonical_urls": set(),
        "normalized_titles": set(),
        "source_titles": set(),
        "topic_keys": set(),
    }
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = normalize_candidate(raw)
        if item["canonical_url"]:
            out["canonical_urls"].add(item["canonical_url"])
        if item["normalized_title"]:
            out["normalized_titles"].add(item["normalized_title"])
        if item["normalized_source"] and item["normalized_title"]:
            out["source_titles"].add(f"{item['normalized_source']}|{item['normalized_title']}")
        if item["normalized_topic_key"]:
            out["topic_keys"].add(item["normalized_topic_key"])
    return out


def _duplicate_reason(
    candidate: Dict[str, Any],
    sent_log: List[Dict[str, Any]],
    selected: List[Dict[str, Any]],
) -> str:
    item = normalize_candidate(candidate)
    sent_idx = _dedup_indexes(sent_log)
    selected_idx = _dedup_indexes(selected)

    canonical_url = item["canonical_url"]
    title = item["normalized_title"]
    source = item["normalized_source"]
    topic_key = item["normalized_topic_key"]
    source_title = f"{source}|{title}" if source and title else ""

    if canonical_url and canonical_url in sent_idx["canonical_urls"]:
        return "recent_log_canonical_url_duplicate"
    if title and title in sent_idx["normalized_titles"]:
        return "recent_log_normalized_title_duplicate"
    if source_title and source_title in sent_idx["source_titles"]:
        return "recent_log_source_title_duplicate"
    if topic_key and topic_key in sent_idx["topic_keys"]:
        return "recent_log_topic_key_duplicate"
    if title:
        for raw in sent_log:
            other = normalize_candidate(raw)
            if source and source == other.get("normalized_source") and _is_title_similar(title, other.get("normalized_title", "")):
                return "recent_log_source_similar_title_duplicate"

    if canonical_url and canonical_url in selected_idx["canonical_urls"]:
        return "selected_canonical_url_duplicate"
    if title and title in selected_idx["normalized_titles"]:
        return "selected_normalized_title_duplicate"
    if source_title and source_title in selected_idx["source_titles"]:
        return "selected_source_title_duplicate"
    if topic_key and topic_key in selected_idx["topic_keys"]:
        return "selected_topic_key_duplicate"
    if title:
        for raw in selected:
            other = normalize_candidate(raw)
            if source and source == other.get("normalized_source") and _is_title_similar(title, other.get("normalized_title", "")):
                return "selected_source_similar_title_duplicate"
    return ""


def run_sent_news_dedup_gate(
    *,
    briefing_type: str,
    candidates: List[Dict[str, Any]],
    sent_log_last_5_days: List[Dict[str, Any]],
    required_count: int,
) -> Dict[str, Any]:
    selected: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    normalized_candidates = [
        normalize_candidate(item)
        for item in candidates
        if isinstance(item, dict)
    ]

    for item in normalized_candidates:
        reason = _duplicate_reason(item, sent_log_last_5_days, selected)
        if reason:
            rejected.append({**item, "rejected_reason": reason})
            continue
        if len(selected) < required_count:
            selected.append(item)
        else:
            rejected.append({**item, "rejected_reason": "beyond_required_count"})

    selected_count = len(selected)
    rejected_by_reason: Dict[str, int] = {}
    for item in rejected:
        reason = str(item.get("rejected_reason") or "unknown")
        rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1

    shortfall = max(0, required_count - selected_count)
    summary = {
        "briefing_type": briefing_type,
        "required_count": required_count,
        "candidate_count": len(normalized_candidates),
        "selected_count": selected_count,
        "rejected_count": len(rejected),
        "rejected_by_reason": rejected_by_reason,
        "filled_required_count": selected_count >= required_count,
        "shortfall": shortfall,
        "reason": "insufficient_fresh_candidates" if shortfall else "ok",
    }
    return {
        "selected_items": selected,
        "rejected_items": rejected,
        "dedup_summary": summary,
    }


def metadata_from_gate_result(result: Dict[str, Any], *, required_count: int) -> Dict[str, Any]:
    selected = result.get("selected_items") if isinstance(result.get("selected_items"), list) else []
    return {
        "used_dedup_gate": True,
        "selected_items": selected,
        "rejected_items": result.get("rejected_items") if isinstance(result.get("rejected_items"), list) else [],
        "dedup_summary": result.get("dedup_summary") if isinstance(result.get("dedup_summary"), dict) else {},
        "required_count": required_count,
        "selected_count": len(selected),
    }


# ---------------------------------------------------------------------------
# Intra-briefing diversity caps (same-source / same-entity / editorial cluster)
# ---------------------------------------------------------------------------
# Cross-day URL/title dedup above cannot stop two *different* headlines from the
# same outlet (e.g. two NVIDIA Blog posts) crowding one briefing. These caps run
# at TOP-N selection time so a capped duplicate is skipped and the next distinct
# candidate takes the slot.

# Major company entities recognized for the per-briefing entity cap. Keys are
# canonical labels; ASCII aliases match on word boundaries, Korean aliases match
# as substrings.
COMPANY_ENTITY_ALIASES: Dict[str, tuple] = {
    "nvidia": ("nvidia", "엔비디아"),
    "aws": ("aws", "amazon web services", "아마존 웹 서비스"),
    "amazon": ("amazon", "아마존"),
    "openai": ("openai", "오픈ai", "오픈에이아이"),
    "google": ("google", "alphabet", "구글"),
    "microsoft": ("microsoft", "마이크로소프트"),
    "meta": ("meta", "facebook", "메타", "페이스북"),
    "apple": ("apple", "애플"),
}

# Editorial cluster keywords (first match in order wins). Broad category fields
# are intentionally NOT used here — category misclassification is a known,
# separate defect — so the cluster key is derived from title/summary/source.
_EDITORIAL_CLUSTER_KEYWORDS: tuple = (
    ("ai_chip_design", ("chip design", "semiconductor design", "칩 설계", "반도체 설계")),
    ("ai_agents", ("ai agent", "agentic", "agent toolkit", "에이전트")),
    (
        "ai_infrastructure",
        (
            "infrastructure",
            "inference",
            "data center",
            "datacenter",
            "at scale",
            "gpu",
            "인프라",
            "추론",
        ),
    ),
    ("finance_app", ("finance app", "google finance", "stock app", "금융 앱", "증권 앱")),
    ("funding_round", ("raises $", "lands $", "series a", "series b", "투자 유치")),
)


def _entity_text(item: Dict[str, Any]) -> str:
    parts = [
        _first_text(item, "title", "headline", "headline_ko", "statement"),
        _short_summary(item),
        _source_name(item),
    ]
    return " ".join(p for p in parts if p).lower()


def extract_company_entities(item: Dict[str, Any]) -> List[str]:
    """Return canonical company-entity keys mentioned in the item (sorted)."""
    text = _entity_text(item)
    if not text:
        return []
    found: set[str] = set()
    for canon, aliases in COMPANY_ENTITY_ALIASES.items():
        for alias in aliases:
            if alias.isascii():
                if re.search(r"\b" + re.escape(alias) + r"\b", text):
                    found.add(canon)
                    break
            elif alias in text:
                found.add(canon)
                break
    return sorted(found)


def editorial_cluster_key(item: Dict[str, Any]) -> str:
    """Derive a coarse editorial cluster from title/summary/source text."""
    text = _entity_text(item)
    if not text:
        return ""
    for key, keywords in _EDITORIAL_CLUSTER_KEYWORDS:
        if any(kw in text for kw in keywords):
            return key
    return ""


def diversity_source_key(item: Dict[str, Any]) -> str:
    """Stable source identity for the same-source cap.

    Prefers the normalized source name, falling back to the source_id prefix
    (trailing hash stripped) and finally any source domain, so the cap still
    works when the source name was never hydrated onto the item.
    """
    norm = normalize_title(_source_name(item))
    if norm:
        return norm
    sids = item.get("source_ids")
    if isinstance(sids, list) and sids:
        sid = str(sids[0]).strip().lower()
        sid = re.sub(r"[-_][0-9a-f]{6,}$", "", sid)
        if sid:
            return sid
    return normalize_title(_first_text(item, "source_domain", "domain"))


def _diversity_identity(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "news_id": item.get("news_id") or item.get("claim_id") or "",
        "title": _first_text(item, "title", "headline"),
        "source": _source_name(item),
    }


def select_with_diversity_caps(
    candidates: List[Dict[str, Any]],
    *,
    required_count: int,
    same_source_max: int = 1,
    entity_max: int = 1,
) -> Dict[str, Any]:
    """Pick up to ``required_count`` items from priority-ordered candidates while
    capping repeated source / company-entity / source+cluster within one briefing.

    A capped duplicate is skipped so the next distinct candidate can take the
    slot (replacement, not silent pass-through). If the caps leave fewer than
    ``required_count`` items and capped candidates remain, those are added back
    in priority order and flagged ``diversity_relaxed`` while the summary records
    ``relaxed_due_to_candidate_shortage`` so the relaxation is auditable.
    """
    annotated: List[Dict[str, Any]] = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item["normalized_source"] = item.get("normalized_source") or normalize_title(_source_name(item))
        item["entity_keys"] = extract_company_entities(item)
        item["editorial_cluster_key"] = editorial_cluster_key(item)
        item["_diversity_source_key"] = diversity_source_key(item)
        annotated.append(item)

    selected: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []
    beyond: List[Dict[str, Any]] = []
    source_counts: Dict[str, int] = {}
    entity_counts: Dict[str, int] = {}
    cluster_owner: Dict[str, Dict[str, Any]] = {}
    same_source_reject = 0
    entity_reject = 0
    cluster_reject = 0

    for item in annotated:
        if len(selected) >= required_count:
            beyond.append(item)
            continue
        skey = item["_diversity_source_key"]
        ekeys = item["entity_keys"]
        ckey = item["editorial_cluster_key"]
        sc_key = f"{skey}|{ckey}" if skey and ckey else ""

        if skey and source_counts.get(skey, 0) >= same_source_max:
            same_source_reject += 1
            collided = next((s for s in selected if s["_diversity_source_key"] == skey), None)
            item["_diversity_reason"] = "same_source_cap"
            item["_diversity_collided_with"] = _diversity_identity(collided) if collided else None
            deferred.append(item)
            continue
        ent_hit = next((e for e in ekeys if entity_counts.get(e, 0) >= entity_max), None)
        if ent_hit:
            entity_reject += 1
            collided = next((s for s in selected if ent_hit in s.get("entity_keys", [])), None)
            item["_diversity_reason"] = "entity_cap"
            item["_diversity_collided_entity"] = ent_hit
            item["_diversity_collided_with"] = _diversity_identity(collided) if collided else None
            deferred.append(item)
            continue
        if sc_key and sc_key in cluster_owner:
            cluster_reject += 1
            item["_diversity_reason"] = "editorial_cluster_cap"
            item["_diversity_collided_cluster"] = ckey
            item["_diversity_collided_with"] = _diversity_identity(cluster_owner[sc_key])
            deferred.append(item)
            continue

        selected.append(item)
        if skey:
            source_counts[skey] = source_counts.get(skey, 0) + 1
        for e in ekeys:
            entity_counts[e] = entity_counts.get(e, 0) + 1
        if sc_key:
            cluster_owner[sc_key] = item

    relaxed = False
    for item in deferred:
        if len(selected) >= required_count:
            break
        relaxed = True
        item["diversity_relaxed"] = True
        item["diversity_relaxed_from"] = item.get("_diversity_reason")
        item["_diversity_promoted"] = True
        selected.append(item)

    rejected: List[Dict[str, Any]] = []
    for item in deferred:
        if item.get("_diversity_promoted"):
            continue
        rejected.append(
            {
                "news_id": item.get("news_id") or item.get("claim_id") or "",
                "title": _first_text(item, "title", "headline"),
                "source": _source_name(item),
                "rejected_reason": item.get("_diversity_reason") or "diversity_cap",
                "collided_with": item.get("_diversity_collided_with"),
                "collided_entity": item.get("_diversity_collided_entity"),
                "collided_cluster": item.get("_diversity_collided_cluster"),
            }
        )
    for item in beyond:
        rejected.append(
            {
                "news_id": item.get("news_id") or item.get("claim_id") or "",
                "title": _first_text(item, "title", "headline"),
                "source": _source_name(item),
                "rejected_reason": "beyond_required_count",
            }
        )

    clean_selected: List[Dict[str, Any]] = []
    for rank, item in enumerate(selected, start=1):
        out = {k: v for k, v in item.items() if not k.startswith("_diversity")}
        out["rank"] = rank
        clean_selected.append(out)

    shortfall = max(0, required_count - len(clean_selected))
    summary = {
        "candidate_count": len(annotated),
        "qualified_count": len(annotated),
        "selected_count": len(clean_selected),
        "rejected_count": len(rejected),
        "required_count": required_count,
        "selected_after_diversity_gate": True,
        "same_source_reject_count": same_source_reject,
        "entity_reject_count": entity_reject,
        "cluster_reject_count": cluster_reject,
        "shortfall": shortfall,
        "relaxed_due_to_candidate_shortage": relaxed,
    }
    return {
        "selected_items": clean_selected,
        "rejected_items": rejected,
        "diversity_summary": summary,
    }
