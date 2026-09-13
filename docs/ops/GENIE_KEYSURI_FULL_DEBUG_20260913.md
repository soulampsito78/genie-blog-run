# Genie / KeeSuri full debug closeout — 2026-09-13

## Decision summary

The local candidate is technically ready for release, but production is **NO-GO
for delegated customer submission until this candidate is merged and deployed**.
The production service inspected on 2026-09-13 still serves commit `231c41e` at
100% traffic and therefore still contains six process-global rich-email mode
mutations. `DELEGATED_SEND_MODE` is already `ON`, so the 2026-09-14 delegated
review automations must not be allowed to submit against that old revision.

This work did not send customer or Owner-review mail, invoke a Scheduler job,
publish to Naver, run Gemini, call an image model, change production, alter an
automation, or deploy a revision.

## Root causes

### 1. Historical 2026-09-11 Global 12:30 HTTP 500

The Global response parser accepted a schema-valid model payload whose English
headlines echoed source evidence. The canonical post-enrichment reader boundary
then correctly withheld all five echoed headlines, leaving five empty reader
headline fields. The renderer performed another validation pass and raised a
`ValueError`. That unexpected exception reached the endpoint as HTTP 500 before
the service wrapper could persist the normal failed-run artifact.

The exact five headlines from the natural 12:30 run were not persisted and must
not be reconstructed as fact. The incident regression uses the five distinct
English headlines from the persisted same-day 11:45 preflight as a
representative input and explicitly records that provenance limitation.

The existing remediation on this branch is correctly wired:

- the same canonical reader boundary runs after parse and enrichment;
- a five-headline reader failure becomes structured
  `keysuri_reader_surface_blocked` plus five precise headline-missing issues;
- Global can spend only the one remaining model call within the two-call budget;
- an incomplete prior parse cannot be restored as fallback;
- a second incomplete result becomes a safe validation failure, not a renderer
  exception;
- the service wrapper persists the failed run before image or SMTP work;
- approval and customer preparation fail closed when reader-surface proof is
  missing, false, or incomplete.

### 2. Test environment leakage and order dependence

Several `unittest` classes assigned customer-recipient and SMTP environment
variables in `setUp` but did not restore them. A class-level `patch.dict`
attempted as an initial repair was also insufficient: the decorated test method
starts after `setUp`, so it snapshots the already-mutated environment and later
restores the leaked values.

The concrete failure was reproducible by running a KeeSuri customer-delivery
test before the delegated authority suite. The leaked test recipient was then
treated as an unauthorized environment cohort, producing
`ADMIN_BETA_ENV_RECIPIENTS_NOT_AUTHORIZED`; a broader reordered run produced 11
false failures.

The repair starts the environment patcher as the first action in each affected
`setUp` and registers cleanup before any assignment. The original
`internal_jobs` test is also locally scoped with `patch.dict`, and the remaining
single-method URL mutation is locally decorated. Execution-before/after
snapshots for nine affected modules are now identical.

### 3. Production rich-email process mutation

Six legitimate rich-email call paths used
`os.environ.setdefault("GENIE_EMAIL_RICH_MODE", "1")`. In a long-lived worker,
the first eligible call permanently changed process-global configuration for
later jobs and tests. The affected paths covered Today orchestration and
reissue, Today customer delivery, KeeSuri service delivery, and KeeSuri customer
delivery.

The patch replaces that mutation with a call-scoped
`allow_rich_delivery=True` capability accepted only by the shared sender. The
low-level sender remains fail closed by default. Semantics of the former
`setdefault` are preserved exactly: an absent environment key permits a trusted
internal call, while an explicitly configured `0`, `false`, or empty value is
still an operator kill switch and blocks SMTP.

## Changed files

Runtime:

- `email_sender.py`
- `keysuri_customer_delivery.py`
- `keysuri_service_full_run.py`
- `orchestrator.py`
- `today_geenee_customer_delivery.py`
- `today_genie_reissue.py`
- `today_genie_service_full_run.py`

Tests:

- `tests/test_admin_routes.py`
- `tests/test_batch_8_3_today_geenee_delivery.py`
- `tests/test_beta_customer_recipients.py`
- `tests/test_email_sender_trace.py`
- `tests/test_keysuri_customer_delivery.py`
- `tests/test_keysuri_internal_jobs.py`
- `tests/test_today_genie_orchestrator_images.py`

This report is the only documentation file added by the debug closeout.

## Verification evidence

All commands ran from the isolated candidate worktree. No customer-send switch
or Scheduler endpoint was invoked.

- Focused regression: **399 passed**.
- Exact two-test order reproduction: **2 passed**.
- KeeSuri customer-delivery then delegated-authority order: **55 passed**.
- Reverse order: **55 passed**.
- The same two orders with the September 11 incident suite: **66 passed** in
  each direction.
- Affected-module environment snapshots: nine modules, all
  `ENV_CHANGED={}`.
- September 11 incident suite: **11 tests**, covering all five withheld
  headlines, no evidence-prose leakage, bounded recovery, safe failure,
  durable artifact evidence, recovery classification, and customer-send
  defenses.
- Product regression gate: **374 tests run, 1 skipped, PASS**;
  `TECHNICAL_TEST_PASS`, `RUNTIME_SAFETY_CONTRACT`,
  `CUSTOMER_SURFACE_CONTRACT`, and `GENIE_PRODUCT_REGRESSION_GATE` all PASS.
- Full suite on the final code candidate: **3,938 passed, 33 skipped**.
- Python compilation and whitespace/diff validation: PASS.

The code-only candidate diff SHA-256 before adding this report is
`ad3a43d5a452a8292e049830aaf6e9f75bfa25534d7cadfd53a64919f1cd39ea`.
The report-inclusive diff checksum is recorded in the release handoff after the
file is complete; embedding that value here would make the hash
self-referential.

## Live no-send smoke

Read-only live RSS smoke was run for both KeeSuri editions with `--no-email`,
without Gemini or image generation.

Global:

- result `ok=true`, validation `PASS`;
- 88 fetched items, 84 scored source candidates, five final selections;
- `send_attempted=false`, `send_block_reason=send_not_requested`;
- no Gemini, image API, admin-run mutation, Naver publication, or email side
  effect.

Korea:

- result `ok=true`, validation `PASS`;
- 36 fetched items, 34 normalized candidates, five final selections;
- `send_attempted=false`, `send_block_reason=send_not_requested`;
- no Gemini, image API, admin-run mutation, Naver publication, or email side
  effect.

An initial sandboxed Global attempt could not resolve public feed hosts and
returned zero items. The same explicit no-email command succeeded when network
read access was allowed. That first result is an execution-environment limit,
not a feed or application failure.

## Current operational state

Read-only Cloud Run inspection on 2026-09-13 established:

- production commit label and `COMMIT_SHA`: `231c41e5b235f473502fee4ac765ec188bfe624f`;
- 100% traffic revision:
  `genie-blog-run-gcb-c9057e8b-7446-4157-9169-3a529e6cef5f`;
- service Ready and RoutesReady;
- `DELEGATED_SEND_MODE=ON`;
- recipient authority is the admin beta delegation path;
- the production commit still contains all six process-global rich-mode
  `setdefault` calls removed by this candidate.
- the current `c905...` delegated-authority build evidence is **17 passed**.
  A correction record that says `delegated_release_gate_passed=18` is a P2
  evidence-count mismatch and must not be repeated as build fact.

Therefore a green local suite is not production evidence. Deployment and exact
revision verification are release blockers for the September 14 delegated
submission window.

## Automation helper pinning finding

The Today, Global, and Korea Spark automations are active and preserve their
agreed schedules, model `gpt-5.3-codex-spark`, `xhigh` reasoning, failure-only
notifications, observation/final distinction, and no-resend guard. However,
all three prompts invoke the submission helper by an absolute path inside this
temporary candidate worktree. The configured project working directory points
to a different Owner checkout which is both dirty and far behind current
`origin/main`; it cannot safely replace the helper path.

This is a reproducibility and pinning P1. It is not safely repairable by merely
editing a repository file: the active automation records live outside the
repository. The release must create a clean, dedicated checkout pinned to the
merged release SHA and then update only the helper path in the three automation
prompts. The schedules, time zone interpretation, model, reasoning effort,
notification policy, evidence paths, fallback/escalation wording, status, and
historical no-resend ID must remain byte-for-byte equivalent unless separately
approved.

Before and after the update, capture sanitized automation configuration hashes
and verify:

- the pinned checkout `HEAD` equals the merged release SHA;
- the pinned checkout is clean;
- the helper is executable and is the file at that SHA;
- each automation references only that pinned helper;
- no automation references this temporary worktree;
- the three recurrence rules and model settings are unchanged.

## Safe release, verification, and rollback procedure

1. Freeze the final diff and record both the code-only and report-inclusive
   checksums. Re-run diff validation, the focused gate, product gate, and full
   suite. Obtain independent QA PASS and confirm no direct P0 from safety
   review.
2. Commit on the feature branch, push that exact commit, open/update the PR, and
   merge through the repository's normal review path. Confirm the merged
   `origin/main` commit contains the candidate commit and record both SHAs.
3. Before any delegated review window, temporarily pause the three product
   review automations if release verification is still in progress. Do not
   change their recurrence/model contract and do not run them manually.
4. Let the configured Cloud Build run from the merged main SHA. Its existing
   `cloudbuild.yaml` builds the SHA-tagged image, runs the offline product gate
   and delegated-authority gate, pushes the image, resolves its immutable
   digest, creates an exact no-traffic revision, verifies the deployed digest,
   and promotes only that revision to 100%.
5. Require every Cloud Build step to succeed. Record build ID, source SHA,
   immutable image digest, revision name, and gate logs. A build from a
   different SHA is not acceptable evidence.
6. Read back Cloud Run and require: latest ready revision equals the promoted
   revision, traffic is exactly 100% on it, the `commit-sha` label and
   `COMMIT_SHA` equal merged main, the deployed digest equals the resolved
   digest, service conditions are Ready, and the delegated mode/authority and
   explicit rich-mode kill-switch value match the approved configuration.
7. Call only the public read-only health endpoint and repeat the Global and
   Korea no-email smoke. Do not call a Scheduler endpoint, review submission
   endpoint, customer approval endpoint, or any send path.
8. Create the clean release-SHA checkout and update the three Spark automation
   helper paths as described above. Restore ACTIVE status only after path,
   schedule, model, evidence, no-resend, and notification-policy comparisons
   pass. Do not manually trigger an automation as proof.
9. The release is GO for the next natural slot only when steps 1–8 are complete.
   If they are not complete before the review window, keep the affected
   automations paused and report a decision-ready hold.
10. Observe each September 14 natural slot without manually invoking it. A
    Scheduler HTTP 200 is not publication success: reconcile the persisted run
    artifact's `response_status`, validation state, `email_sent`, actual Owner
    mail receipt, and watchdog incident state. Record disagreement as an
    observability failure rather than promoting the HTTP status to success.

The recovery exactly-once guarantee applies to the automatic recovery attempt.
It does not prohibit a later, explicit Admin re-approval after a failed attempt.
Every recovery child remains `customer_send=0`; recovery itself never grants or
performs customer delivery.

Rollback is fail closed:

1. Pause the three delegated product automations before changing traffic.
2. Route 100% back to the last recorded known-good revision and verify its
   digest and Ready status.
3. Because that previous revision retains this P1, keep delegated submission
   disabled or the automations paused; rollback restores service availability,
   not delegated-send eligibility.
4. Preserve failed-build, revision, and automation evidence. Fix forward through
   the same reviewed pipeline. Never compensate with a manual customer send or
   Scheduler run.

## Remaining warnings and limits

- The 33 skipped tests are optional/external integration cases; they are not
  failures, but production persistence and provider integrations still require
  post-deploy read-only verification.
- The runtime uses Python 3.9, which now emits end-of-life warnings from Google
  client libraries, and the local interpreter reports a LibreSSL compatibility
  warning from `urllib3`. These did not fail this release but should be handled
  as a planned runtime upgrade.
- Live no-send smoke covered current RSS collection and selection only. It did
  not call Gemini, render a newly generated briefing, generate images, or prove
  SMTP acceptance.
- The natural 2026-09-11 Global raw response/source artifact was not persisted;
  the incident's exact five natural-run headlines remain unknowable.
- The temporary candidate worktree and the dirty Owner checkout are not valid
  long-term automation runtimes. A clean release-SHA checkout is mandatory.
- Safety review found no direct P0 in the final code candidate. Customer GO is
  still conditional on deploying this patch and pinning the automations to the
  clean release checkout; Scheduler and preflight configuration remain out of
  scope and unchanged.
