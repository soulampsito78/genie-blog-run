from __future__ import annotations

import unittest

from sent_news_dedup_gate import (
    canonicalize_url,
    editorial_cluster_key,
    extract_company_entities,
    normalize_title,
    run_sent_news_dedup_gate,
    select_with_diversity_caps,
)


def _item(idx: int, **overrides):
    data = {
        "title": f"Fresh AI headline {idx}",
        "url": f"https://example.com/news/{idx}",
        "source": "Example",
        "topic_key": f"topic-{idx}",
        "summary": f"Summary {idx}",
    }
    data.update(overrides)
    return data


def _item_without_topic(idx: int, **overrides):
    data = _item(idx, **overrides)
    data.pop("topic_key", None)
    return data


class SentNewsDedupGateTests(unittest.TestCase):
    def test_canonical_url_removes_tracking(self) -> None:
        self.assertEqual(
            canonicalize_url("HTTPS://Example.COM/path/?utm_source=x&a=1#frag"),
            "https://example.com/path?a=1",
        )

    def test_normalized_title_removes_noise(self) -> None:
        self.assertEqual(normalize_title("[속보] AI 투자 확대!!!"), "ai 투자 확대")

    def test_recent_log_canonical_url_duplicate_rejected(self) -> None:
        result = run_sent_news_dedup_gate(
            briefing_type="today_genie",
            candidates=[_item(1, url="https://example.com/a?utm_source=x"), _item(2)],
            sent_log_last_5_days=[_item(9, url="https://example.com/a")],
            required_count=1,
        )
        self.assertEqual(result["rejected_items"][0]["rejected_reason"], "recent_log_canonical_url_duplicate")

    def test_recent_log_normalized_title_duplicate_rejected(self) -> None:
        result = run_sent_news_dedup_gate(
            briefing_type="today_genie",
            candidates=[_item(1, title="[단독] Same Title"), _item(2)],
            sent_log_last_5_days=[_item(9, title="Same Title")],
            required_count=1,
        )
        self.assertEqual(result["rejected_items"][0]["rejected_reason"], "recent_log_normalized_title_duplicate")

    def test_recent_log_source_similar_title_duplicate_rejected(self) -> None:
        result = run_sent_news_dedup_gate(
            briefing_type="today_genie",
            candidates=[_item(1, source="Wire", title="OpenAI launches enterprise agent platform"), _item(2)],
            sent_log_last_5_days=[_item(9, source="Wire", title="OpenAI launches enterprise agents platform")],
            required_count=1,
        )
        self.assertEqual(result["rejected_items"][0]["rejected_reason"], "recent_log_source_similar_title_duplicate")

    def test_recent_log_topic_key_duplicate_rejected(self) -> None:
        result = run_sent_news_dedup_gate(
            briefing_type="keysuri_global_tech",
            candidates=[_item(1, topic_key="chips"), _item(2)],
            sent_log_last_5_days=[_item(9, topic_key="chips")],
            required_count=1,
        )
        self.assertEqual(result["rejected_items"][0]["rejected_reason"], "recent_log_topic_key_duplicate")

    def test_same_category_does_not_count_as_topic_duplicate(self) -> None:
        candidates = [
            _item_without_topic(
                idx,
                category="ai_product",
                title=f"Different headline {idx}",
                url=f"https://example.com/different/{idx}",
                source=f"Source {idx}",
            )
            for idx in range(1, 6)
        ]
        result = run_sent_news_dedup_gate(
            briefing_type="keysuri_global_tech",
            candidates=candidates,
            sent_log_last_5_days=[],
            required_count=5,
        )
        self.assertEqual(len(result["selected_items"]), 5)
        self.assertEqual(result["rejected_items"], [])

    def test_missing_topic_key_uses_url_title_source_only(self) -> None:
        result = run_sent_news_dedup_gate(
            briefing_type="keysuri_global_tech",
            candidates=[
                _item_without_topic(1, category="policy", title="Policy headline", url="https://example.com/a"),
                _item_without_topic(2, category="policy", title="Funding headline", url="https://example.com/b"),
            ],
            sent_log_last_5_days=[
                _item_without_topic(9, category="policy", title="Old unrelated headline", url="https://example.com/old")
            ],
            required_count=2,
        )
        self.assertEqual(len(result["selected_items"]), 2)
        self.assertNotIn("recent_log_topic_key_duplicate", result["dedup_summary"]["rejected_by_reason"])

    def test_selected_internal_duplicate_rejected(self) -> None:
        result = run_sent_news_dedup_gate(
            briefing_type="keysuri_korea_tech",
            candidates=[_item(1, title="Same"), _item(2, title="Same", url="https://example.com/other"), _item(3)],
            sent_log_last_5_days=[],
            required_count=2,
        )
        reasons = [item["rejected_reason"] for item in result["rejected_items"]]
        self.assertIn("selected_normalized_title_duplicate", reasons)

    def test_next_candidate_promoted_to_fill_required_count(self) -> None:
        result = run_sent_news_dedup_gate(
            briefing_type="keysuri_global_tech",
            candidates=[
                _item(1, url="https://dup.example/a"),
                _item(2, title="Semiconductor capex expands"),
                _item(3, title="Cloud security spending rises"),
            ],
            sent_log_last_5_days=[_item(9, url="https://dup.example/a")],
            required_count=2,
        )
        self.assertEqual([item["title"] for item in result["selected_items"]], ["Semiconductor capex expands", "Cloud security spending rises"])
        self.assertTrue(result["dedup_summary"]["filled_required_count"])

    def test_insufficient_fresh_candidates_records_shortfall(self) -> None:
        result = run_sent_news_dedup_gate(
            briefing_type="keysuri_korea_tech",
            candidates=[_item(1)],
            sent_log_last_5_days=[],
            required_count=2,
        )
        self.assertEqual(result["dedup_summary"]["selected_count"], 1)
        self.assertEqual(result["dedup_summary"]["reason"], "insufficient_fresh_candidates")


def _div_item(
    news_id: str,
    title: str,
    *,
    source: str = "",
    source_ids=None,
    summary: str = "",
    source_domain: str = "",
):
    item = {"news_id": news_id, "title": title, "headline": title, "summary": summary}
    if source:
        item["source"] = source
    if source_ids is not None:
        item["source_ids"] = source_ids
    if source_domain:
        item["source_domain"] = source_domain
    return item


class DiversityCapTests(unittest.TestCase):
    """same-source / entity / editorial-cluster caps applied at TOP-N selection."""

    def test_same_source_cap_replaces_with_next_distinct_candidate(self) -> None:
        # Two NVIDIA Blog items + four other-source items; required 5.
        candidates = [
            _div_item("n1", "NVIDIA and AWS Collaborate to Bring AI to Production at Scale", source="NVIDIA Blog"),
            _div_item("p1", "Patronus AI lands $50M for agent testing", source="TechCrunch"),
            _div_item("n2", "How Businesses Build Specialized AI They Can Trust", source="NVIDIA Blog"),
            _div_item("o1", "OpenAI partners with chip firms on design", source="Datacenter Dynamics"),
            _div_item("g1", "Latest Google Finance upgrades, new app", source="Google AI Blog"),
            _div_item("m1", "Microsoft expands cloud security offering", source="Reuters"),
        ]
        result = select_with_diversity_caps(candidates, required_count=5)
        ids = [it["news_id"] for it in result["selected_items"]]
        self.assertEqual(len(ids), 5)
        # The second NVIDIA Blog item is replaced by the next distinct source (m1).
        self.assertIn("n1", ids)
        self.assertNotIn("n2", ids)
        self.assertIn("m1", ids)
        self.assertFalse(result["diversity_summary"]["relaxed_due_to_candidate_shortage"])
        self.assertGreaterEqual(result["diversity_summary"]["same_source_reject_count"], 1)
        rej = [r for r in result["rejected_items"] if r["news_id"] == "n2"]
        self.assertEqual(rej[0]["rejected_reason"], "same_source_cap")
        self.assertEqual(rej[0]["collided_with"]["news_id"], "n1")

    def test_non_nvidia_same_source_cap_is_general(self) -> None:
        cases = [
            ("OpenAI Blog", {}, {}),
            ("Google Blog", {}, {}),
            ("TechCrunch", {}, {}),
            ("", {"source_ids": ["live-unknown-publisher-a1b2c3d4"]}, {"source_ids": ["live-unknown-publisher-deadbeef"]}),
            ("", {"source_domain": "example.com"}, {"source_domain": "example.com"}),
        ]
        for source, first_extra, second_extra in cases:
            with self.subTest(source=source or first_extra):
                candidates = [
                    _div_item("a", "First AI platform update", source=source, **first_extra),
                    _div_item("b", "Second AI platform update", source=source, **second_extra),
                    _div_item("c", "Funding round closes", source="Wire C"),
                    _div_item("d", "Cloud platform expands", source="Wire D"),
                    _div_item("e", "Enterprise SaaS launch", source="Wire E"),
                    _div_item("f", "Policy update lands", source="Wire F"),
                ]
                result = select_with_diversity_caps(candidates, required_count=5)
                rejected = [r for r in result["rejected_items"] if r["news_id"] == "b"]
                self.assertEqual(rejected[0]["rejected_reason"], "same_source_cap")
                self.assertEqual(rejected[0]["collided_with"]["news_id"], "a")
                self.assertIn("f", [it["news_id"] for it in result["selected_items"]])

    def test_entity_cap_rejects_second_same_company_even_with_different_source(self) -> None:
        candidates = [
            _div_item("a", "NVIDIA unveils new Blackwell GPU lineup", source="Wire A"),
            _div_item("b", "Why NVIDIA chips dominate AI training", source="Wire B"),  # diff source, same entity
            _div_item("c", "Patronus AI raises funding", source="Wire C"),
            _div_item("d", "OpenAI ships new model", source="Wire D"),
            _div_item("e", "Apple updates developer tools", source="Wire E"),
            _div_item("f", "Meta open-sources a dataset", source="Wire F"),
        ]
        result = select_with_diversity_caps(candidates, required_count=5)
        ids = [it["news_id"] for it in result["selected_items"]]
        self.assertIn("a", ids)
        self.assertNotIn("b", ids)
        rej = [r for r in result["rejected_items"] if r["news_id"] == "b"]
        self.assertEqual(rej[0]["rejected_reason"], "entity_cap")
        self.assertEqual(rej[0]["collided_entity"], "nvidia")

    def test_entity_cap_handles_non_nvidia_alias_variants(self) -> None:
        cases = [
            ("openai", "OpenAI ships new agent platform", "Open AI updates model router"),
            ("microsoft", "Microsoft expands Copilot Studio", "MS adds enterprise agents"),
            ("google", "Google launches Gemini workflow", "Alphabet updates AI research platform"),
            ("aws", "AWS launches AI infrastructure", "Amazon Web Services expands inference"),
            ("aws", "AWS launches AI infrastructure", "Amazon expands inference cloud"),
            ("anthropic", "Anthropic launches Claude agents", "앤트로픽 enterprise AI update"),
            ("databricks", "Databricks adds AI functions", "Databricks launches Lakebase"),
        ]
        for expected_entity, first_title, second_title in cases:
            with self.subTest(expected_entity=expected_entity):
                candidates = [
                    _div_item("a", first_title, source="Wire A"),
                    _div_item("b", second_title, source="Wire B"),
                    _div_item("c", "Apple releases developer tools", source="Wire C"),
                    _div_item("d", "Meta updates model platform", source="Wire D"),
                    _div_item("e", "Oracle cloud policy update", source="Wire E"),
                    _div_item("f", "Perplexity enterprise search launch", source="Wire F"),
                ]
                result = select_with_diversity_caps(candidates, required_count=5)
                rejected = [r for r in result["rejected_items"] if r["news_id"] == "b"]
                self.assertEqual(rejected[0]["rejected_reason"], "entity_cap")
                self.assertEqual(rejected[0]["collided_entity"], expected_entity)

    def test_added_company_aliases_are_extracted_without_broad_ms_false_positive(self) -> None:
        expected = {
            "Perplexity launches enterprise search": "perplexity",
            "퍼플렉시티 browser update": "perplexity",
            "Oracle expands cloud AI": "oracle",
            "오라클 database AI 출시": "oracle",
            "Salesforce updates CRM workflow": "salesforce",
            "세일즈포스 productivity suite": "salesforce",
            "Adobe ships creative AI tools": "adobe",
            "어도비 business app update": "adobe",
            "Broadcom announces VMware platform changes": "broadcom",
            "브로드컴 chip software update": "broadcom",
            "AMD releases AI accelerator": "amd",
            "Intel updates server roadmap": "intel",
            "인텔 launches inference chip": "intel",
        }
        for title, entity in expected.items():
            with self.subTest(title=title):
                self.assertIn(entity, extract_company_entities(_div_item("x", title)))
        self.assertNotIn("microsoft", extract_company_entities(_div_item("ms", "latency is 10 ms lower")))

    def test_source_id_prefix_fallback_when_source_name_missing(self) -> None:
        # No source name; same-source cap must fall back to source_id prefix.
        candidates = [
            _div_item("x1", "NVIDIA AWS production scale", source_ids=["live-nvidia-blog-e7cad40fb5"]),
            _div_item("x2", "Specialized enterprise AI trust", source_ids=["live-nvidia-blog-75c7b56bd5"]),
            _div_item("x3", "Patronus funding", source_ids=["live-techcrunch-ai-9fde553dee"]),
            _div_item("x4", "Datacenter chip design", source_ids=["live-datacenter-dynamics-f4e8437ee7"]),
            _div_item("x5", "Korean robotics growth", source_ids=["live-etnews-korea-aaaa1111"]),
        ]
        result = select_with_diversity_caps(candidates, required_count=5)
        # 5 candidates, two share the nvidia-blog prefix -> strict caps leave 4 ->
        # relax fills to 5 with an explicit shortage flag (never a silent pass).
        self.assertEqual(len(result["selected_items"]), 5)
        self.assertTrue(result["diversity_summary"]["relaxed_due_to_candidate_shortage"])
        self.assertGreaterEqual(result["diversity_summary"]["same_source_reject_count"], 1)
        promoted = [it for it in result["selected_items"] if it.get("diversity_relaxed")]
        self.assertEqual(len(promoted), 1)
        self.assertEqual(promoted[0]["diversity_relaxed_from"], "same_source_cap")

    def test_target_run_two_nvidia_only_one_survives_strict(self) -> None:
        # Reproduces 20260626 global run: 5 candidates incl. 2 NVIDIA Blog.
        candidates = [
            _div_item("g", "Our latest Google Finance upgrades, including a new app", source="Google AI Blog"),
            _div_item("p", "Patronus AI lands $50M to build digital worlds", source="TechCrunch AI"),
            _div_item("n1", "NVIDIA and AWS Collaborate to Bring AI to Production at Scale", source="NVIDIA Blog"),
            _div_item("n2", "How Businesses Are Building Specialized AI They Can Trust", source="NVIDIA Blog"),
            _div_item("o", "OpenAI new bet to partner with semiconductor companies", source="Datacenter Dynamics"),
        ]
        result = select_with_diversity_caps(candidates, required_count=5)
        # Only 5 candidates so 5 must be returned (contract), but the duplicate is
        # surfaced loudly via same_source_reject_count + relaxed flag, not silent.
        self.assertEqual(len(result["selected_items"]), 5)
        self.assertEqual(result["diversity_summary"]["same_source_reject_count"], 1)
        self.assertTrue(result["diversity_summary"]["relaxed_due_to_candidate_shortage"])
        promoted = [it for it in result["selected_items"] if it.get("diversity_relaxed")]
        self.assertEqual([it["news_id"] for it in promoted], ["n2"])

    def test_no_shortfall_or_relax_when_all_distinct(self) -> None:
        candidates = [
            _div_item("a", "Chipmaker A expands fab", source="Src A"),
            _div_item("b", "Cloud B launches region", source="Src B"),
            _div_item("c", "Startup C raises seed", source="Src C"),
            _div_item("d", "Platform D opens API", source="Src D"),
            _div_item("e", "Policy E updates rules", source="Src E"),
        ]
        result = select_with_diversity_caps(candidates, required_count=5)
        self.assertEqual(len(result["selected_items"]), 5)
        self.assertFalse(result["diversity_summary"]["relaxed_due_to_candidate_shortage"])
        self.assertEqual(result["diversity_summary"]["same_source_reject_count"], 0)
        self.assertEqual(result["diversity_summary"]["entity_reject_count"], 0)
        self.assertEqual(result["diversity_summary"]["shortfall"], 0)
        self.assertEqual([it["rank"] for it in result["selected_items"]], [1, 2, 3, 4, 5])

    def test_entity_extraction_and_cluster_key(self) -> None:
        item = _div_item(
            "z", "NVIDIA and AWS Collaborate to Bring AI to Production at Scale",
            source="NVIDIA Blog",
            summary="Low-latency inference and GPU infrastructure at scale across Amazon EC2.",
        )
        self.assertIn("nvidia", extract_company_entities(item))
        self.assertIn("aws", extract_company_entities(item))
        self.assertEqual(editorial_cluster_key(item), "ai_infrastructure")

    def test_editorial_cluster_key_generalized_topics(self) -> None:
        cases = [
            ("OpenAI updates safety policy for platform developers", "platform_policy"),
            ("EU antitrust regulation changes app store rule", "platform_policy"),
            ("Salesforce launches enterprise SaaS workflow suite", "enterprise_saas"),
            ("Adobe adds productivity collaboration workspace", "enterprise_saas"),
            ("AWS expands inference cloud compute capacity", "cloud_infrastructure"),
            ("Oracle opens new cloud region and data center", "cloud_infrastructure"),
        ]
        for title, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(editorial_cluster_key(_div_item("x", title)), expected)


if __name__ == "__main__":
    unittest.main()
