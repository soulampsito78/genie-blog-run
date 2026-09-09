# Today 2026-09-10: recovery and transient infrastructure self-healing

The 06:30 natural run `20260910_063029_today_genie_72848cab` failed on a Vertex
429 after TOP3 extraction. The natural Scheduler fired and the application ran,
but its failed artifact contained no usable body. Incident
`2026-09-10_today_genie_06-30` was reported at 06:45.

## Independently verified baseline

Before this change, origin/main and production both used
`e3c74549bcef08fa857db2d5077e3463a83012db` and image digest
`sha256:8d69c7748714b864fff0af0e9b357f695770b7297b0c8ad9f433a483b24a1534`.
Build `cc8a0693-09a5-462a-8ac4-b04294c24a66` succeeded, with the same resolved
Git source SHA. Revision `genie-blog-run-gcb-cc8a0693-09a5-462a-8ac4-b04294c24a66`
was Ready with 100% traffic, health 200, and no immediate revision ERROR logs.
It was not unnecessarily rebuilt or redeployed.

The existing retry implementation correctly distinguished transient provider
exceptions from permanent request/auth/config failures. Its defaults were safe:
three attempts, base sleep 4s, jitter at most 1s, cumulative sleep at most 45s per
model call. Environment overrides lacked hard upper bounds; this change caps
attempts at 3, base delay at 15s, total sleep at 45s and rejects non-finite values.
Existing downstream validation and customer-send authority are unchanged.

## Actual recovery and owner receipt

Exactly one logical incident recovery produced
`20260910_080444_today_genie_22a3d46a`, execution class `recovery`, using a fresh
live feed collected on 2026-09-10 around 08:04 KST. The target date is 2026-09-10;
2026-09-09 closed market sessions and overnight news are correctly identified.
The three selected source IDs were retained throughout.

The first returned payload had runtime and surface PASS, but final HTML review
found unsupported causal prose, a wrong office reference, and deterministic
padding. The owner mail was held. The existing recovery function described that
hold as a failed recovery and sent its failure report; this was a delivery/QA
hold, not another model failure. One agent editorial correction of this same
artifact removed those defects. It added zero model calls, zero image calls,
and zero extra recovery runs. The unchanged runtime validator and product
surface validator were rerun and both passed. This was explicitly recorded as
an editorial correction, not as a new model result or an automatic remediation
child. Existing auto-remediation excludes recovery children and was not bypassed.

Accepted HTML was rendered and read before delivery. SMTP accepted the single
owner recipient at 08:10:13 KST. Gmail INBOX message `1a0886fb409f9d25` was read in
full; the accepted HTML is byte-identical to the start of the received HTML.
Naver appended its own hidden receipt pixel. Accepted HTML SHA-256:
`88f2b877b5ae9bf7e8b50a795a765405a871432b10a1ad203fcdcbe941972872`.
Two generated CID images were present in the received message. The incident was
resolved and a success report followed. Owner approval remains pending; customer
status remains `not_sent`, and approval was not inherited.

Cost evidence: original natural run = one logical run, two text attempts
(TOP3 success + main 429), no internal retries or image calls. Recovery = one
logical run, two successful text calls, no transient retry log events, two
successful image requests. No auto-remediation model calls or paid canaries.
Recovery text usage: 25,544 input, 2,534 output, 4,404 reasoning tokens; the
runtime text-only estimate was USD 0.0250082, not a billing reconciliation.

## Runtime change

The watchdog previously only reported and waited for Admin recovery approval.
The provider exception also became an unstructured HTTP 500, so the persisted
artifact could not distinguish a proven transient fault from an unknown one.

The model API now preserves allowlisted typed exhaustion evidence and per-call
attempt counts in its HTTP 500 JSON. The orchestrator stores that evidence on
the failed artifact. The watchdog hydrates only the exact failed artifact after
the existing SLA grace period and admits automatic recovery only when:

- the program/date/slot/trigger and explicit natural execution class match;
- the artifact is explicitly unusable, failed, and has no validation result;
- exhausted 429/ResourceExhausted/TooManyRequests, 500/502/503/504, or
  DeadlineExceeded is proven by typed provider evidence;
- owner mail was not sent, customer status is known `not_sent`, no approval exists;
- no source, validation, product-surface, preflight, verification or unknown
  failure evidence is present; no prior recovery has occurred.

The current provider-evidence producer is the Today main API seam. Global and
Korea success paths and their provider clients are unchanged; missing evidence
in any program fails closed rather than inferring a transient class.

The existing `execute_approved_recovery` and `acquire_recovery_lease` boundaries
are reused. A durable recovery lease record uses GCS generation preconditions
(create with generation 0; updates compare the generation read). Local execution
uses an OS file lock. Lease acquisition completes before generation. Diagnostic
upserts cannot erase this independent lease record. An automatic attempt remains
spent on crash, unknown delivery outcome, child failure, or a stale incident
write, and cannot be reopened through Admin. Existing explicit manual retry
policy remains only for incidents without an automatic attempt.

Recovery requests disable the orchestrator's outer transport retry, so a lost
response cannot start another paid generation. Bounded internal Vertex retries
remain part of the same logical run. Recovery children are tagged and never
satisfy the original natural SLA or recursively recover. Reviewable content
continues to use the existing separate auto-remediation eligibility contract.

## Regression evidence

`tests/test_transient_self_healing_20260910.py` pins A–L: retry success,
exhaustion persistence, permanent failure, failed-slot visibility, grace, exactly
one recovery, concurrent watchdog calls, GCS CAS across independent instances,
stale upserts, successful Today/Global/Korea paths, preflight exclusions,
content-remediation separation, recovery-child failure, and customer-send guards.

Authoritative suite: **3612 passed, 32 skipped, 0 failed**.
The baseline also reported 32 skips; skipped optional checks are not counted as passes.
GENIE_PRODUCT_REGRESSION_GATE: **PASS** (363 tests, one skip).
Tests run offline; no paid canary was generated.

## Scheduler HTTP contract finding

Today_Geenee has attemptDeadline 300s, retryCount omitted (default 0),
maxRetryDuration 0s, minBackoff 5s, maxBackoff 3600s, maxDoublings 5.
Natural_Run_Watchdog has attemptDeadline 180s and the same retry configuration.
No Scheduler configuration or new recurring job was introduced.

The create-owner-review endpoint can still return HTTP 200 while its payload
reports response_status 500/email_sent false. This observability mismatch is
recorded separately; its HTTP contract was deliberately preserved in this task.
Google documents that retryCount=0 plus maxRetryDuration=0 performs no retries:
https://docs.cloud.google.com/scheduler/docs/configuring/retry-jobs
The watchdog's single recovery lease owns the new bounded recovery authority.

## Release

Use the unchanged cloudbuild.yaml path: build, offline product gate, push,
resolve immutable digest, create exact revision without traffic, verify digest,
and promote that exact revision. Final release SHA/build/revision/digest and
production checks are recorded in the execution closeout, after promotion.
