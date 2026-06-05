# KEYSURI Image Track R6 — Full-Body Reference Asset Plan

Status:
Planning only / no production wiring / no image API in this document
Asset 02 classification: **complete** — `KEEP_AS_SILHOUETTE_REFERENCE`

Scope:
Define how Kee-Suri **full-body reference assets** should be classified, evaluated, and used in a future R6 track—without repeating R5 blind canary experimentation.

Non-scope (R6 planning phase):

- live image generation
- blind image retries
- Scheduler / Cloud Run / GCP wiring
- default opt-in enablement
- committing generated images before operator QA
- modifying production resolver or Today_Geenee / Tomorrow_Geenee paths
- treating R5 canary JPGs as production assets

Aligned references:

- R5 closure report: commit `844591e` — `docs/keysuri/KEYSURI_IMAGE_TRACK_R5_CLOSURE_REPORT.md`
- Wardrobe v4 rotation design: commit `fa6f592` — `docs/keysuri/KEYSURI_WARDROBE_V4_STRUCTURE_VARIATION_DESIGN.md`
- R5F guarded canary path: commit `82a0d97`
- Visual asset guide: `assets/keysuri/README_KeeSuri_Visual_Asset_Guide.md`
- Full-body asset path: `assets/keysuri/reference/image_keysuri_asset_02_full_body.png`
- Identity/briefing asset path: `assets/keysuri/reference/image_keysuri_asset_01_main_briefing.png`

---

## Relation to R5 and Wardrobe v4

### R5 closure (commit `844591e`)

R5 closed with a definitive visual conclusion: **Wardrobe v4 structure variation works; color-only variation does not.** R5 canary infrastructure (`82a0d97`) and three `PASS_DIRECTION` v4 profiles (`fa6f592`) are **direction candidates and QA references**, not production publication.

R5 explicitly deferred production asset work to **R6**. This plan is that deferral made concrete for **full-body** usage.

### Wardrobe v4 connection

Wardrobe v4 profiles (v4_01, v4_02, v4_03) were validated primarily through **upper-body / private briefing** canaries using **Asset 01** (main briefing reference) for identity continuity. Full-body Asset 02 was **not** exercised as a production input during R5.

R6 must connect Wardrobe v4 **outfit structure rules** to full-body generation:

- v4 wardrobe clauses and anti-repeat blocks apply to full-body outputs
- full-body framing must not reintroduce the failed **dark blazer + pale blouse + tablet-at-waist** uniform
- seasonal bands (spring/summer v4_03, fall/winter v4_02, all-season v4_01) inform full-body mood and garment weight

Full-body work is an **extension** of accepted v4 direction—not a reset to pre-v4 color roulette.

---

## 1. Why Full-Body Assets Were Not Modified During R5

R5 was scoped to **wardrobe structure validation** under guarded manual canaries, not production asset promotion.

| Reason | Explanation |
|--------|-------------|
| **Track focus** | R5 answered: “Can Kee-Suri rotate outfits without repeating the same image?” — tested via briefing-framed upper-body canaries |
| **Reference discipline** | R5 locked **identity-only** use of Asset 01; outfit cloning from reference was explicitly forbidden and QA-verified |
| **Risk isolation** | Full-body generation introduces proportion, pose stiffness, glamour drift, and outfit over-locking risks not present in waist-up briefing shots |
| **No production path** | R5 had no Scheduler, no default opt-in, no static/email promotion—full-body production assets were out of scope |
| **Asset 02 unused in live canaries** | `image_keysuri_asset_02_full_body.png` exists in the repo and provider contract but was not treated as another random canary input during R5 |
| **QA reference boundary** | All R5 generated JPGs remain gitignored QA references; modifying or replacing full-body production assets would have blurred that boundary |

Full-body asset strategy requires a **separate planning and classification pass**—which is R6.

---

## 2. Difference Between Asset and Workflow Types

| Type | Definition | Primary asset | R5 status | R6 role |
|------|------------|---------------|-----------|---------|
| **Identity reference** | Face, bob, glasses, Korean private AI tech secretary impression — **not** outfit, pose, or composition copy | Asset 01 | Used in R5 canaries (identity-only policy) | Continues for upper-body and may supplement full-body identity anchoring |
| **Silhouette reference** | Standing proportions, body line, full-frame stance, editorial height balance | Asset 02 | Defined in asset guide; **not production-tested in R5** | **Classified:** `KEEP_AS_SILHOUETTE_REFERENCE` — proportion/framing only |
| **Wardrobe canary** | Guarded one-live-call experiment to test a wardrobe profile; output is QA reference only | Asset 01 (+ v4 prompt override) | R5 complete (`82a0d97`, `fa6f592`) | **Not** the R6 default workflow—no blind retries |
| **Production asset** | Operator-approved image suitable for landing, thumbnail, intro, or committed static/email use after QA | TBD from R6 workflow | **Does not exist yet** for full-body | R6 target **only after** checklist and decision gate |

**Key distinction:** A **reference asset** (01 or 02) is an **input constraint** for generation. A **production asset** is an **output artifact** that passed operator QA and explicit promotion approval. R5 conflated neither with the other.

---

## 3. Full-Body Asset Usage Policy

### Asset 02 canonical path

`assets/keysuri/reference/image_keysuri_asset_02_full_body.png`

### Classification (required before any R6 generation)

Every full-body asset or candidate must be labeled with one or more roles:

| Role | Meaning |
|------|---------|
| **Silhouette reference** | Body line, stance, proportion anchor |
| **Body proportion reference** | Head-to-body ratio, leg line, shoulder-waist balance |
| **Full-body outfit fit reference** | How v4 garment structures drape at full length—not copying the reference outfit |
| **Production asset candidate** | Output being considered for publication after QA |
| **Landing / thumbnail / intro visual candidate** | Specific use-case tag for approved production assets |

An asset may be **reference only**, **production candidate**, or **both sequentially** (reference first → generate → QA → promote)—never assumed production by default.

### Policy rules

1. **One reference asset per generation prompt** — Asset 01 **or** Asset 02 per call, not both merged (per visual asset guide).
2. **Identity reference ≠ outfit reference** — Asset 02 may inform silhouette and proportion; Wardrobe v4 clause defines outfit—not Asset 02’s embedded outfit.
3. **No canary-without-plan** — R6 does not repeat R5 open-ended wardrobe experiments on full-body framing.
4. **Decision gate before image API** — Preflight + operator approval + explicit reference role declaration required (see § Decision Gate).
5. **QA before commit** — Generated full-body images stay under `output/` until operator PASS; never committed or copied to `static/email/` pre-QA.

---

## Asset 02 Inspection and Classification (Completed)

Operator inspection of the tracked full-body reference asset is **complete**. This section records the binding R6 classification. Do not treat Asset 02 as a production asset or wardrobe source of truth.

### 1. Classification result

| Field | Value |
|-------|-------|
| **Path** | `assets/keysuri/reference/image_keysuri_asset_02_full_body.png` |
| **Classification** | **`KEEP_AS_SILHOUETTE_REFERENCE`** |
| **Tracked** | Yes (commit `672d5a1`) |
| **Gitignored** | No |
| **Type / dimensions** | PNG RGB, 1023 × 1537, ~1.9 MB |
| **Code constant** | `REFERENCE_ASSET_FULL_BODY` in `keysuri_image_provider_contract.py` |
| **Role** | Silhouette / body proportion / full-length framing reference **only** |

**Not classified as:** production asset candidate, wardrobe-fit reference, or primary identity anchor.

### 2. Asset role split

| Asset / source | R6 role |
|----------------|---------|
| **Asset 01** (`image_keysuri_asset_01_main_briefing.png`) | **Primary** identity / face / upper-body briefing reference |
| **Asset 02** (`image_keysuri_asset_02_full_body.png`) | **Secondary** silhouette / proportion / full-length framing reference |
| **Wardrobe v4 profiles** (v4_01, v4_02, v4_03) | **Outfit structure source of truth** — wardrobe clause + R5F structure blocks |
| **New generated QA JPGs** (under `output/`) | **Candidate production assets only after operator QA PASS** — never by default |

One reference asset per generation call (per visual asset guide). When Asset 02 is attached, identity continuity is enforced through **prompt policy aligned with Asset 01**, not by attaching both files in one call.

### 3. Strengths of Asset 02

- **Full head-to-toe view** — only tracked Kee-Suri asset showing complete standing frame
- **Skirt hem, shoes, leg line, and standing proportion** clearly visible (Asset 01 cuts at mid-thigh)
- **Identity-consistent** with Asset 01 — same face, bob, thin glasses, executive secretary persona
- **Already wired** as `REFERENCE_ASSET_FULL_BODY` — resolver accepts `02` / `full_body` selector
- Useful for **full-body framing and proportion anchoring** when strict no-outfit-copy blocks are applied

### 4. Weaknesses / anti-patterns (embedded in Asset 02)

| Anti-pattern | Risk |
|--------------|------|
| Charcoal suit + champagne high-neck blouse | **R5-failed baseline** — same uniform R5 rejected |
| Tablet held at waist with both hands | **R5 anti-pattern** — must not become default prop pose |
| Command-center / data-wall background | Not preferred production setting — private briefing preferred |
| Catalog-stiff full-body standing pose | Limited natural variation |
| Same outfit as Asset 01 | **Freezes wardrobe variation** if outfit/prop/background are copied |
| Low-angle hero framing | May over-elongate legs if copied literally |

Asset 02 is a useful **proportion reference** and a useful **negative example** of what production full-body outputs must not replicate.

### 5. Allowed usage

- **Silhouette reference** — body line, standing stance, full-length framing
- **Proportion anchor** — head-to-body ratio, leg line, shoe/skirt hem placement
- **Full-body framing reference** — how Kee-Suri occupies a vertical hero frame
- **Secondary reference only**, always with strict **no-outfit-copy** prompt block:
  - Do not copy reference outfit, pose, composition, or background
  - Wardrobe v4 clause defines garments; Asset 02 does not

### 6. Forbidden usage

- **Production asset as-is** — not for landing, thumbnail, intro, or static/email publication
- **Outfit reference** — do not use embedded charcoal/champagne suit as wardrobe template
- **Tablet pose reference** — do not replicate tablet-at-waist grip
- **Command-center background reference** — do not replicate data-wall / war-room staging
- **Default identity anchor** — Asset 01 remains primary for face/upper-body identity
- **Wardrobe v4 replacement** — v4 profiles remain outfit source of truth; Asset 02 does not override them

### 7. R6 next decision

| Question | Decision |
|----------|----------|
| Replace Asset 02 in repo? | **No** — keep tracked file as silhouette reference |
| Generate new images now? | **No** — not without explicit one-call approval after decision gate |
| What generation is for? | **New production full-body QA JPGs only** — v4-profile outputs under `output/`, not Asset 02 replacement |
| When to generate? | Only after production prompt package + operator sign-off + preflight + dry-run |

### 8. R6 production prompt implication

Future full-body production prompts must **combine roles in prompt text**, even when only one reference image is attached per call:

| Source | Contributes |
|--------|-------------|
| **Asset 01 policy** | Identity — face, short bob, thin glasses, Korean private AI tech secretary impression (via prompt language; attach 01 if call is upper-body or identity-critical) |
| **Asset 02 (when attached)** | Silhouette / proportion / full-length framing **only** |
| **Wardrobe v4 profile** | Outfit structure — garment clauses, seasonal band, prop rules |
| **Explicit anti-copy block** | Forbid copying Asset 02 outfit, tablet pose, command-center background, and composition |

Example anti-copy language (required when Asset 02 is attached):

> Use reference image for body proportion and full-length framing only. Do not copy the reference outfit, tablet, pose, command-center background, or composition. Apply Wardrobe v4 profile wardrobe clause for all garments and props.

Operator QA must cross-check **identity against Asset 01** and **outfit against Wardrobe v4** even when Asset 02 was the attached reference.

---

## 4. What the Full-Body Asset Is Good For

Asset 02 (**classified `KEEP_AS_SILHOUETTE_REFERENCE`**) is appropriate for:

| Use case | Notes |
|----------|-------|
| **Silhouette and proportion anchoring** | Standing height, leg line, shoe/skirt hem — with no-outfit-copy blocks |
| **Full-length framing reference** | How Kee-Suri occupies a vertical portrait frame |

Future full-body **production** outputs (new QA JPGs, not Asset 02 itself) may additionally target:

| Use case | Notes |
|----------|-------|
| **Full-body outfit fit validation** | Verify v4 garment structures (jacket length, skirt line, folder prop at side) at full length |
| **Landing / hero / intro visuals** | Premium Korean executive secretary; private AI tech briefing mood — **only after QA PASS on new generation** |
| **Thumbnail candidates** | Identity and outfit readable at reduced size |
| **Seasonal wardrobe presentation** | v4_03 summer vs v4_02 fall/winter at full length |
| **Rotation proof at full length** | Same identity across v4 profiles without cloning one hero frame |

Full-body generation should **extend** Wardrobe v4 PASS_DIRECTION profiles, not invent a parallel wardrobe track.

---

## 5. What the Full-Body Asset Must Not Be Used For

| Prohibited use | Reason |
|----------------|--------|
| **Random canary input** | R5 proved structure variation requires planned profiles—not ad hoc full-body retries |
| **Outfit cloning source** | Reproduces failed R5 baseline uniform (Asset 02: charcoal suit + champagne blouse + tablet) |
| **Identity + outfit lock combined** | Over-locks both face and clothes; blocks v4 rotation |
| **Collage / split-screen / multi-subject** | Violates generation rules in asset guide |
| **News anchor / CEO / weathercaster framing** | Wrong persona read for Kee-Suri |
| **Fashion editorial / glamour / lounge shoot** | Drift from premium private secretary briefing |
| **Department-store / showroom styling** | Especially risk for v4_03 summer variants |
| **Default tablet-at-waist prop anchor** | Failed R5 visual pattern |
| **Automatic production publication** | No Scheduler, no static/email copy without R6 QA PASS |
| **Committing generated JPGs to git** | QA references only until explicit promotion decision |

---

## 6. How Wardrobe v4 Should Connect to Full-Body Assets

### Profile mapping

| v4 profile | Full-body intent | Reference strategy |
|------------|------------------|-------------------|
| **v4_01** cream jacket + black inner | All-season structure-break hero | Asset 02 for proportion only; v4_01 wardrobe clause for garments; Asset 01 for identity QA cross-check |
| **v4_02** black suit + bow blouse + clutch | Fall/winter full-length executive read | Strong bow blouse visibility at full length; clutch at side—not waist tablet |
| **v4_03** summer ivory jacket + cool beige inner | Spring/summer lightweight full-body | Brighter daylight; short/3-4 sleeve visible; thin light folder |

### Prompt package requirements (R6, before any call)

Each full-body production prompt package must include:

- Selected v4 profile id and wardrobe clause
- R5F structure blocks and anti-repeat language from catalog
- Explicit **identity-only** instruction for whichever reference asset is attached
- Full-body framing directive: premium private office or controlled studio briefing—not runway
- Prop rule: folder/notebook; no tablet in hands
- Seasonal mood line when applicable
- Negative block: no glamour, no showroom, no anchor/CEO, no outfit copy from reference

### What transfers unchanged from R5

- Same Kee-Suri identity, not same image
- Color-only variation forbidden
- Structure + inner blouse + prop + pose must vary together
- PASS_DIRECTION canary JPGs are **direction references**, not files to commit or upscale blindly

---

## 7. Production Asset Candidate Checklist

Operator must complete this checklist before any full-body output is promoted from `output/` to a production path.

### Reference and prompt

- [ ] Asset 02 classified **`KEEP_AS_SILHOUETTE_REFERENCE`** — silhouette/proportion only; not outfit reference
- [ ] Wardrobe v4 profile selected (v4_01, v4_02, or v4_03)
- [ ] Production prompt package written and reviewed—not improvised at call time
- [ ] Decision gate approved (§ below)
- [ ] Preflight pass; dry-run `request_count=0`

### Visual QA (full-body specific)

- [ ] **Identity:** Same Kee-Suri—face, bob, glasses; no identity drift
- [ ] **Proportion:** Natural editorial proportion; no short-leg / torso-heavy / stiff mannequin read
- [ ] **Outfit structure:** Matches selected v4 profile at full length; not collapsed to dark blazer + pale blouse
- [ ] **Inner blouse:** Visible and structurally distinct (bow, tie-neck, black inner, or cool beige as specified)
- [ ] **Prop:** Folder/notebook visible; no tablet in hands; no tablet-at-waist
- [ ] **Pose:** Natural standing or briefing stance; not frozen showroom pose
- [ ] **Mood:** Premium Korean executive secretary; not anchor/CEO/editorial/glamour/showroom
- [ ] **Seasonal read:** Correct for profile band (summer light vs fall/winter heavier)
- [ ] **Thumbnail test:** Identity and outfit readable at reduced size (if landing/thumbnail use intended)
- [ ] **Different from R5 QA refs:** Not a near-duplicate crop of existing canary JPG

### Promotion hygiene

- [ ] Operator PASS recorded with `visual_qa_status` and reason
- [ ] Output remains in `output/` until explicit copy decision to production path
- [ ] No git commit of generated image without separate asset promotion approval
- [ ] No Scheduler or default opt-in enabled as side effect

---

## 8. Risks

| Risk | Description | Mitigation |
|------|-------------|------------|
| **Over-locking outfit** | Asset 02 outfit copied into every full-body output | Identity/silhouette-only policy; v4 wardrobe clause overrides reference clothes |
| **Face drift** | Full-body framing loses Kee-Suri facial consistency | Asset 01 cross-check; identity-only blocks; operator identity QA |
| **Too much glamour** | Full-body reads as fashion shoot not secretary briefing | Mood blocks; negative prompts; operator QA |
| **Department-store / showroom drift** | Summer v4_03 becomes retail catalog styling | Brighter daylight yes; showroom posing no; private office setting |
| **Full-body pose stiffness** | Standing mannequin / catalog stance | Natural variation language; briefing-context poses |
| **Inconsistent proportions** | Head-to-body ratio varies between generations | Asset 02 proportion reference; explicit proportion language in prompt package |
| **Dark suit collapse** | v4_02 reverts to generic blazer template | Bow blouse + clutch must dominate visual delta |
| **Prop morphing** | Folder becomes tablet-like | Strong prop prompts; explicit no-tablet negatives |
| **Premature production use** | QA JPG copied to static/email without checklist | R6 decision gate; promotion checklist |

---

## 9. R6 Recommended Workflow

R6 is **plan → classify → package → approve → generate (if approved) → QA → promote (if PASS)**.

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Inspect existing full-body asset (Asset 02)          [DONE] │
│    - File: image_keysuri_asset_02_full_body.png               │
│    - Embedded outfit/pose/background documented               │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. Classify asset roles                                   [DONE] │
│    - KEEP_AS_SILHOUETTE_REFERENCE                             │
│    - NOT production asset; NOT wardrobe-fit reference         │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. Decide: reference only vs regenerate production asset [DONE] │
│    - Asset 02 stays in repo as silhouette reference only       │
│    - New v4 full-body QA JPGs require separate generation       │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. Create production prompt package                             │
│    - v4 profile + structure blocks + full-body framing          │
│    - Reference role declaration (02 = silhouette, not outfit)   │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. Decision gate (operator sign-off)                            │
│    - No image API until gate PASS                               │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. Preflight + dry-run (guarded one-call infrastructure)        │
│    - Reuse R5B/R5F runner patterns where applicable             │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 7. One approved live call (if gate passed)                      │
│    - Output → output/keysuri_preview/... only                   │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 8. Operator visual QA (§7 checklist)                            │
│    - PASS → production asset candidate                          │
│    - FAIL → document reason; no retry without new plan          │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ 9. Promotion (separate decision)                                │
│    - Copy to landing/thumbnail/static path only if approved      │
│    - Still no Scheduler/default opt-in unless future track      │
└─────────────────────────────────────────────────────────────────┘
```

**Do not skip steps 1–5.** R5 demonstrated that generation without classification produces repeated failures.

---

## 10. R6 Non-Scope

The following are **explicitly out of R6** unless a future track reopens them with separate design approval:

| Item | Status |
|------|--------|
| Blind image retries / open-ended canary batches | **Out of scope** |
| Scheduler / GCP / Cloud Run / production wiring | **Out of scope** |
| Default wardrobe or image opt-in | **Out of scope** |
| Committing generated images before operator QA | **Out of scope** |
| Promoting R5 canary JPGs directly to production | **Out of scope** |
| Reopening R5D/R5E failed profiles for full-body | **Out of scope** |
| Color-only wardrobe variation experiments | **Out of scope** |
| Today_Geenee / Tomorrow_Geenee integration | **Out of scope** |
| Modifying v1 production resolver without design review | **Out of scope** |

R6 planning documents and classifications may be committed; **generated full-body images may not** until QA PASS and explicit promotion approval.

---

## Decision Gate Before Any New Image API Call

No full-body image API call may proceed unless **all** gate conditions are satisfied:

| # | Condition |
|---|-----------|
| 1 | R6 plan reviewed; Asset 02 classified **`KEEP_AS_SILHOUETTE_REFERENCE`** with declared reference roles |
| 2 | Target v4 profile and use case documented (landing / thumbnail / intro / fit validation) |
| 3 | Production prompt package written—not ad hoc |
| 4 | Operator approval record: date, profile id, reference asset role, operator ref |
| 5 | Preflight PASS for exact target |
| 6 | Dry-run PASS with `request_count=0`, `called_image_api=false` |
| 7 | Guarded one-live-call env set (`GENIE_KEYSURI_APPROVED_ONE_LIVE_CALL=1` + R5F override if using v4 catalog) |
| 8 | Explicit acknowledgment: output is QA reference until checklist §7 PASS |

If any condition fails: **stop**. Do not call image API. Do not retry without updating the plan.

---

## Summary

R5 validated Wardrobe v4 **upper-body** structure variation using Asset 01 for identity only. **Asset 02** has been inspected and classified **`KEEP_AS_SILHOUETTE_REFERENCE`** — silhouette and proportion only; not production, not wardrobe-fit, not primary identity anchor. v4 profiles supply outfit structure; new QA JPGs under `output/` are candidate production assets only after operator QA. Production assets require prompt packages, decision gate, one guarded call, and full-body QA before any promotion.

**Next action:** Commit this classification update when approved. **Do not generate** until a production prompt package passes the decision gate (workflow steps 4–5 onward).
