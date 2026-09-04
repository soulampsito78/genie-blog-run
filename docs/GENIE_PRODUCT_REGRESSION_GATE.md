# GENIE product regression gate

## One release command

Run from the repository root:

```bash
python scripts/run_product_regression_gate.py
```

Success ends with:

```text
TECHNICAL_TEST_PASS=PASS
RUNTIME_SAFETY_CONTRACT=PASS
CUSTOMER_SURFACE_CONTRACT=PASS
RELEASE_REGRESSION_PASS
GENIE_PRODUCT_REGRESSION_GATE=PASS
```

Any test failure exits non-zero and prints `RELEASE_REGRESSION_FAIL` and
`GENIE_PRODUCT_REGRESSION_GATE=FAIL`.

The command is offline and deterministic. It uses only persisted fixtures and
unit tests. It must not call Gemini, SMTP, Cloud Run, Scheduler, or any external
service. Cloud Build runs it in the just-built container with networking
disabled, before the image can be pushed or deployed.

## Authority boundaries

1. `TECHNICAL_TEST_PASS` says the bounded implementation tests passed.
2. Runtime safety retains the legacy wire values `pass`, `draft_only`, and
   `block`; metadata maps them to `RUNTIME_SAFETY_PASS`, `REVIEW_REQUIRED`, and
   `HARD_FAIL` without changing their authority.
3. Customer-surface QA emits `CUSTOMER_SURFACE_PASS` or
   `PRODUCT_REVIEW_REQUIRED`. It can block customer approval, but never owner
   artifact creation or owner-review delivery for a usable run.
4. The offline gate emits `RELEASE_REGRESSION_PASS` or
   `RELEASE_REGRESSION_FAIL`. It blocks release, never a scheduled production
   execution.

## Covered paths

The gate covers Today assembly/grounding/render-facing behavior, Global and
Korea selection and reader surfaces, runtime validator compatibility, owner
review/customer approval authority, and the persisted cross-mode corpus in
`tests/fixtures/product_surface/manifest.json`.

The structural similarity threshold is `0.82`. English is evaluated only in
reader-facing titles and prose; company names, tickers, source names, URLs, and
financial terms are not rejected merely for being English.
