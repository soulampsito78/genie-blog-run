# GENIE × KeeSuri — Frontend UX Spec v1

**Status:** APPROVED
**Version:** v1
**As of:** 2026-08-10 (KST)
**Authority:** Customer-facing screen behavior (implementation guidance)
**Parent:** `docs/web/GENIE_KEYSURI_CUSTOMER_WEB_SSOT_v1.md`
**Policy sources:** Lifecycle, Auth, Delivery contracts
**Map:** `docs/web/DOCUMENT_MAP_AND_AUTHORITY.md`

This spec defines product-screen behavior. It **MUST NOT** contradict domain policy.
`web_prototype/` is REFERENCE ONLY; reconcile later against this document.

Keep UI small. Prefer one primary action per step.

---

## 1. Global UX rules

- Mark irreversible actions with explicit confirmation.
- Show loading / retry for network failures; fail closed on payment/IDV uncertainty.
- Never imply automatic paid conversion after card registration.
- Never show customer passwords (passwordless).
- Prices: VAT-inclusive KRW; use catalog from Lifecycle.
- Mock/dev builds MUST label non-production clearly; production MUST NOT use `[MOCK]` banners.

### 1.1 Shared copy anchors (Korean examples)

| Context | Example |
|---------|---------|
| Hero headline | 당신의 메일함으로 / 찾아오는 인사이트 |
| Hero support | AI 지니와 키수리 글로벌·코리아가 국내외 핵심 시장과 기술 동향을 엄선합니다. |
| Products headline | 하루의 중요한 순간을 채우는 세 가지 전문 리포트 |
| Products support | AI가 초안을 만들고 운영자 검수와 오너 승인을 거쳐 전달합니다. |
| Common cadence | 평일 발행 · 주말 및 대한민국 공휴일 미발행 |
| Review cue | AI 초안 생성 → 운영자 검수 → 오너 승인 후 발송 |
| Adult gate fail | 만 19세 미만은 가입할 수 없습니다. |
| No auto convert | 카드 등록만으로 유료 전환되지 않습니다. 체험 종료 전 직접 연장에 동의해야 합니다. |
| Soft bounce SMS intent | 브리핑 메일 전달에 일시 문제가 있습니다. 내 구독에서 수신 메일을 확인해 주세요. |

**Rejected portfolio copy (MUST NOT use as production):** `매일 아침…`, `최고의 아침`, `평일 아침 07:00 KST 배달`, absolute `검증된 정보` / `품질 보증` claims.

---

## 2. Landing & Introduction

**Entry:** Anonymous visitor

**Principle:** Explain the **customer experience** before internal product structure. A visitor MUST understand within a few seconds: what they receive (email briefing), what kind of service (AI draft + operator review + owner approval), and what to do next (14-day Full Set trial or pricing).

**MUST NOT** require understanding GENIE/KeeSuri architecture, pipeline jargon, Admin/operator concepts, backend, or detailed taxonomy before value is clear.

**Landing progression:**

```
Hero → Products & Services → product differentiation → pricing → 14-day trial model → review/trust → FAQ
```

Admin/operator/backend concepts **MUST NOT** appear in this customer journey.

### 2.1 Hero — visual direction (LOCKED)

Preferred visual language:

- very dark / near-black background
- large centered Korean value proposition
- high-contrast white typography
- restrained gold accent (emphasis + primary CTA only)
- strong typographic hierarchy; generous negative space; low visual noise
- subdued secondary CTA
- premium editorial / intelligence-report atmosphere

**Feel:** premium, editorial, calm, intelligence-oriented, immediate, easy to understand.

**MUST NOT feel:** SaaS-dashboard-heavy, crypto-like, generic AI futurism, noisy, consulting-corporate, stock-chart-heavy, feature-card-heavy above the fold.

Typography and message clarity are the primary Hero device.

### 2.2 Hero — information hierarchy (canonical)

| Order | Element | Canonical baseline |
|-------|---------|-------------------|
| 1 | Eyebrow | `AI BRIEFING × GLOBAL MARKET INTELLIGENCE` |
| 2 | Primary headline | `당신의 메일함으로` / `찾아오는 인사이트` (responsive wrap OK) |
| 3 | Supporting product sentence | `AI 지니와 키수리 글로벌·코리아가` / `국내외 핵심 시장과 기술 동향을 엄선합니다.` |
| 4 | Trial proposition | `14일간 3종 풀세트를 무료로 경험해 보세요.` |
| 5 | Primary CTA | `14일 무료 체험 신청하기` → Signup |
| 6 | Secondary CTA | `구독 요금제 보기` → Pricing section |
| 7 | Compact review/trust cue | `AI 초안 생성 → 운영자 검수 → 오너 승인 후 발송` |

Do **not** place detailed workflow explanation above the fold.

### 2.3 Hero — prohibited misleading cadence / scope

Portfolio Hero **MUST NOT** imply:

- all three products arrive in the morning
- all three arrive at the same time
- seven-day publication / weekend / ROK holiday publication

**MUST NOT** canonize: `매일 아침, 당신의 메일함으로 찾아오는 인사이트`

Approved headline remains time-agnostic: `당신의 메일함으로 찾아오는 인사이트`.

Campaign variants MAY be tested later only if factually compatible with cadence (§2.5–§2.7).

Portfolio support **MUST** represent **both** global and domestic scope. **MUST NOT** canonize global-only framing such as `전 세계 핵심 기술과 시장 동향` as the sole portfolio sentence.

### 2.4 Hero — review / trust language

Canonical concept: AI draft → operator review → owner approval → delivery.

Preferred: show the review chain, or `검수 후 발송`.

**MUST NOT** canonize: `품질 보증`, `완벽한 품질`, `정확성 보장`, `오류 없음`, `검증된 정보만 제공`, `수익 보장`.

Preserve: generation ≠ validation ≠ owner-review ≠ approval ≠ customer delivery ≠ customer receipt.

### 2.5 Products & Services

**Rejected headline:** `세 가지 전문 리포트로 만나는 최고의 아침`
**Canonical headline:** `하루의 중요한 순간을 채우는 세 가지 전문 리포트`

**Rejected support:** absolute `검증된 프리미엄 정보만` / “검증된 정보” certification claims
**Canonical support:** `AI가 초안을 만들고 운영자 검수와 오너 승인을 거쳐 전달합니다.`

Shared calendar note (once is enough): `평일 발행 · 주말 및 대한민국 공휴일 미발행`

| Product | Time / position label | Core positioning |
|---------|----------------------|------------------|
| 오늘의 지니 브리핑 | 장전 브리핑 · **06:30 KST** | 핵심 기술 트렌드와 비즈니스/시장 이슈를 하루 시작 전 빠르게 파악하는 브리핑 |
| 키수리 글로벌 | 글로벌 테크·시장 브리핑 · **12:30 KST** | 실리콘밸리와 글로벌 기술기업, 기술산업 및 시장 변화를 분석하는 글로벌 인텔리전스 리포트 |
| 키수리 코리아 | 국내 테크·정책 브리핑 · **18:30 KST** | 국내 IT 생태계, 스타트업, 정책, 규제, 산업 이슈를 정리하는 국내 브리핑 |

Exact descriptive prose MAY later be refined; **times and position distinctions are FIXED**.

Visual: three comparable dark cards, restrained borders, gold accent, short explanations, generous whitespace — **not** a feature matrix / architecture / ops dashboard.

### 2.6 Pricing cards — cadence and current prices

Prices remain Lifecycle VAT-inclusive amounts. Cadence labels use **발송** (not primary **배달**).

| Plan | Canonical timing line |
|------|----------------------|
| 오늘의 지니 (₩6,600) | `평일 06:30 KST 발송` |
| 키수리 글로벌 (₩9,900) | `평일 12:30 KST 발송` |
| 키수리 코리아 (₩6,600) | `평일 18:30 KST 발송` |
| 2종 선택 패키지 (₩11,000) | `선택한 두 브리핑의 발송 시각에 각각 전달` (combinations: 06:30+12:30 / 06:30+18:30 / 12:30+18:30). **MUST NOT** imply one combined email/time unless a future policy says so |
| 3종 풀세트 (₩16,500) | `06:30 / 12:30 / 18:30 KST에 각각 발송` (+ Full Set / 14-day trial eligibility cue; `2종에서 월 5,500원 추가`) |

**MUST NOT** reuse `평일 아침 07:00 KST 배달` (or any single generic morning time) across cards.

If mentioning one-email policy, prefer `수신 이메일 1개 지정` / `계정당 수신 이메일 1개` — **MUST NOT** use `단일 수신 이메일 보장` unless “보장” is separately approved.

Visual: five clear plans, **neutral at rest**. Emphasis **MUST** follow only customer hover, focus, touch, or explicit selection.

**Pricing hierarchy / ethics (HARD):**

- **MUST NOT:** `강력 추천`, `가장 인기`, `MOST POPULAR`, `BEST VALUE`, unsupported recommendation badges
- **MUST NOT:** forced or preselected paid plan on Landing pricing or D-3
- Pricing itself creates hierarchy; UX **MUST NOT** fabricate behavioral popularity evidence
- Value copy for Full Set: `2종에서 월 5,500원 추가` (or equivalent) — **MUST NOT** claim universal “둘 값에 셋” math
- Full Set **CURRENT** VAT-included price: **₩16,500** (**SUPERSEDES** historical ₩14,300)

No dense spreadsheet.

### 2.7 Terminology: 발송 vs 배달

Canonical operational/customer timing labels: **발송**.

Marketing may say `메일함으로 찾아오는`, but lifecycle/cadence chips use `발송`.

Preserve: send / provider accepted ≠ customer receipt.

### 2.8 Landing entry / actions summary

**Primary:** `14일 무료 체험 신청하기` → Signup
**Secondary:** `구독 요금제 보기` → Pricing

**MUST:** weekday + ROK holiday non-publish; review chain; prices from Lifecycle; publication times 06:30 / 12:30 / 18:30.
**MUST NOT:** auto Naver publish; 365-day; investment advice; KRW 29,900 legacy; morning-portfolio framing; Admin links.

---

## 3. Login

**Entry:** Returning customer

**State:** Email or mobile challenge; `[ ] 로그인 유지` default OFF

**Primary:** Send login link/OTP → verify → enter app

**Secondary:** Account recovery

**Validation:** Registered channel only

**Error:** `LOGIN_CHALLENGE_INVALID`, rate limit

**Success:** Session created per Auth lifetimes

**MUST NOT:** Password field.

---

## 4. Signup — Adult identity verification

**Entry:** New customer from Landing

**State:** Mobile IDV UI (vendor widget)

**Primary:** Complete IDV

**Error:** `AGE_NOT_ELIGIBLE` → terminate; no account. `IDV_FAILED` → retry/exit. `IDENTITY_ALREADY_REGISTERED` → login/recovery

**Success:** Proceed to account email capture

**Confirmation:** None (gate only)

---

## 5. Signup — Account email & channel registration

**Entry:** Adult verified

**State:** Collect `account_email`; confirm mobile from IDV as registered mobile

**Primary:** Verify email ownership (transactional challenge)

**Error:** Email already used on another active account → support/login

**Success:** `delivery_email` defaults to `account_email`; proceed to payment-method registration

**MUST NOT:** Ask for password.

---

## 6. Signup — Payment method registration

**Entry:** Verified account shell (no paid plan selected)

**State:** PG widget; own-name card required; no charge during trial

**Primary:** Register billing key

**Error:** Verification fail; own-name mismatch (vendor)

**Success:** Trial starts → Trial confirmation

**MUST:** “카드 등록 ≠ 유료 결제 동의”

**MUST NOT:** Require paid-plan selection before card registration

**Irreversible:** Token stored at provider; service stores billing key metadata only.

---

## 7. Signup — Trial confirmation (stage 4 of 4)

Canonical signup has **exactly FOUR** stages:

1. 본인인증 (adult IDV)
2. 계정 생성 (account + email verify)
3. 결제 수단 등록 (own-name payment method)
4. 무료체험 시작 / 가입 확인

**Entry:** Trial created (`trialing`)

**State:** Show:

- 14 calendar days; Full Set
- trial end date
- no same-day briefing; first briefing next eligible publication day
- D-3 renewal invitation will ask them to choose a paid plan
- no automatic paid conversion; no response → no charge → trial ends; token destroyed

**MUST NOT** show:

- selected future paid plan
- future paid plan price
- requirement to choose a paid plan before trial

**Primary:** Go to My Page

**Secondary:** Support contact

---

## 8. D-3 renewal / initial paid-plan selection

**Entry:** Email / SMS / My Page CTA within D-3 window (`renewal_pending`)

**Meaning:** “세 가지 브리핑을 모두 체험했습니다. 유료로 계속 받을 플랜을 선택하세요.”
**MUST NOT** mean: “가입 시 선택한 플랜을 확인하세요.”

### 8.1 Deep-link / login

| Auth state | Behavior |
|------------|----------|
| Logged out | Renewal link → passwordless login → **return directly to paid-plan selection** (not generic My Page first) |
| Logged in | Renewal link → **paid-plan selection** directly |

Still inside the **three-part customer IA** (Landing / Signup & Payment / My Page). **MUST NOT** create a fourth customer top-level category or route D-3 into Admin.

### 8.2 Conversion steps

1. Show five paid plans (VAT-inclusive catalog prices; Full Set **₩16,500**); `package_two` requires exactly two products
2. Customer selects one plan (**opens with zero selection**)
3. Plan confirmation reflecting chosen plan + frozen price
4. Mobile step-up reauthentication
5. Explicit paid-conversion confirmation → `conversion_scheduled` + pending conversion snapshot

**Secondary:** `체험만 종료` / dismiss (no plan; no consent)

**Error:** Step-up failure; no verified delivery email → block convert until fixed; invalid `package_two` selection

**Success copy:** “체험 종료일에 선택한 플랜으로 첫 결제가 진행됩니다.”

**MUST NOT:** Charge at D-3. **MUST NOT:** Auto-extend trial if notification failed (show My Page renewal CTA instead).
**MUST NOT:** recommendation badges, static gold “recommended” emphasis before selection, or preselected Full Set.
Continuation CTA **MUST** remain disabled until an explicit valid plan selection exists.

If customer does nothing: no plan, no consent, no charge → `trial_expired`.

---

## 9. Paid conversion result

| Outcome | UX |
|---------|----|
| Charge success | `active` on selected plan; receipt transactional email; My Page shows next billing |
| Charge fail | Never-paid; delivery OFF; “카드 교체 후 다시 결제” explicit retry; no grace |

Browser redirect alone **MUST NOT** show success until server confirms.

---

## 10. My Page

**Entry:** Authenticated customer

**Core blocks (always small):**

- Status badge (`trialing` / `renewal_pending` / `conversion_scheduled` / `active` / …)
- Delivery email (+ change)
- Payment method (masked)
- Support email
- Actions: cancel, withdraw, sessions; plan change only when `active`

### 10.1 Trial before D-3 (`trialing`)

**MUST** show: Full Set free trial; trial start; trial end; delivery email; payment method; trial status; cancel/withdraw as applicable

**MUST NOT** show: selected future paid plan; future paid price

### 10.2 During D-3 (`renewal_pending`)

Show renewal CTA → paid-plan selection (§8)

### 10.3 After conversion confirmation (`conversion_scheduled`)

Show: conversion_scheduled; selected paid plan; selected products if `package_two`; first charge date; agreed pending price; view pending conversion selection

**MUST NOT** label customer as paid/`active` before verified payment success

**MUST NOT:** Briefing history, editor, regen, analytics, ops admin.

---

## 11. Plan change (active paid only)

**Entry:** `active` (distinct from D-3 initial plan selection)

**State:** Select new plan; copy “다음 결제일부터 적용 · 이번 기간 환불/추가결제 없음”

**Primary:** Confirm with step-up

**Success:** `pending_plan_change` until next successful renewal

**Error:** Invalid package_two selection; step-up fail

---

## 12. Card replacement

**Entry:** My Page payment section

**Flow UX:** Add new → verify → set default → allow delete old

**Error:** `PAYMENT_METHOD_REPLACEMENT_REQUIRED` if attempting to delete sole method while obligation exists

**Step-up:** Financial (mobile OTP)

---

## 13. Cancellation

### Trial

**Primary:** Confirm immediate end → delivery OFF → token destroy

### Paid

**Primary:** Schedule cancel at period end → continue briefings until then → MAY revoke

**Copy:** “해지 ≠ 즉시 환불. 이번 결제 기간까지 이용할 수 있습니다.”

---

## 14. Refund inquiry

**Entry:** Support / My Page link

**State:** Form for duplicate charge / first-period unused / defect review

**MUST NOT:** Promise automatic prorated refund calculator

**Success:** Ticket/review status

---

## 15. Membership withdrawal

**Step-up:** Full IDV

**Trial:** Immediate withdraw flow with strong warning

**Paid:** Schedule for period end; guarantee no next charge; MAY revoke before effective

**Copy:** “탈퇴 후에는 계정을 복구하지 않습니다. 재가입 시 새로 인증합니다.”

---

## 16. Resubscription

**Entry:** `canceled` (fully ended) or withdrawn-return after new IDV account

**State:** Current catalog prices; new card; new charge; new anchor

**Success:** Delivery from next eligible publication day (not same-day)

---

## 17. Delivery-email change

**Entry:** My Page

**State:** Enter new email → ownership verify → becomes active after verify

**Copy:** “변경은 다음 발송부터 적용됩니다. 같은 호를 두 주소로 보내지 않습니다.”

**Step-up:** Per Auth (email change risk tier)

---

## 18. Bounce recovery

| Event | Customer UX |
|-------|-------------|
| Soft Bounce | In-app notice + SMS; optional “수신함/스팸 확인” guidance; no forced email change |
| Hard Bounce | Delivery suppressed; SMS; **required** replace+verify email CTA |
| Recovery | Next snapshot resumes; no bulk backfill of missed issues |

---

## 19. Payment failure UX

| Context | UX |
|---------|----|
| Never-paid conversion fail | Delivery OFF; replace card; explicit retry |
| `past_due` | Banner: grace days remaining; update card; retain entitlement |
| `suspended` | Delivery OFF; recovery payment required |

---

## 20. Session / device management

**Entry:** My Page → 보안

**State:** List sessions; revoke one; logout all (step-up)

**Show:** Approximate device/browser label + last seen — minimal

---

## 21. Private Operator / Owner-Review surface (NOT customer IA)

**Customer navigation entry:** NONE
**Landing / Login / Signup / My Page entry:** NONE

Customer screen inventory is limited to Landing, Login/auth entry, Signup, My Page, and related customer modals/states. Admin is **not** a customer top-level screen.

### 21.1 Normal operator entry

```
owner-review email
→ signed review deep link
→ server-side token validation
→ exact review/run context
```

**MUST** deep-link to the specific briefing/run — **MUST NOT** dump the owner on a generic Admin homepage to search manually.

### 21.2 Operator UX (separate mock / production console)

May include: run / owner-review / customer-delivery / image status; `review_required` / `failed`; dangerous-action confirmation; bounce / `CUSTOMER_CONTACT_FAILURE` / refund review / audit.

**MUST** separate owner-review from customer delivery visually.
**MUST NOT** imply a button alone is production authority without confirm + operator auth.
**MUST NOT** treat signed review link open as approval, or approval as customer send, or send as receipt.

### 21.3 Prototype reconciliation note (documentation only)

Next prototype patch: customer pages (`index.html`, `login.html`, `signup.html`, `mypage.html`) **MUST** contain **zero** links to `admin.html`. Operator mock may remain as a separate file only if never linked from customer navigation and never assumed as production `/admin.html`.

---

## 22. Error inventory (customer-visible)

| Code | Example copy |
|------|----------------|
| `AGE_NOT_ELIGIBLE` | 만 19세 미만은 이용할 수 없습니다. |
| `PAYMENT_METHOD_REPLACEMENT_REQUIRED` | 새 카드를 먼저 등록한 뒤 기존 카드를 삭제하세요. |
| `STEP_UP_REQUIRED` | 보안을 위해 다시 인증해 주세요. |
| `DELIVERY_EMAIL_UNVERIFIED` | 결제·발송 전에 수신 이메일 인증이 필요합니다. |
| `HARD_BOUNCE_SUPPRESSED` | 수신 이메일 전달이 거부되었습니다. 새 주소를 인증해 주세요. |
| `CONVERSION_NOT_CONFIRMED` | 유료 전환 동의가 없습니다. 체험 종료 후 결제되지 않습니다. |

---

## 23. Briefing Preview — composition preservation (LOCKED)

**APPROVED PRINCIPLE:** Preserve the source composition before maximizing container fill.

Preview images are intentional persona/visual compositions — **not** generic decorative banner crops.

| MUST | MUST NOT |
|------|----------|
| Prefer natural source aspect ratios | Force vertically oriented sources into shallow panoramic banner containers |
| Prefer vertical scrolling over destructive cropping | Crop faces merely to equalize card height |
| Allow different rendered heights | Sacrifice forehead/chin/body/context to fill width |
| Use `object-fit: contain` / negative space when needed | Distort images |
| Treat equal-height imagery as **non-invariant** | Treat equal-height `cover` crop as mandatory |

**SUPERSEDES** prior shallow fixed-height `cover` presentation where it conflicts with composition preservation.

### 23.1 Current source geometry (implementation evidence — not permanent product tokens)

| Asset | Current pixels | Ratio |
|-------|----------------|-------|
| Today | 832 × 1248 | 2:3 portrait |
| Global | 896 × 1152 | 7:9 portrait |
| Korea | 896 × 1152 | 7:9 portrait |

Assets MAY change; the durable rule is composition preservation.

### 23.2 Mobile classification

A wide screenshot from an iPhone in **landscape** is still **MOBILE**.

**MUST NOT** infer desktop/tablet regression from width alone. Consider device context, orientation, short visual viewport, browser chrome, touch, `visualViewport`, and mobile Safari viewport behavior.

### 23.3 Mobile landscape Hero

In short mobile landscape viewports, Hero **MUST NOT** clip content merely to fit one landscape screen.

Accessible via scroll if needed: eyebrow, full H1, supporting copy, CTAs, trust/review line.
Vertical page scrolling is acceptable; clipping is not. Avoid fixed viewport-height assumptions that sacrifice content.

### 23.4 Preview QA evidence status (2026-08-11)

| Surface | Status |
|---------|--------|
| Chromium mobile portrait Preview (e.g. 393×852 QA) | **PASS** (full-composition / contain direction) |
| Actual iPhone Safari portrait Preview final confirmation | **PENDING** — **MUST NOT** claim actual-device portrait PASS |
| Chromium mobile landscape Preview | **PASS** |
| Actual iPhone landscape Preview composition | **ACCEPTED** (owner visual confirmation after repair) |
| Rejected prior landscape behavior | ~722×~220 `cover` crop → forehead-only / chin-neck floating-head failure; `object-position` alone was not the root fix |

---

## 24. FAQ — functional disclosure contract

All FAQ questions **MUST**:

- use native `button` semantics
- remain visible when closed
- expose `aria-expanded="false"` initially
- have `aria-controls` pointing to the matching answer
- open the matching answer on activation → `aria-expanded="true"`
- close on second activation → `aria-expanded="false"`
- work with mouse, touch, Enter, and Space

Independent disclosure is acceptable unless later product policy changes it.
FAQ **text/content** is separate content policy — functional repair **MUST NOT** silently rewrite FAQ copy.

| Evidence | Status |
|----------|--------|
| Chromium FAQ functional QA (3/3) | **PASS** |
| Actual iPhone Safari FAQ post-repair confirmation | **PENDING** — owner confirmed OLD broken; do **not** claim real-iPhone FAQ PASS yet |

---

## 25. Raw Markdown leakage prohibition

Literal Markdown heading tokens such as visible `###`, `##`, `#` **MUST NEVER** appear in customer UI when semantic HTML headings are used.

Prior Preview defect: nine literal `###` strings. Repaired target: visible `###` count = **0**.
This is a presentation/output defect, not branding. Future Preview/sample content **MUST** pass a raw-Markdown leakage check.

---

## 26. Prototype / QA diagnostic isolation

QA/debug indicators **MUST NOT** dominate or overlap normal customer showcase (nav, hamburger, Hero, short landscape viewports).

| Mode | Behavior |
|------|----------|
| Normal customer showcase | Diagnostic ribbon (e.g. large diagonal `MOCK PROTOTYPE`) **hidden** |
| Explicit debug mode | Ribbon **MAY** be shown |

Observed implementation mechanism: `body.debug-mode` (not elevated to permanent API contract).
Durable rule: diagnostic UI isolated from normal customer presentation.
This remains **prototype** work — prototype QA ≠ production readiness.

---

## 27. Design direction preservation / critique authority

Recent repairs are **NOT** authorization for a full redesign.

**Still preserved:** dark editorial direction; navy/black foundation; restrained gold; GENIE × KeeSuri branding; current Hero/Products/Preview/pricing structures; pricing neutral-at-rest; small My Page.

Claude Design Round 1:

| Item | Status |
|------|--------|
| Mode | CRITIQUE ONLY |
| Diagnosis | `PRODUCT_COMMUNICATION_RETHINK_REQUIRED` |
| Accepted at strategic diagnosis level | YES |
| Automatic implementation / redesign authority | **NO** |

Critique findings **MUST** be triaged individually as accepted / partially accepted / rejected / deferred.
Any major visual restructuring requires **explicit owner approval**.

---

## 28. Related documents

Domain numbers and states: Lifecycle, Auth, Delivery.
API shapes: `FRONTEND_API_CONTRACT_v1.md`.
Dated stabilization evidence: `CUSTOMER_WEB_STABILIZATION_STATUS_2026_08_11.md`.
