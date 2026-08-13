# GENIE × KeeSuri — Customer Auth, Identity & Session Spec v1

**Status:** APPROVED
**Version:** v1
**As of:** 2026-08-10 (KST)
**Authority:** Customer identity verification, passwordless auth, sessions
**Parent:** `docs/web/GENIE_KEYSURI_CUSTOMER_WEB_SSOT_v1.md`
**Map:** `docs/web/DOCUMENT_MAP_AND_AUTHORITY.md`

**Scope:** This specification applies **ONLY** to the **customer product**.

It does **NOT** authorize:

- Admin
- operator consoles
- owner-review surfaces

Customer passwordless sessions **MUST NOT** authorize operator/Admin APIs.
Operator auth / signed review-link contexts **MUST NOT** be treated as customer login.

**MUST NOT** invent a specific identity-verification vendor in this document. Vendor selection is **EXTERNAL VALIDATION REQUIRED**.
Do **NOT** invent a full operator-auth architecture here; preserve stronger existing Admin authentication.

---

## 1. Adult-only absolute rule

GENIE × KeeSuri is an **adult-only** service.

| Rule | Requirement |
|------|-------------|
| Minimum age | **19** (Republic of Korea age eligibility as enforced via IDV) |
| Minors | **MUST NOT** register, start trial, register a card, subscribe, or receive customer briefing delivery |
| Guardian consent | **MUST NOT** create an exception |
| Enforcement | Through **identity verification**, not a self-entered birthdate checkbox |

If verification indicates age under 19:

- Terminate signup
- **MUST NOT** create customer account, trial, subscription, or payment method
- Stable error/status: `AGE_NOT_ELIGIBLE`

**MUST NOT** permanently store full birthdate unless technically or legally required. Prefer:

- `adult_verified`
- `adult_verified_at`
- verification provider / reference

---

## 2. Stable person identity

**MUST NOT** use phone number as the permanent person identity.

**MUST** use a stable identifier from the identity-verification provider (e.g. **DI** or equivalent service-level identity key).

**SHOULD** avoid CI unless actually necessary.

Invariant:

```
1 verified person
= 1 active customer identity
= 1 active account
```

| Scenario | Behavior |
|----------|----------|
| Same stable identity, second active signup | **MUST NOT** create another account; route to account recovery/login |
| Same phone, different verified identity | **MUST NOT** merge users merely because phone matches |
| Phone-number change | Verify new number/person; stable identity **MUST** match existing customer; else reject with identity mismatch → support review |

Trial eligibility (Lifecycle) keys on this stable identity, **not** email/phone/card.

---

## 3. Passwordless authentication

There is **NO** customer password.

| Flow | Method |
|------|--------|
| Initial signup | Full **mobile identity verification** (IDV) |
| Routine login | Passwordless: registered **email verification** OR registered **mobile verification** |

Roles remain distinct:

```
identity verification (IDV)
≠
routine login OTP / magic-link verification
```

Prototype password fields are **NON-CANONICAL** and MUST NOT be implemented as product policy.

---

## 4. Login UI — Keep me signed in

Login UI **MUST** include:

```
[ ] 로그인 유지 / Keep me signed in
```

**Default: OFF**

### 4.1 When OFF

- Normal browser session
- Absolute session lifetime: **12 hours**
- Inactivity expiration: **2 hours**
- Browser session cookie **SHOULD NOT** be intentionally persistent

### 4.2 When ON

- Persistent browser session
- Absolute lifetime: **30 days**
- Inactivity expiration: **7 days**

Long-lived browser session **MUST NOT** mean a single 30-day bearer access token.

Architecture **MUST** separate:

- short-lived access credential / session (**~15 minutes** baseline unless a safer equivalent is required)
- revocable **server-managed** browser session

Each browser/device has an **independent** session.

---

## 5. Step-up reauthentication

Sensitive actions require **recent reauthentication** even when Keep me signed in is ON.

**Fresh-authentication window: 10 minutes**

### 5.1 Sensitive actions (minimum)

- Add / replace / delete eligible payment card
- Confirm paid conversion
- Confirm plan change
- Cancel subscription / cancel scheduled cancellation
- Membership withdrawal / cancel scheduled withdrawal
- Account-email change
- Delivery-email change
- Phone-number change
- Account recovery
- Logout all devices

### 5.2 Risk levels

| Risk | Requirement |
|------|-------------|
| Lower-risk email ownership change | Current-session reauthentication + new email ownership verification |
| Financial / subscription actions | Mobile OTP / equivalent strong reauthentication |
| Identity-destructive actions | Full mobile identity verification |

Phone-number change and membership withdrawal **MUST** require full identity verification.

---

## 6. Concurrent sessions

Multiple personal-device sessions are **allowed**.

**MUST NOT** impose a simplistic hard limit such as max 3 or max 5 devices.

Each browser session is independently revocable.

Customer **MUST** be able to:

- view active sessions
- revoke one session
- logout all sessions

**MUST NOT** terminate a session solely because IP address changed.
**SHOULD** use risk-based step-up for abnormal patterns.
**MUST NOT** build excessive permanent device fingerprinting.

---

## 7. Trust boundaries

| Boundary | Rule |
|----------|------|
| Customer browser | Untrusted; holds only opaque session cookies / short-lived access tokens |
| Customer API | Authenticates sessions; enforces step-up |
| IDV provider | Source of adult result + stable person key |
| Login OTP / magic-link | Proves control of registered email or mobile — not full IDV |
| Admin / operator auth | Separate trust domain (`GENIE_ADMIN_PASSWORD` / ops console / signed owner-review link validation). Customer session **MUST NOT** authorize it. |
| Owner-review deep link | MAY bootstrap constrained review context after server validation; **MUST NOT** equal permanent Admin bearer authority or customer session |
| Payment provider | Card data vault; service stores billing key only |

---

## 8. Failure states

| Code / state | Meaning | Fail-closed behavior |
|--------------|---------|----------------------|
| `AGE_NOT_ELIGIBLE` | Under 19 | No account / trial / PM / delivery |
| `IDV_FAILED` | Verification failed or abandoned | No account creation |
| `IDENTITY_ALREADY_REGISTERED` | DI already has active account | Route to login/recovery |
| `IDENTITY_MISMATCH` | Phone change / recovery identity mismatch | Reject; support review |
| `LOGIN_CHALLENGE_INVALID` | OTP/magic-link invalid/expired | No session |
| `SESSION_EXPIRED` | Absolute or inactivity timeout | Re-login required |
| `STEP_UP_REQUIRED` | Sensitive action without fresh auth | Challenge then retry |
| `SESSION_REVOKED` | User or system revoked session | Re-login required |

---

## 9. Security invariants

1. No customer password storage or password login.
2. Adult gate before account, trial, card, subscription, delivery.
3. One active account per stable verified person.
4. Short-lived access token ≠ long-lived refresh/browser session.
5. Step-up window is **10 minutes** for listed sensitive actions.
6. Session revocation is server-authoritative.
7. Customer auth APIs **MUST NOT** expose admin approve/send/Scheduler/Secrets.
8. Customer account ≠ operator identity; customer session ≠ Admin authorization.

---

## 10. Minimum proposed data model

Conceptual only (not a schema migration):

### `person_identity`

- `person_id` (internal)
- `idv_stable_key` (DI or equivalent; unique)
- `adult_verified` (bool)
- `adult_verified_at`
- `idv_provider`
- `idv_reference`
- `created_at`

### `customer_account`

- `account_id`
- `person_id` (1:1 active)
- `account_email`
- `mobile_e164` (registered; changeable under policy)
- `status` (`active` | `withdrawn` | …)
- `created_at`

### `browser_session`

- `session_id`
- `account_id`
- `remember_login` (bool)
- `absolute_expires_at`
- `inactivity_expires_at`
- `last_seen_at`
- `revoked_at` (nullable)
- `user_agent_summary` (minimal)

### `access_credential` (optional separate)

- short-lived token metadata bound to `session_id`

### `trial_eligibility_block`

- `idv_stable_key`
- `block_expires_at` (1 year from trial end)
- separated from operational membership tables

---

## 11. Account recovery

- Prove control of registered email or mobile (routine challenge)
- For high-risk recovery (e.g. both channels compromised): require full IDV matching `idv_stable_key`
- Successful recovery **MUST** offer revoke-all-sessions

---

## 12. Related documents

- Lifecycle (trial eligibility retention): `CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md`
- Delivery email ownership: `CUSTOMER_DELIVERY_ENTITLEMENT_CONTRACT_v1.md`
- UX flows: `FRONTEND_UX_SPEC_v1.md`
- API: `FRONTEND_API_CONTRACT_v1.md`
