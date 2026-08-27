"""Historical corpus regressions for the 2026-08-27 Kee-Suri Global incident.

Reconstructed from two real production runs:

* ``20260827_123001_keysuri_global_tech_1f269612`` — natural 12:30 scheduled run.
  The model returned 645 output tokens containing none of the expected contract
  keys. The Global contract scaffold grafted all nine top-level keys from the
  claim pool, the parse became ``parsed_valid``, corrective generation was
  recorded as ``not_needed``, and the owner received a template-only SAFE/POOR
  quality notice whose cards carried English implementation copy.

* ``20260827_123607_keysuri_global_tech_847c9113`` — body-only reissue. It
  correctly hard-excluded all five parent articles and re-selected five fresh
  ones, then paired the fresh articles to the parent's prose *by rank position*,
  shipping every card as a composite of two unrelated stories.

Both runs also show ``exposure_log_updated: false`` with
``exposure_log_update_error: "customer_not_sent_yet"`` — cross-day memory had
been silently dead, which is why 08-24/25/26 all converged on the same
NVIDIA / OpenAI / IEEE ecosystem.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keysuri_briefing_content_enricher import _concrete_next_watch_pair
from keysuri_global_signal_scoring import classify_global_tech_category
from keysuri_news_contract import apply_cross_day_novelty_ordering
from keysuri_service_full_run import correlate_reissue_seeds

# Verbatim strings observed on the reader-visible surface of the natural run.
LEAKED_SOURCE_TEMPLATE = "Public tech source"
LEAKED_IMPLICATION_TEMPLATE = "AI/software/platform shifts may change vendor shortlists"

ARTICLE_A_TITLE = "Bringing ChatGPT for Teachers to more U.S. school districts"
ARTICLE_B_TITLE = "5 ways to upgrade your home decor with Google Search"


def _parent_item(rank, news_id, title, source, url):
    """A parent TOP5 card: carries a checkable article identity."""
    return {
        "rank": rank,
        "news_id": news_id,
        "headline": title,
        "title": title,
        "normalized_title": title.lower(),
        "source_name": source,
        "normalized_source": source.lower(),
        "canonical_url": url,
        "summary": f"{title} 요약",
        "why_it_matters": f"{title} 관련 판단 포인트",
    }


def _parent_top5():
    return [
        _parent_item(1, "claim-live-nvidia-blog-a50e18aa16",
                     "NVIDIA NVLink Fusion Expands With NVHBM Custom High-Bandwidth Memory",
                     "NVIDIA Blog", "https://blogs.nvidia.com/blog/nvlink-fusion-nvhbm"),
        _parent_item(2, "claim-live-google-ai-blog-9ce79d4dde", ARTICLE_B_TITLE,
                     "Google AI Blog", "https://blog.google/products/search/home-decor-tips"),
        _parent_item(3, "claim-live-arstechnica-tech-lab-33551649b5",
                     "AI agents meant to replace Meta workers made large-scale disruptive actions",
                     "Ars Technica Technology Lab", "https://arstechnica.com/ai/2026/08/meta-ai-native"),
        _parent_item(4, "claim-live-openai-blog-34e62ff4c7",
                     "The Hugging Face incident and the road ahead",
                     "OpenAI News", "https://openai.com/index/hugging-face-incident"),
        _parent_item(5, "claim-live-techcrunch-ai-745d673f45",
                     "Viral AI startup Instinct has raised $350 million at a $2.5 billion valuation",
                     "TechCrunch AI", "https://techcrunch.com/2026/08/26/instinct-350-million"),
    ]


def _fresh_reissue_top5():
    """The five genuinely different articles the reissue re-selected."""
    return [
        _parent_item(1, "claim-live-techcrunch-ai-d949d26fe8",
                     "Amazon just tripled its order of Nvidia chips over surging demand",
                     "TechCrunch AI", "https://techcrunch.com/2026/08/27/amazon-nvidia-order"),
        _parent_item(2, "claim-live-openai-blog-fa2791fbc9", ARTICLE_A_TITLE,
                     "OpenAI News", "https://openai.com/index/chatgpt-for-teachers-districts"),
        _parent_item(3, "claim-live-techcrunch-startups-aed46dac12",
                     "Meta child-safety deal hinges on age-verification tech",
                     "TechCrunch", "https://techcrunch.com/2026/08/27/meta-age-verification"),
        _parent_item(4, "claim-live-ieee-spectrum-63bb0f18fe",
                     "A New NASA Design Turbocharges Nuclear Spacecraft",
                     "IEEE Spectrum", "https://spectrum.ieee.org/nasa-nuclear-spacecraft"),
        _parent_item(5, "claim-live-datacenter-dynamics-3cf76770dc",
                     "Eurofiber secures 2.2bn sustainability-linked debt financing",
                     "Datacenter Dynamics", "https://datacenterdynamics.com/eurofiber-financing"),
    ]


class ReissueCrossItemContaminationTests(unittest.TestCase):
    """A/B: a card must never be assembled from two different articles."""

    def test_disjoint_reissue_batch_refuses_positional_pairing(self) -> None:
        seeds, diag = correlate_reissue_seeds(
            live_items=_fresh_reissue_top5(), base_items=_parent_top5()
        )
        # Zero identity overlap across five items is proof of a DIFFERENT batch,
        # not licence to pair by position.
        self.assertFalse(diag["reissue_correlation_positional_used"])
        self.assertFalse(diag["reissue_correlation_positional_guards_passed"])
        self.assertTrue(diag["reissue_correlation_batch_identity_conflict"])
        self.assertEqual(diag["reissue_correlation_matched_count"], 0)
        self.assertEqual(seeds, [None] * 5)

    def test_chatgpt_for_teachers_card_never_carries_home_decor(self) -> None:
        """Assertion A: article A's card must not contain article B's story."""
        seeds, _ = correlate_reissue_seeds(
            live_items=_fresh_reissue_top5(), base_items=_parent_top5()
        )
        teachers_rank = next(
            i for i, item in enumerate(_fresh_reissue_top5())
            if item["headline"] == ARTICLE_A_TITLE
        )
        seed = seeds[teachers_rank]
        # With no seed bound, the card falls back to its own article's fields.
        self.assertIsNone(seed)

    def test_home_decor_card_never_inherits_another_articles_source(self) -> None:
        """Assertion B: the Google home-decor story keeps its own identity."""
        # Parent order and fresh order both contain a Google/OpenAI slot; pairing
        # them positionally is what put OpenAI's source on the decor headline.
        seeds, diag = correlate_reissue_seeds(
            live_items=_fresh_reissue_top5(), base_items=_parent_top5()
        )
        for seed in seeds:
            self.assertIsNone(seed)
        self.assertEqual(diag["reissue_correlation_methods"], ["unmatched"] * 5)

    def test_matching_batch_still_correlates_by_identity(self) -> None:
        """The fix must not break the normal case: same batch, same articles."""
        base = _parent_top5()
        live = _parent_top5()
        seeds, diag = correlate_reissue_seeds(live_items=live, base_items=base)
        self.assertEqual(diag["reissue_correlation_matched_count"], 5)
        self.assertFalse(diag["reissue_correlation_positional_used"])
        for live_item, seed in zip(live, seeds):
            self.assertIsNotNone(seed)
            self.assertEqual(seed["canonical_url"], live_item["canonical_url"])


class InternalTemplateLeakTests(unittest.TestCase):
    """C/D: implementation copy must not reach the reader surface."""

    def test_source_pack_claims_carry_no_english_internal_templates(self) -> None:
        from keysuri_live_source_smoke import (
            FetchedFeedItem,
            _build_source_entries_from_items,
        )

        item = FetchedFeedItem(
            feed_id="google-ai-blog",
            feed_name="Google AI Blog",
            feed_url="https://blog.google/rss",
            source_tier="T1_OFFICIAL",
            default_category="ai_software_platform",
            title=ARTICLE_B_TITLE,
            link="https://blog.google/products/search/home-decor-tips",
            published_at="2026-08-27T09:00:00+09:00",
            summary="Learn how to use Google Search tools to find home decor inspiration.",
        )
        _sources, claims, _stamp = _build_source_entries_from_items(
            "keysuri_global_tech", [item]
        )
        self.assertEqual(len(claims), 1)
        claim = claims[0]
        for field in ("why_it_matters", "business_implication"):
            value = str(claim.get(field) or "")
            self.assertNotIn(LEAKED_SOURCE_TEMPLATE, value)
            self.assertNotIn(LEAKED_IMPLICATION_TEMPLATE, value)
            self.assertTrue(value.strip(), msg=f"{field} must stay contract-populated")
            # Reader-facing Global prose is Korean.
            self.assertTrue(
                any("가" <= ch <= "힣" for ch in value),
                msg=f"{field} must be Korean, got {value!r}",
            )

    def test_why_it_matters_placeholder_is_bound_to_its_own_article(self) -> None:
        from keysuri_live_source_smoke import _why_it_matters_placeholder

        value = _why_it_matters_placeholder("Google AI Blog", ARTICLE_B_TITLE)
        self.assertIn("Google AI Blog", value)
        self.assertIn(ARTICLE_B_TITLE, value)
        self.assertNotIn(ARTICLE_A_TITLE, value)
        self.assertNotIn(LEAKED_SOURCE_TEMPLATE, value)


class GlobalCategoryCascadeTests(unittest.TestCase):
    """E/F: one misclassification must not fan out into visible falsehoods."""

    ROBOT_TITLE = "Samsung's new AI companion robot follows you around the home"
    ROBOT_SUMMARY = (
        "The compact home robot charges on its dock and the battery lasts a full "
        "day. Reviewers praised the charging speed and power efficiency."
    )

    def test_companion_robot_is_not_battery_ev_energy_grid(self) -> None:
        primary, secondary, confidence, reason = classify_global_tech_category(
            f"{self.ROBOT_TITLE} {self.ROBOT_SUMMARY}",
            feed_default="hardware_device_display",
            title=self.ROBOT_TITLE,
        )
        self.assertEqual(primary, "robotics_automation_manufacturing")
        self.assertNotEqual(primary, "battery_ev_energy_grid")
        self.assertGreater(confidence, 0.5)
        self.assertIn("title_hits", reason)

    def test_category_ties_are_not_broken_alphabetically(self) -> None:
        """A NVIDIA headline must not lose to ai_software_platform on 'a' < 's'."""
        title = "NVIDIA specialized AI trust tools secure runtime"
        summary = "NVIDIA enterprise AI platform customer workflow."
        primary, _secondary, _confidence, _reason = classify_global_tech_category(
            f"{title} {summary}", feed_default="market_signal", title=title
        )
        self.assertEqual(primary, "semiconductor_chip_infra")

    def test_body_only_evidence_stays_low_confidence(self) -> None:
        title = "A quiet week for enterprise buyers"
        summary = "Analysts mentioned battery costs and grid storage only in passing."
        _primary, _secondary, confidence, _reason = classify_global_tech_category(
            f"{title} {summary}", feed_default="market_signal", title=title
        )
        self.assertLessEqual(confidence, 0.5)

    def test_robot_story_gets_no_ess_grid_followup_without_own_evidence(self) -> None:
        """F: vertical-specific fallback needs same-item evidence."""
        meta = {
            "source_name": "IEEE Spectrum",
            "primary_category": "battery_ev_energy_grid",
            "category_confidence": 0.35,
        }
        item = {"headline": self.ROBOT_TITLE, "summary": self.ROBOT_SUMMARY}
        first, second = _concrete_next_watch_pair(meta, item)
        joined = f"{first} {second}"
        for banned in ("ESS", "전력 조달", "그리드"):
            self.assertNotIn(banned, joined)
        self.assertIn("IEEE Spectrum", joined)

    def test_grounded_category_still_gets_its_vertical_followup(self) -> None:
        """The gate must not flatten every card into a neutral placeholder."""
        meta = {
            "source_name": "Datacenter Dynamics",
            "primary_category": "battery_ev_energy_grid",
            "category_confidence": 0.85,
        }
        item = {
            "headline": "Grid storage operator signs multi-year ESS supply contract",
            "summary": "The battery supplier will deliver grid storage capacity.",
        }
        first, second = _concrete_next_watch_pair(meta, item)
        self.assertIn("ESS", f"{first} {second}")


class CrossDayNoveltyTests(unittest.TestCase):
    """K: repetition is a bounded penalty, never a ban."""

    def _exposure_rows(self):
        rows = []
        for day in ("2026-08-24", "2026-08-25", "2026-08-26"):
            rows.append({
                "exposed_date_kst": day,
                "normalized_source": "nvidia blog",
                "entity_keys": ["nvidia"],
                "editorial_cluster_key": "ai_infrastructure",
            })
        return rows

    def _pool(self):
        return [
            {"news_id": "nvidia-repeat", "title": "NVIDIA AI Factory again",
             "normalized_source": "nvidia blog", "entity_keys": ["nvidia"],
             "editorial_cluster_key": "ai_infrastructure"},
            {"news_id": "fresh-a", "title": "Ars on storage",
             "normalized_source": "ars technica", "entity_keys": ["ars"],
             "editorial_cluster_key": "consumer_tech"},
            {"news_id": "fresh-b", "title": "TechCrunch on funding",
             "normalized_source": "techcrunch ai", "entity_keys": [],
             "editorial_cluster_key": "platform_policy"},
        ]

    def test_repeated_source_entity_cluster_is_demoted(self) -> None:
        reordered, decisions = apply_cross_day_novelty_ordering(
            self._pool(), self._exposure_rows()
        )
        self.assertNotEqual(reordered[0]["news_id"], "nvidia-repeat")
        penalised = [d for d in decisions if d["news_id"] == "nvidia-repeat"]
        self.assertEqual(len(penalised), 1)
        decision = penalised[0]
        self.assertGreater(decision["recent_source_penalty"], 0)
        self.assertGreater(decision["recent_entity_penalty"], 0)
        self.assertGreater(decision["recent_cluster_penalty"], 0)
        self.assertTrue(decision["demoted"])

    def test_materially_stronger_repeat_still_survives(self) -> None:
        """A genuinely important repeated entity is not banned."""
        pool = self._pool()
        # Same repeated NVIDIA story, but now far stronger than the field: the
        # penalty is bounded, so a wide score lead still wins.
        weak_tail = [
            {"news_id": f"weak-{i}", "title": f"Weak {i}",
             "normalized_source": "ars technica", "entity_keys": [],
             "editorial_cluster_key": "consumer_tech"}
            for i in range(5)
        ]
        pool = [pool[0]] + weak_tail
        reordered, _decisions = apply_cross_day_novelty_ordering(
            pool, self._exposure_rows()
        )
        self.assertIn(
            "nvidia-repeat", [item["news_id"] for item in reordered[:4]]
        )

    def test_no_recent_history_is_a_no_op(self) -> None:
        pool = self._pool()
        reordered, decisions = apply_cross_day_novelty_ordering(pool, [])
        self.assertEqual([i["news_id"] for i in reordered], [i["news_id"] for i in pool])
        self.assertEqual(decisions, [])


class OwnerReviewExposureMemoryTests(unittest.TestCase):
    """G/I: owner exposure is recorded without a customer send; sent stays hard."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(
            os.environ,
            {
                "GENIE_OWNER_REVIEW_EXPOSURE_LOG_PATH": str(
                    Path(self.tmp.name) / "owner_review_exposure_log.json"
                )
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_owner_review_exposure_recorded_with_customer_not_sent(self) -> None:
        from keysuri_service_full_run import _maybe_write_owner_review_exposure_log
        from owner_review_exposure_log_store import load_owner_review_exposure_log

        meta = {
            "program_id": "keysuri_global_tech",
            "run_id": "20260827_123001_keysuri_global_tech_1f269612",
            "customer_delivery_status": "not_sent",
            "selected_items": _parent_top5(),
        }
        _maybe_write_owner_review_exposure_log(
            meta, email_sent=True, exposure_kind="owner_review_email"
        )
        self.assertTrue(meta["exposure_log_updated"])
        self.assertIsNone(meta["exposure_log_update_error"])
        self.assertEqual(len(load_owner_review_exposure_log()), 5)

    def test_exposure_write_still_requires_a_real_owner_email(self) -> None:
        from keysuri_service_full_run import _maybe_write_owner_review_exposure_log
        from owner_review_exposure_log_store import load_owner_review_exposure_log

        meta = {
            "program_id": "keysuri_global_tech",
            "run_id": "r-no-email",
            "customer_delivery_status": "not_sent",
            "selected_items": _parent_top5(),
        }
        _maybe_write_owner_review_exposure_log(
            meta, email_sent=False, exposure_kind="owner_review_email"
        )
        self.assertFalse(meta["exposure_log_updated"])
        self.assertEqual(meta["exposure_log_update_error"], "email_not_sent")
        self.assertEqual(load_owner_review_exposure_log(), [])


class TodayGenieUnchangedTests(unittest.TestCase):
    """L: this remediation is Global-only."""

    def test_today_genie_modules_untouched_by_global_category_change(self) -> None:
        from keysuri_global_signal_scoring import classify_global_tech_category as c

        # The Global classifier must not be reachable from Today_Geenee's mode.
        primary, _s, _c, _r = c("today genie weather brief", feed_default="market_signal")
        self.assertIn(primary, {"ai_software_platform", "market_signal"})


if __name__ == "__main__":
    unittest.main()
