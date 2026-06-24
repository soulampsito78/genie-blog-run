"""Tests for Kee-Suri top image safety + diversity variation (offline, no image API)."""
from __future__ import annotations

import re
import unittest

from keysuri_top_image_variation import (
    OUTFIT_VARIANTS,
    PROP_VARIANTS,
    SIDE_EFFECTS_DISABLED,
    build_top_image_diversity_seed,
    resolve_keysuri_top_image_variation,
)
from keysuri_weather_visual_prompt_integration import (
    REQUIRED_NEGATIVE_PHRASES,
    build_keysuri_production_top_image_prompt,
    validate_keysuri_final_top_image_prompt,
)

_AGE_PATTERNS = (
    "late 20s",
    "late twenties",
    "mature professional age",
    "30s",
    "thirties",
    "mid-to-late",
)
_FORBIDDEN_ROLE_PATTERNS = (
    "ceo",
    "chairwoman",
    "senior executive",
    "fashion model",
)


def _global(**kw) -> dict:
    return build_keysuri_production_top_image_prompt(
        "keysuri_global_tech",
        run_date_kst=kw.get("date", "2026-06-24"),
        subject_top_headline=kw.get("headline", "엔비디아와 AWS 협력 강화"),
    )


def _korea(**kw) -> dict:
    return build_keysuri_production_top_image_prompt(
        "keysuri_korea_tech",
        run_date_kst=kw.get("date", "2026-06-24"),
        subject_top_headline=kw.get("headline", "국내 AI 스타트업 정책 변화"),
    )


class ProductionPromptPathTests(unittest.TestCase):
    def test_production_uses_integration_module_not_fallback(self) -> None:
        # The gate path replaces the static snapshot with the diversified prompt.
        from keysuri_image_api_canary_client import DEFAULT_LOCK_PATH, _gate_prompt_source

        src, issues, ready = _gate_prompt_source(
            DEFAULT_LOCK_PATH,
            "keysuri_global_tech",
            manual_approval_for_gate=True,
            run_date_kst="2026-06-24",
            subject_top_headline="엔비디아와 AWS 협력 강화",
        )
        self.assertTrue(ready)
        self.assertTrue(src.get("prompt_diversified"))
        self.assertIn("top_image_variation", src)
        # The diversified prompt is identity-locked KeeSuri, not the old fallback.
        self.assertIn("kee-suri", src["positive_prompt"].lower())

    def test_gate_without_date_keeps_static_snapshot(self) -> None:
        from keysuri_image_api_canary_client import DEFAULT_LOCK_PATH, _gate_prompt_source

        src, _issues, ready = _gate_prompt_source(
            DEFAULT_LOCK_PATH,
            "keysuri_global_tech",
            manual_approval_for_gate=True,
        )
        self.assertTrue(ready)
        self.assertNotIn("prompt_diversified", src)


class WardrobeInjectionTests(unittest.TestCase):
    def test_daily_wardrobe_snippet_in_both_programs(self) -> None:
        g = _global()["positive_prompt"].lower()
        k = _korea()["positive_prompt"].lower()
        allowed_clauses = [clause.lower() for _id, clause in OUTFIT_VARIANTS]
        self.assertTrue(any(c in g for c in allowed_clauses))
        self.assertTrue(any(c in k for c in allowed_clauses))

    def test_single_charcoal_clause_not_always_forced(self) -> None:
        # Across many dates the outfit must not be the static charcoal lock every day.
        outfits = set()
        for day in range(1, 26):
            date = f"2026-06-{day:02d}"
            outfits.add(_global(date=date)["variation"]["top_image_wardrobe_variant"])
        self.assertGreater(len(outfits), 1)
        # The exact old static single clause is not hard-forced into every prompt.
        forced = 0
        for day in range(1, 26):
            pos = _global(date=f"2026-06-{day:02d}")["positive_prompt"].lower()
            if "a charcoal fitted suit with an ivory blouse" in pos:
                forced += 1
        self.assertLess(forced, 25)


class IdentitySafetyTests(unittest.TestCase):
    def test_no_age_phrases_in_prompt(self) -> None:
        for build in (_global, _korea):
            blob = (
                build()["positive_prompt"] + " " + build()["negative_prompt"]
            ).lower()
            for pat in _AGE_PATTERNS:
                self.assertNotIn(pat, blob, msg=f"age phrase leaked: {pat!r}")

    def test_no_forbidden_role_unnegated(self) -> None:
        # Forbidden roles may appear ONLY inside the explicit negation clause.
        negation_clause = "not a ceo or chairwoman or senior executive"
        for build in (_global, _korea):
            pos = build()["positive_prompt"].lower()
            self.assertIn(negation_clause, pos)
            stripped = pos.replace(negation_clause, "").replace("not a fashion model", "")
            for role in _FORBIDDEN_ROLE_PATTERNS:
                self.assertNotIn(role, stripped, msg=f"unnegated forbidden role {role!r}")

    def test_identity_lock_preserved(self) -> None:
        for build in (_global, _korea):
            pos = build()["positive_prompt"].lower()
            self.assertIn("same person as the reference", pos)
            self.assertIn("sleek short bob", pos)
            self.assertIn("thin metal glasses", pos)
            self.assertIn("private", pos)
            self.assertIn("briefing", pos)

    def test_no_wardrobe_drift_softened(self) -> None:
        self.assertNotIn("no wardrobe drift", [p.lower() for p in REQUIRED_NEGATIVE_PHRASES])
        for build in (_global, _korea):
            self.assertNotIn("no wardrobe drift", build()["negative_prompt"].lower())

    def test_no_readable_text_negative_retained(self) -> None:
        for build in (_global, _korea):
            neg = build()["negative_prompt"].lower()
            self.assertIn("no readable text overlay", neg)


class DeterminismTests(unittest.TestCase):
    def test_same_input_deterministic(self) -> None:
        a = _global(date="2026-06-24", headline="signal A")
        b = _global(date="2026-06-24", headline="signal A")
        self.assertEqual(a["positive_prompt"], b["positive_prompt"])
        self.assertEqual(a["variation"], b["variation"])

    def test_different_date_can_change_variant(self) -> None:
        summaries = {
            _global(date=f"2026-06-{d:02d}")["variation"]["top_image_prompt_variant_summary"]
            for d in range(1, 16)
        }
        self.assertGreater(len(summaries), 1)

    def test_different_program_seed_differs(self) -> None:
        g_seed = build_top_image_diversity_seed(
            "keysuri_global_tech", "2026-06-24", "same headline"
        )
        k_seed = build_top_image_diversity_seed(
            "keysuri_korea_tech", "2026-06-24", "same headline"
        )
        self.assertNotEqual(g_seed, k_seed)

    def test_different_headline_changes_seed(self) -> None:
        s1 = build_top_image_diversity_seed("keysuri_global_tech", "2026-06-24", "alpha")
        s2 = build_top_image_diversity_seed("keysuri_global_tech", "2026-06-24", "beta")
        self.assertNotEqual(s1, s2)


class GlobalKoreaSeparationTests(unittest.TestCase):
    def test_program_visual_context_distinct(self) -> None:
        g = _global()["positive_prompt"].lower()
        k = _korea()["positive_prompt"].lower()
        self.assertIn("global big-tech", g)
        self.assertIn("data-center", g)
        self.assertIn("korean tech-ecosystem", k)
        self.assertIn("seoul", k)
        self.assertNotIn("korean tech-ecosystem", g)
        self.assertNotIn("global big-tech", k)

    def test_no_readable_company_or_policy_text_instruction(self) -> None:
        for build in (_global, _korea):
            pos = build()["positive_prompt"].lower()
            self.assertIn("no readable real", pos)


class PropVariantTests(unittest.TestCase):
    def test_tablet_not_mandatory(self) -> None:
        prop_ids = {pid for pid, _clause in PROP_VARIANTS}
        self.assertIn("prop_none_hands_desk", prop_ids)
        self.assertIn("prop_briefing_folder", prop_ids)
        # Across dates at least one non-tablet prop is selected for Global.
        chosen = {
            _global(date=f"2026-06-{d:02d}")["variation"]["top_image_prop_variant"]
            for d in range(1, 26)
        }
        self.assertTrue(chosen - {"prop_slim_tablet"})


class MetadataTests(unittest.TestCase):
    def test_metadata_fields_present_and_safe(self) -> None:
        meta = _global(headline="시크릿 없는 헤드라인")["variation"]
        for key in (
            "top_image_identity_lock",
            "top_image_wardrobe_variant",
            "top_image_pose_variant",
            "top_image_prop_variant",
            "top_image_background_variant",
            "top_image_camera_variant",
            "top_image_lighting_variant",
            "top_image_program_visual_context",
            "top_image_subject_cue",
            "top_image_diversity_seed_hash",
            "top_image_prompt_variant_summary",
        ):
            self.assertIn(key, meta)
        # seed hash only, never the raw headline text
        self.assertRegex(meta["top_image_diversity_seed_hash"], r"^[0-9a-f]{64}$")
        self.assertNotIn("헤드라인", str(meta))

    def test_side_effects_disabled(self) -> None:
        self.assertFalse(any(SIDE_EFFECTS_DISABLED.values()))


class FinalPromptGateSafetyTests(unittest.TestCase):
    def test_clean_final_prompt_passes(self) -> None:
        for build in (_global, _korea):
            built = build()
            self.assertEqual(built["final_prompt_validation_status"], "pass")
            self.assertEqual(built["final_prompt_validation_issues"], [])

    def test_forbidden_age_in_final_prompt_fails(self) -> None:
        built = _global()
        tampered = built["positive_prompt"] + " She is in her late 20s."
        issues = validate_keysuri_final_top_image_prompt(
            "keysuri_global_tech", tampered, built["negative_prompt"]
        )
        codes = {i["code"] for i in issues}
        self.assertIn("final_age_label_present", codes)

    def test_forbidden_role_in_final_prompt_fails(self) -> None:
        built = _korea()
        tampered = built["positive_prompt"] + " She is a powerful CEO chairwoman."
        issues = validate_keysuri_final_top_image_prompt(
            "keysuri_korea_tech", tampered, built["negative_prompt"]
        )
        codes = {i["code"] for i in issues}
        self.assertIn("final_forbidden_role_unnegated", codes)

    def test_missing_identity_lock_fails(self) -> None:
        issues = validate_keysuri_final_top_image_prompt(
            "keysuri_global_tech",
            "a woman in an office, global big-tech, no readable real text, "
            "a charcoal fitted suit with an ivory blouse, one-person private "
            "briefing, tech secretary",
            "no readable text overlay, no age label, not a public news anchor, "
            "not a weathercaster, no fashion model styling",
        )
        codes = {i["code"] for i in issues}
        # missing "same person as the reference" / "sleek short bob" / "thin metal glasses"
        self.assertIn("final_positive_phrase_missing", codes)

    def test_readable_text_negative_required_in_final(self) -> None:
        built = _global()
        issues = validate_keysuri_final_top_image_prompt(
            "keysuri_global_tech", built["positive_prompt"], "no collage"
        )
        codes = {i["code"] for i in issues}
        self.assertIn("final_negative_phrase_missing", codes)

    def test_gate_blocks_when_final_prompt_fails(self) -> None:
        # static design snapshot passes, but a tampered diversified final prompt
        # must drive the whole gate result to fail (gate_ready False).
        import keysuri_image_api_canary_client as cc
        from keysuri_image_api_canary_client import DEFAULT_LOCK_PATH, _gate_prompt_source

        def _bad_builder(program_id, *, run_date_kst, subject_top_headline="", palette_version="v1"):
            return {
                "program_id": program_id,
                "positive_prompt": "public news anchor, mature professional age, on tv",
                "negative_prompt": "no collage",
                "variation": {"top_image_final_prompt_validation_status": "block"},
                "final_prompt_validation_status": "block",
                "final_prompt_validation_issues": [
                    {"code": "final_age_label_present", "message": "x"}
                ],
            }

        import keysuri_weather_visual_prompt_integration as integ

        original = integ.build_keysuri_production_top_image_prompt
        integ.build_keysuri_production_top_image_prompt = _bad_builder
        try:
            src, issues, ready = _gate_prompt_source(
                DEFAULT_LOCK_PATH,
                "keysuri_global_tech",
                manual_approval_for_gate=True,
                run_date_kst="2026-06-24",
                subject_top_headline="x",
            )
        finally:
            integ.build_keysuri_production_top_image_prompt = original

        self.assertFalse(ready)
        self.assertEqual(src["final_prompt_validation_status"], "block")
        self.assertTrue(any(i.get("code") == "final_age_label_present" for i in issues))

    def test_gate_final_prompt_matches_builder_output(self) -> None:
        from keysuri_image_api_canary_client import DEFAULT_LOCK_PATH, _gate_prompt_source

        built = build_keysuri_production_top_image_prompt(
            "keysuri_global_tech",
            run_date_kst="2026-06-24",
            subject_top_headline="엔비디아와 AWS",
        )
        src, _issues, ready = _gate_prompt_source(
            DEFAULT_LOCK_PATH,
            "keysuri_global_tech",
            manual_approval_for_gate=True,
            run_date_kst="2026-06-24",
            subject_top_headline="엔비디아와 AWS",
        )
        self.assertTrue(ready)
        self.assertEqual(src["positive_prompt"], built["positive_prompt"])
        self.assertEqual(src["negative_prompt"], built["negative_prompt"])
        self.assertEqual(src["final_prompt_validation_status"], "pass")

    def test_image_fn_uses_validated_final_prompt(self) -> None:
        # The prompt sent to the image API equals the validated diversified prompt.
        from unittest import mock

        import keysuri_service_full_run as svc
        from service_full_run_contract import ServiceImageOutcome

        built = build_keysuri_production_top_image_prompt(
            "keysuri_global_tech",
            run_date_kst="2026-06-24",
            subject_top_headline="",
        )
        captured = {}

        def _fake_invoke(*, prompt, output_path, reference_image_path, generate_fn=None):
            captured["prompt"] = prompt
            return ServiceImageOutcome(
                called_image_api=True,
                image_generation_status="generated",
                image_source="generated",
                generated_image_path="output/x.jpg",
            )

        with mock.patch.object(svc, "invoke_vertex_image_generation", _fake_invoke):
            outcome = svc._generate_keysuri_service_image(
                "keysuri_global_tech",
                run_id="20260624_151504_keysuri_global_tech_abc",
                subject_top_headline="",
            )
        self.assertTrue(outcome.called_image_api)
        self.assertIn(built["positive_prompt"], captured["prompt"])
        self.assertIn(built["negative_prompt"], captured["prompt"])

    def test_image_fn_blocks_on_final_validation_failure(self) -> None:
        from unittest import mock

        import keysuri_image_api_canary_client as cc
        import keysuri_service_full_run as svc

        def _bad_gate(*a, **k):
            return (
                {
                    "final_prompt_validation_status": "block",
                    "final_prompt_validation_issues": [
                        {"code": "final_age_label_present"}
                    ],
                },
                [],
                False,
            )

        called = {"invoke": False}

        def _should_not_invoke(**k):
            called["invoke"] = True
            raise AssertionError("image API must not be called when final prompt blocks")

        with mock.patch.object(cc, "_gate_prompt_source", _bad_gate), mock.patch.object(
            svc, "invoke_vertex_image_generation", _should_not_invoke
        ):
            outcome = svc._generate_keysuri_service_image(
                "keysuri_global_tech",
                run_id="20260624_151504_keysuri_global_tech_abc",
                subject_top_headline="",
            )
        self.assertFalse(outcome.ok)
        self.assertIn("final_prompt_validation_failed", str(outcome.error_message))
        self.assertFalse(called["invoke"])

    def test_both_programs_final_validated_metadata(self) -> None:
        for build in (_global, _korea):
            meta = build()["variation"]
            self.assertTrue(meta["top_image_final_prompt_validated"])
            self.assertEqual(meta["top_image_final_prompt_validation_status"], "pass")
            self.assertEqual(meta["top_image_final_prompt_validation_issues"], [])


if __name__ == "__main__":
    unittest.main()
