# KeeSuri Global 12:30 incident closeout (2026-08-07)

## Identity
- incident_id: `2026-08-07_keysuri_global_tech_12-30`
- run_id: `20260807_123001_keysuri_global_tech_a349afa9`
- revision at failure: `genie-blog-run-00281-4gw` @ `7f98e77`

## Exact block
Model returned a display-only JSON shell (`opening_lead` / `selected_title` /
`closing_message` / titles) missing required contract keys
(`operational_status`, `generated_status`, `top_5_news`, `deep_dive`,
`one_line_checkpoint`, `closing_sources`). Attempt #1 and GLOBAL_MALFORMED_CONTRACT
repair attempt #2 both failed the same way. Not truncation.

## Fix
1. Deterministic Global contract scaffold for display-shell salvage from trusted
   TOP5 + model display prose (no third model call; junk JSON not salvaged).
2. Corrective prompt forbids display-only shells.
3. Watchdog stage_map derives from deepest proven stage (generation_validation
   no longer reported as 실행 게이트 실패).
4. Failure diagnostic snapshot now includes selected news_ids / headlines.

## Recovery
Admin human approval only. No automatic recovery. Customer send remains blocked
until owner-review approve/final-send.
