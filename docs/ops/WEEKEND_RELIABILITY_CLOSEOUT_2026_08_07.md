# Weekend Reliability Burn-In + Pre-Natural Preflight Closeout

**Date (KST):** 2026-08-07 evening → deploy same night  
**Final label:** `GENIE_KEESURI_WEEKEND_RELIABILITY_CLOSEOUT_COMPLETE`  
**Evidence root:** `/tmp/genie_weekend_reliability_20260807_20260807_191726/`

## Production deployment

| Field | Value |
|---|---|
| HEAD / origin/main | `95542deb746192ef6cea6f1b741390317cf7f446` |
| Cloud Build | `d37ab96d-17f3-4492-86a6-5f1a84a8dfb5` SUCCESS |
| Revision | `genie-blog-run-00287-tbd` |
| Digest | `sha256:6a4ca86f2fd2d98ba978fc7b487fef0d617cb1bad96b1b89d6cb990759941d0d` (build = deployed) |
| Traffic | 100% |
| Ready | True |
| Health | 200 |

## Live-model burn-in (no-send)

Scope clarification (2026-08-11): the Global/Korea streaks below repeatedly used one
frozen source pack. They proved **MODEL_PIPELINE_STABILITY** on fixed inputs. They did
not prove **NATURAL_INPUT_DISTRIBUTION_RELIABILITY**, and should not be cited as evidence
that an upcoming live TOP5 was covered.

| Program | Consecutive PASS | Attempts | Terminal fails | Image/SMTP/Customer |
|---|---|---|---|---|
| Today | **10** | 10 | 0 | 0/0/0 |
| Global | **10** | 10 | 0 | 0/0/0 |
| Korea | **10** | 14 | 1 (dangling quoted fragment correctly blocked) | 0/0/0 |

## Preflight Schedulers (ENABLED, Asia/Seoul, Mon–Fri)

| Job | Schedule | Natural slot |
|---|---|---|
| `Today_Geenee_Preflight` | `45 5 * * 1-5` | 06:30 |
| `KeeSuri_Global_Tech_Preflight` | `45 11 * * 1-5` | 12:30 |
| `KeeSuri_Korea_Tech_Preflight` | `45 17 * * 1-5` | 18:30 |

Natural jobs + Watchdog unchanged. `Tomorrow_Geenee` remains **PAUSED**.

## Historical deployed preflight proof (2026-08-11 fixture date)

All three: `PRECHECK_PASS`, model called, image/SMTP/customer/slot/incident = 0. This
historical proof used frozen fixture input for KeeSuri and therefore demonstrated
side-effect isolation and fixed-input stability, not natural-input equivalence.

## Full suite ×2

Command: `python3 -u -m unittest discover -s tests -p 'test_*.py' -q`  
Both runs: **Ran 2707 tests / OK** on final tree.
