# GENIE Phase 1 README Draft

Status: preserved draft, not canonical.
Source: local README.md working-tree rewrite before README restore.
Reason preserved: contains potentially useful Phase 1 governance notes, but requires reconciliation with current Today_Geenee / Kee-Suri review-operation policy and Tomorrow_Geenee dormant status before use.

Important:
This draft is not the canonical README.
Do not treat Tomorrow_Geenee as an active implementation gap.
Today_Geenee and Kee-Suri are the active operating tracks.

---

# genie-blog-run
Backend-centered automation system for the Genie persona briefing workflow.
This repository generates, validates, renders, and delivers Genie briefing drafts through an email-first handoff flow.
The current Phase 1 goal is **not full auto-publishing**.
The current Phase 1 goal is:
1. Generate `today_genie` / `tomorrow_genie` briefing drafts.
2. Validate the result safely.
3. Render an almost-final customer-facing email draft.
4. Send the draft by email.
5. Expose the minimum admin surface needed to review status, failures, and follow-up actions.
---
## 1. Current Product Definition
Genie is a single character persona operating in two modes.
### `today_genie`
Morning pre-market financial briefing.
- Role: financial news anchor
- Priority: strict factual grounding
- Risk: financial hallucination, unsupported market claims, weak briefing authority
- Output goal: customer-readable almost-final briefing email
### `tomorrow_genie`
Next-day weather and lifestyle briefing.
- Role: weather / lifestyle broadcast caster
- Priority: grounded weather-based preparation
- Risk: invented precise weather values, generic lifestyle filler
- Output goal: customer-readable almost-final preparation email
---
## 2. Current Phase 1 Goal
Phase 1 is complete only when the system can produce and send a customer-facing almost-final email draft with enough operational visibility to review the result.
Phase 1 includes:
- `today_genie` / `tomorrow_genie` generation
- JSON validation
- channel-aware rendering
- email handoff
- workflow status tracking
- review-required handling
- minimum admin visibility
Phase 1 does **not** include:
- full Naver auto-publishing
- Playwright-based unattended production publishing
- long-term browser/session/selector maintenance
- large customer-facing dashboard
- fully unmanned final publishing
---
## 3. Current Source of Truth
The current project authority is the v3 document set.
Primary authority:
1. `GENIE_PROJECT_SSOT_v3`
2. `GENIE_PROJECT_SSOT_v3 반영본`
3. `GENIE_PROJECT_MASTER_GOVERNANCE`
4. `GENIE_email_UX_implementation_governance_v1 반영본`
5. `GENIE_email_handoff_UX_reference_v1 반영본`
6. `GENIE Current Status Snapshot`
7. `GENIE_admin_UI_spec_updated_with_revision_flow_2026-04-13 반영본`
8. `GENIE_Production_Rollout_Runbook_v1 반영본`
Older v1/v2 documents are reference material only unless they do not conflict with the v3 direction.
When documents conflict, follow this rule:
```text
SSOT v3 > latest reflected governance docs > implementation governance > older v2/v1 reference docs

⸻

4. Current System Focus

The current project is no longer only about basic infrastructure bring-up.

The current focus is:

* real received email quality
* email handoff structure
* today_genie briefing authority
* numeric table correctness
* image placement and perceived quality
* operation box accuracy
* minimum admin alignment

A successful send is not the same as product readiness.

email_sent=True means delivery-layer success.
It does not automatically mean handoff quality is complete.

⸻

5. Recommended Runtime Flow

Scheduler or manual trigger
↓
API / runner entry point
↓
mode selection
↓
runtime input assembly
↓
prompt build
↓
LLM generation
↓
JSON parse
↓
validation
↓
rendering
↓
email handoff
↓
workflow status / admin surface

⸻

6. Important Files

Core runtime

* main.py
    * API/runtime entry point
    * mode routing
    * runtime metadata handling
    * validation result propagation
* prompts.py
    * persona rules
    * mode prompts
    * output schema guidance
    * prompt assembly
* renderers.py
    * email HTML rendering
    * section order
    * image placement
    * operation box rendering
    * mobile-first handoff structure

Policy / validation

* validators.py
    * JSON structure checks
    * required field checks
    * strict-mode issues
    * review/block decision support
* publishing_policy.py
    * downstream permission logic
    * suppress / review_required / emailed routing

Orchestration / delivery

* orchestrator.py
    * API call + policy + downstream flow
* run_orchestrator.py
    * worker / job entry point
* email_sender.py
    * SMTP email delivery

Optional / future scope

* naver_draft.py
    * Playwright-based Naver draft automation
    * currently not part of Phase 1 completion

⸻

7. Official Workflow States

Use these states carefully.

Core Phase 1 states

* generated
* validated
* emailed
* review_required
* failed

Operational failure states

* infra_failed
* delivery_failed

Revision / request states

* revision_requested
* revision_rejected
* revision_completed
* revision_limit_reached

Future / optional states

* assets_ready
* drafted
* published

Important:

review_required is not a failure.
emailed is not the same as product-quality complete.
published is not a Phase 1 requirement.

⸻

8. today_genie Strict Mode

today_genie must not fabricate:

* market index numbers
* interest rates
* exchange rates
* earnings
* analyst opinions
* news headlines
* schedules
* stock-specific claims

If critical market input is missing, the system must:

1. shorten the briefing,
2. mark the result as review-required,
3. or block downstream delivery.

Do not create a full-looking financial briefing from thin input.

A safe but empty result is also a failure.
A rich-looking but unsupported result is also a failure.

⸻

9. tomorrow_genie Weather Grounding

tomorrow_genie must not invent precise weather values.

Weather content must be grounded in supplied weather input.

If critical weather fields are missing, the system must degrade conservatively instead of fabricating values.

⸻

10. Email Handoff Requirements

Email is the main customer handoff surface.

The customer should be able to read the email body and understand the draft without opening an attachment or relying on a separate dashboard.

Recommended email surface order:

top image
mode label
title
summary
main briefing section
TOP 3 / key points
numeric board when applicable
risk / caution
one-line decision basis
hashtags
operation box
bottom image

The operation box must stay below the content body.

The operation box is a read-only operational surface.
It must not imply that the whole admin system is complete.

⸻

11. Numeric Section Rules

For today_genie, numeric sections must be treated as correctness-critical.

Check:

* index name
* index value
* percentage change
* sign direction
* consistency between narrative and table

Failure examples:

* index value is - or 0
* point movement is placed in the index value field
* percentage sign is reversed
* table values conflict with narrative text
* image placement changes while fixing numbers

⸻

12. Image Rules

Image success has two layers:

1. The image exists and is placed correctly.
2. The image feels appropriate and improves the email handoff.

Do not treat these as the same.

The current project standard requires perceived quality, not just asset existence.

⸻

13. Playwright / Naver Policy

Naver auto-publishing is not a Phase 1 requirement.

Playwright-based automation is optional / future scope.

Current default priority:

Generate
↓
Validate
↓
Render email handoff
↓
Send email draft
↓
Review / request / admin follow-up

Do not make Playwright or Naver draft automation block Phase 1 completion.

⸻

14. Runtime Environment

Core environment variables:

* PROJECT_ID
    * Google Cloud project ID used for Vertex AI initialization.
* VERTEX_LOCATION
    * Vertex AI location / region.
    * Default: global.
* VERTEX_MODEL
    * Gemini model name.
    * Default: gemini-2.5-flash.

Market input

* TODAY_GENIE_OVERNIGHT_US_MARKET_JSON
* TODAY_GENIE_MACRO_INDICATORS_JSON
* TODAY_GENIE_TOP_MARKET_NEWS_JSON
* TODAY_GENIE_RISK_FACTORS_JSON

If unset or invalid, the related input is treated as missing.

Missing critical market input must not be replaced with fabricated content.

Weather input

* OPENWEATHER_API_KEY

If unset, weather context may be missing.
The system must not invent precise weather values.

Orchestrator

* GENIE_API_URL
* GENIE_REQUEST_TIMEOUT
* GENIE_API_RETRIES
* GENIE_API_RETRY_DELAY_SEC

Email delivery

* SMTP_HOST
* SMTP_PORT
* SMTP_USER
* SMTP_PASSWORD
* SMTP_APP_PASSWORD
* SMTP_PASSWORD_FILE
* SMTP_APP_PASSWORD_FILE
* EMAIL_FROM
* EMAIL_TO

Production credentials should use secret files when possible.

Optional Naver draft automation

* NAVER_ID
* NAVER_PASSWORD
* NAVER_APP_PASSWORD
* NAVER_PASSWORD_FILE
* NAVER_APP_PASSWORD_FILE
* NAVER_BLOG_ID
* NAVER_HEADLESS
* NAVER_DRAFT_TIMEOUT_MS

Naver / Playwright automation requires a separate worker image or install step with Chromium.

The Genie API container should not be forced to carry browser automation unless explicitly required.

⸻

15. Current Development Priorities

1. Confirm active runtime path.
2. Inspect main.py and renderers.py.
3. Verify actual received email output.
4. Stabilize today_genie handoff quality.
5. Verify numeric table correctness.
6. Verify image placement and perceived quality.
7. Keep the operation box read-only and non-overstated.
8. Avoid changing body, image, admin, and prompt layers in one batch.
9. Only adjust prompts.py after runtime/rendering issues are confirmed.
10. Treat actual received email as the final truth.

⸻

16. Development Rules

* Do not claim completion without checking the actual code and output.
* Do not treat local HTML as final if actual received email differs.
* Do not treat email_sent=True as product completion.
* Do not expand scope back to Naver auto-publishing by default.
* Do not move Playwright into the critical path for Phase 1.
* Do not modify body, image, admin, and prompt layers in one uncontrolled batch.
* Do not assume admin features are live unless they are implemented and verified.
* Do not fabricate missing market or weather data.

⸻

17. Current Definition of Done

Phase 1 Done

Phase 1 is done when:

* today_genie and tomorrow_genie can be generated.
* JSON validation works.
* email rendering works.
* email delivery works.
* actual received email is readable as an almost-final draft.
* today_genie strict mode prevents unsupported financial claims.
* numeric sections are correct.
* image placement does not break the handoff.
* operation box does not overstate the admin implementation.
* minimum admin visibility exists for status, failures, and review-required handling.

Not Required for Phase 1

* final Naver publishing
* Playwright-based unattended operation
* complete revision backend
* large customer dashboard
* full auto-publishing

⸻

18. Final Operating Principle

This repository should not merely prove that generation and email sending work.

It must prove that the customer receives an almost-final draft that is safe, readable, useful, and operationally traceable.
