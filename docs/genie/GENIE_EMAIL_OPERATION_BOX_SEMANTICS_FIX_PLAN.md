# Genie Email Operation Box Semantics — Fix Plan

## 1. Purpose

This document defines the safe implementation plan for correcting Genie owner/admin operational email labels **before** code changes.

Genie owner/admin operational email labels must clearly distinguish:

- **automated validation result** — outcome of `validators.py` / API `validation_result`
- **owner/admin Gmail delivery** — whether the owner-review SMTP send succeeded (`orchestrator.email_sent`)
- **owner approval / review completion** — human decision (`admin_store.owner_review_status`)
- **customer final email send completion** — whether customer SMTP send succeeded (`admin_store.customer_delivery_status`)
- **reissue/revision state** — admin reissue workflow (`reissue_count`, `parent_run_id`, admin web)

**Related policy:** `docs/REVIEW_OPERATION_BOX_POLICY.md`

**Inspection basis (2026-06):** `renderers.py`, `main.py`, `orchestrator.py`, `publishing_policy.py`, `today_geenee_customer_delivery.py`, `admin_routes.py`, `admin_store.py`, `tests/test_batch_8_3_today_geenee_delivery.py`, `tests/test_owner_review_send_policy.py`

---

## 2. Current confirmed implementation

| Component | Current behavior |
|-----------|------------------|
| Operational box renderer | `render_email_operational_box()` in `renderers.py` |
| DOM id | `#genie-operational-handoff` |
| Box title | `운영 안내` |
| Meta builder | `email_operational_handoff_meta()` in `main.py` |
| Meta fields | `mode_label`, `status_label`, `execution_time_kst`, `result_summary`, `email_delivery_label`, `rerequest_url`, `mode_code`, `revision_request_post_url` |
| Box rows | 모드, 현재 상태, 실행 시각, 핵심 결과 요약, **이메일 발송 여부** |
| Label source | `email_delivery_label` is derived from **`validation_result` only** |
| `validation_result == "pass"` | `status_label = "기본 검수 통과"`, `email_delivery_label = "이메일 발송 완료"` |
| SMTP timing | Labels are set at **render time** in `main.py` — **before** orchestrator SMTP result is known |
| Owner email send | `orchestrator.send_email_if_allowed()` → separate `email_sent: bool` on artifact metadata |
| Owner email subject (today) | `[운영자 검토]` prefix when not reissue |
| Persisted review state | `admin_store`: `owner_review_status` (default `pending_review`), `customer_delivery_status` (default `not_sent`) |
| Customer approval send | `admin_store.approve_run()` → `customer_delivery_status = "customer_sent_after_approval"` |
| Customer HTML prep | `today_geenee_customer_delivery.strip_owner_operational_handoff()` removes `#genie-operational-handoff` before customer send |
| Publishing policy | `send_customer_email=False` for scheduled today_genie; owner send gated by `GENIE_OWNER_REVIEW_SEND` + owner `EMAIL_TO` allowlist |
| Email operational copy | 재발행/수정 요청 notice text in box; **no interactive form** in email HTML (admin web has reissue form) |
| Tests | `test_batch_8_3_today_geenee_delivery.py` — strip, approve flow; `test_owner_review_send_policy.py` — owner gate |

---

## 3. Problem statement

### 3.1 `이메일 발송 완료` is unsafe

The phrase **이메일 발송 완료** can be read as **customer email sent**, but it currently only means **automated validation returned `pass`**.

It is **not** tied to:

- `orchestrator` `email_sent` (owner Gmail SMTP result)
- `customer_delivery_status` (customer send result)

Therefore the owner/admin operational box can display **이메일 발송 완료** even when:

- no email was sent (`email_sent=False`)
- customer email was never sent (`customer_delivery_status=not_sent`)

This conflicts with `docs/REVIEW_OPERATION_BOX_POLICY.md`: owner Gmail delivered must not equal customer sent; do not use send-complete wording before real send completion.

### 3.2 `기본 검수 통과` is unsafe

The phrase **기본 검수 통과** can be read as **human owner review completion (검수완료)**, but it currently only means **automated validation returned `pass`**.

Human owner approval is a separate persisted state (`owner_review_status = approved`) set only via `approve_run()` in admin — not via validation pass.

This conflicts with shared policy: validation PASS must not equal 검수완료.

### 3.3 Docstring mismatch

`email_operational_handoff_meta()` docstring refers to "customer-facing labels," but the operational box is **owner/admin** content and is **stripped** before customer final email.

---

## 4. Required semantic separation

Five concepts must remain separate. They must not be collapsed into one row or one label.

### A. `automated_validation_status`

Derived from API `validation_result` / validator outcome only.

| Condition | Proposed label |
|-----------|----------------|
| `pass` | **자동 검증 통과** |
| `draft_only` | **운영 검토 필요** |
| other / block | **자동 진행 불가** |

Must **not** imply human 검수완료 or any email send.

### B. `owner_review_email_delivery_status`

Derived from orchestrator SMTP result for **owner-review email** (`EMAIL_TO` owner allowlist), not customer `GENIE_CUSTOMER_EMAIL_TO`.

| Condition | Proposed label |
|-----------|----------------|
| Not attempted / policy blocked | **운영자 검수 메일 미발송** |
| Attempt pending / not yet sent | **운영자 검수 메일 발송 전** |
| SMTP success | **운영자 검수 메일 발송 완료** |
| SMTP failure | **운영자 검수 메일 발송 실패** |

Must **not** imply customer send.

**Open design point:** This status may not be available at initial HTML render time (see §9).

### C. `owner_review_status`

Human workflow state — aligned with `docs/REVIEW_OPERATION_BOX_POLICY.md` admin operation box states.

| State | Label |
|-------|-------|
| Default / pending | **검수대기** |
| After `approve_run()` | **검수완료** |
| Reissue requested | **재발행 필요** |
| On hold | **보류** |
| Revision requested | **수정요청** |

Must **not** be inferred from `validation_result == pass`.

### D. `customer_delivery_status`

Customer final email lifecycle — separate from owner Gmail.

| State | Label |
|-------|-------|
| Default | **고객 발송 전** |
| After successful `approve_run()` | **고객 발송 완료** |
| Send failure | **고객 발송 실패** |
| Not applicable (e.g. block, unsupported mode) | **고객 발송 대상 아님** |

Maps to persisted `customer_delivery_status` values such as `not_sent`, `customer_sent_after_approval`, `failed`.

### E. `revision/reissue_status`

Admin reissue workflow — separate from validation and customer send.

| State | Label |
|-------|-------|
| No reissue | **재발행 요청 없음** |
| Reissue needed | **재발행 필요** |
| Revision requested | **수정요청** |
| In progress | **재발행 처리 중** |
| Completed | **재발행 완료** |

Email box may show read-only copy only; interactive controls remain on admin web.

---

## 5. Admin operation box target

### Title

**운영자 검수 상태** (replaces `운영 안내`)

### DOM

Keep `#genie-operational-handoff` for backward compatibility with strip regex and existing tests — **or** migrate id in a coordinated change (deferred decision; strip tests depend on current id).

### Owner/admin box may show

| Row | Source concept |
|-----|----------------|
| 모드 | `mode_label` |
| 실행 시각 | `execution_time_kst` |
| 자동 검증 상태 | `automated_validation_status` (§4A) |
| 운영자 검수 상태 | `owner_review_status` (§4C) — when available |
| 운영자 검수 메일 발송 | `owner_review_email_delivery_status` (§4B) — when available |
| 고객 발송 상태 | `customer_delivery_status` (§4D) — when available |
| 재발행/수정 상태 | `revision/reissue_status` (§4E) — when available |
| 핵심 결과 요약 | `result_summary` (validation-oriented summary, not send claim) |

### Rules

- Must **not** imply customer send completion unless `customer_delivery_status` confirms it.
- Must **not** use **이메일 발송 완료** as a generic label tied to `validation_result`.
- Must **not** use **기본 검수 통과** for automated validation pass.
- 재발행/수정 요청 copy may remain read-only; no customer-facing controls.

---

## 6. Customer-facing final email target

Customer final email (`today_geenee_customer_delivery.prepare_customer_final_html`) must:

- **strip** `#genie-operational-handoff`
- **not** contain `운영자 검수 상태`
- **not** contain `재발행`, `다시 생성`, `수정요청`
- **not** contain owner review email delivery status rows
- **eventually** include `#review-confirmation-box` only after approval path exists (later phase — not this patch)
- use **발송되었습니다** wording only after `customer_delivery_status == customer_sent_after_approval` or a future archive completion record

MirAI:ON usage note and legal disclaimer remain separate footer components — not review confirmation.

**Current safe behavior to preserve:** strip regex in `today_geenee_customer_delivery.py`; tests in `test_batch_8_3_today_geenee_delivery.py`.

---

## 7. Immediate implementation sequence

Documentation-only here. Recommended **code/test** order for the first patch:

### Step 1 — tests first (TDD)

Add or update tests proving:

- `validation_result == "pass"` **no longer** produces `이메일 발송 완료` in operational meta
- `validation_result == "pass"` uses **자동 검증 통과**, not **기본 검수 통과**
- owner/admin operational box title becomes **운영자 검수 상태**
- customer final HTML still strips `#genie-operational-handoff`
- customer final HTML does **not** contain `재발행`, `수정요청`, or `운영자 검수 상태`

Suggested test files:

- New: `tests/test_genie_email_operational_box_semantics.py` (or extend existing delivery tests)
- Keep: `tests/test_batch_8_3_today_geenee_delivery.py` strip/approve tests green

### Step 2 — implementation (narrow scope)

- Update `email_operational_handoff_meta()` label mapping (§4A; remove unsafe §3 strings)
- Update `render_email_operational_box()` title and row labels if needed (§5)
- **Do not** add customer `#review-confirmation-box` yet
- **Do not** wire `owner_review_email_delivery_status` from orchestrator in this patch unless Step 1 tests explicitly require it — prefer absent/honest label over false complete

### Step 3 — regression tests

Run:

```bash
python3 -m unittest tests.test_batch_8_3_today_geenee_delivery -v
python3 -m unittest tests.test_owner_review_send_policy -v
python3 -m unittest tests.test_genie_email_operational_box_semantics -v  # when added
```

### Step 4 — later (separate tasks)

- Add customer `#review-confirmation-box` after approval/state gate is defined
- Inject `owner_review_email_delivery_status` post-SMTP if product requires it in saved HTML
- Tomorrow_Geenee customer delivery module
- Reissue max 2회 enforcement

---

## 8. Explicit non-goals

This plan and the **first code patch** must **not** implement:

- customer review confirmation box (`#review-confirmation-box`)
- `sent_archived` equivalent
- send/archive completion gate beyond existing `customer_sent_after_approval`
- reissue count enforcement (최대 2회)
- Tomorrow_Geenee customer send path
- admin web redesign
- email sending behavior changes
- scheduler changes
- publishing policy changes (unless strictly required for label injection — defer)

---

## 9. Open questions

| # | Question | Current bias |
|---|----------|--------------|
| 1 | Should **owner review email delivery status** be injected after orchestrator send result, or remain absent from rendered HTML? | **Absent or honest "미발송/발송 전"** in first patch if SMTP result unknown at render time |
| 2 | Should saved artifact HTML be regenerated or annotated after owner email send result? | **Defer** — artifact stores `email_sent` in JSON; HTML may be stale on delivery row |
| 3 | Should Tomorrow_Geenee get a customer delivery module later? | **Yes, separate task** — only Today_Geenee has `today_geenee_customer_delivery.py` today |
| 4 | Should revision **최대 2회** be enforced in `admin_store` / `admin_routes`? | **Defer** — currently copy-only in email box |
| 5 | Rename DOM id from `genie-operational-handoff` to match policy naming? | **Keep id** in first patch to avoid breaking strip regex and tests |

---

## 10. Acceptance criteria for future code patch

A semantics-fix patch is **acceptable** only if **all** of the following hold:

- [ ] No string **이메일 발송 완료** is produced from `validation_result` alone
- [ ] No string **기본 검수 통과** is used for automated validation pass
- [ ] Owner/admin box title is **운영자 검수 상태**
- [ ] Automated pass label is **자동 검증 통과** (or equivalent from §4A)
- [ ] Customer final email remains stripped of admin operation box
- [ ] Tests prove customer HTML has no admin controls (`재발행`, `수정요청`, operational box)
- [ ] No email API is invoked in tests (mocks only)
- [ ] No scheduler is triggered
- [ ] `docs/REVIEW_OPERATION_BOX_POLICY.md` surface matrix remains satisfied for Genie owner vs customer paths

---

## References

| Document / module | Role |
|-------------------|------|
| `docs/REVIEW_OPERATION_BOX_POLICY.md` | Shared box taxonomy and forbidden mixing |
| `docs/keysuri/KEYSURI_HTML_PREVIEW_VALIDATOR_REVIEW_BOX_DECISION.md` | Validator deferral; points to Genie semantics as next step |
| `renderers.py` | `render_email_operational_box()`, `render_email_html()` |
| `main.py` | `email_operational_handoff_meta()` |
| `orchestrator.py` | Owner email send, `email_sent` artifact field |
| `publishing_policy.py` | Owner vs customer send separation |
| `today_geenee_customer_delivery.py` | Customer strip and send |
| `admin_store.py` | `owner_review_status`, `customer_delivery_status`, `approve_run()` |
| `admin_routes.py` | Admin approve and reissue UI |
