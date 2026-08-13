# GENIE × KeeSuri — Customer Lifecycle & Billing Policy v1

**Status:** APPROVED
**Version:** v1
**As of:** 2026-08-10 (KST)
**Authority:** Customer subscription / trial / billing / cancel / refund / withdrawal
**Parent:** `docs/web/GENIE_KEYSURI_CUSTOMER_WEB_SSOT_v1.md`
**Map:** `docs/web/DOCUMENT_MAP_AND_AUTHORITY.md`

This document is FIXED PRODUCT POLICY. Do not reopen prices, trial length, or conversion rules without an explicit owner supersession.

---

## 1. Catalog and pricing

All prices are **monthly** and **VAT-inclusive**.

| `plan_code` | Products included | Monthly price (KRW) |
|-------------|-------------------|---------------------|
| `today_genie` | `today_genie` | 6,600 |
| `keysuri_global` | `keysuri_global` | 9,900 |
| `keysuri_korea` | `keysuri_korea` | 6,600 |
| `package_two` | Exactly two of `{today_genie, keysuri_global, keysuri_korea}` | 11,000 |
| `full_set` | All three | 16,500 |

`full_set` price composition: supply price KRW 15,000 + VAT KRW 1,500 = KRW 16,500.
The upgrade delta from `package_two` to `full_set` is KRW 5,500.
The three standalone prices total KRW 23,100; Full Set vs that total differs by KRW 6,600.
**CURRENT** customer-facing step-up message: `2종에서 월 5,500원 추가` (or semantically equivalent).
**MUST NOT** claim a universal “둘 값에 셋” mathematical identity.

**MUST NOT** use as current customer policy:

- KRW 14,300 Full Set (**HISTORICAL** — superseded by owner decision 2026-08-11 → KRW 16,500)
- KRW 29,900 single price
- 5-day trial
- “1+1 package”

### 1.1 Price versioning and conversion snapshot timing

Each **paid** subscription contract **MUST** snapshot agreed price / price version.

**MUST NOT** create a contracted paid-plan price snapshot at **trial signup**.
During `trialing` / `renewal_pending` (before explicit conversion), paid plan = **NONE**.

At **explicit D-3 paid-conversion confirmation**, freeze a **pending conversion snapshot**:

- `pending_plan_code`
- selected product set if `package_two`
- agreed VAT-inclusive price
- `price_version`
- `confirmed_at`

The first charge at `trial_end_at` **MUST** use this pending conversion snapshot.
Only after provider/server-verified successful payment does it become the active paid contract:

- `contracted_plan_code`
- `contracted_price_krw`
- `price_version`
- selected product set for `package_two`

**MUST NOT** bill an existing contract by blindly reading the live catalog price.
Future catalog changes **MUST NOT** silently mutate historical or current-period contracts.

---

## 2. Publication calendar (customer billing/delivery calendar)

**FIXED POLICY:**

- Timezone: **KST**
- Publish: **weekdays only**
- **MUST NOT** publish on weekends
- **MUST NOT** publish on Republic of Korea public holidays

One customer publication-calendar policy applies to all three products.

Foreign-market holidays MAY influence content/data logic. They **MUST NOT** create a second customer billing/publication calendar.

Holiday calendar source is an **IMPLEMENTATION REQUIREMENT** (authoritative ROK holiday list). Until wired, product policy remains: holidays are non-publication days.

---

## 3. Free trial

| Rule | Value |
|------|-------|
| Duration | **14 calendar days** (NOT 14 publication days) |
| Entitlement during trial | **Full Set** (`today_genie` + `keysuri_global` + `keysuri_korea`) |
| Charge during trial | **None** |
| Payment method at signup | **REQUIRED** — verified customer’s **own-name** card / method |
| Paid plan at signup | **NONE** — paid-plan selection is **not** part of trial signup |
| Auto paid conversion | **MUST NOT** occur |

### 3.0 Trial signup prerequisites (canonical)

Trial start **MUST** require, in order:

1. Adult identity verification (age ≥ 19)
2. Account creation + email ownership verification
3. Own-name payment method registration
4. Trial confirmation (Full Set)

Trial start **MUST NOT** require:

- paid-plan selection
- future paid-plan price commitment
- conversion consent

### 3.1 First delivery timing

- **MUST NOT** deliver a briefing on the subscription/trial application calendar day
- Delivery eligibility starts from the **next calendar day**
- If that day is not a publication day, first delivery is the **next publication day**

### 3.2 Trial eligibility retention

After a free trial ends:

- Retain **minimum verified-person identity evidence** needed to prevent duplicate free trials
- Retention: **1 year**
- Operational membership data and eligibility evidence **MUST** be separated

Within the 1-year block:

- **MUST NOT** grant a new free trial to the same verified person

After expiry:

- Delete blocking identity evidence per policy
- Person MAY become eligible again

Effective rule: **maximum one free trial per verified person per 1-year eligibility window**.

**MUST NOT** key trial eligibility primarily by email, phone number, or payment card.
**MUST** key by stable verified-person identity (see Auth spec).

---

## 4. Free-trial conversion (no automatic paid conversion)

Card registration **MUST NOT** equal consent to paid conversion.

**INITIAL paid-plan selection** occurs only in this D-3 conversion flow.
It is **not** the same operation as a later `active` subscriber plan change (§9).

### 4.1 D-3 invitation

Three calendar days before `trial_end_at`:

- **MUST** send an explicit renewal/conversion invitation (email)
- SMS fallback and My Page CTA per §4.3
- Invitation meaning: customer has experienced Full Set; they now choose what to continue as paid
- Invitation **MUST NOT** assume a plan was selected at signup

### 4.1A Explicit conversion (plan selection + consent)

To continue as paid, the customer **MUST**:

1. Open renewal link / My Page CTA (passwordless login if needed; deep-link to plan selection)
2. Select **one** of the five paid plans (catalog §1); `package_two` requires exactly two products
3. Complete mobile step-up reauthentication
4. Explicitly confirm paid conversion

**D-3 neutrality (HARD):**

- **MUST NOT** preselect any paid plan (including Full Set)
- **MUST NOT** show `강력 추천` / `가장 인기` / `MOST POPULAR` / `BEST VALUE` / unsupported recommendation badges
- All plan options start **neutral**; emphasis only after customer hover/focus/touch/explicit selection
- Continuation CTA **MUST** stay disabled until an explicit valid plan selection exists
- Confirmation UI **MUST** show the actually chosen plan and frozen pending price (catalog §1; Full Set = KRW 16,500 VAT included)

Then:

- Freeze **pending conversion snapshot** (§1.1)
- State → `conversion_scheduled`
- **MUST NOT** charge at D-3
- **MUST** schedule first paid charge for `trial_end_at`
- Trial Full Set entitlement remains until trial end

If no explicit plan selection + conversion consent by trial end:

- Trial ends → `trial_expired`
- Customer delivery **OFF**
- **MUST NOT** attempt paid charge
- Provider payment token/billing key **MUST** be destroyed immediately
- No paid-plan selection is required to reach `trial_expired`

### 4.2 Token deletion failure

If provider token deletion fails:

- Trial still ends; delivery stays OFF; **MUST NOT** charge
- Mark deletion retry required
- Create operational/admin alert
- Retry deletion independently (idempotent)

### 4.3 D-3 notification failure

If D-3 renewal email fails:

- Retry email safely (idempotent)
- Use **SMS** as fallback notification
- Expose renewal availability in customer web account
- **MUST NOT** extend the trial because notification failed

---

## 5. Payment methods

### 5.1 Storage

The service **MUST NEVER** store:

- full PAN / card number
- CVV / CVC
- card password
- raw sensitive card authentication payload

Provider handles card data. Service stores provider token/billing key + minimal safe display metadata only.

Own-name card verification mechanism: **VENDOR CAPABILITY VALIDATION** (required capability, vendor TBD).

### 5.2 Add / replace / delete

While a future billing obligation exists, a valid **default** payment method **MUST** always exist.

**MUST NOT** delete the only valid/default method first.

Replacement flow:

1. Register new own-name card
2. Verification succeeds
3. Set new card as default
4. Confirm default switch
5. Old card becomes removable
6. Delete/revoke old provider token when requested

Core rule: **ADD NEW CARD BEFORE DELETE OLD CARD**

Temporary multiple cards during replacement are allowed; only **one** default.

If future billing obligation exists and only one valid method remains:

- Reject deletion with `PAYMENT_METHOD_REPLACEMENT_REQUIRED`

When no future billing obligation remains (trial expired without renewal; paid cancellation effective):

- Payment token **MAY/MUST** be destroyed without replacement (MUST destroy when policy requires end of obligation).

---

## 6. Billing anchor and dates

Preserve original `billing_anchor_day`.

If that day does not exist in a month: bill on that month’s **final calendar day**.
**MUST NOT** permanently move the anchor because February was shorter.

Examples:

- Jan 31 → Feb 28/29 → Mar 31 → Apr 30 → May 31
- Jan 30 → Feb 28/29 → Mar 30

Persist at minimum:

- `billing_anchor_day`
- `current_period_start`
- `current_period_end`
- `next_billing_at`

---

## 7. Initial paid conversion charge failure

If first paid charge at `trial_end_at` fails:

- **MUST NOT** activate paid subscription
- Customer delivery stops
- **MUST NOT** provide grace for never-paid conversion
- Ask customer to update/replace card
- Customer **MUST** explicitly retry
- Activate paid only after **server/provider-verified** payment success

Browser redirect alone **MUST NOT** be payment success truth.

---

## 8. Existing paid renewal failure

For already-paid `active` subscriber:

- Failed renewal → `past_due`
- Grace period: **3 days**

Fixed retry cadence:

| Attempt | Timing |
|---------|--------|
| Scheduled billing | Day 0 |
| Retry | Day +1 |
| Final automatic retry | Day +3 |

If payment succeeds during grace:

- Restore `active`
- **Retain original billing anchor** (e.g. Aug 15 fail, Aug 17 recover → next Sep 15, **not** Sep 17)

If final retry fails:

- Suspend paid entitlement/delivery (`suspended`)
- Require payment recovery

All payment retries **MUST** be idempotent.

### 8.1 Billing requires deliverable email

**MUST NOT** charge a new renewal (first paid conversion or recurring renewal) if there is no valid, verified briefing `delivery_email` at the billing decision point.

---

## 9. Plan change (active paid subscribers only)

**MUST NOT** confuse this with D-3 **initial** paid-plan selection (§4).

| Operation | When | Behavior |
|-----------|------|----------|
| Initial conversion plan choice | `renewal_pending` → `conversion_scheduled` | §4.1A |
| Later plan change | `active` subscriber | This section |

Paid subscribers MAY request plan change at any time.

Initial product rules for **later** plan change:

- Apply at **NEXT renewal**
- **No** immediate proration
- **No** mid-cycle additional charge
- **No** automatic partial refund
- Current paid-period entitlement unchanged
- Latest valid requested plan before next billing wins

At renewal:

- Charge new plan price
- Activate new entitlement **only after** successful payment

If renewal payment fails: **MUST NOT** activate requested new plan.

For `package_two`: exactly two products **MUST** be selected.

---

## 10. Cancellation

Cancellation and refund are **separate**.

### 10.1 Paid cancellation

- Customer MAY request anytime → `cancellation_scheduled`
- **No** future renewal charge
- Current paid entitlement remains through paid period end
- Eligible briefings continue through period end
- Customer MAY revoke scheduled cancellation before effective

At effective time:

- `canceled`
- Entitlement ends; delivery ends
- Destroy provider payment token if no future billing obligation

### 10.2 Trial cancellation

Trial cancellation is **immediate**:

- Trial ends; delivery OFF
- Destroy provider payment token
- Ordinary account data follows membership/account policy

---

## 11. Refund policy

General cancellation **MUST NOT** automatically refund the current paid period.

| Case | Policy |
|------|--------|
| A. First paid period, before any paid-period briefing delivered | Eligible for **full refund** |
| B. Duplicate / system erroneous charge | **Full refund** |
| C. Paid briefing/service already provided | No automatic prorated refund engine; normal cancel at period end |
| D. Service defect / non-provision / legally required withdrawal | Separate review path |

**MUST NOT** create automated per-briefing refund formula.
**MUST NOT** claim contractual policy overrides mandatory consumer rights.

Exact legal wording: **LEGAL IMPLEMENTATION VALIDATION** before launch.

---

## 12. Membership withdrawal

### 12.1 Trial customer

Request → immediate trial termination → delivery OFF → destroy payment token → account withdrawn (`withdrawn`).

### 12.2 Paid active customer

Request → `withdrawal_scheduled` for current paid-period end → no future renewal → service through period end → at effective time: subscription canceled, delivery ends, token destroyed, account withdrawn.

**Invariant:** `withdrawal_scheduled` → next recurring charge **MUST NOT** execute.

Customer MAY revoke scheduled withdrawal before effective time.

### 12.3 Data retention after withdrawal

Account lifecycle ≠ legally required transaction retention.

At withdrawal:

- Delete/anonymize operational account data no longer required (including active auth/session and payment-method access)
- **MUST NOT** retain a reusable billing key merely because historical payment records must exist

Separate:

- operational customer data
- legally required transaction archive
- dispute / consumer-support archive
- 1-year free-trial eligibility evidence

Hashed/pseudonymous identity data is **not** automatically non-personal.
Statutory retention periods: **LEGAL IMPLEMENTATION VALIDATION** — do not invent periods here.

---

## 13. Resubscription

| Situation | Behavior |
|-----------|----------|
| Cancellation scheduled, not yet effective | Cancel the cancellation; same subscription, plan, price, anchor, payment method continue |
| Completely ended paid subscription | **NEW** subscription contract; current plans/prices; new own-name payment method; successful first charge establishes **new** billing anchor; delivery from next eligible publication day (**not** same-day) |
| Payment failure recovery | **NOT** resubscription |
| Withdrawn customer returning | New active account after IDV; **MUST NOT** reactivate old withdrawn account as operational truth; trial eligibility uses stable identity policy |

**MUST NOT** resurrect old contract price or old billing anchor after a fully ended subscription.

---

## 14. Subscription state machine

Canonical states (cleaner model; map UI labels to these):

| State | Meaning |
|-------|---------|
| `trialing` | Active free trial; Full Set entitlement; **paid plan = NONE** |
| `renewal_pending` | D-3 window; Full Set still active; paid plan **MAY** still be NONE |
| `conversion_scheduled` | Plan selected + explicit consent; pending conversion snapshot frozen; charge at `trial_end_at`; Full Set until trial end |
| `trial_expired` | Trial ended without paid activation; delivery OFF; paid plan never required |
| `active` | Paid active entitlement = selected paid plan’s product set |
| `past_due` | Paid renewal failed; within 3-day grace |
| `suspended` | Grace exhausted; paid entitlement/delivery suspended |
| `cancellation_scheduled` | Paid cancel requested; active until period end |
| `canceled` | Paid subscription ended |
| `withdrawal_scheduled` | Withdrawal requested; service until period end (paid) or immediate (trial) |
| `withdrawn` | Account withdrawn |

### 14.1 Primary transitions

| From | Event | To |
|------|-------|----|
| — | Signup: IDV + account/email + own-name PM + trial start (**no** paid-plan selection) | `trialing` |
| `trialing` | D-3 invitation sent | `renewal_pending` (MAY remain `trialing` with flag) |
| `trialing` / `renewal_pending` | Plan selected + explicit convert confirmation | `conversion_scheduled` |
| `conversion_scheduled` | Charge success at trial end (pending snapshot) | `active` |
| `conversion_scheduled` | Charge failure | `trial_expired` (never-paid; no grace) |
| `trialing` / `renewal_pending` | No convert / no plan by trial end | `trial_expired` |
| `trialing` | Trial cancel / trial withdraw / trial unsubscribe/complaint | `trial_expired` or `withdrawn` per event |
| `active` | Renewal failure | `past_due` |
| `past_due` | Retry success | `active` (same anchor) |
| `past_due` | Final retry fail | `suspended` |
| `suspended` | Recovery payment success | `active` |
| `active` | Cancel request | `cancellation_scheduled` |
| `cancellation_scheduled` | Revoke cancel | `active` |
| `cancellation_scheduled` | Period end | `canceled` |
| `active` / `cancellation_scheduled` | Withdraw request (paid) | `withdrawal_scheduled` |
| `withdrawal_scheduled` | Revoke | prior active-like state |
| `withdrawal_scheduled` | Effective | `withdrawn` |
| `canceled` | New paid subscribe success | new contract → `active` |

Fail-closed: unknown payment provider state → reconcile before activating entitlement or resending charges.

When paid plan becomes known:

- **Not** at trial signup
- **At** explicit D-3 conversion confirmation → pending snapshot on `conversion_scheduled`
- **Active contract** only after verified payment success → `active`

---

## 15. Entitlement summary

Trial (`trialing` / `renewal_pending` / `conversion_scheduled` until trial end): **Full Set**.
Paid (`active` and eligible paid states): selected plan’s product set (from conversion snapshot or later plan change).

Eligibility inputs (non-exhaustive; Delivery contract is authoritative for snapshot rules):

- account active/eligible
- verified delivery email
- publication day
- `delivery_start_date`
- subscription state
- trial or paid entitlement
- payment/grace status
- cancellation/withdrawal effective date
- duplicate-delivery prevention

---

## 16. External dependencies

| Dependency | Type |
|------------|------|
| PG / billing-key provider | VENDOR CAPABILITY VALIDATION |
| Own-name card match capability | VENDOR CAPABILITY VALIDATION |
| ROK public holiday calendar feed | IMPLEMENTATION REQUIREMENT |
| Final Terms / Privacy / refund legal text | LEGAL IMPLEMENTATION VALIDATION |

---

## 17. Related documents

- `GENIE_KEYSURI_CUSTOMER_WEB_SSOT_v1.md`
- `CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md`
- `CUSTOMER_DELIVERY_ENTITLEMENT_CONTRACT_v1.md`
- `FRONTEND_UX_SPEC_v1.md`
- `FRONTEND_API_CONTRACT_v1.md`
