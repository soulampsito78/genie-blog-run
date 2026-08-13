"""Stable customer-facing error codes.

Codes come from docs/web/CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md sec. 8 and
docs/web/FRONTEND_API_CONTRACT_v1.md sec. 4. They are part of the contract:
rename one and a future frontend breaks, so treat them as canonical strings.

Error *messages* are for operators and logs. They MUST NOT carry a verification
code, session token, IDV payload, or any other secret.
"""

from typing import Optional


class CustomerAuthError(Exception):
    """Base class carrying a stable machine-readable code."""

    code = "CUSTOMER_AUTH_ERROR"

    def __init__(self, message: Optional[str] = None) -> None:
        super().__init__(message or self.code)

    def __str__(self) -> str:
        return "{0}: {1}".format(self.code, super().__str__())


# --- identity --------------------------------------------------------------


class AgeNotEligible(CustomerAuthError):
    """Verification resolved to an age under 19. No guardian exception."""

    code = "AGE_NOT_ELIGIBLE"


class IdentityVerificationFailed(CustomerAuthError):
    """Verification failed or was abandoned; no account may be created."""

    code = "IDV_FAILED"


class IdentityAlreadyRegistered(CustomerAuthError):
    """Stable identity already owns an active account -> route to recovery."""

    code = "IDENTITY_ALREADY_REGISTERED"


class IdentityMismatch(CustomerAuthError):
    """Verification resolved to a different person than the account owner."""

    code = "IDENTITY_MISMATCH"


# --- challenge -------------------------------------------------------------


class LoginChallengeInvalid(CustomerAuthError):
    """Challenge is unknown, wrong, expired, consumed, or locked.

    Deliberately one code for every failure mode: distinguishing "wrong code"
    from "no such challenge" would let an attacker enumerate accounts.
    """

    code = "LOGIN_CHALLENGE_INVALID"


class ChallengeRateLimited(CustomerAuthError):
    """A new challenge was requested inside the issue cooldown."""

    code = "CHALLENGE_RATE_LIMITED"


# --- session ---------------------------------------------------------------


class SessionExpired(CustomerAuthError):
    """Absolute or inactivity timeout elapsed."""

    code = "SESSION_EXPIRED"


class SessionRevoked(CustomerAuthError):
    """Session was revoked server-side."""

    code = "SESSION_REVOKED"


class SessionInvalid(CustomerAuthError):
    """Presented session token does not match any session."""

    code = "SESSION_INVALID"


class StepUpRequired(CustomerAuthError):
    """Sensitive action attempted without sufficiently fresh/strong auth."""

    code = "STEP_UP_REQUIRED"


class AccountNotActive(CustomerAuthError):
    """Account is withdrawn or otherwise not eligible to authenticate."""

    code = "ACCOUNT_NOT_ACTIVE"
