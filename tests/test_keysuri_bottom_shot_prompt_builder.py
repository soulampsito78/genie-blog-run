"""Tests for Key-Suri bottom-shot prompt builder (Contract v6).

Verifies:
- v6 persona: private AI secretary, fresh smile, luxury off-duty, handbag, farewell
- v5 authority/blazer/mock-neck/C-curl/headshot drift is banned
- Asset01/105936 roles and gate status preserved
- Backward-compatible metadata_only return keys for service_full_run
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from keysuri_bottom_shot_prompt_builder import (
    ASSET01_PATH,
    ASSET01_ROLE,
    DIRECTION_REF_105936_NOTE,
    DIRECTION_REF_105936_PATH,
    DIRECTION_REF_105936_ROLE,
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
# Identity Gene — v6 persona (fresh/attractive, not authority)
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
        self.assertIn("mid-to-late thirties", text)
        self.assertIn("glasses", text)
        self.assertIn("side-parted short bob", text)

    def test_identity_contains_attractive_premium(self):
        text = _build()["fixed_identity_gene"]["text"]
        self.assertIn("attractive", text)
        self.assertIn("premium", text)

    def test_identity_hair_is_sleek_no_curl(self):
        text = _build()["fixed_identity_gene"]["text"]
        self.assertIn("sleek", text)
        self.assertIn("no curl at the ends", text)

    def test_identity_no_quiet_authority(self):
        text = _build()["fixed_identity_gene"]["text"]
        self.assertNotIn("quiet authority", text)
        self.assertNotIn("processed the room", text)
        self.assertNotIn("never performative", text)

    def test_identity_no_c_curl(self):
        inv = _build()["fixed_identity_gene"]["invariants"]
        self.assertIn("no C-curl", inv["hair"])


# ===================================================================
# Role + Relationship Gene — secretary, owner, farewell
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


# ===================================================================
# Expression Gene — fresh composed smile
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
# Prop + Gesture Gene — handbag, hand farewell
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
        self.assertLessEqual(count_no, 1, "Camera gene should not stack multiple anti-body negatives")

    def test_camera_unchanged_across_weather(self):
        texts = {_build(weather_condition=c)["fixed_camera_gene"]["text"]
                 for c in ["cloudy", "rainy", "snow"]}
        self.assertEqual(len(texts), 1)


# ===================================================================
# Wardrobe — taste cluster catalog, no blazer/mock-neck
# ===================================================================

class WardrobeTests(unittest.TestCase):

    def test_default_cluster_B(self):
        r = _build()
        self.assertEqual(r["weather_outfit_shell"]["taste_cluster"], "B")

    def test_cluster_A_selection(self):
        r = _build(taste_cluster="A")
        self.assertEqual(r["weather_outfit_shell"]["taste_cluster"], "A")
        self.assertIn("silk-knit", r["weather_outfit_shell"]["outfit_descriptor"])

    def test_cluster_G_selection(self):
        r = _build(taste_cluster="G")
        self.assertEqual(r["weather_outfit_shell"]["taste_cluster"], "G")
        self.assertIn("camel", r["weather_outfit_shell"]["outfit_descriptor"].lower())

    def test_outfit_in_prompt_text(self):
        r = _build(taste_cluster="C")
        self.assertIn("smoky blue", r["prompt_text"].lower())

    def test_no_blazer_in_any_cluster(self):
        for cluster in "ABCDEFGH":
            outfit = _build(taste_cluster=cluster)["weather_outfit_shell"]["outfit_descriptor"]
            self.assertNotIn("blazer", outfit.lower(),
                             f"Cluster {cluster} must not contain blazer")

    def test_no_mock_neck_in_any_cluster(self):
        for cluster in "ABCDEFGH":
            outfit = _build(taste_cluster=cluster)["weather_outfit_shell"]["outfit_descriptor"]
            self.assertNotIn("mock-neck", outfit.lower(),
                             f"Cluster {cluster} must not contain mock-neck")

    def test_no_bare_cardigan_in_luxury_clusters(self):
        # Clusters A, C, G had lifestyle/cardigan drift in v6 QA run 031005
        for cluster in ["A", "C", "G"]:
            outfit = _build(taste_cluster=cluster)["weather_outfit_shell"]["outfit_descriptor"]
            self.assertNotIn(" cardigan", outfit,
                             f"Cluster {cluster} must not use bare 'cardigan' — use structured layer language")

    def test_weather_modifies_fabric_not_structure(self):
        r_warm = _build(weather_condition="clear", temperature_c=30.0)
        r_cold = _build(weather_condition="snow", temperature_c=-5.0)
        self.assertNotEqual(
            r_warm["weather_outfit_shell"]["outfit_descriptor"],
            r_cold["weather_outfit_shell"]["outfit_descriptor"],
        )

    def test_identity_unchanged_when_cluster_changes(self):
        r_a = _build(taste_cluster="A")
        r_e = _build(taste_cluster="E")
        self.assertEqual(r_a["fixed_identity_gene"]["text"], r_e["fixed_identity_gene"]["text"])

    def test_outfit_after_camera_not_required(self):
        """v6: wardrobe appears before camera in assembly to prevent outfit-first."""
        from keysuri_bottom_shot_prompt_builder import ASSEMBLY_ORDER
        self.assertGreater(
            ASSEMBLY_ORDER.index("camera_gene"),
            ASSEMBLY_ORDER.index("wardrobe_gene"),
        )


# ===================================================================
# Negative Prompt — retargeted for v6
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


# ===================================================================
# Reference Assets — unchanged from v5
# ===================================================================

class ReferenceAssetTests(unittest.TestCase):

    def setUp(self):
        self.refs = _build()["reference_assets"]

    def test_asset01_is_primary_identity_reference(self):
        self.assertEqual(self.refs["primary_identity_reference"]["role"], ASSET01_ROLE)
        self.assertEqual(self.refs["primary_identity_reference"]["path"], ASSET01_PATH)

    def test_105936_is_direction_reference_only(self):
        ref = self.refs["direction_reference"]
        self.assertEqual(ref["role"], DIRECTION_REF_105936_ROLE)
        self.assertEqual(ref["path"], DIRECTION_REF_105936_PATH)

    def test_105936_not_flagged_as_image_input(self):
        self.assertIn("NOT image input", self.refs["direction_reference"]["note"])

    def test_105936_not_flagged_as_fixed_final_asset(self):
        self.assertIn("NOT fixed final asset", self.refs["direction_reference"]["note"])

    def test_105936_note_warns_against_silk_satin(self):
        self.assertIn("silk-knit/satin", self.refs["direction_reference"]["note"])


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
# Weather Input Metadata — unchanged
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
        prompt = _build()["prompt_text"]
        self.assertGreater(
            prompt.find(_build()["weather_outfit_shell"]["outfit_descriptor"][:30]),
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


# ===================================================================
# V5 Drift Ban — authority/blazer/headshot must be absent
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

    def test_farewell_gesture_in_prompt(self):
        self.assertIn("farewell", _build()["prompt_text"])

    def test_restrained_composed_smile_in_prompt(self):
        self.assertIn("restrained composed slight smile", _build()["prompt_text"])

    def test_secretary_in_prompt(self):
        self.assertIn("secretary", _build()["prompt_text"])


if __name__ == "__main__":
    unittest.main()
