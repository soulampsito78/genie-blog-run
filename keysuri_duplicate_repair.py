"""Plan a minimum same-event replacement from a parent's preserved source pool.

No network, generation, persistence or authority changes. Callers retain normal
source, reissue, review, signature, recipient and publication gates.
"""
from __future__ import annotations

import copy

from keysuri_news_contract import (
    TOP5_QUALITY_FLOOR_BASE_SCORE, _claim_is_qualified, _claim_to_news_item,
)
from news_event_identity import event_identity
from sent_news_dedup_gate import recent_log_duplicate_reason


def plan_duplicate_repair(parent, *, sent_rows):
    pid = parent.get("program_id") or parent.get("mode")
    if pid != "keysuri_korea_tech":
        raise ValueError("targeted_duplicate_repair_korea_only")
    pack = copy.deepcopy(parent.get("regen_source_pack_snapshot"))
    prompt = copy.deepcopy(parent.get("regen_prompt_input_snapshot"))
    selected = copy.deepcopy(parent.get("selected_items"))
    if not isinstance(pack, dict) or not isinstance(prompt, dict) or not isinstance(selected, list) or len(selected) != 5:
        raise ValueError("targeted_duplicate_repair_missing_snapshot")
    sources = {s["source_id"]: s for s in pack.get("sources", []) + pack.get("backfill_sources", []) if isinstance(s, dict) and s.get("source_id")}
    claims = {c["claim_id"]: c for c in pack.get("claims", []) + pack.get("backfill_claims", []) if isinstance(c, dict) and c.get("claim_id")}
    kept, removed, events = [], [], {}
    for item in selected:
        claim = claims.get(item.get("news_id"))
        if not claim:
            raise ValueError("targeted_duplicate_repair_unbound_selection")
        hydrated = _claim_to_news_item(claim, item["rank"], sources, pid, pack.get("generated_at", ""))
        identity = event_identity(hydrated)
        if identity and identity in events:
            survivor = events[identity]
            survivor["source_ids"] = list(dict.fromkeys(survivor["source_ids"] + item["source_ids"]))
            survivor.setdefault("merged_event_news_ids", [survivor["news_id"]]).append(item["news_id"])
            removed.append(item["news_id"])
            continue
        if recent_log_duplicate_reason(hydrated, sent_rows):
            raise ValueError("targeted_duplicate_repair_customer_sent_parent")
        kept.append(item)
        if identity:
            events[identity] = item
    if not removed:
        raise ValueError("targeted_duplicate_repair_no_proven_duplicate")
    selected_ids = {item["news_id"] for item in selected}
    candidates = sorted(pack.get("backfill_claims", []), key=lambda c: -float(c.get("selection_score_before_diversity", c.get("selection_score", 0))))
    replacements = []
    for claim in candidates:
        if len(kept) == 5:
            break
        if claim.get("claim_id") in selected_ids:
            continue
        score = claim.get("selection_score_before_diversity", claim.get("selection_score"))
        if not isinstance(score, (int, float)) or score < TOP5_QUALITY_FLOOR_BASE_SCORE:
            continue
        if claim.get("korea_tech_scope_status") not in {"strong_tech", "weak_tech"}:
            continue
        qualified, _ = _claim_is_qualified(claim, sources, pid, pack.get("generated_at", ""))
        if not qualified or not claim.get("business_implication"):
            continue
        item = _claim_to_news_item(claim, len(kept) + 1, sources, pid, pack.get("generated_at", ""))
        if recent_log_duplicate_reason(item, sent_rows + kept):
            continue
        kept.append(item)
        replacements.append(item["news_id"])
    if len(kept) != 5:
        raise ValueError("targeted_duplicate_repair_qualified_pool_exhausted")
    selected_claims = []
    for rank, item in enumerate(kept, 1):
        item["rank"] = rank
        claim = copy.deepcopy(claims[item["news_id"]])
        claim["source_ids"] = list(item["source_ids"])
        selected_claims.append(claim)
    pack["sources"] = [sources[sid] for sid in dict.fromkeys(sid for item in kept for sid in item["source_ids"])]
    pack["claims"] = selected_claims
    if isinstance(pack.get("korea_top5_selection"), dict):
        pack["targeted_repair_original_selection"] = copy.deepcopy(pack["korea_top5_selection"])
    pack["korea_top5_selection"] = {
        "policy": "keysuri_korea_targeted_event_repair_v1",
        "selected_source_ids": [item["source_ids"][0] for item in kept],
        "same_event_removed_ids": list(removed),
        "replacement_news_ids": list(replacements),
    }
    prompt["source_pack"] = pack
    prompt["selected_items"] = copy.deepcopy(kept)
    prompt["top_5_news"]["items"] = copy.deepcopy(kept)
    prompt["selected_count"] = 5
    selection = prompt.get("top_5_selection_result")
    if isinstance(selection, dict):
        selection["top_5_news"] = copy.deepcopy(prompt["top_5_news"])
        selection["same_event_repair_removed_ids"] = list(removed)
        selection["same_event_repair_replacement_ids"] = list(replacements)
    # Working copy only. Persisted original evidence is never edited.
    working = copy.deepcopy(parent)
    working["selected_items"] = kept
    working["regen_prompt_input_snapshot"] = prompt
    working["regen_source_pack_snapshot"] = pack
    return working, {"reissue_source_contract": "targeted_parent_event_repair",
                     "reissue_source_recollected": False, "reissue_news_reselected": True,
                     "reissue_same_event_removed_ids": removed,
                     "reissue_targeted_replacement_ids": replacements}
