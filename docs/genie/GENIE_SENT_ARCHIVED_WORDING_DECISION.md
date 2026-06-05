# Genie `sent_archived` / Send-Completion Wording — Deferral Decision

## 1. Purpose

This note records why Genie **outbound customer email** uses `review_passed` only and does **not** use `sent_archived` or **발송되었습니다** wording yet.

The goal is to prevent send-complete language from appearing in customer-facing outbound HTML before a real send/archive completion surface exists and before durable post-send records are available at render time.

**Related policy:** `docs/REVIEW_OPERATION_BOX_POLICY.md`  
**Related plan:** `docs/genie/GENIE_EMAIL_OPERATION_BOX_SEMANTICS_FIX_PLAN.md`

---

## 2. Current implemented state

As of commit `64985ff` (Genie customer review confirmation on approved send):

| Surface | Behavior |
|---------|----------|
| Owner/admin email | Contains `#genie-operational-handoff` (운영자 검수 상태 box) |
| Customer final HTML prep | Strips `#genie-operational-handoff` via `strip_owner_operational_handoff()` |
| Approved customer send path | `send_today_geenee_customer_final_email()` calls `prepare_customer_final_html(..., review_confirmation_state="review_passed")` |
| Customer review box DOM | `id="review-confirmation-box"` with `data-review-state="review_passed"` |
| Customer review box text | `본 브리핑은 운영책임자의 직접 검수를 통과했습니다.` |
| Genie outbound allowed states | `review_passed` only (`_GENIE_CUSTOMER_OUTBOUND_REVIEW_STATES`) |
| Genie outbound rejected states | `preview_pending`, `sent_archived`, and any other value → `ValueError` |
| `sent_archived` for Genie outbound | **Not implemented** |

**Persistence model today:**

- Saved owner artifact HTML (`output/admin_runs/{run_id}.email.html`) remains **pre-approval** content (includes operational handoff; no review confirmation box).
- Review confirmation is injected **only** at outbound send transform time in `today_geenee_customer_delivery.py`.
- Post-send durable signal: `admin_store.approve_run()` sets `customer_delivery_status = "customer_sent_after_approval"` and `customer_sent_at` **only after** successful SMTP.

---

## 3. Decision

**Do not** use `sent_archived` or the exact text:

> 본 브리핑은 운영책임자의 직접 검수를 통과하여 발송되었습니다.

in Genie **outbound customer email**.

### Reason

Outbound customer HTML is **constructed before** SMTP send success is known. The same HTML body is passed to `send_genie_email()` and only afterward does `approve_run()` persist send completion metadata.

Embedding **발송되었습니다** inside the email being transmitted creates a timing and semantic conflict:

1. The wording claims send completion inside content that may still fail to deliver.
2. Send-complete copy would conflate **owner approval** (`review_passed`) with **customer delivery completion** (`customer_sent_after_approval`).
3. Shared policy (`docs/REVIEW_OPERATION_BOX_POLICY.md` §4) requires: do not use **발송되었습니다** before actual send completion; `sent_archived` requires a real send-completion record.

`review_passed` is the correct boundary for approved outbound email: it confirms human 검수 completion without claiming SMTP/archive completion.

---

## 4. Allowed customer outbound state

For **Today_Geenee** approved customer outbound email:

| State | Outbound email |
|-------|----------------|
| `review_passed` | **Allowed** — only permitted `review_confirmation_state` |
| `preview_pending` | **Forbidden** — preview-only; not customer outbound |
| `sent_archived` | **Forbidden** — post-send/archive surface only |
| Any other / unsupported value | **Must raise `ValueError`** |

Default `prepare_customer_final_html(saved_html)` with `review_confirmation_state=None` returns strip-only HTML with **no** review box.

---

## 5. When `sent_archived` may be introduced later

`sent_archived` may be introduced **only** for surfaces that are clearly **post-send**, for example:

- Post-send archive copy (separate HTML artifact from outbound MIME body)
- Admin-visible sent copy / delivery record view
- Customer-accessible web or archive page generated after send success
- Persisted delivery record view backed by artifact metadata

### Required conditions before using `sent_archived`

All of the following must be true at render time:

- `customer_delivery_status == "customer_sent_after_approval"`
- `customer_sent_at` exists
- Send/archive completion record exists (persisted artifact or equivalent)
- The generated surface is **explicitly post-send**, not the outbound email body assembled pre-SMTP

Outbound customer email itself should **not** switch to `sent_archived` even after these conditions exist unless a separate design explicitly requires it — the safer default is to keep outbound MIME at `review_passed` and reserve `sent_archived` for archive/web copies.

---

## 6. State mapping

| Phase | Surface | Review confirmation state | Persisted metadata |
|-------|---------|---------------------------|-------------------|
| Pre-approval | Owner artifact HTML | None (no customer review box) | `owner_review_status=pending_review`, `customer_delivery_status=not_sent` |
| Owner Gmail | Owner email | None (admin operation box only) | `email_sent` may be true independently |
| Approved outbound | Customer SMTP body | `review_passed` | Unchanged until send succeeds |
| Post-send success | Metadata / admin view | N/A for outbound body | `approved`, `customer_sent_after_approval`, `customer_sent_at` |
| Post-send archive (future) | Archive copy / web page | `sent_archived` possible | Requires §5 conditions |
| Send failure | No customer delivery | No `sent_archived` | Stays `pending_review` / `not_sent` |
| Preview / test tools (future) | Explicit preview surfaces only | `preview_pending` allowed | Not Genie outbound email |

---

## 7. Tests already enforcing this

| Test file | Enforcement |
|-----------|-------------|
| `tests/test_genie_email_operation_box_semantics.py` | Default prepare has no review box; `review_passed` inserts box with policy text; `preview_pending`, `sent_archived`, `invalid_state` raise `ValueError`; outbound HTML lacks 발송되었습니다 / admin fragments; send path passes `review_passed` via mocked `send_genie_email` |
| `tests/test_batch_8_3_today_geenee_delivery.py` | Full approve path outbound HTML contains `review_passed` box; lacks `genie-operational-handoff`, 재발행, 발송되었습니다; duplicate approval still blocked |

These tests define the current phase contract. Any future `sent_archived` work must add **new** tests without weakening the outbound-email prohibitions above.

---

## 8. Non-goals

This decision note does **not** implement:

- Archive copy generation or storage
- `sent_archived` renderer for Genie
- Customer web archive page
- Tomorrow_Geenee customer delivery
- Email send retry state handling
- Delivery failure state mutation (`customer_delivery_status=failed` on SMTP failure)
- Admin web redesign

---

## 9. Future implementation conditions

Before adding `sent_archived` anywhere in Genie:

1. **Define archive surface** — separate from outbound SMTP MIME body.
2. **Define artifact path or DB field** for post-send HTML (e.g. `{run_id}.customer_sent.html` or equivalent).
3. **Ensure send success is persisted** before rendering `sent_archived` (`customer_sent_at` must exist).
4. **Add tests** proving outbound customer email **never** uses `sent_archived` or 발송되었습니다.
5. **Add tests** proving archive/post-send copy uses `sent_archived` **only** when `customer_sent_at` is set and surface is post-send.

---

## 10. Acceptance criteria for current phase

The current phase is **correct** if all of the following hold:

- [x] Outbound customer email contains `review_passed` confirmation box on approved send path
- [x] Outbound customer email does **not** contain 발송되었습니다
- [x] Outbound customer email does **not** contain `sent_archived` state or wording
- [x] Saved owner artifact HTML remains pre-approval (no review box persisted)
- [x] `customer_delivery_status` and `customer_sent_at` are the only durable post-send signals today
- [x] Unsupported review states (`preview_pending`, `sent_archived`) raise `ValueError` for outbound prepare

---

## References

- `today_geenee_customer_delivery.py` — `prepare_customer_final_html`, `render_genie_review_confirmation_box`, `send_today_geenee_customer_final_email`
- `admin_store.py` — `approve_run`, `customer_delivery_status`, `customer_sent_at`
- `docs/REVIEW_OPERATION_BOX_POLICY.md` — §4 Customer Review Confirmation Box, §5 Sent / Archive Confirmation
