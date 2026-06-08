# Kee-Suri Premium Briefing — Design Handoff

**For:** Cursor implementation on `keysuri_contract_preview_renderer.py` (contract-preview surface only)
**Surface:** `output/keysuri_preview/html_test/` premium private briefing preview + email-ready HTML
**Scope guardrail:** Redesign the preview/email surface only. No backend, no scheduler, no email send, no image API, no owner-review renderer changes.
**Persona:** 테크 비서 키수리 — private tech secretary briefing the owner as **주인님**. Not an anchor, not a newsletter, not an RSS digest, not a dev audit page.

---

## 0. Reading order for the implementer

1. §1 Diagnosis — what is wrong and why.
2. §2 New visual structure — the section-by-section skeleton.
3. §5 CSS spec + §6 component spec — the actual build.
4. §4 Image strategy — the one thing most likely to break.
5. §8 Cursor handoff + §9 acceptance — definition of done.

This handoff is consistent with `KEYSURI_TITLE_AND_BODY_SECTION_CONTRACT.md`, `KEYSURI_CONTRACT_PREVIEW_RENDERER_DESIGN.md`, `KEYSURI_IMAGE_PROFILE_LOCK.md`, and the existing read-only validator `keysuri_html_preview_validation.py`. Where this handoff and the contract disagree, **the contract wins** — locked section labels and section order are not changed here.

---

## 1. Diagnosis of the current HTML

### 1.1 Why it feels cheap (not premium)

The single biggest failure is a **palette collision**. The shell and hero are dark navy (`#0b1220`→`#0f172a`), but every content card flips to cream/white (`.section-card { background:#f8f6f0 }`, `.briefing-card { background:#fff }`). The eye reads "premium dark header glued onto a plain white document." That white-document interior is exactly what makes it look like generated output or a Google-Doc export rather than a private briefing.

Specific cheapness drivers:

- **No type scale discipline.** Hero title `1.65rem`, section headings `1.15rem`, card headlines `1.05rem` — everything is bunched between 1.0–1.65rem. There is no confident large display number, no quiet small caps, no rhythm. Premium = bigger contrast between the loud and the quiet.
- **TOP 5 cards are uniform and flat.** Same white box, same `0 2px 8px` shadow, rank as a tiny blue pill in the corner. Five identical rectangles read as a list, not a ranked signal board.
- **The owner's value is buried.** "주인님 관점" is a pale blue left-border block (`#eff6ff` / `border-left:3px`) that looks *less* important than the headline. The most valuable line in the product is styled like a footnote.
- **"키수리 판단" is a generic navy pill.** `.judgment-badge { background:#1e3a5f }` is the same color family as everything else — it reads as a tag, not a private judgment signal.
- **Borders and dividers do the work that spacing should do.** `border-bottom:2px solid #cbd5e1` under headings, `1px solid #d1d5db` around cards — hairline boxes everywhere. Premium layouts lean on whitespace and elevation, not boxes.

### 1.2 Why the image does not reliably show

```html
<img src="../image_canary/keysuri_global_canary_20260605_105936_mirai_on_watermarked.jpg" .../>
```

- It is a **relative path that escapes the file's own folder** (`../image_canary/...`). The preview is written to `output/keysuri_preview/html_test/`, so `../image_canary/` resolves to `output/keysuri_preview/image_canary/` — fine only if the file is opened in place and the asset exists at exactly that sibling path. Move the HTML, attach it, or open it from a different cwd and the image 404s.
- **It will never render in email.** Email clients do not resolve local relative file paths. There is no `https://` host and no CID, so in Gmail/Naver/Apple Mail this is a broken-image icon.
- There is **no fallback** — if the image fails, the hero collapses to an empty bordered box with no identity, no text, no graceful degradation.

The contract (§10) already requires the briefing to "work if images fail to load." The current hero violates that.

### 1.3 Why the email subject fails

The reference subject `[KEYSURI test] Kee-Suri Global Tech...` fails on every axis in contract §4:

- `[KEYSURI test]` is an internal/debug tag leaking to the recipient — looks like staging output.
- It is English-led for a Korean-first product.
- It carries **no structural movement, no direction, no currentness** — it is a label, not a signal. Contract §4.3 explicitly forbids generic-digest shapes.
- It creates zero expectation before opening.

### 1.4 What makes it feel like developer output

- Visible internal-ish blocks at the bottom: `Preview metadata`, `Operation metadata (server-rendered only)`, `Contract compliance checklist`, `Validation result` — all rendered in plain English with raw keys (`program_id`, `mode`, `status`, `slot`). These are *correct to exist* for owner review, but they are styled at the same visual weight as content and sit in plain sight.
- English component headings inside Korean copy: `Review confirmation`, `Validation result`, `Preview metadata`.
- The `validation-box` literally prints `validation_status: PASS`, `top5_sources: PASS` … — that is a CI panel, not a briefing.

### 1.5 What must change first (priority order)

1. **Image reliability** (§4) — without a visible hero the whole "premium" claim dies. Switch the preview to a self-contained embed and make the renderer CID-ready for email.
2. **Palette unification** (§5) — one cohesive dark executive palette; kill the white document cards.
3. **Hierarchy of 주인님 관점 + 키수리 판단** (§6) — promote the owner panel, make the judgment a real signal badge.
4. **Demote operational metadata** (§6 CompactAuditBox) — collapse into one muted, secondary, `<details>`-style block at the very bottom.
5. **Korean subject/preheader** (§3) — replace the test subject.

> ⚠️ **Pre-existing gate failure to fix while you are in here:** the current closing reads `...도움이 되기를 바랍니다. 추가 문의사항은 언제든 말씀해주십시오.` Both `도움이 되기를 바랍니다` and `추가 문의사항은 언제든` are in `GENERIC_CLOSING_PHRASES` in `keysuri_contract_preview_quality.py`. Today's HTML fails `validate_contract_preview_visible_body`. The redesigned closing copy in §7 fixes this.

---

## 2. New visual structure (section-by-section)

Order is **locked by contract** (`KEYSURI_CONTRACT_PREVIEW_RENDERER_DESIGN.md` §5). Do not reorder; only restyle. Global 12:30 shown; Korea 18:30 adds bottom-shot + warm close per §5.1.

```
┌─ A. Subject + preheader ─────────── (email envelope; not in <body>) ──┐
│                                                                       │
│  B. PremiumHero                                                       │
│     · OwnerReviewBadge  (운영자 검수용 · 발송 전)                       │
│     · identity line:  테크 비서 키수리                                  │
│     · hero title + subtitle                                           │
│     · hero image (top-shot) with graceful fallback                    │
│                                                                       │
│  C. Opening memo  (signal-first, personal, 3 sentences)              │
│                                                                       │
│  D. SignalSummary  (today's read in one strip: 3–5 signal chips)     │
│                                                                       │
│  E. TOP 5 briefing cards                                              │
│     each: rank · headline · 무슨 일이 있었나 · 왜 지금 중요한가         │
│            · ★OwnerAnglePanel(주인님 관점) · KeysuriJudgmentBadge(키수리 판단) │
│            · NextWatchCue(다음 확인 포인트) · 출처                      │
│                                                                       │
│  F. DeepDiveMemo  (키수리의 딥-다이브 — executive memo + 1/2/3 layers) │
│                                                                       │
│  G. OneLineCheckpoint  (원-라인 체크포인트 — single decisive cue)      │
│                                                                       │
│  [Korea 18:30 only] bottom-shot → ReviewConfirm → 따뜻한 마무리]      │
│                                                                       │
│  H. SourceList  (마무리 및 출처 리스트 — provenance, visually separated)│
│                                                                       │
│  ── thin divider ──                                                   │
│  I. CompactAuditBox  (collapsed; preview + operation + validation)   │
│  J. RightsFooter  (MirAI:ON)                                          │
└───────────────────────────────────────────────────────────────────┘
```

Note the contract order puts the **rights footer after 마무리 및 출처 리스트 and before operation metadata**. Keep that DOM order (RightsFooter sits inside the footer cluster *above* operation metadata in source order, per renderer `footer` block). Visual grouping in §6 keeps audit muted regardless.

---

## 3. Email subject + preheader

### 3.1 Subjects — 12 (premium, private-briefing, no clickbait)

Built on contract §4.2 pattern families (A structural movement, B control shift, C side-effect, D quiet premium). All Korean-first; `키수리` used only where it earns its place.

| # | Subject | Pattern |
|---|---------|---------|
| 1 | `[키수리 브리핑] 빅테크의 AI 내재화가 '일의 구조'를 바꾸고 있습니다` | A |
| 2 | `[키수리] 오늘의 테크 신호 — 통제권이 모델에서 인프라로 이동합니다` | B |
| 3 | `[키수리 브리핑] AI 에이전트 확산 이후, 개발 조직에 생긴 압력` | C |
| 4 | `AI가 제품 속으로 들어온 날, 주인님이 먼저 봐야 할 신호` | D |
| 5 | `[키수리 브리핑] 거대 AI 기업의 '실용화' 전환 — 오늘 무엇이 움직였나` | A |
| 6 | `[키수리] 오늘의 구조 변화: 누가 워크플로의 통제권을 가져가는가` | B |
| 7 | `[키수리 브리핑] 검색·에이전트·기억 — 세 신호가 가리키는 한 방향` | A |
| 8 | `빅테크 발표 이후, 진입 장벽이 어디서 높아지는가` | C |
| 9 | `[키수리 브리핑] 오늘 테크 시장에서 조용히 이동한 권한` | D |
| 10 | `[키수리] 연구를 넘어 운영으로 — AI가 인프라가 된 날의 신호` | A |
| 11 | `AI 내재화 경쟁, 오늘 읽어야 할 단 하나의 구조` | D |
| 12 | `[키수리 브리핑] 같은 날 움직인 구글과 OpenAI — 방향은 하나입니다` | A |

**Shorter mobile-friendly (≤ ~24 chars before truncation):**

| # | Subject |
|---|---------|
| M1 | `[키수리] 오늘의 테크 신호, 한 줄로` |
| M2 | `[키수리] 통제권이 이동하고 있습니다` |
| M3 | `오늘 먼저 봐야 할 테크 신호` |

### 3.2 Preheaders — 12 (pair by index with subjects above)

Preheader = the gray preview text after the subject. Keep ≤ ~60 Korean chars; front-load the signal.

| # | Preheader |
|---|-----------|
| 1 | `구글·OpenAI가 같은 방향으로 움직였습니다. 오늘의 구조부터 정리했습니다.` |
| 2 | `모델 경쟁이 아니라, 인프라·라우팅 통제권 싸움으로 넘어가는 중입니다.` |
| 3 | `에이전트가 개발을 재편하면, 다음 순서는 조직과 비용입니다.` |
| 4 | `발표 5건을 신호 5개로 압축했습니다. 주인님 관점까지 함께 올립니다.` |
| 5 | `'할 수 있다'에서 '운영에 넣는다'로 — 무게중심이 옮겨갑니다.` |
| 6 | `자동화의 통제권이 누구에게 쌓이는지, 오늘 신호로 짚었습니다.` |
| 7 | `검색·에이전트·기억. 따로 보면 뉴스, 합치면 구조 변화입니다.` |
| 8 | `진입 장벽은 모델 품질이 아니라 인프라·정책 스택에서 올라갑니다.` |
| 9 | `헤드라인이 아니라, 오늘 조용히 이동한 권한을 봅니다.` |
| 10 | `AI가 연구실을 떠나 인프라가 된 신호를 한자리에 모았습니다.` |
| 11 | `오늘 다섯 건 중, 주인님이 꼭 봐야 할 하나의 구조를 짚었습니다.` |
| 12 | `같은 날, 같은 방향. 두 회사의 움직임이 말하는 한 가지.` |

**Mobile preheaders (M1–M3):**

- M1 → `발표 5건, 신호 5개. 핵심은 한 줄에 담았습니다.`
- M2 → `오늘 권한이 어디로 가는지 짚었습니다.`
- M3 → `구글·OpenAI가 같은 방향으로 움직였습니다.`

### 3.3 Implementation note

Add these as **constants** in the renderer, not free generation, so they are reviewable and gate-able:

```python
# keysuri_contract_preview_renderer.py
SUBJECT_LINES_GLOBAL: tuple[str, ...] = (...)   # the 12 above
SUBJECT_LINES_GLOBAL_MOBILE: tuple[str, ...] = (...)
PREHEADERS_GLOBAL: tuple[str, ...] = (...)
DEFAULT_SUBJECT_INDEX = 0   # owner picks; default to #1
```

Render the chosen subject into `<title>` and emit the preheader as the **first DOM node in `<body>`** (hidden span, §5.6). Forbidden in subject/preheader: `[KEYSURI test]`, `오늘 브리핑`, `도움이 되셨기를`, investment/urgency claims.

---

## 4. Hero image strategy

**Do not call any image API.** Use the existing local Kee-Suri canary asset. The accepted Global production reference per `KEYSURI_IMAGE_PROFILE_LOCK.md` §7 is `keysuri_global_canary_20260604_221233.jpg`; the current HTML points at a `..._mirai_on_watermarked.jpg` variant — use whichever is the overlay-applied, owner-accepted file. The watermark must already be **pixel-baked** (`MirAI:ON`), per profile lock §9.1 — the renderer does not add it.

### 4.A Local browser preview

**Problem:** `../image_canary/...` is fragile. **Fix: self-contained base64 data-URI embed.** The render script reads the approved JPG, base64-encodes it, and inlines it:

```python
import base64, pathlib
def _data_uri(path: str) -> str:
    p = pathlib.Path(path)
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"
```

```html
<img src="data:image/jpeg;base64,…" alt="테크 비서 키수리 — 프라이빗 테크 브리핑" class="top-shot-hero" loading="eager">
```

This makes the preview open correctly from *any* path or cwd, survives being moved/attached, and needs no host. (Trade-off: ~30–40% file-size inflation; fine for a preview.) Keep `id="top-shot-image"` and `class="top-shot-hero"` — the quality gate (`keysuri_contract_preview_quality.py`) hard-requires both.

Fallback if the asset file is missing at render time: emit the existing `#top-shot-placeholder` block, but styled as a branded gradient panel (§6 PremiumHero) carrying the identity text — never a bare empty box.

### 4.B Email send preview (when wiring is built — not now)

Same HTML, but the `<img src>` becomes a **CID reference**: `src="cid:keysuri_topshot_global_20260608"`. The renderer should already emit this shape behind a mode flag so the future send step is drop-in.

### 4.C Production email — recommendation

**Use CID (embedded, `multipart/related`)** as the primary path; hosted HTTPS as fallback only.

| Option | Verdict | Why |
|--------|---------|-----|
| **CID embedded** | ✅ Primary | No external host, no proxy image-blocking, no open-tracking leakage, renders offline. Best privacy fit for a *private* secretary. Naver/Daum/Gmail all support `cid:` in `multipart/related`. |
| Hosted HTTPS | ◻ Fallback | Needs a CDN/host (not wired); some clients block remote images by default → broken until "load images" clicked. |
| Attachment-only | ✗ Avoid | Image won't appear inline in the body; reads as a file dump. |

**Filename / CID convention:**
```
file:    keysuri_<program>_topshot_<YYYYMMDD>_mirai_on.jpg
cid:     keysuri_topshot_<program>_<YYYYMMDD>        e.g. cid:keysuri_topshot_global_20260608
```

**Alt text:** `테크 비서 키수리 — 프라이빗 테크 브리핑` (identity + genre; not "image" or a filename).

**Fallback if image fails:** the hero container itself carries the dark gradient + identity line + title in real text, so a missing image degrades to a clean branded header, not a hole. Add a `bgcolor` and min-height on the hero so the layout never collapses.

**Placement / crop / size:**

- **Full-width hero**, directly under the badge+title, above the opening memo. (Not a side portrait — the accepted canary is a centered premium portrait; side-cropping risks clipping the face, which profile-lock §9 forbids.)
- **Aspect ratio: 16:9 letterbox crop (≈ 1.91:1 acceptable)** with `object-fit: cover; object-position: center 28%` so the face/upper body sits in frame and the watermark safe-area (lower-right) is preserved.
- **Max display height ≈ 320px desktop / ≈ 200px mobile.** A full-bleed portrait at natural ratio eats the entire first screen and pushes the signal below the fold; letterboxing keeps the opening memo visible.
- Rounded container (`border-radius:14px`), subtle inner border, no heavy drop shadow on the image itself.

---

## 5. Premium HTML/CSS design spec

Single `<style>` block in `<head>` (contract: no external CSS, no remote webfont). Use a CSS-variable token layer for the browser/preview surface; provide inline + table fallbacks for email (§5.5).

### 5.1 Color tokens (dark executive palette — one cohesive system)

```css
:root{
  /* surfaces */
  --ks-bg:        #0a0f1a;   /* page */
  --ks-surface:   #111a2b;   /* primary card */
  --ks-surface-2: #16223a;   /* nested / source chip */
  --ks-hero-1:    #1b3050;   /* hero gradient top */
  --ks-hero-2:    #0c1322;   /* hero gradient bottom */
  /* lines */
  --ks-line:      rgba(148,163,184,0.14);
  --ks-line-strong: rgba(148,163,184,0.26);
  /* text */
  --ks-text:      #eaf0fa;   /* primary */
  --ks-text-dim:  #aab6cc;   /* secondary */
  --ks-text-mute: #6f7d96;   /* tertiary / meta */
  /* accents */
  --ks-gold:      #c8a96a;   /* PRIVATE signal — owner panel, judgment, rank */
  --ks-gold-soft: rgba(200,169,106,0.12);
  --ks-blue:      #5f8fd6;   /* structural accent — links, layer numbers */
  --ks-blue-soft: rgba(95,143,214,0.12);
  /* status */
  --ks-warn:      #d9a441;   /* 추가 확인 필요 */
}
```

Principle: **gold = private/owner/judgment (rare, high-value); blue = structure/navigation; everything else is the navy-charcoal scale.** No cream, no white card backgrounds anywhere in the body.

### 5.2 Spacing + radius + type tokens

```css
:root{
  --sp-1:4px; --sp-2:8px; --sp-3:12px; --sp-4:16px; --sp-5:24px; --sp-6:32px; --sp-7:48px;
  --r-sm:8px; --r-md:12px; --r-lg:16px; --r-pill:999px;
  --shadow-card: 0 10px 30px rgba(0,0,0,0.35);
  --shadow-soft: 0 4px 14px rgba(0,0,0,0.25);
}
```

Type scale (confident contrast — fix for the bunched scale):

| Role | Size / weight | Token use |
|------|---------------|-----------|
| Hero title | `clamp(1.6rem, 4.5vw, 2.1rem)` / 700, `letter-spacing:-0.01em` | `--ks-text` |
| Section heading | `1.05rem` / 700, small-caps feel via `letter-spacing:0.04em`, uppercase off | `--ks-text` w/ gold tick |
| Card rank numeral | `1.5rem` / 800, tabular | `--ks-gold` |
| Card headline | `1.12rem` / 700, line-height 1.4 | `--ks-text` |
| Block label (무슨 일…) | `0.74rem` / 700, `letter-spacing:0.06em`, uppercase-style | `--ks-text-mute` |
| Body | `0.95rem` / 400, line-height 1.7 | `--ks-text-dim` |
| Meta / audit | `0.72rem` / 400 | `--ks-text-mute` |

Font stack (system Korean, no webfont): `"Apple SD Gothic Neo","Pretendard","Malgun Gothic","Noto Sans KR",sans-serif`.

### 5.3 Card styles (replace white cards)

```css
.section-card{
  background:var(--ks-surface);
  color:var(--ks-text-dim);
  border:1px solid var(--ks-line);
  border-radius:var(--r-lg);
  padding:var(--sp-5);
  margin-bottom:var(--sp-5);
  box-shadow:var(--shadow-card);
}
.section-heading{
  display:flex; align-items:center; gap:var(--sp-2);
  margin:0 0 var(--sp-4);
  font-size:1.05rem; font-weight:700; letter-spacing:0.03em;
  color:var(--ks-text); border:0; padding:0;
}
.section-heading::before{                 /* gold tick instead of underline */
  content:""; width:3px; height:1.05em; border-radius:2px; background:var(--ks-gold);
}
.briefing-card{
  position:relative;
  background:linear-gradient(180deg, var(--ks-surface) 0%, #0f1828 100%);
  border:1px solid var(--ks-line);
  border-radius:var(--r-md);
  padding:var(--sp-5) var(--sp-4) var(--sp-4);
  margin-bottom:var(--sp-4);
  box-shadow:var(--shadow-soft);
}
.briefing-card:hover{ border-color:var(--ks-line-strong); } /* browser only */
```

### 5.4 Link / badge styles

```css
.chip-url, a{ color:var(--ks-blue); text-decoration:none; word-break:break-all; }
.chip-url:hover{ text-decoration:underline; }
/* rank as large gold numeral, not a corner pill */
.card-rank{ position:static; font-size:1.5rem; font-weight:800; color:var(--ks-gold);
  line-height:1; margin-bottom:var(--sp-2); }
```

No CTA buttons in this surface (it is a briefing, not a marketing email). Links are source URLs only.

### 5.5 Mobile responsiveness

```css
.briefing-shell{ max-width:680px; margin:0 auto; padding:var(--sp-5) var(--sp-4) var(--sp-7); }
@media (max-width:600px){
  .briefing-shell{ padding:var(--sp-4) var(--sp-3) var(--sp-6); }
  .section-card{ padding:var(--sp-4); border-radius:var(--r-md); }
  .top-shot-hero{ max-height:200px; }
  .judgment-row{ flex-direction:column; }   /* badge above text */
}
```

Deep-dive layers must stay short per contract §7.7 — no text walls on mobile.

### 5.6 Email-safe compromises + client fallbacks

- **Keep the `<style>` block** (Gmail/Apple/Naver web honor `<head><style>`), **but additionally inline** the critical properties on hero, cards, owner panel, judgment badge, rights footer — because Outlook (Word engine) and some mobile clients drop `<style>`.
- **Preheader span** as first body node:
  ```html
  <span style="display:none!important;opacity:0;color:transparent;height:0;width:0;overflow:hidden;mso-hide:all;">{{preheader}}</span>
  ```
- **Gradients fail in Outlook** → always pair a gradient with a solid `bgcolor`/`background-color` fallback. Hero: `<table bgcolor="#0c1322">…`.
- **Layout:** wrap hero and each card region in `<table role="presentation" width="100%">` for Outlook; keep the CSS-flex version for modern clients. Don't rely on fl/grid in email.
- **CSS variables don't work in many email clients** → run a build step (or render-time substitution) that **resolves `var(--ks-*)` to literal hex** in the email build, while the browser-preview build can keep variables. Simplest: store tokens in a Python dict and `.format()` them into the CSS string so both builds share one source of truth.
- **Dark-mode clients:** the design is already dark; set `<meta name="color-scheme" content="dark light">` and `<meta name="supported-color-schemes" content="dark light">` so clients don't auto-invert your navy into mud.
- **No remote webfont** — system stack only (satisfied).

### 5.7 Inline-vs-class guidance

| Element | Browser preview | Email build |
|---------|----------------|-------------|
| Page shell, generic spacing | class | class (kept) |
| Hero bg/gradient + bgcolor | class | **inline + table bgcolor** |
| Card bg/border | class | **inline** |
| OwnerAnglePanel, JudgmentBadge | class | **inline** (most-likely-stripped, highest-value) |
| RightsFooter | class | **inline** |
| Audit/operation/validation boxes | class | class (low stakes; ok if it degrades) |

---

## 6. Component redesign spec

For each: purpose · visible fields · hidden/internal fields · layout · class suggestions. DOM ids in the renderer stay as-is unless noted (the read-only validator and quality gate key off `id="top-shot-image"`, `class="top-shot-hero"`, `id="premium-hero"`, `id="opening-lead"`, `data-top-item`, `id="operation-metadata"`, `id="top5-section"`, `id="deep-dive-section"`, the rights string, and the `premium-*`/`briefing-card`/`owner-angle-block`/`judgment-badge` markers — **do not rename these**).

### PremiumHero  `#premium-hero`
- **Purpose:** Establish private-secretary authority + mood in the first screen.
- **Visible:** OwnerReviewBadge; identity line `테크 비서 키수리`; hero title; hero subtitle; top-shot image (§4).
- **Hidden/internal:** none (no program_id/slot here).
- **Layout:** badge (top-left) → identity (small, dim) → title (large) → subtitle (dim) → image (full-width, 16:9, rounded). Dark gradient `--ks-hero-1`→`--ks-hero-2`, `bgcolor` fallback, `min-height` so missing image never collapses.
- **Classes:** `.premium-hero`, `.owner-badge`, `.identity-line`, `.hero-title`, `.hero-subtitle`, `.hero-image-card`, `.top-shot-hero`.

### OwnerReviewBadge  (inside hero)
- **Purpose:** Make "this is a pre-send owner preview" unmistakable, quietly.
- **Visible:** `운영자 검수용 미리보기 · 발송 전`.
- **Layout:** small gold-soft pill, gold text, `--ks-gold-soft` bg, gold hairline border. (Reuse current `.owner-badge` look but recolor amber→gold for palette unity.)

### SignalSummary  `#signal-summary`  (NEW, optional-but-recommended)
- **Purpose:** "오늘의 신호" one-strip read so the owner gets the day in 3 seconds before scrolling 5 cards. Replaces the perception of an RSS list with an executive scan line.
- **Visible:** 3–5 short signal chips, each = 2–4 words distilled from a TOP item (e.g. `AI 내재화` · `에이전트 개발 재편` · `통제권 이동`). Optional one-line read above the chips.
- **Hidden/internal:** none. Derive chips from item headlines/judgment; **do not** expose `category`/`confidence`.
- **Layout:** horizontal wrap of pill chips, gold-soft and blue-soft alternating, inside a slim `.section-card` with no heavy heading.
- **Classes:** `.signal-summary`, `.signal-chip`.
- **Gate note:** purely additive; keeps `주인님` absent here is fine (gate only requires 주인님 somewhere in body, satisfied by opening/cards).

### TopFiveCard  `article.briefing-card[data-top-item="n"]`
- **Purpose:** One ranked signal, with the owner's angle and Kee-Suri's judgment as the payoff.
- **Visible (exact Korean labels, §7):** rank numeral; headline (`n. …`); `무슨 일이 있었나`; `왜 지금 중요한가`; `주인님 관점` (OwnerAnglePanel); `키수리 판단` (KeysuriJudgmentBadge); `다음 확인 포인트` (NextWatchCue); `출처` (source chip: name + URL).
- **Hidden/internal:** keep the existing off-screen `.source-box` (`기준시각`, `검증 상태`) for owner provenance — it is `aria-hidden`/off-canvas and that's fine; do **not** surface `category`, `why_it_matters` (as a raw key), `business_implication`, `confidence`, `source_ids` as labels.
- **Layout:** rank numeral (large gold, top) → headline → two plain blocks → **OwnerAnglePanel (elevated)** → **JudgmentBadge row** → NextWatchCue (compact) → source chip (muted, last, after interpretation per contract §6.4). Visual weight should descend: headline > owner panel > judgment > what/why > source.
- **Classes:** `.briefing-card`, `.card-rank`, `.card-headline`, `.brief-block`, `.block-label`, `.block-body`, `.source-chip`.

### OwnerAnglePanel  `.owner-angle-block`  (PROMOTE)
- **Purpose:** The single highest-value line per card — what it means *for 주인님*. Must visually outrank the neutral blocks.
- **Visible:** label `주인님 관점` + body.
- **Layout:** elevated insight panel, **gold** left rule (`border-left:3px solid var(--ks-gold)`), `--ks-gold-soft` background, slightly larger body (`0.98rem`), label in gold (`--ks-gold`) small-caps. This is the one place gold fills a block — it signals "private, for you."
- **Classes:** `.owner-angle-block`, `.owner-angle-block .block-label`.

### KeysuriJudgmentBadge  `.judgment-row` / `.judgment-badge`  (SIGNAL, not tag)
- **Purpose:** Kee-Suri's private call on the signal — read as a verdict, not a category chip.
- **Visible:** badge label (활용 후보 / 사업 신호 / 기회 / 관찰 / 리스크 신호) + one-line rationale.
- **Layout:** badge = gold outline pill on dark (`background:transparent; border:1px solid var(--ks-gold); color:var(--ks-gold); font-weight:700; letter-spacing:0.04em`), prefixed with a small `키수리 판단` micro-label so the owner knows whose judgment it is. Rationale text in `--ks-text-dim` beside it. On mobile, stack.
- **Classes:** `.judgment-row`, `.judgment-label` (NEW micro-label), `.judgment-badge`, `.judgment-text`.
- **Gate note:** the quality gate checks for `judgment-row`/`judgment-badge` presence per item — keep both class hooks.

### NextWatchCue  `.next-watch-block`
- **Purpose:** Forward-looking action cue, small.
- **Visible:** label `다음 확인 포인트` + one short line.
- **Layout:** compact, no panel — label in `--ks-text-mute`, body one line, a small `→` glyph prefix. Lower weight than owner panel.
- **Classes:** `.next-watch-block`, `.block-label`, `.block-body`.

### DeepDiveMemo  `#deep-dive-section`
- **Purpose:** Executive memo — what the 5 signals mean *together*; structure + side-effects + direction (contract §7).
- **Visible:** heading `키수리의 딥-다이브`; lead prose; optional `키수리 해석` / `주인님·운영자 영향` / `아직 불확실한 점`; **1/2/3 layer cards** when dense (titles like 인프라·플랫폼 신호 / 통제권·규제 압력 / 워크플로·락인).
- **Hidden/internal:** none.
- **Layout:** reads like a memo, not a card grid — generous line-height, max ~3–4 lines per paragraph (mobile contract §7.7). Layer cards: numbered gold numeral, bold title, short body, `--ks-surface-2` background, thin blue left rule.
- **Classes:** `.deep-dive-prose`, `.deep-interpretation`, `.deep-impact`, `.deep-uncertainty`, `.deep-layer`, `.deep-layer-number`, `.deep-layer-title`, `.deep-layer-body`.

### OneLineCheckpoint  `#one-line-section` / `.checkpoint`
- **Purpose:** One decisive direction cue (contract §9) — the line the owner remembers.
- **Visible:** heading `원-라인 체크포인트` + one sentence.
- **Layout:** make it feel like a pull-quote: larger (`1.15rem`), `--ks-text`, gold left rule, `--ks-gold-soft` wash, more vertical padding. Single most quotable element after the hero.
- **Classes:** `.checkpoint`.

### SourceList  `#closing-section`
- **Purpose:** Provenance, clearly separated from analysis (contract §12).
- **Visible:** heading `마무리 및 출처 리스트`; short controlled closing line; source cards (출처명 / URL / 수집 시각 / 상태).
- **Layout:** visually quieter than content cards — `--ks-surface-2`, smaller text, tight rows. Sits *below* the briefing, clearly a reference appendix.
- **Classes:** `.closing-message`, `.source-card`, `.src-name`, `.src-url`, `.src-fetched`, `.src-status`.
- **Copy fix:** closing must avoid `GENERIC_CLOSING_PHRASES` (§7).

### CompactAuditBox  `#operation-metadata` (+ preview/validation/checklist)  (DEMOTE/COLLAPSE)
- **Purpose:** Owner/operator review metadata — must exist (contract requires operation metadata + validation box) but be visually secondary.
- **Visible by default:** a single muted summary line, e.g. `운영 정보 · 검수용` with the boxes inside a collapsed `<details>` (open-on-click).
- **Internal fields (kept, inside the fold):** `program_id`, `slot`, `mode`, `status`; validation result fields (`validation_status` etc.); compliance checklist. **These never appear in the main body** and never leak `category/why_it_matters/business_implication/confidence/source_ids`.
- **Layout:** `--ks-text-mute`, `0.72rem`, `--ks-line` hairline, no shadow; wrapped in `<details class="audit-fold"><summary>운영 정보 (검수용) 보기</summary> … </details>`. Keep DOM ids so the validator/quality gate still find them. (Quality gate's `_visible_body_region` cuts off at `id="operation-metadata"` — keeping that id means all your premium body stays in the checked region and the audit stays out of it. Good.)
- **Classes:** `.audit-fold`, `.meta-box`, `.op-meta`, `.validation-box`, `.compliance-box`.
- **Note:** Korean-localize the English component headings where they are customer-adjacent, but per renderer-design §6.4 the `Review confirmation` heading may stay as an implementation label for now; prefer localizing `Preview metadata`/`Operation metadata` visible to owner to `미리보기 정보`/`운영 정보`.

### RightsFooter  `#rights-policy`
- **Purpose:** MirAI:ON copyright (contract §13, exact text — gate-checked).
- **Visible (exact):**
  ```
  Copyright Ⓒ MirAI:ON. All rights reserved.
  무단 전재, 재배포 및 AI학습 이용 절대 금지
  ```
- **Layout:** centered, `--ks-text-mute`, `0.78rem`, a thin top rule and small wordmark treatment (`MirAI:ON` in `--ks-gold` letter-spaced) so it reads as a brand sign-off, not a disclaimer dump. Must stay **separate** from the review-confirmation box and image watermark (contract §13.3). Keep the exact ASCII string `Copyright Ⓒ MirAI:ON. All rights reserved.` — the gate matches it literally.

---

## 7. Content display rules

### 7.1 Exact visible labels (Korean) — TOP 5 card

Use these strings verbatim; the quality gate (`REQUIRED_ITEM_LABELS`) checks for them:

- `무슨 일이 있었나`
- `왜 지금 중요한가`
- `주인님 관점`
- `키수리 판단`  (via `.judgment-row`/`.judgment-badge`)
- `다음 확인 포인트`
- `출처`

Locked section labels (do not alter): `글로벌 테크 TOP 5` / `국내 테크 TOP 5`, `키수리의 딥-다이브`, `원-라인 체크포인트`, `마무리 및 출처 리스트`.

### 7.2 Closing copy (replaces gate-failing line)

Use a short controlled close with **no** service-desk phrasing, e.g.:
> `주인님, 오늘 신호는 여기까지 정리해 두었습니다. 출처는 아래에 그대로 남깁니다.`

### 7.3 Forbidden phrases (must be absent from visible body)

`귀사` · `오늘 브리핑이 도움이 되셨기를 바랍니다` · `다음 브리핑에서 찾아뵙겠습니다` · `도움이 되기를 바랍니다` / `도움이 되셨기를 바랍니다` · `추가 문의사항은 언제든` · `더 유익한 정보로 찾아뵙` · 공개 방송형 톤 · `앵커` / `뉴스 앵커` / `테크 앵커` · raw keys `category` / `why_it_matters` / `business_implication` / `confidence` / `source_ids` · Today_Geenee / Tomorrow_Geenee.

(First four families and the raw keys are enforced today by `FORBIDDEN_PHRASES`, `GENERIC_CLOSING_PHRASES`, and `INTERNAL_VISIBLE_LABELS` in `keysuri_contract_preview_quality.py`.)

---

## 8. Cursor implementation handoff

**Goal:** Restyle + harden the contract-preview surface. HTML/CSS redesign, subject/preheader constants, image embedding fix, gate still green. No behavior beyond rendering.

**Files to MODIFY:**
- `keysuri_contract_preview_renderer.py` — replace `_premium_styles()` with the §5 token-based CSS; restyle components per §6 (keep all DOM ids/classes the validator & gate depend on); add `SUBJECT_LINES_*` / `PREHEADERS_*` constants (§3); add preheader hidden span as first body node; add `<meta name="color-scheme">`; switch top-shot to data-URI embed with CID-ready mode flag (§4); add branded fallback for missing image; fix closing copy (§7.2); add `SignalSummary` + `JudgmentBadge` micro-label + `<details>` audit fold.
- `scripts/render_keysuri_contract_preview.py` — read the approved local canary JPG, base64-embed (preview mode) or set CID (email mode flag, default off); write timestamped file to `output/keysuri_preview/html_test/`; then run the validator and print JSON.
- `tests/test_keysuri_contract_preview_renderer.py` — assert new structure (see §8 tests below).
- `keysuri_contract_preview_quality.py` — *optional, additive only*: add a check that the hero `src` is not a `../` relative path (must be `data:`, `cid:`, `https://`, or absolute) — see §8 tests. Do not weaken existing checks.

**Files NOT to touch:**
- `keysuri_renderer.py` (owner-review renderer)
- `keysuri_html_preview_validation.py` (read-only validator v0 — renderer must conform to it, not the reverse)
- `keysuri_prompt_profiles.py`, generation prompts, JSON schema, briefing validators
- scheduler / email sender / image API / `main.py` / `orchestrator.py`
- Genie validators (`validators.py`, `publishing_policy.py`)

**Hard constraints (do all):**
- ❌ No email send. ❌ No scheduler wiring. ❌ No image API call (use existing local asset only).
- ❌ No Today_Geenee / Tomorrow_Geenee anywhere.
- ❌ No `admin_runs` mutation. ❌ No `production_ready/scheduler_ready/email_ready` flags or language.
- ✅ Keep `contract_preview` validator (`scripts/validate_keysuri_html_preview.py`) **PASS**.
- ✅ Keep `validate_contract_preview_visible_body` (quality gate) **PASS** (no issues).
- ✅ `output/**` stays gitignored — generated HTML never committed.
- ✅ Image embedding fixed and CID-ready (mode flag emits `cid:` shape for future send).
- ✅ Subject/preheader provided as reviewable constants.

**Build sequence:**
1. Token CSS + component restyle (no DOM id/class renames).
2. Data-URI image embed + fallback + CID mode flag.
3. Subject/preheader constants + preheader span + `<title>`.
4. Closing copy + audit `<details>` fold.
5. Render → run both gates → iterate to PASS.
6. Extract visible body and report (§8 final step).

**Visual-quality tests to add/adjust** (`tests/test_keysuri_contract_preview_renderer.py`):
- hero `src` starts with `data:image/` (preview build) — never contains `../`.
- preheader hidden span present as first child of `<body>` and non-empty.
- `<meta name="color-scheme"` present.
- `.signal-summary` present; `.judgment-label` micro-label present in each item.
- audit `<details class="audit-fold">` wraps `#operation-metadata`.
- run `validate_contract_preview_visible_body(html).ok is True`.
- run the read-only `keysuri_html_preview_validation` → `validation_status == "PASS"`.
- assert closing contains none of `GENERIC_CLOSING_PHRASES`.

**Generate new preview HTML + report (final step):**
```bash
python3 scripts/render_keysuri_contract_preview.py --program keysuri_global_tech --slot 12:30
python3 scripts/validate_keysuri_html_preview.py \
  'output/keysuri_preview/html_test/keysuri_global_1230_contract_preview_*.html' --pretty
```
Then extract the visible body (everything before `id="operation-metadata"`) and report: PASS/FAIL of both gates, subject/preheader chosen, image embed mode, and a 5-line visible-body summary for owner review.

---

## 9. Acceptance checklist (strict PASS/FAIL)

| # | Check | PASS condition |
|---|-------|----------------|
| 1 | Hero image visible in **browser preview** | Opens from any path; data-URI embed renders; no broken icon |
| 2 | **Email image strategy** defined | CID-ready mode emits `cid:` src; hosted fallback + alt text + branded fallback documented (§4) |
| 3 | Subject/preheader improved | Korean premium constants in place; no `[KEYSURI test]`, no `오늘 브리핑`, no clickbait |
| 4 | `주인님` present | Appears in visible body (opening + cards + deep-dive) |
| 5 | `귀사` absent | Not anywhere in visible body |
| 6 | Premium design applied | Unified dark palette; no white document cards; promoted OwnerAnglePanel; gold judgment signal; type scale per §5.2 |
| 7 | Raw internal labels absent | No `category` / `why_it_matters` / `business_implication` / `confidence` / `source_ids` / `prompt_status` / etc. in visible body |
| 8 | Operational metadata bottom/collapsed | Inside `<details class="audit-fold">`, below `#operation-metadata`, muted; not in checked body region |
| 9 | Source list readable | `마무리 및 출처 리스트` present; item-level 출처 in each card; provenance visually separated |
| 10 | `contract_preview` validator | `scripts/validate_keysuri_html_preview.py` → `validation_status: PASS` |
| 11 | Visible-body quality gate | `validate_contract_preview_visible_body(html).ok == True`, zero issues |
| 12 | No email sent | No sender code invoked; no `email_ready` language |
| 13 | No scheduler / image API / Geenee bleed | None present |
| 14 | Closing copy clean | No `GENERIC_CLOSING_PHRASES` |
| 15 | Rights footer exact | `Copyright Ⓒ MirAI:ON. All rights reserved.` + `무단 전재…` present, separate from review/watermark |
| 16 | **Ready for owner visual review?** | **YES** only if 1–15 all PASS |

---

### Appendix — what stayed locked (did not redesign)

- Section order and locked Korean section labels (contract §16.3, renderer-design §5).
- DOM ids/classes the validator and quality gate key on.
- Image watermark ownership model (pixel-baked `MirAI:ON`, post-process; renderer does not draw it).
- Owner-review renderer, scheduler, email, image API — untouched.
- Review-confirmation / validation / operation boxes remain **separate components** (contract Appendix B) — only visually demoted, never collapsed into each other.
