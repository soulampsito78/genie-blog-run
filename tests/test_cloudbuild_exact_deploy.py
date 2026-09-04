from __future__ import annotations

import unittest
from pathlib import Path

import yaml


class CloudBuildExactDeployTests(unittest.TestCase):
    def test_main_build_deploys_verified_digest_without_early_traffic(self) -> None:
        config = yaml.safe_load(
            (Path(__file__).resolve().parents[1] / "cloudbuild.yaml").read_text(
                encoding="utf-8"
            )
        )
        steps = config["steps"]
        self.assertEqual(
            [step["id"] for step in steps],
            [
                "Build",
                "ProductRegressionGate",
                "Push",
                "ResolveDigest",
                "DeployExact",
                "PromoteExact",
            ],
        )

        gate = steps[1]
        self.assertEqual(gate["waitFor"], ["Build"])
        self.assertIn("--network=none", gate["args"])
        self.assertIn("scripts/run_product_regression_gate.py", gate["args"])
        self.assertEqual(steps[2]["waitFor"], ["ProductRegressionGate"])

        resolve_script = steps[3]["args"][-1]
        deploy_script = steps[4]["args"][-1]
        promote_script = steps[5]["args"][-1]
        self.assertIn("image_summary.fully_qualified_digest", resolve_script)
        self.assertIn('--image="$$immutable_image"', deploy_script)
        self.assertIn("--no-traffic", deploy_script)
        self.assertIn("status.imageDigest", deploy_script)
        self.assertIn('test "$$deployed_image" = "$$immutable_image"', deploy_script)
        self.assertIn("printf '%s\\n'", deploy_script)
        self.assertIn('--to-revisions="$$revision_name=100"', promote_script)
        self.assertNotIn("--to-latest", promote_script)
        self.assertNotIn("--memory", deploy_script + promote_script)


if __name__ == "__main__":
    unittest.main()
