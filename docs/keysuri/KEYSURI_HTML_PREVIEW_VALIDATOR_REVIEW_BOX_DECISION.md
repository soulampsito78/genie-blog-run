# Kee-Suri HTML Preview Validator — Review Confirmation Box Decision (v1)

## 1. Purpose

This note decides how `keysuri_html_preview_validation.py` should treat the **review confirmation box** (`#review-confirmation-box`) in a future validator v1 pass.

It answers one question: **Should the HTML preview validator enforce review-confirmation-box presence and state in v1?**

**Decision:** Defer automatic validator enforcement. Keep review-confirmation-box behavior locked by renderer tests for now.

**Related policy:** `docs/REVIEW_OPERATION_BOX_POLICY.md`

---

## 2. Current state

| Component | Status |
|-----------|--------|
| `keysuri_contract_preview_renderer.py` | Renders `#review-confirmation-box` with `data-review-state` and exact Korean copy for `preview_pending`, `review_passed`, `sent_archived` |
| `tests/test_keysuri_contract_preview_renderer.py` | Locks DOM hooks, exact Korean text, separation from validation/operation metadata boxes, forbidden admin controls in review block, Korea bottom-shot → review confirmation → warm close order, `preview_pending` default, `sent_archived` fixture-only documentation |
| `keysuri_html_preview_validation.py` (v0) | Validates automated contract requirements; **does not** reference or enforce `review-confirmation-box` |
| `tests/test_keysuri_html_preview_validation.py` | Covers v0 validator behavior; no review-confirmation-box assertions |

This separation is **acceptable for v0**.

The `html_test/` contract preview surface intentionally contains multiple box types in one HTML file:

- Customer-safe **review confirmation** box
- Automated **validation result** box
- **Operation metadata** box
- **Rights policy** footer

---

## 3. Decision

**Do not add review-confirmation-box enforcement to `keysuri_html_preview_validation.py` yet.**

Keep enforcement in `tests/test_keysuri_contract_preview_renderer.py` until the conditions in §6 are met.

---

## 4. Rationale

- **Human review state must not be conflated with automated validation PASS.** If the validator enforces review state too early, a CLI `validation_status: PASS` may be read as owner `검수완료`.
- **Review confirmation is customer-safe copy, but not an automated quality proof.** It communicates lifecycle state to the owner during visual review — not contract compliance.
- **Validation result box and review confirmation box are separate components** per `docs/REVIEW_OPERATION_BOX_POLICY.md` and `docs/keysuri/KEYSURI_CONTRACT_PREVIEW_RENDERER_DESIGN.md` §6.
- **`html_test/` is a contract preview surface, not the final customer email.** It is expected to mix internal boxes (validation, operation metadata) with customer-safe sections for owner visual review.
- **Customer final email/export should have its own stricter strip/export tests later.** Validator v1 for review confirmation should not precede a clearly defined customer-final export surface.

---

## 5. What validator v0 continues to check

Based on `keysuri_html_preview_validation.py` and `tests/test_keysuri_html_preview_validation.py`, v0 continues to enforce **automated contract** requirements only. Representative categories:

| Category | v0 behavior (summary) |
|----------|----------------------|
| Required preview contract sections | Preview metadata, identity title, TOP 5 heading, deep-dive section, one-line checkpoint, closing section, operation metadata, compliance checklist, validation result box |
| TOP 5 / source structure | Item-level source visibility (name, URL, verification status) |
| Deep-dive readability | Layer structure when content is dense |
| Rights policy / footer | Exact MirAI:ON copyright lines |
| No hashtags | Hashtag section absent |
| No production implication | Forbidden Genie bleed, `production_ready` / `scheduler_ready` / `email_ready` language |
| Korea 18:30 warm-close order | Bottom-shot before warm close before closing (when Korea 18:30 evidence is present) |

**Not in v0:** review-confirmation-box presence, `data-review-state`, review-state Korean copy, admin-control absence inside review block.

---

## 6. Conditions for future validator v1 enforcement

Review-confirmation-box checks may be added to the validator **only when all** of the following hold:

1. Renderer tests in `tests/test_keysuri_contract_preview_renderer.py` remain green.
2. Customer-final export surface is separated or clearly defined (distinct from `html_test/` multi-box preview).
3. Review state promotion rules exist (who may set `review_passed`, when `sent_archived` is allowed).
4. `preview_pending` / `review_passed` / `sent_archived` are mapped to allowed surfaces per `docs/REVIEW_OPERATION_BOX_POLICY.md` surface matrix.
5. `sent_archived` is gated by a **real send/archive completion record** — not renderer default or CLI fixture alone.
6. Validator output wording clearly distinguishes **automated validation PASS** from owner **검수완료**.

Until then, deferring validator enforcement avoids premature coupling of human review state to automated PASS.

---

## 7. Possible v1 checks (later only)

If adopted after §6 conditions are met, the validator **may** add optional checks such as:

| Check | Detail |
|-------|--------|
| Box exists | `#review-confirmation-box` present |
| State attribute | `data-review-state` present |
| Allowed states | One of `preview_pending`, `review_passed`, `sent_archived` |
| Exact Korean copy | Text matches state per `docs/REVIEW_OPERATION_BOX_POLICY.md` §4 |
| No admin controls in block | Block must not contain `재발행`, `다시 생성`, `수정요청` |
| No internal metadata in block | Block must not contain `scheduler`, `preview_path`, `manifest_path`, `validation_status` |
| Korea 18:30 placement | Review confirmation appears after bottom-shot and before warm close (when Korea 18:30 bottom-close preview) |

These checks should inspect **only** the extracted review-confirmation block — not the whole HTML — because operation metadata and validation result boxes legitimately contain internal terms on the `html_test/` surface.

**Heading localization:** Do not fail on English heading `Review confirmation` until a separate owner decision requires Korean heading (see contract preview design doc §6).

---

## 8. Non-goals

This decision note does **not**:

- change renderer code
- change validator code
- change tests
- implement customer final email export
- implement send/archive completion gate
- approve `sent_archived` for production default
- require validator v1 in the next implementation batch

---

## 9. Next recommended implementation order

After this decision note is committed:

1. Commit this decision note.
2. Move to **Genie operational box semantics** inspection (`운영 안내` → `운영자 검수 상태`, `email_delivery_label` semantics).
3. Fix Genie **"이메일 발송 완료"** semantics before adding customer review confirmation box.
4. Only later revisit Kee-Suri validator v1 — after customer-final export surface and review-state promotion rules exist.

---

## References

| Document / module | Role |
|-------------------|------|
| `docs/REVIEW_OPERATION_BOX_POLICY.md` | Shared box taxonomy and forbidden mixing rules |
| `docs/keysuri/KEYSURI_CONTRACT_PREVIEW_RENDERER_DESIGN.md` | Contract preview renderer design; §6 review confirmation policy |
| `docs/keysuri/KEYSURI_TITLE_AND_BODY_SECTION_CONTRACT.md` | Section order including Korea review confirmation placement |
| `keysuri_contract_preview_renderer.py` | Renders review confirmation box |
| `keysuri_html_preview_validation.py` | v0 automated contract validator (no review box today) |
| `tests/test_keysuri_contract_preview_renderer.py` | Current enforcement for review box behavior |
| `tests/test_keysuri_html_preview_validation.py` | v0 validator test suite |
