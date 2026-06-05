# Kee-Suri Terminology Lock

## 1. Purpose

Kee-Suri terminology is a **product asset**, not disposable copy. Section labels, identity phrases, and briefing-structure terms define how operators and customers recognize the product.

This document **locks known terms** before title/body section contract design.

Clarifications:

- This file does **not** connect Cloud Scheduler, enable production auto-calls, or send email.
- This file does **not** change runtime code or JSON schema validators.
- This file is a **design guard** for copy, contracts, and future documentation.

Rules:

- **Do not create new section labels** that overwrite existing locked labels in `keysuri_private_briefing.py` and related validators.
- **Do not import** Today_Geenee / Tomorrow_Geenee language into Kee-Suri customer-facing copy.
- **Do not normalize** subtitle drift silently — unresolved choices are listed in §9.

Related documents:

- `docs/keysuri/KEYSURI_R6B_PRODUCTION_PROMOTION_CHECKLIST.md` — promotion gate (commit `8313281`)
- `docs/keysuri/KEYSURI_R6B_OFFDUTY_02C_PROMPT_DIRECTION_ONLY_DECISION.md` — prompt-direction lock (commit `07a98ac`)
- `docs/keysuri/KEYSURI_SCHEDULER_STATE_AND_FUTURE_WIRING_DESIGN.md` — scheduler state (commit `1b23bcf`)

Code-aligned sources:

- `keysuri_private_briefing.py` — locked section constants and forbidden renames
- `keysuri_news_contract.py` — scope-specific TOP 5 headings
- `keysuri_prompt_profiles.py` — prompt profile section rules
- `keysuri_generation_prompt.py` — generation identity strings
- `keysuri_renderer.py` — owner-review HTML identity display
- `keysuri_generated_briefing.py` — generated briefing validation and forbidden identity strings

---

## 2. Owner-confirmed canonical section terms

The following terms are **owner-confirmed** as the correct Kee-Suri production section labels.

| Canonical label | JSON field | Status |
|-----------------|------------|--------|
| **`키수리의 딥-다이브`** | `deep_dive.section_heading` | **Approved — preserve exactly** |
| **`원-라인 체크포인트`** | `one_line_checkpoint.section_heading` | **Approved — preserve exactly** |

### 2.1 Rejected labels (not production Kee-Suri terms)

The following are **not approved** Kee-Suri section labels, aliases, replacements, or migration targets **unless a future owner-approved rename migration is explicitly created and implemented in code + validators + samples**.

**Do not use:**

| Rejected term | Variants |
|---------------|----------|
| 원-다이브 | 원다이브, 원 다이브 |
| One-Dive | One Dive, ONE-DIVE |
| 원포인트 | 원-포인트, 원 포인트 |
| One-Point | One Point, ONE-POINT |

**Policy:** Do not introduce these in docs, prompts, UI, email HTML, subject lines, or title/body contracts as synonyms for the canonical labels above.

### 2.2 Mapping note (inspection only — not aliases)

Terminology inspection found no repo occurrences of 원-다이브 / 원포인트 / One-Dive / One-Point. The committed equivalents are **`키수리의 딥-다이브`** and **`원-라인 체크포인트`**. They are **not interchangeable spellings** — only the canonical forms are valid production labels.

---

## 3. Current canonical identity terms

### 3.1 Locked identity terms

| Term | Usage | Keep |
|------|-------|------|
| **테크 비서 키수리** | Primary Korean persona title (`IDENTITY_TITLE`) | **Yes** |
| **키수리** | Short Korean name in prompts and copy | **Yes** |
| **Kee-Suri** | English product name | **Yes** |
| **프라이빗 테크 비서** | Role identity in generation/visual paths (`IDENTITY_SUBTITLE` in `keysuri_generation_prompt.py`) | **Yes — preferred role identity until subtitle resolved** |
| **private tech secretary** | English role guardrail | **Yes** |
| **glamorous premium AI tech secretary** | Registry role + prompt profile role string | **Yes** |

### 3.2 Subtitle drift (unresolved — do not silently normalize)

| Phrase | Where found | Status |
|--------|-------------|--------|
| **프라이빗 테크 비서** | `keysuri_generation_prompt.py`, `keysuri_visual_context.py`, sample contracts | **Preferred role identity** until owner resolves subtitle |
| **프라이빗 테크 인사이트 브리핑** | `keysuri_renderer.py` `IDENTITY_SUBTITLE` | **Renderer subtitle candidate only** — not universal identity replacement |

**Policy until §9 is resolved:**

- Use **`프라이빗 테크 비서`** for role identity in generation prompts, validation copy, and new contracts.
- **`프라이빗 테크 인사이트 브리핑`** may appear in owner-review HTML renderer subtitle only — do not propagate to schema, validators, or customer email without explicit owner approval.

### 3.3 Program display names

| program_id | Display label |
|------------|---------------|
| `keysuri_global_tech` | Kee-Suri Global Tech |
| `keysuri_korea_tech` | Kee-Suri Korea Tech |

---

## 4. Locked section labels

These are **current code/schema-aligned** Kee-Suri section labels. Preserve **exact spellings** including hyphens, spacing, and Korean particles.

| JSON / schema key | Locked `section_heading` | Scope |
|-------------------|--------------------------|-------|
| `top_5_news` | **글로벌 테크 TOP 5** | `keysuri_global_tech` only |
| `top_5_news` | **국내 테크 TOP 5** | `keysuri_korea_tech` only |
| `deep_dive` | **키수리의 딥-다이브** | Both programs |
| `one_line_checkpoint` | **원-라인 체크포인트** | Both programs |
| `closing_sources` | **마무리 및 출처 리스트** | Both programs |

**Source of truth:** `keysuri_private_briefing.py` constants `SECTION_DEEP_DIVE`, `SECTION_ONE_LINE`, `SECTION_CLOSING`; `keysuri_news_contract.py` `SECTION_TOP5_GLOBAL` / `SECTION_TOP5_KOREA`.

### 4.1 Forbidden replacements

Do **not** replace locked labels with:

| Forbidden replacement | Why blocked |
|----------------------|-------------|
| 심층 분석 | Generic — weakens brand (`FORBIDDEN_SECTION_RENAMES`) |
| 핵심 요약 | Today_Geenee-style generic |
| 출처 | Too thin for closing section |
| generic **TOP 5** / **TOP 3** | Strips global/korea scope |
| **오늘의 핵심 요약** | Today_Geenee bleed |
| **키수리의 한 줄 판단** | Unapproved invented heading |
| **원-다이브** / **원포인트** / **One-Dive** / **One-Point** | Rejected — see §2.1 |

**Rename migration rule:** Any change to locked section spellings requires a separate owner-approved migration updating `keysuri_private_briefing.py`, validators, tests, prompt profiles, and sample fixtures together.

---

## 5. Product-language assets

### A. Identity terms

| Term | Asset type |
|------|------------|
| 테크 비서 키수리 | Primary title |
| 프라이빗 테크 비서 | Role identity (preferred) |
| private tech secretary | English role |
| Kee-Suri Global Tech | Program label — global 12:30 |
| Kee-Suri Korea Tech | Program label — korea 18:30 |

### B. Briefing structure terms

| Term | Role |
|------|------|
| 글로벌 테크 TOP 5 | Global TOP block heading |
| 국내 테크 TOP 5 | Korea TOP block heading |
| 키수리의 딥-다이브 | Deep analysis section |
| 원-라인 체크포인트 | One-line checkpoint section |
| 마무리 및 출처 리스트 | Closing + source list section |

### C. Signal / relevance terms

| Field / term | Container | Purpose |
|--------------|-----------|---------|
| `why_it_matters` | TOP 5 item | Relevance / signal hook |
| `business_implication` | TOP 5 item | Money/work decision hook |
| `risk_note` | TOP 5 item (optional) | Risk annotation |
| `key_implications` | `deep_dive` | Bullet implications under 딥-다이브 |
| `closing_message` | `closing_sources` | End-of-briefing prose |

### D. Governance / operation terms

| Term | Usage |
|------|-------|
| `review_required` | `operational_status` — pre-send owner gate |
| `generated_review_required` | `generated_status` — post-generation review |
| Owner-review | Internal preview surfaces (`keysuri_renderer.py`) |
| Source Gate / TOP 5 Selection Audit | Internal audit UI section |

**Policy:** Internal governance terms (`staged`, `generation_pending`, `Gemini 호출 전`, audit section titles) **must not leak** into customer copy unless explicitly intended for operator-only surfaces.

---

## 6. Forbidden / dangerous terms

### 6.1 Identity / role violations

- 테크 앵커
- 뉴스 앵커
- 아나운서
- public news anchor
- announcer
- tech anchor / news anchor (English)

### 6.2 Program bleed

- Today_Geenee
- Tomorrow_Geenee
- tomorrow_genie
- 오늘의 핵심 요약

### 6.3 Wrong product genre

- 생활 노트
- 운세
- 날씨 브리핑 (as Kee-Suri persona framing)
- girlfriend fantasy
- idol fan-service
- weathercaster emotional filler

### 6.4 Test / system / demo smell (customer copy)

- 생성 결과
- 테스트 결과
- staging / E2E / demo language
- generic newsletter wording

### 6.5 Rejected section-label variants

- 원-다이브, 원다이브, 원 다이브
- One-Dive, One Dive, ONE-DIVE
- 원포인트, 원-포인트, 원 포인트
- One-Point, One Point, ONE-POINT

### 6.6 Generic section weakenings

- 심층 분석 (instead of 키수리의 딥-다이브)
- 핵심 요약 (instead of 원-라인 체크포인트)
- 출처 (instead of 마무리 및 출처 리스트)
- generic TOP 5 without scope prefix

---

## 7. Opal prototype recovery mapping

Opal benchmark language appears in `ops/quality_gate/OPAL_BENCHMARK_TODAY_GENIE_EMAIL_REVIEW.md` as a **Today_Geenee finish-quality bar** — not as Kee-Suri section labels.

### 7.1 Recover from Opal (concepts — not literal section names)

| Opal concept | Recover |
|--------------|---------|
| **Opening Power** | Inbox/subject + opening lead quality |
| **Briefing Authority** | Concrete, premium desk-note credibility |
| **Visual / Text Rhythm** | Top visual → editorial body → optional close pacing |
| **Product Language** | Shipped-product tone — no demo/staging smell |

### 7.2 Map to Kee-Suri (without changing locked labels)

| Opal concept | Kee-Suri mapping |
|--------------|------------------|
| Opening Power | Subject line + opening summary rules — **does not rename** TOP 5 or 딥-다이브 headings |
| Briefing Authority | TOP 5 + **키수리의 딥-다이브** + **원-라인 체크포인트** content quality |
| Visual / Text Rhythm | Top-shot opening mood + JSON body sections + optional 18:30 R6B bottom-shot close (image track separate) |
| Product Language | Remove test/system tone; keep private secretary register |

### 7.3 Do not copy from Opal / Today_Geenee

- Today_Geenee morning-market / 장전 브리핑 framing
- Weather / emotional comfort structure as Kee-Suri core
- Generic “news collection” or public-broadcast tone
- Opal criterion names as **customer-facing section headings** unless owner explicitly approves
- **원-다이브 / 원포인트 / One-Dive / One-Point** — rejected (§2.1)

---

## 8. Title/body contract implications

The future **title/body section contract** must treat this document as the terminology source of truth.

### 8.1 Must use locked section labels

The contract **must** preserve exact headings:

- Scope-specific **글로벌 테크 TOP 5** / **국내 테크 TOP 5**
- **키수리의 딥-다이브**
- **원-라인 체크포인트**
- **마무리 및 출처 리스트**

It may add rules for subject lines, opening summaries, paragraph rhythm, section density, and bottom-shot closing rhythm — **without replacing** these section names.

### 8.2 May define (additive only)

- Email / in_app **subject line** patterns
- Opening summary rules (prose under or before TOP 5 — not a new section heading)
- Paragraph rhythm and scanning structure
- Per-section content density and tone
- 18:30 bottom-shot closing rhythm (image track — separate from JSON section headings)

### 8.3 Must not invent

| Forbidden invention | Correct locked term |
|--------------------|---------------------|
| 오늘의 핵심 신호 (as replacement heading) | Use scope-specific TOP 5 + 원-라인 체크포인트 |
| 키수리의 한 줄 판단 | **원-라인 체크포인트** |
| 핵심 요약 | **원-라인 체크포인트** |
| 원-다이브 | **키수리의 딥-다이브** |
| 원포인트 / One-Point | **원-라인 체크포인트** |
| 심층 분석 | **키수리의 딥-다이브** |

### 8.4 Contract dependency order

1. This terminology lock (committed)
2. Title/body section contract (next)
3. Implementation changes (only after explicit approval — not automatic)

---

## 9. Open owner decisions

The following remain **unresolved**. Do not silently pick one in new copy or contracts.

### 9.1 Canonical subtitle

Which customer-facing subtitle is authoritative?

| Option | Current usage |
|--------|---------------|
| **프라이빗 테크 비서** | Generation + visual context — **preferred interim** |
| **프라이빗 테크 인사이트 브리핑** | Renderer owner-review subtitle only |
| Another approved phrase | Requires explicit owner sign-off |

### 9.2 Closing section customer display

Should **`마무리 및 출처 리스트`** remain the customer-visible heading, or should the renderer/email layer show a softer customer label while the JSON schema keeps the locked key and validator string?

**Default until decided:** Schema and validators keep **`마무리 및 출처 리스트`** exactly.

### 9.3 Email subject line pattern

Should the subject use:

- `테크 비서 키수리`
- `키수리 브리핑`
- Program-specific label (`Kee-Suri Global Tech` / `Kee-Suri Korea Tech`)
- Another approved pattern?

**Not decided in this document.**

### 9.4 Explicitly not open decisions

**One-Dive / One-Point variants are rejected** as production Kee-Suri terms (§2.1). They are not listed here as options pending owner choice. A future rename migration would be a **separate explicit approval**, not an open design question.

---

## 10. Acceptance checklist

Before writing the title/body section contract, confirm:

- [ ] Locked section labels preserved exactly (§4)
- [ ] **키수리의 딥-다이브** preserved — no 원-다이브 / One-Dive variants
- [ ] **원-라인 체크포인트** preserved — no 원포인트 / One-Point / 핵심 요약 variants
- [ ] One-Dive / One-Point variants **not introduced** as aliases or headings
- [ ] Subtitle drift acknowledged — **프라이빗 테크 비서** vs **프라이빗 테크 인사이트 브리핑** (§3.2, §9.1)
- [ ] Today/Tomorrow_Geenee language blocked (§6.2)
- [ ] Opal concepts mapped to Kee-Suri quality — not copied as section labels (§7)
- [ ] Internal/test/system terms blocked from customer copy (§5.D, §6.4)
- [ ] Title/body contract references this lock as terminology source (§8)

---

## 11. Recommended next steps

| Step | Action | Status |
|------|--------|--------|
| 1 | Commit this terminology lock | Pending operator request |
| 2 | Create title/body section contract using this document as source | **Do not start before step 1** |
| 3 | Resolve open owner decisions in §9 before customer email/subject finalization | Not started |

**Do not write the title/body section contract before this terminology lock is committed.**

---

## Appendix A — Code reference map

| Locked term | Primary code location |
|-------------|---------------------|
| 키수리의 딥-다이브 | `keysuri_private_briefing.py` → `SECTION_DEEP_DIVE` |
| 원-라인 체크포인트 | `keysuri_private_briefing.py` → `SECTION_ONE_LINE` |
| 마무리 및 출처 리스트 | `keysuri_private_briefing.py` → `SECTION_CLOSING` |
| 글로벌 테크 TOP 5 | `keysuri_news_contract.py` → `SECTION_TOP5_GLOBAL` |
| 국내 테크 TOP 5 | `keysuri_news_contract.py` → `SECTION_TOP5_KOREA` |
| Forbidden renames | `keysuri_private_briefing.py` → `FORBIDDEN_SECTION_RENAMES` |
| Prompt profile rules | `keysuri_prompt_profiles.py` → `_FORBIDDEN_RENAME_RULES` |
| 테크 비서 키수리 | `keysuri_generation_prompt.py` → `IDENTITY_TITLE` |
| 프라이빗 테크 비서 | `keysuri_generation_prompt.py` → `IDENTITY_SUBTITLE` |
| 프라이빗 테크 인사이트 브리핑 | `keysuri_renderer.py` → `IDENTITY_SUBTITLE` (drift) |

---

## Appendix B — Related commits (terminology / promotion context)

| Commit | Message |
|--------|---------|
| `8313281` | Update Kee-Suri R6B promotion checklist decision state |
| `07a98ac` | Record Kee-Suri R6B offduty_02C prompt-direction decision |
| `1b23bcf` | Document Kee-Suri scheduler state and future wiring design |
