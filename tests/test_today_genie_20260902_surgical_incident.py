"""Deterministic replay of the 2026-09-02 Today_Geenee incident evidence."""
from __future__ import annotations

import unittest

from main import stabilize_today_genie_market_narrative
from sent_news_dedup_gate import run_sent_news_dedup_gate
from today_genie_top3_assembly import (
    assemble_key_watchpoints_from_slots,
    ensure_canonical_news_identity,
    top3_identity_prompt_suffix,
)
from validators import (
    _today_market_fact_consistency_issues,
    _validate_top_three_news_briefing,
)


GOOD_NEWS = [
    "Trump announced a massive oil deal with Venezuela. Why it won't lower gas prices anytime soon",
    "Supreme Court lets Trump build White House ballroom as lawsuit continues",
    "House Intelligence Committee warns of 'Black Swan' AI risks",
]
FAILED_NEWS = [
    "U.S. strikes Iran as Tehran retaliates, raising risk of wider war",
    "U.S. House votes to avoid government shutdown amid GOP hard-liner resistance",
    "Palo Alto Networks beats quarterly estimates on AI demand, continues acquisition spree",
]


def _runtime(headlines=FAILED_NEWS):
    candidates = [{"date": "2026-09-01", "headline": h, "source": "CNBC"} for h in headlines]
    selected = run_sent_news_dedup_gate(
        briefing_type="today_genie", candidates=candidates,
        sent_log_last_5_days=[], required_count=3,
    )["selected_items"]
    indices = {
        "KOSPI": (6835.8, 0.23), "KOSDAQ": (821.25, -1.56),
        "NIKKEI": (66215.34, -0.15), "SPX": (7631.47, -0.71),
        "NASDAQ": (26099.774, -1.03), "DJI": (52766.88, -0.79),
    }
    slots = {
        key: {"close": close, "change_pct": pct, "market_date": "2026-09-01",
              "observation_status": "settled", "source_name": "persisted public probe"}
        for key, (close, pct) in indices.items()
    }
    return ensure_canonical_news_identity({
        "target_date": "2026-09-02", "input_feed_status": "full",
        "top_market_news": selected,
        "korea_japan_indices": {"indices": {k: slots[k] for k in ("KOSPI", "KOSDAQ", "NIKKEI")}},
        "overnight_us_market": {"indices": {k: slots[k] for k in ("SPX", "NASDAQ", "DJI")}},
        "macro_indicators": {"as_of": "2026-09-01", "headline": "확정 세션"},
        "risk_factors": [{"risk": "지정학", "detail": "중동 위험"}],
    })


def _slots(runtime):
    out = []
    for rank, item in enumerate(runtime["top_market_news"], 1):
        out.append({
            "slot": rank, "news_id": item["news_id"], "headline_ko": f"제{rank} 핵심 뉴스",
            "what_happened": f"선택된 제{rank} 뉴스의 사실관계가 야간 시장에서 확인됐습니다.",
            "why_it_matters_today": "오늘 장전에는 위험선호와 업종별 반응을 가르는 변수입니다.",
            "what_to_watch_in_korea": "국내에서는 코스피·코스닥과 원/달러, 외국인 수급을 확인합니다.",
        })
    return out


class TodayGenieSurgicalIncidentReplay(unittest.TestCase):
    def test_0901_good_and_0902_three_attempts_replay(self):
        for name, news in (("09-01", GOOD_NEWS), ("natural", FAILED_NEWS),
                           ("recovery-1", FAILED_NEWS), ("recovery-2", FAILED_NEWS)):
            with self.subTest(name=name):
                runtime = _runtime(news)
                watchpoints = assemble_key_watchpoints_from_slots(_slots(runtime), runtime)
                self.assertFalse(_validate_top_three_news_briefing(runtime, {"key_watchpoints": watchpoints}))

    def test_identity_survives_prompt_generation_and_validation(self):
        runtime = _runtime()
        ids = [item["news_id"] for item in runtime["top_market_news"]]
        suffix = top3_identity_prompt_suffix(runtime)
        self.assertTrue(all(news_id in suffix for news_id in ids))
        watchpoints = assemble_key_watchpoints_from_slots(list(reversed(_slots(runtime))), runtime)
        self.assertEqual([wp["news_id"] for wp in watchpoints], ids)
        self.assertFalse(_validate_top_three_news_briefing(runtime, {"key_watchpoints": watchpoints}))

    def test_invented_article_is_still_rejected(self):
        runtime = _runtime()
        watchpoints = assemble_key_watchpoints_from_slots(_slots(runtime), runtime)
        watchpoints[0]["news_id"] = "invented-article"
        codes = [i.code for i in _validate_top_three_news_briefing(runtime, {"key_watchpoints": watchpoints})]
        self.assertIn("top3_not_grounded_in_input_news", codes)

    def test_market_session_repair_and_validator_guard(self):
        runtime = _runtime()
        contradiction = "코스피와 코스닥이 모두 하락했습니다."
        self.assertTrue(_today_market_fact_consistency_issues({"market_setup": contradiction}, runtime))
        data = {"summary": contradiction, "market_setup": contradiction,
                "key_watchpoints": assemble_key_watchpoints_from_slots(_slots(runtime), runtime)}
        repaired = stabilize_today_genie_market_narrative(data, runtime)
        self.assertIn("2026-09-01", repaired["market_setup"])
        self.assertIn("코스피(+0.23%)", repaired["market_setup"])
        self.assertFalse(_today_market_fact_consistency_issues(repaired, runtime))

    def test_recovery_rejects_stale_grounding_snapshot(self):
        current, stale = _runtime(), _runtime(GOOD_NEWS)
        stale_slots = _slots(stale)
        stale_slots[0]["what_happened"] = "STALE_VENEZUELA_MARKER " * 4
        watchpoints = assemble_key_watchpoints_from_slots(stale_slots, current)
        self.assertNotIn("STALE_VENEZUELA_MARKER", str(watchpoints))
        self.assertEqual([w["news_id"] for w in watchpoints], [n["news_id"] for n in current["top_market_news"]])
        self.assertFalse(_validate_top_three_news_briefing(current, {"key_watchpoints": watchpoints}))


if __name__ == "__main__":
    unittest.main()
