# AGENTS.md

## Cursor Cloud specific instructions

`genie-blog-run` is a single Python 3 **FastAPI** service (entry `main.py`, ASGI app `main:app`)
that generates Korean-language "briefing" content via Google Vertex AI (Gemini) and delivers
it by email / in-app owner review. There is no relational database; state/artifacts are stored
in Google Cloud Storage with a **local-filesystem fallback** when no bucket env is set.

### Environment / dependencies
- Dependencies live in a Python virtualenv at `.venv/` (created by the startup update script).
  Activate it before running anything: `source .venv/bin/activate`.
- Runtime deps are `requirements.txt`; `pytest` is also installed because one test file needs it
  (everything else uses stdlib `unittest`).

### Run the app (dev)
- `uvicorn main:app --host 0.0.0.0 --port 8080` (add `--reload` for hot reload while developing).
- `GET /health` works with **no** cloud configuration — `init_vertex()` is lazy, so the server
  starts without `PROJECT_ID`.
- Live generation (`POST /`, and `service_full_run` internal jobs) calls Vertex AI Gemini and
  therefore **requires `PROJECT_ID` + valid GCP credentials**. Without them it raises
  `RuntimeError: PROJECT_ID ... required` and returns HTTP 500. This is expected in a bare cloud
  VM — it is not a code bug.
- Admin UI (`/admin`) is gated by env `GENIE_ADMIN_PASSWORD`; internal job endpoints require
  header `X-Genie-Internal-Job-Token` matching env `GENIE_INTERNAL_JOB_TOKEN`. Set these to any
  value locally to exercise those routes.

### Exercise the core pipeline WITHOUT Gemini/GCP
Use the first-class offline paths (generate-prompt → validate → render, no network):
- `python scripts/render_keysuri_owner_review_preview.py` — renders real owner-review briefing
  HTML into `output/keysuri_preview/*.html` (the product's actual deliverable).
- `python scripts/run_keysuri_offline_dry_run.py` / module `keysuri_offline_dry_run` — full
  offline dry-run of the source-gate + validation pipeline.
`output/` is gitignored.

### Tests
- Full suite: `python -m unittest discover -s tests -p 'test_*.py'`.
- The single pytest-based file: `python -m pytest tests/test_billing_infra_costs.py`.
- **Non-obvious caveat — some tests are DATE-SENSITIVE.** `keysuri_source_gate.py` enforces a
  72-hour freshness window (`_STALE_HOURS = 72`) against the current wall clock, while the staged
  sample source packs in `ops/feeds/` carry fixed dates (e.g. `2026-06-04`). When "now" is more
  than 72h after those fixture dates the source gate returns `hold`, so the offline-dry-run /
  prompt-input / manual-canary tests that assert a `pass` result will FAIL. These failures (plus a
  few static test-vs-code text-drift cases) are pre-existing/time-dependent, **not** environment or
  dependency regressions — do not "fix" them as part of unrelated work.
