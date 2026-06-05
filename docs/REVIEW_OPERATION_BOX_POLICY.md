# Shared Review / Operation Box Policy

## 1) Purpose

This document defines a shared box policy for Today_Geenee, Tomorrow_Geenee, Kee-Suri Global, and Kee-Suri Korea.

The goal is to prevent internal review controls, scheduler metadata, validation details, and customer-facing review confirmation from being mixed into the wrong output surface.

In particular, owner/admin Gmail and customer-facing outputs must not share the same control UI.

---

## 2) Box Taxonomy

The following are separate components and must not be collapsed into one box:

- A. Admin operation box
- B. Customer review confirmation box
- C. Sent/archive confirmation
- D. Validation result box
- E. Operation metadata box

Also:

- F. Rights/footer is not a review box.

---

## 3) Admin Operation Box

### Audience

- owner/admin Gmail
- admin web
- internal owner-review surfaces

### Title

- `운영자 검수 상태`

### Allowed states

- `검수대기`
- `검수완료`
- `재발행 필요`
- `보류`
- `수정요청`

### Allowed admin-only controls/copy

- `다시 생성`
- `재발행`
- `검수 완료 처리`
- `보류`
- `수정 요청`
- `validation_status`
- `manifest_status`
- `preview_path`
- source freshness
- image overlay status
- rerun/reissue metadata

### Rules

- May appear in owner/admin Gmail.
- May appear in admin web.
- Must not appear in customer-facing final HTML/email.
- Must not be confused with validation result box.

---

## 4) Customer Review Confirmation Box

### Audience

- customer-facing final briefing
- approved preview shown as customer-like output
- public/archive output only when state allows

### DOM recommendation

- `id="review-confirmation-box"`
- `data-review-state="{state}"`

### States and exact text

#### `preview_pending`

본 브리핑은 운영책임자의 직접 검수 대기 상태입니다.

#### `review_passed`

본 브리핑은 운영책임자의 직접 검수를 통과했습니다.

#### `sent_archived`

본 브리핑은 운영책임자의 직접 검수를 통과하여 발송되었습니다.

### Rules

- No admin controls.
- No `재발행`.
- No `다시 생성`.
- No scheduler/debug/internal paths.
- No `preview_path`.
- No validation details unless separately internal.
- Do not use `발송되었습니다` before actual send completion.
- `sent_archived` requires a real send-completion record.
- `review_passed` requires explicit owner approval.
- `preview_pending` is allowed only in preview/pre-approval context.

---

## 5) Sent / Archive Confirmation

- `sent_archived` is not a separate admin state.
- It is the sent/archive branch of the customer review confirmation box.
- It may be used only after real customer send completion or persisted archive completion.
- Owner Gmail send success does not equal customer send completion.

---

## 6) Validation Result Box

### Purpose

Automated contract or quality checks.

### Examples

- `validation_status: PASS/FAIL`
- `required_sections`
- `top5_sources`
- `rights_policy`
- `no_hashtags`
- `no_production_implication`

### Rules

- It is not human approval.
- It must not imply owner `검수완료`.
- It must not replace customer review confirmation.
- It may appear in `html_test` / internal preview surfaces.
- It should not appear in final customer email unless explicitly designed.

---

## 7) Operation Metadata Box

### Purpose

Server/run context.

### May include

- `program_id`
- `mode`
- `slot`
- `run_id`
- `preview_path`
- `manifest_path`
- source freshness
- image overlay status
- scheduler metadata

### Rules

- Internal by default.
- Must not dominate customer-facing copy.
- Must not be shown in customer final email unless stripped or intentionally transformed.

---

## 8) Rights / Footer

- MirAI:ON rights footer is separate from review and operation status.
- It must not be used as proof of review.
- It must not replace image watermark.
- It may appear in both owner and customer surfaces.

---

## 9) Surface Matrix

| Surface | Admin operation box | Customer review confirmation | Validation result box | Operation metadata | Rights/footer |
|---|---|---|---|---|---|
| Genie owner email | yes | no | implicit/internal | yes | yes if part of briefing |
| Genie customer email | no | yes (future) | no | no | yes |
| Genie admin web | yes (actions) | no | yes/internal | yes | optional |
| Kee-Suri contract `html_test` preview | no | yes | yes | yes | yes |
| Kee-Suri owner-review HTML | yes (future/admin-audit) | no | no or internal only | yes | optional |
| Kee-Suri future customer email/archive | no | yes | no | no | yes |

---

## 10) Current Gaps from Inspection

### Genie

- Current owner email uses `운영 안내` instead of standardized `운영자 검수 상태`.
- Current labels are validation-oriented: `기본 검수 통과` / `운영 검토 필요` / `자동 진행 불가`.
- `email_delivery_label = 이메일 발송 완료` can be misleading because owner-review email send is not customer send completion.
- Customer-facing review confirmation box is missing.

### Kee-Suri

- Contract preview renderer already has review confirmation states.
- `KEYSURI_TITLE_AND_BODY_SECTION_CONTRACT.md` Korea order should include review confirmation between bottom-shot and warm close.
- `html_test` contains validation/operation boxes and is not final customer email.
- Owner-review renderer is separate and may expose scheduler/audit details by design.

---

## 11) Forbidden Mixing Rules

- Customer-facing output must not contain admin operation controls.
- Customer-facing output must not contain `재발행` / `다시 생성` / `수정요청` controls.
- Customer-facing output must not contain scheduler/debug/internal paths.
- Validation PASS must not equal `검수완료`.
- Owner Gmail delivered must not equal customer sent.
- `sent_archived` must not be emitted without send/archive completion record.
- MirAI:ON rights footer must not be treated as review confirmation.

---

## 12) Implementation Sequence Recommendation (Later)

1. Update Kee-Suri docs to reference this shared policy.
2. Update Kee-Suri title/body contract Korea order to include review confirmation box.
3. Add/adjust tests for review confirmation presence if needed.
4. Update Genie owner operational box naming/state mapping.
5. Fix Genie `email_delivery_label` semantics.
6. Add Genie customer review confirmation box only on approved customer path.
7. Add a shared review-state promotion helper later if needed.

---

## 13) Non-goals

This document does not implement:

- email sending
- scheduler behavior
- approval workflow backend
- admin UI actions
- customer delivery
- Content Shield tracking
- file-copy tracking
