"""Tests for Key-Suri bottom-shot prompt builder (Contract v5).

Verifies:
- Fixed Identity Gene A is always present and unmodified by weather
- Fixed Role/Scene Gene B is always present and unmodified by weather
- Fixed Camera Gene D is always present and unmodified by weather
- Negative prompt blocks all Contract v5 failure modes
- Weather changes outfit shell only (Gene C) — identity/role/camera unchanged
- 105936 is marked direction_reference_only, not image input
- Asset01 is primary identity reference
- variation gate false still uses fixed 105936 fallback (service_full_run)
- No image generation call is introduced
- builder_status flags: generation_allowed=False, image_api_called=False
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
    FIXED_IDENTITY_GENE,
    FIXED_ROLE_SCENE_GENE,
    NEGATIVE_PROMPT_V5,
    build_bottom_shot_prompt,
    build_bottom_shot_prompt_metadata_only,
)


def _build(weather_condition="cloudy", temperature_c=None, season=None, program_id="keysuri_korea_tech"):
    return build_bottom_shot_prompt(
        weather_condition=weather_condition,
        temperature_c=temperature_c,
        season=season,
        program_id=program_id,
    )


class FixedIdentityGeneTests(unittest.TestCase):
    """Gene A — Fixed Identity Gene must be present in every prompt, unmodified."""

    def test_identity_gene_text_in_prompt(self):
        result = _build()
        self.assertIn(FIXED_IDENTITY_GENE, result["prompt_text"])

    def test_identity_gene_unchanged_across_all_weather_conditions(self):
        conditions = ["clear", "cloudy", "overcast", "rainy", "snow", "cold", "fine_dust", "haze"]
        identity_texts = set()
        for cond in conditions:
            r = _build(weather_condition=cond)
            identity_texts.add(r["fixed_identity_gene"]["text"])
        self.assertEqual(len(identity_texts), 1, "Identity gene text must not change with weather")

    def test_identity_gene_metadata_gene_label(self):
        result = _build()
        self.assertEqual(result["fixed_identity_gene"]["gene"], "A_fixed_identity")

    def test_identity_invariants_present(self):
        inv = _build()["fixed_identity_gene"]["invariants"]
        self.assertIn("age", inv)
        self.assertIn("glasses", inv)
        self.assertIn("hair", inv)
        self.assertIn("expression", inv)

    def test_identity_contains_key_features(self):
        text = _build()["fixed_identity_gene"]["text"]
        self.assertIn("mid-to-late thirties", text)
        self.assertIn("bob", text)
        self.assertIn("glasses", text)
        self.assertIn("quiet authority", text)


class FixedRoleSceneGeneTests(unittest.TestCase):
    """Gene B — Fixed Role/Scene Gene must be present and unmodified by weather."""

    def test_role_scene_gene_in_prompt(self):
        result = _build()
        self.assertIn(FIXED_ROLE_SCENE_GENE, result["prompt_text"])

    def test_role_scene_unchanged_across_weather(self):
        conditions = ["cloudy", "rainy", "snow", "fine_dust"]
        texts = {_build(weather_condition=c)["fixed_role_scene_gene"]["text"] for c in conditions}
        self.assertEqual(len(texts), 1)

    def test_role_scene_gene_label(self):
        self.assertEqual(_build()["fixed_role_scene_gene"]["gene"], "B_fixed_role_scene")

    def test_no_outdoor_scene_in_role(self):
        text = _build()["fixed_role_scene_gene"]["text"]
        self.assertIn("No outdoor scenes", text)

    def test_no_full_body_in_role(self):
        text = _build()["fixed_role_scene_gene"]["text"]
        self.assertIn("No full-body framing", text)

    def test_no_open_doors_in_role(self):
        text = _build()["fixed_role_scene_gene"]["text"]
        self.assertIn("No open doors", text)


class FixedCameraGeneTests(unittest.TestCase):
    """Gene D — Camera/Framing Gene must be present and unmodified by weather."""

    def test_camera_gene_in_prompt(self):
        result = _build()
        self.assertIn(FIXED_CAMERA_GENE, result["prompt_text"])

    def test_camera_gene_unchanged_across_weather(self):
        conditions = ["cloudy", "rainy", "snow", "autumn_evening"]
        texts = set()
        for c in conditions:
            if c == "autumn_evening":
                r = _build(season="autumn_evening")
            else:
                r = _build(weather_condition=c)
            texts.add(r["fixed_camera_gene"]["text"])
        self.assertEqual(len(texts), 1)

    def test_camera_gene_label(self):
        self.assertEqual(_build()["fixed_camera_gene"]["gene"], "D_fixed_camera_framing")

    def test_camera_upper_body_framing(self):
        text = _build()["fixed_camera_gene"]["text"]
        self.assertIn("upper-body shot", text)
        self.assertIn("85mm", text)


class NegativePromptBlocklistTests(unittest.TestCase):
    """Negative prompt must block all Contract v5 failure modes."""

    def setUp(self):
        self.neg = _build()["negative_prompt"]

    def test_vneck_wrap_dress_blocked(self):
        self.assertIn("V-neck wrap dress", self.neg)

    def test_open_front_dress_blocked(self):
        self.assertIn("open-front dress", self.neg)

    def test_satin_wrap_blocked(self):
        self.assertIn("satin wrap dress", self.neg)

    def test_full_body_blocked(self):
        self.assertIn("full body shot", self.neg)

    def test_outdoor_scene_blocked(self):
        self.assertIn("outdoor scene", self.neg)

    def test_open_door_blocked(self):
        self.assertIn("open door", self.neg)

    def test_toothy_smile_blocked(self):
        self.assertIn("smile with teeth", self.neg)

    def test_c_curl_cute_bob_blocked(self):
        self.assertIn("C-curl cute bob", self.neg)

    def test_young_office_worker_blocked(self):
        self.assertIn("young office worker", self.neg)

    def test_glamour_model_blocked(self):
        self.assertIn("glamour model", self.neg)

    def test_decollete_blocked(self):
        self.assertIn("décolleté", self.neg)

    def test_outfit_first_blocked(self):
        self.assertIn("outfit-first composition", self.neg)

    def test_active_wave_blocked(self):
        self.assertIn("active wave", self.neg)

    def test_open_hotel_room_blocked(self):
        self.assertIn("open hotel-like room", self.neg)

    def test_full_body_lookbook_blocked(self):
        self.assertIn("full-body lookbook", self.neg)

    def test_negative_same_across_weather(self):
        negs = {_build(weather_condition=c)["negative_prompt"]
                for c in ["rainy", "snow", "cloudy", "fine_dust"]}
        self.assertEqual(len(negs), 1, "Negative prompt must not change with weather")

    def test_negative_prompt_constant_matches(self):
        self.assertEqual(_build()["negative_prompt"], NEGATIVE_PROMPT_V5)


class WeatherOutfitShellTests(unittest.TestCase):
    """Gene C — Weather/Outfit Shell: changes with weather, identity/role/camera do not."""

    def _outfit(self, **kwargs):
        return _build(**kwargs)["weather_outfit_shell"]["outfit_descriptor"]

    def test_rainy_outfit_differs_from_sunny(self):
        self.assertNotEqual(self._outfit(weather_condition="rainy"), self._outfit(weather_condition="sunny"))

    def test_snow_outfit_differs_from_rainy(self):
        self.assertNotEqual(self._outfit(weather_condition="snow"), self._outfit(weather_condition="rainy"))

    def test_fine_dust_outfit_is_indoor_professional(self):
        outfit = self._outfit(weather_condition="fine_dust")
        self.assertIn("Clean", outfit)

    def test_outfit_in_prompt_text(self):
        r = _build(weather_condition="rainy")
        self.assertIn(r["weather_outfit_shell"]["outfit_descriptor"], r["prompt_text"])

    def test_outfit_appears_last_in_assembly(self):
        r = _build(weather_condition="snow")
        prompt = r["prompt_text"]
        camera_pos = prompt.find(FIXED_CAMERA_GENE[:30])
        outfit_pos = prompt.find(r["weather_outfit_shell"]["outfit_descriptor"][:30])
        self.assertGreater(outfit_pos, camera_pos, "Outfit must appear after Camera Gene in prompt")

    def test_clear_warm_with_temperature(self):
        r = _build(weather_condition="clear", temperature_c=22.0)
        self.assertEqual(r["weather_outfit_shell"]["outfit_map_key"], "clear_warm")

    def test_clear_cool_with_temperature(self):
        r = _build(weather_condition="clear", temperature_c=10.0)
        self.assertEqual(r["weather_outfit_shell"]["outfit_map_key"], "clear_cool")

    def test_autumn_evening_season_override(self):
        r = _build(weather_condition="cloudy", season="autumn_evening")
        self.assertEqual(r["weather_outfit_shell"]["outfit_map_key"], "autumn_evening")

    def test_winter_evening_season_override(self):
        r = _build(weather_condition="clear", season="winter_evening")
        self.assertEqual(r["weather_outfit_shell"]["outfit_map_key"], "winter_evening")

    def test_humid_hot_by_temperature(self):
        r = _build(weather_condition="clear", temperature_c=30.0)
        self.assertEqual(r["weather_outfit_shell"]["outfit_map_key"], "humid_hot")

    def test_identity_unchanged_when_outfit_changes(self):
        r_rainy = _build(weather_condition="rainy")
        r_snow = _build(weather_condition="snow")
        self.assertEqual(r_rainy["fixed_identity_gene"]["text"], r_snow["fixed_identity_gene"]["text"])

    def test_camera_unchanged_when_outfit_changes(self):
        r_rainy = _build(weather_condition="rainy")
        r_snow = _build(weather_condition="snow")
        self.assertEqual(r_rainy["fixed_camera_gene"]["text"], r_snow["fixed_camera_gene"]["text"])

    def test_weather_outfit_shell_gene_label(self):
        self.assertEqual(_build()["weather_outfit_shell"]["gene"], "C_variable_weather_outfit_shell")


class ReferenceAssetTests(unittest.TestCase):
    """Asset01 = primary identity reference; 105936 = direction reference only."""

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
        note = self.refs["direction_reference"]["note"]
        self.assertIn("NOT image input", note)

    def test_105936_not_flagged_as_fixed_final_asset(self):
        note = self.refs["direction_reference"]["note"]
        self.assertIn("NOT fixed final asset", note)

    def test_105936_note_warns_against_silk_satin(self):
        note = self.refs["direction_reference"]["note"]
        self.assertIn("silk-knit/satin", note)


class BuilderStatusTests(unittest.TestCase):
    """builder_status flags: generation disabled, image API not called."""

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

    def test_contract_version_v5(self):
        self.assertEqual(self.status["contract_version"], "v5")

    def test_family_id_default_family_a(self):
        self.assertEqual(self.status["family_id"], "family_a")

    def test_program_id_recorded(self):
        r = _build(program_id="keysuri_korea_tech")
        self.assertEqual(r["builder_status"]["program_id"], "keysuri_korea_tech")

    def test_unsupported_family_raises(self):
        with self.assertRaises(ValueError):
            build_bottom_shot_prompt(weather_condition="cloudy", family_id="family_z")


class WeatherInputMetadataTests(unittest.TestCase):
    """Records whether temperature_c and fine_dust are available."""

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


class VariationGateFallbackTests(unittest.TestCase):
    """Variation gate False → fixed 105936 fallback; no image generation."""

    def test_variation_gate_false_uses_fixed_fallback(self):
        from keysuri_service_full_run import korea_bottom_variation_enabled
        self.assertFalse(korea_bottom_variation_enabled())

    def test_variation_gate_false_no_image_api_call(self):
        """Calling build_bottom_shot_prompt must never invoke image generation."""
        with patch("keysuri_bottom_shot_prompt_builder.build_bottom_shot_prompt",
                   wraps=build_bottom_shot_prompt) as mock_builder:
            result = build_bottom_shot_prompt(weather_condition="cloudy")
        # assert no image API was called (builder has no image API import)
        self.assertFalse(result["builder_status"]["image_api_called"])

    def test_resolve_korea_bottom_returns_fixed_path_when_gate_off(self):
        """resolve_korea_bottom_email_image_path falls back to 105936 when gate is off."""
        from keysuri_service_full_run import resolve_korea_bottom_email_image_path
        from pathlib import Path

        # Patch gate to False (default) and asset resolution to return a fake path
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
        self.assertEqual(meta["bottom_shot_prompt_contract_version"], "v5")

    def test_metadata_only_records_weather_case(self):
        meta = build_bottom_shot_prompt_metadata_only(weather_condition="snow")
        self.assertTrue(len(meta["bottom_shot_weather_case"]) > 0)


class AssemblyOrderTests(unittest.TestCase):
    """Assembly order: Scene → Identity → Role → Camera → Outfit → Negative."""

    def test_assembly_order_tuple(self):
        from keysuri_bottom_shot_prompt_builder import ASSEMBLY_ORDER
        self.assertEqual(ASSEMBLY_ORDER[0], "scene_lock")
        self.assertEqual(ASSEMBLY_ORDER[-1], "negative_prompt")
        self.assertIn("identity_gene", ASSEMBLY_ORDER)
        self.assertIn("weather_outfit_shell", ASSEMBLY_ORDER)
        # Outfit must come after camera
        self.assertGreater(
            ASSEMBLY_ORDER.index("weather_outfit_shell"),
            ASSEMBLY_ORDER.index("camera_gene"),
        )

    def test_scene_lock_first_in_prompt_text(self):
        from keysuri_bottom_shot_prompt_builder import SCENE_LOCK
        r = _build()
        self.assertTrue(r["prompt_text"].startswith(SCENE_LOCK.strip()[:30]))

    def test_identity_before_role_in_prompt(self):
        r = _build()
        prompt = r["prompt_text"]
        identity_pos = prompt.find(FIXED_IDENTITY_GENE[:30])
        role_pos = prompt.find(FIXED_ROLE_SCENE_GENE[:30])
        self.assertGreater(role_pos, identity_pos)

    def test_role_before_camera_in_prompt(self):
        r = _build()
        prompt = r["prompt_text"]
        role_pos = prompt.find(FIXED_ROLE_SCENE_GENE[:30])
        camera_pos = prompt.find(FIXED_CAMERA_GENE[:30])
        self.assertGreater(camera_pos, role_pos)


if __name__ == "__main__":
    unittest.main()
