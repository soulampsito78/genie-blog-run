# KEYSURI R5B Production Preflight and Manual Canary Procedure

Status:
Design/procedure only / no implementation / no live call

Scope:
Kee-Suri wardrobe opt-in prompt canary readiness and preflight rules.

Non-scope:

- production wiring
- Scheduler changes
- Cloud Run/GCP changes
- automatic image generation
- Gemini/LLM text generation
- Today_Geenee changes
- Tomorrow_Geenee revival
- output artifact commits
- default opt-in enablement

Aligned references:

- R5A design: docs/keysuri/KEYSURI_WARDROBE_SEED_RESOLVER_DESIGN.md (commit 9830463)
- R5 production wiring design: docs/keysuri/KEYSURI_PRODUCTION_WIRING_DESIGN.md (commit 0a85a51)
- Profile lock: docs/keysuri/KEYSURI_IMAGE_PROFILE_LOCK.md (commit 9c6a289)
- R5A-I resolver: commit 233bbeb
- R5A-Pa metadata: commit a4b6add
- R5A-Pb opt-in injection: commit 3c902fc

---

## 1. Purpose

This document defines when and how a **single explicit manual opt-in wardrobe canary** may be allowed after R5A offline review completion.

R5A delivered:

- a deterministic daily wardrobe resolver
- same-day Global/Korea metadata parity
- opt-in wardrobe clause injection behind an explicit flag

R5A did **not** authorize automatic image generation, Scheduler binding, or production auto-call.

This R5B procedure exists so operators know exactly what must be true **before** any live Vertex image call with opt-in wardrobe injection — and what must remain forbidden afterward.

---

## 2. Current R5A Baseline

The following is confirmed at R5A review pack completion (HEAD 3c902fc):

| Item | State |
|------|-------|
| Deterministic resolver | Implemented in keysuri_daily_wardrobe_resolver.py (R5A-I) |
| Metadata parity | daily_wardrobe on Global/Korea contracts (R5A-Pa) |
| Opt-in prompt injection | use_daily_wardrobe_prompt_snippet flag (R5A-Pb) |
| Default positive_prompt | Static charcoal/ivory identity stem unchanged |
| Report/gate default path | Non-injected; use_daily_wardrobe_prompt_snippet defaults False |
| ready_for_production_auto_call | false in offline reports |
| ready_for_image_api_call | false in offline reports |
| ready_for_scheduler | false in offline reports |
| side_effects.called_image_api | false in offline reports |
| Live image canary with opt-in | **Not run** |

Default behavior must remain the accepted static prompt path until an operator explicitly opts in for a single approved manual canary.

---

## 3. Manual Canary Principle

Any live Kee-Suri image call after R5A follows these rules:

| Rule | Requirement |
|------|-------------|
| Max calls per approved batch | **One** live image API call |
| Human approval | Explicit operator approval required before call |
| Automatic retry | **Forbidden** without new approval |
| Scheduler | **Not used** |
| Production auto-call | **Not enabled** |
| Default flag flip | **Forbidden** — do not change report builder, gate, or canary defaults to opt-in |
| Pair generation | Global + Korea pair requires **separate explicit approval per call** (default: one program only) |

Manual canary is an exception path for evaluation, not production wiring.

---

## 4. Required Preconditions Before Any Manual Opt-In Canary

All items below must be satisfied before a live opt-in canary:

**Repository and tests**

- Relevant Kee-Suri wardrobe commits present on branch (9830463, 233bbeb, a4b6add, 3c902fc minimum)
- Clean git state for Kee-Suri code paths except known out-of-scope README.md and unrelated untracked artifacts
- R5A unit tests pass (resolver + weather visual prompt integration)
- Offline weather visual prompt report passes with issue_count 0

**Production safety flags**

- ready_for_production_auto_call=false
- ready_for_image_api_call=false
- ready_for_scheduler=false
- side_effects.called_image_api=false in offline report

**Prompt and wardrobe planning**

- Opt-in prompt diff reviewed for target KST date and program
- wardrobe_date_kst fixed and explicit (no guessing today)
- program_id fixed: keysuri_global_tech or keysuri_korea_tech
- wardrobe_profile_id and daily_wardrobe_seed computed offline and recorded in approval
- use_daily_wardrobe_prompt_snippet=True only for the approved canary build path
- Accepted baseline image identified for comparison (see §11)
- Rollback/stop decision path known (see §13)

**Explicit non-goals for this batch**

- No Scheduler changes
- No Cloud Run/GCP changes
- No .env or secrets commits
- No output image commits

---

## 5. Required Offline Commands

Run these commands locally before any manual opt-in canary approval:

1. python3 -m unittest tests.test_keysuri_daily_wardrobe_resolver -v
2. python3 -m unittest tests.test_keysuri_weather_visual_prompt_integration -v
3. python3 scripts/build_keysuri_weather_visual_prompt_report.py

Expected offline report summary:

- report_status: pass
- issue_count: 0
- ready_for_production_auto_call: false
- ready_for_image_api_call: false
- prompt contracts built: keysuri_global_tech, keysuri_korea_tech

Optional future commands (not required today; design-only placeholders):

- python3 scripts/build_keysuri_wardrobe_opt_in_prompt_diff_report.py (future)
- python3 scripts/run_keysuri_canary_preflight.py (future)

Do **not** run scripts/run_keysuri_image_api_canary.py until all preconditions and manual approval (§8) are complete.

---

## 6. Opt-In Prompt Diff Review Criteria

Before approving opt-in, verify offline:

| Criterion | Expected |
|-----------|----------|
| Default prompt unchanged | use_daily_wardrobe_prompt_snippet=False produces static charcoal/ivory clause |
| Opt-in changes wardrobe only | Identity prefix, reference paragraph, pose/scene stems unchanged except wardrobe clause |
| Full prompt_snippet not injected | No snippet-only negatives (e.g. not a lounge or glamour shoot) in positive_prompt |
| Same-date Global/Korea wardrobe | Identical wardrobe clause and daily_wardrobe_seed for same wardrobe_date_kst |
| Program separation preserved | Global: daytime/tablet; Korea: winter 18:30/optional tablet/clasped hands |
| 2026-06-04 profile_01 | Colors charcoal/ivory; **wording differs** from accepted static stem — treat as prompt contract change |
| Non-profile_01 dates | New visual QA cycle; do not assume accepted baselines apply |

**Default static wardrobe clause (reference):**

Charcoal fitted suit, ivory or soft cream blouse, pencil skirt, premium private tech briefing mood.

**Opt-in profile_01 wardrobe clause (reference, 2026-06-04):**

Charcoal fitted suit with ivory blouse, pencil skirt, fitted premium business silhouette.

Operators must acknowledge that opt-in on 2026-06-04 is a wording change even when profile_01 matches accepted color family.

---

## 7. Target Date / Program Selection Rules

| Field | Rule |
|-------|------|
| wardrobe_date_kst | Explicit YYYY-MM-DD; derive from fixture or approved ops date — never guess |
| program_id | keysuri_global_tech or keysuri_korea_tech only |
| Current date/time | **Do not** call datetime.now or equivalent to infer wardrobe date |
| Forbidden programs | today_geenee, tomorrow_geenee, tomorrow_genie, Tomorrow_Geenee |
| Pair calls | Default one program per approval; Global+Korea same day requires two approvals and two separate calls if ever allowed |

Record in approval record:

- wardrobe_date_kst
- program_id
- wardrobe_profile_id (from offline resolver)
- daily_wardrobe_seed
- use_daily_wardrobe_prompt_snippet: true

---

## 8. Manual Approval Gate

Manual approval is a human operator checkpoint, not automatic production enablement.

**Conceptual approval record must include:**

- Operator name or ticket id
- Timestamp (human-recorded; not used for wardrobe resolution)
- wardrobe_date_kst
- program_id
- Expected wardrobe_profile_id
- Expected daily_wardrobe_seed
- Confirmation that use_daily_wardrobe_prompt_snippet=True for this call only
- Confirmation that default paths remain non-injected
- Single-call limit acknowledged

**Environment pattern (existing canary convention):**

- GENIE_KEYSURI_IMAGE_MANUAL_APPROVAL=1 or equivalent explicit operator confirmation documented in run notes

**Approval properties:**

- Expires after **one** live image call
- Does **not** authorize Scheduler binding
- Does **not** authorize production auto-call
- Does **not** authorize changing default report/gate/canary flags
- Does **not** authorize a second call without new approval

---

## 9. Live Canary Execution Boundary

When (and only when) all preconditions and manual approval are satisfied:

| Boundary | Rule |
|----------|------|
| Image API calls | Exactly **one** per approval |
| Retry | Forbidden without new approval |
| Batch generation | Forbidden |
| Global+Korea pair | Forbidden unless explicitly approved as two separate single-call batches |
| Production asset replacement | Forbidden |
| Output location | output/keysuri_preview/image_canary/ (gitignored) |
| Git commit of generated image | **Forbidden** |
| Provider | Vertex image per existing canary contract; manual approval still required |
| Prompt path | Opt-in wardrobe clause only for approved call; all other profile lock criteria apply |

After call: record filename, program, date, profile, seed, PASS/FAIL, and comparison notes. Do not commit output artifacts.

---

## 10. PASS / FAIL Criteria for Manual Canary

### PASS criteria

- Identity continuity with reference asset 01
- Kee-Suri private Korean AI tech secretary identity preserved
- Wardrobe family matches selected wardrobe_profile_id (colors/silhouette)
- Program mood correct if applicable (Global daytime vs Korea after-sunset)
- Hands/pose safety (no pointing, no extra fingers, no malformed hands)
- No public anchor, weathercaster, or CEO portrait drift
- No lounge, bar, or glamour shoot feel
- No readable text, logos, or fake UI in image

### FAIL criteria

- Identity drift (different woman, face drift, hair/glasses drift)
- Hand/finger failure (extra fingers, distorted hands, screen-covering gesture)
- Wrong time mood (Korea too bright/daytime; Global too evening)
- Wrong wardrobe family for selected profile
- Public anchor, weathercaster, or CEO dominance
- Over-glamour, lounge, or seductive night styling
- Malformed image, collage, split screen, or provider artifact
- Prompt contract violation (e.g. tablet policy wrong for program)

FAIL does not authorize automatic retry. New approval required for any follow-up call.

---

## 11. Baseline Comparison

Compare manual opt-in canary results against local accepted baselines (gitignored reference outputs):

| Program | Accepted baseline (local path) |
|---------|-------------------------------|
| Global 12:30 | output/keysuri_preview/image_canary/keysuri_global_canary_20260604_221233.jpg |
| Korea 18:30 | output/keysuri_preview/image_canary/keysuri_korea_canary_20260604_225207.jpg |

These baselines were produced under the **static default** prompt path (pre opt-in wording). Opt-in canary on 2026-06-04 profile_01 may match color family but not exact prompt wording.

**Clarifications:**

- Baselines are local QA references only
- Do **not** commit baseline or new canary images
- Rejected reference examples remain documented in KEYSURI_IMAGE_PROFILE_LOCK.md (e.g. Korea 223121.jpg for time mood failure — not for wardrobe evaluation)

For opt-in on dates other than 2026-06-04, baselines above are **identity/mood reference only**, not wardrobe color reference.

---

## 12. WARDROBE_LOCK / REFERENCE_USAGE_POLICY Mismatch Handling

Current production prompt contracts still attach static structures:

- wardrobe_lock allowed list: charcoal fitted suit, ivory or soft cream blouse
- reference_usage_policy must_preserve: charcoal fitted suit continuity, ivory or soft cream blouse continuity

Opt-in injection with non-profile_01 wardrobe (e.g. profile_03_graphite_champagne on 2026-06-05) may **conflict** with static lock/policy wording even when resolver and metadata are correct.

**R5B procedure rules:**

- Do not treat static lock/policy as automatically updated by opt-in injection
- Do not enable non-profile_01 production canary without an explicit decision:
  - amend lock/policy dynamically in a future code change, or
  - restrict manual opt-in canary to profile_01 dates until policy is aligned
- This document does **not** implement dynamic lock/policy alignment

Recommended conservative path for first manual opt-in canary: **2026-06-04 / profile_01_charcoal_ivory** with full understanding of wording diff vs static stem.

---

## 13. Rollback / Stop Rules

**Stop immediately and do not proceed** if any of the following occur:

| Condition | Action |
|-----------|--------|
| Default positive_prompt changed unexpectedly | Stop; investigate before any live call |
| ready_for_production_auto_call or ready_for_image_api_call flips true in offline report | Stop; fix before live call |
| Scheduler path touched | Stop; revert operational changes |
| Image API call without documented approval | Stop; treat as incident |
| More than one live call under single approval | Stop; document; require new approval |
| Today_Geenee or Tomorrow_Geenee files modified for this batch | Stop |
| Output image proposed for git commit | Reject commit |
| Gate/canary default changed to opt-in | Revert; default must remain non-injected |
| Tests fail | Stop; fix offline first |

Rollback for a failed canary: do not retry automatically; revert to default non-injected prompt path for all production-facing builders; preserve local output for QA notes only.

---

## 14. Future R5B Implementation Candidates

Design only. **No implementation in this document step.**

| Candidate | Purpose |
|-----------|---------|
| keysuri_canary_preflight.py | Check tests, flags, approval record, date/program/profile before live call |
| scripts/build_keysuri_wardrobe_opt_in_prompt_diff_report.py | Offline default vs opt-in diff for a given wardrobe_date_kst |
| scripts/run_keysuri_image_api_canary.py enhancement | Require explicit opt-in flag + approval env + preflight pass |
| tests/test_keysuri_canary_preflight.py | Unit tests for preflight checker |

Integration must not change default report/gate behavior without explicit profile-lock and ops approval.

---

## 15. Production Boundary

This document explicitly does **not**:

- Connect production wiring
- Enable image_auto_call or production auto-call
- Change Cloud Scheduler jobs or bindings
- Deploy or alter Cloud Run / GCP configuration
- Call Vertex image API or any image generation service
- Revive Tomorrow_Geenee programs or styling
- Change Today_Geenee image execution paths
- Commit or modify output/** artifacts
- Set use_daily_wardrobe_prompt_snippet=True by default anywhere

Wardrobe manual canary, when approved, remains a single-call exception under existing manual-approval patterns — not production rollout.

---

## 16. Recommendation

1. **Complete this R5B document** and review it offline.
2. **Do not implement** preflight checker or change canary scripts until review approves.
3. **Do not run** a live opt-in canary until:
   - all §4 preconditions pass
   - §6 prompt diff is reviewed and acknowledged
   - §8 manual approval is recorded
   - conservative target (2026-06-04 profile_01) is preferred for first opt-in call
4. After optional future preflight implementation, run **at most one** explicit manual opt-in canary with documented PASS/FAIL.
5. **Do not** move to automatic production wiring, Scheduler binding, or default opt-in enablement without a separate approved track beyond R5B.

R5A is complete for offline wardrobe resolver work. R5B defines the gate for the first manual opt-in image evaluation only.

---

*Document: GENIE Image Track R5B — production preflight and manual opt-in canary procedure. No implementation. No live call. No production wiring.*
