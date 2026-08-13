# GENIE × KeeSuri — Customer Web SSOT v1

**Status:** APPROVED
**Version:** v1
**As of:** 2026-08-10 (KST)
**Authority:** Customer-web / product constitution
**Map:** `docs/web/DOCUMENT_MAP_AND_AUTHORITY.md`

---

## 1. Purpose

This document is the primary constitution for the **GENIE × KeeSuri customer-facing web product**.

The web product is the frontend/product surface of the existing private briefing service. It does **not** replace operational generation, owner-review, or approve/send authority.

Detailed billing, auth, delivery, UX, and API rules live in peer domain specs. This SSOT defines scope, invariants, information architecture, and cross-cutting boundaries.

---

## 2. Product purpose

**상위 서비스명:** 프라이빗 브리핑 (GENIE × KeeSuri)

평일마다 시장·기술 신호를 AI가 구조화하고, 운영자 검수를 통과한 브리핑만 고객 이메일로 전달하는 **검수형 AI 브리핑 서비스**의 고객 제품 표면.

**Customer value surface (MUST):**

- Discover the three briefings and packages
- Complete adult identity verification and passwordless account creation
- Start a 14-calendar-day Full Set free trial with own-name card registration (**without** choosing a paid plan at signup)
- Explicitly convert to paid at D-3 by selecting a paid plan (no automatic paid conversion)
- Manage a small My Page: trial status (no future paid plan until conversion), then plan/payment/delivery email, cancel, withdraw
- Recover from delivery failures (bounce) without becoming an operator console

**MUST NOT** present the service as:

- investment advice / buy-sell recommendations / guaranteed returns
- real-time news feed
- fully automatic / unattended publishing
- 365-day or weekend publication

(See `docs/BUSINESS_BRAND_SSOT_v1.md` forbidden expressions.)

---

## 3. Products (catalog summary)

Authoritative prices and plan rules: `CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md`.

| Product code | Customer name | Monthly price (VAT included) |
|--------------|---------------|------------------------------|
| `today_genie` | Today Genie Briefing / 오늘의 지니 브리핑 | KRW 6,600 |
| `keysuri_global` | KeeSuri Global / 키수리 글로벌 | KRW 9,900 |
| `keysuri_korea` | KeeSuri Korea / 키수리 코리아 | KRW 6,600 |
| `package_two` | Two-product Package / 2종 선택 패키지 | KRW 11,000 (exactly two of three) |
| `full_set` | Full Set / 3종 풀세트 | KRW 16,500 (all three; KRW 5,500 above `package_two`) |

**Superseded legacy customer-subscription claims (MUST NOT reuse as current policy):**

- KRW 14,300 Full Set (**HISTORICAL** — superseded by owner decision 2026-08-11 → KRW 16,500)
- KRW 29,900 single monthly price
- 5-day free trial
- “1+1 package” wording
- Forced / preselected paid plan or unsupported “강력 추천” / MOST POPULAR / BEST VALUE badges

Pricing hierarchy ethics: prices create hierarchy; UX **MUST NOT** fabricate popularity/recommendation evidence. D-3 opens with **zero** selected plans.

## 4. Information architecture (FIXED)

Exactly **three** customer-facing top-level areas:

1. **Landing & Introduction**
2. **Signup & Payment**
3. **My Page**

**Admin / Owner Review is NOT a customer-web top-level area.**
It is a **separate private operator surface** (§4.3).

**MUST NOT** invent a fourth customer-facing top-level product category. FAQ, pricing, sample briefing, support, and settings are sections inside these three.

### 4.1 Customer discoverability — zero Admin paths

The customer-facing website **MUST** expose **ZERO** normal navigation paths to Admin / Owner Review.

This includes header, footer, Landing, Login, Signup, My Page, account/security, pricing, FAQ, support, and customer error screens.

**MUST NOT** contain customer-visible:

- Admin / 관리자 / 운영 콘솔 / owner-review / operator dashboard links
- “back to Admin”
- customer-accessible Admin route discovery

`robots.txt` or URL obscurity alone is **NOT** an authorization mechanism.

### 4.2 My Page scope (MUST stay small)

Include:

- subscription / trial status
- subscription start date
- next billing date (or trial end / first billing if conversion scheduled)
- current plan (**only when paid/active or conversion_scheduled pending selection**)
- briefing delivery email
- support contact
- payment method management
- plan change
- cancellation
- membership withdrawal
- session/security management only as needed

**MUST NOT** include:

- briefing history browser
- content editor / regeneration
- analytics dashboard
- large notification control center
- customer-side operational admin
- complex publication controls
- any link or affordance into Admin / Owner Review

### 4.3 Private Operator / Owner-Review Surface (OUTSIDE customer IA)

Admin / Owner Review is a **SEPARATE PRIVATE OPERATOR SURFACE**.

It belongs to the operator / owner-review / operations boundary — **not** the customer product navigation hierarchy.

**Normal entry (canonical):**

```
owner-review generation
→ review notification email to owner
→ signed review deep link
→ server-side token validation
→ exact review/run operator context
```

Conceptual form: `https://<service-host>/<private-owner-review-path>/<signed-token>`

Do not hard-lock a production path name in this constitution unless architecture already defines one; the **security/authority model** is normative.

Signed review link **MUST** be conceptually:

- high entropy / unguessable
- server validated
- time limited
- revocable / invalidatable
- bound to a specific review/run context
- **not** permanent unrestricted Admin bearer authority
- **not** a grant of customer privileges (or vice versa)

**Preferred UX:** open the **exact** briefing/run review detail referenced by the email — **MUST NOT** force email → generic Admin homepage → manual run search.

**Customer navigation entry:** NONE
**My Page entry:** NONE
**Public Landing entry:** NONE

Opening a review link ≠ approval ≠ customer send ≠ customer receipt.

Operator surface may show operational safety/status (runs, owner-review, delivery, queues, controlled confirmations, support visibility) but **MUST NOT** become a large CRM / BI / infrastructure control panel, and **MUST NOT** let a signed link alone authorize Scheduler mutation, Secret access, arbitrary SMTP, raw production endpoints, or GCS destructive ops without existing stronger auth/confirmation gates.

Preserve stronger production Admin authentication if already required. Do not weaken it.

---

## 5. High-level fixed principles

| Topic | Fixed rule | Detail authority |
|-------|------------|------------------|
| Adult-only | Age ≥ 19 only; no guardian exception; IDV-enforced | Auth spec |
| Passwordless | No customer password | Auth spec |
| Trial | 14 calendar days; Full Set first; **no** paid-plan selection at signup; card required; paid plan chosen only on explicit D-3 conversion; no auto paid conversion | Lifecycle |
| Publication | KST weekdays only; no weekends; no ROK public holidays; times **06:30 / 12:30 / 18:30** (Today / Global / Korea) | Delivery + Lifecycle + Landing UX |
| Landing copy | Customer-experience first; portfolio MUST NOT imply all products are morning; domestic + global scope; dark editorial Hero | UX §2 |
| Pricing ethics | No recommendation badges / no preselection; Full Set CURRENT ₩16,500 (SUPERSEDES historical ₩14,300); step-up “2종에서 월 5,500원 추가” | Lifecycle + UX |
| Preview / FAQ / debug | Composition preservation; FAQ disclosure a11y; no raw Markdown leakage; diagnostic UI isolated; no automatic redesign | UX §23–§27 |
| Delivery email | Exactly one active `delivery_email` per account | Delivery |
| Entitlement | subscription state → entitlement → recipient snapshot → delivery | Delivery |
| Payment data | Never store PAN/CVV/card password; provider token only | Lifecycle |
| Ops boundary | Customer web has zero Admin navigation; customer session ≠ operator auth; no approve/send/Scheduler/SMTP/Secrets/GCS mutation | This SSOT §4.3 / §7 |

---

## 6. Email-first briefing product model

Customer product delivery channel for briefings is **email**.

**Landing rule (compact):** Lead with customer experience/value. Portfolio copy MUST NOT imply all products are morning publications. The three products occupy different daily delivery moments (**06:30 / 12:30 / 18:30 KST**). Customer-facing portfolio copy MUST distinguish domestic and global scope. Detailed Hero/Products/Pricing layout: `FRONTEND_UX_SPEC_v1.md` §2.

Pipeline invariant (MUST preserve):

```
generation
→ validation
→ owner-review
→ approval
→ customer delivery
→ receipt evidence
≠ publishing
```

**FIXED POLICY distinctions:**

| Concept | Meaning |
|---------|---------|
| generated | Model/output artifact exists |
| validated | Passed validation gates |
| owner-review | Operator review path |
| approved | Explicit approve for customer final send |
| customer delivery attempted | Send pipeline ran |
| provider accepted (`smtp_accepted` or equivalent) | Provider accepted message — **not** customer receipt |
| customer received | Independent receipt evidence when required for ops PASS |
| published | External publish channel (e.g. Naver) — **not** default customer product |

HTTP 200 from an endpoint **MUST NOT** be treated as business success for generation or delivery.

---

## 7. Operational safety boundaries

The customer web **MUST NOT** directly:

- control Cloud Scheduler
- access production Secrets
- operate SMTP
- perform owner-review approval
- authorize customer-send
- mutate operational GCS artifacts
- invoke raw internal job endpoints as a customer capability

Existing private operator / Admin surface (today often `/admin/*` in FastAPI) is an **operating console outside the customer IA**.
Customer frontend is a **separate product surface** with **zero** Admin discoverability (§4.1).

A customer or operator UI button **MUST NEVER** become implicit production authority for approve, send, schedule, or secret access.

Review-link handoff invariants:

```
opening review link ≠ approval
approval ≠ customer send
customer send ≠ customer receipt
```

---

## 8. Relationship to existing backend

**FACT (as of documentation batch):**

- Production customer auth, subscription DB, and PG integration are not yet the live product surface.
- Current customer delivery uses env + admin-managed beta recipient lists and approve-gated SMTP.
- `web_prototype/` is a static mock.

**IMPLEMENTATION REQUIREMENT:**

Future implementation MUST replace “manual fixed recipient list as the product model” with:

```
subscription / payment state
→ entitlement evaluation
→ recipient snapshot
→ customer delivery
```

Backend generation/owner-review/approve modules remain authoritative for briefing safety. Customer-web APIs consume entitlements; they do not bypass approve.

---

## 9. Prototype vs production boundary

| Surface | Status |
|---------|--------|
| `docs/web/*` | Canonical **customer**-product policy |
| Customer prototype pages (`index` / `login` / `signup` / `mypage`) | REFERENCE; **MUST** have zero links to Admin |
| Operator mock (`admin.html` or equivalent) | Separate private operator mock only; not customer IA; production routing **MUST NOT** be assumed as `/admin.html` |
| Production Admin / owner-review HTML | Operating console (ops/architecture authority) |
| Future customer web app | Must implement `docs/web/` |

Prototype may show passwords, obsolete copy, or incomplete states. Those are **not** policy. Reconciliation is a later task: `RECONCILE_WEB_PROTOTYPE_AGAINST_NEW_SSOT`.

---

## 10. Terminology

| Prefer | Avoid |
|--------|-------|
| 브리핑 | 뉴스레터 (as primary product name) |
| 검수 / 운영자 검수 | 완전 자동 발행 |
| KeeSuri / 키수리 | Key-Suri drift in customer UI without glossary |
| Full Set / 3종 풀세트 | 1+1 패키지 |
| VAT 포함 월 구독가 | Unlabeled “₩29,900” single plan |

Kee-Suri section-label locks for briefing **content** remain in `docs/keysuri/KEYSURI_TERMINOLOGY_LOCK.md`.

---

## 11. Scope and non-goals

### In scope (customer web product)

- Landing, signup, trial, paid conversion, My Page, recovery UX
- Customer identity/auth/session
- Subscription lifecycle & billing policy encoding
- Entitlement-driven delivery contract
- Explicit **separation** of private operator / owner-review surface from customer IA

### Non-goals (this constitution)

- Implementing PG / IDV / SMS / ESP vendor selection
- Changing owner-review or generation pipelines
- Naver auto-publish as a customer feature
- Building a customer briefing editor
- Treating Admin as a customer-web navigation category
- Full operator-auth architecture redesign (preserve stronger existing Admin auth)

---

## 12. Authority references

| Concern | Document |
|---------|----------|
| Document navigation | `DOCUMENT_MAP_AND_AUTHORITY.md` |
| Plans, trial, billing, cancel, refund, withdrawal | `CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md` |
| Adult IDV, passwordless, sessions | `CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md` |
| Entitlement, bounce, SMS, streams | `CUSTOMER_DELIVERY_ENTITLEMENT_CONTRACT_v1.md` |
| Screens | `FRONTEND_UX_SPEC_v1.md` |
| Customer API design | `FRONTEND_API_CONTRACT_v1.md` |
| Brand / forbidden copy | `docs/BUSINESS_BRAND_SSOT_v1.md` |
| Ops safety | `docs/architecture/`, `OPERATIONS.md`, `ROLLOUT.md` |

---

## 13. External validation dependencies

**EXTERNAL VALIDATION REQUIRED (implementation, not open product policy):**

- Identity-verification vendor and DI field mapping
- PG / billing-key vendor and own-name card verification capability
- SMS provider delivery receipts
- Email ESP / bounce/complaint webhook fidelity
- Final legal Terms / Privacy / consumer-right wording and statutory retention periods

These **MUST NOT** block documenting the fixed product policy above.
