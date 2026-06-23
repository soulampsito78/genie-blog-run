# Schedule Reference (updated 2026-06-23)

> **Updated 2026-06-23** based on confirmed GCP audit.
> This document supersedes all older schedule references (14:00, 15:00 for tomorrow_genie).
> Live GCP Cloud Scheduler settings remain the authoritative source of truth.

---

## Effective production schedule (2026-06-23 confirmed)

| GCP Job | Program | Schedule | State | Last run |
|---------|---------|----------|-------|----------|
| `Today_Geenee` | `today_genie` | **06:30 KST** Mon–Fri (`30 6 * * 1-5`) | **ENABLED** | 2026-06-22T21:30Z → 200 OK |
| `KeeSuri_Global_Tech` | `keysuri_global_tech` | **12:30 KST** Mon–Fri (`30 12 * * 1-5`) | **ENABLED** | 2026-06-23T03:30Z → 200 OK |
| `KeeSuri_Korea_Tech` | `keysuri_korea_tech` | **18:30 KST** Mon–Fri (`30 18 * * 1-5`) | **ENABLED** | 2026-06-22T09:30Z → 200 OK |
| `Tomorrow_Geenee` | `tomorrow_genie` | 18:00 KST daily (`0 18 * * *`) | **PAUSED** | No successful run on record |
| `approval_timeout_processor` | internal | Every 10 min (`*/10 * * * *`) | **ENABLED** | 2026-06-23T06:00Z → 200 OK (send retired in code) |

---

## Notes on specific entries

**tomorrow_genie (18:00)**
- GCP Scheduler PAUSED; env `GENIE_OPS_TOMORROW_SCHEDULER_STATE=PAUSED`
- Older references to 14:00 or 15:00 are superseded
- Resume requires explicit operator decision

**approval_timeout_processor**
- Scheduler is ENABLED and fires every 10 min
- Code policy: `_timeout_customer_send_retired()` returns True — no customer email is sent on timeout
- Effect: processor runs but only scans; does not trigger sends

---

## Precedence rule

Live GCP Cloud Scheduler settings are authoritative.
This document is the secondary reference when GCP cannot be queried directly.
