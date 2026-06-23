# Genie Project – production rollout preparation

> **⚠️ HISTORICAL DOCUMENT — Read this notice first**
>
> This document was written as a pre-production rollout plan describing a two-container architecture
> (API service + separate worker/orchestrator container). The **actual production deployment** as of
> 2026-06-23 is a **single Cloud Run service** (`genie-blog-run`) that integrates generation,
> validation, owner review, customer delivery, admin UI, and internal scheduler job endpoints.
>
> The API + Worker separation described below was **not adopted**. Do not follow these instructions
> for the current production system. Use this document as a historical reference only.
>
> **Current production facts (2026-06-23 audit):**
> - Service: `genie-blog-run`, region `asia-northeast3`, revision `genie-blog-run-00176-x7r`
> - Scheduler: `Today_Geenee` ENABLED 06:30, `KeeSuri_Global_Tech` ENABLED 12:30, `KeeSuri_Korea_Tech` ENABLED 18:30
> - All programs (today_genie, keysuri_global_tech, keysuri_korea_tech) running in the single service
> - Customer delivery requires operator approval via `/admin` UI
> - GCS artifact bucket: `gen-lang-client-0667098249-genie-artifacts`

---

## 1. Rollout checklist (high level) [HISTORICAL — for reference only]

- [ ] **Secrets**: Create Secret Manager secrets; map to worker env / `*_FILE` (see §2).
- [ ] **Genie API**: Deploy API service (existing Dockerfile); set PROJECT_ID, VERTEX_*, OPENWEATHER_API_KEY, TODAY_GENIE_*_JSON (or placeholders).
- [ ] **Worker image**: Build and deploy orchestrator/worker with an **immutable commit-SHA image tag** (see `cloudbuild-worker.yaml`, `DEPLOY.md` §3); separate image with Playwright if Naver draft is used; set GENIE_API_URL and all worker env (see §2, §4).
- [ ] **First manual runs**: Run `run_orchestrator.py` once for `today_genie`, once for `tomorrow_genie`; verify logs and outcomes (see §5).
- [ ] **Scheduler**: Configure two schedules (or one parameterized job) for daily runs at recommended KST times (see §3).
- [ ] **Monitoring**: Confirm exit codes and summary log line are visible; set alert on exit 1.

---

## 2. Secret Manager mapping

### Secrets to create (GCP Secret Manager)

| Secret name (example) | Content | Used for |
|-----------------------|---------|----------|
| **genie-smtp-password** | SMTP password or app password (plain text) | Email send |
| **genie-naver-password** | Naver account password or app password (plain text) | Naver draft login |

Create with:

```bash
# Example (replace with your values and project)
echo -n "YOUR_SMTP_APP_PASSWORD" | gcloud secrets create genie-smtp-password --data-file=-
echo -n "YOUR_NAVER_APP_PASSWORD" | gcloud secrets create genie-naver-password --data-file=-
```

### Worker runtime: env and `*_FILE` mapping

Mount the secrets into the worker container and point the app to the mount path.

| Env var | Purpose | Example value (worker runtime) |
|---------|---------|---------------------------------|
| **SMTP_PASSWORD_FILE** | Path to mounted SMTP secret | `/secrets/smtp-password` (or Cloud Run secret mount path) |
| **SMTP_APP_PASSWORD_FILE** | Alternative to SMTP_PASSWORD_FILE | Same pattern if using app password secret |
| **NAVER_PASSWORD_FILE** | Path to mounted Naver secret | `/secrets/naver-password` |
| **NAVER_APP_PASSWORD_FILE** | Alternative | Same pattern |

Non-secret worker env (no Secret Manager):

| Env var | Purpose |
|---------|---------|
| GENIE_API_URL | Full URL of the Genie API (e.g. `https://genie-api-xxx.run.app`) |
| GENIE_MODE | Optional; can pass mode via CLI instead |
| GENIE_REQUEST_TIMEOUT | Optional (default 120) |
| GENIE_API_RETRIES | Optional (default 2) |
| SMTP_HOST | SMTP server host |
| SMTP_PORT | SMTP port (e.g. 587) |
| SMTP_USER | SMTP username |
| EMAIL_FROM | From address |
| EMAIL_TO | Comma-separated recipients (do not log) |
| NAVER_ID | Naver account ID |
| NAVER_BLOG_ID | Blog ID for postwrite URL |
| NAVER_HEADLESS | Optional (default true) |

If the platform mounts a secret as a file, set e.g. `SMTP_PASSWORD_FILE=/mnt/secrets/genie-smtp-password` so the code reads the secret from that path.

---

## 3. Scheduler plan [HISTORICAL — see SCHEDULE_OVERRIDE.md for actual schedules]

> The times below (05:30, 14:00) were planning-stage recommendations.
> **Actual deployed schedules** differ — see SCHEDULE_OVERRIDE.md or live GCP.

### Planning-stage times (superseded)

| Mode | Planned time | Actual deployed time (GCP) |
|------|-------------|---------------------------|
| **today_genie** | 05:30 | **06:30 KST** (`30 6 * * 1-5`) |
| **tomorrow_genie** | 14:00 | 18:00 KST — **PAUSED** |
| **keysuri_global_tech** | (not planned here) | **12:30 KST** (`30 12 * * 1-5`) |
| **keysuri_korea_tech** | (not planned here) | **18:30 KST** (`30 18 * * 1-5`) |

Use SCHEDULE_OVERRIDE.md and live GCP as authoritative references.

---

## 4. Worker / container rollout shape

### Confirmed production shape

- **Genie API container (unchanged)**  
  - **Role**: Serves `main:app` (FastAPI); generation, validation, render.  
  - **Image**: Current Dockerfile (no Playwright, no Chromium).  
  - **Deploy**: Cloud Run service; env: PROJECT_ID, VERTEX_*, OPENWEATHER_API_KEY, TODAY_GENIE_*_JSON, etc.

- **Orchestrator / worker container (separate)**  
  - **Role**: Runs `run_orchestrator.py`; calls API, applies policy, sends email, creates Naver draft (draft-only).  
  - **Image**: Separate Dockerfile (or Cloud Run job image) that includes:
    - Python + repo deps (`requirements.txt`).
    - **If Naver draft is used**: Playwright + Chromium (`playwright install chromium` or equivalent).
  - **Entrypoint**: `python run_orchestrator.py` with mode from CLI or `GENIE_MODE`.  
  - **Env**: GENIE_API_URL, SMTP_*, EMAIL_*, NAVER_*; secrets via Secret Manager mount and `*_FILE`.

### Minimum runtime / dependency differences for the worker

| Need | Genie API | Worker |
|------|-----------|--------|
| Python + FastAPI, Vertex, etc. | Yes | Yes (same requirements.txt for shared code) |
| Playwright + Chromium | No | Yes if Naver draft is used |
| Public URL | Yes (ingress) | Not required if triggered by Scheduler → job |
| Secrets | API keys, TODAY_GENIE_* | SMTP, Naver (via *_FILE) |

Worker can use the same repo and `requirements.txt`; the worker image adds a step to install Playwright browsers when Naver draft is required.

---

## 5. First controlled run checklist

Execute in this order for the first safe rollout.

1. **Deploy Genie API**  
   - Deploy the API service; set PROJECT_ID, VERTEX_*, OPENWEATHER_API_KEY, and TODAY_GENIE_*_JSON (or placeholders).  
   - Confirm `GET /health` returns 200.

2. **Create secrets**  
   - Create `genie-smtp-password` and `genie-naver-password` in Secret Manager; grant the worker’s service account access.

3. **Deploy worker**  
   - Build worker image (with Playwright if using Naver draft). Use an **immutable image tag that includes the full Git commit SHA** (see `cloudbuild-worker.yaml` and `DEPLOY.md` §3); configure Cloud Run Jobs with that SHA-tagged image, not a floating tag alone.  
   - Configure env: GENIE_API_URL (pointing to the API), SMTP_*, EMAIL_*, NAVER_*; set SMTP_PASSWORD_FILE and NAVER_PASSWORD_FILE to the secret mount paths.  
   - Do **not** enable the scheduler yet.

4. **Run today_genie once manually**  
   - Invoke worker with `mode=today_genie` (e.g. `python run_orchestrator.py today_genie` or GENIE_MODE=today_genie).  
   - **Success**: Log line contains `reason_summary=ok` or `reason_summary=review_required`, and `email_sent=True` or `email_sent=False` per policy; exit code 0.  
   - **Failure**: Exit code 1 (e.g. request_failed, suppress_external) or 2 (bad mode); log line shows `reason_summary=...`; no email/draft if policy blocked.

5. **Inspect logs and results**  
   - Check the single summary log: `mode=... reason_summary=... email_sent=... naver_draft_created=...`.  
   - If email was sent: confirm receipt and content.  
   - If Naver draft was created: confirm draft in Naver Blog; no publish.

6. **Run tomorrow_genie once manually**  
   - Same as step 4 with `mode=tomorrow_genie`.  
   - Verify summary log and, if applicable, email and Naver draft.

7. **Enable scheduler**  
   - Add Cloud Scheduler (or cron) for today_genie at 05:30 KST and tomorrow_genie at 14:00 KST.  
   - Confirm trigger invokes the worker with the correct mode and that exit codes are visible for alerting.

### What success / failure looks like

- **Success (exit 0)**  
  - Log: `run_orchestrator: mode=today_genie reason_summary=ok email_sent=True naver_draft_created=True` (or False for either when policy disallows).  
  - No stack trace; email and/or draft created only when policy allows.

- **Failure (exit 1)**  
  - Log: `reason_summary=request_failed` or API/validation failure; or `suppress_external` so email/draft correctly skipped.  
  - Investigate API availability, credentials, or validation issues.

- **Bad mode (exit 2)**  
  - Log: mode required (env GENIE_MODE or CLI arg).  
  - Fix invocation (set GENIE_MODE or pass mode as argument).

---

## 6. Remaining operational risks

| Risk | Mitigation |
|------|------------|
| **CAPTCHA / 2FA (Naver)** | Login may fail; implement cookie/session reuse (load Playwright storage state) or use an account with reduced checks. Monitor `naver_draft_created=False` and logs. |
| **Duplicate sends / drafts** | No idempotency in runner; scheduler retry or double trigger can send duplicate email or create duplicate draft. Mitigate: ensure scheduler runs once per mode per day; optional future: idempotency key per run. |
| **Secret misconfiguration** | Wrong or missing `*_FILE` / mount: send or draft is skipped (graceful). Test with a manual run; confirm SMTP and Naver env and mounts before enabling scheduler. |
| **Scheduler retry behavior** | If job is retried on exit 1, the same mode may run again and send/draft again. Prefer alert-on-failure and manual retry, or define a single retry with backoff and accept possible duplicate on rare double-run. |

---

Reference: OPERATIONS.md (hardening, secrets, worker split, logging); README.md (env vars, modes).
