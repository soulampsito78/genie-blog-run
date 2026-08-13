# GENIE × KeeSuri — Document Map and Authority

**Status:** APPROVED
**Version:** v1
**As of:** 2026-08-10 (KST)
**Domain:** Customer web / product documentation meta-authority

---

## 1. Purpose

This document defines how repository documentation is navigated and which document wins when statements conflict.

It does **not** define product prices, trial rules, auth flows, or delivery mechanics. Those live in the domain documents listed below.

---

## 2. Authority hierarchy

When statements conflict, resolve in this order:

### 2.1 Operational / runtime truth

1. **Live production operational state** (Cloud Scheduler, Cloud Run, GCS artifacts, secrets as deployed)
2. **`docs/CURRENT_STATUS_SNAPSHOT.md`** — latest confirmed operational snapshot
3. **`SCHEDULE_OVERRIDE.md`**, **`OPERATIONS.md`**, **`ROLLOUT.md`**, **`docs/ops/*`** — schedule, hardening, deploy verification, incident runbooks
4. **`docs/architecture/*`** — system and **owner-review / customer-delivery safety boundaries**

Customer-web documents **MUST NOT** supersede operational safety truth. They **MUST** inherit it.

### 2.2 Business / brand truth

5. **`docs/BUSINESS_BRAND_SSOT_v1.md`** — service definition, brand principles, forbidden marketing copy, customer segments

Brand SSOT **does not** own customer subscription pricing, trial duration, billing, or auth. Those are delegated to `docs/web/`.

### 2.3 Customer web / product truth

6. **`docs/web/GENIE_KEYSURI_CUSTOMER_WEB_SSOT_v1.md`** — customer-web constitution
7. Domain specifications (equal peer authority within their scope; Web SSOT wins on scope conflicts):
   - `docs/web/CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md`
   - `docs/web/CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md`
   - `docs/web/CUSTOMER_DELIVERY_ENTITLEMENT_CONTRACT_v1.md`
8. Implementation specifications:
   - `docs/web/FRONTEND_UX_SPEC_v1.md`
   - `docs/web/FRONTEND_API_CONTRACT_v1.md`
   - `docs/web/CUSTOMER_BACKEND_INFRASTRUCTURE_DECISION_v1.md`

### 2.4 Supporting / reference (not policy authority)

9. **`README.md`** — general navigation and ops entry
10. **`docs/keysuri/*` terminology/image/content contracts** — Kee-Suri content/copy locks (not customer billing)
11. **`docs/genie/*`**, **`docs/REVIEW_OPERATION_BOX_POLICY.md`** — owner-review / email operation-box wording
12. **`web_prototype/`** — **REFERENCE / NON-CANONICAL** static UX prototype
13. Closeouts, audits, incident reports, validation artifacts — **evidence only**
14. **`docs/web/CUSTOMER_WEB_STABILIZATION_STATUS_2026_08_11.md`** — customer-web prototype stabilization evidence (REPORT; not policy)

---

## 3. What `docs/web/` owns

| Owns | Does NOT own |
|------|----------------|
| Customer-facing web product scope and IA (**three** areas only) | Live GCP deploy/revision truth |
| Subscription, trial, billing, payment-method policy | Owner-review approval authority |
| Customer identity, passwordless auth, sessions | Operator/Admin authentication architecture |
| Customer entitlement → recipient snapshot → delivery contract | Scheduler enable/pause |
| Customer Frontend UX and **customer** API design contracts | Direct SMTP / Secret / GCS ops mutation |
| Explicit **separation** statement for private operator surface | Kee-Suri generation/image prompt locks |
| Mock vs production product boundary for the **customer** surface | Historical incident narrative |

`docs/web/` may describe the private operator / owner-review surface **only** to define its separation from the customer product.
Runtime Admin / owner-review authority remains in ops / architecture / review-operation documents (`docs/architecture/*`, `OPERATIONS.md`, `docs/REVIEW_OPERATION_BOX_POLICY.md`, `docs/genie/*`). **Do not create split authority.**

---

## 4. Conflict resolution rules

| Conflict type | Winner |
|---------------|--------|
| Ops success semantics (HTTP 200, SMTP accepted, Gmail receipt) | Operational docs + architecture safety |
| Brand forbidden phrases / service naming | `BUSINESS_BRAND_SSOT_v1.md` |
| Prices, trial, billing, cancel, refund, withdrawal | `CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md` |
| Customer DB provider, Supabase scope, migration authority | `CUSTOMER_BACKEND_INFRASTRUCTURE_DECISION_v1.md` |
| Adult gate, DI, passwordless, sessions | `CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md` |
| Entitlement, bounce, SMS, unsubscribe | `CUSTOMER_DELIVERY_ENTITLEMENT_CONTRACT_v1.md` |
| Screen behavior (customer) | `FRONTEND_UX_SPEC_v1.md` (must not contradict domain specs) |
| Customer API shape | `FRONTEND_API_CONTRACT_v1.md` domain A |
| Operator / owner-review API & approve gates | Ops / architecture / existing Admin contracts (domain B) |
| Prototype HTML/CSS/JS vs `docs/web/` | **`docs/web/` wins** |
| Closeout/report vs current policy | Current `docs/web/` / Brand / ops SSOT wins; report remains historical evidence |

---

## 5. Authority matrix

| Document / domain | Authority | Scope | May supersede | May NOT supersede |
|-------------------|-----------|-------|---------------|-------------------|
| Live GCP state | CURRENT (ops) | Deployed runtime | Stale ops snapshot rows | Brand / customer product policy |
| `docs/CURRENT_STATUS_SNAPSHOT.md` | CURRENT (ops snapshot) | Confirmed ops audit | Older snapshot layers | Customer billing/auth policy |
| `OPERATIONS.md` / `ROLLOUT.md` / `docs/ops/*` | SUPPORTING (ops) | Hardening, deploy, incidents | Informal ops notes | Customer product SSOT |
| `docs/architecture/*` | CURRENT (safety) | Pipeline & approve boundaries | Vague “auto-send” claims | Customer pricing |
| `docs/BUSINESS_BRAND_SSOT_v1.md` | CURRENT (brand) | Brand, principles, forbidden copy | Marketing drafts | Lifecycle/billing detail |
| `docs/web/GENIE_KEYSURI_CUSTOMER_WEB_SSOT_v1.md` | CURRENT (customer web) | Product constitution | Prototype claims; stale brand § pricing | Ops safety invariants |
| `docs/web/CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md` | CURRENT (lifecycle) | Plans, trial, bill, cancel, refund | Stale 5-day / ₩29,900 claims | Owner-review gates |
| `docs/web/CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md` | CURRENT (auth) | IDV, login, sessions | Prototype password fields | Admin password ops auth |
| `docs/web/CUSTOMER_DELIVERY_ENTITLEMENT_CONTRACT_v1.md` | CURRENT (delivery product) | Entitlement, bounce, SMS | Manual fixed-list-as-product model | Generation / approve internals |
| `docs/web/FRONTEND_UX_SPEC_v1.md` | SUPPORTING (customer UX) | Customer screens; separation note for operator surface | Prototype customer UX where conflicting | Domain policy; operator runtime authority |
| `docs/web/FRONTEND_API_CONTRACT_v1.md` | SUPPORTING (API design) | Customer API domain A + separation of domain B | Ad-hoc frontend coupling ideas | Scheduler / SMTP / Secrets; treating Admin as customer API |
| `docs/web/CUSTOMER_BACKEND_INFRASTRUCTURE_DECISION_v1.md` | CURRENT (infrastructure) | Customer DB provider, Supabase feature scope, Alembic authority, connection strategy | Ad-hoc provider/migration choices | Customer product policy; ops safety |
| `docs/web/CUSTOMER_WEB_STABILIZATION_STATUS_2026_08_11.md` | REPORT / EVIDENCE | 2026-08-11 stabilization; **its ₩14,300 Full Set price is SUPERSEDED** | Nothing as standing policy | Current `docs/web/` policy docs |
| `web_prototype/` | REFERENCE / NON-CANONICAL | Static UX simulation | Nothing authoritative | Any `docs/web/` policy |
| Closeouts / audits / `*_CLOSEOUT_*` | REPORT / EVIDENCE | Dated incident state | Nothing as standing policy | Current SSOT documents |

---

## 6. Status of `web_prototype/`

**Classification:** REFERENCE / NON-CANONICAL

- Static standalone HTML/CSS/JS simulation
- **NOT** production
- **NOT** auth, payment, or subscription implementation
- **NOT** policy authority
- Subject to later reconciliation against `docs/web/`
- If prototype and Web SSOT conflict: **Web SSOT wins**

Do not modify prototype files under the authority of this documentation batch; reconciliation is a separate task.

---

## 7. Status of historical reports and closeouts

Implementation reports, sandbox closeouts, incident forensics, and validation HTML/JSON artifacts are **evidence of a past state**.

They:

- MAY inform engineering judgment
- MUST NOT be reused as standing customer-product policy
- MAY retain obsolete numbers (e.g. historical “₩29,900”, “₩14,300”) when clearly dated as historical

---

## 8. Entry points for agents

| Task | Start here |
|------|------------|
| Customer web product scope | `GENIE_KEYSURI_CUSTOMER_WEB_SSOT_v1.md` |
| Prices / trial / billing / cancel | `CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md` |
| Login / IDV / sessions | `CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md` |
| Who gets which email | `CUSTOMER_DELIVERY_ENTITLEMENT_CONTRACT_v1.md` |
| Screen behavior | `FRONTEND_UX_SPEC_v1.md` |
| Future customer API | `FRONTEND_API_CONTRACT_v1.md` |
| Customer-web stabilization evidence (2026-08-11) | `CUSTOMER_WEB_STABILIZATION_STATUS_2026_08_11.md` |
| Customer DB provider / Supabase scope / Alembic authority | `CUSTOMER_BACKEND_INFRASTRUCTURE_DECISION_v1.md` |
| Ops safety / approve boundary | `docs/architecture/` + `OPERATIONS.md` / `ROLLOUT.md` |
| Brand / forbidden marketing | `docs/BUSINESS_BRAND_SSOT_v1.md` |

---

## 9. Document management

| Item | Value |
|------|-------|
| This document’s authority | Meta-map for documentation navigation |
| Next change rule | Update this map whenever a new `docs/web/` authority document is added or retired |
| Related Brand pointer | `docs/BUSINESS_BRAND_SSOT_v1.md` §7 delegates lifecycle pricing to `docs/web/` |
