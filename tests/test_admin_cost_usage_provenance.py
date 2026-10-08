"""Synthetic-only cost JSON propagation; the CSV contract stays unchanged."""
import copy
import importlib.util
import json
import os
import unittest
from unittest.mock import patch

import admin_cost_ledger as ledger


def meta_fixture():
    return {
        'run_id': '20260701_183000_keysuri_korea_tech_abcdef01',
        'created_at': '2026-07-01T18:30:00+09:00', 'mode': 'keysuri_korea_tech',
        'artifact_url': 'https://example.test/synthetic-artifact',
        'cost_estimate': {
            'estimate_only': True, 'service_family': 'keysuri',
            'usage': {'prompt_token_count': 100, 'candidates_token_count': 20,
                      'thoughts_token_count': None, 'generated_image_count': 1},
            'image_usage': {'image_output_tokens': 1290, 'image_successful_output_count': 1,
                            'image_failed_request_count': 0, 'image_retry_count': 0,
                            'image_token_provenance': {
                                'recorded_output_tokens': 1290,
                                'recorded_output_tokens_source': 'successful_output_count_times_fixed_tokens_per_output',
                                'calculated_output_tokens': 1290,
                                'response_measured_output_tokens': None,
                                'response_measured_usage_source': 'UNKNOWN',
                                'components': [{'response_measured_output_tokens': 0,
                                                'response_measured_usage_source': 'response_usage_metadata.synthetic'},
                                               {'response_measured_output_tokens': None,
                                                'response_measured_usage_source': 'UNKNOWN'}]}},
            'components': {'image_cost_usd': 0.0387, 'image_billed_cost_usd': None},
            'total_cost_usd': 0.0387, 'total_cost_krw': None,
            'billing_reconciliation_status': 'billing_export_unavailable'}}


class AdminCostUsageProvenanceTests(unittest.TestCase):
    def test_record_deep_copies_provenance_and_json_preserves_zero_and_null(self):
        meta = meta_fixture()
        before = copy.deepcopy(meta)
        record = ledger.build_cost_record(meta)
        self.assertEqual(meta, before)
        expected = before['cost_estimate']['image_usage']['image_token_provenance']
        self.assertEqual(record.get('image_token_provenance'), expected)
        roundtrip = json.loads(json.dumps(record))
        self.assertEqual(roundtrip['image_token_provenance'], expected)
        self.assertEqual(roundtrip['image_token_provenance']['components'][0]['response_measured_output_tokens'], 0)
        self.assertIsNone(roundtrip['image_token_provenance']['components'][1]['response_measured_output_tokens'])
        record['image_token_provenance']['components'][0]['response_measured_output_tokens'] = 99
        self.assertEqual(meta, before)
        self.assertEqual(record['image_output_tokens'], 1290)
        self.assertIsNone(record['image_billed_cost_usd'])

    def test_missing_nonmapping_and_empty_provenance_preserve_meaning(self):
        for value in (None, 'invalid', 7):
            with self.subTest(value=value):
                meta = meta_fixture()
                meta['cost_estimate']['image_usage']['image_token_provenance'] = value
                record = ledger.build_cost_record(meta)
                self.assertNotIn('image_token_provenance', record)
                self.assertIsNone(record['image_billed_cost_usd'])
        meta = meta_fixture()
        meta['cost_estimate']['image_usage']['image_token_provenance'] = {}
        self.assertEqual(ledger.build_cost_record(meta).get('image_token_provenance'), {})

    def test_no_numeric_or_price_field_changes_and_csv_schema_identical_to_base(self):
        base_path = os.environ.get('PROVENANCE_TEST_BASE_LEDGER')
        if not base_path:
            self.skipTest('Exact-base private compatibility harness is not part of public fixtures')
        spec = importlib.util.spec_from_file_location('original_cost_ledger', base_path)
        original = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(original)
        meta = meta_fixture()
        record, prior = ledger.build_cost_record(meta), original.build_cost_record(meta)
        without_new = {k:v for k,v in record.items() if k != 'image_token_provenance'}
        self.assertEqual(without_new, prior)
        self.assertEqual(ledger.COST_LEDGER_COLUMNS, original.COST_LEDGER_COLUMNS)
        self.assertEqual(ledger.cost_record_to_csv_row(record), original.cost_record_to_csv_row(prior))
        self.assertNotIn('image_token_provenance', ledger.COST_LEDGER_COLUMNS)

    def test_mock_json_persistence_keeps_provenance_and_csv_does_not_gain_column(self):
        uploads = {}
        def upload(key, text, *, content_type):
            uploads[key] = (text, content_type)
        meta = meta_fixture()
        before = copy.deepcopy(meta)
        with patch.dict(os.environ, {'GENIE_ADMIN_ARTIFACT_BUCKET': 'synthetic-bucket'}), \
             patch.object(ledger, '_gcs_upload_text', side_effect=upload), \
             patch.object(ledger, '_gcs_download_text', return_value=None):
            result = ledger.save_cost_record_best_effort(meta)
        self.assertTrue(result['cost_record_saved'])
        self.assertTrue(result['cost_ledger_saved'])
        body = next(text for key,(text,_) in uploads.items() if key.endswith('.cost.json'))
        csv = next(text for key,(text,_) in uploads.items() if key.endswith('.csv'))
        self.assertEqual(json.loads(body)['image_token_provenance'], before['cost_estimate']['image_usage']['image_token_provenance'])
        self.assertNotIn('image_token_provenance', csv.splitlines()[0])
        self.assertEqual(meta, before)

    def test_missing_counts_do_not_become_zero_in_json_record(self):
        meta = meta_fixture()
        meta['cost_estimate']['image_usage'].update(image_output_tokens=None,
            image_failed_request_count=None, image_retry_count=None)
        record = ledger.build_cost_record(meta)
        self.assertIsNone(record['image_output_tokens'])
        self.assertIsNone(record['image_failed_request_count'])
        self.assertIsNone(record['image_retry_count'])
        self.assertIsNone(record['image_billed_cost_usd'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
