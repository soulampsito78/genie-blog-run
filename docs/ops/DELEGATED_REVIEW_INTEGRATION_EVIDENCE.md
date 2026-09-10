# Delegated review candidate: integration closeout

**LIVE DELEGATED SEND REMAINS OFF. MERGE / DEPLOY / ACTIVATION REQUIRE SEPARATE OWNER AUTHORITY.**

Task `GENIE_KEESURI_DELEGATED_REVIEW_GATE_001`, 2026-09-10 KST. This is the production candidate for changing normal GENIE × KEESURI publications from per-publication human approval to exception-based independent Work review. It prepares that transition; it does not enable automatic publishing. The Owner's Option B authorizes clean branch → validation → bounded fixes → commit → feature-branch push → review PR only.

## Source and production boundary

Fresh remote/main and branch base: `b35d2fb30c1985b1a2dc015f968b13831d7d170d`. Integration branch: `ops/delegated-review-gate-001`. The final 25-file prepared patch applied without conflict to a separate clean clone. The Owner's distinct checkout at `ef6c7bdec9f5d6b059810c1e2c1356517192b886` and its 33 existing dirty entries were not used as input or edited.

Fresh read-only runtime inspection still found revision `genie-blog-run-gcb-3a7196eb-50e3-46d0-85aa-8259ded77280`, matching the base commit and serving 100% traffic. Today 06:30, Global 12:30 and Korea 18:30 KST weekday schedules remain unchanged; Tomorrow remains paused. The serving baseline has no delegated modules or delegated-mode setting and retains the authenticated human approval path. This branch defaults `DELEGATED_SEND_MODE` to OFF and installs no live route, cloud runner, key, scheduler or production configuration.

The inspected Cloud Build trigger listens only to pushes matching `^main$`, with no PR event. The repository has no GitHub Actions workflows or repository webhooks. The feature branch therefore does not match the observed deployment trigger. **The main trigger does deploy and promote traffic: never merge or push main as part of this closeout.** Build files and trigger configuration are unchanged.

## Final clean-base validation

| Check | Final result | Scope |
|---|---|---|
| Entire repository `pytest` suite | **4,262 passed, 0 failed/errors, 19 skipped** | 4,281 collected; includes real PostgreSQL customer tests and all gate regressions. |
| Existing offline product release script | **362 passed, 1 skipped, 0 failed** | 363 run; overlaps the full suite and is not added again. |
| Separate historical-mail precheck harness | **16 passed, 0 failed** | Local historical-evidence checks outside the repository suite; no live approval authority. |
| Authenticated gate | 91 passed | Included in full suite; 14 added during adversarial remediation. |
| Delivery safety / actual PostgreSQL gate adapter | 64 / 28 passed | Included; PostgreSQL includes 8 new suppression-precedence cases. |
| Repair boundary / no-send shadow | 8 / 91 passed | Included; persistent boundaries and incomplete outcomes. |
| Patch/diff/secret-evidence review | Passed | Only intended source, tests and sanitized review documentation; no private mail/image bytes or credentials. |

Unique passed checks including the separate mail harness: **4,278**. The full run produced 24 existing dependency compatibility warnings under Python 3.9.6. The isolated database was PostgreSQL 16.14 with real migrations and transaction rollback. The 19 skips require absent production-proof bodies, approved image assets or preview fixtures; their exact names/reasons are preserved in the [sanitized validation record](evidence/delegated-review-integration-20260910.json). They are not claimed as passing or supplied by copying the Owner's untracked files.

Production credentials and mutation settings were not inherited. A validation-only Python audit guard was loaded before pytest and inherited by Python subprocesses; it rejected external socket/DNS calls and provider CLIs while allowing the dedicated local PostgreSQL Unix socket. Fifteen DNS attempts were blocked during the full suite. Provider dispatch tests used injected/mocked SMTP paths. No real customer mail or production database write occurred. The sandbox exception used for database tests was required for the local Unix socket, not provider access.

The original unmodified base was also run in the same isolated conditions: **3,963 passed, 12 failed, 19 skipped**. All 12 failures belonged to the D3 conversion API fixture: its fixed clock is August 18, while a freshly migrated catalog uses the September 10 database creation time. The service correctly considers that catalog unavailable at the earlier test date. The committed correction changes only the test fixture's initial catalog availability inside its rollback transaction. Prices, products, versions, VAT, service date checks, migrations and billing/runtime code remain unchanged. The corrected D3 module passes all 20 cases in the final suite; the original failing baseline output remains in local evidence.

## Bounded adversarial fixes

1. A meaningful anomaly HOLD was originally recorded only by event ID; a new signed event could issue PASS for the same candidate. An authoritative ON-mode anomaly now latches the run for manual new-candidate recovery. Temporary incomplete/unavailable attempts can retry with complete fresh evidence; SHADOW outcomes cannot change the live transition state.
2. A successful human HOLD could race the last candidate read before SMTP. Human HOLD/reopen and human/delegated provider handoff now share a bounded append-only journal using existing GCS create-if-absent/local O_EXCL. Conflicting processes can win only one next transition. Once handoff wins, later HOLD reports that it cannot retract the handoff. Corrupt/partial storage and exhausted bounds stop for reconciliation. Six independent-process actors and the actual human-HOLD interleaving are covered.
3. DB-only manual fallback still consulted the old environment recipient list before loading its authoritative plan. The builder now loads the plan first, product preparation respects explicit recipients, and guarded readiness checks SMTP configuration without substituting legacy recipient authority. Real preparation boundaries for all three products are exercised.
4. Later hard-bounce events could overwrite stronger complaint/unsubscribe/manual suppression. Ingestion now preserves the stronger effective reason and first suppression timestamp, and audits the incoming and effective reasons separately. Eight real database regressions cover the orderings. It does not change billing ownership or authorize re-consent.

Independent follow-up review found no additional concrete blocker for a review PR after these fixes. That is not a claim of live operational readiness.

## Reproduction and exact evidence

Run from the feature checkout with its normal runtime requirements plus `requirements-customer.txt`, pytest and httpx available. Use a **fresh disposable PostgreSQL database named `genie_customer_test`**, because the existing migration-precondition fixture derives temporary database names from that exact test URL. Do not set the test variable to a customer/production database. Use a dedicated Unix socket and non-production test role; remove real provider credentials and enforce offline execution in the test harness.

```text
CUSTOMER_TEST_DATABASE_URL=postgresql+psycopg://TEST_ROLE@/genie_customer_test?host=TEST_SOCKET_DIRECTORY&port=TEST_PORT
python -m pytest -q --junitxml=integration-full.xml
python scripts/run_product_regression_gate.py
```

The environment variable above must be exported or supplied to the test process. Existing customer fixtures migrate the disposable database and roll back individual test data. Do not run simultaneous suites against its scratch migration databases. The release gate's production container definition also specifies network isolation, but neither a Cloud Build nor a deployment was run here.

The [machine-readable validation record](evidence/delegated-review-integration-20260910.json) contains per-suite counts, all missing-fixture skips, exact tested Python-file hashes and raw evidence digests. Raw logs, the validation-only network guard and private image/mail evidence stay in the Owner's local task evidence; they are not published in this repository. The earlier 595-pass report is historical context and does not replace this clean-base run.

## Policy, rollout, manual mode and next phase

- [Approved policy diff and exact-candidate review contract](DELEGATED_SECOND_PASS_STAGED_POLICY.md)
- [Delivery entitlement contract](../web/CUSTOMER_DELIVERY_ENTITLEMENT_CONTRACT_v1.md)
- [Rollout and manual fallback requirements](DELEGATED_SECOND_PASS_STAGED_POLICY.md#rollout-and-manual-mode-fallback)
- [Finite 15-slot shadow protocol and notification contract](DELEGATED_REVIEW_SHADOW_PROTOCOL.md)

Manual fallback is `DELEGATED_SEND_MODE=OFF` with guarded code and all cutover/recipient/publication/transition evidence retained. Do not restore an older writer that bypasses these claims. OFF cannot retract a provider handoff; accepted/partial/unknown attempts require reconciliation rather than blind retry. New manual anomaly recovery candidates need their own exact review. A normal delegated audit must say `DELEGATED_WORK_REVIEW`, not individual human approval.

The current code records a final guard failure before provider submission as `NOT_SUBMITTED_FINAL_GUARD_BLOCKED`, retains its publication and recipient claims, and deliberately has no automatic recovery/reissue release. Manual fallback also blocks when recipient authority, suppression ingestion, duplicate claims or transition evidence is unhealthy. These are safety requirements, not reasons to grant a customer right from the legacy beta address list.

The next phase is operational evidence. The registered **local** Sep11/14/15/16/17 × three-product shadow remains read-only, with **0/15 completed at closeout preparation**. It does not prove Mac-independent cloud execution. Actual cloud Gmail/authentication, both render captures, protected review transport, recipient/suppression ingress and lifecycle follow-up, durable evidence and independently observed failure notifications still require integrated qualification. An all-HOLD cohort or a synthetic normal PASS does not establish normal unattended operation; measure real normal/false-hold/anomaly/missing outcomes without inventing confidence from 15 slots.

After sufficient real Mac-independent shadow evidence, the next Owner decision is **AUTHORIZE or REJECT merge → deploy → delegated live-send activation**. Until then the PR remains review-only, auto-merge is not enabled, and no further normal development or production activation follows from this closeout.
