# GENIE × KeeSuri — Customer Web Stabilization Status

**As of:** 2026-08-11 (KST)
**Classification:** REPORT / EVIDENCE (not policy authority)
**Policy authority:** `docs/web/*` SSOT + domain specs + Brand SSOT
**Map:** `docs/web/DOCUMENT_MAP_AND_AUTHORITY.md`

This record distinguishes evidence layers. Prototype QA ≠ production readiness.

> **PRICING SUPERSEDED (2026-08-11, later same day).** Every Full Set price in
> this report (₩14,300) is **HISTORICAL EVIDENCE OF A PAST STATE**, retained
> unmodified as a dated record. It **MUST NOT** be read as current pricing.
> Current Full Set price is **₩16,500** by owner decision; the authorities are
> `CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md` §1 and `BUSINESS_BRAND_SSOT_v1.md` §7.

---

## 1. Summary matrix

| Area | POLICY LOCKED | IMPLEMENTED (prototype) | BROWSER QA | ACTUAL DEVICE |
|------|---------------|-------------------------|------------|---------------|
| Pricing rebalance Full Set ₩14,300 (**SUPERSEDED** → ₩16,500) | YES (at the time) | YES | N/A | N/A |
| D-3 neutral / no default / no recommendation badge | YES | YES | PASS (as implemented) | N/A |
| FAQ disclosure contract | YES | YES | Chromium PASS (3/3) | Post-repair iPhone confirmation **PENDING** |
| Raw `###` leakage | YES (prohibition) | CLOSED (visible count 0) | PASS | N/A |
| Prototype diagnostic ribbon isolation | YES | Hidden by default; debug mode retained | PASS | N/A |
| Mobile landscape Hero (no clip) | YES | YES | PASS | N/A |
| Mobile landscape Preview composition | YES | YES | PASS | iPhone landscape **ACCEPTED** |
| Mobile portrait Preview full composition | YES | YES | PASS | iPhone portrait **PENDING** |
| Horizontal overflow (tested required viewports) | — | — | browser QA 0 | N/A |
| Desktop | No redesign authorized | — | regression QA PASS | N/A |

---

## 2. Pricing (AS RECORDED ON 2026-08-11 — SUPERSEDED, NOT CURRENT)

The Full Set figure below is superseded; see the banner at the top of this
document. Current Full Set price is ₩16,500.

| Plan | VAT-included monthly |
|------|----------------------|
| Today | ₩6,600 |
| Global | ₩9,900 |
| Korea | ₩6,600 |
| 2종 | ₩11,000 |
| 3종 Full Set | ₩14,300 |

Full Set (as recorded that day): supply ₩13,000 + VAT ₩1,300 = ₩14,300;
2종→3종 +₩3,300. **This arithmetic is historical.**
Current Full Set: supply ₩15,000 + VAT ₩1,500 = ₩16,500; 2종→3종 +₩5,500.

---

## 3. Claude Design Round 1

| Item | Value |
|------|-------|
| Mode | CRITIQUE ONLY |
| Diagnosis | `PRODUCT_COMMUNICATION_RETHINK_REQUIRED` |
| Strategic diagnosis accepted | YES |
| Automatic redesign authority | **NO** |

Findings require individual triage (accepted / partial / rejected / deferred).

---

## 4. Evidence language rules

Allowed: “Chromium QA PASS”; “Actual iPhone landscape visually confirmed”; “Actual iPhone portrait confirmation pending”.
**MUST NOT:** “all iPhone/Safari QA passed” without per-surface evidence.

---

## 5. Related canonical docs

- Pricing / D-3 neutrality: `CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md`, Brand §7
- Preview / FAQ / Markdown / debug / mobile: `FRONTEND_UX_SPEC_v1.md` §23–§27
- Customer web summary: `GENIE_KEYSURI_CUSTOMER_WEB_SSOT_v1.md`
