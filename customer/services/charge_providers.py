"""Provider-neutral server-side first-charge boundary.

No browser redirect participates in this contract.  A provider adapter must
return one authoritative outcome and must honor ``idempotency_key``.  The
billing-key reference is intentionally server-only and excluded from repr.
"""

from dataclasses import dataclass, field
from enum import Enum
import datetime as dt
from typing import Optional, Protocol


class ChargeOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PROVIDER_STATE_UNKNOWN = "provider_state_unknown"


@dataclass(frozen=True)
class FirstChargeRequest:
    attempt_id: str
    conversion_snapshot_id: str
    account_id: str
    subscription_id: str
    amount_krw: int
    currency: str
    plan_code: str
    price_version: int
    idempotency_key: str
    billing_key_reference: str = field(repr=False)


@dataclass(frozen=True)
class FirstChargeProviderResult:
    outcome: ChargeOutcome
    transaction_reference: Optional[str] = None
    provider_event_reference: Optional[str] = None
    failure_code: Optional[str] = None

    @classmethod
    def succeeded(
        cls, transaction_reference: str, *, event_reference: Optional[str] = None
    ) -> "FirstChargeProviderResult":
        return cls(
            ChargeOutcome.SUCCEEDED,
            transaction_reference=transaction_reference,
            provider_event_reference=event_reference,
        )

    @classmethod
    def failed(
        cls, failure_code: str, *, event_reference: Optional[str] = None
    ) -> "FirstChargeProviderResult":
        return cls(
            ChargeOutcome.FAILED,
            provider_event_reference=event_reference,
            failure_code=failure_code,
        )

    @classmethod
    def unknown(
        cls, *, operation_reference: Optional[str] = None
    ) -> "FirstChargeProviderResult":
        return cls(
            ChargeOutcome.PROVIDER_STATE_UNKNOWN,
            provider_event_reference=operation_reference,
            failure_code="PROVIDER_STATE_UNKNOWN",
        )


class FirstChargeProvider(Protocol):
    """A server-side vault charge adapter with provider idempotency."""

    name: str

    def charge(self, request: FirstChargeRequest) -> FirstChargeProviderResult:
        ...


@dataclass(frozen=True)
class RenewalChargeRequest:
    """Server-only command for one immutable paid-renewal attempt slot."""

    attempt_id: str
    account_id: str
    subscription_id: str
    billing_period_start: dt.date
    billing_period_end: dt.date
    amount_krw: int
    currency: str
    plan_code: str
    price_version: int
    attempt_no: int
    retry_offset_day: int
    idempotency_key: str = field(repr=False)
    billing_key_reference: str = field(repr=False)


class RenewalChargeProvider(Protocol):
    """Provider-neutral server-side recurring-charge adapter."""

    name: str

    def charge_renewal(
        self, request: RenewalChargeRequest
    ) -> FirstChargeProviderResult:
        ...


class ReconciliationOutcome(str, Enum):
    """Authoritative query result for the original provider command.

    Provider adapters must map missing or ambiguous provider records to
    ``STILL_UNKNOWN`` unless their provider contract proves that absence is a
    definitive non-charge result.
    """

    CONFIRMED_SUCCESS = "confirmed_success"
    CONFIRMED_FAILURE = "confirmed_failure"
    STILL_UNKNOWN = "still_unknown"
    NOT_FOUND = "not_found"


class ReconciliationLookupBasis(str, Enum):
    """Durable authority used to query the original provider command."""

    OPERATION_REFERENCE = "operation_reference"
    IDEMPOTENCY_KEY = "idempotency_key"


@dataclass(frozen=True)
class FirstChargeReconciliationCapabilities:
    """Explicit provider-adapter guarantees; defaults are fail-closed."""

    authoritative_idempotency_lookup: bool = False
    definitive_not_found_means_no_charge: bool = False


@dataclass(frozen=True)
class FirstChargeReconciliationRequest:
    """Server-only lookup evidence for one already-issued charge command."""

    attempt_id: str
    provider: str
    lookup_basis: ReconciliationLookupBasis
    original_idempotency_key: str = field(repr=False)
    original_operation_reference: Optional[str] = field(default=None, repr=False)


@dataclass(frozen=True)
class FirstChargeReconciliationResult:
    outcome: ReconciliationOutcome
    transaction_reference: Optional[str] = None
    provider_event_reference: Optional[str] = None
    failure_code: Optional[str] = None

    @classmethod
    def confirmed_success(
        cls, transaction_reference: str, *, event_reference: Optional[str] = None
    ) -> "FirstChargeReconciliationResult":
        return cls(
            ReconciliationOutcome.CONFIRMED_SUCCESS,
            transaction_reference=transaction_reference,
            provider_event_reference=event_reference,
        )

    @classmethod
    def confirmed_failure(
        cls, failure_code: str, *, event_reference: Optional[str] = None
    ) -> "FirstChargeReconciliationResult":
        return cls(
            ReconciliationOutcome.CONFIRMED_FAILURE,
            provider_event_reference=event_reference,
            failure_code=failure_code,
        )

    @classmethod
    def still_unknown(
        cls, *, event_reference: Optional[str] = None
    ) -> "FirstChargeReconciliationResult":
        return cls(
            ReconciliationOutcome.STILL_UNKNOWN,
            provider_event_reference=event_reference,
        )

    @classmethod
    def not_found(
        cls, *, event_reference: Optional[str] = None
    ) -> "FirstChargeReconciliationResult":
        return cls(
            ReconciliationOutcome.NOT_FOUND,
            provider_event_reference=event_reference,
        )


class FirstChargeReconciliationProvider(Protocol):
    """Query-only adapter for the original first-charge provider command."""

    name: str
    reconciliation_capabilities: FirstChargeReconciliationCapabilities

    def reconcile_first_charge(
        self, request: FirstChargeReconciliationRequest
    ) -> FirstChargeReconciliationResult:
        ...


@dataclass(frozen=True)
class RenewalChargeReconciliationRequest:
    """Lookup-only evidence for one original renewal charge command."""

    attempt_id: str
    provider: str
    lookup_basis: ReconciliationLookupBasis
    original_idempotency_key: str = field(repr=False)
    original_operation_reference: Optional[str] = field(default=None, repr=False)


class RenewalChargeReconciliationProvider(Protocol):
    """Query-only adapter; it can never create a renewal charge."""

    name: str
    reconciliation_capabilities: FirstChargeReconciliationCapabilities

    def reconcile_renewal(
        self, request: RenewalChargeReconciliationRequest
    ) -> FirstChargeReconciliationResult:
        ...
