"""Tests for Kee-Suri top image safety + diversity variation (offline, no image API)."""
from __future__ import annotations

import re
import unittest

from keysuri_top_image_variation import (
    CAMERA_VARIANTS,
    GLOBAL_PROP_VARIANTS,
    KOREA_PROP_VARIANTS,
    OUTFIT_VARIANTS,
    POSE_VARIANTS,
    PROGRAM_VISUAL_CONTEXT,
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
            self.assertIn("viewer, who remains off-camera", pos)
            self.assertIn("only visible human subject", pos)
            self.assertIn("private", pos)
            self.assertIn("briefing", pos)

    def test_consultation_second_person_drift_phrase_absent(self) -> None:
        forbidden = (
            "private briefing to one person",
            "briefing to one person",
            "turned toward the viewer as if briefing one person",
        )
        for build in (_global, _korea):
            pos = build()["positive_prompt"].lower()
            for phrase in forbidden:
                self.assertNotIn(phrase, pos)

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

    def test_global_context_avoids_weather_cloud_icon_cues(self) -> None:
        text = PROGRAM_VISUAL_CONTEXT["keysuri_global_tech"].lower()
        for forbidden in (
            "cloud diagram",
            "cloud icon",
            "cloud cue",
            "cloud silhouette",
            "weather icon",
            "weather-like symbols",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn("distributed computing infrastructure", text)
        self.assertIn("no forecast-style symbols", text)

    def test_no_readable_company_or_policy_text_instruction(self) -> None:
        for build in (_global, _korea):
            pos = build()["positive_prompt"].lower()
            self.assertIn("no readable real", pos)


class ProgramPropRuleTests(unittest.TestCase):
    def test_global_props_are_all_tablet(self) -> None:
        for _id, clause in GLOBAL_PROP_VARIANTS:
            self.assertIn("tablet", clause.lower())

    def test_korea_props_have_no_tablet(self) -> None:
        for _id, clause in KOREA_PROP_VARIANTS:
            self.assertNotIn("tablet", clause.lower())

    def test_global_final_prompt_always_has_tablet(self) -> None:
        for d in range(1, 13):
            pos = _global(date=f"2026-06-{d:02d}", headline=f"h{d}")["positive_prompt"].lower()
            self.assertIn("tablet", pos)

    def test_korea_final_prompt_has_domestic_non_tablet_prop(self) -> None:
        markers = ("notebook", "briefing cards", "laptop", "phone and a memo", "briefing board")
        for d in range(1, 13):
            built = _korea(date=f"2026-06-{d:02d}", headline=f"h{d}")
            self.assertEqual(built["final_prompt_validation_status"], "pass")
            # Korea prop (outside the reference-separation paragraph) must not be a tablet.
            from keysuri_weather_visual_prompt_integration import _PRODUCTION_TOP_IMAGE_REFERENCE
            scan = built["positive_prompt"].lower().replace(_PRODUCTION_TOP_IMAGE_REFERENCE.lower(), " ")
            self.assertNotIn("tablet", scan)
            self.assertTrue(any(m in scan for m in markers))

    def test_global_korea_prop_sets_disjoint(self) -> None:
        g = {pid for pid, _ in GLOBAL_PROP_VARIANTS}
        k = {pid for pid, _ in KOREA_PROP_VARIANTS}
        self.assertEqual(g & k, set())


class ImageFamilyConsistencyTests(unittest.TestCase):
    def test_assistant_role_pose_catalog_has_no_executive_seat(self) -> None:
        pose_ids = {pid for pid, _ in POSE_VARIANTS}
        self.assertNotIn("pose_seated_desk", pose_ids)
        joined = " ".join(clause for _pid, clause in POSE_VARIANTS).lower()
        for forbidden in (
            "seated behind the main executive desk",
            "sitting in the boss chair",
            "executive chair pose",
            "ceo office portrait",
            "boardroom authority pose",
        ):
            self.assertNotIn(forbidden, joined)
        self.assertIn("assistant-side briefing table", joined)
        self.assertIn("prepared for an off-camera viewer", joined)
        self.assertIn("not behind the main desk", joined)
        self.assertIn("not in an executive chair", joined)

    def test_camera_catalog_avoids_authority_angle(self) -> None:
        camera_ids = {cid for cid, _ in CAMERA_VARIANTS}
        self.assertNotIn("cam_three_quarter_above", camera_ids)
        joined = " ".join(clause for _cid, clause in CAMERA_VARIANTS).lower()
        self.assertIn("neutral eye level", joined)
        self.assertIn("no authority angle", joined)

    def test_style_family_lock_shared_by_both_programs(self) -> None:
        required = (
            "consistent premium photorealistic editorial style",
            "natural realistic skin texture",
            "clean korean premium tech briefing brand look",
            "same restrained contrast and polished office lighting family",
            "realistic lens",
            "no beauty-ad gloss",
            "no fashion editorial texture",
            "no cinematic poster look",
            "no casual stock-photo look",
            "no anime",
            "no illustration",
            "no plastic skin",
            "no over-saturated color grading",
            "no random style shift between runs",
        )
        for build in (_global, _korea):
            pos = build()["positive_prompt"].lower()
            for phrase in required:
                self.assertIn(phrase, pos)

    def test_weather_icon_negatives_required(self) -> None:
        required = (
            "no weather icons",
            "no cloud weather symbol",
            "no sun/rain/cloud forecast icon",
            "no weather app ui",
            "no meteorological dashboard",
            "no tomorrow genie weather mood",
        )
        for build in (_global, _korea):
            neg = build()["negative_prompt"].lower()
            for phrase in required:
                self.assertIn(phrase, neg)

    def test_consultation_negatives_required(self) -> None:
        required = (
            "no second person visible",
            "no client consultation scene",
            "no advisor-client meeting",
            "no interview table composition",
            "no customer sitting across from her",
            "no over-the-shoulder attendee",
            "no back of another person's head",
            "no visible listener",
            "no meeting counterpart",
            "no counseling session mood",
        )
        for build in (_global, _korea):
            neg = build()["negative_prompt"].lower()
            for phrase in required:
                self.assertIn(phrase, neg)

    def test_final_prompt_avoids_weather_icon_invitation(self) -> None:
        forbidden = (
            "cloud diagram",
            "cloud cue",
            "cloud silhouette",
            "weather icon",
            "weather app ui",
            "meteorological dashboard",
            "tomorrow genie weather mood",
        )
        for build in (_global, _korea):
            pos = build()["positive_prompt"].lower()
            for phrase in forbidden:
                self.assertNotIn(phrase, pos)

    def test_validator_blocks_executive_pose_and_weather_icon(self) -> None:
        built = _global()
        issues = validate_keysuri_final_top_image_prompt(
            "keysuri_global_tech",
            built["positive_prompt"] + " seated behind the main executive desk with a cloud icon.",
            built["negative_prompt"],
        )
        codes = {i["code"] for i in issues}
        self.assertIn("executive_boss_pose_present", codes)
        self.assertIn("weather_cloud_icon_present", codes)


class ReferenceSeparationTests(unittest.TestCase):
    def test_identity_only_and_do_not_preserve_present(self) -> None:
        for build in (_global, _korea):
            pos = build()["positive_prompt"].lower()
            self.assertIn("only for facial identity", pos)
            self.assertIn("do not preserve the reference outfit", pos)
            self.assertIn("same person does not mean same wardrobe", pos)

    def test_no_wardrobe_continuity_in_final_prompt(self) -> None:
        for build in (_global, _korea):
            built = build()
            self.assertEqual(built["final_prompt_validation_status"], "pass")
            from keysuri_weather_visual_prompt_integration import _PRODUCTION_TOP_IMAGE_REFERENCE
            scan = built["positive_prompt"].lower().replace(_PRODUCTION_TOP_IMAGE_REFERENCE.lower(), " ")
            self.assertNotIn("wardrobe continuity", scan)
            self.assertNotIn("outfit continuity", scan)

    def test_old_office_monitor_stem_absent(self) -> None:
        for build in (_global, _korea):
            pos = build()["positive_prompt"].lower()
            self.assertNotIn("desk and monitor with abstract non-readable charts", pos)

    def test_validator_blocks_reintroduced_continuity(self) -> None:
        built = _global()
        tampered = built["positive_prompt"] + " keep the same office and wardrobe continuity."
        issues = validate_keysuri_final_top_image_prompt(
            "keysuri_global_tech", tampered, built["negative_prompt"]
        )
        codes = {i["code"] for i in issues}
        self.assertIn("reference_wardrobe_continuity_present", codes)

    def test_validator_blocks_reintroduced_office_stem(self) -> None:
        built = _korea()
        tampered = built["positive_prompt"] + " Premium private office with large windows, desk and monitor with abstract non-readable charts."
        issues = validate_keysuri_final_top_image_prompt(
            "keysuri_korea_tech", tampered, built["negative_prompt"]
        )
        codes = {i["code"] for i in issues}
        self.assertIn("old_office_monitor_stem_present", codes)


class PromptFamilyTests(unittest.TestCase):
    """Verify the prompt family (Global 6 + Korea 6) BEFORE any image API call."""

    def _family(self, build, n=6):
        rows = []
        for d in range(1, n + 1):
            r = build(date=f"2026-06-{d:02d}", headline=f"signal-{d}")
            v = r["variation"]
            rows.append((
                v["top_image_wardrobe_variant"], v["top_image_pose_variant"],
                v["top_image_prop_variant"], v["top_image_background_variant"],
                r["final_prompt_validation_status"],
            ))
        return rows

    def test_global_family_diverse_and_valid(self) -> None:
        rows = self._family(_global)
        self.assertTrue(all(r[4] == "pass" for r in rows))
        self.assertGreaterEqual(len({r[0] for r in rows}), 3)  # >=3 distinct outfits
        self.assertTrue(all(r[2].startswith("gprop_") for r in rows))

    def test_korea_family_diverse_and_valid(self) -> None:
        rows = self._family(_korea)
        self.assertTrue(all(r[4] == "pass" for r in rows))
        self.assertGreaterEqual(len({r[0] for r in rows}), 3)
        self.assertTrue(all(r[2].startswith("kprop_") for r in rows))

    def test_no_old_single_charcoal_clause_forced(self) -> None:
        for build in (_global, _korea):
            for d in range(1, 13):
                pos = build(date=f"2026-06-{d:02d}")["positive_prompt"].lower()
                self.assertNotIn("charcoal fitted suit, ivory or soft cream blouse, pencil skirt", pos)


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
            "a charcoal fitted suit with an ivory blouse, private "
            "briefing, tech secretary",
            "no readable text overlay, no age label, not a public news anchor, "
            "not a weathercaster, no fashion model styling, no second person visible, "
            "no client consultation scene, no over-the-shoulder attendee, "
            "no customer sitting across from her, no back of another person's head",
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

    def test_validator_blocks_consultation_second_person_drift(self) -> None:
        built = _korea()
        tampered = (
            built["positive_prompt"]
            + " She is turned toward the viewer as if briefing one person in a client consultation scene."
        )
        issues = validate_keysuri_final_top_image_prompt(
            "keysuri_korea_tech", tampered, built["negative_prompt"]
        )
        codes = {i["code"] for i in issues}
        self.assertIn("consultation_second_person_drift_present", codes)


class HairTextureLockTests(unittest.TestCase):
    """Verify that the Hair + Texture Identity Lock patch phrases survive
    the full prompt-build pipeline for both KeeSuri programs."""

    def test_hair_lock_phrases_in_top_image_prompt(self) -> None:
        for build in (_global, _korea):
            pos = build()["positive_prompt"].lower()
            self.assertIn("same sleek chin-length bob silhouette", pos)
            self.assertIn("same side-parted compact bob", pos)
            self.assertIn("smooth inward-folding ends", pos)

    def test_assistant_side_composition_in_top_image(self) -> None:
        for build in (_global, _korea):
            pos = build()["positive_prompt"].lower()
            self.assertIn("assistant-side composition", pos)
            self.assertIn("viewer, who remains off-camera", pos)
            self.assertIn("only visible human subject", pos)

    def test_hair_drift_guard_in_negative_prompt(self) -> None:
        for build in (_global, _korea):
            neg = build()["negative_prompt"].lower()
            self.assertIn("no long bob", neg)
            self.assertIn("no different haircut", neg)
            self.assertIn("no hairstyle change between top and bottom images", neg)

    def test_role_drift_guard_in_negative_prompt(self) -> None:
        for build in (_global, _korea):
            neg = build()["negative_prompt"].lower()
            self.assertIn("no ceo office portrait", neg)
            self.assertIn("no boss desk composition", neg)
            self.assertIn("no second person visible", neg)
            self.assertIn("no client consultation scene", neg)

    def test_clean_final_prompt_passes_with_hair_lock(self) -> None:
        for build in (_global, _korea):
            built = build()
            self.assertEqual(built["final_prompt_validation_status"], "pass")
            self.assertEqual(built["final_prompt_validation_issues"], [])


if __name__ == "__main__":
    unittest.main()
