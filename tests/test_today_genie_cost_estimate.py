"""Tests for Today_Geenee/Tomorrow_Geenee cost-estimate wiring in main.py.

Covers the parts genie_cost_estimate.py cannot: usage accumulation across
main.py's two-phase today_genie text pipeline, and that a usage_sink failure
never breaks generation.
"""
from __future__ import annotations

import unittest
from unittest import mock

import main


class SumUsageSinksTests(unittest.TestCase):
    def test_sums_numeric_fields_across_sinks(self) -> None:
        ext = {"model": "gemini-2.5-flash", "prompt_token_count": 1000, "candidates_token_count": 200}
        main_sink = {"model": "gemini-2.5-flash", "prompt_token_count": 3000, "candidates_token_count": 700}
        combined = main._sum_usage_sinks(ext, main_sink)
        self.assertEqual(combined["prompt_token_count"], 4000)
        self.assertEqual(combined["candidates_token_count"], 900)
        self.assertEqual(combined["model"], "gemini-2.5-flash")

    def test_missing_fields_treated_as_zero(self) -> None:
        ext = {"model": "m", "prompt_token_count": 100}
        main_sink = {"model": "m", "candidates_token_count": 50}
        combined = main._sum_usage_sinks(ext, main_sink)
        self.assertEqual(combined["prompt_token_count"], 100)
        self.assertEqual(combined["candidates_token_count"], 50)

    def test_empty_sinks_return_empty_dict(self) -> None:
        self.assertEqual(main._sum_usage_sinks({}, {}), {})

    def test_non_dict_inputs_do_not_raise(self) -> None:
        combined = main._sum_usage_sinks(None, {"prompt_token_count": 5, "model": "m"})
        self.assertEqual(combined["prompt_token_count"], 5)


class TodayGenieTextPipelineUsageTests(unittest.TestCase):
    """Reproduces the two-phase today_genie call sequence (extraction + main
    briefing) and asserts usage accumulates across both calls."""

    def test_usage_accumulates_across_both_phases(self) -> None:
        ext_usage = {"model": "gemini-2.5-flash", "prompt_token_count": 500, "candidates_token_count": 100}
        main_usage = {"model": "gemini-2.5-flash", "prompt_token_count": 4000, "candidates_token_count": 900, "thoughts_token_count": 200}

        def _fake_call_gemini(prompt, mode, *, max_output_tokens=None, usage_sink=None):
            if usage_sink is not None:
                if max_output_tokens == 4096:
                    usage_sink.update(ext_usage)
                    return '{"top3": []}'
                usage_sink.update(main_usage)
            return '{"title": "t", "summary": "s"}'

        with mock.patch("main.call_gemini", side_effect=_fake_call_gemini), mock.patch(
            "main.build_top3_extraction_prompt", return_value="ext-prompt"
        ), mock.patch("main.build_full_prompt", return_value="main-prompt"), mock.patch(
            "main.normalize_top3_slots_payload", return_value={"slots": []}
        ), mock.patch(
            "main.assemble_key_watchpoints_from_slots", return_value=[]
        ), mock.patch("main.apply_briefing_repetition_guard", return_value=None):
            data, raw_main, prof, usage = main.run_today_genie_text_pipeline({})

        self.assertEqual(usage["prompt_token_count"], 4500)
        self.assertEqual(usage["candidates_token_count"], 1000)
        self.assertEqual(usage["thoughts_token_count"], 200)
        self.assertEqual(usage["model"], "gemini-2.5-flash")
        self.assertIn("top3_extract_inference_sec", prof)
        self.assertIn("main_brief_inference_sec", prof)

    def test_usage_sink_populate_failure_does_not_break_call_gemini(self) -> None:
        """A usage_sink that raises on assignment must not prevent text from
        being returned — mirrors the KeeSuri gemini client's same guarantee."""

        class _BrokenSink(dict):
            def __setitem__(self, key, value):
                raise RuntimeError("sink is broken")

        fake_response = mock.MagicMock()
        fake_response.text = '{"ok": true}'
        fake_response.usage_metadata = None

        with mock.patch("main.init_vertex"), mock.patch("main.get_model") as mock_get_model:
            mock_get_model.return_value.generate_content.return_value = fake_response
            text = main.call_gemini("prompt", "today_genie", usage_sink=_BrokenSink())
        self.assertEqual(text, '{"ok": true}')


if __name__ == "__main__":
    unittest.main()
