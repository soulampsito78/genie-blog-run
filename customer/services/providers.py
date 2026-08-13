"""Provider ports for identity verification and code delivery.

Narrow, provider-neutral boundaries. No vendor is selected, integrated, or
named here - vendor choice is EXTERNAL VALIDATION REQUIRED per the Auth spec
and the Web SSOT sec. 13.

The point of these ports is that a provider's payload shape never leaks into
the domain: an adapter converts whatever the vendor returns into
`IdentityVerificationResult`, and nothing downstream knows the difference.
"""

import datetime as dt
from typing import Optional

try:  # pragma: no cover - typing convenience only
    from typing import Protocol
except ImportError:  # pragma: no cover - Python < 3.8
    Protocol = object  # type: ignore

from dataclasses import dataclass

from customer.domain.enums import AuthChallengeChannel


@dataclass(frozen=True)
class IdentityVerificationResult:
    """Normalised outcome of a full mobile identity verification.

    Deliberately minimal (Auth spec sec. 1): an adult flag, the stable person
    key, the verified number, and a provider reference for re-audit. There is
    no name, no birthdate, and no raw payload field - if a field is not here,
    the domain cannot accidentally persist it.
    """

    provider: str
    provider_reference: str
    #: True/False only when the provider actually answered.
    adult_verified: Optional[bool]
    #: DI or equivalent. Present only on a successful adult verification.
    stable_key: Optional[str]
    mobile_e164: Optional[str] = None
    #: Provider-side completion instant, if supplied.
    completed_at: Optional[dt.datetime] = None
    #: True when the provider reported an outright failure/abandonment.
    failed: bool = False


class IdentityVerificationProvider(Protocol):
    """Full mobile IDV. Establishes 19+ eligibility and the stable person key."""

    name: str

    def start(self, purpose: str, reference_hint: Optional[str] = None) -> str:
        """Begin a verification session; return the provider reference."""
        ...

    def result(self, provider_reference: str) -> IdentityVerificationResult:
        """Fetch the normalised outcome for a provider reference."""
        ...


class VerificationCodeSender(Protocol):
    """Delivers a verification code over email or SMS.

    Real delivery is out of scope for this phase. The port exists so the
    challenge service has somewhere to hand the plaintext code, and so no code
    path is tempted to persist or log it instead.
    """

    def send(self, channel: str, target: str, code: str) -> None:
        ...


class NullVerificationCodeSender:
    """No-op sender used until a real ESP/SMS vendor is selected.

    Explicitly does NOT record the code anywhere. A sender that logged the code
    "just for development" would put a live credential in the log pipeline.
    """

    def __init__(self) -> None:
        #: Count only - never the code, never the target's contents.
        self.sent_count = 0

    def send(self, channel: str, target: str, code: str) -> None:
        if channel not in AuthChallengeChannel.values():
            raise ValueError("unknown verification channel: {0}".format(channel))
        self.sent_count += 1
