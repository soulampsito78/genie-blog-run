# Kee-Suri Title and Body Section Contract

## 1. Purpose

This document defines the **official Kee-Suri title/body structure** — the customer-facing narrative contract for `keysuri_global_tech` (12:30 KST) and `keysuri_korea_tech` (18:30 KST).

It is built from:

| Input | Commit / status |
|-------|-----------------|
| `docs/keysuri/KEYSURI_TERMINOLOGY_LOCK.md` | `23bed0b` — locked section labels and identity terms |
| `docs/keysuri/KEYSURI_PROTOTYPE_PUBLICATION_LOGIC_FLOW_EXTRACTION.md` | `cd66dca` — prototype logic-flow assets |
| Scheduler / promotion / prompt-direction boundaries | `1b23bcf`, `07a98ac`, `8313281` |

Clarifications:

- This contract **does not approve** Cloud Scheduler wiring, email sending, production image assets, or bottom-shot production attachment.
- This contract **does not verify** source accuracy or factual claims.
- This contract **does not rename** locked section labels — it uses them exactly as defined in code and `KEYSURI_TERMINOLOGY_LOCK.md`.
- This contract **preserves** Kee-Suri product-language assets and prototype logic-flow strengths: latestness pressure, structural interpretation, side-effect detection, directional judgment, and **원-라인 체크포인트** compression.

Code-aligned sources (reference only — no code changes in this document):

- `keysuri_private_briefing.py` — `SECTION_DEEP_DIVE`, `SECTION_ONE_LINE`, `SECTION_CLOSING`
- `keysuri_news_contract.py` — `SECTION_TOP5_GLOBAL`, `SECTION_TOP5_KOREA`
- `keysuri_prompt_profiles.py` — prompt profile section rules
- `keysuri_renderer.py` — renderer layout and identity display

---

## 2. Scope

### 2.1 In scope

| Area | Detail |
|------|--------|
| Title / subject direction | Structural movement, currentness, business relevance |
| Opening lead structure | Signal-first, not greeting-first |
| TOP 5 item text structure | Signal capture per global/korea scope |
| **키수리의 딥-다이브** logic | Structural interpretation + side effects + direction |
| **원-라인 체크포인트** function | Executive decision cue |
| **마무리 및 출처 리스트** function | Controlled close + provenance |
| 18:30 domestic bottom-shot warm closing | Placement rule (promotion-gated) |
| Model / renderer / server responsibility split | Who owns what |

### 2.2 Out of scope

| Area | Reason |
|------|--------|
| Source verification | Owner excluded |
| Factual validation | Owner excluded |
| Web search | Not requested |
| Scheduler implementation | No active scheduler (`scheduler_allowed=false`) |
| Image API | Manual canary only; `PROMPT_DIRECTION_ONLY` for offduty_02C |
| Email sender wiring | Not connected |
| Production asset promotion | Separate checklist (`8313281`) |
| Today_Geenee / Tomorrow_Geenee | Forbidden bleed |

---

## 3. Core publication logic

Reusable Kee-Suri analytical arc — every briefing should move through these steps:

```
Step 1: What changed today?
        → 글로벌 테크 TOP 5 or 국내 테크 TOP 5

Step 2: Why is this not just news?
        → transition into 키수리의 딥-다이브

Step 3: What structure is moving?
        → deep_dive.body — movement thesis

Step 4: What second-order effects appear?
        → deep_dive.body + key_implications

Step 5: Who gains control / who loses leverage?
        → deep_dive conclusion thread

Step 6: What should the reader watch, hold, or prepare for?
        → bridge to 원-라인 체크포인트

Step 7: 원-라인 체크포인트
        → one decisive direction cue (not recap)

Step 8: [18:30 Korea only — bottom-shot production-promoted]
        → warm farewell below domestic bottom-shot (§11)

Step 9: 마무리 및 출처 리스트 / operation metadata
        → closing_message + source_list; server metadata separate
```

**Programs:**

| program_id | Slot | TOP heading | Bottom-shot warm close |
|------------|------|-------------|------------------------|
| `keysuri_global_tech` | 12:30 KST | **글로벌 테크 TOP 5** | **No** |
| `keysuri_korea_tech` | 18:30 KST | **국내 테크 TOP 5** | **Future only** (§11) |

---

## 4. Title / subject contract

### 4.1 Rules

| Rule | Detail |
|------|--------|
| Expose **structural movement** | Not only the single biggest headline |
| Carry **currentness** | Reader knows this is today's read |
| Carry **direction** | Where pressure or control is moving |
| Carry **business relevance** | Work, money, platform, infrastructure, regulation, opportunity |
| No clickbait | No hype bait, no false urgency |
| No generic tech news tone | Not a digest label |
| No **테크 앵커** | Use **테크 비서 키수리** / **키수리** identity |
| Subject policy | Title may use **키수리** / **키수리 브리핑** / **테크 비서 키수리** per renderer policy — this contract does not lock final email subject line policy beyond these rules |

### 4.2 Allowed pattern families

**A. Structural movement**

```
[키수리 브리핑] {핵심 변화}가 {시장/일/플랫폼/인프라}를 움직입니다
```

**B. Control shift**

```
[키수리] 오늘의 테크 신호: {누가} {무엇의 통제권}을 가져가고 있습니다
```

**C. Side-effect focus**

```
[키수리 브리핑] {이슈} 이후, {돈/일/인프라/규제}에 생긴 압력
```

**D. Quiet premium**

```
{핵심 이슈} 이후, 오늘 봐야 할 테크 신호
```

### 4.3 Bad examples (forbidden shapes)

| Bad title | Why |
|-----------|-----|
| 오늘의 AI 뉴스 모음 | Generic digest |
| 최신 기술 소식입니다 | No structural movement |
| 키수리가 알려주는 오늘 이야기 | Vague, no direction |
| 놓치면 안 되는 대박 AI 뉴스 | Clickbait / hype |
| 테크 앵커 키수리 리포트 | Forbidden identity |
| 오늘도 수고했어요 … | Weather/emotional opener in title |

---

## 5. Opening lead contract

### 5.1 Rules

| Rule | Detail |
|------|--------|
| **Not greeting-first** | Signal before salutation |
| Sentence 1 | Creates **currentness pressure** — what changed / what is moving |
| Sentence 2 | Why it matters to work, money, platform power, infrastructure, regulation, or opportunity |
| Sentence 3 (optional) | What lens the reader should use today — what to watch / hold / prepare for |
| Greeting | May appear **only after** signal framing, if used at all |

### 5.2 Structure template

```
Sentence 1: What changed / what is moving?
Sentence 2: Why it matters to work, money, platform power, infrastructure, regulation, or opportunity?
Sentence 3: What lens should the reader use today?
```

### 5.3 Avoid

| Forbidden opener | Why |
|------------------|-----|
| 오늘은 여러 소식이 있습니다. | Weak, no structural thesis |
| 안녕하십니까 … | Greeting-first |
| Generic tech newsletter intro | No Kee-Suri signal density |
| Emotional weather-style intro | Wrong register |

---

## 6. 글로벌 테크 TOP 5 / 국내 테크 TOP 5 contract

### 6.1 Function

- **Latest signal capture** — what moved today in scope
- **Current event surface** — reader sees the live board
- Each item is a **signal**, not a republished article summary

### 6.2 Scope labels (locked)

| program_id | `section_heading` |
|------------|-------------------|
| `keysuri_global_tech` | **글로벌 테크 TOP 5** |
| `keysuri_korea_tech` | **국내 테크 TOP 5** |

Do not use generic **TOP 5** or prototype-era **TOP 3** as production headings.

### 6.3 Each item must include

| Element | Purpose |
|---------|---------|
| Entity / company / institution | Who moved |
| Action or event | What happened |
| Consequence | What shifts downstream |
| `why_it_matters` | Stakes for the reader |
| `business_implication` | Work / money / platform read |
| `risk_note` (optional) | Secondary pressure if needed |

### 6.4 Preferred item rhythm

```
A. What happened
B. Why it matters
C. What side effect may follow
```

### 6.5 Title shape per item (preferred)

**Entity + action + consequence** — e.g. who did what, and what pressure follows.

### 6.6 Do not

- Lead with source-heavy display before interpretation
- Write generic news digest bullets
- Use scope-less **TOP 5** heading
- Turn into Today_Geenee market summary
- Use **오늘의 핵심 신호** as section replacement

---

## 7. 키수리의 딥-다이브 contract

### 7.1 Function

- **Structural interpretation** — what the day's signals mean together
- **Side-effect detection** — second-order consequences
- **Movement synthesis** — connect TOP 5 items into one larger structural shift

### 7.2 Locked label

`deep_dive.section_heading` = **`키수리의 딥-다이브`** — exact spelling, hyphen included.

### 7.3 Required behavior

| Must | Must not |
|------|----------|
| Identify structure underneath the news | Repeat TOP 5 item-by-item |
| Detect second-order effects | Use **심층 분석** label |
| Name who gains control / loses leverage | Item recap only |
| Give strategic direction | Investment advice |
| Use bold but bounded judgment | Over-neutral summary |
| | **반드시** / **확정** / **대박** / **무조건** |

### 7.4 Recommended paragraph flow

**Paragraph 1:** 오늘의 TOP 5가 결국 무엇으로 읽히는지.

**Paragraph 2:** What structural movement is happening.

**Paragraph 3:** Second-order effects — regulation, capital, infrastructure, platform lock-in, supply chain, security, workflow, entry barrier.

**Paragraph 4:** Directional judgment — what to watch / hold / prepare for.

### 7.5 Preferred phrasing (Korean)

- 가능성이 커집니다.
- 압력이 생깁니다.
- 이동하고 있습니다.
- 진입 장벽이 높아집니다.
- 통제권이 이동합니다.
- 구조 변화에 가깝습니다.

### 7.6 Forbidden replacements

Do not substitute **키수리의 딥-다이브** with:

- **키수리의 인사이트**
- **심층 분석**
- **원-다이브** / **One-Dive**
- Generic analysis headings

---

## 8. Side-effect detection rules

Each **키수리의 딥-다이브** should identify **at least one** side-effect category when enough input exists.

| Category | Example read |
|----------|--------------|
| Market shock | Valuation / cap-table pressure from a single event |
| Infrastructure bottleneck | Compute, power, fab, datacenter constraints |
| Regulation / sovereignty | National AI rules, export controls, data residency |
| Platform lock-in | Ecosystem capture deepens |
| Supply-chain control | Chip, cloud, or model supply concentration |
| Data / security control | Access, audit, compliance leverage shifts |
| Labor / workflow shift | Who automates what; control of knowledge work |
| Startup entry barrier | Capital, distribution, or regulation raises floor |
| Capital concentration | Hyperscaler spend pulls industry gravity |
| National bloc formation | US/EU/China/Korea alignment or decoupling |
| Energy / compute constraint | Power or GPU supply as binding limit |
| Local vs cloud control shift | On-prem / sovereign cloud vs hyperscaler gravity |

**Method:** For each TOP signal, ask: *If this holds, what else must change?* — feed answers into the movement thesis and `key_implications`.

---

## 9. 원-라인 체크포인트 contract

### 9.1 Function

- **One decisive direction cue**
- **Executive-level compression**
- **Not a recap** of articles or TOP items

### 9.2 Locked label

`one_line_checkpoint.section_heading` = **`원-라인 체크포인트`** — exact spelling, hyphen included.

### 9.3 Rules

| Rule | Detail |
|------|--------|
| Length | One sentence preferred |
| Content | Compresses **structural judgment**, not article list |
| Question answered | "그래서 오늘 무엇을 봐야 하는가?" |
| May mention | Power shift, bottleneck, control, pressure, entry barrier, opportunity signal |
| Label | Must use **`원-라인 체크포인트`** exactly |

### 9.4 Good shape

```
{핵심 구조 변화}가 진행되면서, {통제권/진입장벽/기회/위험}은 {어디로} 이동하고 있습니다.
```

### 9.5 Avoid

| Forbidden | Why |
|-----------|-----|
| 한 줄 체크포인트 | Spelling drift |
| 원포인트 / One-Point | Rejected label |
| 키수리의 한 줄 판단 | Unapproved invented heading |
| 핵심 요약 | Today_Geenee bleed |
| Vague motivational sentence | Not a decision cue |

---

## 10. Image and text rhythm

| Layer | Rule |
|-------|------|
| **Top-shot** | Opens briefing mood and authority — 12:30 global and 18:30 domestic |
| **Body text** | Must carry full meaning **without** relying on image |
| **Self-sufficiency** | Briefing must work if images fail to load |
| **Bottom-shot** | **Not active production** unless separately promoted (`8313281`) |
| **18:30 domestic** | Future bottom-shot may support emotional close (§11) |
| **12:30 global** | Top-shot only unless separately approved |

**Current image state (boundary reference):**

- `offduty_02C` = **`PROMPT_DIRECTION_ONLY`** (`07a98ac`) — not production asset
- `scheduler_allowed=false`, `ready_for_scheduler=false` (`1b23bcf`)
- No email attachment wiring for Kee-Suri bottom-shot

**Text rhythm:**

```
[top-shot — when wired]
[opening lead]
[TOP 5]
[키수리의 딥-다이브]
[원-라인 체크포인트]
[bottom-shot — 18:30 only, when production-promoted]
[warm close — §11, when production-promoted]
[마무리 및 출처 리스트]
```

---

## 11. Domestic 18:30 bottom-shot warm closing contract

### 11.1 Applies only to

| Condition | Value |
|-----------|-------|
| program_id | `keysuri_korea_tech` |
| Slot | 18:30 domestic tech |
| Production gate | Bottom-shot **production-promoted** state only |

**Does not apply to:** `keysuri_global_tech` 12:30, Today_Geenee, Tomorrow_Geenee.

### 11.2 Placement

- **Below** domestic bottom-shot image
- **Before** **마무리 및 출처 리스트** / operation metadata (if renderer policy allows)
- Must **not** replace **원-라인 체크포인트**
- Must **not** replace **마무리 및 출처 리스트**

### 11.3 Copy (owner-locked)

| Calendar | Text |
|----------|------|
| Monday–Thursday | **오늘도 수고하셨습니다. 내일 다시 뵙겠습니다.** |
| Friday (KST) | **이번 주도 수고하셨습니다. 주말 잘 보내시고 월요일에 다시 뵙겠습니다.** |

### 11.4 Tone

| Allowed | Forbidden |
|---------|-----------|
| Warm, concise, premium | Romantic / girlfriend |
| Private secretary-like | Idol / fan-service |
| Controlled familiarity | Weathercaster |
| Small human ritual | Overly sentimental |
| | New analysis section disguised as goodbye |

### 11.5 Schedule interaction

If weekend/holiday skip policy is implemented later: **no send → no closing**.

### 11.6 Unpromoted bottom-shot

If bottom-shot is **not** production-promoted: document and design as **future rhythm only** — do **not** render as active production close. Current state: `PROMPT_DIRECTION_ONLY` only.

**Note:** This block is a **renderer placement prose block**, not a new JSON `section_heading` today.

---

## 12. 마무리 및 출처 리스트 contract

### 12.1 Function

- Close the briefing
- Preserve provenance area
- Avoid overclaiming
- Keep sources **separated** from main analysis

### 12.2 Locked label

`closing_sources.section_heading` = **`마무리 및 출처 리스트`**

### 12.3 Rules

| Rule | Detail |
|------|--------|
| `closing_message` | Short, controlled close |
| `source_list` | Below closing message; provenance preserved |
| Operation metadata | Must **not** dominate customer copy |
| `review_required` / `generated_review_required` | Operation metadata only — not reader-facing emotional climax |
| Emotional climax | If domestic warm close exists (§11), **마무리 및 출처 리스트** is not the emotional peak |

### 12.4 Open issue (owner decision — not resolved here)

Whether customer-facing **display label** should remain **마무리 및 출처 리스트** or renderer may show a softer visual label while schema keeps the locked `section_heading` key.

Until resolved: schema and validators use **`마무리 및 출처 리스트`** exactly.

---

## 13. Product language guardrails

### 13.1 Use

| Term | Role |
|------|------|
| 테크 비서 키수리 | Primary Korean persona title |
| 키수리 | Short name |
| Kee-Suri | English product name |
| 프라이빗 테크 비서 | Role identity (preferred until subtitle resolved) |
| private tech secretary | English role guardrail |
| 테크 브리핑 | Product genre |
| 신호 | Event/signal framing |
| 구조 변화 | Movement thesis |
| 통제권 | Control shift |
| 진입 장벽 | Barrier framing |
| 기회 신호 | Opportunity read |
| 리스크 신호 | Risk read |
| 체크포인트 | Within **원-라인 체크포인트** only — not standalone section rename |

### 13.2 Avoid

| Term / tone | Why |
|-------------|-----|
| 테크 앵커 | Forbidden identity |
| 뉴스 앵커 | Public broadcast register |
| 아나운서 | Public broadcast register |
| public news anchor | English forbidden identity |
| Generic newsletter wording | Weakens product |
| Today_Geenee / Tomorrow_Geenee language | Forbidden bleed |
| Weathercaster emotional filler | Wrong register |
| Girlfriend fantasy | R6B boundary |
| Idol fan-service | R6B boundary |
| demo / staging / E2E / generated result | Customer-facing copy forbidden |

### 13.3 Locked section labels (canonical — use exactly)

- **글로벌 테크 TOP 5**
- **국내 테크 TOP 5**
- **키수리의 딥-다이브**
- **원-라인 체크포인트**
- **마무리 및 출처 리스트**

### 13.4 Rejected section replacements (never use)

- 원-다이브 / One-Dive
- 원포인트 / One-Point
- 심층 분석
- 핵심 요약
- 키수리의 한 줄 판단
- 오늘의 핵심 신호
- 키수리의 인사이트
- 한 줄 체크포인트

---

## 14. Responsibility split

### 14.1 Model responsible (generation / JSON content)

| Field / section | Owner |
|-----------------|-------|
| Title candidates | Model |
| Opening lead | Model |
| TOP 5 item text | Model |
| `why_it_matters` | Model |
| `business_implication` | Model |
| `risk_note` | Model |
| **키수리의 딥-다이브** (`body`, `key_implications`) | Model |
| **원-라인 체크포인트** (`body`) | Model |
| `closing_message` | Model |
| `source_list` entries | Model (provenance strings) |

Model must obey locked `section_heading` values and forbidden rename rules in `keysuri_private_briefing.py`.

### 14.2 Renderer responsible (presentation)

| Concern | Owner |
|---------|-------|
| Section order | Renderer |
| Mobile-first formatting | Renderer |
| Top-shot placement | Renderer |
| Bottom-shot placement | Renderer — only if approved |
| Warm closing placement | Renderer — only if approved (§11) |
| Operation metadata box placement | Renderer |
| Source list visual treatment | Renderer |
| Identity subtitle display | Renderer — `프라이빗 테크 인사이트 브리핑` is renderer candidate only per terminology lock §9 |

### 14.3 Server responsible (runtime / gates)

| Concern | Owner |
|---------|-------|
| `program_id` | Server |
| `mode` | Server |
| `status` | Server |
| Run time / slot | Server |
| Send status | Server |
| `review_required` | Server |
| `generated_review_required` | Server |
| Weekday / Friday determination | Server — if warm close later implemented |
| Production promotion flags | Server |
| Scheduler / email gates | Server — remain **off** until explicitly approved |

---

## 15. Acceptance checklist

Before treating any generated briefing as contract-compliant:

- [ ] Locked section labels preserved exactly
- [ ] Title has opening power and structural movement
- [ ] Opening is **not** greeting-first
- [ ] TOP 5 items are **signals**, not article dumps
- [ ] Scope heading matches program (**글로벌** vs **국내**)
- [ ] **키수리의 딥-다이브** gives structural interpretation — not item recap
- [ ] At least one side-effect category identified when input allows
- [ ] Directional judgment is bold but bounded — no investment advice
- [ ] **원-라인 체크포인트** is a **decision cue**, not recap
- [ ] Source verification remains separate from narrative contract
- [ ] Domestic warm close limited to **18:30 Korea** slot
- [ ] Friday copy uses weekend / Monday wording
- [ ] No production implication for unpromoted bottom-shot
- [ ] No Today / Tomorrow_Geenee bleed
- [ ] No **테크 앵커** / **뉴스 앵커** drift
- [ ] Operation metadata does not dominate customer copy
- [ ] No **원-다이브** / **원포인트** / **One-Dive** / **One-Point** label drift
- [ ] Body works without images

---

## 16. Example skeleton

Fillable contract skeleton — placeholders only; not factual claims.

```
[Program label]
테크 비서 키수리
(Kee-Suri Global Tech | Kee-Suri Korea Tech)

[Title]
[키수리 브리핑] {핵심 변화}가 {시장/플랫폼/인프라}를 움직입니다

[Opening lead]
{무엇이 오늘 이동했는가 — sentence 1}
{왜 일/돈/플랫폼/인프라/규제/기회에 중요한가 — sentence 2}
{오늘 어떤 렌즈로 봐야 하는가 — sentence 3}

[글로벌 테크 TOP 5 | 국내 테크 TOP 5]

1. {entity} — {action} — {consequence}
   - what happened: ...
   - why_it_matters: ...
   - business_implication: ...
   - risk_note (if needed): ...

2. ...
3. ...
4. ...
5. ...

[키수리의 딥-다이브]

P1: 오늘의 TOP 5는 결국 {구조적 움직임}으로 읽힙니다.
P2: {구조 변화 서술}
P3: {2차 효과 — 규제/자본/인프라/락인/공급망/보안/워크플로/진입장벽}
P4: {방향 판단 — watch / hold / prepare}

key_implications:
- ...
- ...

[원-라인 체크포인트]
{핵심 구조 변화}가 진행되면서, {통제권/진입장벽/기회/위험}은 {어디로} 이동하고 있습니다.

[Domestic 18:30 bottom-shot warm close — only if production-promoted]

월~목:
오늘도 수고하셨습니다. 내일 다시 뵙겠습니다.

금요일:
이번 주도 수고하셨습니다. 주말 잘 보내시고 월요일에 다시 뵙겠습니다.

[마무리 및 출처 리스트]
closing_message: ...
source_list:
- ...

[Operation metadata]
server-rendered only — review_required, generated_review_required, run time, send status
```

---

## 17. Recommended next steps

| Step | Action | Gate |
|------|--------|------|
| 1 | Commit this title/body contract | Operator request |
| 2 | Create **one sample Kee-Suri body** using this contract | After step 1 |
| 3 | Owner review of sample against §15 checklist | Before prompt/renderer changes |
| 4 | Prompt profile / generation prompt alignment | After sample approved |
| 5 | Renderer warm-close placement | After R6B bottom-shot production promotion |
| 6 | Scheduler / email wiring | Separate explicit approval (`1b23bcf`) |

**Do not implement renderer or prompt code until the sample body is approved.**

---

## Appendix A — Document dependency chain

```
KEYSURI_TERMINOLOGY_LOCK.md (23bed0b)
        ↓
KEYSURI_PROTOTYPE_PUBLICATION_LOGIC_FLOW_EXTRACTION.md (cd66dca)
        ↓
KEYSURI_TITLE_AND_BODY_SECTION_CONTRACT.md (this document)
        ↓
[future] sample body → prompt/renderer alignment
```

## Appendix B — Production boundary reminders

| Surface | Current state |
|---------|---------------|
| Scheduler | None in repo; `scheduler_allowed=false` |
| Email | Not connected for Kee-Suri |
| Image API | Manual canary only |
| offduty_02C bottom-shot | `PROMPT_DIRECTION_ONLY` (`07a98ac`) |
| Warm close §11 | Future rhythm — not active production |

## Appendix C — Related commits

| Commit | Document |
|--------|----------|
| `23bed0b` | Add Kee-Suri terminology lock |
| `cd66dca` | Extract Kee-Suri prototype publication logic flow |
| `8313281` | Update Kee-Suri R6B promotion checklist decision state |
| `07a98ac` | Record Kee-Suri R6B offduty_02C prompt-direction decision |
| `1b23bcf` | Document Kee-Suri scheduler state and future wiring design |
