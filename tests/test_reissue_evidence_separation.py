import copy
import unittest

from keysuri_contract_preview_fixture import build_contract_preview_fixture_from_generated
from keysuri_contract_preview_renderer import (
    build_keysuri_global_gmail_owner_email_html,
    render_keysuri_contract_preview_html,
)
from keysuri_reader_surface import enforce_reader_surface
from keysuri_service_full_run import (
    _build_repaired_reissue_payload,
    _repair_reissue_top5_from_live_selection,
    KEYSURI_TOP_NEWS_COUNT,
)
from tests.test_service_full_run import (
    _briefing_for_live_items,
    _live_reselection_items_with_raw_english_ellipsis,
)


class ReissueEvidenceSeparationTest(unittest.TestCase):
    def _separated_pair(self):
        evidence = _live_reselection_items_with_raw_english_ellipsis(prefix="qa-independent")
        authored = copy.deepcopy(evidence)
        for n, item in enumerate(authored, 1):
            item.update(headline=f"검증용 새 기술 변화 {n}", korean_title=f"검증용 새 기술 변화 {n}",
                        summary=f"공개한 기능의 적용 대상과 사용 조건을 구분해 설명하는 작성 본문 {n}입니다.",
                        why_it_matters=f"계약 일정과 도입 비용을 비교할 때 확인할 구체적인 변화 {n}입니다.",
                        business_implication=f"사업 적용 범위와 후속 지표를 따로 점검할 판단 {n}입니다.")
        prompt = {"program_id": "keysuri_global_tech", "source_pack": {"sources": [], "claims": [], "sentinel": "unaltered"},
                  "top_5_news": {"news_scope": "global", "section_heading": "글로벌 테크 TOP 5", "sentinel": "keep-metadata", "items": evidence},
                  "selected_items": copy.deepcopy(evidence), "other_metadata": {"sentinel": [1, 2]}}
        return prompt, _briefing_for_live_items(authored), authored

    def _build(self, prompt, briefing, items):
        return _build_repaired_reissue_payload(base_briefing=briefing, top5_items=items,
                                              prompt_input=prompt, program_id="keysuri_global_tech")

    def test_unknown_url_cannot_override_a_known_id(self):
        prompt, briefing, items = self._separated_pair()
        items[0]["canonical_url"] = "https://example.invalid/unrelated"
        p, b, codes = self._build(prompt, briefing, items)
        self.assertIsNone(p)
        self.assertIsNone(b)
        self.assertEqual(codes, ["reissue_evidence_id_url_disagreement"])

    def test_duplicate_raw_url_is_ambiguous(self):
        prompt, briefing, items = self._separated_pair()
        prompt["top_5_news"]["items"][1]["canonical_url"] = prompt["top_5_news"]["items"][0]["canonical_url"]
        p, b, codes = self._build(prompt, briefing, items)
        self.assertIsNone(p)
        self.assertIsNone(b)
        self.assertEqual(codes, ["reissue_evidence_duplicate_identity"])

    def test_duplicate_output_binding_and_partial_output_fail_closed(self):
        prompt, briefing, items = self._separated_pair()
        for output, expected in ((items[:4], "reissue_output_count_mismatch"),
                                 ([items[0], items[0]] + items[2:], "reissue_evidence_duplicate_binding")):
            with self.subTest(expected=expected):
                p, b, codes = self._build(prompt, briefing, output)
                self.assertIsNone(p)
                self.assertIsNone(b)
                self.assertEqual(codes, [expected])

    def test_non_text_or_missing_evidence_is_not_stringified_into_proof(self):
        for key, invalid in (("summary", True), ("summary", {}), ("why_it_matters", []),
                             ("why_it_matters", None), ("news_id", ""), ("news_id", 123)):
            with self.subTest(key=key, invalid=invalid):
                prompt, briefing, items = self._separated_pair()
                prompt["top_5_news"]["items"][0][key] = invalid
                p, b, codes = self._build(prompt, briefing, items)
                self.assertIsNone(p)
                self.assertIsNone(b)
                self.assertTrue(codes)

    def test_input_preserved_and_returned_evidence_not_shared_with_authored(self):
        prompt, briefing, items = self._separated_pair()
        original_prompt = copy.deepcopy(prompt)
        original_briefing = copy.deepcopy(briefing)
        p, b, codes = self._build(prompt, briefing, items)
        self.assertEqual(codes, [])
        self.assertEqual(prompt, original_prompt)
        self.assertEqual(briefing, original_briefing)
        self.assertEqual(p, {**original_prompt, "required_count": 5, "selected_count": 5})
        b["top_5_news"]["items"][0]["summary"] = "changed-authored"
        self.assertEqual(p["top_5_news"]["items"], original_prompt["top_5_news"]["items"])

    def test_reordered_output_preserves_raw_evidence_and_reader_binding(self):
        prompt, briefing, items = self._separated_pair()
        order = [2, 0, 4, 1, 3]
        output = [copy.deepcopy(items[i]) for i in order]
        p, b, codes = self._build(prompt, briefing, output)
        self.assertEqual(codes, [])
        self.assertEqual(p["top_5_news"]["sentinel"], "keep-metadata")
        self.assertEqual(p["source_pack"], prompt["source_pack"])
        self.assertEqual(p["top_5_news"]["items"], [prompt["top_5_news"]["items"][i] for i in order])
        _, fields = enforce_reader_surface(b, program_id="keysuri_global_tech", prompt_input=p)
        self.assertEqual(fields["reader_surface_ready_item_count"], 5)

    def test_frozen_parent_repair_does_not_promote_authored_text_into_evidence(self):
        from keysuri_service_full_run import _repair_reissue_top5_from_parent_selection
        prompt, briefing, items = self._separated_pair()
        original = copy.deepcopy(prompt)
        parent = {"selected_items": copy.deepcopy(prompt["top_5_news"]["items"]),
                  "regen_generated_briefing_snapshot": copy.deepcopy(briefing)}
        p, b, fields, reason = _repair_reissue_top5_from_parent_selection(
            generated_briefing=briefing, prompt_input=prompt, parent=parent,
            program_id="keysuri_global_tech", strict_frozen_parent=True)
        self.assertIsNone(reason)
        self.assertEqual(p["top_5_news"]["items"], original["top_5_news"]["items"])
        self.assertEqual(prompt, original)
        _, reader = enforce_reader_surface(b, program_id="keysuri_global_tech", prompt_input=p)
        self.assertEqual(reader["reader_surface_ready_item_count"], 5)

    def test_positive_five_ready_and_html_render(self):
        live_items = _live_reselection_items_with_raw_english_ellipsis(prefix="pos-5")[:KEYSURI_TOP_NEWS_COUNT]
        prompt_input = {
            "program_id": "keysuri_global_tech",
            "source_pack": {
                "program_id": "keysuri_global_tech",
                "sources": [{"source_id": it["source_ids"][0]} for it in live_items],
                "claims": [],
            },
            "top_5_news": {
                "news_scope": "global",
                "section_heading": "글로벌 테크 TOP 5",
                "items": copy.deepcopy(live_items),
            },
        }
        briefing = _briefing_for_live_items(copy.deepcopy(live_items))
        for i, card in enumerate(briefing["top_5_news"]["items"]):
            card["headline"] = f"차세대 AI 프로세서 및 아키텍처 {i+1} 동향"
            card["korean_title"] = f"글로벌 테크 핵심 분석 {i+1}"
            card["summary"] = f"원문 영문 사실과 명확히 구별되는 독자 지향적 한국어 요약문 {i+1}입니다."
            card["why_it_matters"] = f"산업 생태계 및 기술 공급망에 미치는 파급 효과와 시사점 {i+1}입니다."
            card["business_implication"] = f"국내 기업 비즈니스 및 연구개발 전략에 주는 의미 {i+1}입니다."

        repaired_prompt, repaired_briefing, fields, err = _repair_reissue_top5_from_live_selection(
            generated_briefing=briefing,
            prompt_input=prompt_input,
            program_id="keysuri_global_tech",
            parent={},
        )
        self.assertIsNone(err)
        self.assertIsNotNone(repaired_prompt)
        self.assertIsNotNone(repaired_briefing)

        # Source pack untouched & prompt metadata preserved
        self.assertEqual(repaired_prompt["source_pack"], prompt_input["source_pack"])
        self.assertEqual(
            [it["summary"] for it in repaired_prompt["top_5_news"]["items"]],
            [it["summary"] for it in live_items],
        )

        enforced, rf = enforce_reader_surface(
            repaired_briefing,
            program_id="keysuri_global_tech",
            prompt_input=repaired_prompt,
        )
        self.assertEqual(rf.get("reader_surface_ready_item_count"), 5)

        fixture = build_contract_preview_fixture_from_generated(
            program_id="keysuri_global_tech",
            prompt_input=repaired_prompt,
            generated_briefing=enforced,
            source_pack=repaired_prompt["source_pack"],
        )
        self.assertEqual(len(fixture["top_5_items"]), 5)
        preview_html = render_keysuri_contract_preview_html(fixture, auto_prepare=False)
        self.assertIn("글로벌 테크 TOP 5", preview_html)
        self.assertNotIn("이 카드의 본문은 보류되었습니다", preview_html)
        gmail_html = build_keysuri_global_gmail_owner_email_html(fixture, subject="격리 합성 검수")
        self.assertIn("글로벌 테크 TOP 5", gmail_html)
        self.assertNotIn("이 카드의 본문은 보류되었습니다", gmail_html)
        for item in enforced["top_5_news"]["items"]:
            self.assertIn(item["what_happened"], preview_html)
            self.assertIn(item["what_happened"], gmail_html)

    def test_literal_raw_copy_control_zero_ready(self):
        live_items = _live_reselection_items_with_raw_english_ellipsis(prefix="raw-copy")[:KEYSURI_TOP_NEWS_COUNT]
        for i, it in enumerate(live_items):
            it["summary"] = f"한국어 원문 증거 텍스트 요약 {i+1}입니다."
            it["why_it_matters"] = f"한국어 원문 시사점 증거 텍스트 {i+1}입니다."
        prompt_input = {
            "program_id": "keysuri_global_tech",
            "source_pack": {"program_id": "keysuri_global_tech", "sources": [], "claims": []},
            "top_5_news": {
                "news_scope": "global",
                "section_heading": "글로벌 테크 TOP 5",
                "items": copy.deepcopy(live_items),
            },
        }
        base = _briefing_for_live_items(live_items)
        copied_items = copy.deepcopy(live_items)
        repaired_prompt, repaired_briefing, codes = _build_repaired_reissue_payload(
            base_briefing=base,
            top5_items=copied_items,
            prompt_input=prompt_input,
            program_id="keysuri_global_tech",
        )
        self.assertEqual(codes, [])
        self.assertIsNotNone(repaired_briefing)
        enforced, rf = enforce_reader_surface(
            repaired_briefing,
            program_id="keysuri_global_tech",
            prompt_input=repaired_prompt,
        )
        self.assertEqual(rf.get("reader_surface_ready_item_count"), 0)

    def test_missing_count_duplicate_id_url_conflict_and_partial_fail_closed(self):
        live_items = _live_reselection_items_with_raw_english_ellipsis(prefix="neg-id")[:KEYSURI_TOP_NEWS_COUNT]
        base_prompt = {
            "program_id": "keysuri_global_tech",
            "source_pack": {"program_id": "keysuri_global_tech", "sources": [], "claims": []},
            "top_5_news": {"items": copy.deepcopy(live_items)},
        }
        base = _briefing_for_live_items(live_items)

        # Count mismatch in raw evidence (4 items)
        p_count = copy.deepcopy(base_prompt)
        p_count["top_5_news"]["items"] = copy.deepcopy(live_items[:4])
        _, _, codes = _build_repaired_reissue_payload(
            base_briefing=base, top5_items=copy.deepcopy(live_items),
            prompt_input=p_count, program_id="keysuri_global_tech",
        )
        self.assertIn("reissue_evidence_count_mismatch", codes)

        # Duplicate news_id in raw evidence
        p_dup = copy.deepcopy(base_prompt)
        p_dup["top_5_news"]["items"][1]["news_id"] = p_dup["top_5_news"]["items"][0]["news_id"]
        _, _, codes = _build_repaired_reissue_payload(
            base_briefing=base, top5_items=copy.deepcopy(live_items),
            prompt_input=p_dup, program_id="keysuri_global_tech",
        )
        self.assertIn("reissue_evidence_duplicate_identity", codes)

        # ID/URL conflict (output item 0 has news_id of 0 but canonical_url of 1)
        out_conflict = copy.deepcopy(live_items)
        out_conflict[0]["canonical_url"] = live_items[1]["canonical_url"]
        _, _, codes = _build_repaired_reissue_payload(
            base_briefing=base, top5_items=out_conflict,
            prompt_input=base_prompt, program_id="keysuri_global_tech",
        )
        self.assertIn("reissue_evidence_id_url_disagreement", codes)

        # Partial/non-string evidence
        p_partial = copy.deepcopy(base_prompt)
        p_partial["top_5_news"]["items"][0]["summary"] = ""
        _, _, codes = _build_repaired_reissue_payload(
            base_briefing=base, top5_items=copy.deepcopy(live_items),
            prompt_input=p_partial, program_id="keysuri_global_tech",
        )
        self.assertIn("reissue_evidence_incomplete", codes)

        # Missing top_5_news completely
        p_missing = {"program_id": "keysuri_global_tech"}
        _, _, codes = _build_repaired_reissue_payload(
            base_briefing=base, top5_items=copy.deepcopy(live_items),
            prompt_input=p_missing, program_id="keysuri_global_tech",
        )
        self.assertIn("reissue_evidence_missing", codes)

    def test_template_only_cards_remain_zero_ready(self):
        live_items = _live_reselection_items_with_raw_english_ellipsis(prefix="template")[:KEYSURI_TOP_NEWS_COUNT]
        prompt_input = {
            "program_id": "keysuri_global_tech",
            "source_pack": {"program_id": "keysuri_global_tech", "sources": [], "claims": []},
            "top_5_news": {"news_scope": "global", "section_heading": "글로벌 테크 TOP 5", "items": copy.deepcopy(live_items)},
        }
        base = _briefing_for_live_items(live_items)
        template_items = copy.deepcopy(live_items)
        for it in template_items:
            it["summary"] = f"「{it['headline']}」 소식을 AI·테크 관점에서 선별해 정리했습니다."
            it["why_it_matters"] = f"「{it['headline']}」 관련 주요 시사점과 산업적 영향입니다."

        repaired_prompt, repaired_briefing, codes = _build_repaired_reissue_payload(
            base_briefing=base,
            top5_items=template_items,
            prompt_input=prompt_input,
            program_id="keysuri_global_tech",
        )
        self.assertEqual(codes, [])
        enforced, rf = enforce_reader_surface(
            repaired_briefing,
            program_id="keysuri_global_tech",
            prompt_input=repaired_prompt,
        )
        self.assertEqual(rf.get("reader_surface_ready_item_count"), 0)
