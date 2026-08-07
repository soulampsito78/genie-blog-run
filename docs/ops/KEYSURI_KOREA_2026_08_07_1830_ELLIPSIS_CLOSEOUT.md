# KeeSuri Korea 2026-08-07 18:30 ellipsis + retry actionability closeout

**run_id:** `20260807_183002_keysuri_korea_tech_fc4ce837`  
**incident_id:** `2026-08-07_keysuri_korea_tech_18-30`  
**revision at failure:** `genie-blog-run-00284-h9d`

## Exact residual

`KDB생명 인수전, 한국투자·한화·흥국 '3파전'…삼성·교보 불참`

Window ±8 around U+2026:

`흥국 '3파전'…삼성·교보 불참`

Codepoints: closing ASCII `'` (U+0027) → `…` (U+2026) → `삼` (U+C0BC).

## Why Global 13:11 patch did not cover it

Global fixed **word → ellipsis → opening/closing curly quote**.  
Korea residual is **closing delimiter → ellipsis → word**.

## Repair invariant

Structural connector bridges (not a punctuation blacklist):

1. Normalize `..` / ZWSP / NBSP around ellipsis  
2. Repair `left_edge … right_edge` where edges are word or quote/bracket delimiters  
3. Absorb `…` before clause/sentence punctuation  
4. Strip trailing sentence-final ellipsis  
5. Genuine in-paren corruption `확인 불가 (…)` remains blocked

## Retry policy (two axes)

| Axis | Values |
|---|---|
| Root cause | `ROOT_CAUSE_CONFIRMED` / `PARTIAL` / `UNKNOWN` |
| Actionability | `RETRY_SAFE` / `RETRY_ALLOWED_WITH_WARNING` / `RETRY_BLOCKED` |

`RETRY_STATUS_UNKNOWN` is reserved for unknowable **side effects**, not unexplained validator text.

Validator failure + customer=0 + no owner mail → actionable (`ALLOWED_WITH_WARNING` or `SAFE` once repair proven).

## Closeout (deployed)

| Item | Value |
|---|---|
| Final status | `KEESURI_KOREA_1830_PATCHED_AND_RETRY_ENABLED` |
| tested HEAD / origin/main | `d986dcd61840d4384a0df95ca07dc7ab9500a95b` |
| revision | `genie-blog-run-00285-lkq` |
| digest | `sha256:bb78e3ec860df5a8fca29266a7365eb96151869f032b772e5b3ad41cca1c057d` |
| suite ×2 | `2675` / `2675` OK identical |
| no-send replay | validation PASS; model/image/SMTP/customer/natural = 0 |
| live incident | `ROOT_CAUSE_CONFIRMED` + `RETRY_SAFE` |
| Admin button | ENABLED |
| Recovery executed | NO |
