"""Provider-neutral server-side first-charge boundary.

No browser redirect participates in this contract.  A provider adapter must
return one authoritative outcome and must honor ``idempotency_key``.  The
billing-key reference is intentionally server-only and excluded from repr.
"""

from dataclasses import dataclass, field
from enum import Enum
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
