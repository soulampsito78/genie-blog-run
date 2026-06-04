"""Tests for Kee-Suri image provider/env contract (no API calls)."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from keysuri_image_provider_contract import (
    CONTRACT_TYPE,
    OUTPUT_IMAGES_DIR,
    PROVIDER_SELECTION_STATUS,
    REFERENCE_ASSET_DEFAULT,
    REFERENCE_ASSET_FULL_BODY,
    build_keysuri_image_provider_env_contract,
    get_keysuri_image_provider_env_summary_from_env,
    mask_secret,
    program_id_is_allowed,
    program_id_is_forbidden,
    resolve_keysuri_reference_asset_path,
    validate_keysuri_image_output_path,
    validate_keysuri_image_provider_env_contract,
)

_REPO_ENV_KEYS = (
    "GENIE_VERTEX_PROJECT_ID",
    "GOOGLE_CLOUD_PROJECT",
    "GENIE_KEYSURI_IMAGE_CANARY_PROGRAM",
    "GENIE_KEYSURI_IMAGE_MANUAL_APPROVAL",
)


class KeysuriImageProviderContractTests(unittest.TestCase):
    def test_contract_shape(self) -> None:
        contract = build_keysuri_image_provider_env_contract()
        self.assertEqual(contract["contract_type"], CONTRACT_TYPE)
        self.assertEqual(
            contract["provider_policy"]["provider_selection_status"],
            PROVIDER_SELECTION_STATUS,
        )
        self.assertTrue(contract["runtime_policy"]["default_no_call"])
        self.assertTrue(contract["runtime_policy"]["manual_only"])
        self.assertTrue(contract["runtime_policy"]["one_program_per_run"])
        self.assertEqual(contract["runtime_policy"]["max_requests_per_run"], 1)
        self.assertFalse(contract["runtime_policy"]["scheduler_allowed"])
        self.assertFalse(contract["runtime_policy"]["production_auto_call_allowed"])
        self.assertEqual(contract["runtime_policy"]["runtime_wiring"], "none")
        self.assertEqual(validate_keysuri_image_provider_env_contract(contract), [])

    def test_reference_assets(self) -> None:
        contract = build_keysuri_image_provider_env_contract()
        refs = contract["reference_assets"]
        self.assertEqual(refs["default"], REFERENCE_ASSET_DEFAULT)
        self.assertEqual(refs["full_body"], REFERENCE_ASSET_FULL_BODY)

    def test_output_policy(self) -> None:
        contract = build_keysuri_image_provider_env_contract()
        out = contract["output_policy"]
        self.assertTrue(str(out["future_generated_images_dir"]).startswith(OUTPUT_IMAGES_DIR))
        self.assertTrue(out["must_not_commit_images"])
        self.assertTrue(out["must_remain_unstaged"])

    def test_mask_secret(self) -> None:
        self.assertEqual(mask_secret(None), "(missing)")
        self.assertEqual(mask_secret("ab"), "****")
        masked = mask_secret("supersecretkey1234")
        self.assertTrue(masked.startswith("****"))
        self.assertNotIn("supersecretkey1234", masked)

    def test_env_summary_no_full_secrets(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "GENIE_VERTEX_PROJECT_ID": "my-gcp-project-xyz",
                "GENIE_KEYSURI_IMAGE_MANUAL_APPROVAL": "true",
            },
            clear=False,
        ):
            summary = get_keysuri_image_provider_env_summary_from_env()
        self.assertTrue(summary["project_id_present"])
        self.assertNotIn("my-gcp-project-xyz", str(summary))
        self.assertFalse(summary["secrets_printed"])
        for key in _REPO_ENV_KEYS:
            if key in summary.get("env_presence", {}):
                self.assertIn(summary["env_presence"][key], ("set", "unset"))

    def test_output_path_validator(self) -> None:
        ok = OUTPUT_IMAGES_DIR + "keysuri_global_canary.jpg"
        self.assertEqual(validate_keysuri_image_output_path(ok), [])
        for bad in (
            "assets/keysuri/out.jpg",
            "static/email/x.jpg",
            "ops/preview/x.jpg",
            "../output/keysuri_preview/image_canary/x.jpg",
            "data:image/png;base64,abc",
            "output/other/x.jpg",
        ):
            self.assertTrue(validate_keysuri_image_output_path(bad), msg=bad)

    def test_resolve_reference_asset(self) -> None:
        p01, i01 = resolve_keysuri_reference_asset_path("01")
        self.assertEqual(p01, REFERENCE_ASSET_DEFAULT)
        self.assertEqual(i01, [])
        p02, _ = resolve_keysuri_reference_asset_path("02")
        self.assertEqual(p02, REFERENCE_ASSET_FULL_BODY)

    def test_program_guards(self) -> None:
        self.assertTrue(program_id_is_allowed("keysuri_global_tech"))
        self.assertTrue(program_id_is_allowed("keysuri_korea_tech"))
        self.assertFalse(program_id_is_allowed("today_geenee"))
        self.assertTrue(program_id_is_forbidden("today_geenee"))
        self.assertTrue(program_id_is_forbidden("tomorrow_geenee"))
        self.assertTrue(program_id_is_forbidden("tomorrow_genie"))


if __name__ == "__main__":
    unittest.main()
