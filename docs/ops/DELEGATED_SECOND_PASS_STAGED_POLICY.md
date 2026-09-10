# Delegated second-pass review — Owner-approved target, activation pending

Task `GENIE_KEESURI_DELEGATED_REVIEW_GATE_001`; Owner final directive dated 2026-09-10 KST supersedes the first preparation's blanket automatic-remediation shutdown proposal. Product-policy choices below are already approved. The subsequent Option B decision authorizes clean-branch integration, validation, bounded fixes, commit, feature-branch push and a review PR. **LIVE DELEGATED SEND REMAINS OFF. MERGE / DEPLOY / ACTIVATION REQUIRE SEPARATE OWNER AUTHORITY.** Deployed customer send continues through the existing authenticated human-confirmation path until an exact deployment/activation is authorized.

## Authority and target flow

Keep Gemini briefing/image generation and the existing first-validation pipeline, including deterministic Python checks. Active programs: `today_genie`, `keysuri_global_tech`, `keysuri_korea_tech`. Tomorrow is retired/out of scope.

Existing generation and permitted pre-freeze repair → all required validation → freeze exact candidate → actual review email received/rendered → independent GPT Work review → complete PASS → authenticated delegated authority → current entitlement/verified-email/start-date/product/suppression evaluation → immutable recipient snapshot → durable publication/recipient and run/command reservations → customer SMTP outcome → separate receipt evidence.

NORMAL means unattended operation: audit/evidence only, no routine Owner approval request. Meaningful anomaly means HOLD and one diagnosed Owner exception packet. Missing, incomplete, unavailable, malformed, conflicting or timed-out review never authorizes delivery. Silence is not approval. Recovery of a Work-detected content anomaly is manual and creates a separately identified candidate requiring fresh first validation and second-pass review.

## Policy diff and canonical authority

| Prior requirement | Approved target | Deployment meaning |
|---|---|---|
| Customer Delivery Contract §1 requires an Owner approval for every publication | A normal exact candidate may use complete authenticated delegated Work PASS under this Owner policy; human approval remains a separate manual route | No live authority follows from this document or a caller boolean |
| Customer operation box says the human personally reviewed the publication | `HUMAN_OWNER_APPROVAL` permits human-review wording; `DELEGATED_AUTOMATION_PASS` / equivalent `DELEGATED_WORK_REVIEW` uses automated-review wording | Never label automated review as personal Owner approval |
| Architecture/operations require explicit operator action for normal sends | Verified normal delegated PASS may proceed unattended; exceptions hold | Customer web still cannot approve, send, reissue or mutate operations |
| Initial staged proposal required disabling all automatic content remediation | Classify repairs by the candidate freeze/review boundary, as specified below | A blanket shutdown is not required by the final Owner decision |
| Per-snapshot reservation alone is the duplicate boundary | Durable publication/product/date/recipient coverage plus run and command identity | Different executions and reissues must share the publication delivery boundary |

Unchanged: entitlement, verified delivery email, delivery start date, subscription/product eligibility, complaint/unsubscribe/hard-bounce suppression, frozen recipient snapshot, billing/delivery separation, duplicate protection, ambiguous-send reconciliation and provider-accepted versus actually received distinction. Customer-web SSOT describes these boundaries; operations owns approval authority.

## Automatic correction: exact existing behavior and permitted scope

The observed serving baseline has `auto_remediation.py` enabled by default and `Auto_Remediate_Reviewable` enabled. It classifies natural scheduled `review_required` / `product_review_required` output into `body_only`, `image_only` or `body_and_image`; terminal, finance/safety, infrastructure and unknown issue codes stop. It stamps an attempt before invoking the existing reissue runner, allows at most one attempt per natural parent, excludes children, persists parent/child/result/issue evidence and sends a corrected review email. It does not itself customer-send. September 9 Today parent `20260909_063102_today_genie_bc5aae92` and child `20260909_135155_today_genie_eee1cec6` are a persisted example; the child remained reviewable and unsent. This existing asynchronous behavior must not be confused with proof of second-pass authority.

The existing Keysuri generation path also performs deterministic parse/visible-text repairs and bounded generation recovery with repair and generation diagnostics. Existing Today body/image reissue paths are separate candidate-generation paths. None of these mechanisms becomes a GPT generation migration.

Apply these three cases mechanically:

1. **Before the candidate is frozen for Work:** existing bounded generation/validation repair may remain. Preserve its attempt/parent/child/issue/hash trace; rerun every required first-pass, render, source, product and image gate affected by the repair; freeze the final repaired candidate and review its actual newly received email. A prior parent email or validation PASS cannot cover the repaired child. A repair still failing checks holds. Merely naming an operation “pre-review” is insufficient if a frozen/reviewed candidate already exists.
2. **After freeze or Work PASS:** any material body, image, subject, source/link or publication-identity change creates a new candidate/version and invalidates the previous PASS. Do not mutate the reviewed candidate and send it using the old evidence. Re-freeze, rerun applicable validations and independently review the altered delivered result. Keep the previous evidence immutable.
3. **After Work detects an anomaly:** HOLD; stop automatic content rewrite/reissue for that candidate. Diagnose and prepare a correction/recovery recommendation locally. Production recovery/reissue needs the manual action already required by Owner policy, then the new candidate re-enters both gates. Do not silently correct and customer-send.

Existing scheduler retention is conditional on these protections. If an active correction path cannot distinguish these cases, that path must fail closed for frozen, reviewed or Work-held candidates until fixed; it must not inherit a previous PASS. No production scheduler or configuration change is authorized by this preparation.

## Review contract and exact-candidate binding

Required classes are CONTENT, SOURCE, IMAGE, EMAIL_RENDER, RUN_IDENTITY and DELIVERY_READINESS. The initial local evaluator's `content/sources/images/render/operations` fields represent the first four plus operational identity/readiness checks; the new classes must remain separately complete in authenticated review evidence. A checked box or Gemini result alone is not received-output review.

Bind the signed/authenticated review to run ID, product, publication date, immutable candidate/version, final customer HTML/body and subject hashes, required image roles and byte hashes, source/link set hash, review-policy version, reviewer identity/model, verdict and timestamps, plus the actual received mailbox/message/Internet Message-ID/raw MIME/render evidence. The adapter must establish how the operational email corresponds to the exact final customer candidate; whole-email byte equality is not expected when owner controls are removed, but customer content must be frozen before review and verified again before send. No content transformation after review may escape this comparison.

Required image roles: Today top+bottom, Korea top+bottom, Global top. A private URL being present is not visual inspection. Any inaccessible required pixels or unavailable render evidence yields an incomplete/unavailable result. A new child must not inherit the parent's message identity, verdict or recipient delivery claim reset.

Target verdicts: PASS, HOLD_ANOMALY, HOLD_INCOMPLETE, REVIEW_UNAVAILABLE, STATE_CONFLICT. Existing shadow equivalents map `HOLD` with anomaly reasons to HOLD_ANOMALY, operational/binding reasons to STATE_CONFLICT, `REVIEW_INCOMPLETE` to HOLD_INCOMPLETE, and `WORK_REVIEW_ERROR` to an unavailable/incomplete failure. Only complete PASS may qualify; every other verdict fails closed. Unknown reason/state is not silently normalized to PASS.

The isolated shadow checker validates attestation completeness and internal consistency. Shadow records use SECOND_PASS_SHADOW, approval_authority=NONE, customer_send_authorized=false and authenticity_verified=false. They do not prove actual visual/semantic work or authenticate the claimed GPT identity. Actual model/connector/render evidence and authenticated execution are separate prerequisites. Durable evidence failure must not preserve a successful-record claim.

## Truthful audit and notification

Human and delegated events use distinct machine-readable approval sources. For delegated decisions retain the Owner delegation policy/version, exact candidate, actual received-message evidence, reviewer/model, review verdict/time, final recipient snapshot, persistent duplicate claim, attempted delivery identity and SMTP outcome. Do not write OWNER_APPROVED or “personally reviewed by the Owner” for an automated decision. A shadow PASS is not an approval event.

An exception packet contains PRODUCT, RUN_ID, PUBLICATION_DATE, ANOMALY_TYPE, EXACT_PROBLEM, SUPPORTING_EVIDENCE, CUSTOMER_SEND_STATE, RECOMMENDED_RECOVERY and OWNER_ACTION_REQUIRED. Deduplicate repeated notifications for unchanged exceptions; normal success produces evidence only. Delayed email gets bounded rechecks before the absence is diagnosed as an operational exception. There is no timeout-based customer send.

## Duplicate protection, reconciliation and manual reissue

Retain existing immutable approval snapshots and application delivery commands. Per-run atomic claims prevent competing snapshots from each submitting the same run. Publication/product/date/recipient protection must also cover distinct child IDs, retries and process restarts. Customer identity should come from the trusted recipient resolver; caller-provided recipient lists or safety booleans cannot establish entitlement.

A crash after reservation or provider submission must leave a durable stop. Do not automatically delete claims for unknown, partial, refused or not-submitted outcomes. Investigate and reconcile before an explicitly authorized recovery. A held unsent publication can enter manual recovery with a new candidate identity; previously accepted recipients remain protected across reissue. SMTP acceptance is not inbox receipt, and provider-side exactly-once is not claimed.

## Rollout and manual-mode fallback

1. Complete local exact-candidate/authentication, recipient/suppression, publication duplicate, repair-boundary and manual-mode tests. Verify the actual cloud review path, including scheduled Gmail/private image/render access, durable evidence and bounded failure notification with the Owner Mac offline.
2. Evaluate the actual normal/historical abnormal cases with independent labels. State visual, source and semantic coverage and measured false-pass/false-hold denominators; synthetic contract tests alone do not establish content quality.
3. Prepare five publication days × three active slots = 15 prospective shadow opportunities, with a bounded schedule derived from actual receipt timings. Run the supported read-only mechanism without touching GENIE production state or customer delivery. Record absent candidates and unavailable reviews honestly; do not fill missing opportunities with invented normal cases.
4. Before any live transition, drain old writers; reconcile all historical SUBMITTED, OUTCOME_UNKNOWN, partial/refused/accepted state and command ledgers; preserve sent evidence and migrate required claims. Prove concurrent persistent-store behavior in an isolated environment. Retaining a tagged older revision is not proof it honors new claims.
5. Close the approved Option B repository integration through a tested feature branch and review PR. After sufficient real Mac-independent shadow evidence, present the exact merge/deployment/activation decision for the reviewed version. Merge, deploy, production configuration/scheduler/data/secret/IAM mutation and live send remain unauthorized. Repository integration does not turn a shadow PASS into production authority.

The target kill switch is an independent delegated-send OFF/manual mode evaluated at the final send boundary. OFF prevents delegated PASS from authorizing delivery while retaining the safe authenticated human flow and every snapshot/claim/receipt record. It must not require deleting evidence or reverting to claim-unaware code. On rollback, drain writers and retain/reconcile ledgers; never blindly resend. Current deployed human mode remains the live baseline until authorized activation. Document whether the final local kill switch was actually tested rather than treating this policy text as evidence.

Five-day shadow is a finite evidence requirement, not a claim that fifteen slots have completed. Require zero known abnormal candidates silently passed and explain all missing/incomplete/conflicting states. Report NORMAL_PASS, NORMAL_FALSE_HOLD, KNOWN_ANOMALY_CAUGHT, KNOWN_ANOMALY_MISSED and REVIEW_UNAVAILABLE with actual denominators. The initial suggested “at most one false hold” is an engineering checkpoint, not a new Owner policy or statistical guarantee; analyze causes instead of hiding them in an aggregate.

## Final prepared components and explicit integration boundary

`delegated_gate.py` implements the configured worker entry point, authenticated HMAC reviewer events, one-time event claims and immutable final customer payload. Policy is `genie-keesuri-second-pass-v2`; `DELEGATED_SEND_MODE` defaults to `OFF`, with `SHADOW` and `ON` as explicit modes. `ON` additionally requires the exact `GENIE_DELEGATED_AUTHORIZED_POLICY`. Reviewer keys/audience are trusted service configuration, never request booleans. Seven evidence fields represent the six review classes because EMAIL_RENDER separately covers the actual received email and the frozen final customer render. Model name is retained as reported, not falsely described as independently authenticated.

The received-mail broker checks actual raw MIME, run identity and original image bytes against the saved artifact. It recognizes only the narrowly specified Naver hidden read-receipt suffix as a transport addition; raw MIME and suffix fingerprints remain recorded. No material body difference is ignored. The final customer wording is made truthful before freeze and Work inspection; no post-PASS rewrite is permitted.

`delegated_delivery_safety.py` reads the existing PostgreSQL authority and freezes actual RecipientSnapshot identities. Its configured factory requires authenticated, fresh unsubscribe/complaint/hard-bounce ingestion evidence bound to the configured customer database authority. Signed suppression events update actual delivery records, retain idempotency/audit and signal required lifecycle follow-up without silently changing billing. Environment flags cannot substitute for ingestion evidence. Actual provider/unsubscribe ingress, lifecycle follow-up, secrets and cloud access remain integration acceptance checks; local signatures and tests do not prove a deployed feed.

`admin_approval.py` and `admin_store.py` connect the existing human confirmation path to the same recipient and durable publication guard after cutover. `DELEGATED_SEND_MODE=OFF` disables delegated authority but never disables the persistent cutover guard. Existing evidence/claims stay in place. A configured and healthy recipient authority is also required in manual fallback; reverting to an older claim-unaware revision is not a safe rollback.

`auto_remediation.py` now checks durable received-candidate bindings and delegated-review state before proposing automatic repair. Frozen/reviewed/Work-held candidates require manual recovery; unavailable boundary evidence holds. Existing unfrozen generation repair remains allowed under its prior validation/attempt restrictions. Cross-process tests verify the persistent boundary.

Controlled integration sequence: keep mode OFF; install prepared dependencies/configuration in an isolated environment; connect and verify the protected Gmail/final-render/reviewer/signing/suppression/notification chain; demonstrate Mac-independent scheduled execution; complete the finite shadow cohort and adjudicate anomalies/false holds; drain every old manual/delegated writer; reconcile prior accepted/unknown publications and seed the once-only cutover; verify manual fallback; only then seek the authorized production deployment/activation gate. No key, IAM, DB, scheduler or customer-delivery production change is made by this prepared patch.
