# Schedule override (interim)

**This document is the temporary operational source of truth for Genie scheduling.** It takes precedence over older schedule references until full documentation alignment is completed.

---

## Effective production schedule

| Mode | Schedule |
|------|----------|
| **today_genie** | Keep current confirmed operating schedule as currently configured in GCP. |
| **tomorrow_genie** | **18:00 KST** (official operating schedule). |

Older references to 14:00 or 15:00 KST for tomorrow_genie are **superseded** by this override.

---

## Interim precedence

- **Actual GCP Cloud Scheduler settings** take precedence during this interim period. If a deployed schedule differs from this document, the live GCP configuration is authoritative until docs are aligned.
- This override remains valid until full documentation alignment is completed; then it may be retired and the main docs updated.
