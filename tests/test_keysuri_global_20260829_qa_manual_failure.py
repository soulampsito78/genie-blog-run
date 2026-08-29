"""The 2026-08-29 15:11 KST Global qa_manual failure, replayed from its artifact.

Owner-observed shape, from the Admin run page:

* the section labelled "FINAL CONTENT / 고객에게 보이는 브리핑 / 저장된 실제 HTML"
  showed cards whose headline was "(본문 준비되지 않음 — 운영자 확인 필요)";
* the same stored HTML still carried raw English source prose — "There's a lot
  of capital pouring into the business of giving models away.", "Because it went
  so well before.", "Our decision to wind down our contract providing OpenAI
  models to Cursor following its acquisition by SpaceX.";
* the placeholder was reused as if it were an article headline, including in the
  owner-review subject line;
* an OpenAI/Cursor contract decision was filed under 항공우주·위성·방산 테크.

Delivery safety held — customer_send=0, approval unavailable — but the content
production failed, and a blocked bad briefing is still a product failure.

The mechanism: the model returned a display-only shell twice, the scaffold
completed ``top_5_news`` from the evidence pack, and the enricher then seeded
``what_happened`` / ``why_now`` from ``summary`` / ``why_it_matters`` — which at
that moment *were* the evidence. The old boundary bound ``summary``; the
renderer reads ``_item_field(item, "what_happened", "summary")``, so it read the
enricher's copy. The boundary wrote the fallback and the renderer read the
primary.

Every value below comes from the persisted artifact. No article fact is invented.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from admin_routes import reader_surface_preview_labels  # noqa: E402
from keysuri_contract_preview_renderer import (  # noqa: E402
    WITHHELD_CARD_NOTICE,
    _gmail_render_global_top_item,
)
from keysuri_global_signal_scoring import classify_global_tech_category  # noqa: E402
from keysuri_reader_surface import (  # noqa: E402
    PROSE_ALIASES,
    READER_STATUS_WITHHELD,
    UNAVAILABLE_MARKER,
    enforce_reader_surface,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "global_corpus_20260828"
    / "20260829_qa_manual_failure.json"
)

#: The five source sentences the owner read in the stored customer HTML.
SOURCE_ENGLISH = (
    "There's a lot of capital pouring into the business of giving models away.",
    "Because it went so well before.",
    "Our decision to wind down our contract providing OpenAI models to Cursor",
    "Are XREAL's smart glasses the way of the future for home entertainment?",
    "Given 10 benchmarks for specific misaligned behaviors",
)


def _case() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _prompt_input(case: dict) -> dict:
    return {"top_5_news": {"news_scope": "global", "items": case["evidence"]}}


def _briefing(case: dict) -> dict:
    return {"top_5_news": {"news_scope": "global", "items": case["items"]}}


def _visible_text(markup: str) -> str:
    import html as _html
    import re as _re

    text = _re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", markup)
    return _re.sub(r"\s+", " ", _html.unescape(_re.sub(r"<[^>]+>", " ", text)))


def _fixture_item(item: dict) -> dict:
    """The card as the renderer receives it, with reader state carried through."""
    return {
        k: item.get(k)
        for k in (
            "rank", "news_id", "headline", "korean_title", "what_happened", "why_now",
            "why_it_matters", "owner_angle", "business_implication", "next_watch",
            "selection_reason", "source_name", "source_url", "primary_category",
            "category_label_ko", "customer_visible", "reader_status",
            "reader_surface_ready",
        )
        if item.get(k) is not None
    }


def _reader_blob(item: dict) -> str:
    nested = item.get("briefing_item") if isinstance(item.get("briefing_item"), dict) else {}
    return json.dumps(
        {k: item.get(k) for k in PROSE_ALIASES}, ensure_ascii=False
    ) + json.dumps(nested, ensure_ascii=False)


class TheFailureIsFaithfullyPinnedTests(unittest.TestCase):
    """The fixture must still describe the failure, or it proves nothing."""

    def test_the_artifact_is_the_real_failed_run(self) -> None:
        case = _case()
        self.assertEqual(case["run_id"], "20260829_151157_keysuri_global_tech_d4a7f5da")
        self.assertEqual(case["editorial_verdict"], "POOR")
        self.assertEqual(case["safety_verdict"], "SAFE")

    def test_delivery_safety_held(self) -> None:
        case = _case()
        self.assertEqual(case["customer_send"], 0)
        self.assertFalse(case["customer_approval_available"])
        self.assertEqual(case["owner_delivery_behavior"], "SEND_OWNER_QUALITY_NOTICE")

    def test_the_persisted_cards_carried_the_source_english(self) -> None:
        # Pre-fix state. If this stops holding the fixture has drifted and the
        # rest of this file is asserting against a failure that is not the one
        # the owner saw.
        blob = json.dumps(_case()["items"], ensure_ascii=False)
        for sentence in SOURCE_ENGLISH:
            self.assertIn(sentence, blob, sentence)

    def test_the_placeholder_had_become_the_subject_line(self) -> None:
        self.assertTrue(_case()["observed_email_subject"].startswith(UNAVAILABLE_MARKER))


class TheBoundaryNowClosesThePathTests(unittest.TestCase):
    """Replayed through the patched boundary, on the same bytes."""

    def setUp(self) -> None:
        self.case = _case()
        self.out, self.diag = enforce_reader_surface(
            _briefing(self.case),
            program_id="keysuri_global_tech",
            prompt_input=_prompt_input(self.case),
        )
        self.items = self.out["top_5_news"]["items"]

    def test_no_raw_source_english_enters_customer_visible_prose(self) -> None:
        for item in self.items:
            blob = _reader_blob(item)
            for sentence in SOURCE_ENGLISH:
                self.assertNotIn(sentence, blob, f"{item.get('news_id')} / {sentence}")

    def test_a_rejected_field_stays_withheld_in_every_alias(self) -> None:
        # "summary" is an alias of "what_happened" and "why_it_matters" of
        # "why_now". Binding one and leaving the other is the 08-29 bypass.
        for item in self.items:
            for field in ("what_happened", "summary", "why_now", "why_it_matters"):
                self.assertEqual(item.get(field) or "", "", f"{item.get('news_id')}/{field}")

    def test_the_placeholder_cannot_become_an_article_field(self) -> None:
        for item in self.items:
            self.assertNotIn(UNAVAILABLE_MARKER, _reader_blob(item), str(item.get("news_id")))

    def test_withheld_is_structural_not_a_string(self) -> None:
        for item in self.items:
            self.assertEqual(item["reader_status"], READER_STATUS_WITHHELD)
            self.assertFalse(item["customer_visible"])
            self.assertFalse(item["reader_surface_ready"])
        self.assertEqual(self.diag["reader_surface_ready_item_count"], 0)

    def test_the_boundary_is_idempotent(self) -> None:
        # A reissue or repair pass reads back a briefing this boundary wrote. It
        # must not be able to promote the boundary's own refusal into prose.
        again, diag2 = enforce_reader_surface(
            self.out,
            program_id="keysuri_global_tech",
            prompt_input=_prompt_input(self.case),
        )
        self.assertEqual(diag2["reader_surface_ready_item_count"], 0)
        for item in again["top_5_news"]["items"]:
            self.assertNotIn(UNAVAILABLE_MARKER, _reader_blob(item))


class CategoryFollowsTheDominantSubjectTests(unittest.TestCase):
    """TOP1..TOP5 replayed against the same evidence."""

    #: What the failed run published, and what the dominant subject actually is.
    EXPECTED = {
        "claim-live-techcrunch-ai-fea5f6e87e": "policy_regulation_capital_supplychain",
        "claim-live-datacenter-dynamics-698c032847": "semiconductor_chip_infra",
        # OpenAI ending a model-supply contract. Not aerospace because the
        # acquirer is named SpaceX.
        "claim-live-openai-blog-b42ac281ec": "ai_software_platform",
        # An XREAL smart-glasses review. Not policy/capital because it came from
        # the TechCrunch Startups feed.
        "claim-live-techcrunch-startups-9d933e87ed": "hardware_device_display",
        "claim-live-techcrunch-ai-8152c5575e": "ai_software_platform",
    }

    def test_each_article_is_classified_by_its_primary_event(self) -> None:
        for ev in _case()["evidence"]:
            news_id = str(ev["news_id"])
            title = str(ev.get("headline") or "")
            blob = f"{title} {ev.get('summary') or ''}"
            primary, _sec, _conf, reason = classify_global_tech_category(
                blob, title=title, feed_default=str(ev.get("category") or "")
            )
            self.assertEqual(primary, self.EXPECTED[news_id], f"{news_id}: {reason}")

    def test_an_entity_name_alone_does_not_decide_the_category(self) -> None:
        primary, _s, _c, _r = classify_global_tech_category(
            "Our decision on Cursor following its acquisition by SpaceX",
            title="Our decision on Cursor following its acquisition by SpaceX",
        )
        self.assertNotEqual(primary, "aerospace_satellite_defense_tech")

    def test_a_real_aerospace_story_still_classifies_as_aerospace(self) -> None:
        # The guard must withhold the category on a bare entity name, not break
        # it for stories that are actually about the domain.
        primary, _s, _c, _r = classify_global_tech_category(
            "SpaceX launches 60 more Starlink satellites into low earth orbit",
            title="SpaceX launches 60 more Starlink satellites into low earth orbit",
        )
        self.assertEqual(primary, "aerospace_satellite_defense_tech")


class TheStoredHtmlTellsTheTruthTests(unittest.TestCase):
    """What the owner actually reads on the Admin run page."""

    def setUp(self) -> None:
        case = _case()
        out, _diag = enforce_reader_surface(
            _briefing(case),
            program_id="keysuri_global_tech",
            prompt_input=_prompt_input(case),
        )
        self.items = out["top_5_news"]["items"]
        self.html = "".join(
            _gmail_render_global_top_item(_fixture_item(item), int(item.get("rank") or 1))
            for item in self.items
        )
        self.visible = _visible_text(self.html)

    def test_no_source_english_reaches_the_rendered_card(self) -> None:
        for sentence in SOURCE_ENGLISH:
            self.assertNotIn(sentence, self.visible, sentence)

    def test_no_placeholder_reaches_the_rendered_card(self) -> None:
        self.assertNotIn(UNAVAILABLE_MARKER, self.visible)

    def test_a_withheld_card_says_it_is_withheld(self) -> None:
        self.assertEqual(self.visible.count(WITHHELD_CARD_NOTICE), len(self.items))

    def test_a_withheld_field_leaves_no_empty_labelled_block(self) -> None:
        # The label without a body under it was the shape the card took once the
        # marker stopped being written into the prose.
        for label in ("무슨 일이 있었나", "왜 지금 중요한가"):
            self.assertNotIn(label, self.visible, label)


class AdminMustNotCallABlockedCandidateCustomerContentTests(unittest.TestCase):
    """Section 8: the Admin heading is a claim, and it must be true."""

    def test_an_incomplete_reader_surface_is_labelled_as_blocked(self) -> None:
        labels = reader_surface_preview_labels(
            {
                "reader_surface_enforced": True,
                "reader_surface_complete": False,
                "reader_surface_ready_item_count": 0,
                "reader_surface_unavailable_fields": ["a:headline"],
                "reader_surface_issue_codes": ["keysuri_reader_prose_was_source_text:headline"],
            }
        )
        self.assertNotIn("고객에게 보이는", labels["title"])
        self.assertIn("고객에게 보이지 않음", labels["title"])
        self.assertNotEqual(labels["evidence_label"], "저장된 실제 HTML")

    def test_a_complete_reader_surface_is_still_customer_content(self) -> None:
        labels = reader_surface_preview_labels(
            {"reader_surface_enforced": True, "reader_surface_complete": True}
        )
        self.assertEqual(labels["title"], "고객에게 보이는 브리핑")

    def test_the_failed_run_would_have_been_labelled_blocked(self) -> None:
        case = _case()
        labels = reader_surface_preview_labels(
            {
                "reader_surface_enforced": True,
                "reader_surface_complete": False,
                "reader_surface_ready_item_count": case["reader_surface_ready_item_count"],
            }
        )
        self.assertIn("고객에게 보이지 않음", labels["title"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
