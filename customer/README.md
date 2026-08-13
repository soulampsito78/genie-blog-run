# Customer backend — Phase 1 (DB + domain foundation)

Persistence and domain foundation for the GENIE × KeeSuri **customer web
product**. Additive and isolated: nothing here touches the operational
briefing runtime (`main.py`, `internal_jobs.py`, `admin_routes.py`,
`email_sender.py`, schedulers, GCS, Secrets).

Policy authority lives in `docs/web/`. This package encodes it; it does not
define it.

## What exists

| Layer | Path |
|-------|------|
| Canonical enums / catalog constants | `customer/domain/` |
| SQLAlchemy models (20 tables) | `customer/persistence/models/` |
| Declarative base, naming convention | `customer/persistence/base.py` |
| Engine / session boundary | `customer/persistence/session.py` |
| Alembic environment | `customer/migrations/` (root `alembic.ini`) |

## What does NOT exist yet

No customer API routes, no auth/sessions logic, no IDV / PG / SMS / ESP
integration, no billing execution or retry scheduler, no D-3 job, no
entitlement evaluation service, no state-transition service. Those are later
phases. `main.py` is untouched.

## Setup

```bash
pip install -r requirements-customer.txt
```

## Migrations

Alembic is the **only** schema authority. Never `metadata.create_all()`, never
hand-written DDL. The URL comes from the environment, never from `alembic.ini`.

```bash
CUSTOMER_DATABASE_URL='postgresql+psycopg://user@host/dbname' alembic upgrade head
```

```bash
CUSTOMER_DATABASE_URL='postgresql+psycopg://user@host/dbname' alembic downgrade base
```

## Tests

Domain/catalog tests need no database and run in the normal suite. The
persistence-invariant tests need PostgreSQL and read
`CUSTOMER_TEST_DATABASE_URL` — deliberately a different variable from
`CUSTOMER_DATABASE_URL`, so a test run can never migrate or write to a
configured runtime database. They skip when it is unset.

```bash
CUSTOMER_TEST_DATABASE_URL='postgresql+psycopg://user@host/testdb' python -m pytest tests/test_customer_domain_catalog.py tests/test_customer_persistence_invariants.py tests/test_customer_migration_integrity.py
```

PostgreSQL is required — SQLite is rejected at the session boundary. Several
invariants are partial unique indexes and deferred constraint triggers that
SQLite cannot express, and no constraint may be weakened to accommodate it.

## Invariants enforced by the database

- one verified person → at most one **active** account
- one account → at most one **live** subscription
- one account → exactly one **active** `delivery_email`
- no contracted paid plan while `trialing` / `renewal_pending` /
  `conversion_scheduled`
- `package_two` → exactly two distinct products; `full_set` → all three
- `(account_id, product_code, publication_date)` unique on `recipient_snapshot`
- frozen recipient snapshots and audit events cannot be UPDATEd
- one settled billing attempt per billing period; unique idempotency keys
- one default payment method per account; no PAN/CVV/card-password columns
