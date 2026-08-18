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


class AuthenticationRequired(CustomerAuthError):
    """A customer route was called without a valid browser session."""

    code = "AUTHENTICATION_REQUIRED"


class StepUpRequired(CustomerAuthError):
    """Sensitive action attempted without sufficiently fresh/strong auth."""

    code = "STEP_UP_REQUIRED"


class AccountNotActive(CustomerAuthError):
    """Account is withdrawn or otherwise not eligible to authenticate."""

    code = "ACCOUNT_NOT_ACTIVE"


# --- payment method -------------------------------------------------------


class PaymentMethodNotFound(CustomerAuthError):
    """Payment method or registration is unavailable to this customer."""

    code = "PAYMENT_METHOD_NOT_FOUND"


class PaymentProviderNotConfigured(CustomerAuthError):
    """No payment provider adapter has been selected or configured."""

    code = "PAYMENT_PROVIDER_NOT_CONFIGURED"


class PaymentProviderUnavailable(CustomerAuthError):
    """Provider operation failed without exposing provider error details."""

    code = "PAYMENT_PROVIDER_UNAVAILABLE"


class PaymentProviderStateUnknown(CustomerAuthError):
    """Provider has not authoritatively confirmed registration success."""

    code = "PROVIDER_STATE_UNKNOWN"


class PaymentMethodVerificationFailed(CustomerAuthError):
    """Provider authoritatively rejected registration or own-name proof."""

    code = "PAYMENT_METHOD_VERIFICATION_FAILED"


class IdempotencyKeyConflict(CustomerAuthError):
    """An idempotency key was reused with different command parameters."""

    code = "IDEMPOTENCY_KEY_CONFLICT"


# --- trial ---------------------------------------------------------------


class PaymentMethodRequired(CustomerAuthError):
    """A usable verified own-name default method is absent."""

    code = "PAYMENT_METHOD_REQUIRED"


class DeliveryEmailUnverified(CustomerAuthError):
    """No verified active delivery address can receive trial briefings."""

    code = "DELIVERY_EMAIL_UNVERIFIED"


class TrialNotEligible(CustomerAuthError):
    """The verified person or account cannot receive a new free trial."""

    code = "TRIAL_NOT_ELIGIBLE"


class TrialNotFound(CustomerAuthError):
    """No trial projection exists for the authenticated account."""

    code = "TRIAL_NOT_FOUND"
