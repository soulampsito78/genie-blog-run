# Genie orchestration – production hardening and operations

This document covers secret handling, runtime split, resilience, logging, and the production execution model for the orchestration layer. The Genie API runtime (`main.py`) is unchanged.

---

## 1. Secret handling

### Pattern

- **Environment variables**: Sensitive values can be set directly (e.g. `SMTP_PASSWORD`, `NAVER_PASSWORD`).
- **Secret Manager mount**: For production, prefer mounting secrets as files. Set `*_FILE` to the path of the mounted secret; the code reads the secret from that path and falls back to the env var if the file is missing.

### Exact secret / env names

| Purpose | Env var (direct) | File-style (Secret Manager mount) |
|--------|-------------------|------------------------------------|
| SMTP password | `SMTP_PASSWORD` or `SMTP_APP_PASSWORD` | `SMTP_PASSWORD_FILE` or `SMTP_APP_PASSWORD_FILE` |
| Naver account password | `NAVER_PASSWORD` or `NAVER_APP_PASSWORD` | `NAVER_PASSWORD_FILE` or `NAVER_APP_PASSWORD_FILE` |
| Genie API URL (non-secret) | `GENIE_API_URL` | — |
| Orchestrator credentials | None (orchestrator only calls Genie API; use same identity as the service) | — |

**Recommendation:** In production, create Secret Manager secrets (e.g. `genie-smtp-password`, `genie-naver-password`) and mount them into the orchestrator/worker container as files; set `SMTP_PASSWORD_FILE` and `NAVER_PASSWORD_FILE` to those paths. Do not log or echo any `*_PASSWORD*` or `*_FILE` values.

---

## 2. Playwright / Chromium runtime readiness

### What is needed

- **Playwright** and **Chromium** must be available where `naver_draft.create_naver_draft` runs (e.g. `playwright install chromium`).
- The **Genie API** container (current Dockerfile) does **not** install browsers; it only serves the FastAPI app.

### Recommendation: separate worker

- **Keep the main Dockerfile unchanged** for the Genie API (Cloud Run service that serves `main:app`).
- **Use a separate worker image/job** for orchestration when Naver draft is required:
  - Base image that includes Python + Playwright + Chromium (e.g. custom Dockerfile that runs `playwright install chromium` and installs this repo’s deps).
  - Worker process: invoke `run_genie_job(mode)`, then `send_email_if_allowed(result)` and `create_naver_draft_if_allowed(result)`.
  - Trigger: Cloud Scheduler (or equivalent) calling the worker (e.g. HTTP target to a Cloud Run job or a function that runs the orchestrator).

### Minimal shape of the split

| Component | Image / runtime | Role |
|----------|-----------------|------|
| **Genie API** | Current Dockerfile, Cloud Run service | `uvicorn main:app`; generation, validation, render; no Playwright. |
| **Orchestrator / worker** | Separate image with Playwright + Chromium; Cloud Run job or separate service | Calls Genie API, applies policy, sends email, creates Naver draft. |

If you do **not** need Naver draft in production initially, the orchestrator can run in the same Python env as the API (e.g. same image, different entrypoint) and only SMTP will be used; Playwright is then optional for that deployment.

---

## 3. CAPTCHA / 2FA / login resilience (Naver)

### Current behavior

- Naver login is performed on each draft via ID/password. If the login page shows CAPTCHA or extra verification, the flow detects “still on nidlogin” and returns `False` (no draft created).

### Safest production approach

- **Prefer cookie/session reuse** over repeated ID/password login:
  - Log in once (manually or in a one-off job), export the browser state (e.g. Playwright `storage_state`) to a secure store (e.g. GCS or Secret Manager).
  - In production, load that state into the Playwright context before navigating to the blog postwrite page, and skip the login step. This avoids CAPTCHA/2FA on every run.
- **No auto-publish**: The implementation only clicks “임시저장” (save as draft). No change to that behavior.
- **If cookie reuse is not yet implemented**: Run the Naver draft worker in an environment where login is possible (e.g. optional 2FA exemption for an automation account), or accept that some runs may fail when Naver shows CAPTCHA and surface failures for manual intervention.

---

## 4. Retry / timeout / logging hardening

### Retry and timeout

- **Genie API** (`orchestrator.run_genie_job`):
  - Transient failures (connection error, timeout) are retried up to **`GENIE_API_RETRIES`** (default 2) with **`GENIE_API_RETRY_DELAY_SEC`** (default 2.0 s) between attempts.
  - HTTP 4xx/5xx are **not** retried.
- **SMTP** (`email_sender.send_genie_email`): No retry in code; single attempt with 30 s timeout. For production, consider one retry with short delay for transient SMTP errors (optional later step).
- **Naver draft** (`naver_draft.create_naver_draft`): No retry; single attempt with `NAVER_DRAFT_TIMEOUT_MS`. Optional: retry once on timeout (later step).

### Logging (non-PII)

- **Do not log**: Full HTML bodies, passwords, recipient email addresses, or any `*_PASSWORD*` / `*_FILE` values.
- **Safe to log**: Mode, `reason_summary`, `response_status`, `validation_result`, decision flags (e.g. `send_email`, `create_naver_draft`), recipient **count** (e.g. `recipients=3`), and high-level outcomes (e.g. “send_genie_email: sent (recipients=N)”, “create_naver_draft: draft saved” or “skipped/failed”).
- **Orchestrator**: After a run, a single summary line is recommended, e.g. `mode`, `reason_summary`, `email_sent`, `naver_draft_created`, and optionally `validation_result`, without including response payload or PII.

---

## 5. Scheduler / runner readiness

### Runner entrypoint: `run_orchestrator.py`

The script `run_orchestrator.py` is the single entrypoint for one orchestration run:

1. Reads `mode` from CLI (`today_genie` or `tomorrow_genie`) or env **`GENIE_MODE`**.
2. Calls `result = run_genie_job(mode)`.
3. Calls `send_email_if_allowed(result)` and `create_naver_draft_if_allowed(result)`.
4. Logs one non-PII line: `mode=... reason_summary=... email_sent=... naver_draft_created=...`.
5. Exits **0** when the API returned and policy was applied; **1** when request failed or `suppress_external`; **2** when mode is missing or invalid.

**Invocation:**

```bash
python run_orchestrator.py today_genie
# or
GENIE_MODE=tomorrow_genie python run_orchestrator.py
```

### Minimal production execution model

- **Process/job**: Run `run_orchestrator.py` (or equivalent) with the desired mode:
  1. Set `GENIE_MODE` or pass mode as the first argument.
  2. The script calls `run_genie_job(mode)`, then `send_email_if_allowed(result)` and `create_naver_draft_if_allowed(result)`.
  3. A single summary line is logged; no passwords, addresses, or HTML.
- **Frequency**: Once per mode per day (or as per product requirements), e.g. Cloud Scheduler triggering the worker at the desired times.
- **Env/secrets**: All secrets and config (including `GENIE_API_URL`, `SMTP_*`, `NAVER_*`) are provided via the worker’s environment; secrets are preferably mounted from Secret Manager as files and referenced with `*_FILE`.
- **Failure handling**: On `request_failed`, `validation_block`, or send/draft failure, the worker should exit non-zero or return a non-2xx status so the scheduler can alert or retry according to policy; do not treat “draft_only” as a failure (content was generated and policy applied).

---

## 6. Production hardening checklist

- [ ] **Secrets**: SMTP and Naver credentials stored in Secret Manager; mounted as files and used via `*_FILE` (or injected as env from Secret Manager).
- [ ] **No PII in logs**: Recipient addresses, HTML, and passwords never logged; only counts and high-level outcomes.
- [ ] **Genie API retries**: Orchestrator uses `GENIE_API_RETRIES` and `GENIE_API_RETRY_DELAY_SEC` (defaults in place).
- [ ] **Worker split**: If Naver draft is used, run the orchestrator in a separate image with Playwright + Chromium; keep the Genie API Dockerfile unchanged.
- [ ] **Naver login**: Prefer cookie/session reuse; if not yet implemented, document CAPTCHA/2FA risk and manual fallback.
- [ ] **Scheduler**: Cloud Scheduler (or equivalent) triggers the worker at the desired times; worker logs a non-PII summary and surfaces failures.

---

## 7. Remaining risks

- **Naver**: CAPTCHA or 2FA can block login; cookie-based auth is not yet implemented. Selectors for the blog editor may need updates if Naver changes the page.
- **SMTP**: No retry on transient failure; consider one retry in a future iteration.
- **Orchestrator**: No built-in idempotency key; duplicate scheduler runs could send duplicate emails or create duplicate drafts unless the trigger is deduplicated externally.

---

## 8. Next implementation step after hardening

1. **Add a small runner entrypoint** (e.g. `run_orchestrator.py` or a single function) that: accepts `mode` (env or CLI), calls `run_genie_job(mode)`, then `send_email_if_allowed(result)` and `create_naver_draft_if_allowed(result)`, and logs one non-PII summary line (mode, reason_summary, email_sent, naver_draft_created).
2. **Optional**: Implement Naver cookie/session reuse (load Playwright storage state from a secret or GCS before opening the blog page).
3. **Optional**: Add one retry for SMTP send and/or Naver draft on timeout.

---

## 9. 변경 통제 — Kee-Suri Global 생성 컨트롤 (2026-07-31 신설)

아래 항목을 수정하는 변경은 **명시적 회귀 검토(regression review)** 없이 병합·배포하지
않는다. 정본 근거:
[docs/keysuri/KEYSURI_GLOBAL_RECURRENCE_PREVENTION_CLOSEOUT_2026_07_31.md](docs/keysuri/KEYSURI_GLOBAL_RECURRENCE_PREVENTION_CLOSEOUT_2026_07_31.md)

### 9.1 변경 통제 대상

- generation call budget (`GLOBAL_GENERATION_CALL_BUDGET`)
- 재시도 자격 코드 (`_GLOBAL_CONTRACT_REPAIR_CODES`)
- `program_id` 결정적 보정 (`_repair_program_id_for_parse`)
- generation contract fingerprint 필드 (`generation_contract_record`)
- prompt-template fingerprint / schema fingerprint 산출 방식
- 실패 우선순위 순서 (`FAILURE_PRIORITY_TIERS`)
- sanitized snapshot 상한 (`MODEL_OUTPUT_SNAPSHOT_MAX_CHARS`)
- recurrence counter 이름 (`RECURRENCE_COUNTER_NAMES`)
- image / owner-review email side-effect 게이트
- cross-mode 동작 (Today / Korea / Tomorrow)

### 9.2 필수 증거

변경 시 다음 테스트가 모두 존재하고 통과해야 한다.

| 요구 | 내용 |
|------|------|
| production-path test | fake 는 외부 경계에만. 실제 production 함수를 구동할 것 |
| bounded-attempt test | Global 총 모델 호출이 **2회를 넘지 않음**을 단언 |
| conflicting-identifier hard-block test | 충돌 non-empty `program_id` 가 보정되지 않고 재시도 자격도 없음 |
| no-double-send test | 성공 경로에서 owner-review email 이 정확히 1회 |
| side-effect isolation test | 실패 경로에서 publishable payload 없음 / SMTP 미도달 |
| cross-mode regression test | Global 보정이 Today / Korea / Tomorrow 로 유출되지 않음 |
| exact SHA deployment verification | ROLLOUT.md §7 의 동일성 체인 |

### 9.3 테스트 거버넌스 (불변 조건)

fake 나 recorder 에 대한 단언은 **그 fake 가 실제로 대상 경로에 연결되어 있을 때에만**
유효하다. 연결되지 않은 recorder 에 대한 `calls == 0` 류 단언은 결코 실패할 수 없으므로
증거로 인정하지 않는다. 실제 송신 횟수는 production send path 를 구동하는 테스트가
담당한다.

### 9.4 프로덕션 성공 판정

owner-review 성공은 endpoint HTTP 200 / `email_sent=true` / SMTP accepted 단독으로
판정하지 않는다. **Gmail 실제 수신 확인까지 필요**하다.
