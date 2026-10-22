"""A prose-only reissue must generate against the parent's exact TOP5."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import keysuri_service_full_run as runner


class FrozenParentPromptTests(unittest.TestCase):
    def _parent(self) -> dict:
        items = [
            {
                "rank": rank,
                "news_id": f"parent-news-{rank}",
                "headline": f"Parent headline {rank}",
                "summary": f"Parent summary {rank}",
                "source_ids": [f"parent-source-{rank}"],
            }
            for rank in range(1, 6)
        ]
        source_pack = {
            "program_id": "keysuri_global_tech",
            "sources": [{"source_id": f"parent-source-{rank}"} for rank in range(1, 6)],
            "claims": [],
        }
        return {
            "program_id": "keysuri_global_tech",
            "selected_items": items,
            "regen_source_pack_snapshot": source_pack,
            "regen_prompt_input_snapshot": {
                "program_id": "keysuri_global_tech",
                "prompt_status": "ready_for_generation",
                "top_5_news": {"items": copy.deepcopy(items)},
                "source_pack": copy.deepcopy(source_pack),
            },
        }

    def test_uses_saved_selection_without_reselecting_against_current_logs(self) -> None:
        parent = self._parent()
        with patch.object(runner, "build_keysuri_prompt_input", side_effect=AssertionError("reselected")):
            prompt_input, error = runner._regen_prompt_input_from_parent(
                parent, "keysuri_global_tech"
            )
        self.assertIsNone(error)
        self.assertEqual(
            [item["news_id"] for item in prompt_input["top_5_news"]["items"]],
            [item["news_id"] for item in parent["selected_items"]],
        )
        prompt_input["top_5_news"]["items"][0]["news_id"] = "mutated"
        self.assertEqual(
            parent["regen_prompt_input_snapshot"]["top_5_news"]["items"][0]["news_id"],
            "parent-news-1",
        )

    def test_mismatched_saved_selection_fails_closed(self) -> None:
        parent = self._parent()
        parent["regen_prompt_input_snapshot"]["top_5_news"]["items"][0]["news_id"] = "other-news"
        prompt_input, error = runner._regen_prompt_input_from_parent(
            parent, "keysuri_global_tech"
        )
        self.assertIsNone(prompt_input)
        self.assertEqual(error, "regen_parent_prompt_selection_mismatch")

    def test_missing_saved_prompt_fails_closed(self) -> None:
        parent = self._parent()
        del parent["regen_prompt_input_snapshot"]
        prompt_input, error = runner._regen_prompt_input_from_parent(
            parent, "keysuri_global_tech"
        )
        self.assertIsNone(prompt_input)
        self.assertEqual(error, "regen_missing_parent_prompt_snapshot")

    def test_wrong_program_or_unready_snapshot_fails_closed(self) -> None:
        parent = self._parent()
        parent["regen_prompt_input_snapshot"]["program_id"] = "keysuri_korea_tech"
        self.assertEqual(
            runner._regen_prompt_input_from_parent(parent, "keysuri_global_tech")[1],
            "regen_parent_prompt_program_mismatch",
        )
        parent = self._parent()
        parent["regen_prompt_input_snapshot"]["prompt_status"] = "hold_review_required"
        self.assertEqual(
            runner._regen_prompt_input_from_parent(parent, "keysuri_global_tech")[1],
            "regen_parent_prompt_not_ready",
        )
        parent = self._parent()
        parent["regen_source_pack_snapshot"]["program_id"] = "keysuri_korea_tech"
        self.assertEqual(
            runner._regen_prompt_input_from_parent(parent, "keysuri_global_tech")[1],
            "regen_parent_source_pack_program_mismatch",
        )

    def test_exact_generated_top5_keeps_new_korean_item_prose(self) -> None:
        parent = self._parent()
        generated_items = copy.deepcopy(parent["selected_items"])
        generated_items[0]["korean_title"] = "새로 다듬은 한국어 제목"
        generated = {"top_5_news": {"items": generated_items}}

        def accept_payload(**kwargs):
            return kwargs["prompt_input"], kwargs["base_briefing"], []

        with patch.object(runner, "_build_repaired_reissue_payload", side_effect=accept_payload):
            _prompt, briefing, fields, error = runner._repair_reissue_top5_from_parent_selection(
                generated_briefing=generated,
                prompt_input=parent["regen_prompt_input_snapshot"],
                parent=parent,
                program_id="keysuri_global_tech",
                strict_frozen_parent=True,
            )
        self.assertIsNone(error)
        self.assertEqual(fields["reissue_top5_repair_source"], "gemini_output_exact_parent_top5")
        self.assertEqual(
            briefing["top_5_news"]["items"][0]["korean_title"],
            "새로 다듬은 한국어 제목",
        )

    def test_different_generated_top5_never_mix_with_new_narrative(self) -> None:
        parent = self._parent()
        parent["regen_generated_briefing_snapshot"] = {
            "top_5_news": {"items": copy.deepcopy(parent["selected_items"])},
            "deep_dive": {},
            "one_line_checkpoint": {},
            "closing_sources": {},
        }
        generated_items = copy.deepcopy(parent["selected_items"])
        generated_items[0]["news_id"] = "unrelated-news"
        generated = {"top_5_news": {"items": generated_items}, "deep_dive": {"body": "unrelated"}}

        def accept_payload(**kwargs):
            return kwargs["prompt_input"], kwargs["base_briefing"], []

        with patch.object(runner, "_build_repaired_reissue_payload", side_effect=accept_payload) as build:
            _prompt, briefing, fields, error = runner._repair_reissue_top5_from_parent_selection(
                generated_briefing=generated,
                prompt_input=parent["regen_prompt_input_snapshot"],
                parent=parent,
                program_id="keysuri_global_tech",
                strict_frozen_parent=True,
            )
        self.assertIsNone(error)
        self.assertEqual(build.call_count, 1)
        self.assertEqual(fields["reissue_top5_repair_source"], "parent_generated_briefing_snapshot")
        self.assertNotEqual(briefing["deep_dive"].get("body"), "unrelated")

    def test_frozen_regeneration_uses_bounded_generation_helper(self) -> None:
        parent = self._parent()
        caller = Mock()
        generated = {"top_5_news": {"items": copy.deepcopy(parent["selected_items"])}}
        with patch.object(
            runner,
            "generate_keysuri_body_raw_text",
            return_value=("generated-json", {"retry_applied": True}),
        ) as bounded, patch.object(
            runner,
            "parse_keysuri_generated_response",
            return_value={"parse_status": "parsed_valid", "generated_briefing": generated},
        ), patch.object(
            runner, "enrich_generated_briefing_content", side_effect=lambda body, *_a: body
        ), patch.object(
            runner, "repair_keysuri_visible_text_fields", side_effect=lambda body, **_kw: (body, {})
        ):
            prompt_input, briefing, error = runner._regenerate_keysuri_text_from_snapshot(
                parent, "keysuri_global_tech", text_caller=caller
            )
        self.assertIsNone(error)
        self.assertIsNotNone(briefing)
        self.assertEqual(
            [item["news_id"] for item in prompt_input["top_5_news"]["items"]],
            [item["news_id"] for item in parent["selected_items"]],
        )
        bounded.assert_called_once()
        self.assertIs(bounded.call_args.kwargs["gemini_caller"], caller)

    def test_failed_prose_generation_does_not_reemail_parent_body(self) -> None:
        parent = self._parent()
        with patch.object(
            runner,
            "_regenerate_keysuri_text_from_snapshot",
            return_value=(parent["regen_prompt_input_snapshot"], None, "generated_briefing_regen_parse_failed"),
        ), patch.object(runner, "_repair_reissue_top5_from_parent_selection") as repair:
            prompt_input, briefing, fields, error = runner._regenerate_keysuri_text_from_frozen_parent(
                "keysuri_global_tech", parent
            )
        self.assertIsNone(prompt_input)
        self.assertIsNone(briefing)
        self.assertFalse(fields["reissue_frozen_parent_prose_regenerated"])
        self.assertEqual(error, "text_only_reissue_prose_generation_failed")
        repair.assert_not_called()


class EditorialRepairAndImageOriginTests(unittest.TestCase):
    def test_korea_frozen_image_identity_is_independent_of_restore_paths(self):
        run_id='20261022_200306_keysuri_korea_tech_a3bf255a'
        warm=runner.inline_jpeg_parts_for_korea_service_email(Path('/warm/original.jpg'),run_id,bottom_image_path=Path('/warm/bottom.jpg'))
        restored=runner.inline_jpeg_parts_for_korea_service_email(Path('/cold/restored_top.jpg'),run_id,bottom_image_path=Path('/cold/restored_bottom.jpg'))
        self.assertEqual([(cid,name) for _,cid,name in warm],[(cid,name) for _,cid,name in restored])
        self.assertEqual(warm[0][2],warm[0][1]+'.jpg')
        self.assertEqual(warm[1][2],warm[1][1]+'.jpg')
        self.assertNotEqual(warm[0][0],restored[0][0])

    def test_korea_reissue_pending_copy_stays_owner_only_in_delegated_final(self):
        from keysuri_customer_delivery import prepare_keysuri_customer_final_html
        from customer_review_confirmation import DELEGATED_WORK_REVIEW, DELEGATED_REVIEW_TEXT
        pending = '본 브리핑은 운영책임자의 직접 검수 대기 상태입니다.'
        original = '<html><body><p>사전등록 520명, 750명 이상 예상.</p><table><tr><td>'+pending+'</td></tr></table></body></html>'
        owner = runner._mark_korea_reissue_owner_pending_copy(original)
        self.assertIn(pending, owner)
        customer = prepare_keysuri_customer_final_html(owner, meta={'mode':'keysuri_korea_tech'}, approval_source=DELEGATED_WORK_REVIEW)
        self.assertNotIn('운영책임자의 직접 검수', customer)
        self.assertNotIn('검수 대기', customer)
        self.assertIn(DELEGATED_REVIEW_TEXT, customer)
        self.assertIn('사전등록 520명, 750명 이상 예상.', customer)
        self.assertIn('email_html = _mark_korea_reissue_owner_pending_copy(email_html)', Path(runner.__file__).read_text())

    def test_cold_revision_restores_exact_korea_top_and_bottom_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {"top": b"original top", "bottom": b"original bottom"}
            parent = {"mode": "keysuri_korea_tech", "top_image_cid": "top", "bottom_image_cid": "bottom",
                      "korea_generated_image_gcs_bucket": "existing-bucket",
                      "korea_generated_top_gcs_object": "parent/top.jpg",
                      "korea_generated_bottom_gcs_object": "parent/bottom.jpg",
                      "owner_email_inline_image_hashes": [{"cid": role, "path": str(Path(tmp)/(role+"-gone.jpg")),
                          "sha256": hashlib.sha256(value).hexdigest()} for role,value in data.items()]}
            def download(dest, *, bucket_name, object_name):
                self.assertEqual(bucket_name, "existing-bucket")
                dest.write_bytes(data[Path(object_name).stem])
                return None
            with patch.object(runner, "_writable_keysuri_service_assets_dir", return_value=Path(tmp)), \
                 patch.object(runner, "_download_keysuri_top_image_from_gcs", side_effect=download) as fetch:
                top, fields = runner._saved_top_image_reference(parent)
                bottom = runner._saved_korea_bottom_image_path(parent)
            self.assertEqual(top.read_bytes(), data["top"])
            self.assertEqual(bottom.read_bytes(), data["bottom"])
            self.assertTrue(fields["reissue_body_only_image_hash_verified"])
            self.assertEqual(fetch.call_count, 2)

    def test_restored_korea_image_mismatch_or_missing_proof_never_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = {"top_image_cid": "top", "korea_generated_image_gcs_bucket": "existing-bucket",
                      "korea_generated_top_gcs_object": "parent/top.jpg",
                      "owner_email_inline_image_hashes": [{"cid": "top", "sha256": "0"*64}]}
            def download(dest, **_):
                dest.write_bytes(b"wrong bytes")
                return None
            with patch.object(runner, "_writable_keysuri_service_assets_dir", return_value=Path(tmp)), \
                 patch.object(runner, "_download_keysuri_top_image_from_gcs", side_effect=download) as fetch:
                self.assertIsNone(runner._restore_exact_korea_parent_image(parent, "top"))
                self.assertIsNone(runner._restore_exact_korea_parent_image({}, "bottom"))
                self.assertEqual(fetch.call_count, 1)

    def test_operator_correction_reaches_actual_generation_caller_without_mutating_source(self):
        prompt_input = {"program_id": "keysuri_korea_tech", "source_pack": {"preserved": True}}
        original = copy.deepcopy(prompt_input)
        caller = Mock(return_value="generated JSON")

        def generate(value, *, gemini_caller):
            self.assertEqual(value, original)
            return gemini_caller("ORIGINAL SAFETY AND SOURCE CONTRACT", program_id="keysuri_korea_tech"), {}

        with patch.object(runner, "_regen_prompt_input_from_parent", return_value=(prompt_input, None)), \
             patch.object(runner, "generate_keysuri_body_raw_text", side_effect=generate), \
             patch.object(runner, "parse_keysuri_generated_response", return_value={"parse_status": "parsed_valid", "generated_briefing": {"top_5_news": {}}}), \
             patch.object(runner, "enrich_generated_briefing_content", side_effect=lambda value, *_: value), \
             patch.object(runner, "repair_keysuri_visible_text_fields", side_effect=lambda value, **_: (value, {})):
            _, _, error = runner._regenerate_keysuri_text_from_snapshot(
                {}, "keysuri_korea_tech", text_caller=caller,
                editorial_instruction="사전등록 520명, 현장 포함 750명 이상 예상으로 고칩니다.",
            )
        self.assertIsNone(error)
        sent = caller.call_args.args[0]
        self.assertIn("ORIGINAL SAFETY AND SOURCE CONTRACT", sent)
        self.assertIn("750명 이상 예상", sent)
        self.assertIn("grants no delivery", sent)
        self.assertEqual(prompt_input, original)

    def test_no_instruction_keeps_existing_caller_contract(self):
        source = Path(runner.__file__).read_text()
        self.assertIn('if reissue_reason_note else {}', source)
        self.assertIn('if editorial_instruction else {}', source)

    def test_exact_parent_image_bytes_preserve_generated_identity_not_send_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"bottom.jpg";path.write_bytes(b"exact image")
            parent = {"bottom_image_cid": "bottom", "bottom_shot_source": "generated_v6_multi_ref",
                      "bottom_anchor_asset_id": "keysuri_korea_bottom_20260605_105936", "bottom_anchor_slot": 0,
                      "secondary_reference_asset_id": "Asset01", "secondary_reference_slot": 1,
                      "bottom_shot_generated": True, "owner_review_status": "approved", "customer_send": 14,
                      "owner_email_inline_image_hashes": [{"cid": "bottom", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]}
            before=copy.deepcopy(parent)
            result,error=runner._preserved_korea_bottom_identity(parent,path)
            self.assertIsNone(error)
            self.assertEqual(result["bottom_shot_source"], "generated_v6_multi_ref")
            self.assertEqual(result["bottom_anchor_slot"],0)
            self.assertNotIn("owner_review_status", result)
            self.assertNotIn("customer_send", result)
            self.assertEqual(parent,before)

    def test_image_byte_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"bottom.jpg";path.write_bytes(b"changed")
            parent={"bottom_image_cid":"bottom","bottom_shot_source":"generated_v6_multi_ref",
                    "owner_email_inline_image_hashes":[{"cid":"bottom","sha256":"0"*64}]}
            result,error=runner._preserved_korea_bottom_identity(parent,path)
            self.assertEqual(result,{})
            self.assertEqual(error,"text_only_reissue_bottom_image_hash_mismatch")

    def test_missing_provenance_cannot_invent_approved_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"bottom.jpg";path.write_bytes(b"unknown")
            result,error=runner._preserved_korea_bottom_identity({"bottom_shot_source":"generated_v6_multi_ref"},path)
            self.assertEqual(result,{})
            self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
