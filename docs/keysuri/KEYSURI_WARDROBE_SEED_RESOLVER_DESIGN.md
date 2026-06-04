# KEYSURI Wardrobe Seed Resolver Design

Status:
Design only / no implementation / no production wiring

Scope:
Kee-Suri image prompt wardrobe consistency only.

Non-scope:

- production runtime wiring
- Scheduler changes
- Cloud Run/GCP changes
- live image generation
- Gemini/LLM calls
- Today_Geenee image path
- Tomorrow_Geenee revival
- output artifact changes

Aligned references:

- Profile lock: `docs/keysuri/KEYSURI_IMAGE_PROFILE_LOCK.md` (commit `9c6a289`)
- Production wiring design: `docs/keysuri/KEYSURI_PRODUCTION_WIRING_DESIGN.md` (commit `0a85a51`)
- Global image profile: commit `0c0d459`
- Korea image profile: commit `ae0e162`

---

## 1. Purpose

This document defines the **R5A Daily Wardrobe Seed Resolver** design for Kee-Suri image generation.

The resolver exists to enforce one rule: on the **same KST calendar date**, `keysuri_global_tech` (12:30) and `keysuri_korea_tech` (18:30) must wear the **same outfit**.

Program-specific differences remain allowed and required:

- Global: daytime global briefing mood, tablet allowed, simple edge grip
- Korea: winter after-sunset domestic briefing mood, tablet optional or absent, clasped hands allowed

The resolver must **not** merge time mood, lighting, pose, or briefing context. It only selects and binds **wardrobe** for a given KST date within an approved palette.

---

## 2. Background

GENIE Image Track R5 locked the **production wiring design** in `KEYSURI_PRODUCTION_WIRING_DESIGN.md`. That document introduced:

- `wardrobe_group: keysuri_daily`
- conceptual fields `wardrobe_date_kst`, `wardrobe_profile_id`, `daily_wardrobe_seed`
- `image_auto_call_default: false` for both programs
- explicit boundary: no Scheduler binding, no production auto-call

**Current gap:** wardrobe same-day consistency is **design-only**. No Python module implements a wardrobe seed resolver. `keysuri_weather_visual_prompt_integration.py` uses a static `wardrobe_lock` (charcoal/ivory continuity) but does **not** rotate or deterministically select a daily profile across dates.

R5A closes the design gap before any implementation or production wiring.

---

## 3. Design Goals

| Goal | Description |
|------|-------------|
| Same-day Global/Korea consistency | One outfit per KST date for both programs |
| Retry stability | Same date + same inputs → same wardrobe seed on retry |
| No storage dependency for MVP | Deterministic resolver; no DB or object store required initially |
| Manual override extensibility | Optional future override map without changing default behavior |
| Debug visibility | Internal metadata for audits and local reports |
| No production auto-call side effects | Resolver design must not imply or enable image API auto-call |

---

## 4. Inputs

All resolver invocations should accept the following inputs.

| Input | Type / value | Required | Notes |
|-------|----------------|----------|-------|
| `wardrobe_date_kst` | string, YYYY-MM-DD | Yes | Calendar date in Asia/Seoul |
| `wardrobe_group` | string | Yes | Fixed to `keysuri_daily` for Kee-Suri image tracks |
| `wardrobe_palette_version` | string | Yes | e.g. `v1`; bumps only when palette definition changes |
| `program_id` | string | Yes | `keysuri_global_tech` or `keysuri_korea_tech` |
| `manual_override_profile_id` | string or null | No | If set, must be a valid palette profile id |
| `timezone` | string | Yes | Default `Asia/Seoul`; used only to derive or validate `wardrobe_date_kst` |

**Validation expectations:**

- `program_id` must be one of the two Kee-Suri image programs (not Today_Geenee, not Tomorrow_Geenee).
- `wardrobe_group` must be `keysuri_daily` for MVP.
- `wardrobe_date_kst` must parse as a valid date in KST context.

---

## 5. Outputs

| Output | Description |
|--------|-------------|
| `wardrobe_profile_id` | Stable id for one palette entry (e.g. `profile_01_charcoal_ivory`) |
| `daily_wardrobe_seed` | Composite seed string for logging, reports, and prompt injection binding |
| `wardrobe_profile` | Structured description: suit color, blouse color, silhouette notes |
| Debug metadata | See §13 |

**Consumer behavior (future):** prompt builders inject `wardrobe_profile` text into positive prompt stems while leaving program-specific time/mood stems unchanged.

---

## 6. Recommended MVP Resolver

Use a **deterministic resolver** with no persisted wardrobe state for MVP.

**Step A — Select profile index**

Compute a non-negative integer index from:

- `wardrobe_group`
- `wardrobe_date_kst`
- `wardrobe_palette_version`

Use a stable hash of the concatenation of those three fields (normalized strings), then reduce modulo `palette_size` (number of profiles in the active palette version). The result selects one entry from Approved Wardrobe Palette v1.

**Step B — Assign wardrobe_profile_id**

Map the selected index to a fixed `wardrobe_profile_id` defined in the palette table (not the raw index alone), so palette reordering can be managed via version bumps.

**Step C — Derive daily_wardrobe_seed**

Form `daily_wardrobe_seed` as a deterministic string derived from:

- `wardrobe_group`
- `wardrobe_date_kst`
- `wardrobe_palette_version`
- `wardrobe_profile_id`

Example logical shape (prose, not code): keysuri_daily|2026-06-04|v1|profile_01_charcoal_ivory

**Manual override path:** if `manual_override_profile_id` is present and valid, skip hash selection and use that profile id directly; still emit `daily_wardrobe_seed` with an override flag in metadata.

---

## 7. Why Deterministic First

| Approach | Pros | Cons |
|----------|------|------|
| **Deterministic hash resolver (MVP)** | No DB/object storage; retry-safe; same date always reproducible; Korea can resolve same outfit if Global failed earlier; lower operational surface | Palette rotation is formula-driven; manual override needs separate path |
| **Stored state (DB / file / object metadata)** | Explicit audit trail per run; easier manual edits in UI | Partial writes if Global fails; sync bugs between Global/Korea; migration and backup burden; harder offline canary |

**Why deterministic before production wiring:**

- Production wiring is not approved yet; minimizing moving parts is appropriate.
- Canary and regression tests can assert same inputs → same outputs without fixtures for stored rows.
- Global failure before Korea does not block Korea from picking the **same** wardrobe for that date independently.
- No risk of “yesterday’s stored outfit” leaking across date boundaries if state cleanup fails.

Stored state may be added later for override workflows or editorial control, behind explicit flags.

---

## 8. Approved Wardrobe Palette v1

Conservative palette: **4 profiles**. All preserve Kee-Suri identity constraints from the profile lock doc.

| wardrobe_profile_id | Suit / jacket | Blouse | Notes |
|---------------------|---------------|--------|-------|
| profile_01_charcoal_ivory | Charcoal fitted suit | Ivory blouse | Default-adjacent; matches accepted Global QA direction |
| profile_02_navy_cream | Deep navy fitted suit | Soft cream blouse | Distinct but still premium business |
| profile_03_graphite_champagne | Muted graphite suit | Champagne blouse | Slightly warmer neutral |
| profile_04_slate_soft_ivory | Dark slate suit | Soft ivory blouse | Cool-neutral variant |

**Each profile must preserve:**

- Private Korean AI tech secretary identity (not public anchor)
- Sleek short bob and thin glasses (identity continuity via reference + text)
- Fitted premium business silhouette
- Pencil skirt or equivalent refined business lower silhouette where applicable

**Each profile must not imply:**

- Public news anchor or weathercaster styling
- CEO power portrait dominance
- Hotel lounge, bar lounge, or glamour shoot
- Evening party dress, fashion editorial, or seductive night styling
- Weather-driven outerwear (umbrella, raincoat, seasonal outdoor gear)

`wardrobe_palette_version` = `v1` until palette table changes; then bump to `v2` with explicit migration notes in tests and docs.

---

## 9. Same-Day Global/Korea Consistency

**Shared for a given KST date:**

- `wardrobe_date_kst` (same calendar day)
- `wardrobe_group` = `keysuri_daily`
- `wardrobe_palette_version` (same active version)
- Resolver algorithm version (when implemented)

**Therefore:**

- `wardrobe_profile_id` is identical for Global 12:30 and Korea 18:30 on that date.
- `daily_wardrobe_seed` is identical for both programs on that date.
- Injected wardrobe text in prompts matches for both runs.

**Remains program-specific (not set by wardrobe resolver):**

- Time of day and window/exterior mood (daytime vs winter after-sunset)
- Tablet vs clasped hands posture
- Global vs domestic briefing mood strings
- Weather window/light/haze wording (must not change outfit)

---

## 10. Retry Behavior

| Rule | Requirement |
|------|-------------|
| Same KST date retry | Must reuse same `wardrobe_profile_id` and `daily_wardrobe_seed` |
| Silent rotation | **Forbidden** on retry without manual override |
| Manual override | Only allowed path to change same-day wardrobe |
| Palette version | Must be explicit; changing version intentionally may change outfit (documented bump) |

Retries include: failed image API call, blocked gate, operator-initiated re-run on same date.

---

## 11. Global Failure / Korea First Success

No stored wardrobe state is required for MVP.

**Scenario:** Global 12:30 image generation fails or is skipped; Korea 18:30 runs later the same KST date.

**Behavior:**

- Korea invokes resolver with same `wardrobe_date_kst`, `wardrobe_group`, `wardrobe_palette_version`.
- Korea receives the **same** `wardrobe_profile_id` Global would have received.
- If Global is retried later that day, Global resolves the **same** profile independently.

**No cross-run file or DB row is required** for consistency; determinism provides the guarantee.

---

## 12. Manual Override Design

Design only — not implemented in this step.

**Future override map (conceptual):**

- Key: `wardrobe_date_kst` + `wardrobe_group`
- Value: `wardrobe_profile_id` (must exist in active palette)

**Rules:**

- Override applies to **both** `keysuri_global_tech` and `keysuri_korea_tech` for that date.
- Override must set `manual_override_applied: true` in debug metadata.
- Override must be logged in internal reports; not customer-facing email copy by default.
- Invalid override id → fail closed with explicit error (do not fall back silently to hash selection without logging).

**Operator workflow (future):** approve override in canary or ops tooling; never expose raw seed strings to end users.

---

## 13. Metadata / Debug Visibility

Internal fields attached to resolver result (reports, future run metadata, local JSON only):

| Field | Purpose |
|-------|---------|
| wardrobe_group | Confirm `keysuri_daily` |
| wardrobe_date_kst | Audit date used |
| wardrobe_palette_version | e.g. `v1` |
| wardrobe_profile_id | Selected or overridden profile |
| daily_wardrobe_seed | Composite seed string |
| manual_override_applied | boolean |
| resolver_version | e.g. `r5a_mvp_1` for implementation tracking |
| program_id | Which program invoked resolver (per-call audit) |

**Clarifications:**

- Internal logs and offline reports only
- Not customer-facing email body or Naver publish copy
- May appear in `output/keysuri_preview/` reports when implemented — still gitignored
- Must not include secrets, API keys, or raw provider payloads

---

## 14. Failure Modes

| Failure | Expected handling |
|---------|-------------------|
| Invalid KST date | Reject; do not resolve wardrobe |
| Empty palette | Reject; fail closed |
| Invalid override id | Reject; no silent fallback |
| Palette version mismatch | Reject or explicit “unknown version” error |
| Wrong wardrobe_group | Reject if not `keysuri_daily` for Kee-Suri MVP |
| Timezone mismatch | Reject or normalize only via Asia/Seoul policy |
| Today_Geenee wardrobe logic mixed in | Reject at integration boundary; Kee-Suri resolver must not import Today_Geenee image wardrobe pools |
| Tomorrow_Geenee program id | Reject |
| Hash modulo edge (empty version string) | Reject at validation |

---

## 15. Future Implementation Candidates

Design only. **No implementation in R5A doc step.**

| Candidate | Role |
|-----------|------|
| `keysuri_daily_wardrobe_resolver.py` | Pure resolver: inputs → outputs + validation |
| `tests/test_keysuri_daily_wardrobe_resolver.py` | Unit tests for determinism, override, failures |
| Integration: `keysuri_weather_visual_prompt_integration.py` | Inject resolved wardrobe text into per-program positive prompt |
| Integration: `keysuri_visual_context.py` | Optional: pass wardrobe_profile into visual context dict |
| Script: `scripts/build_keysuri_wardrobe_resolver_report.py` | Offline report for pair dry-run (no image API) |

Integration must preserve Global/Korea mood separation from existing committed profiles.

---

## 16. Test Plan

Design-only test plan for future implementation. **No live API required.**

| Case | Expectation |
|------|-------------|
| Same date, Global then Korea | Same `wardrobe_profile_id` and `daily_wardrobe_seed` |
| Different KST dates | May select different profiles (rotation over palette) |
| Retry same date | Identical seed and profile |
| Manual override valid | Both programs get override profile; metadata flag set |
| Manual override invalid | Error; no silent rotation |
| No Today_Geenee symbols | Resolver module does not reference Today_Geenee wardrobe families |
| No Tomorrow_Geenee program | Reject forbidden program ids |
| Palette v1 size | Exactly 4 profiles; modulo behavior stable |
| wardrobe_group mismatch | Reject |

Suggested offline commands (future, after implementation):

- `python3 -m unittest tests.test_keysuri_daily_wardrobe_resolver`
- Pair dry-run report script (design TBD) alongside existing prompt and gate reports

---

## 17. Production Boundary

This document explicitly does **not**:

- Connect production wiring
- Enable `image_auto_call` or set `image_auto_call_default` to true
- Change Cloud Scheduler jobs or bindings
- Call Vertex image API or any image generation service
- Revive Tomorrow_Geenee programs or styling
- Change Today_Geenee image execution paths
- Deploy Cloud Run services or alter GCP configuration
- Commit or modify `output/**` artifacts

Wardrobe resolver implementation, when approved, remains behind the same manual-approval and production-enable flags described in R5.

---

## 18. Recommendation

**Adopt the deterministic resolver for MVP/R5A implementation.**

Rationale:

- Matches R5 production wiring design (`keysuri_daily` group, same-date rule)
- Lowest risk before Scheduler or runtime wiring
- Retry-safe and Global/Korea-order independent
- Manual override can be layered later without replacing core determinism

**Suggested next tracks (after this design is reviewed/committed):**

1. **R5A-I** — Implement `keysuri_daily_wardrobe_resolver.py` + unit tests only
2. **R5A-P** — Integrate resolver into prompt builder (offline reports first)
3. **R5B** — Production preflight contract (still no Scheduler)

Do not proceed to Scheduler or production auto-call until profile lock checklist and R5 preflight items are explicitly approved.

---

*Document: GENIE Image Track R5A — wardrobe seed resolver design. No implementation. No production wiring.*
