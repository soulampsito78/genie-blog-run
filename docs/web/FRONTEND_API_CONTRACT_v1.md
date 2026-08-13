# GENIE × KeeSuri — Frontend / API Contract v1

**Status:** APPROVED (design contract — not implemented)
**Version:** v1
**As of:** 2026-08-10 (KST)
**Authority:** Future customer API boundary for the customer web
**Parent:** `docs/web/GENIE_KEYSURI_CUSTOMER_WEB_SSOT_v1.md`
**Map:** `docs/web/DOCUMENT_MAP_AND_AUTHORITY.md`

This is a **DESIGN CONTRACT**, not runnable code. Paths are conceptual.
Implementations MUST obey Lifecycle, Auth, and Delivery policies.

---

## 1. Global API rules

Two **separate trust domains**:

| Domain | Scope |
|--------|-------|
| **A. CUSTOMER API** | identity, login/session, account, subscription, payment, delivery-email, customer lifecycle |
| **B. PRIVATE OPERATOR / OWNER-REVIEW API** | review-link token validation, review-context retrieval, authorized owner actions; ops Admin APIs |

Customer session tokens **MUST NOT** authorize domain B.
Operator credentials / review tokens **MUST NOT** authorize customer-lifecycle mutations as if they were the customer.

| Rule | Requirement |
|------|-------------|
| Auth (customer) | Customer session (short-lived access + server session) only for domain A |
| Auth (operator) | Separate operator auth and/or validated signed review-link context for domain B; preserve stronger existing Admin auth |
| Idempotency | Payment, conversion, cancel, withdraw, token delete, delivery-key sends, D-3 notify, SMS bounce notify MUST be idempotent (`Idempotency-Key` or equivalent) |
| Truth | Provider webhooks / server verification beat browser redirects |
| Fail-closed | Unknown payment or IDV state → do not activate entitlement or charge |
| Tenancy | All customer mutations scoped to authenticated `account_id` |

### 1.1 Forbidden operational crossings (customer API)

Customer APIs **MUST NOT** expose:

- Cloud Scheduler control
- SMTP send primitives
- Owner-review approval
- Production Secrets
- Raw GCS operational controls
- Raw `/internal/jobs/*` invocation
- Admin / operator route discovery for customer clients

Customer delivery of briefings remains an **ops-approved pipeline** consuming entitlement snapshots — not a customer “Send now” API.

---

## 2. Customer API family catalog

The families below are **domain A only**. They are **not** Admin APIs.

### 2.1 Identity (`/v1/identity/...`)

| Aspect | Spec |
|--------|------|
| Purpose | Start/complete adult IDV; return adult result + bindable stable key handle |
| Authority | Auth spec |
| Auth level | Pre-account bootstrap token OR anonymous + anti-abuse |
| Step-up | N/A (this IS the high-assurance gate) |
| Idempotency | Provider session idempotent |
| Allowed | Create IDV session; poll/complete; receive `AGE_NOT_ELIGIBLE` / success |
| Forbidden | Storing full birthdate by default; creating account if under 19 |

### 2.2 Auth / session (`/v1/auth/...`)

| Aspect | Spec |
|--------|------|
| Purpose | Passwordless login challenges; create/refresh/revoke sessions; Keep-me-signed-in |
| Authority | Auth spec |
| Auth level | Challenge → session |
| Step-up | N/A for login; used by other families |
| Idempotency | Challenge consume once |
| Allowed | Email/mobile login start/verify; logout; logout-all; list sessions; revoke session |
| Forbidden | Password set/reset; 30-day bearer access tokens |

Session lifetimes: OFF → 12h absolute / 2h idle; ON → 30d absolute / 7d idle; access ~15m.

### 2.3 Account (`/v1/account/...`)

| Aspect | Spec |
|--------|------|
| Purpose | Read/update account profile channels |
| Authority | Auth + Delivery (emails) |
| Auth level | Logged-in |
| Step-up | Email change (lower-risk + ownership verify); phone change (full IDV) |
| Allowed | Get account; request account_email change; request phone change |
| Forbidden | Merge accounts by phone; second active account for same DI |

### 2.4 Plans / catalog (`/v1/catalog/plans`)

| Aspect | Spec |
|--------|------|
| Purpose | Public current catalog (VAT-inclusive) |
| Auth level | Public or logged-in |
| Allowed | List plans/prices/product codes |
| Forbidden | Mutating historical contract prices |

### 2.5 Trial eligibility (`/v1/trial/eligibility`)

| Aspect | Spec |
|--------|------|
| Purpose | Check 1-year DI-keyed eligibility |
| Authority | Lifecycle |
| Auth level | Post-IDV |
| Allowed | `{ eligible: bool, reason }` |
| Forbidden | Eligibility keyed primarily by email/phone/card |

### 2.6 Subscription (`/v1/subscriptions/...`)

| Aspect | Spec |
|--------|------|
| Purpose | Start trial (no paid plan); read state; D-3 plan selection + conversion; cancel; withdraw |
| Authority | Lifecycle |
| Auth level | Logged-in + step-up for mutations below |
| Step-up | Convert, cancel, withdraw, revoke cancel/withdraw per Auth |
| Idempotency | Required on start/convert/cancel/withdraw |
| Allowed states | Per Lifecycle state machine |
| Forbidden | Auto-convert without explicit consent; charge at D-3; grace for never-paid; requiring paid plan on `trial/start` |

Key operations:

- `POST .../trial/start` — IDV done, own-name PM required, Full Set, `delivery_start_date` set; **MUST NOT** require `plan_code` / paid-plan selection
- `POST .../conversion/accept` — requires authenticated session + step-up; body carries or references pending conversion selection: `plan_code`, `selected_products` when `package_two`, price/`price_version` snapshot; result `conversion_scheduled`
- `POST .../cancellation` / `DELETE .../cancellation`
- `POST .../withdrawal` / `DELETE .../withdrawal`

Conversion acceptance **MUST** freeze the pending conversion snapshot (Lifecycle §1.1). Browser redirect alone is not payment success.

### 2.7 Payment methods (`/v1/payment-methods/...`)

| Aspect | Spec |
|--------|------|
| Purpose | Add/list/set-default/delete billing keys |
| Authority | Lifecycle |
| Auth level | Logged-in + financial step-up |
| Idempotency | Add/delete |
| Allowed | Add before delete; one default |
| Forbidden | PAN/CVV submission to app servers; delete sole method while obligation exists (`PAYMENT_METHOD_REPLACEMENT_REQUIRED`) |

### 2.8 Billing (`/v1/billing/...`)

| Aspect | Spec |
|--------|------|
| Purpose | Invoices/receipts metadata; retry never-paid or past_due recovery |
| Authority | Lifecycle |
| Auth level | Logged-in + step-up for charge retry |
| Idempotency | Charge attempts |
| Allowed | Explicit retry after card update |
| Forbidden | Treating redirect as success; renew without verified delivery_email |

Server jobs (not customer-callable raw): Day0/+1/+3 renewal retries.

### 2.9 Plan changes (`/v1/subscriptions/{id}/plan-change`)

| Aspect | Spec |
|--------|------|
| Purpose | Request next-renewal plan change for **already-active** paid subscribers |
| Step-up | Yes |
| Allowed | Latest request wins; apply only after successful renewal charge |
| Forbidden | Mid-cycle proration charges/refunds; using this endpoint for D-3 **initial** conversion (use `conversion/accept`) |

Initial D-3 paid-plan selection belongs to `conversion/accept`, not this family.

### 2.10 Cancellation / refund / withdrawal

| Aspect | Spec |
|--------|------|
| Purpose | Schedule/revoke cancel; open refund review; schedule/revoke withdraw |
| Step-up | Cancel/revoke: financial; Withdraw: full IDV |
| Allowed | Paid cancel at period end; trial cancel immediate; refund cases A/B/D review |
| Forbidden | Auto prorated refund engine; withdraw without IDV |

### 2.11 Delivery email (`/v1/delivery-email/...`)

| Aspect | Spec |
|--------|------|
| Purpose | Change/verify single active delivery_email |
| Authority | Delivery |
| Step-up | Per Auth email tier |
| Allowed | Pending verify → activate; next snapshot applies |
| Forbidden | Dual-address same publication; per-product addresses |

### 2.12 Sessions (`/v1/sessions/...`)

Covered under Auth/session; listed for UX mapping.

### 2.13 Delivery status / recovery (`/v1/delivery/...`)

| Aspect | Spec |
|--------|------|
| Purpose | Customer-visible delivery health; hard-bounce recovery entry |
| Auth level | Logged-in |
| Allowed | Read suppression reasons; start delivery-email recovery |
| Forbidden | Customer-triggered resend of provider-accepted delivery keys; bulk missed-issue backfill; SMTP controls |

Ops systems own snapshot creation and send after approve.

---

## 2A. Private Operator / Owner-Review API (domain B)

**MUST NOT** be documented or called as a customer-frontend API family.

| Aspect | Spec |
|--------|------|
| Purpose | Validate signed owner-review deep links; retrieve exact review/run context; perform explicitly authorized owner actions; support operator visibility (bounce, contact failure, refund review, audit) where ops policy allows |
| Authority | Ops / architecture / existing Admin safety (`docs/architecture/*`, `OPERATIONS.md`, review-operation docs) — not customer Web SSOT IA |
| Auth level | **Operator** auth and/or server-validated review-link context — **never** a customer session |
| Review link | High-entropy; time-limited; revocable; scoped to one review/run; **MUST NOT** become permanent unrestricted Admin bearer authority |
| Allowed | Review-context GET after validation; constrained owner actions under existing confirm gates |
| Forbidden | Customer-session access; Scheduler/Secrets/SMTP/GCS destructive shortcuts without existing ops confirm; treating link-open as approval |

If concrete operator endpoints already exist (e.g. `/admin/*`, approve nonce flows), **reference** those ops contracts rather than duplicating them here.

Invariants:

```
opening review link ≠ approval
approval ≠ customer send
customer send ≠ customer receipt
```

---

## 3. Notification jobs (server-side; not public customer APIs)

| Job | Rules |
|-----|-------|
| D-3 conversion invite | Idempotent; email + SMS fallback; no trial extension on failure |
| Soft/Hard Bounce SMS | One SMS per incident type rules in Delivery; track submitted→delivered |
| Token deletion retry | After trial expire / cancel / withdraw; alert on failure; never charge |
| Renewal retries | Day 0/+1/+3; idempotent; preserve billing anchor on recovery |

---

## 4. Error contract (shared)

APIs SHOULD return stable machine codes including:

`AGE_NOT_ELIGIBLE`, `IDENTITY_ALREADY_REGISTERED`, `IDENTITY_MISMATCH`, `STEP_UP_REQUIRED`, `SESSION_EXPIRED`, `PAYMENT_METHOD_REPLACEMENT_REQUIRED`, `DELIVERY_EMAIL_UNVERIFIED`, `TRIAL_NOT_ELIGIBLE`, `CONVERSION_NOT_CONFIRMED`, `HARD_BOUNCE_SUPPRESSED`, `IDEMPOTENCY_REPLAY`, `PROVIDER_STATE_UNKNOWN`

---

## 5. Relationship to existing FastAPI service

**FACT:** Current service exposes `/health`, `POST /`, `/admin/*`, `/internal/jobs/*`.

**IMPLEMENTATION REQUIREMENT:** Customer API families (domain A) are a **new** product surface. Operator `/admin/*` and internal jobs remain **domain B**. Customer sessions **MUST NOT** authorize domain B. Entitlement engine feeds recipient snapshots consumed by existing customer delivery modules after ops approval.

---

## 6. External dependencies

IDV vendor, PG, SMS provider, ESP webhooks — **VENDOR CAPABILITY VALIDATION**.
Legal texts — **LEGAL IMPLEMENTATION VALIDATION**.

---

## 7. Related documents

- `CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md`
- `CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md`
- `CUSTOMER_DELIVERY_ENTITLEMENT_CONTRACT_v1.md`
- `FRONTEND_UX_SPEC_v1.md`
