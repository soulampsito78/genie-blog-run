"""Reissued body previews may use only the matching recorded parent's assets."""
from unittest.mock import Mock

import pytest
import admin_preview_assets as assets

PARENT = '20261106_173002_keysuri_korea_tech_88f8819f'
CHILD = '20261106_173708_keysuri_korea_tech_fc8f6e99'
BUCKET = 'test-bucket'


@pytest.fixture
def candidates(monkeypatch):
    parent = {'run_id': PARENT, 'mode': 'keysuri_korea_tech',
              'top_image_cid': 'top', 'bottom_image_cid': 'bottom',
              'korea_generated_image_gcs_bucket': BUCKET,
              'korea_generated_top_gcs_object': f'admin_runs/{PARENT}.images/top.jpg',
              'korea_generated_bottom_gcs_object': f'admin_runs/{PARENT}.images/bottom.jpg'}
    child = dict(parent, run_id=CHILD, regen_parent_run_id=PARENT,
                 regen_type='body_only', regen_preserved_images=True,
                 reissue_body_only_image_reused=True)
    monkeypatch.setattr(assets, 'admin_artifact_bucket_name', lambda: BUCKET)
    monkeypatch.setattr(assets, 'admin_artifact_gcs_prefix', lambda: 'admin_runs')
    monkeypatch.setattr(assets, '_local_path_for_slot', lambda *args: None)
    loader = Mock(return_value=parent)
    monkeypatch.setattr(assets, 'load_run_artifact', loader)
    return child, parent, loader


def test_verified_parent_reused_for_both_slots(candidates):
    child, parent, loader = candidates
    found = assets.preview_assets_for_run(CHILD, child)
    assert {slot: value.object_name for slot, value in found.items()} == {
        'top': parent['korea_generated_top_gcs_object'],
        'bottom': parent['korea_generated_bottom_gcs_object']}
    loader.assert_called_once_with(PARENT)


@pytest.mark.parametrize('field,value', [
    ('regen_type', 'full'), ('regen_preserved_images', False),
    ('reissue_body_only_image_reused', False), ('regen_parent_run_id', '../foreign'),
    ('mode', 'today_genie'), ('korea_generated_image_gcs_bucket', 'foreign'),
])
def test_unverified_parent_is_rejected(candidates, field, value):
    child, _, _ = candidates
    child[field] = value
    assert assets.preview_assets_for_run(CHILD, child) == {}


def test_wrong_slot_or_cid_is_rejected(candidates):
    child, parent, _ = candidates
    child['top_image_cid'] = 'other'
    child['korea_generated_bottom_gcs_object'] = parent['korea_generated_top_gcs_object']
    assert assets.preview_assets_for_run(CHILD, child) == {}
