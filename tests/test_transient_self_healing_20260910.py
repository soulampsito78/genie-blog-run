"""2026-09-10 Today outage: A–L, offline provider and delivery probes only."""
from __future__ import annotations

import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime
from unittest import mock

import pytest
from fastapi import HTTPException
from google.api_core import exceptions as gexc

import main
import natural_run_incident_store as store
import natural_run_recovery as recovery
import natural_run_watchdog as watchdog
import orchestrator
from auto_remediation import plan_auto_remediation
from transient_infrastructure import automatic_recovery_candidate, vertex_failure_evidence

IID = '2026-09-10_today_genie_06-30'
RID = '20260910_063029_today_genie_72848cab'
CHILD = '20260910_070000_today_genie_recovery01'
NOW = datetime(2026, 9, 10, 6, 46, tzinfo=store.KST)
ACTIVATION = datetime(2026, 9, 10, 0, 0, tzinfo=store.KST)


def failed_artifact(**changes):
    row = dict(run_id=RID, mode='today_genie', execution_class='natural_scheduled',
               scheduled_slot='06:30', kst_schedule_date='2026-09-10',
               trigger_source='scheduled_owner_review', artifact_status='failed',
               artifact_usable=False, response_status=500, validation_result=None,
               first_failed_stage='model_generation', email_sent=False,
               owner_review_status='pending_review', customer_delivery_status='not_sent',
               policy={'send_email': False, 'suppress_external': True},
               infrastructure_failure=vertex_failure_evidence(gexc.TooManyRequests('429'),
                    attempt_count=3, slept_seconds=16, max_attempts=3))
    row.update(changes)
    return row


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('GENIE_ARTIFACT_BUCKET', '')
    monkeypatch.setenv('GENIE_ADMIN_ARTIFACT_BUCKET', '')
    monkeypatch.setenv('GENIE_AUTO_REMEDIATION', '1')
    monkeypatch.setattr(store, 'incidents_local_dir', lambda: tmp_path)
    monkeypatch.setattr(store, '_uses_gcs', lambda: False)
    return tmp_path


def incident_for(row):
    result = watchdog.diagnose_program_sla(program_id='today_genie', artifacts=[row], now=NOW)
    assert result and result['original_run_id'] == RID
    return result


class Model:
    def __init__(self, values):
        self.values = iter(values)
        self.calls = 0

    def generate_content(self, *args, **kwargs):
        self.calls += 1
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return value


def invoke(model):
    return main._generate_content_with_transient_retry(model, 'bounded prompt', generation_config=None, mode='today_genie')


def test_a_429_then_success_same_logical_model_call(monkeypatch):
    monkeypatch.setattr(main.time, 'sleep', lambda _: None)
    model = Model([gexc.TooManyRequests('429'), 'ok'])
    assert invoke(model) == 'ok'
    assert model.calls == 2


def test_b_exhaustion_survives_api_and_artifact_boundary(isolated, monkeypatch):
    monkeypatch.setattr(main.time, 'sleep', lambda _: None)
    model = Model([gexc.TooManyRequests('429')] * 3)
    monkeypatch.setattr(main, '_generate_impl', lambda job: invoke(model))
    with pytest.raises(HTTPException) as error:
        main.generate(main.JobRequest(type='today_genie'))
    assert error.value.status_code == 500
    payload = {'detail': error.value.detail}
    result = orchestrator.OrchestrationResult(
        decision=orchestrator.decide_publishing_actions('today_genie', None, None, [], None),
        reason_summary='vertex_transient_exhausted', response_status=500,
        response_data=payload, mode='today_genie')
    meta = orchestrator.build_run_artifact_metadata(result, run_id=RID, email_sent=False,
               execution_class='natural_scheduled', scheduled_slot='06:30', trigger_source='scheduled_owner_review')
    assert meta['infrastructure_failure']['attempt_count'] == 3
    assert meta['artifact_usable'] is False
    assert meta['model_call_evidence'][0]['internal_retry_count'] == 2
    assert meta['policy']['suppress_external']
    assert meta['validation_result'] is None
    assert model.calls == 3
    import admin_store
    monkeypatch.setattr(admin_store, 'admin_runs_dir', lambda: isolated)
    meta['kst_schedule_date'] = '2026-09-10'
    admin_store.save_run_artifact(meta, email_html='')
    persisted = admin_store.load_run_artifact(RID, normalize=False)
    assert persisted['artifact_status'] == 'failed'
    assert automatic_recovery_candidate(incident_for(persisted), persisted, now=NOW)


@pytest.mark.parametrize('exc', [gexc.InvalidArgument, gexc.PermissionDenied, gexc.NotFound, gexc.Unauthenticated])
def test_c_permanent_once_and_no_auto(isolated, monkeypatch, exc):
    model = Model([exc('permanent')])
    with pytest.raises(exc):
        invoke(model)
    assert model.calls == 1
    row = failed_artifact(infrastructure_failure=vertex_failure_evidence(exc('permanent'), attempt_count=1, slept_seconds=0, max_attempts=3))
    assert not automatic_recovery_candidate(incident_for(row), row, now=NOW)


def test_d_failed_natural_never_satisfies_sla(isolated):
    row = failed_artifact()
    assert watchdog._natural_completer_exists([row], program_id='today_genie', kst_date='2026-09-10', scheduled_slot='06:30') is None
    assert incident_for(row)['original_run_id'] == RID


@pytest.mark.parametrize('exc', [gexc.TooManyRequests, gexc.ResourceExhausted, gexc.InternalServerError, gexc.BadGateway, gexc.ServiceUnavailable, gexc.GatewayTimeout, gexc.DeadlineExceeded])
def test_e_allowed_classes_after_grace_only(isolated, exc):
    row = failed_artifact(infrastructure_failure=vertex_failure_evidence(exc('transient'), attempt_count=3, slept_seconds=16, max_attempts=3))
    inc = incident_for(row)
    assert automatic_recovery_candidate(inc, row, now=NOW)
    assert not automatic_recovery_candidate(inc, row, now=NOW.replace(minute=44))
    assert not automatic_recovery_candidate(inc, row, now=NOW.replace(day=11))


def test_efjk_watchdog_concurrent_one_child_no_recursion_or_customer_send(isolated, monkeypatch):
    row = failed_artifact()
    # A reported incident prevents unrelated report-SMTP race in this test.
    inc = incident_for(row)
    inc.update(status='reported', report_sent_at=NOW.isoformat())
    store.save_incident(inc)
    monkeypatch.setattr('admin_store.load_run_artifact', lambda *a, **k: copy.deepcopy(row))
    stamped = {}
    monkeypatch.setattr('admin_store.update_run_artifact', lambda rid, fn: fn(stamped))
    generated = []

    def run(mode, **kwargs):
        generated.append(kwargs)
        assert store.load_incident(IID)['automatic_recovery_attempt_count'] == 1
        assert store.load_incident(IID)['recovery_lease_token']
        assert kwargs['execution_class'] == 'recovery'
        assert kwargs['send_owner_email'] is True
        assert kwargs['original_incident_id'] == IID
        return CHILD, mock.Mock(response_data={'validation_result': None}), False

    monkeypatch.setattr(orchestrator, 'execute_orchestrator_run', run)
    def poll():
        return watchdog.run_watchdog_poll(artifacts=[row], now=NOW, activated_at=ACTIVATION,
                         programs=['today_genie'], send_fn=lambda **k: True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(lambda _: poll(), range(2)))
    poll()  # Recovery child failed: still no recursion / later reattempt.
    assert len(generated) == 1
    assert all(o['customer_send'] == 0 for o in outputs)
    assert stamped['customer_delivery_status'] == 'not_sent'
    assert stamped['approve_customer_final_send'] is False
    assert stamped['owner_review_status'] == 'pending_review'
    assert store.load_incident(IID)['automatic_recovery_attempt_count'] == 1
    assert store.acquire_recovery_lease(IID, automatic=True) is None
    assert store.acquire_recovery_lease(IID) is None  # automatic budget cannot be reopened via Admin


@pytest.mark.parametrize('program,slot,hour', [('today_genie','06:30',7), ('keysuri_global_tech','12:30',13), ('keysuri_korea_tech','18:30',19)])
def test_gl_success_paths_zero_recovery(isolated, monkeypatch, program, slot, hour):
    row = failed_artifact(mode=program, scheduled_slot=slot, run_id=f'20260910_{hour:02d}0000_{program}_success',
        trigger_source='scheduled_owner_review' if program=='today_genie' else 'scheduled_service_full_run',
        artifact_status='emailed', validation_result='pass', email_sent=True,
        runtime_safety_status='RUNTIME_SAFETY_PASS', customer_surface_status='CUSTOMER_SURFACE_PASS')
    with mock.patch.object(recovery, 'execute_approved_recovery') as run:
        watchdog.run_watchdog_poll(artifacts=[row], programs=[program], now=NOW.replace(hour=hour),
                                 activated_at=ACTIVATION, send_fn=lambda **k: True)
    run.assert_not_called()


@pytest.mark.parametrize('change', [
    {'execution_class':'preflight'}, {'first_failed_stage':'preflight'},
    {'execution_class':'recovery'}, {'parent_run_id':RID}, {'issue_codes':['source_corruption']},
    {'issue_codes':['security_sensitive']}, {'validation_result':'block'},
    {'validation_result':'draft_only', 'artifact_usable':True},
    {'customer_surface_status':'PRODUCT_REVIEW_REQUIRED','product_surface_issue_codes':['customer_surface_duplicate_filler']},
    {'infrastructure_failure':None}, {'artifact_usable':None}, {'customer_delivery_status':None},
    {'email_sent':True}, {'approve_customer_final_send':True}, {'scheduled_slot':'12:30'},
    {'trigger_source':'qa_manual'}, {'owner_review_status':'approved'},
])
def test_hi_unknown_validation_product_preflight_and_children_excluded(isolated, change):
    inc = incident_for(failed_artifact())
    assert not automatic_recovery_candidate(inc, failed_artifact(**change), now=NOW)


def test_i_content_auto_remediation_separate(isolated):
    row = failed_artifact()
    assert not plan_auto_remediation(row).eligible
    row.update(artifact_status='stored', artifact_usable=True, validation_result='draft_only',
               runtime_safety_status='REVIEW_REQUIRED', issue_codes=['customer_surface_duplicate_filler'],
               customer_surface_status='PRODUCT_REVIEW_REQUIRED', response_status=200,
               first_failed_stage='validation', infrastructure_failure=None)
    plan = plan_auto_remediation(row)
    assert plan.eligible, plan
    assert not automatic_recovery_candidate(incident_for(failed_artifact()), row, now=NOW)


def test_recovery_transport_uncertainty_never_reposts(monkeypatch):
    import urllib.error
    with mock.patch('urllib.request.urlopen', side_effect=urllib.error.URLError('timeout')) as request:
        result = orchestrator.run_genie_job('today_genie', transport_retries=0)
    assert request.call_count == 1 and result.response_status is None


@pytest.mark.parametrize('value', ['999999999','inf','nan','-4'])
def test_retry_config_has_hard_attempt_and_sleep_caps(monkeypatch, value):
    for key in ('GENIE_VERTEX_RETRY_ATTEMPTS','GENIE_VERTEX_RETRY_BASE_DELAY_SEC','GENIE_VERTEX_RETRY_MAX_TOTAL_DELAY_SEC'):
        monkeypatch.setenv(key, value)
    assert 1 <= main._vertex_retry_attempts() <= 3
    assert 0 <= main._vertex_retry_base_delay_sec() <= 15
    assert 0 <= main._vertex_retry_max_total_delay_sec() <= 45


def test_f_gcs_cas_between_independent_instances_and_stale_upsert(isolated, monkeypatch):
    inc = incident_for(failed_artifact())
    inc['status'] = 'reported'
    # Both instances read the same incident, with no process-wide lock.
    monkeypatch.setattr(store, '_LOCK', nullcontext())
    monkeypatch.setattr(store, 'load_incident', lambda _: copy.deepcopy(inc))
    monkeypatch.setattr(store, 'save_incident', lambda _: IID)
    monkeypatch.setattr(store, '_uses_gcs', lambda: True)
    barrier, lock = threading.Barrier(2), threading.Lock()
    records = {}

    class Blob:
        generation = None
        def download_as_text(self, **kwargs):
            with lock:
                snapshot = copy.deepcopy(records.get('claim'))
            if snapshot is None:
                barrier.wait(timeout=5)
                raise gexc.NotFound('absent')
            self.generation = snapshot[0]
            return snapshot[1]
        def upload_from_string(self, body, *, if_generation_match, **kwargs):
            with lock:
                current = records.get('claim', (0, ''))[0]
                if current != if_generation_match:
                    raise gexc.PreconditionFailed('race lost')
                records['claim'] = (current+1, body)

    client = mock.Mock()
    client.bucket.return_value.blob.side_effect = lambda key: Blob()
    monkeypatch.setattr(store, '_gcs_storage_client', lambda: client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = list(pool.map(lambda _: store.acquire_recovery_lease(IID, automatic=True), range(2)))
    assert sum(token is not None for token in leases) == 1
    # Stale incident overwritten to 'reported' still cannot erase consumed lease.
    assert store.acquire_recovery_lease(IID, automatic=True) is None
    claim = json.loads(records['claim'][1])
    assert claim['attempt_count'] == claim['automatic_attempt_count'] == 1
    assert claim['customer_send'] is False


def test_e_successful_automatic_recovery_delivers_once(isolated, monkeypatch):
    row = failed_artifact()
    monkeypatch.setattr('admin_store.load_run_artifact', lambda *a, **k: copy.deepcopy(row))
    monkeypatch.setattr('admin_store.update_run_artifact', lambda rid, fn: fn({}))
    runner = mock.Mock(return_value=(CHILD, mock.Mock(response_data={'validation_result':'pass'}), True))
    monkeypatch.setattr(orchestrator, 'execute_orchestrator_run', runner)
    kwargs = dict(artifacts=[row], now=NOW, activated_at=ACTIVATION,
                  programs=['today_genie'], send_fn=lambda **k: True)
    first = watchdog.run_watchdog_poll(**kwargs)
    second = watchdog.run_watchdog_poll(**kwargs)
    assert runner.call_count == 1
    assert first['automatic_recovery_attempt_count'] == first['auto_retry'] == 1
    assert second['automatic_recovery_attempt_count'] == 0
    child = first['results'][0]['automatic_recovery']
    assert child['ok'] and child['email_sent'] and child['customer_send'] == 0
    assert store.load_incident(IID)['status'] == 'recovery_succeeded'
