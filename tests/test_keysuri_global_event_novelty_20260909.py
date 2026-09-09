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
        self.assertTrue(verdict.presentable_as_new_development)
        self.assertEqual(verdict.event_date_basis, "document_published_proxy")

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


# ===========================================================================
# Owner acceptance round 2 — GLOBAL_EVENT_NOVELTY_RECOVERY_20260909
#
# The first fix caught the recap case but left a hole: with no backward
# wording, classify_global_event_novelty asserted has_independent_development
# =True and eligible=True unconditionally. Absence of backward wording is not
# positive evidence of a new development.
#
# Consequence in production (run 20260909_171733_keysuri_global_tech_b607aee3,
# customer-sent to 12 recipients at 17:35:22 KST): two NVIDIA documents
# published Sept 3-4 led a Sept 9 briefing as that day's news.
#
# REAL evidence below is copied from that run's frozen artifact.
# ===========================================================================

from keysuri_news_contract import GLOBAL_CURRENT_DEVELOPMENT_WINDOW_HOURS

# --- REAL: the Sept 9 correction run's own clock and two aged documents ----
B607_AS_OF = "2026-09-09T17:17:39+09:00"
NVIDIA_IFA_TITLE = "Sparks Fly: NVIDIA Accelerates Local AI at IFA 2026"
NVIDIA_IFA_PUBLISHED_AT = "2026-09-04T01:00:59+09:00"
NVIDIA_HF_TITLE = "NVIDIA to Acquire Hugging Face"
NVIDIA_HF_PUBLISHED_AT = "2026-09-03T20:56:49+09:00"

# --- REAL: canonical URLs of both runs' final selections -------------------
ORIGINAL_URLS = {
    "https://aws.amazon.com/blogs/aws/aws-weekly-roundup-claude-fable-5-1-on-aws-amazon-linux-2027-preview-aws-certified-ai-business-strategist-and-more-september-7-2026",
    "https://techcrunch.com/2026/09/08/meta-debuts-its-muse-ai-agent-will-consumers-trust-it",
    "https://openai.com/index/teen-development-research-grants",
    "https://www.microsoft.com/en-us/microsoft-cloud/blog/us-government/2026/09/08/codename-mdash-brings-agentic-ai-security-scanning-to-us-government",
    "https://techcrunch.com/2026/09/08/google-cloud-races-to-catch-up-in-the-ai-deployment-wars-with-accenture-deal",
}
CORRECTION_URLS = {
    "https://blogs.nvidia.com/blog/local-ai-ifa-next-gen-agents-nv-pair-rtx-spark",
    "https://openai.com/index/1password",
    "https://techcrunch.com/2026/09/08/meta-debuts-its-muse-ai-agent-will-consumers-trust-it",
    "https://blogs.nvidia.com/blog/nvidia-to-acquire-hugging-face",
    "https://openai.com/index/teen-development-research-grants",
}


class TestJ_PastAnnouncementWithoutBackwardWording(unittest.TestCase):
    """Old primary announcement carrying no 'last week' wording. REAL evidence."""

    def test_aged_document_is_not_presentable_as_new(self):
        for title, pub in (
            (NVIDIA_IFA_TITLE, NVIDIA_IFA_PUBLISHED_AT),
            (NVIDIA_HF_TITLE, NVIDIA_HF_PUBLISHED_AT),
        ):
            with self.subTest(title=title):
                v = classify_global_event_novelty(
                    title, "", published_at=pub, as_of=B607_AS_OF
                )
                self.assertEqual(v.backward_reference, "")
                self.assertFalse(v.has_independent_development)
                self.assertFalse(v.presentable_as_new_development)
                self.assertEqual(v.framing_role, "historical_followup")

    def test_aged_document_stays_selectable_not_suppressed(self):
        """No blanket age cutoff: eligibility is unchanged, only framing moves."""
        v = classify_global_event_novelty(
            NVIDIA_HF_TITLE, "", published_at=NVIDIA_HF_PUBLISHED_AT, as_of=B607_AS_OF
        )
        self.assertTrue(v.eligible_as_new_development)

    def test_absence_of_backward_wording_is_not_evidence_of_newness(self):
        """The exact branch that failed acceptance."""
        v = classify_global_event_novelty(
            "Some vendor announcement", "", published_at="2026-08-01T00:00:00+09:00",
            as_of=B607_AS_OF,
        )
        self.assertFalse(v.has_independent_development)
        self.assertFalse(v.presentable_as_new_development)


class TestK_GenuineLaterDevelopmentAboutOldProduct(unittest.TestCase):
    """A real new development about an old product stays presentable. SYNTHETIC."""

    def test_recent_document_about_old_product_is_new_development(self):
        v = classify_global_event_novelty(
            "Hugging Face deal clears EU antitrust review",
            "The European Commission today cleared the transaction.",
            published_at="2026-09-09T09:00:00+09:00",
            as_of=B607_AS_OF,
        )
        self.assertTrue(v.presentable_as_new_development)
        self.assertEqual(v.framing_role, "new_development")

    def test_aged_document_with_its_own_present_development_stays_new(self):
        """Positive evidence beats age — this is why there is no age cutoff."""
        v = classify_global_event_novelty(
            "Vendor status update",
            "The company is announcing a price reduction effective immediately.",
            published_at="2026-09-01T00:00:00+09:00",
            as_of=B607_AS_OF,
        )
        self.assertTrue(v.has_independent_development)
        self.assertTrue(v.presentable_as_new_development)


class TestL_DocumentDateIsProxyNotVerifiedEvent(unittest.TestCase):
    """Publication timestamp must stay a disclosed proxy."""

    def test_basis_names_itself_a_proxy(self):
        v = classify_global_event_novelty(
            "Vendor ships feature",
            "The company announced a feature today.",
            published_at="2026-09-09T09:00:00+09:00",
            as_of=B607_AS_OF,
        )
        self.assertEqual(v.event_date_basis, "document_published_proxy")

    def test_age_is_measured_against_the_briefing_not_wall_time(self):
        v = classify_global_event_novelty(
            NVIDIA_HF_TITLE, "", published_at=NVIDIA_HF_PUBLISHED_AT, as_of=B607_AS_OF
        )
        self.assertAlmostEqual(v.document_age_hours, 140.3, delta=0.5)

    def test_without_as_of_age_is_unknown_not_guessed(self):
        v = classify_global_event_novelty(
            NVIDIA_HF_TITLE, "", published_at=NVIDIA_HF_PUBLISHED_AT
        )
        self.assertIsNone(v.document_age_hours)

    def test_window_boundary_is_the_existing_recency_bucket(self):
        self.assertEqual(GLOBAL_CURRENT_DEVELOPMENT_WINDOW_HOURS, 48)


class TestM_SelectionDiffReconciliation(unittest.TestCase):
    """Reconcile selections by source identity, never by assertion.

    The first acceptance report claimed 'the other four current items
    retained'. Computed from canonical URLs the real answer is 2 retained,
    3 removed, 3 added.
    """

    @staticmethod
    def _diff(before, after):
        return {
            "retained": sorted(before & after),
            "removed": sorted(before - after),
            "added": sorted(after - before),
        }

    def test_reconciliation_matches_the_artifacts(self):
        d = self._diff(ORIGINAL_URLS, CORRECTION_URLS)
        self.assertEqual(len(d["retained"]), 2)
        self.assertEqual(len(d["removed"]), 3)
        self.assertEqual(len(d["added"]), 3)

    def test_retained_set_is_exactly_meta_and_openai_grants(self):
        d = self._diff(ORIGINAL_URLS, CORRECTION_URLS)
        self.assertEqual(
            d["retained"],
            [
                "https://openai.com/index/teen-development-research-grants",
                "https://techcrunch.com/2026/09/08/meta-debuts-its-muse-ai-agent-will-consumers-trust-it",
            ],
        )

    def test_aws_roundup_was_removed(self):
        d = self._diff(ORIGINAL_URLS, CORRECTION_URLS)
        self.assertTrue(any("aws-weekly-roundup" in u for u in d["removed"]))


class TestN_ClaimModalityPromptRules(unittest.TestCase):
    """Agreement must not be written as completion."""

    def _global_prompt_text(self):
        from keysuri_generation_prompt import build_keysuri_generation_prompt
        from keysuri_news_contract import _claim_to_news_item

        snippet = "NVIDIA has agreed to acquire Hugging Face."
        srcs = [
            _source("m1", NVIDIA_HF_TITLE, snippet, NVIDIA_HF_PUBLISHED_AT,
                    "https://blogs.nvidia.com/blog/nvidia-to-acquire-hugging-face")
        ]
        claims = [_claim("m1", NVIDIA_HF_TITLE, snippet)]
        pack = {
            "program_id": "keysuri_global_tech",
            "generated_at": B607_AS_OF,
            "sources": srcs,
            "claims": claims,
        }
        smap = {s["source_id"]: s for s in srcs}
        item = _claim_to_news_item(
            claims[0], rank=1, smap=smap,
            program_id="keysuri_global_tech", as_of=B607_AS_OF,
        )
        prompt_input = {
            "program_id": "keysuri_global_tech",
            "news_scope": "global",
            "source_pack": pack,
            "top_5_news": {"section_heading": "글로벌 테크 TOP 5", "items": [item]},
        }
        return build_keysuri_generation_prompt(prompt_input)

    def test_item_carries_historical_followup_role_into_the_prompt(self):
        text = self._global_prompt_text()
        self.assertIn("historical_followup", text)
        self.assertIn(NVIDIA_HF_PUBLISHED_AT, text)

    def test_prompt_forbids_asserting_completion(self):
        text = self._global_prompt_text()
        self.assertIn("CLAIM MODALITY", text)
        self.assertIn("인수를 확정", text)
        self.assertIn("소유하게 되었습니다", text)

    def test_prompt_carries_temporal_framing_rules(self):
        text = self._global_prompt_text()
        self.assertIn("TEMPORAL FRAMING", text)
        self.assertIn("historical_followup", text)
        self.assertIn("new_development", text)


class TestO_OwnerAddressFragments(unittest.TestCase):
    """The two fragments observed in the customer-sent briefing."""

    def test_possessive_owner_address_leaves_no_orphan_particle(self):
        from keysuri_briefing_body_ux_normalizer import _strip_owner_address
        cases = {
            "주인님의 서비스가 이러한 에이전트 생태계 내에서 어떻게 발견될지 전략을 세워야 합니다.":
                "서비스가 이러한 에이전트 생태계 내에서 어떻게 발견될지 전략을 세워야 합니다.",
            "주인님의 기술 스택이 특정 벤더에 종속되지 않도록 점검하십시오.":
                "기술 스택이 특정 벤더에 종속되지 않도록 점검하십시오.",
        }
        for src, want in cases.items():
            with self.subTest(src=src):
                self.assertEqual(_strip_owner_address(src), want)

    def test_no_sentence_starts_with_an_orphan_particle(self):
        from keysuri_briefing_body_ux_normalizer import _strip_owner_address
        for src in (
            "주인님의 서비스가 흔들립니다.",
            "주인님께서는 확인하십시오.",
            "주인님, 오늘 신호입니다.",
            "주인님은 검토하십시오.",
            "주인님과 함께 봅니다.",
        ):
            with self.subTest(src=src):
                out = _strip_owner_address(src)
                self.assertFalse(
                    out.startswith(("의 ", "은 ", "는 ", "이 ", "가 ", "을 ", "를 ", "과 ", "와 ", ", ")),
                    f"orphan particle in {out!r}",
                )
