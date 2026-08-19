"""Security-event auditing for the customer auth domain.

One shared helper, writing to the Phase 1 `audit_event` table. There is
deliberately no second auth-audit table and no ad-hoc `session.add(AuditEvent…)`
scattered through the services: a single choke point is what makes the
no-secrets rule enforceable rather than aspirational.

`AuditEvent` rows are append-only (an UPDATE-blocking trigger from Phase 1), so
what is written here is what a later investigation reads.

PROHIBITED IN PAYLOADS - verification codes and their verifiers, raw session
tokens or their hashes, full IDV payloads, the stable person key, card data.
`_reject_secrets` enforces this at runtime for both keys and values, so a
future caller cannot quietly widen what gets recorded.
"""

import uuid
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from customer.domain.clock import Clock
from customer.domain.enums import AuditActorType
from customer.persistence.models import AuditEvent


# --- canonical event names -------------------------------------------------
# Namespaced and stable: these strings end up in operational queries, so treat
# them as a contract rather than free text.

IDENTITY_VERIFICATION_PREFIX = "identity.verification_"
IDENTITY_DUPLICATE_SIGNUP_BLOCKED = "identity.duplicate_signup_blocked"
IDENTITY_PHONE_CHANGED = "identity.phone_changed"
IDENTITY_PHONE_CHANGE_MISMATCH = "identity.phone_change_mismatch"

AUTH_CHALLENGE_ISSUED = "auth.challenge_issued"
AUTH_CHALLENGE_VERIFIED = "auth.challenge_verified"
AUTH_CHALLENGE_FAILED = "auth.challenge_failed"
AUTH_CHALLENGE_LOCKED = "auth.challenge_locked"
AUTH_FRESH_AUTH_RECORDED = "auth.fresh_auth_recorded"

SESSION_CREATED = "session.created"
SESSION_REVOKED = "session.revoked"
SESSION_LOGOUT_ALL = "session.logout_all"

PAYMENT_METHOD_REGISTERED = "payment_method.registered"
TRIAL_STARTED = "subscription.trial_started"
CONVERSION_CONFIRMED = "subscription.conversion_confirmed"
FIRST_CHARGE_SUCCEEDED = "billing.first_charge_succeeded"
FIRST_CHARGE_FAILED = "billing.first_charge_failed"
FIRST_CHARGE_UNKNOWN = "billing.first_charge_provider_state_unknown"
FIRST_CHARGE_RECONCILIATION_SUCCEEDED = "billing.first_charge_reconciled_success"
FIRST_CHARGE_RECONCILIATION_FAILED = "billing.first_charge_reconciled_failure"
FIRST_CHARGE_RECONCILIATION_UNKNOWN = "billing.first_charge_reconciliation_unknown"
FIRST_CHARGE_RECONCILIATION_CONFLICT = "billing.first_charge_reconciliation_conflict"
RENEWAL_PREPARED = "billing.renewal_prepared"
RENEWAL_SUCCEEDED = "billing.renewal_succeeded"
RENEWAL_FAILED = "billing.renewal_failed"
RENEWAL_UNKNOWN = "billing.renewal_provider_state_unknown"
RENEWAL_RECONCILIATION_SUCCEEDED = "billing.renewal_reconciled_success"
RENEWAL_RECONCILIATION_FAILED = "billing.renewal_reconciled_failure"
RENEWAL_RECONCILIATION_UNKNOWN = "billing.renewal_reconciliation_unknown"
RENEWAL_RECONCILIATION_CONFLICT = "billing.renewal_reconciliation_conflict"
BILLING_RECOVERY_REQUESTED = "billing.recovery_requested"
BILLING_RECOVERY_SUCCEEDED = "billing.recovery_succeeded"
BILLING_RECOVERY_FAILED = "billing.recovery_failed"
BILLING_RECOVERY_UNKNOWN = "billing.recovery_provider_state_unknown"
BILLING_RECOVERY_RECONCILIATION_SUCCEEDED = "billing.recovery_reconciled_success"
BILLING_RECOVERY_RECONCILIATION_FAILED = "billing.recovery_reconciled_failure"
BILLING_RECOVERY_RECONCILIATION_UNKNOWN = "billing.recovery_reconciliation_unknown"
BILLING_RECOVERY_RECONCILIATION_CONFLICT = "billing.recovery_reconciliation_conflict"


#: Payload keys that must never appear, regardless of value.
_FORBIDDEN_KEY_FRAGMENTS = (
    "code",
    "otp",
    "token",
    "secret",
    "password",
    "hash",
    "verifier",
    "salt",
    "stable_key",
    "idv_payload",
    "payload",
    "card",
    "pan",
    "cvv",
)

#: Keys that are safe despite matching a fragment above.
_ALLOWED_KEYS = frozenset(
    {
        "plan_code",
        "product_code",
        "failure_code",
        "error_code",
        "revoke_reason",
    }
)


class AuditSecretLeak(RuntimeError):
    """Raised when an audit payload would record prohibited material."""


def _reject_secrets(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fail loudly rather than record a secret.

    Deliberately raises instead of scrubbing: silently dropping a field would
    hide the fact that a caller tried to log a credential.
    """
    for key, value in (payload or {}).items():
        lowered = str(key).lower()
        if lowered in _ALLOWED_KEYS:
            continue
        for fragment in _FORBIDDEN_KEY_FRAGMENTS:
            if fragment in lowered:
                raise AuditSecretLeak(
                    "audit payload key {0!r} may carry secret material".format(key)
                )
        if isinstance(value, (dict, list)):
            raise AuditSecretLeak(
                "audit payload value for {0!r} must be a scalar; nested "
                "structures invite unreviewed payload dumping".format(key)
            )
    return dict(payload or {})


class AuditService:
    """Append security events to the shared `audit_event` table."""

    def __init__(self, session: Session, clock: Clock) -> None:
        self._session = session
        self._clock = clock

    def record(
        self,
        event_type: str,
        *,
        account_id: Optional[uuid.UUID] = None,
        subscription_id: Optional[uuid.UUID] = None,
        actor_type: str = AuditActorType.SYSTEM.value,
        actor_account_id: Optional[uuid.UUID] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        safe_payload = _reject_secrets(payload or {})

        if actor_type == AuditActorType.CUSTOMER.value and actor_account_id is None:
            # The CHECK on audit_event requires a customer actor to name an
            # account; fall back to the subject rather than failing the write.
            actor_account_id = account_id

        event = AuditEvent(
            actor_type=actor_type,
            actor_account_id=actor_account_id,
            account_id=account_id,
            subscription_id=subscription_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            payload=safe_payload,
            occurred_at=self._clock.now(),
        )
        self._session.add(event)
        self._session.flush()
        return event
