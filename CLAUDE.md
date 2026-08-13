# GENIE × KeeSuri — Project Constitution

Durable execution rules for every session in this repository. This is a
constitution, not a transcript. Keep it short enough to read every time.

Repository: live production service. Two distinct worlds live here:

- **Operational runtime** — flat top-level modules (`main.py`, `orchestrator.py`,
  `internal_jobs.py`, `admin_routes.py`, `email_sender.py`, `keysuri_*`,
  `today_genie_*`). Protected.
- **Customer backend** — `customer/` package + `alembic.ini`. Additive, new.

---

## 1. Authority order

Lower authority MUST NEVER silently override higher authority.

1. Current explicit owner decision (this session's prompt)
2. This constitution (`CLAUDE.md`)
3. Canonical / SSOT documents (`docs/web/*`, `docs/BUSINESS_BRAND_SSOT_v1.md`)
4. Verified current repository / runtime truth
5. Implementation specifications
6. Existing code
7. Tests
8. Prototypes / mocks (`web_prototype/` is NON-CANONICAL)
9. Historical / superseded material (closeouts, dated reports)
10. Model inference

If two authorities genuinely conflict and the current prompt does not resolve
it: stop **only the conflicting portion** and report `CONSTITUTION_CONFLICT`.
Never improvise policy.

Start from `docs/web/DOCUMENT_MAP_AND_AUTHORITY.md`.

## 2. Evidence before claim

Never claim something exists, was modified, was generated, was deployed,
passed, is live, or is canonical without evidence: file content, git output,
test output, runtime output, database output.

- rules changed ≠ artifact generated
- code exists ≠ runtime works
- HTTP 200 ≠ business success
- provider accepted ≠ customer received

## 3. Operational pipeline separation (protected)

```
generation ≠ validation ≠ artifact persistence ≠ owner review ≠ approval
≠ customer delivery ≠ provider acceptance ≠ customer receipt ≠ publishing
```

The customer backend MUST NOT gain authority over: Cloud Scheduler,
`/internal/jobs/*`, generation execution, validation bypass, owner approval,
direct SMTP / customer-send, Secret Manager, production GCS mutation,
production deployment.

**Fail closed.** Never raise apparent reliability by bypassing a safety gate.

## 4. Customer IA / operator boundary

Customer web has **exactly three** customer product areas:

1. Landing & Introduction
2. Signup & Payment
3. My Page

**Login is an authentication entry surface, not a fourth area.** Never invent a
fourth customer top-level category.

Admin / Owner Review is a **separate private operator surface**, not a customer
product area. Customer navigation must expose **0** Admin destinations and **0**
Owner Review destinations, and customer authentication must authorize **0**
operator functions. A customer session never authorizes an operator API.

## 5. Current product catalog (owner lock)

Monthly, VAT included:

| Plan | KRW |
|------|-----|
| `today_genie` | 6,600 |
| `keysuri_global` | 9,900 |
| `keysuri_korea` | 6,600 |
| `package_two` (exactly two of three) | 11,000 |
| `full_set` (all three) | **16,500** |

Full Set: supply 15,000 + VAT 1,500 = 16,500. Step-up from `package_two`:
5,500. **14,300 and 29,900 are HISTORICAL — never current.** No recommendation
badges, no preselected plan.

## 6. Schedule

`today_genie` 06:30 KST · `keysuri_global` 12:30 KST · `keysuri_korea` 18:30 KST.

Weekdays only. No weekends, no Republic of Korea public holidays.

`Tomorrow_Geenee` is **not** a current customer product — do not reintroduce it.

## 7. Signup, trial, and D-3 conversion

**Signup is exactly FOUR stages — no more, no fewer:**

1. Adult mobile identity verification
2. Passwordless account creation + email verification
3. Own-name payment method registration
4. Start / confirm the 14-calendar-day Full Set trial

Trial: **14 calendar days**, entitlement = **Full Set** (all three products).

**At signup there is NO paid-plan selection**, and the confirmation screen shows
**no future paid-plan name and no future paid price**. Card registration ≠
conversion consent.

**D-3 is the FIRST paid-plan selection point:**

```
renewal entry → authenticate if needed → choose one of five paid plans
(package_two = exactly two products) → confirmation → mobile strong step-up
→ explicit conversion confirmation → conversion_scheduled
```

**No charge at D-3.** The first charge occurs at `trial_end_at`. No automatic
conversion. No explicit conversion → trial expires, delivery OFF, **no charge**.

**Pre-D-3 My Page** (`trialing` / `renewal_pending` with no conversion
confirmation) MUST NOT show a selected future paid plan or a future paid-price
placeholder. The pending plan and price appear **only** after
`conversion_scheduled`.

## 8. Database authority

PostgreSQL + SQLAlchemy + **Alembic as the only** application schema migration
authority. No manual application DDL, no second migration framework, no
`metadata.create_all()` against a real database, no Supabase CLI/Dashboard
application DDL.

## 9. Supabase decision

Managed production PostgreSQL provider: **Supabase PostgreSQL**, Seoul /
ap-northeast-2, Pro or higher. Used as **hosted PostgreSQL only**.

```
Customer Web → FastAPI → Customer Services → SQLAlchemy → Supabase PostgreSQL
```

Browser MUST NOT connect to the database. Supabase Auth, browser Data API,
Edge Functions, Realtime, and Storage are **out of scope / not authority**.
Migrations must not run at app startup. Detail:
`docs/web/CUSTOMER_BACKEND_INFRASTRUCTURE_DECISION_v1.md`.

## 10. Git / production authority

Unless the **current** owner prompt explicitly authorizes it, do NOT:
`git commit`, `git push`, deploy, run a production migration, touch a
production DB, mutate Scheduler or Secrets, or send customer mail.

Never `git reset` / `restore` / `clean` / `stash` / force-push.
**Authorization never carries over from a previous phase.**

## 11. Unattended execution

Owner attention is expensive; target zero interventions during approved work.
Do not ask permission for repository reads, in-scope edits, safe test runs,
lint checks, or diff inspection. Batch inspections; reuse one command form
instead of inventing five. If a permission-sensitive operation is not required
for PASS, skip it and record the limitation. Never request sudo, production
credentials, cloud mutations, or external provisioning unless the current task
requires it.

## 12. Giant Step

Default mode: inspect → reason → implement → test → diagnose → repair →
retest → regression → self-audit → report, continuously.

Do not hand back after one file, one migration, one failing test, or one
bounded bug. Classify failures:

- defect from current work → fix and continue
- pre-existing unrelated failure → record and continue
- related regression → investigate and bounded-fix
- authority/safety conflict → stop that portion only

Giant Step is not scope creep. Do not start the next product phase.

## 13. Verification commands

```bash
python3 -m pytest tests -q
```

Customer persistence tests need PostgreSQL and read
`CUSTOMER_TEST_DATABASE_URL` (deliberately distinct from the runtime
`CUSTOMER_DATABASE_URL`); they skip when it is unset. Deps:
`requirements-customer.txt` — kept out of `requirements.txt` so the production
image is unchanged. See `customer/README.md`.
