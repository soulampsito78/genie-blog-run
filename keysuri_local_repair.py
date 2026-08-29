"""Repair one field of one article without touching the other four cards.

Whole-contract regeneration is the right response to a malformed or unparseable
generation: nothing usable came back. It is the wrong response to a local
editorial defect — one card's ``why_now`` reading like boilerplate — because it
throws away four cards that were fine and re-rolls the dice on all of them.
That is how a single weak field turns into five freshly-generated ones.

This module makes a local defect a local repair. Each request carries one
article's identity, its own canonical evidence, its own narrative plan, the
field that failed and why. Several requests may be batched into one model call
for efficiency, but the response contract stays independently keyed by
``news_id`` + ``field``, and the applier is the enforcement point: it writes
only authorized pairs and cannot touch article identity, source attribution, a
neighbouring card, or a field that already passed.

Whole-contract correction remains available and unchanged for true structural
failure.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from keysuri_narrative_plan import ArticleNarrativePlan, build_narrative_plans

#: Editorial fields a local repair may rewrite.
REPAIRABLE_FIELDS: Tuple[str, ...] = (
    "what_happened",
    "why_now",
    "owner_angle",
    "next_watch",
    "selection_reason",
)

#: Factual identity. Never repairable, never model-editable.
IMMUTABLE_FIELDS: Tuple[str, ...] = (
    "news_id",
    "rank",
    "headline",
    "korean_title",
    "source_ids",
    "source_name",
    "source_url",
)

LOCAL_REPAIR_APPLIED = "keysuri_local_field_repair_applied"
LOCAL_REPAIR_REJECTED = "keysuri_local_field_repair_rejected"
LOCAL_REPAIR_FAILED = "keysuri_local_field_repair_failed"


@dataclass(frozen=True)
class FieldRepairRequest:
    """One authorized (article, field) repair, with only that article's context."""

    rank: int
    news_id: str
    field: str
    issue_code: str
    current_value: str
    evidence: Mapping[str, Any]
    plan: ArticleNarrativePlan

    @property
    def key(self) -> Tuple[str, str]:
        return (self.news_id, self.field)

    def as_prompt_dict(self) -> Dict[str, Any]:
        """What the model sees. Its own article, and nothing about the others."""
        return {
            "news_id": self.news_id,
            "rank": self.rank,
            "field": self.field,
            "issue_code": self.issue_code,
            "current_value": self.current_value,
            "canonical_evidence": {
                "headline": str(self.evidence.get("headline") or ""),
                "summary": str(self.evidence.get("summary") or ""),
                "source_name": str(self.evidence.get("source_name") or ""),
            },
            "narrative_plan": self.plan.as_prompt_dict(),
        }


def _text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value)
    return str(value or "").strip()


def build_local_repair_requests(
    items: Sequence[Mapping[str, Any]],
    evidence_items: Sequence[Mapping[str, Any]],
    findings: Sequence[Mapping[str, Any]],
) -> List[FieldRepairRequest]:
    """Turn per-field findings into bounded, same-article repair requests.

    A finding that names no repairable field, or an article with no evidence,
    yields no request: there is nothing to repair it *from*, and inventing a
    basis is what this whole contract exists to prevent.
    """
    evidence_by_id = {
        str(e.get("news_id") or ""): e
        for e in evidence_items or ()
        if isinstance(e, Mapping) and e.get("news_id")
    }
    plans = {p.article_identity: p for p in build_narrative_plans(list(evidence_items or ()))}
    items_by_id = {
        str(i.get("news_id") or ""): i
        for i in items or ()
        if isinstance(i, Mapping) and i.get("news_id")
    }

    requests: List[FieldRepairRequest] = []
    seen: set = set()
    for finding in findings or ():
        if not isinstance(finding, Mapping):
            continue
        news_id = str(finding.get("news_id") or "").strip()
        field = str(finding.get("field") or "").strip()
        if field not in REPAIRABLE_FIELDS:
            continue
        item = items_by_id.get(news_id)
        evidence = evidence_by_id.get(news_id)
        plan = plans.get(news_id)
        if item is None or evidence is None or plan is None:
            continue
        if (news_id, field) in seen:
            continue
        seen.add((news_id, field))
        requests.append(
            FieldRepairRequest(
                rank=int(item.get("rank") or 0),
                news_id=news_id,
                field=field,
                issue_code=str(finding.get("issue_code") or ""),
                current_value=_text(item.get(field)),
                evidence=evidence,
                plan=plan,
            )
        )
    return requests


def build_local_repair_prompt(requests: Sequence[FieldRepairRequest]) -> str:
    """One batched call, five separate articles.

    Batching is an efficiency choice, not a licence to blend: the payload keeps
    each article's evidence and plan under its own ``news_id``, and the response
    must come back keyed the same way.
    """
    from keysuri_editorial_policy import policy_block

    payload = [r.as_prompt_dict() for r in requests]
    return "\n".join(
        [
            "=== BOUNDED LOCAL FIELD REPAIR ===",
            policy_block(),
            "",
            "Rewrite ONLY the fields listed below. This is not a regeneration.",
            "",
            "Rules:",
            "- Return exactly one JSON object: "
            '{"repairs": [{"news_id": ..., "field": ..., "value": ...}]}',
            "- Emit one entry per requested (news_id, field). Emit nothing else.",
            "- Write each field from THAT article's canonical_evidence and "
            "narrative_plan only. Never use another article's evidence or wording.",
            "- Do not restate the headline in place of analysis.",
            "- A narrative_plan field marked UNAVAILABLE has no supporting evidence: "
            "say so plainly or write less. Never invent a fact, number, date or quote.",
            "- Do not change identity, source, URL or any field not listed.",
            "- Two repaired fields must not share a sentence shape.",
            "",
            "REPAIR_REQUESTS",
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            "END — output the single JSON object only.",
        ]
    )


def parse_local_repair_response(raw: Any) -> Dict[Tuple[str, str], str]:
    """Model response reduced to ``{(news_id, field): value}``. Never raises."""
    out: Dict[Tuple[str, str], str] = {}
    payload: Any = raw
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return out
    if not isinstance(payload, Mapping):
        return out
    repairs = payload.get("repairs")
    if not isinstance(repairs, (list, tuple)):
        return out
    for entry in repairs:
        if not isinstance(entry, Mapping):
            continue
        news_id = str(entry.get("news_id") or "").strip()
        field = str(entry.get("field") or "").strip()
        value = _text(entry.get("value"))
        if news_id and field and value:
            out[(news_id, field)] = value
    return out


def apply_local_repairs(
    briefing: Any,
    repairs: Mapping[Tuple[str, str], str],
    authorized: Sequence[FieldRepairRequest],
) -> Tuple[Any, Dict[str, Any]]:
    """Write only authorized (news_id, field) pairs. Everything else is preserved.

    This is the enforcement point, not the prompt. A model that returns a value
    for an unrequested field, another card, or an identity field has that entry
    dropped and recorded — the briefing it was given back is otherwise the one
    it started with.
    """
    diagnostics: Dict[str, Any] = {
        "local_repair_attempted": bool(authorized),
        "local_repair_applied": [],
        "local_repair_rejected": [],
        "local_repair_missing": [],
        "local_repair_issue_codes": [],
    }
    if not isinstance(briefing, dict) or not authorized:
        return briefing, diagnostics

    top = briefing.get("top_5_news")
    items = top.get("items") if isinstance(top, dict) else None
    if not isinstance(items, list):
        return briefing, diagnostics

    allowed = {r.key for r in authorized}
    for key in repairs:
        if key not in allowed:
            diagnostics["local_repair_rejected"].append(
                {"news_id": key[0], "field": key[1], "reason": "not_authorized"}
            )

    applied: List[Dict[str, str]] = []
    new_items: List[Any] = []
    for item in items:
        if not isinstance(item, dict):
            new_items.append(item)
            continue
        news_id = str(item.get("news_id") or "").strip()
        updated = dict(item)
        for field in REPAIRABLE_FIELDS:
            key = (news_id, field)
            if key not in allowed:
                continue
            value = repairs.get(key)
            if not value:
                diagnostics["local_repair_missing"].append(
                    {"news_id": news_id, "field": field}
                )
                continue
            updated[field] = value
            applied.append({"news_id": news_id, "field": field})
        # Identity is re-asserted from the original item, so a repair can never
        # move a card's news_id, rank, headline, source or URL.
        for field in IMMUTABLE_FIELDS:
            if field in item:
                updated[field] = item[field]
            else:
                updated.pop(field, None)
        new_items.append(updated)

    out = dict(briefing)
    out_top = dict(top)
    out_top["items"] = new_items
    out["top_5_news"] = out_top

    diagnostics["local_repair_applied"] = applied
    codes: List[str] = []
    if applied:
        codes.append(LOCAL_REPAIR_APPLIED)
    if diagnostics["local_repair_rejected"]:
        codes.append(LOCAL_REPAIR_REJECTED)
    if diagnostics["local_repair_missing"]:
        codes.append(LOCAL_REPAIR_FAILED)
    diagnostics["local_repair_issue_codes"] = codes
    return out, diagnostics


def is_whole_contract_failure(issue_codes: Sequence[str]) -> bool:
    """Whether the failure is structural rather than editorial.

    Only a generation that came back unusable earns a whole-contract retry. A
    local editorial defect must not consume it.
    """
    structural = {
        "parse_multiple_json_objects_unrecoverable",
        "gemini_multiple_json_objects_no_valid_schema",
        "gemini_json_recovery_failed",
        "gemini_json_missing_required_keys",
        "top_5_news_missing",
        "deep_dive_missing",
        "one_line_checkpoint_missing",
        "closing_sources_missing",
        "global_contract_scaffold_fabricated_top5",
    }
    return any(str(code) in structural for code in issue_codes or ())
