"""Provider-neutral payment-method registration boundary.

No PG vendor is selected here.  A future adapter owns every provider-specific
payload and converts it into these deliberately narrow results.  In
particular, this boundary has no PAN, CVV/CVC, card-password, holder-name, raw
identity payload, or raw provider-payload field.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

try:  # pragma: no cover - typing convenience only
    from typing import Protocol
except ImportError:  # pragma: no cover - Python < 3.8
    Protocol = object  # type: ignore

from customer.domain.errors import PaymentProviderNotConfigured


class PaymentRegistrationStatus(str, Enum):
    """Authoritative provider-side registration states."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PENDING = "pending"


@dataclass(frozen=True)
class PaymentRegistrationStart:
    """Safe browser workflow handle, never a reusable billing credential."""

    registration_reference: str


@dataclass(frozen=True)
class PaymentRegistrationResult:
    """Normalised result fetched server-to-server from the provider.

    `billing_key_reference` is server-only.  Transport projections must never
    return it.  The own-name result is linked to the already verified person
    by the PaymentMethod -> CustomerAccount -> PersonIdentity relationship;
    no name or raw identity assertion is copied into this application.
    """

    provider: str
    registration_reference: str
    status: str
    billing_key_reference: Optional[str] = None
    own_name_verified: bool = False
    own_name_verification_reference: Optional[str] = None
    card_brand: Optional[str] = None
    card_last4: Optional[str] = None
    display_label: Optional[str] = None


class PaymentMethodProvider(Protocol):
    """Vaulted-card registration port implemented by a future PG adapter."""

    name: str

    def start_registration(
        self, *, account_reference: str, idempotency_key: str
    ) -> PaymentRegistrationStart:
        """Create/replay a provider registration workflow."""
        ...

    def verify_registration(
        self, *, registration_reference: str
    ) -> PaymentRegistrationResult:
        """Fetch authoritative server-side state; redirects carry no truth."""
        ...


class UnconfiguredPaymentMethodProvider:
    """Fail-closed default until the Owner selects and configures a PG."""

    name = "unconfigured"

    def start_registration(self, *, account_reference: str, idempotency_key: str):
        del account_reference, idempotency_key
        raise PaymentProviderNotConfigured("payment provider is not configured")

    def verify_registration(self, *, registration_reference: str):
        del registration_reference
        raise PaymentProviderNotConfigured("payment provider is not configured")
