"""Synthetic provenance for copy-only positive tests, not historical facts.

Call only for an explicitly migrated positive fixture with absent provenance.
Never repair a negative fixture, infer real article URLs, or change reader copy.
"""
from __future__ import annotations
import copy
from typing import Any, Dict, Tuple


def bind_synthetic_today_sources(payload: Dict[str, Any], *, fixture: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    out = copy.deepcopy(payload)
    items = out.get("key_watchpoints") or out.get("top_3_news") or []
    sources = []
    for index, item in enumerate(items, 1):
        if any(item.get(key) for key in ("source_url", "source_name", "source_published_at")):
            raise ValueError("Positive fixture already has provenance; do not overwrite it")
        news_id = item.get("news_id") or f"synthetic-{fixture}-{index}"
        url = f"https://fixture.example.test/{fixture}/article-{index}"
        published = "2026-10-07T00:00:00+00:00"
        source = "Synthetic fixture publisher"
        item.update(news_id=news_id, source_kind="selected_news", source_url=url,
                    source_name=source, source_published_at=published, source_date="2026-10-07",
                    source_publication_status="INPUT_VALUE_UNVERIFIED",
                    source_provenance_status="INPUT_URL_BOUND_NOT_FACT_PASS",
                    source_provenance_issue="")
        sources.append({"news_id":news_id,"headline":item["headline"],"url":url,
                        "source":source,"published_at":published,"date":"2026-10-07"})
    return out, {"top_market_news":sources,
                 "fixture_note":"D10 synthetic source binding for copy-only expectations; not actual historical provenance"}
