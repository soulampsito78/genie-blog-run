"""Canonical customer-domain enumerations.

Every member here is taken verbatim from an approved policy document. Do not
invent, rename, or collapse values; if a document changes, change it there
first and follow with a migration.

Authorities:
  - docs/web/CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md (plans, subscription
    state machine sec. 14, billing sec. 7-8)
  - docs/web/CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md (account status)
  - docs/web/CUSTOMER_DELIVERY_ENTITLEMENT_CONTRACT_v1.md (delivery email
    model sec. 5, delivery result vocabulary sec. 17)

These are persisted as constrained VARCHAR + CHECK, not native PostgreSQL
ENUM types. Rationale: the lifecycle vocabulary is expected to keep evolving,
and CHECK constraints are cheap to alter in a single Alembic revision, whereas
native enum value removal requires a type rewrite. The repository had no prior
migration convention to inherit.
"""

from enum import Enum
from typing import FrozenSet, Tuple


class _StrEnum(str, Enum):
    """String-valued enum (Python 3.9 compatible; no enum.StrEnum)."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(member.value for member in cls)


class ProductCode(_StrEnum):
    """The three briefing products (Delivery contract sec. 2)."""

    TODAY_GENIE = "today_genie"
    KEYSURI_GLOBAL = "keysuri_global"
    KEYSURI_KOREA = "keysuri_korea"


class PlanCode(_StrEnum):
    """Paid plan catalog (Lifecycle sec. 1).

    The free trial is NOT a member of this enum: a trial has no paid plan.
    """

    TODAY_GENIE = "today_genie"
    KEYSURI_GLOBAL = "keysuri_global"
    KEYSURI_KOREA = "keysuri_korea"
    PACKAGE_TWO = "package_two"
    FULL_SET = "full_set"


class AccountStatus(_StrEnum):
    """Customer account status (Auth spec sec. 10)."""

    ACTIVE = "active"
    WITHDRAWN = "withdrawn"


class SubscriptionState(_StrEnum):
    """Canonical subscription state machine (Lifecycle sec. 14).

    Exact canonical names. Note in particular that the terminal trial state is
    `trial_expired` (not "ended") and paid cancellation is
    `cancellation_scheduled` -> `canceled`.
    """

    TRIALING = "trialing"
    RENEWAL_PENDING = "renewal_pending"
    CONVERSION_SCHEDULED = "conversion_scheduled"
    TRIAL_EXPIRED = "trial_expired"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    SUSPENDED = "suspended"
    CANCELLATION_SCHEDULED = "cancellation_scheduled"
    CANCELED = "canceled"
    WITHDRAWAL_SCHEDULED = "withdrawal_scheduled"
    WITHDRAWN = "withdrawn"


#: States in which the subscription is finished and no longer occupies the
#: account's single active-subscription slot.
TERMINAL_SUBSCRIPTION_STATES: FrozenSet[str] = frozenset(
    {
        SubscriptionState.TRIAL_EXPIRED.value,
        SubscriptionState.CANCELED.value,
        SubscriptionState.WITHDRAWN.value,
    }
)

#: States that are still inside the free trial. Lifecycle sec. 1.1 / sec. 14:
#: during these states the contracted paid plan MUST be NONE. A conversion
#: selection lives in `conversion_snapshot`, not on the subscription contract.
TRIAL_PHASE_SUBSCRIPTION_STATES: FrozenSet[str] = frozenset(
    {
        SubscriptionState.TRIALING.value,
        SubscriptionState.RENEWAL_PENDING.value,
        SubscriptionState.CONVERSION_SCHEDULED.value,
    }
)

#: States that require an established paid contract (verified payment success).
PAID_CONTRACT_SUBSCRIPTION_STATES: FrozenSet[str] = frozenset(
    {
        SubscriptionState.ACTIVE.value,
        SubscriptionState.PAST_DUE.value,
        SubscriptionState.SUSPENDED.value,
        SubscriptionState.CANCELLATION_SCHEDULED.value,
        SubscriptionState.WITHDRAWAL_SCHEDULED.value,
    }
)


class EntitlementSource(_StrEnum):
    """Why a customer holds an entitlement (Lifecycle sec. 15)."""

    TRIAL = "trial"
    PAID = "paid"


class DeliveryEmailStatus(_StrEnum):
    """Delivery-email lifecycle (Delivery contract sec. 5, sec. 5.1, sec. 10).

    Exactly one `active` row per account. A replacement is inserted as
    `pending_verification` and only supersedes the old row once verified, so
    the account is never without a deliverable address mid-change.
    """

    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    SUPPRESSED = "suppressed"


class SuppressionReason(_StrEnum):
    """Why briefing delivery to an address is suppressed (Delivery sec. 10-13)."""

    HARD_BOUNCE = "hard_bounce"
    COMPLAINT = "complaint"
    UNSUBSCRIBE = "unsubscribe"
    OPERATOR_MANUAL = "operator_manual"


class PaymentMethodStatus(_StrEnum):
    """Payment-method reference status (Lifecycle sec. 5)."""

    ACTIVE = "active"
    REVOKED = "revoked"
    INVALID = "invalid"


class BillingAttemptPurpose(_StrEnum):
    """Why a charge is being attempted (Lifecycle sec. 7-8).

    `first_conversion_charge` is the never-paid first charge at `trial_end_at`;
    it has NO grace period. `renewal_charge` is an existing paid subscriber's
    recurring charge and does get the 3-day grace / Day0,+1,+3 cadence.
    """

    FIRST_CONVERSION_CHARGE = "first_conversion_charge"
    RENEWAL_CHARGE = "renewal_charge"
    RECOVERY_CHARGE = "recovery_charge"


class BillingAttemptStatus(_StrEnum):
    """Billing attempt outcome.

    `provider_state_unknown` is a first-class state: Lifecycle sec. 14 requires
    fail-closed reconciliation before activating entitlement or re-charging.
    """

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PROVIDER_STATE_UNKNOWN = "provider_state_unknown"
    ABANDONED = "abandoned"


class ConversionSnapshotStatus(_StrEnum):
    """Pending conversion snapshot lifecycle (Lifecycle sec. 1.1, sec. 4.1A)."""

    PENDING = "pending"
    APPLIED = "applied"
    ABANDONED = "abandoned"


class DeliveryEventType(_StrEnum):
    """Per-recipient delivery vocabulary (Delivery contract sec. 17).

    Deliberately recipient-scoped. The run-level pipeline stages (generated,
    validated, owner-approved) are NOT duplicated here: they remain owned by
    the existing operational modules, and copying them into the customer DB
    would blur the invariant that approval is not a customer-domain concept.
    """

    NOT_ELIGIBLE = "not_eligible"
    SNAPSHOT_FROZEN = "snapshot_frozen"
    SEND_ATTEMPTED = "send_attempted"
    PROVIDER_ACCEPTED = "provider_accepted"
    PROVIDER_REJECTED = "provider_rejected"
    SOFT_BOUNCE = "soft_bounce"
    HARD_BOUNCE = "hard_bounce"
    COMPLAINT = "complaint"
    DELIVERED_EVIDENCE = "delivered_evidence"
    UNKNOWN_AFTER_SUBMIT = "unknown_after_submit"
    SUPPRESSED = "suppressed"
    CUSTOMER_CONTACT_FAILURE = "customer_contact_failure"
    SENDER_INCIDENT = "sender_incident"


class AuditActorType(_StrEnum):
    """Who caused an audited event."""

    CUSTOMER = "customer"
    SYSTEM = "system"
    OPERATOR = "operator"


class CommandIdempotencyStatus(_StrEnum):
    """Idempotent command replay state (API contract sec. 1)."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


# ---------------------------------------------------------------------------
# Phase 2 - authentication, session, and identity-verification vocabulary.
#
# Canonical: docs/web/CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md
# ---------------------------------------------------------------------------


class AuthChallengePurpose(_StrEnum):
    """Why a verification challenge was issued.

    Purpose is bound into the challenge row and checked on verification, so a
    routine `login` code can never be replayed to authorize a `withdrawal`
    (Auth spec sec. 5; cross-purpose reuse is a fail-closed rejection).
    """

    LOGIN = "login"
    STEP_UP = "step_up"
    EMAIL_OWNERSHIP = "email_ownership"
    PHONE_OWNERSHIP = "phone_ownership"
    ACCOUNT_RECOVERY = "account_recovery"


class AuthChallengeChannel(_StrEnum):
    """Where the challenge was delivered. Delivery itself is out of scope."""

    EMAIL = "email"
    SMS = "sms"


class AuthChallengeStatus(_StrEnum):
    """Bounded challenge lifecycle.

    `verified` and `consumed` are distinct: verification proves control of the
    contact, consumption spends the single-use right it grants. Both terminal
    failure states (`expired`, `locked`) fail closed.
    """

    PENDING = "pending"
    VERIFIED = "verified"
    CONSUMED = "consumed"
    EXPIRED = "expired"
    LOCKED = "locked"


class AuthAssuranceLevel(_StrEnum):
    """How strongly the actor has proven themselves, most recently.

    Deliberately ordered rather than a single boolean (Auth spec sec. 5.2
    defines three distinct risk tiers). Compare with
    `assurance_at_least()` - never with string equality.
    """

    #: An authenticated browser session and nothing more.
    SESSION = "session"
    #: Recent proof of control of a registered email (lower-risk tier).
    RECENT_VERIFICATION = "recent_verification"
    #: Mobile OTP or equivalent strong reauthentication (financial tier).
    STRONG_OTP = "strong_otp"
    #: Full mobile identity verification (identity-destructive tier).
    IDENTITY_VERIFIED = "identity_verified"


#: Rank used for "at least this strong" comparisons.
_ASSURANCE_RANK = {
    AuthAssuranceLevel.SESSION.value: 1,
    AuthAssuranceLevel.RECENT_VERIFICATION.value: 2,
    AuthAssuranceLevel.STRONG_OTP.value: 3,
    AuthAssuranceLevel.IDENTITY_VERIFIED.value: 4,
}


def assurance_rank(level) -> int:
    """Numeric rank of an assurance level (higher is stronger)."""
    return _ASSURANCE_RANK[getattr(level, "value", level)]


def assurance_at_least(actual, required) -> bool:
    """True when `actual` is at least as strong as `required`."""
    return assurance_rank(actual) >= assurance_rank(required)


class IdentityVerificationPurpose(_StrEnum):
    """Why full identity verification was run."""

    SIGNUP = "signup"
    PHONE_CHANGE = "phone_change"
    ACCOUNT_RECOVERY = "account_recovery"
    WITHDRAWAL = "withdrawal"


class IdentityVerificationStatus(_StrEnum):
    """Outcome of an identity-verification attempt.

    `age_not_eligible` is a first-class terminal outcome, not a flavour of
    failure: Auth spec sec. 1 forbids creating an account, trial, payment
    method, or subscription for an under-19 result, with no guardian exception.
    """

    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    AGE_NOT_ELIGIBLE = "age_not_eligible"


class SessionRevokeReason(_StrEnum):
    """Why a browser session was revoked (server-authoritative)."""

    USER_LOGOUT = "user_logout"
    USER_LOGOUT_ALL = "user_logout_all"
    USER_REVOKED_SESSION = "user_revoked_session"
    ACCOUNT_RECOVERY = "account_recovery"
    ACCOUNT_WITHDRAWN = "account_withdrawn"
    SECURITY_INCIDENT = "security_incident"
