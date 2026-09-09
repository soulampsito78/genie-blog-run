"""Typed, bounded Vertex failure evidence; never classify from message substrings."""
from __future__ import annotations

import math
from collections.abc import Mapping

_TRANSIENT_CODES = {
    'TooManyRequests': 429, 'ResourceExhausted': 429,
    'InternalServerError': 500, 'BadGateway': 502,
    'ServiceUnavailable': 503, 'GatewayTimeout': 504, 'DeadlineExceeded': 504,
}


def vertex_failure_evidence(exc, *, attempt_count, slept_seconds, max_attempts):
    return {
        'version': 1, 'provider': 'vertex_ai',
        'failure_class': 'transient_infrastructure',
        'exception_type': type(exc).__name__,
        'http_status': _TRANSIENT_CODES.get(type(exc).__name__),
        'retry_exhausted': True, 'attempt_count': attempt_count,
        'internal_retry_count': attempt_count - 1,
        'max_attempts': max_attempts, 'slept_seconds': slept_seconds,
    }


def verified_vertex_failure(value):
    """Fail closed on absent, permanent, unknown or malformed provider evidence."""
    if not isinstance(value, Mapping):
        return None
    if (value.get('version') != 1 or value.get('provider') != 'vertex_ai'
            or value.get('failure_class') != 'transient_infrastructure'
            or value.get('retry_exhausted') is not True):
        return None
    name = value.get('exception_type')
    if name not in _TRANSIENT_CODES or value.get('http_status') != _TRANSIENT_CODES[name]:
        return None
    attempts, maximum = value.get('attempt_count'), value.get('max_attempts')
    if type(attempts) is not int or type(maximum) is not int or not 1 <= attempts <= maximum <= 3:
        return None
    if value.get('internal_retry_count') != attempts - 1:
        return None
    sleep = value.get('slept_seconds')
    if not isinstance(sleep, (int, float)) or not math.isfinite(sleep) or not 0 <= sleep <= 45:
        return None
    # Exhaustion may also occur because the finite sleep budget is spent.
    return {k: value[k] for k in (
        'version', 'provider', 'failure_class', 'exception_type', 'http_status',
        'retry_exhausted', 'attempt_count', 'internal_retry_count', 'max_attempts', 'slept_seconds',
    )}


def automatic_recovery_candidate(incident, artifact, *, now):
    """Only a today's exact natural slot with proven unusable provider failure."""
    from natural_run_incident_store import NATURAL_SLOTS, KST
    from natural_run_watchdog import _artifact_is_exact_natural_execution, schedule_elapsed

    if not isinstance(incident, Mapping) or not isinstance(artifact, Mapping):
        return False
    if any(incident.get(k) for k in ('verification_only', 'smoke_only', 'smoke_failure',
                                    'recovery_approved_at', 'recovery_run_id', 'automatic_recovery_attempt_count')):
        return False
    if incident.get('status') not in ('open', 'reported'):
        return False
    program, date, slot = (incident.get(k) for k in ('program_id', 'kst_date', 'scheduled_slot'))
    local_now = now.replace(tzinfo=KST) if now.tzinfo is None else now.astimezone(KST)
    if date != local_now.date().isoformat() or NATURAL_SLOTS.get(program) != slot:
        return False
    if not schedule_elapsed(program_id=program, now=local_now):
        return False
    if artifact.get('run_id') != incident.get('original_run_id'):
        return False
    if not _artifact_is_exact_natural_execution(artifact, program_id=program, kst_date=date, scheduled_slot=slot):
        return False
    expected_trigger = 'scheduled_owner_review' if program == 'today_genie' else 'scheduled_service_full_run'
    if artifact.get('trigger_source') != expected_trigger or artifact.get('scheduled_slot') != slot:
        return False
    if artifact.get('artifact_status') not in ('failed', 'error') or artifact.get('artifact_usable') is not False:
        return False
    if artifact.get('response_status') != 500 or artifact.get('first_failed_stage') != 'model_generation':
        return False
    if (artifact.get('validation_result') or artifact.get('issue_codes')
            or artifact.get('customer_surface_status') or artifact.get('product_surface_issue_codes')
            or artifact.get('verification_mode') or artifact.get('original_incident_id')):
        return False
    if (artifact.get('email_sent') is not False or artifact.get('customer_delivery_status') != 'not_sent'
            or artifact.get('approve_customer_final_send') or artifact.get('approved_at')
            or artifact.get('owner_review_status') != 'pending_review'):
        return False
    policy = artifact.get('policy') or {}
    if policy.get('send_email') is not False or policy.get('suppress_external') is not True:
        return False
    return verified_vertex_failure(artifact.get('infrastructure_failure')) is not None
