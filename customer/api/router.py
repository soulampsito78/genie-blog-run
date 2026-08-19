"""Isolated FastAPI transport for customer signup, login, and sessions.

No route here is mounted into the production operational application.  This
module builds a complete APIRouter and a dedicated test app only.
"""

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from customer.api.dependencies import (
    CustomerApiSecurityConfig,
    IdentityProviderNotConfigured,
    get_clock,
    get_billing_recovery_executor,
    get_customer_api_security_config,
    get_customer_db_session,
    get_identity_provider,
    get_payment_method_provider,
    get_verification_code_sender,
    require_customer_session,
    require_fresh_auth,
    require_fresh_financial_auth,
    require_same_site_origin,
)
from customer.domain.clock import Clock
from customer.domain.email import is_valid_email, normalize_email
from customer.domain.enums import (
    AuthChallengeChannel,
    AuthChallengePurpose,
    IdentityVerificationPurpose,
    IdentityVerificationStatus,
    SessionRevokeReason,
)
from customer.domain.errors import (
    AgeNotEligible,
    AuthenticationRequired,
    CatalogUnavailable,
    ChallengeRateLimited,
    ConversionNotEligible,
    ConversionSelectionInvalid,
    ConversionSelectionRequired,
    CustomerAuthError,
    DeliveryEmailUnverified,
    IdentityVerificationFailed,
    IdempotencyKeyConflict,
    LoginChallengeInvalid,
    PaymentMethodNotFound,
    PaymentMethodRequired,
    PaymentMethodVerificationFailed,
    PaymentProviderNotConfigured,
    PaymentProviderStateUnknown,
    PaymentProviderUnavailable,
    SessionExpired,
    SessionInvalid,
    SessionRevoked,
    StepUpRequired,
    TrialNotEligible,
    TrialNotFound,
    FirstChargeConflict,
    RenewalBillingConflict,
)
from customer.persistence.models import (
    BrowserSession,
    CustomerAccount,
    IdentityVerification,
    PaymentMethod,
)
from customer.services.challenge_service import ChallengeService
from customer.services.billing_recovery_service import (
    BillingRecoveryResult,
    BillingRecoveryService,
)
from customer.services.conversion_service import (
    ConversionEligibility,
    ConversionResult,
    ConversionService,
)
from customer.services.cookies import cleared_cookie_settings, session_cookie_settings
from customer.services.identity_service import IdentityService
from customer.services.login_service import LoginService
from customer.services.onboarding_service import OnboardingService
from customer.services.payment_method_service import PaymentMethodService
from customer.services.session_service import AccessContext, SessionService
from customer.services.trial_service import TrialResult, TrialService


class IdentityStartRequest(BaseModel):
    # No browser-supplied birthdate, stable key, name, or provider payload.
    pass


class IdentityCompleteRequest(BaseModel):
    verification_reference: str = Field(min_length=1, max_length=255)


class SignupEmailChallengeRequest(BaseModel):
    verification_id: uuid.UUID
    account_email: str = Field(min_length=3, max_length=320)


class SignupCompleteRequest(BaseModel):
    verification_id: uuid.UUID
    account_email: str = Field(min_length=3, max_length=320)
    challenge_id: uuid.UUID
    code: str = Field(min_length=1, max_length=32)
    remember_login: bool = False


class LoginChallengeRequest(BaseModel):
    channel: str
    target: str = Field(min_length=3, max_length=320)


class LoginVerifyRequest(LoginChallengeRequest):
    challenge_id: uuid.UUID
    code: str = Field(min_length=1, max_length=32)
    remember_login: bool = False


class PaymentRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    replacement_payment_method_id: Optional[uuid.UUID] = None


class PaymentRegistrationFinalizeRequest(PaymentRegistrationRequest):
    registration_reference: str = Field(min_length=1, max_length=120)


class TrialStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool


class ConversionSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_code: str = Field(min_length=1, max_length=40)
    products: List[str] = Field(min_length=1, max_length=3)


class ConversionConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool


class BillingRecoveryConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool


customer_router = APIRouter(prefix="/v1/customer")
identity_router = APIRouter(prefix="/identity", tags=["customer-identity"])
auth_router = APIRouter(prefix="/auth", tags=["customer-auth"])
account_router = APIRouter(prefix="/account", tags=["customer-account"])
sessions_router = APIRouter(prefix="/sessions", tags=["customer-sessions"])
onboarding_router = APIRouter(prefix="/onboarding", tags=["customer-onboarding"])
payment_methods_router = APIRouter(
    prefix="/payment-methods", tags=["customer-payment-methods"]
)
trial_router = APIRouter(prefix="/trial", tags=["customer-trial"])
conversion_router = APIRouter(prefix="/conversion", tags=["customer-conversion"])
billing_router = APIRouter(prefix="/billing", tags=["customer-billing"])


@identity_router.post("/start")
def start_identity_verification(
    body: IdentityStartRequest,
    provider=Depends(get_identity_provider),
):
    del body
    try:
        reference = provider.start(IdentityVerificationPurpose.SIGNUP.value)
    except IdentityProviderNotConfigured:
        return _error("IDV_PROVIDER_NOT_CONFIGURED", 503)
    return {
        "accepted": True,
        "verification_reference": reference,
        "onboarding": {"next_required_stage": "identity_verification_required"},
    }


@identity_router.post("/complete")
def complete_identity_verification(
    body: IdentityCompleteRequest,
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
    provider=Depends(get_identity_provider),
):
    try:
        result = provider.result(body.verification_reference)
    except IdentityProviderNotConfigured:
        return _error("IDV_PROVIDER_NOT_CONFIGURED", 503)

    identities = IdentityService(session, clock)
    verification = identities.record_verification_result(
        result, purpose=IdentityVerificationPurpose.SIGNUP.value
    )
    if verification.status == IdentityVerificationStatus.AGE_NOT_ELIGIBLE.value:
        # Returned rather than raised so the legally relevant under-age audit
        # record is committed while still giving the canonical HTTP error.
        return _error(AgeNotEligible.code, 422)
    if verification.status != IdentityVerificationStatus.VERIFIED.value:
        return _error(IdentityVerificationFailed.code, 422)
    return {
        "verification_id": str(verification.id),
        "onboarding": {"next_required_stage": "account_email_verification_required"},
    }


@auth_router.post("/signup/email-challenge")
def issue_signup_email_challenge(
    body: SignupEmailChallengeRequest,
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
    sender=Depends(get_verification_code_sender),
):
    verification = session.get(IdentityVerification, body.verification_id)
    if verification is None:
        return _error(IdentityVerificationFailed.code, 422)
    try:
        IdentityService(session, clock).assert_eligible(verification)
        issued = ChallengeService(session, clock, sender=sender).issue_challenge(
            purpose=AuthChallengePurpose.EMAIL_OWNERSHIP.value,
            channel=AuthChallengeChannel.EMAIL.value,
            target=body.account_email,
        )
    except CustomerAuthError as error:
        return _domain_error(error)
    return {"accepted": True, "challenge_id": str(issued.challenge_id)}


@auth_router.post("/signup/complete")
def complete_signup(
    body: SignupCompleteRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
    config: CustomerApiSecurityConfig = Depends(get_customer_api_security_config),
):
    verification = session.get(IdentityVerification, body.verification_id)
    if verification is None:
        return _error(IdentityVerificationFailed.code, 422)
    try:
        normalized_email = normalize_email(body.account_email)
        if not is_valid_email(normalized_email):
            raise IdentityVerificationFailed("account email is invalid")
        email_verification = ChallengeService(session, clock).verify_and_consume(
            challenge_id=body.challenge_id,
            code=body.code,
            purpose=AuthChallengePurpose.EMAIL_OWNERSHIP.value,
            expected_target=normalized_email,
        )
        identity = IdentityService(session, clock)
        result = OnboardingService(session, clock, identity).complete_account_signup(
            verification=verification,
            account_email=normalized_email,
            email_verification=email_verification,
        )
    except CustomerAuthError as error:
        return _domain_error(error)

    if result.existing_account_recovery_required:
        return {"outcome": "existing_account_recovery_required"}

    created = SessionService(session, clock).create_browser_session(
        account_id=result.account.id,
        remember_login=body.remember_login,
        user_agent_summary=_user_agent(request),
        created_ip=_request_ip(request),
    )
    _set_session_cookie(response, created.token, body.remember_login, config)
    return _account_projection(session, clock, result.account, created.session_id)


@auth_router.post("/login/challenge")
def issue_login_challenge(
    body: LoginChallengeRequest,
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
    sender=Depends(get_verification_code_sender),
):
    try:
        issued = LoginService(
            session, clock, ChallengeService(session, clock, sender=sender)
        ).issue_login_challenge(channel=body.channel, target=body.target)
    except (CustomerAuthError, ValueError) as error:
        # Preserve an enumeration-safe accepted envelope even for cooldowns.
        if isinstance(error, ChallengeRateLimited):
            return {"accepted": True, "challenge_id": str(uuid.uuid4())}
        return _error(LoginChallengeInvalid.code, 400)
    return {"accepted": True, "challenge_id": str(issued.challenge_id)}


@auth_router.post("/login/verify")
def verify_login(
    body: LoginVerifyRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
    config: CustomerApiSecurityConfig = Depends(get_customer_api_security_config),
):
    try:
        account = LoginService(
            session, clock, ChallengeService(session, clock)
        ).verify_login_challenge(
            channel=body.channel,
            target=body.target,
            challenge_id=body.challenge_id,
            code=body.code,
        )
    except CustomerAuthError as error:
        return _domain_error(error)
    created = SessionService(session, clock).create_browser_session(
        account_id=account.id,
        remember_login=body.remember_login,
        user_agent_summary=_user_agent(request),
        created_ip=_request_ip(request),
    )
    _set_session_cookie(response, created.token, body.remember_login, config)
    return _account_projection(session, clock, account, created.session_id)


@account_router.get("/me")
def get_current_account(
    access: AccessContext = Depends(require_customer_session),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
):
    account = session.get(CustomerAccount, access.account_id)
    if account is None:
        raise AuthenticationRequired("customer account is unavailable")
    return _account_projection(session, clock, account, access.session_id)


@onboarding_router.get("/status")
def get_onboarding_status(
    access: AccessContext = Depends(require_customer_session),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
):
    return {"next_required_stage": OnboardingService(session, clock, IdentityService(session, clock)).status_for_account(access.account_id)}


@payment_methods_router.post("/registration")
def initiate_payment_method_registration(
    body: PaymentRegistrationRequest,
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=1, max_length=200
    ),
    access: AccessContext = Depends(require_fresh_financial_auth),
    _: None = Depends(require_same_site_origin),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
    provider=Depends(get_payment_method_provider),
):
    try:
        started = PaymentMethodService(session, clock, provider).initiate_registration(
            account_id=access.account_id,
            idempotency_key=idempotency_key,
            replacement_payment_method_id=body.replacement_payment_method_id,
        )
    except CustomerAuthError as error:
        return _domain_error(error)
    return {
        "accepted": True,
        "registration_reference": started.registration_reference,
        "replayed": started.replayed,
        "completed": started.completed,
    }


@payment_methods_router.post("/registration/finalize")
def finalize_payment_method_registration(
    body: PaymentRegistrationFinalizeRequest,
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=1, max_length=200
    ),
    access: AccessContext = Depends(require_fresh_financial_auth),
    _: None = Depends(require_same_site_origin),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
    provider=Depends(get_payment_method_provider),
):
    try:
        registered = PaymentMethodService(session, clock, provider).finalize_registration(
            account_id=access.account_id,
            idempotency_key=idempotency_key,
            registration_reference=body.registration_reference,
            replacement_payment_method_id=body.replacement_payment_method_id,
        )
    except CustomerAuthError as error:
        return _domain_error(error)
    stage = OnboardingService(
        session, clock, IdentityService(session, clock)
    ).status_for_account(access.account_id)
    return {
        "payment_method": _payment_method_projection(registered.payment_method),
        "onboarding": {"next_required_stage": stage},
        "replayed": registered.replayed,
    }


@payment_methods_router.get("/default")
def get_default_payment_method(
    access: AccessContext = Depends(require_customer_session),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
    provider=Depends(get_payment_method_provider),
):
    try:
        method = PaymentMethodService(
            session, clock, provider
        ).default_payment_method(access.account_id)
    except CustomerAuthError as error:
        return _domain_error(error)
    return {"payment_method": _payment_method_projection(method)}


@trial_router.post("/start")
def start_trial(
    body: TrialStartRequest,
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=1, max_length=200
    ),
    access: AccessContext = Depends(require_customer_session),
    _: None = Depends(require_same_site_origin),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
):
    if body.confirm is not True:
        return _error("TRIAL_CONFIRMATION_REQUIRED", 400)
    try:
        result = TrialService(session, clock).start_trial(
            account_id=access.account_id,
            idempotency_key=idempotency_key,
        )
    except CustomerAuthError as error:
        return _domain_error(error)
    return {
        "trial": _trial_projection(result),
        "onboarding": {"next_required_stage": "onboarding_complete"},
        "replayed": result.replayed,
    }


@trial_router.get("")
def get_current_trial(
    access: AccessContext = Depends(require_customer_session),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
):
    try:
        result = TrialService(session, clock).current_trial(access.account_id)
    except CustomerAuthError as error:
        return _domain_error(error)
    return {"trial": _trial_projection(result)}


@conversion_router.get("/eligibility")
def get_conversion_eligibility(
    access: AccessContext = Depends(require_customer_session),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
):
    try:
        result = ConversionService(session, clock).eligibility(access.account_id)
    except CustomerAuthError as error:
        return _domain_error(error)
    return {"conversion": _conversion_eligibility_projection(result)}


@conversion_router.get("/catalog")
def get_conversion_catalog(
    access: AccessContext = Depends(require_customer_session),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
):
    try:
        rows = ConversionService(session, clock).catalog(access.account_id)
    except CustomerAuthError as error:
        return _domain_error(error)
    return {
        "plans": [
            {
                "plan_code": row.plan_code,
                "price_krw": row.price_krw,
                "price_version": row.price_version,
                "currency": row.currency,
                "vat_included": row.vat_included,
                "product_count": row.product_count,
                "fixed_products": list(products),
                "selected": False,
            }
            for row, products in rows
        ]
    }


@conversion_router.put("/selection")
def put_conversion_selection(
    body: ConversionSelectionRequest,
    access: AccessContext = Depends(require_customer_session),
    _: None = Depends(require_same_site_origin),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
):
    try:
        result = ConversionService(session, clock).select(
            account_id=access.account_id,
            plan_code=body.plan_code,
            products=body.products,
        )
    except CustomerAuthError as error:
        return _domain_error(error)
    return {"conversion": _conversion_projection(result)}


@conversion_router.get("/selection")
def get_conversion_selection(
    access: AccessContext = Depends(require_customer_session),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
):
    try:
        result = ConversionService(session, clock).current_selection(access.account_id)
    except CustomerAuthError as error:
        return _domain_error(error)
    return {"conversion": _conversion_projection(result)}


@conversion_router.post("/confirm")
def confirm_conversion(
    body: ConversionConfirmRequest,
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=1, max_length=200
    ),
    access: AccessContext = Depends(require_fresh_financial_auth),
    _: None = Depends(require_same_site_origin),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
):
    if body.confirm is not True:
        return _error("CONVERSION_NOT_CONFIRMED", 400)
    try:
        result = ConversionService(session, clock).confirm(
            account_id=access.account_id,
            idempotency_key=idempotency_key,
        )
    except CustomerAuthError as error:
        return _domain_error(error)
    return {"conversion": _conversion_projection(result), "replayed": result.replayed}


@billing_router.get("/recovery")
def get_billing_recovery_eligibility(
    access: AccessContext = Depends(require_customer_session),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
):
    projection = BillingRecoveryService(session, clock).projection(access.account_id)
    return {
        "first_charge": _recovery_eligibility_projection(projection.first_charge),
        "suspended_renewal": _recovery_eligibility_projection(
            projection.suspended_renewal
        ),
    }


@billing_router.post("/recovery/first-charge")
def confirm_first_charge_recovery(
    body: BillingRecoveryConfirmRequest,
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=1, max_length=200
    ),
    access: AccessContext = Depends(require_fresh_financial_auth),
    _: None = Depends(require_same_site_origin),
    executor=Depends(get_billing_recovery_executor),
):
    if body.confirm is not True:
        return _error("BILLING_RECOVERY_CONFIRMATION_REQUIRED", 400)
    try:
        result = executor.recover_first_charge(
            access.account_id, idempotency_key=idempotency_key
        )
    except CustomerAuthError as error:
        return _domain_error(error)
    return {"recovery": _billing_recovery_projection(result)}


@billing_router.post("/recovery/suspended-renewal")
def confirm_suspended_renewal_recovery(
    body: BillingRecoveryConfirmRequest,
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=1, max_length=200
    ),
    access: AccessContext = Depends(require_fresh_financial_auth),
    _: None = Depends(require_same_site_origin),
    executor=Depends(get_billing_recovery_executor),
):
    if body.confirm is not True:
        return _error("BILLING_RECOVERY_CONFIRMATION_REQUIRED", 400)
    try:
        result = executor.recover_suspended_renewal(
            access.account_id, idempotency_key=idempotency_key
        )
    except CustomerAuthError as error:
        return _domain_error(error)
    return {"recovery": _billing_recovery_projection(result)}


@sessions_router.get("")
def list_sessions(
    access: AccessContext = Depends(require_customer_session),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
):
    rows = SessionService(session, clock).list_active_sessions(access.account_id)
    return {"sessions": [_session_projection(row, access.session_id) for row in rows]}


@sessions_router.delete("/{session_id}")
def revoke_one_session(
    session_id: uuid.UUID,
    access: AccessContext = Depends(require_customer_session),
    _: None = Depends(require_same_site_origin),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
):
    target = session.get(BrowserSession, session_id)
    if target is None or target.account_id != access.account_id:
        return _error("SESSION_NOT_FOUND", 404)
    SessionService(session, clock).revoke_session(
        session_id, reason=SessionRevokeReason.USER_LOGOUT.value
    )
    return {"revoked": True}


@auth_router.post("/logout")
def logout_current_session(
    response: Response,
    access: AccessContext = Depends(require_customer_session),
    _: None = Depends(require_same_site_origin),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
    config: CustomerApiSecurityConfig = Depends(get_customer_api_security_config),
):
    SessionService(session, clock).revoke_session(
        access.session_id, reason=SessionRevokeReason.USER_LOGOUT.value
    )
    _clear_session_cookie(response, config)
    return {"logged_out": True}


@auth_router.post("/logout-all")
def logout_all_sessions(
    response: Response,
    access: AccessContext = Depends(require_fresh_auth),
    _: None = Depends(require_same_site_origin),
    session: Session = Depends(get_customer_db_session),
    clock: Clock = Depends(get_clock),
    config: CustomerApiSecurityConfig = Depends(get_customer_api_security_config),
):
    count = SessionService(session, clock).revoke_all_sessions(
        access.account_id, reason=SessionRevokeReason.USER_LOGOUT_ALL.value
    )
    _clear_session_cookie(response, config)
    return {"logged_out_all": True, "revoked_count": count}


customer_router.include_router(identity_router)
customer_router.include_router(auth_router)
customer_router.include_router(account_router)
customer_router.include_router(sessions_router)
customer_router.include_router(onboarding_router)
customer_router.include_router(payment_methods_router)
customer_router.include_router(trial_router)
customer_router.include_router(conversion_router)
customer_router.include_router(billing_router)


def create_customer_test_app() -> FastAPI:
    """Build an unmounted app for isolated transport tests only."""
    app = FastAPI()
    app.include_router(customer_router)

    @app.exception_handler(CustomerAuthError)
    async def customer_auth_error_handler(request, error):
        del request
        return _domain_error(error)

    return app


def _error(code: str, status: int) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code}})


def _domain_error(error: CustomerAuthError) -> JSONResponse:
    status = 400
    if isinstance(error, AgeNotEligible):
        status = 422
    elif error.code == "REQUEST_ORIGIN_REJECTED":
        status = 403
    elif isinstance(error, (AuthenticationRequired, SessionInvalid, SessionExpired, SessionRevoked)):
        status = 401
    elif isinstance(error, StepUpRequired):
        status = 403
    elif isinstance(error, LoginChallengeInvalid):
        status = 400
    elif isinstance(error, PaymentMethodNotFound):
        status = 404
    elif isinstance(error, TrialNotFound):
        status = 404
    elif isinstance(error, IdempotencyKeyConflict):
        status = 409
    elif isinstance(
        error,
        (
            CatalogUnavailable,
            ConversionNotEligible,
            ConversionSelectionInvalid,
            ConversionSelectionRequired,
            FirstChargeConflict,
            RenewalBillingConflict,
        ),
    ):
        status = 409
    elif isinstance(
        error, (PaymentMethodRequired, DeliveryEmailUnverified, TrialNotEligible)
    ):
        status = 409
    elif isinstance(error, PaymentProviderStateUnknown):
        status = 409
    elif isinstance(error, PaymentMethodVerificationFailed):
        status = 422
    elif isinstance(error, (PaymentProviderNotConfigured, PaymentProviderUnavailable)):
        status = 503
    return _error(error.code, status)


def _set_session_cookie(response: Response, token: str, remember_login: bool, config) -> None:
    settings = session_cookie_settings(
        remember_login=remember_login, secure=config.cookie_secure
    )
    response.set_cookie(
        key=settings.name,
        value=token,
        max_age=settings.max_age,
        httponly=settings.http_only,
        secure=settings.secure,
        samesite=settings.same_site,
        path=settings.path,
        domain=settings.domain,
    )


def _clear_session_cookie(response: Response, config) -> None:
    settings = cleared_cookie_settings(secure=config.cookie_secure)
    response.set_cookie(
        key=settings.name,
        value="",
        max_age=settings.max_age,
        httponly=settings.http_only,
        secure=settings.secure,
        samesite=settings.same_site,
        path=settings.path,
        domain=settings.domain,
    )


def _account_projection(session: Session, clock: Clock, account: CustomerAccount, session_id) -> Dict[str, Any]:
    stage = OnboardingService(session, clock, IdentityService(session, clock)).status_for_account(account.id)
    return {
        "account": {
            "account_id": str(account.id),
            "account_email": account.account_email,
            "mobile_display": _mobile_display(account.mobile_e164),
            "status": account.status,
        },
        "onboarding": {"next_required_stage": stage},
        "session": {"session_id": str(session_id)},
    }


def _session_projection(row: BrowserSession, current_session_id) -> Dict[str, Any]:
    return {
        "session_id": str(row.id),
        "current": row.id == current_session_id,
        "remember_login": row.remember_login,
        "created_at": row.created_at.isoformat(),
        "last_seen_at": row.last_seen_at.isoformat(),
        "user_agent_summary": row.user_agent_summary,
    }


def _payment_method_projection(method: PaymentMethod) -> Dict[str, Any]:
    """Browser-safe metadata. Billing/verification references stay server-side."""
    return {
        "payment_method_id": str(method.id),
        "provider": method.provider,
        "brand": method.card_brand,
        "last4": method.card_last4,
        "display_label": method.display_label,
        "status": method.status,
        "is_default": method.is_default,
        "own_name_verified": method.own_name_verified,
    }


def _trial_projection(result: TrialResult) -> Dict[str, Any]:
    """Trial-only projection: no paid plan, price, or provider credential."""
    subscription = result.subscription
    return {
        "subscription_id": str(subscription.id),
        "state": subscription.state,
        "trial_start_at": subscription.trial_start_at.isoformat(),
        "trial_end_at": subscription.trial_end_at.isoformat(),
        "delivery_start_date": subscription.delivery_start_date.isoformat(),
        "products": list(result.products),
        "automatic_paid_conversion": False,
    }


def _conversion_eligibility_projection(result: ConversionEligibility) -> Dict[str, Any]:
    return {
        "subscription_id": str(result.subscription.id),
        "state": result.subscription.state,
        "eligible": result.eligible,
        "opens_at": result.opens_at.isoformat(),
        "closes_at": result.closes_at.isoformat(),
        "automatic_paid_conversion": False,
    }


def _conversion_projection(result: ConversionResult) -> Dict[str, Any]:
    snapshot = result.snapshot
    return {
        "subscription_id": str(result.subscription.id),
        "state": result.subscription.state,
        "selection_id": str(result.selection.id),
        "plan_code": result.selection.plan_code,
        "products": list(result.products),
        "price_krw": result.selection.price_krw,
        "price_version": result.selection.price_version,
        "currency": result.selection.currency,
        "confirmed": snapshot is not None,
        "confirmed_at": snapshot.confirmed_at.isoformat() if snapshot else None,
        "first_charge_at": snapshot.first_charge_at.isoformat() if snapshot else None,
        "charged": False,
    }


def _recovery_eligibility_projection(result) -> Dict[str, Any]:
    return {
        "kind": result.kind,
        "eligible": result.eligible,
        "status": result.status,
        "subscription_id": (
            str(result.subscription_id) if result.subscription_id else None
        ),
        "billing_attempt_id": (
            str(result.billing_attempt_id) if result.billing_attempt_id else None
        ),
        "reconciliation_required": result.reconciliation_required,
        "explicit_action_required": result.explicit_action_required,
    }


def _billing_recovery_projection(result: BillingRecoveryResult) -> Dict[str, Any]:
    return {
        "kind": result.kind,
        "status": result.status,
        "subscription_id": (
            str(result.subscription_id) if result.subscription_id else None
        ),
        "billing_attempt_id": (
            str(result.billing_attempt_id) if result.billing_attempt_id else None
        ),
        "replayed": result.replayed,
        "reconciliation_required": result.reconciliation_required,
        "delivery_available": result.delivery_available,
    }


def _mobile_display(value: Optional[str]) -> Optional[str]:
    if not value or len(value) < 7:
        return None
    return "{0}***{1}".format(value[:4], value[-4:])


def _request_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client is not None else None


def _user_agent(request: Request) -> Optional[str]:
    value = request.headers.get("user-agent")
    return value[:200] if value else None
