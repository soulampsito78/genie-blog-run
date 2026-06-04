# Kee-Suri Production Wiring Design — Global 12:30 / Korea 18:30

## 1. Purpose

This document defines the production wiring design for Kee-Suri Global 12:30 and Korea 18:30 image generation before implementation.

Clarifications:

- This file does **not** connect Cloud Scheduler.
- This file does **not** deploy anything.
- This file does **not** change runtime code.
- This file does **not** enable production auto-calls.
- This file is a **design guard** before actual production wiring.

Readers should use this document together with the profile lock doc (`docs/keysuri/KEYSURI_IMAGE_PROFILE_LOCK.md`) for QA and regression alignment.

---

## 2. Current locked baseline

| Item | Value |
|------|--------|
| Global profile commit | `0c0d459b427334f2f7e098eb21e662410716fc77` |
| Global commit message | Add Kee-Suri stable production image prompt profile |
| Korea profile commit | `ae0e162148f18a0139bea102af4b6eb1ac98428b` |
| Korea commit message | Add Kee-Suri Korea winter evening image prompt profile |
| Profile lock doc commit | `9c6a2896d1cd4d73879a54c9ca43645af4f170b2` |
| Profile lock doc message | Add Kee-Suri image profile lock document |
| Profile lock doc path | `docs/keysuri/KEYSURI_IMAGE_PROFILE_LOCK.md` |

**Current operational status:**

- Production wiring is **not** connected.
- Cloud Scheduler is **unchanged**.
- Generated canary images and reports are **local / gitignored only**.

**Accepted live QA reference images (local paths, not committed):**

- Global 12:30: `output/keysuri_preview/image_canary/keysuri_global_canary_20260604_221233.jpg`
- Korea 18:30: `output/keysuri_preview/image_canary/keysuri_korea_canary_20260604_225207.jpg`

---

## 3. Production program identities

### 3.1 keysuri_global_tech

- **Schedule identity:** 12:30 KST
- **Content identity:** Global tech, AI, big tech, platform, startup, and policy signals
- **Visual identity:** Daytime global briefing
- **Accepted profile:** Global 12:30 (locked at commit `0c0d459`)
- **Tablet:** Allowed
- **Tablet posture:** Simple waist or low-chest edge grip
- **Mood:** Daytime global executive briefing

**Must not become:**

- Today_Geenee
- Public news anchor
- CEO portrait
- Generic office worker

### 3.2 keysuri_korea_tech

- **Schedule identity:** 18:30 KST
- **Content identity:** Korea tech, startup, platform, policy, and business opportunity signals
- **Visual identity:** Winter after-sunset domestic briefing
- **Accepted profile:** Korea 18:30 (locked at commit `ae0e162`)
- **Tablet:** Optional or absent
- **Hands:** Calmly clasped or simple relaxed posture allowed
- **Mood:** Organized after-work private briefing

**Must not become:**

- Tomorrow_Geenee
- Weathercaster
- Public news anchor
- Hotel lounge or fashion-editorial image

---

## 4. Daily Wardrobe Consistency Rule

This section defines a **runtime / session design rule**, not only per-prompt wording.

### 4.1 Core rule

- **Same KST date** means the **same Kee-Suri outfit** for both `keysuri_global_tech` (12:30) and `keysuri_korea_tech` (18:30).
- **Different KST date** may rotate outfit within the approved wardrobe palette.
- Outfit rotation must **not** change identity, role, pose policy, time mood, or weather interpretation.
- The two slot images may differ in time mood, lighting, prop posture, and briefing context; they must **not** differ in wardrobe on the same KST date.

### 4.2 Examples

- 2026-06-04 Global 12:30: charcoal suit + ivory blouse
- 2026-06-04 Korea 18:30: **same** charcoal suit + ivory blouse
- 2026-06-05 Global 12:30: deep navy suit + cream blouse
- 2026-06-05 Korea 18:30: **same** deep navy suit + cream blouse

### 4.3 Selection and reuse flow

- Wardrobe is selected **once per KST date** before the first Kee-Suri image generation for that date.
- The selected wardrobe is reused for both programs on that date.
- If Korea runs after Global, Korea **must reuse** the wardrobe seed selected for Global on the same KST date.
- If Global generation failed but Korea runs later, Korea may create that date’s wardrobe seed and store it for the date (Global retry on same date must then reuse it).
- If retry occurs on the same date, retry **must reuse** the same wardrobe seed unless manual override is explicitly approved.

### 4.4 Conceptual field names

| Field | Meaning |
|-------|---------|
| `wardrobe_date_kst` | Calendar date in KST, format YYYY-MM-DD |
| `wardrobe_profile_id` | Deterministic choice from approved wardrobe palette for that date |
| `daily_wardrobe_seed` | Derived from `wardrobe_date_kst`, wardrobe group, and `wardrobe_profile_id` |

**Recommended design (conceptual only):**

- `wardrobe_date_kst` is YYYY-MM-DD in KST.
- `wardrobe_profile_id` is a deterministic value selected from the approved wardrobe palette (e.g. hash or ordered rotation by date).
- `daily_wardrobe_seed` binds date + group + profile for prompt injection and audit metadata.
- Exact implementation module layout is **out of scope** for this document.

---

## 5. Approved wardrobe palette

### 5.1 Allowed examples

- Charcoal fitted suit + ivory blouse
- Deep navy fitted suit + soft cream blouse
- Muted graphite suit + champagne blouse
- Dark gray business dress with structured jacket
- Charcoal jacket + pencil skirt + cream blouse
- Deep navy jacket + pencil skirt + ivory blouse

### 5.2 Wardrobe rules

- Premium business styling
- Private tech secretary presence
- Refined Korean professional silhouette
- Same-day consistency across Global and Korea
- No weather-driven outfit change
- No casual look
- No party or evening dress
- No anchor uniform
- No CEO dominance styling
- No hotel lounge styling
- No fashion editorial styling
- No seductive night styling
- No raincoat
- No umbrella

---

## 6. Shared identity, separated mood

### 6.1 Shared across both programs

- Same Kee-Suri person (reference identity continuity)
- Same face identity
- Same short bob
- Same thin metal glasses
- Same premium professional silhouette
- **Same daily outfit on the same KST date**
- Same private tech secretary identity

### 6.2 Separated by program

| Axis | Global 12:30 | Korea 18:30 |
|------|----------------|-------------|
| Time / light | Daytime, bright grey/cloudy window | Winter after-sunset, deep blue-gray evening city |
| Briefing | Global tech executive | Domestic Korean tech / startup / platform |
| Tablet | Allowed, simple grip | Optional or absent |
| Hands | Simple edge grip | Calmly clasped or relaxed; ready-to-brief |

### 6.3 Rules

- Do not average the two profiles.
- Do not merge them into a generic Kee-Suri office image.
- Do not make Global darker because Korea is evening.
- Do not make Korea brighter because Global is daytime.
- Do not let wardrobe consistency erase time and mood separation.
- Do not let time and mood separation change the daily wardrobe.

---

## 7. Production wiring boundary

### 7.1 Not allowed yet

- No Cloud Scheduler binding
- No production auto-call
- No live image API auto-call
- No email or Naver publishing linkage
- No Today_Geenee runtime coupling
- No Tomorrow_Geenee resurrection
- No direct deployment
- No production runtime wiring
- No automatic image generation

### 7.2 Allowed in future implementation only after explicit approval

- Create runtime mapping from schedule slot to `program_id`
- Create wardrobe seed resolver
- Create dry-run safety report
- Create production preflight check
- Create canary-only manual approval path
- Create explicit production enable flag (default off)

---

## 8. Proposed runtime mapping design

Conceptual mapping only. No Scheduler connection. No production runtime connection. No image API call from this design doc.

### 8.1 keysuri_global_tech

- schedule_kst: 12:30
- program_id: keysuri_global_tech
- profile_lock: global_1230
- wardrobe_group: keysuri_daily
- wardrobe_date_source: KST
- image_auto_call_default: false

### 8.2 keysuri_korea_tech

- schedule_kst: 18:30
- program_id: keysuri_korea_tech
- profile_lock: korea_1830
- wardrobe_group: keysuri_daily
- wardrobe_date_source: KST
- image_auto_call_default: false

### 8.3 Explanation

- Both programs share **wardrobe_group: keysuri_daily**.
- That shared wardrobe group is how same-day outfit consistency is enforced.
- **image_auto_call_default** remains false until explicit production approval.
- This mapping is conceptual only.
- This mapping does not connect Scheduler.
- This mapping does not connect production runtime.
- This mapping does not call the image API.

---

## 9. Proposed production preflight checklist

Use before any production wiring or auto-call enablement:

- [ ] Active commit includes Global profile commit 0c0d459
- [ ] Active commit includes Korea profile commit ae0e162
- [ ] Active commit includes profile lock doc commit 9c6a289
- [ ] keysuri_global_tech maps to 12:30 KST
- [ ] keysuri_korea_tech maps to 18:30 KST
- [ ] Both programs share wardrobe_group=keysuri_daily
- [ ] Same KST date reuses the same daily_wardrobe_seed
- [ ] Global does not inherit Korea evening mood
- [ ] Korea does not inherit Global daytime mood
- [ ] Today_Geenee is not wired to Kee-Suri image profile
- [ ] Tomorrow_Geenee is not resurrected
- [ ] Image API live call requires explicit production enable flag
- [ ] Canary live call still requires manual approval
- [ ] Generated images remain gitignored
- [ ] No generated image or report files are committed
- [ ] No secrets or raw provider payloads are saved
- [ ] Scheduler remains unchanged until explicit approval

---

## 10. Failure modes to block

- Global and Korea on the same KST date use different outfits.
- Daily wardrobe changes between retry attempts on the same date without approved override.
- Korea output looks like bright cloudy daytime or white-night office.
- Global output looks like evening or black night.
- Korea drifts toward Tomorrow_Geenee or weathercaster styling.
- Global drifts toward Today_Geenee or public anchor styling.
- Shared wardrobe rule produces generic office-worker feel (identity dilution).
- Outfit rotation creates fashion or editorial drift.
- Weather condition changes outfit.
- Time mood changes outfit.
- Production auto-call happens without explicit enable flag.
- Scheduler binding occurs before approval.
- Output images or reports are committed accidentally.
- Raw provider payloads or secrets are saved.
- Retry generates a different daily wardrobe without manual override.

---

## 11. Implementation sequence proposal

Design only. Do not implement from this document alone.

Suggested future sequence:

1. Add wardrobe palette and daily seed resolver in an isolated module.
2. Add tests for same KST date wardrobe consistency across Global and Korea.
3. Add schedule-to-program mapping contract.
4. Add production preflight report (offline, no API call).
5. Add dry-run for Global/Korea same-day pair.
6. Add manual canary for paired Global/Korea generation (explicit approval per live call).
7. Only after approval, wire to production runtime.
8. Only after separate approval, connect Scheduler.

---

## 12. Open questions

- Where should wardrobe seed state be stored?
  - Deterministic date-based resolver only
  - Local metadata file
  - Database state
  - Object storage metadata
- Should weekday and weekend use different wardrobe palettes?
- Should season affect wardrobe palette (without tying to weather-driven outfit)?
- Should same-day failed Global but successful Korea still lock wardrobe for that date?
- How many wardrobe profiles are allowed initially?
- Should wardrobe_profile_id be visible in internal debug metadata?
- Should wardrobe be visible in email metadata for debugging?
- How long should accepted image outputs be retained before production deletion or archival?
- Should manual override be allowed for a bad daily outfit?
- Should a manually overridden outfit apply to both Global and Korea for that KST date?

---

## 13. Current recommendation

- **Do not wire production yet.**
- **Do not connect Scheduler yet.**
- **Do not enable automatic image API calls yet.**

**Next recommended track:**

- **R5A** — Wardrobe Seed Resolver Design (lowest risk path), or
- **R5B** — Production Preflight Contract

If choosing the lowest risk path, start with **R5A**.

---

*Document: GENIE Image Track R5-REPAIR — production wiring design. Aligned to profile lock doc commit `9c6a289` and image profile commits `0c0d459` (Global) and `ae0e162` (Korea).*
