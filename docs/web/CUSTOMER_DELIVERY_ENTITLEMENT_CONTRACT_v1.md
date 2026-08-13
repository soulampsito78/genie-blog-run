# GENIE × KeeSuri — Customer Delivery & Entitlement Contract v1

**Status:** APPROVED
**Version:** v1
**As of:** 2026-08-10 (KST)
**Authority:** Entitlement, recipient snapshot, customer delivery, bounce/SMS, streams
**Parent:** `docs/web/GENIE_KEYSURI_CUSTOMER_WEB_SSOT_v1.md`
**Map:** `docs/web/DOCUMENT_MAP_AND_AUTHORITY.md`

Inherits operational safety from `docs/architecture/` and ops docs:

```
generation ≠ validation ≠ owner-review ≠ customer delivery ≠ actual receipt ≠ publishing
provider accepted ≠ customer received
```

---

## 1. Required conceptual flow

**MUST NOT** maintain customer email delivery as a manual fixed recipient list as the product model.

Required flow:

```
subscription / payment state
→ entitlement evaluation
→ recipient snapshot
→ customer delivery
```

Owner-review approval remains a prerequisite for customer final send of a given run/publication. Entitlement answers **who** may receive; approve answers **whether this briefing may be sent**.

---

## 2. Product codes

| Code | Briefing |
|------|----------|
| `today_genie` | Today Genie |
| `keysuri_global` | KeeSuri Global |
| `keysuri_korea` | KeeSuri Korea |

Trial entitlement: **Full Set** (all three).
Paid entitlement: selected plan (Lifecycle).

---

## 3. Publication calendar

Same as Lifecycle:

- KST
- Weekdays only
- No weekends
- No Republic of Korea public holidays

One calendar for all customer products.

---

## 4. Delivery start date

Aligned with Lifecycle trial/paid start:

- **MUST NOT** deliver on application/subscription calendar day
- Eligibility from **next calendar day**
- If non-publication day → next publication day

Persist `delivery_start_date` on the subscription/trial.

---

## 5. Email model

Each customer account has exactly **ONE** active briefing delivery email.

```
1 account = 1 active delivery_email
```

**MUST NOT** permit:

- separate delivery email by product
- multiple simultaneous briefing delivery addresses
- package sharing across addresses

Distinguish:

- `account_email`
- `delivery_email`

Initial default: `delivery_email = account_email`

### 5.1 Delivery-email change

- Old address remains active until new address is verified
- New address becomes active only after verification
- Apply from the **next** recipient snapshot after successful change
- **MUST NEVER** duplicate the same publication to both addresses

---

## 6. Entitlement evaluation

Eligibility **MUST** consider at minimum:

- account active / eligible
- verified delivery email present
- publication day (calendar)
- `delivery_start_date`
- subscription state (`trialing`, `active`, `past_due` within grace, `cancellation_scheduled` still in period, etc.)
- trial or paid product entitlement set
- payment/grace status
- cancellation / withdrawal effective date
- complaint / unsubscribe / hard-bounce suppression
- duplicate-delivery prevention

`past_due` within grace: retain paid entitlement per Lifecycle.
`suspended`, `trial_expired`, `canceled` (effective), `withdrawn`: delivery OFF for briefings.

Billing interaction (Lifecycle §8.1): **MUST NOT** renew/charge if no verified delivery email at billing decision point.

---

## 7. Recipient snapshot

Before customer delivery, **freeze** a recipient snapshot.

Snapshot **MUST** preserve enough evidence to explain:

- which user was eligible
- which email address was selected
- which subscription
- which plan
- entitlement reason
- billing state at snapshot
- delivery result

Changes after snapshot creation **MUST NOT** mutate that snapshot. They apply to the **next** snapshot.

---

## 8. Customer delivery idempotency

Unique delivery key (conceptual):

```
account_id + product_code + publication_date
```

Rules:

- Provider-accepted delivery **MUST NOT** be automatically resent solely because a downstream delivery event is delayed
- `unknown_after_submit` **MUST** reconcile provider state before resend
- **No duplicate send** for the same delivery key once accepted (unless a controlled, audited, explicitly authorized reissue path exists — customer web MUST NOT self-authorize reissue)

---

## 9. Soft Bounce

A **confirmed Soft Bounce MUST** generate an SMS to the customer’s verified mobile number **immediately** for that bounce incident.

**MUST NOT** send a new Soft Bounce SMS for every provider retry of the **same** incident.

Flow:

1. Record bounce
2. Send Soft Bounce SMS
3. Allow safe provider retry / reconciliation
4. If condition persists into action-required state → additional action-required SMS
5. If escalates to Hard Bounce → separate Hard Bounce SMS

SMS wording **MUST** explain the customer-visible problem; **MUST NOT** expose raw SMTP/provider jargon.

---

## 10. Hard Bounce

A confirmed Hard Bounce:

- **MUST** immediately suppress briefing delivery to that address
- **MUST** immediately generate an SMS notification
- **MUST** expose customer-web action to replace and verify delivery email
- **MUST NOT** auto-send missed publications in bulk after recovery

Recovery:

```
new email entered
→ ownership verified
→ becomes active delivery_email
→ delivery resumes from next eligible recipient snapshot
```

---

## 11. SMS delivery observability

SMS API submission alone is **not** sufficient truth.

Track at minimum:

- `submitted`
- `delivered`
- `failed`
- `retrying`
- `terminal_failed`

If briefing email delivery fails **AND** the required SMS notification also **terminally fails**:

- Raise high-priority operational state: `CUSTOMER_CONTACT_FAILURE`
- **MUST NOT** silently ignore dual-channel contact failure

---

## 12. Complaint / spam report

Spam complaint:

- Immediately stop briefing delivery
- Suppress briefing stream
- **MUST NOT** automatically recover
- Require explicit customer re-consent + verification before recovery

| Context | Additional |
|---------|------------|
| Trial | Terminate trial; destroy payment token |
| Paid | Stop briefing delivery; schedule cancellation / prevent next renewal |

**MUST NOT** continue repeatedly sending to a complained address.

---

## 13. Unsubscribe

Briefing email supports **one-click unsubscribe**.

Unsubscribe immediately stops briefing delivery.

| Context | Effect |
|---------|--------|
| Trial | Trial ends; payment token destroyed |
| Paid | Stop briefing delivery; schedule cancellation; no next renewal |

Before paid cancellation becomes effective, customer MAY explicitly re-enable briefing delivery and cancel the scheduled cancellation **after reauthentication** (Auth step-up).

---

## 14. Briefing vs transactional email

| Stream | Examples |
|--------|----------|
| **BRIEFING** | Today Genie, KeeSuri Global, KeeSuri Korea |
| **TRANSACTIONAL / SECURITY** | Login verification, security alerts, payment receipt, payment-method change, cancellation confirmation, account notices |

Briefing unsubscribe / suppression **MUST NOT** disable required authentication / security / transactional email.

---

## 15. Sender incident

**MUST NOT** misclassify a platform-wide sending incident as hundreds of individual customer email failures.

Examples: SPF/DKIM/DMARC failure, sender-domain issue, ESP outage, widespread rate limit, sender reputation event.

If a common failure pattern appears across many recipients, classify/consider: `SENDER_INCIDENT`.

During sender incident:

- **MUST NOT** automatically suppress every customer email as hard bounce
- **MUST NOT** modify customer subscriptions
- **MUST NOT** alter customer billing state
- Fail closed for unsafe customer send
- Alert operations/admin

A long-running confirmed service-wide outage MAY use a separate service-status SMS policy. **MUST NOT** confuse that with individual bounce SMS.

---

## 16. Operator / customer safety

Customer web **MUST NOT** cross:

- Scheduler control
- production Secret access
- direct SMTP operation
- owner-review approval
- customer-send authority
- GCS operational mutation
- Admin / owner-review navigation or API authorization via customer session

A frontend button **MUST NEVER** become implicit production authority.

---

## 17. Delivery result vocabulary

| Term | Meaning |
|------|---------|
| `not_eligible` | Entitlement/calendar/suppression blocked |
| `snapshot_frozen` | Recipient snapshot created |
| `send_attempted` | Delivery pipeline attempted |
| `provider_accepted` | ESP/SMTP accepted (e.g. `smtp_accepted`) |
| `provider_rejected` | Hard failure at accept |
| `soft_bounce` | Confirmed soft bounce |
| `hard_bounce` | Confirmed hard bounce |
| `complaint` | Spam complaint |
| `delivered_evidence` | Independent receipt evidence when available |
| `unknown_after_submit` | Needs reconciliation |

Ops PASS criteria that require Gmail/receipt proof remain governed by operational docs — this contract does not weaken them.

---

## 18. Related documents

- `CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md`
- `CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md`
- `FRONTEND_UX_SPEC_v1.md`
- `FRONTEND_API_CONTRACT_v1.md`
- `docs/architecture/04_owner_review_safety_boundary.*`
