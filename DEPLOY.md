# Genie – deployment commands (plain-language guide)

This guide is for the **first rollout: email only** (no Naver draft). You need: (1) the Genie API already deployed and its URL, (2) GCP project ID and region, (3) SMTP and email settings.

---

## 1. Can the current Dockerfile be used for the worker?

**Yes, but with a catch.**

- The **current Dockerfile** is set up to start the **web API** (the server that generates content). When you run that image, it starts `uvicorn main:app` and listens on port 8080.
- The **worker** is different: it only runs the script `run_orchestrator.py` once (calls the API, then may send email). It does not start a web server.
- So you have two options:
  - **Option A:** Use the **same image** as the API, but when you create the Cloud Run **Job**, you **override the command** to `python run_orchestrator.py today_genie` (or `tomorrow_genie`). Then the same image runs as a one-off worker.
  - **Option B (recommended):** Use a **separate worker image** built from `Dockerfile.worker`. That file is the same as the main Dockerfile except the default command is `python run_orchestrator.py`. So you don’t have to remember to override the command; the worker image is clearly “the job image.”

**In plain language:** The main Dockerfile *can* be used for the worker if you change the run command when you create the job. For clarity and fewer mistakes, we added a second file, `Dockerfile.worker`, which is the “worker-only” image. Use that for the jobs below.

---

## 2. What is different in the worker container?

| | API container (main Dockerfile) | Worker container (Dockerfile.worker) |
|--|----------------------------------|--------------------------------------|
| **Purpose** | Run the web server that generates content. | Run the orchestrator once: call API, then send email if allowed. |
| **Default command** | `uvicorn main:app --host 0.0.0.0 --port 8080` | `python run_orchestrator.py` |
| **How it runs** | Long-running service (Cloud Run **Service**). | One-off run (Cloud Run **Job**). |
| **Dependencies** | Same (Python, FastAPI, Vertex, etc.). | Same. No browser install for email-only. |

So: same code and dependencies; only the **default command** is different. The worker does not start a server; it just runs the script and exits.

---

## 3. Build the worker image

Run this from the **project root** (the folder that contains `Dockerfile.worker` and `run_orchestrator.py`).

### Worker image identity (read-only verification)

- **Source of truth:** the image tag that includes the **full 40-character Git commit SHA** (same form as the Genie API image tag), e.g.  
  `.../genie-orchestrator:c562f2d65d72a65532501b86d920c3746f289262`.
- **Not sufficient for commit proof:** floating tags such as `latest-worker` or `:v1` / `:v2` — they may point at the correct digest but **GCP job config alone cannot prove** which Git revision they were built from unless you also record the SHA tag.
- The repo’s `cloudbuild-worker.yaml` builds **two** tags: the immutable SHA tag (required) and an optional convenience tag (`latest-worker` by default). **Configure Cloud Run Jobs with the SHA-tagged image** when you need audit alignment with Git.

Replace:
- `YOUR_PROJECT_ID` with your GCP project ID.
- `YOUR_REGION` with your region (e.g. `us-central1` or `asia-northeast3`).
- In `cloudbuild-worker.yaml`, `_WORKER_IMAGE` if your Artifact Registry path differs.

**Recommended build (immutable SHA + optional convenience tag):**

```bash
gcloud builds submit --config=cloudbuild-worker.yaml \
  --substitutions=_COMMIT_SHA=$(git rev-parse HEAD) \
  --project=YOUR_PROJECT_ID .
```

This pushes e.g. `.../genie-orchestrator:<full-sha>` and `.../genie-orchestrator:latest-worker` (same digest). **Use the `:<full-sha>` reference** in `gcloud run jobs create` / `update`.

**Alternative (single tag to Artifact Registry / GCR):**

```bash
COMMIT=$(git rev-parse HEAD)
gcloud builds submit --tag REGION-docker.pkg.dev/YOUR_PROJECT_ID/YOUR_REPO/genie-orchestrator:${COMMIT} \
  --file Dockerfile.worker .
```

---

## 3b. Point Cloud Run Jobs at the SHA-tagged image

When creating or updating jobs, set `--image` to the **commit-SHA tag**, not `latest-worker` alone:

```text
--image REGION-docker.pkg.dev/PROJECT/REPO/genie-orchestrator:FULL_GIT_COMMIT_SHA
```

Example (placeholders):

```bash
gcloud run jobs update genie-orchestrator-today \
  --region YOUR_REGION \
  --image asia-northeast3-docker.pkg.dev/YOUR_PROJECT_ID/genie/genie-orchestrator:c562f2d65d72a65532501b86d920c3746f289262
```

---

## 4. Create the two Cloud Run Jobs (email-only)

Replace:
- `YOUR_PROJECT_ID` with your GCP project ID.
- `YOUR_REGION` with your region.
- `https://YOUR-GENIE-API-URL.run.app` with the real URL of your deployed Genie API.
- `FULL_GIT_COMMIT_SHA` with the same 40-character Git revision you used when building the worker image (e.g. output of `git rev-parse HEAD` at build time).

You will also need to add SMTP and email env vars (and optionally secrets). The commands below create the jobs with the **minimum** needed to run; you must add your API URL and email settings.

**Job 1 – today_genie (runs once per day, e.g. 05:30 KST):**

```bash
gcloud run jobs create genie-today-genie \
  --image REGION-docker.pkg.dev/YOUR_PROJECT_ID/genie/genie-orchestrator:FULL_GIT_COMMIT_SHA \
  --region YOUR_REGION \
  --set-env-vars "GENIE_MODE=today_genie,GENIE_API_URL=https://YOUR-GENIE-API-URL.run.app" \
  --set-env-vars "SMTP_HOST=YOUR_SMTP_HOST,SMTP_PORT=587,SMTP_USER=YOUR_SMTP_USER,EMAIL_FROM=YOUR_FROM,EMAIL_TO=YOUR_TO" \
  --set-secrets="SMTP_PASSWORD=smtp-password:latest"
```

**Job 2 – tomorrow_genie (runs once per day, e.g. 14:00 KST):**

```bash
gcloud run jobs create genie-tomorrow-genie \
  --image REGION-docker.pkg.dev/YOUR_PROJECT_ID/genie/genie-orchestrator:FULL_GIT_COMMIT_SHA \
  --region YOUR_REGION \
  --set-env-vars "GENIE_MODE=tomorrow_genie,GENIE_API_URL=https://YOUR-GENIE-API-URL.run.app" \
  --set-env-vars "SMTP_HOST=YOUR_SMTP_HOST,SMTP_PORT=587,SMTP_USER=YOUR_SMTP_USER,EMAIL_FROM=YOUR_FROM,EMAIL_TO=YOUR_TO" \
  --set-secrets="SMTP_PASSWORD=smtp-password:latest"
```

**If you prefer not to use Secret Manager yet**, you can pass the SMTP password as an env var (less secure; only for first tests):

```bash
# today_genie (with password in env – only for testing)
gcloud run jobs create genie-today-genie \
  --image REGION-docker.pkg.dev/YOUR_PROJECT_ID/genie/genie-orchestrator:FULL_GIT_COMMIT_SHA \
  --region YOUR_REGION \
  --set-env-vars "GENIE_MODE=today_genie,GENIE_API_URL=https://YOUR-GENIE-API-URL.run.app,SMTP_HOST=...,SMTP_PORT=587,SMTP_USER=...,SMTP_PASSWORD=...,EMAIL_FROM=...,EMAIL_TO=..."

# tomorrow_genie (same, with GENIE_MODE=tomorrow_genie)
gcloud run jobs create genie-tomorrow-genie \
  --image REGION-docker.pkg.dev/YOUR_PROJECT_ID/genie/genie-orchestrator:FULL_GIT_COMMIT_SHA \
  --region YOUR_REGION \
  --set-env-vars "GENIE_MODE=tomorrow_genie,GENIE_API_URL=https://YOUR-GENIE-API-URL.run.app,SMTP_HOST=...,SMTP_PORT=587,SMTP_USER=...,SMTP_PASSWORD=...,EMAIL_FROM=...,EMAIL_TO=..."
```

**Note:** For `--set-secrets`, the secret must already exist in Secret Manager (e.g. `smtp-password`). The job’s service account needs “Secret Manager Secret Accessor” on that secret. If you use `SMTP_PASSWORD` in env, the worker will use it (and optionally `SMTP_PASSWORD_FILE` if you mount a secret file later).

---

## 5. First rollout is email-only

- **Naver draft is not used.** Do not set `NAVER_ID`, `NAVER_PASSWORD`, or `NAVER_BLOG_ID`. The worker will skip Naver and only run: call API → send email if policy allows.
- No Playwright/Chromium install is required for this.

---

## 6. Summary and what to run first

### Plain-language summary

- **API**: The existing Dockerfile runs the **Genie API** (the server). Deploy that as a Cloud Run **Service** so it has a URL.
- **Worker**: `Dockerfile.worker` runs only **run_orchestrator.py** (call API, then send email). You build one worker image and create **two Cloud Run Jobs**: one for `today_genie`, one for `tomorrow_genie`. Each job uses the same image and only the env var `GENIE_MODE` (and later the schedule time) is different.
- **First rollout**: Email only; no Naver. You need the API URL and SMTP settings. Build the worker image, create the two jobs with the correct env (and optional secret for SMTP password), then run each job once manually to verify before adding schedules.

### Files changed/added

- **Added:** `Dockerfile.worker` – same as the API Dockerfile except the default command is `python run_orchestrator.py`.
- **Added:** `DEPLOY.md` – this guide and the exact commands.

### Commands to run first (in order)

1. **Build the worker image** (from project root; produces immutable `:<full-sha>` tag):

   ```bash
   gcloud builds submit --config=cloudbuild-worker.yaml \
     --substitutions=_COMMIT_SHA=$(git rev-parse HEAD) \
     --project=YOUR_PROJECT_ID .
   ```

2. **Create the today_genie job** (fill in placeholders; `--image` must use the **commit-SHA** tag):

   ```bash
   gcloud run jobs create genie-today-genie \
     --image REGION-docker.pkg.dev/YOUR_PROJECT_ID/genie/genie-orchestrator:FULL_GIT_COMMIT_SHA \
     --region YOUR_REGION \
     --set-env-vars "GENIE_MODE=today_genie,GENIE_API_URL=https://YOUR-API-URL.run.app,SMTP_HOST=...,SMTP_PORT=587,SMTP_USER=...,SMTP_PASSWORD=...,EMAIL_FROM=...,EMAIL_TO=..."
   ```

3. **Create the tomorrow_genie job** (same, but `GENIE_MODE=tomorrow_genie`):

   ```bash
   gcloud run jobs create genie-tomorrow-genie \
     --image REGION-docker.pkg.dev/YOUR_PROJECT_ID/genie/genie-orchestrator:FULL_GIT_COMMIT_SHA \
     --region YOUR_REGION \
     --set-env-vars "GENIE_MODE=tomorrow_genie,GENIE_API_URL=https://YOUR-API-URL.run.app,SMTP_HOST=...,SMTP_PORT=587,SMTP_USER=...,SMTP_PASSWORD=...,EMAIL_FROM=...,EMAIL_TO=..."
   ```

4. **Run each job once by hand** to test:

   ```bash
   gcloud run jobs execute genie-today-genie --region YOUR_REGION
   gcloud run jobs execute genie-tomorrow-genie --region YOUR_REGION
   ```

5. Check the job logs for the single summary line: `mode=... reason_summary=... email_sent=... naver_draft_created=...`. Then add Cloud Scheduler triggers for 05:30 KST (today_genie) and 14:00 KST (tomorrow_genie) if everything looks good.
