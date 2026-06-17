"""Tests for Key-Suri bottom-shot prompt builder (Contract v6 — 105936 anchor patch).

Verifies:
- 105936 is primary Bottom visual anchor (not direction reference)
- Asset01 is secondary same-person continuity reference
- Weather still drives wardrobe selection across 6 closet variants
- All wardrobe variants stay inside 105936 premium closet family
- v6 persona: private AI secretary, composed smile, handbag, owner-facing exclusivity
- Noble sensuality framing preserved; age-risk text removed from identity gene
- Backward-compatible metadata_only return keys for service_full_run
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from keysuri_bottom_shot_prompt_builder import (
    ASSET01_PATH,
    ASSET01_ROLE,
    BOTTOM_ANCHOR_PATH,
    BOTTOM_ANCHOR_ROLE,
    FIXED_CAMERA_GENE,
    FIXED_EXPRESSION_GENE,
    FIXED_IDENTITY_GENE,
    FIXED_PROP_GESTURE_GENE,
    FIXED_ROLE_SCENE_GENE,
    NEGATIVE_PROMPT_V6,
    build_bottom_shot_prompt,
    build_bottom_shot_prompt_metadata_only,
)


def _build(weather_condition="cloudy", temperature_c=None, season=None,
           program_id="keysuri_korea_tech", taste_cluster=None):
    return build_bottom_shot_prompt(
        weather_condition=weather_condition,
        temperature_c=temperature_c,
        season=season,
        program_id=program_id,
        taste_cluster=taste_cluster,
    )


# ===================================================================
# Anchor Role — 105936 is primary Bottom anchor, Asset01 is secondary
# ===================================================================

class AnchorRoleTests(unittest.TestCase):

    def test_bottom_anchor_path_contains_105936(self):
        self.assertIn("105936", BOTTOM_ANCHOR_PATH)

    def test_bottom_anchor_role_is_primary(self):
        self.assertEqual(BOTTOM_ANCHOR_ROLE, "primary_bottom_visual_anchor")

    def test_asset01_role_is_secondary(self):
        self.assertEqual(ASSET01_ROLE, "secondary_same_person_continuity_reference")

    def test_reference_assets_has_primary_bottom_anchor(self):
        refs = _build()["reference_assets"]
        self.assertIn("primary_bottom_anchor", refs)
        self.assertEqual(refs["primary_bottom_anchor"]["role"], BOTTOM_ANCHOR_ROLE)
        self.assertEqual(refs["primary_bottom_anchor"]["path"], BOTTOM_ANCHOR_PATH)

    def test_reference_assets_has_secondary_continuity(self):
        refs = _build()["reference_assets"]
        self.assertIn("secondary_continuity_reference", refs)
        self.assertEqual(refs["secondary_continuity_reference"]["role"], ASSET01_ROLE)
        self.assertEqual(refs["secondary_continuity_reference"]["path"], ASSET01_PATH)

    def test_105936_is_not_direction_reference_only(self):
        # Old "direction reference only" designation is retired
        refs = _build()["reference_assets"]
        roles = [v.get("role", "") for v in refs.values()]
        self.assertNotIn("direction_reference_only", roles)

    def test_105936_note_is_not_not_image_input(self):
        # 105936 is now an image input — old "NOT image input" note must not appear in anchor
        note = _build()["reference_assets"]["primary_bottom_anchor"].get("note", "")
        self.assertNotIn("NOT image input", note)

    def test_asset01_not_primary(self):
        refs = _build()["reference_assets"]
        self.assertNotIn("primary_identity_reference", [v.get("role") for v in refs.values()])


# ===================================================================
# Identity Gene — anchor-aware, age language removed
# ===================================================================

class FixedIdentityGeneTests(unittest.TestCase):

    def test_identity_gene_in_prompt(self):
        self.assertIn(FIXED_IDENTITY_GENE, _build()["prompt_text"])

    def test_identity_unchanged_across_weather(self):
        texts = {_build(weather_condition=c)["fixed_identity_gene"]["text"]
                 for c in ["clear", "cloudy", "rainy", "snow"]}
        self.assertEqual(len(texts), 1)

    def test_identity_gene_label(self):
        self.assertEqual(_build()["fixed_identity_gene"]["gene"], "A_fixed_identity")

    def test_identity_contains_key_features(self):
        text = _build()["fixed_identity_gene"]["text"]
        self.assertIn("glasses", text)
        self.assertIn("side-parted short bob", text)

    def test_identity_no_age_wording(self):
        # Age impression carried by 105936 anchor image — text must not state age
        text = _build()["fixed_identity_gene"]["text"]
        self.assertNotIn("mid-to-late thirties", text)
        self.assertNotIn("thirties", text)

    def test_identity_contains_noble_sensuality(self):
        text = _build()["fixed_identity_gene"]["text"]
        self.assertIn("Noble sensuality", text)

    def test_identity_contains_premium_presence(self):
        text = _build()["fixed_identity_gene"]["text"]
        self.assertIn("Premium presence", text)

    def test_identity_hair_is_sleek_no_curl(self):
        text = _build()["fixed_identity_gene"]["text"]
        self.assertIn("sleek", text)
        self.assertIn("no curl at the ends", text)

    def test_identity_no_quiet_authority(self):
        text = _build()["fixed_identity_gene"]["text"]
        self.assertNotIn("quiet authority", text)
        self.assertNotIn("processed the room", text)
        self.assertNotIn("never performative", text)

    def test_identity_no_attractive_keyword(self):
        text = _build()["fixed_identity_gene"]["text"]
        self.assertNotIn("quietly attractive", text)

    def test_identity_noble_sensuality_not_exposure(self):
        text = _build()["fixed_identity_gene"]["text"]
        self.assertIn("never through exposure", text)

    def test_identity_invariant_anchor_is_105936(self):
        inv = _build()["fixed_identity_gene"]["invariants"]
        self.assertIn("105936", inv.get("anchor", ""))

    def test_identity_no_c_curl_in_invariants(self):
        inv = _build()["fixed_identity_gene"]["invariants"]
        self.assertIn("no C-curl", inv["hair"])

    def test_identity_maintains_reference_image(self):
        text = _build()["fixed_identity_gene"]["text"]
        self.assertIn("reference image", text)


# ===================================================================
# Role + Relationship Gene — exclusive owner-facing
# ===================================================================

class FixedRoleSceneGeneTests(unittest.TestCase):

    def test_role_gene_in_prompt(self):
        self.assertIn(FIXED_ROLE_SCENE_GENE, _build()["prompt_text"])

    def test_role_contains_secretary(self):
        text = _build()["fixed_role_scene_gene"]["text"]
        self.assertIn("private AI secretary", text)

    def test_role_contains_owner_farewell(self):
        text = _build()["fixed_role_scene_gene"]["text"]
        self.assertIn("대표님", text)
        self.assertIn("farewell", text)

    def test_role_contains_wooden_door(self):
        text = _build()["fixed_role_scene_gene"]["text"]
        self.assertIn("wooden door", text)
        self.assertIn("wood-paneled", text)

    def test_role_unchanged_across_weather(self):
        texts = {_build(weather_condition=c)["fixed_role_scene_gene"]["text"]
                 for c in ["cloudy", "rainy", "snow"]}
        self.assertEqual(len(texts), 1)

    def test_no_briefing_host_in_role(self):
        text = _build()["fixed_role_scene_gene"]["text"]
        self.assertNotIn("briefing host", text)

    def test_no_lobby_in_role(self):
        text = _build()["fixed_role_scene_gene"]["text"]
        self.assertNotIn("lobby", text)

    def test_role_exclusive_owner_facing(self):
        text = _build()["fixed_role_scene_gene"]["text"]
        self.assertIn("exclusive owner-facing private closing moment", text)

    def test_role_reserved_for_owner(self):
        text = _build()["fixed_role_scene_gene"]["text"]
        self.assertIn("reserved only for 대표님", text)

    def test_role_unattainable_not_approachable(self):
        text = _build()["fixed_role_scene_gene"]["text"]
        self.assertIn("Unattainable, not approachable", text)

    def test_role_no_warmth_framing(self):
        text = _build()["fixed_role_scene_gene"]["text"]
        self.assertNotIn("warmth of a closing ritual", text)
        self.assertNotIn("genuine care", text)


# ===================================================================
# Expression Gene — cool reserved, not broad/lively
# ===================================================================

class FixedExpressionGeneTests(unittest.TestCase):

    def test_expression_gene_in_prompt(self):
        self.assertIn(FIXED_EXPRESSION_GENE, _build()["prompt_text"])

    def test_expression_contains_restrained_composed_smile(self):
        text = _build()["fixed_expression_gene"]["text"]
        self.assertIn("restrained composed slight smile", text)

    def test_expression_is_not_broad_or_lively(self):
        text = _build()["fixed_expression_gene"]["text"]
        self.assertIn("Not broad", text)
        self.assertIn("Not lively", text)

    def test_expression_blocks_performative(self):
        text = _build()["fixed_expression_gene"]["text"]
        self.assertIn("Not performative", text)

    def test_expression_invariants_forbid_warm_motherly(self):
        forbidden = _build()["fixed_expression_gene"]["invariants"]["forbidden"]
        self.assertIn("warm motherly smile", forbidden)


# ===================================================================
# Prop + Gesture Gene — private contained gesture
# ===================================================================

class FixedPropGestureGeneTests(unittest.TestCase):

    def test_prop_gesture_gene_in_prompt(self):
        self.assertIn(FIXED_PROP_GESTURE_GENE, _build()["prompt_text"])

    def test_prop_contains_handbag(self):
        text = _build()["fixed_prop_gesture_gene"]["text"]
        self.assertIn("handbag", text)

    def test_prop_gesture_is_private_not_raised(self):
        text = _build()["fixed_prop_gesture_gene"]["text"]
        self.assertIn("not raised, not waving", text)

    def test_prop_gesture_is_contained(self):
        text = _build()["fixed_prop_gesture_gene"]["text"]
        self.assertIn("private and contained", text)

    def test_prop_blocks_tablet(self):
        text = _build()["fixed_prop_gesture_gene"]["text"]
        self.assertIn("No tablet", text)


# ===================================================================
# Camera Gene — single knee-up, no anti-body stack
# ===================================================================

class FixedCameraGeneTests(unittest.TestCase):

    def test_camera_gene_in_prompt(self):
        self.assertIn(FIXED_CAMERA_GENE, _build()["prompt_text"])

    def test_camera_knee_up(self):
        text = _build()["fixed_camera_gene"]["text"]
        self.assertIn("Knee-up", text)
        self.assertIn("85mm", text)

    def test_camera_no_anti_body_stack(self):
        text = _build()["fixed_camera_gene"]["text"]
        count_no = text.lower().count("no ")
        self.assertLessEqual(count_no, 1)

    def test_camera_unchanged_across_weather(self):
        texts = {_build(weather_condition=c)["fixed_camera_gene"]["text"]
                 for c in ["cloudy", "rainy", "snow"]}
        self.assertEqual(len(texts), 1)


# ===================================================================
# Weather Wardrobe — 105936-family closet, 6 weather variants
# ===================================================================

class WeatherWardrobeTests(unittest.TestCase):

    def _outfit(self, weather_condition, temperature_c=None, season=None):
        return _build(
            weather_condition=weather_condition,
            temperature_c=temperature_c,
            season=season,
        )["weather_outfit_shell"]["outfit_descriptor"]

    def test_clear_cool_yields_ivory_or_cream(self):
        outfit = self._outfit("clear", temperature_c=12.0)
        self.assertTrue(
            "ivory" in outfit.lower() or "cream" in outfit.lower(),
            f"clear_cool must include ivory or cream: {outfit}"
        )

    def test_cold_yields_cashmere_coat(self):
        outfit = self._outfit("cold", temperature_c=8.0)
        self.assertIn("cashmere", outfit.lower())
        self.assertIn("coat", outfit.lower())

    def test_cold_temp_yields_cashmere_coat(self):
        outfit = self._outfit("cloudy", temperature_c=5.0)
        self.assertIn("cashmere", outfit.lower())

    def test_rainy_yields_trench_or_coat(self):
        outfit = self._outfit("rainy")
        self.assertTrue(
            "trench" in outfit.lower() or "coat" in outfit.lower(),
            f"rainy must include trench or coat: {outfit}"
        )

    def test_warm_yields_silk_knit(self):
        outfit = self._outfit("clear", temperature_c=22.0)
        self.assertIn("silk-knit", outfit.lower())

    def test_hot_has_no_coat(self):
        outfit = self._outfit("clear", temperature_c=30.0)
        self.assertNotIn("overcoat", outfit.lower())
        self.assertNotIn("cashmere coat", outfit.lower())

    def test_snowy_yields_cashmere_overcoat(self):
        outfit = self._outfit("snow", temperature_c=-3.0)
        self.assertIn("cashmere", outfit.lower())
        self.assertIn("overcoat", outfit.lower())

    def test_freezing_temp_yields_snowy_variant(self):
        outfit = self._outfit("cloudy", temperature_c=0.0)
        self.assertIn("cashmere", outfit.lower())

    def test_handbag_in_all_weather_variants(self):
        cases = [
            ("clear", 12.0), ("cold", 8.0), ("rainy", None),
            ("clear", 22.0), ("clear", 30.0), ("snow", -3.0),
        ]
        for cond, temp in cases:
            outfit = self._outfit(cond, temperature_c=temp)
            self.assertIn("handbag", outfit.lower(),
                          f"handbag must be present for {cond}/{temp}: {outfit}")

    def test_no_cardigan_in_any_weather(self):
        cases = [
            ("clear", 12.0), ("cold", 8.0), ("rainy", None),
            ("clear", 22.0), ("clear", 30.0), ("snow", -3.0), ("cloudy", None),
        ]
        for cond, temp in cases:
            outfit = self._outfit(cond, temperature_c=temp)
            self.assertNotIn(" cardigan", outfit,
                             f"cardigan must not appear for {cond}/{temp}: {outfit}")

    def test_no_black_skirt_default(self):
        cases = [
            ("clear", 12.0), ("cold", 8.0), ("rainy", None), ("clear", 22.0),
        ]
        for cond, temp in cases:
            outfit = self._outfit(cond, temperature_c=temp)
            self.assertNotIn("black skirt", outfit.lower(),
                             f"black skirt default not allowed for {cond}/{temp}")

    def test_weather_varies_outfit(self):
        clear_cool = self._outfit("clear", temperature_c=12.0)
        cold = self._outfit("cold", temperature_c=8.0)
        hot = self._outfit("clear", temperature_c=30.0)
        self.assertNotEqual(clear_cool, cold)
        self.assertNotEqual(clear_cool, hot)
        self.assertNotEqual(cold, hot)

    def test_outfit_in_prompt_text(self):
        r = _build(weather_condition="clear", temperature_c=12.0)
        # clear_cool has "silk-knit" in outfit
        self.assertIn("silk-knit", r["prompt_text"].lower())

    def test_no_blazer_in_any_weather(self):
        cases = [
            ("clear", 12.0), ("cold", 8.0), ("rainy", None),
            ("clear", 22.0), ("clear", 30.0), ("snow", -3.0),
        ]
        for cond, temp in cases:
            outfit = self._outfit(cond, temperature_c=temp)
            self.assertNotIn("blazer", outfit.lower(),
                             f"blazer not allowed for {cond}/{temp}")

    def test_no_mock_neck_in_any_weather(self):
        cases = [
            ("clear", 12.0), ("cold", 8.0), ("rainy", None),
        ]
        for cond, temp in cases:
            outfit = self._outfit(cond, temperature_c=temp)
            self.assertNotIn("mock-neck", outfit.lower(),
                             f"mock-neck not allowed for {cond}/{temp}")

    def test_palette_within_allowed(self):
        allowed = {"ivory", "cream", "champagne", "camel", "charcoal", "taupe"}
        cases = [
            ("clear", 12.0), ("cold", 8.0), ("rainy", None),
            ("clear", 22.0), ("clear", 30.0), ("snow", -3.0),
        ]
        for cond, temp in cases:
            outfit = self._outfit(cond, temperature_c=temp).lower()
            found = [w for w in allowed if w in outfit]
            self.assertGreater(len(found), 0,
                               f"No allowed palette color in outfit for {cond}/{temp}: {outfit}")

    def test_weather_closet_key_in_outfit_map(self):
        r = _build(weather_condition="clear", temperature_c=12.0)
        self.assertEqual(r["weather_outfit_shell"]["outfit_map_key"], "clear_cool")

    def test_cold_closet_key(self):
        r = _build(weather_condition="cold", temperature_c=8.0)
        self.assertEqual(r["weather_outfit_shell"]["outfit_map_key"], "cold")

    def test_identity_unchanged_across_weather_variants(self):
        r_cool = _build(weather_condition="clear", temperature_c=12.0)
        r_hot = _build(weather_condition="clear", temperature_c=30.0)
        self.assertEqual(
            r_cool["fixed_identity_gene"]["text"],
            r_hot["fixed_identity_gene"]["text"],
        )

    def test_wardrobe_before_camera_in_assembly(self):
        from keysuri_bottom_shot_prompt_builder import ASSEMBLY_ORDER
        self.assertGreater(
            ASSEMBLY_ORDER.index("camera_gene"),
            ASSEMBLY_ORDER.index("wardrobe_gene"),
        )


# ===================================================================
# Negative Prompt — lean targeted blocklist
# ===================================================================

class NegativePromptTests(unittest.TestCase):

    def setUp(self):
        self.neg = _build()["negative_prompt"]

    def test_blocks_executive_portrait(self):
        self.assertIn("executive portrait", self.neg)

    def test_blocks_consultant_headshot(self):
        self.assertIn("consultant headshot", self.neg)

    def test_blocks_blazer(self):
        self.assertIn("blazer", self.neg)

    def test_blocks_mock_neck(self):
        self.assertIn("mock-neck sweater", self.neg)

    def test_blocks_c_curl(self):
        self.assertIn("C-curl cute bob", self.neg)
        self.assertIn("inward-curled bob", self.neg)

    def test_blocks_headshot_crop(self):
        self.assertIn("tight headshot", self.neg)

    def test_blocks_motherly_smile(self):
        self.assertIn("warm motherly smile", self.neg)

    def test_blocks_matronly(self):
        self.assertIn("matronly expression", self.neg)

    def test_does_not_block_satin_outfit(self):
        self.assertNotIn("satin wrap dress", self.neg)

    def test_does_not_block_smile_with_teeth(self):
        self.assertNotIn("smile with teeth", self.neg)

    def test_does_not_block_active_wave(self):
        self.assertNotIn("active wave", self.neg)

    def test_blocks_broad_open_smile(self):
        self.assertIn("broad open smile", self.neg)

    def test_blocks_lively_smile(self):
        self.assertIn("lively smile", self.neg)

    def test_blocks_raised_hand_wave(self):
        self.assertIn("raised hand wave", self.neg)

    def test_blocks_event_greeter(self):
        self.assertIn("event greeter", self.neg)

    def test_blocks_hotel_receptionist(self):
        self.assertIn("hotel receptionist", self.neg)

    def test_blocks_inward_curled_bob_variants(self):
        self.assertIn("curled ends bob", self.neg)
        self.assertIn("volume at tips", self.neg)

    def test_still_blocks_environment_failures(self):
        for term in ["tablet", "lobby", "desk", "monitor wall"]:
            self.assertIn(term, self.neg)

    def test_negative_same_across_weather(self):
        negs = {_build(weather_condition=c)["negative_prompt"]
                for c in ["rainy", "snow", "cloudy"]}
        self.assertEqual(len(negs), 1)

    def test_blocks_approachable_warmth(self):
        self.assertIn("approachable warmth", self.neg)

    def test_blocks_ordinary_office_lady(self):
        self.assertIn("ordinary office lady", self.neg)

    def test_blocks_lifestyle_model(self):
        self.assertIn("lifestyle model", self.neg)

    def test_blocks_cheap_sexiness(self):
        self.assertIn("cheap sexiness", self.neg)

    def test_blocks_hostess_bar_lounge(self):
        self.assertIn("hostess", self.neg)
        self.assertIn("bar mood", self.neg)
        self.assertIn("lounge mood", self.neg)


# ===================================================================
# Reference Assets — updated anchor hierarchy
# ===================================================================

class ReferenceAssetTests(unittest.TestCase):

    def setUp(self):
        self.refs = _build()["reference_assets"]

    def test_primary_bottom_anchor_is_105936(self):
        anchor = self.refs["primary_bottom_anchor"]
        self.assertEqual(anchor["role"], BOTTOM_ANCHOR_ROLE)
        self.assertEqual(anchor["path"], BOTTOM_ANCHOR_PATH)
        self.assertIn("105936", anchor["path"])

    def test_secondary_continuity_is_asset01(self):
        sec = self.refs["secondary_continuity_reference"]
        self.assertEqual(sec["role"], ASSET01_ROLE)
        self.assertEqual(sec["path"], ASSET01_PATH)

    def test_105936_note_mentions_slot_0(self):
        note = self.refs["primary_bottom_anchor"]["note"]
        self.assertIn("slot 0", note)

    def test_asset01_note_mentions_slot_1(self):
        note = self.refs["secondary_continuity_reference"]["note"]
        self.assertIn("slot 1", note)

    def test_no_direction_reference_only_role(self):
        roles = [v.get("role", "") for v in self.refs.values()]
        self.assertNotIn("direction_reference_only", roles)


# ===================================================================
# Builder Status — generation disabled
# ===================================================================

class BuilderStatusTests(unittest.TestCase):

    def setUp(self):
        self.status = _build()["builder_status"]

    def test_generation_not_allowed(self):
        self.assertFalse(self.status["generation_allowed"])

    def test_runtime_not_enabled(self):
        self.assertFalse(self.status["runtime_enabled"])

    def test_owner_approval_required(self):
        self.assertTrue(self.status["owner_approval_required"])

    def test_image_api_not_called(self):
        self.assertFalse(self.status["image_api_called"])

    def test_contract_version_v6(self):
        self.assertEqual(self.status["contract_version"], "v6")

    def test_family_id_default_family_a(self):
        self.assertEqual(self.status["family_id"], "family_a")

    def test_program_id_recorded(self):
        self.assertEqual(_build()["builder_status"]["program_id"], "keysuri_korea_tech")

    def test_unsupported_family_raises(self):
        with self.assertRaises(ValueError):
            build_bottom_shot_prompt(weather_condition="cloudy", family_id="family_z")


# ===================================================================
# Weather Input Metadata — unchanged contract
# ===================================================================

class WeatherInputMetadataTests(unittest.TestCase):

    def test_temperature_unavailable_when_not_supplied(self):
        r = _build(weather_condition="cloudy")
        self.assertTrue(r["weather_input_metadata"]["temperature_c_unavailable"])

    def test_temperature_available_when_supplied(self):
        r = _build(weather_condition="cloudy", temperature_c=15.0)
        self.assertFalse(r["weather_input_metadata"]["temperature_c_unavailable"])
        self.assertEqual(r["weather_input_metadata"]["temperature_c"], 15.0)

    def test_weather_outfit_source_limited_when_no_temp(self):
        r = _build(weather_condition="cloudy")
        self.assertEqual(r["weather_input_metadata"]["weather_outfit_source"], "limited_condition_string")

    def test_weather_outfit_source_full_when_temp_provided(self):
        r = _build(weather_condition="cloudy", temperature_c=15.0)
        self.assertEqual(r["weather_input_metadata"]["weather_outfit_source"], "condition_plus_temperature")

    def test_fine_dust_unavailable_flag_false_when_fine_dust_condition(self):
        r = _build(weather_condition="fine_dust")
        self.assertFalse(r["weather_input_metadata"]["fine_dust_unavailable"])

    def test_fine_dust_unavailable_flag_true_for_other_conditions(self):
        r = _build(weather_condition="cloudy")
        self.assertTrue(r["weather_input_metadata"]["fine_dust_unavailable"])


# ===================================================================
# Variation Gate Fallback — unchanged
# ===================================================================

class VariationGateFallbackTests(unittest.TestCase):

    def test_variation_gate_false_uses_fixed_fallback(self):
        from keysuri_service_full_run import korea_bottom_variation_enabled
        self.assertFalse(korea_bottom_variation_enabled())

    def test_variation_gate_false_no_image_api_call(self):
        result = build_bottom_shot_prompt(weather_condition="cloudy")
        self.assertFalse(result["builder_status"]["image_api_called"])

    def test_resolve_korea_bottom_returns_fixed_path_when_gate_off(self):
        from keysuri_service_full_run import resolve_korea_bottom_email_image_path
        from pathlib import Path

        fake_path = Path("/tmp/fake_105936.jpg")
        with patch("keysuri_service_full_run.korea_bottom_variation_enabled", return_value=False):
            with patch("keysuri_service_full_run.resolve_korea_bottom_email_asset_path",
                       return_value=(fake_path, [])):
                path, issues, meta = resolve_korea_bottom_email_image_path("test_run_id")

        self.assertEqual(meta["bottom_shot_source"], "fixed_105936_fallback")
        self.assertFalse(meta["bottom_shot_variation_enabled"])

    def test_metadata_only_builder_no_image_api(self):
        meta = build_bottom_shot_prompt_metadata_only(weather_condition="rainy")
        self.assertFalse(meta["bottom_shot_generation_allowed"])
        self.assertFalse(meta["bottom_shot_image_api_called"])

    def test_metadata_only_records_weather_case(self):
        meta = build_bottom_shot_prompt_metadata_only(weather_condition="snow")
        self.assertTrue(len(meta["bottom_shot_weather_case"]) > 0)


# ===================================================================
# Assembly Order — v6: 8 genes
# ===================================================================

class AssemblyOrderTests(unittest.TestCase):

    def test_assembly_order_8_genes(self):
        from keysuri_bottom_shot_prompt_builder import ASSEMBLY_ORDER
        self.assertEqual(len(ASSEMBLY_ORDER), 8)
        self.assertEqual(ASSEMBLY_ORDER[0], "scene_lock")
        self.assertEqual(ASSEMBLY_ORDER[-1], "negative_prompt")
        self.assertIn("expression_gene", ASSEMBLY_ORDER)
        self.assertIn("prop_gesture_gene", ASSEMBLY_ORDER)

    def test_scene_lock_first_in_prompt(self):
        from keysuri_bottom_shot_prompt_builder import SCENE_LOCK
        self.assertTrue(_build()["prompt_text"].startswith(SCENE_LOCK.strip()[:30]))

    def test_identity_before_role_in_prompt(self):
        prompt = _build()["prompt_text"]
        self.assertGreater(
            prompt.find(FIXED_ROLE_SCENE_GENE[:30]),
            prompt.find(FIXED_IDENTITY_GENE[:30]),
        )

    def test_expression_before_wardrobe_in_prompt(self):
        prompt = _build(weather_condition="clear", temperature_c=12.0)["prompt_text"]
        wardrobe_snippet = _build(weather_condition="clear", temperature_c=12.0)[
            "weather_outfit_shell"]["outfit_descriptor"][:30]
        self.assertGreater(
            prompt.find(wardrobe_snippet),
            prompt.find(FIXED_EXPRESSION_GENE[:30]),
        )


# ===================================================================
# Backward Compat — metadata_only returns required keys
# ===================================================================

class MetadataOnlyBackwardCompatTests(unittest.TestCase):

    def test_metadata_only_returns_required_keys(self):
        meta = build_bottom_shot_prompt_metadata_only(weather_condition="cloudy")
        required = [
            "bottom_shot_weather_case",
            "bottom_shot_outfit_map_key",
            "bottom_shot_weather_outfit_source",
            "bottom_shot_prompt_preview",
        ]
        for key in required:
            self.assertIn(key, meta, f"Missing key: {key}")

    def test_metadata_only_prompt_preview_under_200(self):
        meta = build_bottom_shot_prompt_metadata_only(weather_condition="cloudy")
        self.assertLessEqual(len(meta["bottom_shot_prompt_preview"]), 200)

    def test_metadata_only_contract_version_v6(self):
        meta = build_bottom_shot_prompt_metadata_only(weather_condition="cloudy")
        self.assertEqual(meta["bottom_shot_prompt_contract_version"], "v6")

    def test_metadata_only_outfit_map_key_present(self):
        meta = build_bottom_shot_prompt_metadata_only(
            weather_condition="clear", temperature_c=12.0
        )
        self.assertEqual(meta["bottom_shot_outfit_map_key"], "clear_cool")


# ===================================================================
# V5 Drift Ban — authority/blazer/headshot absent from prompt
# ===================================================================

class V5DriftBanTests(unittest.TestCase):

    def test_no_quiet_authority_in_prompt(self):
        self.assertNotIn("quiet authority", _build()["prompt_text"])

    def test_no_processed_the_room_in_prompt(self):
        self.assertNotIn("processed the room", _build()["prompt_text"])

    def test_no_blazer_in_prompt(self):
        prompt = _build()["prompt_text"]
        self.assertNotIn("blazer", prompt.lower())

    def test_no_mock_neck_in_prompt(self):
        prompt = _build()["prompt_text"]
        self.assertNotIn("mock-neck", prompt.lower())

    def test_no_headshot_crop_direction_in_prompt(self):
        prompt = _build()["prompt_text"]
        self.assertNotIn("mid-chest-to-crown", prompt)

    def test_handbag_required_in_prompt(self):
        self.assertIn("handbag", _build()["prompt_text"])

    def test_farewell_in_prompt(self):
        self.assertIn("farewell", _build()["prompt_text"])

    def test_restrained_composed_smile_in_prompt(self):
        self.assertIn("restrained composed slight smile", _build()["prompt_text"])

    def test_secretary_in_prompt(self):
        self.assertIn("secretary", _build()["prompt_text"])


# ===================================================================
# QA Runner Anchor — 105936 path and role exported for runner
# ===================================================================

class QARunnerAnchorTests(unittest.TestCase):

    def test_bottom_anchor_path_importable(self):
        from keysuri_bottom_shot_prompt_builder import BOTTOM_ANCHOR_PATH
        self.assertIn("105936", BOTTOM_ANCHOR_PATH)

    def test_bottom_anchor_role_importable(self):
        from keysuri_bottom_shot_prompt_builder import BOTTOM_ANCHOR_ROLE
        self.assertEqual(BOTTOM_ANCHOR_ROLE, "primary_bottom_visual_anchor")

    def test_asset01_role_importable(self):
        from keysuri_bottom_shot_prompt_builder import ASSET01_ROLE
        self.assertEqual(ASSET01_ROLE, "secondary_same_person_continuity_reference")

    def test_deprecated_direction_ref_path_alias_matches_anchor(self):
        from keysuri_bottom_shot_prompt_builder import (
            BOTTOM_ANCHOR_PATH,
            DIRECTION_REF_105936_PATH,
        )
        self.assertEqual(DIRECTION_REF_105936_PATH, BOTTOM_ANCHOR_PATH)


if __name__ == "__main__":
    unittest.main()
