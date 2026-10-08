"""Synthetic-only additive observation and legacy-value compatibility tests."""
import copy
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from genie_cost_estimate import estimate_genie_generation_cost
from keysuri_bottom_shot_generation import generate_keysuri_korea_bottom_v6
from service_full_run_contract import ServiceImageOutcome, TodayGenieServiceImageBundle, build_service_artifact_fields
from service_image_api import invoke_vertex_image_generation

CALCULATED = 'successful_output_count_times_fixed_tokens_per_output'


class ImageUsageProvenanceTests(unittest.TestCase):
    def estimate(self, image_usage):
        return estimate_genie_generation_cost(
            {'prompt_token_count': 100, 'candidates_token_count': 20,
             'thoughts_token_count': 5, 'total_token_count': 125},
            service_family='keysuri', text_model='gemini-2.5-flash',
            image_model='gemini-2.5-flash-image', image_usage=image_usage)

    def test_wrapper_marks_fixed_calculation_not_response_measurement(self):
        with tempfile.TemporaryDirectory() as tmp:
            def generate(**kwargs):
                kwargs['output_path'].write_bytes(b'synthetic-output')
            outcome = invoke_vertex_image_generation(prompt='synthetic', output_path=Path(tmp)/'result.jpg',
                project_id='synthetic-project', model_name='gemini-2.5-flash-image', generate_fn=generate)
        self.assertEqual(outcome.image_output_tokens, 1290)
        self.assertEqual(outcome.image_evidence_source, 'runtime_vertex_response_image_parts')
        p = outcome.cost_usage().get('image_token_provenance') or {}
        self.assertEqual(p.get('recorded_output_tokens_source'), CALCULATED)
        self.assertEqual(p.get('calculated_output_tokens'), 1290)
        self.assertIsNone(p.get('response_measured_output_tokens'))
        self.assertEqual(p.get('response_measured_usage_source'), 'UNKNOWN')

    def test_estimator_calculation_fallback_is_explicit(self):
        result = self.estimate({'image_successful_output_count': 2})
        p = result['image_usage'].get('image_token_provenance') or {}
        self.assertEqual(result['image_usage']['image_output_tokens'], 2580)
        self.assertEqual(p.get('recorded_output_tokens_source'), CALCULATED)
        self.assertEqual(p.get('calculated_output_tokens'), 2580)
        self.assertIsNone(p.get('response_measured_output_tokens'))

    def test_missing_bottom_reference_has_unknown_measurement(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = generate_keysuri_korea_bottom_v6(repo_root=Path(tmp), output_path=Path(tmp)/'result.jpg',
                primary_reference_path=Path(tmp)/'absent', secondary_reference_path=Path(tmp)/'absent2',
                weather_condition='clear', project_id='synthetic-project')
        self.assertFalse(result.ok)
        self.assertEqual(result.metadata['bottom_shot_image_request_count'], 0)
        p = result.metadata.get('bottom_shot_image_token_provenance') or {}
        self.assertEqual(p.get('response_measured_usage_source'), 'UNKNOWN')
        self.assertIsNone(p.get('response_measured_output_tokens'))

    def test_legacy_outcome_missing_tokens_is_unknown_not_zero(self):
        usage = ServiceImageOutcome().cost_usage()
        p = usage.get('image_token_provenance') or {}
        self.assertEqual(p.get('recorded_output_tokens_source'), 'UNKNOWN')
        self.assertIsNone(p.get('recorded_output_tokens'))
        self.assertIsNone(p.get('calculated_output_tokens'))
        self.assertIsNone(p.get('response_measured_output_tokens'))

    def test_legacy_supplied_numeric_value_not_promoted_to_measured(self):
        result = self.estimate({'image_successful_output_count': 1, 'image_output_tokens': 1290,
                                'image_evidence_source': 'runtime_vertex_response_image_parts'})
        p = result['image_usage']['image_token_provenance']
        self.assertEqual(p['recorded_output_tokens'], 1290)
        self.assertEqual(p['recorded_output_tokens_source'], 'UNKNOWN')
        self.assertIsNone(p['response_measured_output_tokens'])
        self.assertIsNone(p['calculated_output_tokens'])

    def test_failed_request_measurement_and_actual_charge_remain_unknown(self):
        result = self.estimate({'image_successful_output_count': 0, 'image_failed_request_count': 1})
        self.assertIsNone(result['image_usage']['image_token_provenance']['response_measured_output_tokens'])
        self.assertIsNone(result['components']['image_billed_cost_usd'])
        self.assertIsNone(result['total_cost_usd'])
        self.assertTrue(result['estimate_only'])

    def test_explicit_response_measurement_is_separate_and_zero_preserved(self):
        from image_usage_provenance import image_token_provenance
        for measured in (0, 77):
            p = image_token_provenance(1290, calculated_tokens=1290, tokens_per_output=1290,
                                      response_measured_tokens=measured, response_usage_source='response_usage_metadata.synthetic')
            self.assertEqual(p['calculated_output_tokens'], 1290)
            self.assertEqual(p['response_measured_output_tokens'], measured)
            self.assertEqual(p['response_measured_usage_source'], 'response_usage_metadata.synthetic')

    def test_unknown_measurement_does_not_gain_source(self):
        from image_usage_provenance import image_token_provenance
        p = image_token_provenance(1290, response_usage_source='runtime_vertex_response_image_parts')
        self.assertIsNone(p['response_measured_output_tokens'])
        self.assertEqual(p['response_measured_usage_source'], 'UNKNOWN')

    def test_component_missing_measurement_does_not_become_zero(self):
        from image_usage_provenance import image_token_provenance, merge_image_token_provenance
        measured = image_token_provenance(1290, calculated_tokens=1290, response_measured_tokens=0,
                                         response_usage_source='response_usage_metadata.synthetic')
        missing = image_token_provenance(None)
        original = copy.deepcopy([measured, missing])
        merged = merge_image_token_provenance([measured, missing], 1290)
        self.assertIsNone(merged['calculated_output_tokens'])
        self.assertIsNone(merged['response_measured_output_tokens'])
        self.assertEqual(merged['response_measured_usage_source'], 'UNKNOWN')
        self.assertEqual([measured, missing], original)
        self.assertEqual(merged['components'][0]['response_measured_output_tokens'], 0)
        self.assertIsNone(merged['components'][1]['response_measured_output_tokens'])

    def test_complete_components_preserve_calculation_and_measurement_separately(self):
        from image_usage_provenance import image_token_provenance, merge_image_token_provenance
        records = [image_token_provenance(1290, calculated_tokens=1290, response_measured_tokens=0,
                                         response_usage_source='response_usage_metadata.synthetic'),
                   image_token_provenance(1290, calculated_tokens=1290, response_measured_tokens=7,
                                         response_usage_source='response_usage_metadata.synthetic')]
        p = merge_image_token_provenance(records, 2580)
        self.assertEqual(p['calculated_output_tokens'], 2580)
        self.assertEqual(p['response_measured_output_tokens'], 7)
        self.assertEqual(p['response_measured_usage_source'], 'response_usage_metadata.complete_components')

    def test_fallback_preserves_upstream_measurement_and_does_not_change_price_basis(self):
        from image_usage_provenance import image_token_provenance
        image_usage = {'image_successful_output_count': 1,
                       'image_token_provenance': image_token_provenance(None, response_measured_tokens=0,
                                                response_usage_source='response_usage_metadata.synthetic')}
        before = copy.deepcopy(image_usage)
        result = self.estimate(image_usage)
        self.assertEqual(result['image_usage']['image_output_tokens'], 1290)
        p = result['image_usage']['image_token_provenance']
        self.assertEqual(p['response_measured_output_tokens'], 0)
        self.assertEqual(p['upstream_provenance'], before['image_token_provenance'])
        self.assertEqual(image_usage, before)

    def test_bundle_provenance_partial_does_not_claim_complete_sum(self):
        from image_usage_provenance import image_token_provenance
        top = ServiceImageOutcome(image_output_tokens=1290,
            image_token_provenance=image_token_provenance(1290, calculated_tokens=1290))
        bottom = ServiceImageOutcome(image_output_tokens=None)
        meta = build_service_artifact_fields(run_id='synthetic', mode='today_genie',
            trigger_source='synthetic', validation_result=None,
            image_bundle=TodayGenieServiceImageBundle(top=top, bottom=bottom))
        self.assertEqual(meta['image_output_tokens'], 1290)
        self.assertIsNone(meta['image_token_provenance']['calculated_output_tokens'])
        self.assertIsNone(meta['image_token_provenance']['response_measured_output_tokens'])

    def test_korea_cost_aggregation_statements_preserve_legacy_metrics(self):
        import ast
        import keysuri_service_full_run as module
        from image_usage_provenance import image_token_provenance
        tree = ast.parse(Path(module.__file__).read_text())
        block = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                     and any(isinstance(child, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == 'bottom_metric_map' for t in child.targets)
                     for child in node.body))
        values = {'image_request_count': 1, 'image_successful_output_count': 1,
                  'image_failed_request_count': 0, 'image_retry_count': 0, 'image_output_tokens': 1290,
                  'image_token_provenance': image_token_provenance(1290, calculated_tokens=1290)}
        bottom = {'bottom_shot_image_request_count': 1, 'bottom_shot_successful_output_count': 1,
                  'bottom_shot_image_output_tokens': 1290,
                  'bottom_shot_image_token_provenance': image_token_provenance(1290, calculated_tokens=1290)}
        scope = {'pid': module.PROGRAM_KOREA, 'PROGRAM_KOREA': module.PROGRAM_KOREA,
                 'image_usage': values, 'bottom_image_meta': bottom}
        exec(compile(ast.Module(body=[block], type_ignores=[]), '<isolated aggregation statements>', 'exec'), scope)
        self.assertEqual(values['image_output_tokens'], 2580)
        self.assertEqual(values['image_request_count'], 2)
        self.assertEqual(values['image_successful_output_count'], 2)
        self.assertEqual(values['image_retry_count'], 0)
        self.assertEqual(values['image_token_provenance']['calculated_output_tokens'], 2580)
        self.assertIsNone(values['image_token_provenance']['response_measured_output_tokens'])

    def test_bottom_success_and_failure_keep_metrics_and_measurement_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary, secondary = root/'primary.jpg', root/'secondary.jpg'
            primary.write_bytes(b'synthetic-reference')
            secondary.write_bytes(b'synthetic-reference')
            def generate(**kwargs):
                kwargs['output_path'].write_bytes(b'synthetic-output')
                return kwargs['output_path']
            common = dict(repo_root=root, output_path=root/'out.jpg', weather_condition='clear',
                          primary_reference_path=primary, secondary_reference_path=secondary,
                          wardrobe_variant=1, pose_variant=1, project_id='synthetic-project')
            result = generate_keysuri_korea_bottom_v6(**common, generate_fn=generate)
            self.assertTrue(result.ok)
            self.assertEqual(result.metadata['bottom_shot_image_output_tokens'], 1290)
            p = result.metadata['bottom_shot_image_token_provenance']
            self.assertEqual(p['calculated_output_tokens'], 1290)
            self.assertEqual(p['recorded_output_tokens_source'], CALCULATED)
            self.assertIsNone(p['response_measured_output_tokens'])
            def fail(**kwargs):
                raise RuntimeError('synthetic failure')
            failed = generate_keysuri_korea_bottom_v6(**common, generate_fn=fail)
            self.assertFalse(failed.ok)
            self.assertEqual(failed.metadata['bottom_shot_failed_request_count'], 1)
            self.assertEqual(failed.metadata['bottom_shot_retry_count'], 0)
            self.assertIsNone(failed.metadata['bottom_shot_image_token_provenance']['response_measured_output_tokens'])

    def test_missing_measurement_source_cannot_make_aggregate_known(self):
        from image_usage_provenance import image_token_provenance, merge_image_token_provenance
        row = image_token_provenance(1290, response_measured_tokens=0, response_usage_source=None)
        self.assertEqual(row['response_measured_output_tokens'], 0)
        self.assertEqual(row['response_measured_usage_source'], 'UNKNOWN')
        merged = merge_image_token_provenance([row], 1290)
        self.assertIsNone(merged['response_measured_output_tokens'])

    def test_image_parts_are_not_a_token_measurement_source_even_with_numeric_value(self):
        from image_usage_provenance import image_token_provenance, merge_image_token_provenance
        row = image_token_provenance(1290, response_measured_tokens=1290,
                                    response_usage_source='runtime_vertex_response_image_parts')
        self.assertEqual(row['response_measured_output_tokens'], 1290)
        self.assertEqual(row['response_measured_usage_source'], 'UNKNOWN')
        merged = merge_image_token_provenance([row], 1290)
        self.assertIsNone(merged['response_measured_output_tokens'])

    def test_malformed_optional_provenance_does_not_change_existing_estimate(self):
        for invalid in (None, 'invalid provenance', 7):
            with self.subTest(invalid=invalid):
                result = self.estimate({'image_successful_output_count': 1, 'image_token_provenance': invalid})
                self.assertNotEqual(result['cost_estimate_status'], 'error')
                self.assertEqual(result['image_usage']['image_output_tokens'], 1290)
                self.assertIsNone(result['components']['image_billed_cost_usd'])
                self.assertIsNone(result['image_usage']['image_token_provenance']['response_measured_output_tokens'])

    def test_all_legacy_estimate_fields_match_exact_base(self):
        base_path = os.environ.get('PROVENANCE_TEST_BASE_MODULE')
        if not base_path:
            self.skipTest('Exact-base private harness path is not part of portable fixtures')
        spec = importlib.util.spec_from_file_location('original_cost_estimate', base_path)
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        usage = {'prompt_token_count': 100, 'candidates_token_count': 20,
                 'thoughts_token_count': 5, 'total_token_count': 125}
        prices = {'GENIE_COST_GEMINI_2_5_FLASH_INPUT_USD_PER_1M_TOKENS': '0.3',
                  'GENIE_COST_GEMINI_2_5_FLASH_OUTPUT_USD_PER_1M_TOKENS': '2.5',
                  'GENIE_COST_GEMINI_2_5_FLASH_IMAGE_OUTPUT_IMAGE_USD_PER_1M_TOKENS': '30'}
        def without_provenance(value):
            if isinstance(value, dict):
                return {k: without_provenance(v) for k,v in value.items() if k != 'image_token_provenance'}
            if isinstance(value, list):
                return [without_provenance(v) for v in value]
            return value
        for image in ({'image_successful_output_count': 2},
                      {'image_successful_output_count': 1, 'image_output_tokens': 1290},
                      {'image_successful_output_count': 0, 'image_failed_request_count': 1},
                      {'image_successful_output_count': 0}, None):
            with self.subTest(image=image), patch.dict(os.environ, prices, clear=True):
                kwargs = dict(service_family='keysuri', text_model='gemini-2.5-flash',
                              image_model='gemini-2.5-flash-image', image_usage=image)
                self.assertEqual(without_provenance(estimate_genie_generation_cost(usage, **kwargs)),
                                 old.estimate_genie_generation_cost(usage, **kwargs))


if __name__ == '__main__':
    unittest.main(verbosity=2)
