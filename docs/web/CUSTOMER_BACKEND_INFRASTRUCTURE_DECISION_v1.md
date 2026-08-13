# GENIE × KeeSuri — Customer Backend Infrastructure Decision v1

**Status:** APPROVED (owner decision)
**Version:** v1
**As of:** 2026-08-11 (KST)
**Authority:** Customer-backend database provider and application boundary
**Parent:** `docs/web/GENIE_KEYSURI_CUSTOMER_WEB_SSOT_v1.md`
**Map:** `docs/web/DOCUMENT_MAP_AND_AUTHORITY.md`

Scope: **architecture lock only.** No Supabase project was provisioned, no
credentials were requested or stored, and no production database exists.

---

## 1. Decision

| Item | Value |
|------|-------|
| Managed production PostgreSQL provider | **Supabase PostgreSQL** |
| Target production region | **Seoul / ap-northeast-2** |
| Production plan baseline | **Supabase Pro or higher** |
| Schema migration authority | **Alembic ONLY** |
| Runtime access | Standard PostgreSQL connection (SQLAlchemy) |

Supabase is adopted as **hosted PostgreSQL**. It is **not** the customer
application authority.

---

## 2. Application boundary

```
Customer Web (browser)
  → FastAPI
  → Customer Services
  → SQLAlchemy
  → Supabase PostgreSQL
```

The browser **MUST NOT** connect to the database directly. Authentication and
authorization remain behind FastAPI. The database is reachable only from the
server tier.

---

## 3. Supabase feature scope

| Supabase feature | Status |
|------------------|--------|
| PostgreSQL (hosted) | **IN USE** |
| Supabase Auth | **OUT OF SCOPE — NOT AUTHORITY** |
| Supabase Data API from browser | **FORBIDDEN** |
| Supabase Edge Functions | **OUT OF SCOPE** |
| Supabase Realtime | **OUT OF SCOPE** |
| Supabase Storage | **OUT OF SCOPE** unless separately approved |

Customer identity, sessions, and step-up remain governed by
`CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md` and implemented behind FastAPI.

---

## 4. Schema authority

Alembic is the **only** application schema migration authority
(`alembic.ini` → `customer/migrations`).

**FORBIDDEN:**

- manual application DDL at runtime
- a second migration framework
- Supabase CLI migrations as application migration authority
- application DDL through the Supabase Dashboard / SQL Editor

Repository code **MUST NOT** call `metadata.create_all()` against a real
database.

---

## 5. Expected future connection strategy

Not implemented in this phase; recorded so later work does not improvise.

- **Application runtime:** pooled PostgreSQL connection suitable for Cloud Run
  (short-lived instances; a connection pooler endpoint rather than one direct
  connection per instance).
- **Migrations:** a **separate, controlled** Alembic execution using its own
  connection, run deliberately by an operator or a release step.
- **Migrations MUST NOT run automatically at application startup.** A Cloud Run
  instance starting up must never mutate schema.
- Credentials arrive from the environment (`CUSTOMER_DATABASE_URL`) and are
  never committed. `customer/persistence/session.py` refuses to start without
  an explicit URL and rejects non-PostgreSQL URLs.

---

## 6. Not performed in this task

| Item | Status |
|------|--------|
| Supabase project provisioning | **NOT PERFORMED** |
| Region/plan purchase or cost incurred | **NONE** |
| Secrets requested or stored | **NONE** |
| Production database created | **NO** |
| Production migration executed | **NO** |
| Deployment | **NONE** |

---

## 7. Related documents

- `GENIE_KEYSURI_CUSTOMER_WEB_SSOT_v1.md` (§7 operational safety boundaries)
- `CUSTOMER_AUTH_IDENTITY_SESSION_SPEC_v1.md`
- `CUSTOMER_LIFECYCLE_BILLING_POLICY_v1.md`
- `customer/README.md` (implementation entry point)
