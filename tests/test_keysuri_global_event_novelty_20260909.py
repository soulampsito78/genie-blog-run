"""Global event-novelty regression — incident GLOBAL_EVENT_NOVELTY_RECOVERY_20260909.

Incident: the 2026-09-09 12:30 KST Global briefing
(run 20260909_123001_keysuri_global_tech_8915e2dd) led with an AWS Weekly
Roundup published 2026-09-07, presenting "Claude Fable 5.1 출시" as that day's
launch. The roundup's own text said the availability happened "Last week"
(the primary AWS announcement is dated 2026-09-01).

Every gate passed it because every gate read a *document* timestamp:
the source gate reads ``fetched_at`` (when we collected the page) and
``_score_recency`` reads ``published_at`` (when the page was published).
Neither is the time of the news development being asserted.

Evidence provenance
-------------------
``AWS_ROUNDUP_*`` is REAL evidence, copied verbatim from the frozen incident
artifact's ``regen_source_pack_snapshot`` (title, snippet, published_at,
fetched_at, tier). Everything else in this module is SYNTHETIC, written to
probe the rule's boundaries, and is marked as such.

The evaluation clock is frozen so these results never drift with wall time.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from keysuri_global_signal_scoring import (
    score_candidates_from_source_pack,
    score_global_signal_item,
)
from keysuri_news_contract import (
    classify_global_event_novelty,
    is_global_tech_low_signal_headline,
    select_top_5_news,
)
from keysuri_source_gate import GateResult, validate_source_pack

KST = timezone(timedelta(hours=9))

# Frozen evaluation clock: the incident run's own start.
INCIDENT_NOW = datetime(2026, 9, 9, 12, 30, 7, tzinfo=KST)

# --- REAL incident evidence (verbatim from the frozen run artifact) ---------
AWS_ROUNDUP_TITLE = (
    "AWS Weekly Roundup: Claude Fable 5.1 on AWS, Amazon Linux 2027 preview, "
    "AWS Certified AI Business Strategist, and more (September 7, 2026)"
)
AWS_ROUNDUP_SNIPPET = (
    "Last week, Claude Fable 5.1 became available on AWS. According to "
    "Anthropic, Claude Fable 5.1 delivers frontier intelligence for ambitious "
    "tasks across coding, scientific research, and enterprise workflows. "
    "Claude Fable 5.1 is built for long-running, high-stakes work that runs "
    "for hours and spans ma"
)
AWS_ROUNDUP_URL = (
    "https://aws.amazon.com/blogs/aws/aws-weekly-roundup-claude-fable-5-1-on-aws"
    "-amazon-linux-2027-preview-aws-certified-ai-business-strategist-and-more"
    "-september-7-2026/"
)
AWS_ROUNDUP_PUBLISHED_AT = "2026-09-07T23:24:08+09:00"
AWS_ROUNDUP_FETCHED_AT = "2026-09-09T12:30:06+09:00"


def _source(sid, title, snippet, published_at, url, *, fetched_at=None, tier="T1_OFFICIAL_SECONDARY"):
    return {
        "source_id": sid,
        "source_name": "Test Source",
        "source_url": url,
        "source_tier": tier,
        "feed_id": "test-feed",
        "fetched_at": fetched_at or AWS_ROUNDUP_FETCHED_AT,
        "published_at": published_at,
        "title": title,
        "publisher": "Test Source",
        "snippet": snippet,
    }


def _claim(sid, title, snippet):
    return {
        "claim_id": f"claim-{sid}",
        "statement": title,
        "claim_type": "general",
        "source_ids": [sid],
        "confidence_label": "reported",
        "category": "ai_software_platform",
        "headline": title[:160],
        "summary": snippet,
        "why_it_matters": "test",
        "business_implication": "test",
    }


class TestA_RecapOfEarlierAvailability(unittest.TestCase):
    """A. Sep 1 availability repeated in a Sep 7 roundup, evaluated Sep 9."""

    def test_roundup_is_not_a_new_availability_event(self):
        verdict = classify_global_event_novelty(
            AWS_ROUNDUP_TITLE,
            AWS_ROUNDUP_SNIPPET,
            published_at=AWS_ROUNDUP_PUBLISHED_AT,
        )
        self.assertTrue(verdict.is_roundup)
        self.assertEqual(verdict.backward_reference, "last week")
        self.assertFalse(verdict.eligible_as_new_development)
        self.assertEqual(
            verdict.reason, "global_recap_backward_referenced_event"
        )

    def test_event_date_is_bounded_by_its_own_document_not_invented(self):
        verdict = classify_global_event_novelty(
            AWS_ROUNDUP_TITLE,
            AWS_ROUNDUP_SNIPPET,
            published_at=AWS_ROUNDUP_PUBLISHED_AT,
        )
        self.assertEqual(verdict.event_date_basis, "backward_relative_unresolved")
        # The only bound the evidence supports: the event predates its own
        # document. "last week" must NOT be converted into an exact date --
        # the real event (2026-09-01) is not 7 days before 2026-09-07.
        self.assertEqual(verdict.event_not_later_than, AWS_ROUNDUP_PUBLISHED_AT)
        self.assertNotIn("2026-08-31", verdict.event_not_later_than)

    def test_scoring_layer_hard_rejects_the_roundup(self):
        scored = score_global_signal_item(
            {
                "source_id": "live-aws-news-blog-5503c00c09",
                "title": AWS_ROUNDUP_TITLE,
                "link": AWS_ROUNDUP_URL,
                "published_at": AWS_ROUNDUP_PUBLISHED_AT,
                "fetched_at": AWS_ROUNDUP_FETCHED_AT,
                "source_name": "AWS News Blog",
                "source_tier": "T1_OFFICIAL_SECONDARY",
                "summary": AWS_ROUNDUP_SNIPPET,
            },
            now=INCIDENT_NOW,
        )
        self.assertEqual(scored.classification, "hard_reject")
        self.assertEqual(
            scored.hard_reject_reason, "global_recap_backward_referenced_event"
        )

    def test_famous_brand_and_launch_words_do_not_rescue_it(self):
        """"출시"/launch/available/AWS/Anthropic must not by themselves qualify."""
        verdict = classify_global_event_novelty(
            AWS_ROUNDUP_TITLE,
            AWS_ROUNDUP_SNIPPET + " launch release 출시 공개 available",
            published_at=AWS_ROUNDUP_PUBLISHED_AT,
        )
        self.assertFalse(verdict.eligible_as_new_development)


class TestB_RefetchAndRepublishDoNotResetFreshness(unittest.TestCase):
    """B. Same event fetched again or republished at a new URL."""

    def test_refetching_later_does_not_make_the_event_new(self):
        later_fetch = classify_global_event_novelty(
            AWS_ROUNDUP_TITLE,
            AWS_ROUNDUP_SNIPPET,
            published_at=AWS_ROUNDUP_PUBLISHED_AT,
        )
        self.assertFalse(later_fetch.eligible_as_new_development)

    def test_fetched_at_is_never_used_as_a_publication_date(self):
        """A candidate with only fetched_at must not read as freshly published."""
        scored = score_global_signal_item(
            {
                "source_id": "no-pub-date",
                # SYNTHETIC: a feed row that carries no publication date.
                "title": "Vendor ships new inference runtime",
                "link": "https://example.com/no-date",
                "fetched_at": AWS_ROUNDUP_FETCHED_AT,
                "source_name": "Test Source",
                "source_tier": "T1_OFFICIAL_SECONDARY",
                "summary": "A product launch with no publication date in the feed.",
            },
            now=INCIDENT_NOW,
        )
        self.assertEqual(scored.published_at, "")
        self.assertEqual(scored.fetched_at, AWS_ROUNDUP_FETCHED_AT)
        self.assertEqual(scored.hard_reject_reason, "no_date")
        self.assertEqual(scored.scores.recency, 0)

    def test_new_url_for_the_same_recap_still_rejected(self):
        verdict = classify_global_event_novelty(
            AWS_ROUNDUP_TITLE,
            AWS_ROUNDUP_SNIPPET,
            # SYNTHETIC: republished a day later at a different URL.
            published_at="2026-09-08T09:00:00+09:00",
        )
        self.assertFalse(verdict.eligible_as_new_development)


class TestC_UpdatedPageNoMaterialChange(unittest.TestCase):
    """C. Updated old page with no material event change. SYNTHETIC."""

    def test_updated_timestamp_alone_does_not_promote(self):
        verdict = classify_global_event_novelty(
            "Weekly roundup: what shipped",
            "Last month we announced general availability. This page was "
            "updated for clarity.",
            published_at="2026-09-08T09:00:00+09:00",
        )
        self.assertFalse(verdict.eligible_as_new_development)
        self.assertEqual(verdict.event_date_basis, "backward_relative_unresolved")


class TestD_GenuineNewDevelopmentStaysEligible(unittest.TestCase):
    """D. Same model, evidenced new price/region/policy development. SYNTHETIC."""

    def test_price_change_on_a_previously_launched_model_is_eligible(self):
        verdict = classify_global_event_novelty(
            "Anthropic cuts Claude Fable 5.1 pricing on Bedrock",
            "Anthropic today announced a 30% price reduction for Claude Fable "
            "5.1 on Amazon Bedrock, effective immediately.",
            published_at="2026-09-09T02:00:00+09:00",
        )
        self.assertTrue(verdict.eligible_as_new_development)
        self.assertEqual(verdict.event_date_basis, "document_published")

    def test_regional_rollout_is_a_distinct_development(self):
        verdict = classify_global_event_novelty(
            "Claude Fable 5.1 expands to AWS Europe regions",
            "AWS announced Claude Fable 5.1 is now available in Frankfurt and "
            "Stockholm regions.",
            published_at="2026-09-09T02:00:00+09:00",
        )
        self.assertTrue(verdict.eligible_as_new_development)

    def test_ordinary_article_mentioning_an_earlier_launch_stays_eligible(self):
        """A current story is not rejected for referencing past context."""
        verdict = classify_global_event_novelty(
            "Enterprises rethink model choice after benchmark results",
            "The model previously announced in March is now being re-evaluated. "
            "A new independent benchmark released today shows different results.",
            published_at="2026-09-09T02:00:00+09:00",
        )
        self.assertTrue(verdict.eligible_as_new_development)
        self.assertFalse(verdict.is_roundup)


class TestE_RoundupWithBothOldAndNew(unittest.TestCase):
    """E. Roundup carrying an old development and a genuinely new one. SYNTHETIC."""

    def test_roundup_with_its_own_new_development_is_not_blanket_blocked(self):
        verdict = classify_global_event_novelty(
            "AWS Weekly Roundup: model availability, new region, and more",
            "Last week, a partner model became available on AWS. Today AWS is "
            "announcing a new Osaka region for Bedrock with revised pricing.",
            published_at="2026-09-07T23:24:08+09:00",
        )
        self.assertTrue(verdict.is_roundup)
        self.assertTrue(verdict.has_independent_development)
        self.assertTrue(verdict.eligible_as_new_development)

    def test_roundup_whose_only_development_is_backward_is_blocked(self):
        verdict = classify_global_event_novelty(
            "AWS Weekly Roundup: model availability and more",
            "Last week, a partner model became available on AWS. It delivers "
            "frontier intelligence for ambitious tasks.",
            published_at="2026-09-07T23:24:08+09:00",
        )
        self.assertTrue(verdict.is_roundup)
        self.assertFalse(verdict.has_independent_development)
        self.assertFalse(verdict.eligible_as_new_development)


class TestF_UnknownAndRelativeDates(unittest.TestCase):
    """F. Unknown / conflicting / relative dates. SYNTHETIC."""

    def test_missing_publication_date_is_explicit_not_today(self):
        verdict = classify_global_event_novelty(
            "Vendor announces new accelerator",
            "The company announced a new accelerator.",
            published_at="",
        )
        self.assertEqual(verdict.event_date_basis, "unknown")
        self.assertEqual(verdict.event_not_later_than, "")

    def test_unparseable_publication_date_is_explicit(self):
        verdict = classify_global_event_novelty(
            "Vendor announces new accelerator",
            "The company announced a new accelerator.",
            published_at="not-a-date",
        )
        self.assertEqual(verdict.event_date_basis, "unknown")
        self.assertEqual(verdict.event_not_later_than, "")

    def test_relative_date_without_publication_context_is_not_resolved(self):
        verdict = classify_global_event_novelty(
            "Weekly roundup of platform changes",
            "Last week the service became available.",
            published_at="",
        )
        self.assertEqual(verdict.event_date_basis, "unknown")
        self.assertEqual(verdict.event_not_later_than, "")
        self.assertFalse(verdict.eligible_as_new_development)

    def test_relative_date_resolves_against_document_not_wall_clock(self):
        verdict = classify_global_event_novelty(
            AWS_ROUNDUP_TITLE,
            AWS_ROUNDUP_SNIPPET,
            published_at=AWS_ROUNDUP_PUBLISHED_AT,
        )
        # Anchored to the document, never to fetch time or "now".
        self.assertEqual(verdict.event_not_later_than, AWS_ROUNDUP_PUBLISHED_AT)
        self.assertNotIn("2026-09-09", verdict.event_not_later_than)


class TestG_EveryAdmissionPathAgrees(unittest.TestCase):
    """G. Primary selection and every replacement/backfill path."""

    def _pack(self, claims, sources, *, backfill=None, backfill_sources=None):
        pack = {
            "program_id": "keysuri_global_tech",
            "generated_at": "2026-09-09T12:30:06+09:00",
            "sources": sources,
            "claims": claims,
        }
        if backfill is not None:
            pack["backfill_claims"] = backfill
            pack["backfill_sources"] = backfill_sources or []
        return pack

    def _fresh(self, n):
        srcs, claims = [], []
        for i in range(n):
            sid = f"fresh-{i}"
            title = f"Chipmaker {i} announces new datacenter accelerator"
            snippet = (
                f"Vendor {i} today announced a new accelerator for datacenter "
                "inference, with pricing and availability details."
            )
            srcs.append(
                _source(sid, title, snippet, "2026-09-09T01:00:00+09:00",
                        f"https://example{i}.com/a")
            )
            claims.append(_claim(sid, title, snippet))
        return srcs, claims

    def test_primary_path_rejects_the_roundup(self):
        srcs, claims = self._fresh(5)
        srcs.append(
            _source("aws-recap", AWS_ROUNDUP_TITLE, AWS_ROUNDUP_SNIPPET,
                    AWS_ROUNDUP_PUBLISHED_AT, AWS_ROUNDUP_URL)
        )
        claims.append(_claim("aws-recap", AWS_ROUNDUP_TITLE, AWS_ROUNDUP_SNIPPET))
        pack = self._pack(claims, srcs)
        gate = validate_source_pack(pack, now=INCIDENT_NOW)
        res = select_top_5_news(pack, gate, trigger_source="scheduled_service_full_run")
        self.assertEqual(res["verdict"], "pass")
        heads = [i["headline"] for i in res["top_5_news"]["items"]]
        self.assertFalse(any("Weekly Roundup" in h for h in heads))

    def test_fresh_backfill_path_rejects_the_roundup(self):
        srcs, claims = self._fresh(4)
        b_srcs = [
            _source("aws-recap", AWS_ROUNDUP_TITLE, AWS_ROUNDUP_SNIPPET,
                    AWS_ROUNDUP_PUBLISHED_AT, AWS_ROUNDUP_URL)
        ]
        b_claims = [_claim("aws-recap", AWS_ROUNDUP_TITLE, AWS_ROUNDUP_SNIPPET)]
        pack = self._pack(claims, srcs, backfill=b_claims, backfill_sources=b_srcs)
        gate = validate_source_pack(pack, now=INCIDENT_NOW)
        res = select_top_5_news(pack, gate, trigger_source="scheduled_service_full_run")
        heads = [i["headline"] for i in (res.get("top_5_news") or {}).get("items", [])]
        self.assertFalse(any("Weekly Roundup" in h for h in heads))

    def test_scoring_replacement_pool_also_rejects_the_roundup(self):
        srcs, claims = self._fresh(6)
        srcs.append(
            _source("aws-recap", AWS_ROUNDUP_TITLE, AWS_ROUNDUP_SNIPPET,
                    AWS_ROUNDUP_PUBLISHED_AT, AWS_ROUNDUP_URL)
        )
        claims.append(_claim("aws-recap", AWS_ROUNDUP_TITLE, AWS_ROUNDUP_SNIPPET))
        result = score_candidates_from_source_pack(
            self._pack(claims, srcs), now=INCIDENT_NOW
        )
        for bucket in (result.selected_top5, result.watchlist):
            self.assertFalse(
                any("Weekly Roundup" in c.title for c in bucket)
            )
        rejected = [
            c for c in result.rejected
            if c.hard_reject_reason == "global_recap_backward_referenced_event"
        ]
        self.assertTrue(rejected)


class TestH_ExistingPolicyPreserved(unittest.TestCase):
    """Quality floor, low-signal gate and Korea scope must be unchanged."""

    def test_existing_low_signal_gate_still_fires(self):
        flagged, reason = is_global_tech_low_signal_headline(
            "What is a transformer? Everything you need to know", ""
        )
        self.assertTrue(flagged)
        self.assertEqual(reason, "global_evergreen_explainer")

    def test_korea_program_is_untouched_by_the_global_rule(self):
        """The Korea program must not gain the Global event-novelty fields."""
        title = "지난주 공개된 국산 AI 반도체, 주간 정리"
        srcs = [
            _source("k1", title, "지난주 공개된 제품을 정리했습니다.",
                    "2026-09-08T09:00:00+09:00", "https://example.kr/a")
        ]
        claims = [_claim("k1", title, "지난주 공개된 제품을 정리했습니다.")]
        claims[0]["category"] = "ai_product"
        pack = {
            "program_id": "keysuri_korea_tech",
            "generated_at": "2026-09-09T18:30:00+09:00",
            "sources": srcs,
            "claims": claims,
        }
        gate = validate_source_pack(pack, now=datetime(2026, 9, 9, 18, 30, tzinfo=KST))
        res = select_top_5_news(pack, gate, trigger_source="scheduled_service_full_run")
        for item in (res.get("top_5_news") or {}).get("items", []):
            self.assertNotIn("event_novelty", item)


if __name__ == "__main__":
    unittest.main()
