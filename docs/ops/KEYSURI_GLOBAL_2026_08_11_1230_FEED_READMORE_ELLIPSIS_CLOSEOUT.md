# KeeSuri Global 12:30 feed read-more ellipsis closeout (2026-08-11)

## Classification

`VISIBLE_TEXT_FEED_READMORE_ELLIPSIS` (+ dash/clause LEFT-edge gap)

## Natural failure

- incident: `2026-08-11_keysuri_global_tech_12-30`
- run_id: `20260811_123001_keysuri_global_tech_6e91b786`
- revision: `genie-blog-run-00289-4qz` @ `88de548`
- error: `keysuri_korean_connector_ellipsis_blocked`
- selected NVIDIA item: `claim-live-nvidia-blog-9f10ae9fb1`
- residual: RSS/WordPress read-more marker ` […]` (`U+005B U+2026 U+005D`) at end of GeForce NOW feed description
- quality sample truncated at 120 chars hid the residual (`…Legends and discov`)

## Recoveries (frozen TOP5, same residual)

- `20260811_123252_keysuri_global_tech_ee872ee3`
- `20260811_123539_keysuri_global_tech_04ca020a`
- `20260811_123931_keysuri_global_tech_4647dcfe`
- `20260811_124240_keysuri_global_tech_075e1fb3`

## Aug 10 companion

Same issue_code on `20260810_123001_keysuri_global_tech_1ff5fed6`. Structural class: dash/clause punctuation as LEFT bridge edge (`—…Firebird`) was outside Friday delimiter grammar.

## Fix

Structural repair in `keysuri_visible_text_quality.py`:

1. Strip matched square-bracket feed read-more ellipsis (`[…]` / `【…】`)
2. Expand LEFT bridge edge to clause punct + dash family
3. Center quality samples on residual ellipsis for forensics

Parenthesis genuine truncation `(…)` remains blocked.
