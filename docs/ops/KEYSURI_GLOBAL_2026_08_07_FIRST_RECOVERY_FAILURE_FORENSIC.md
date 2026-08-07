# KeeSuri Global first-recovery failure forensic closeout (2026-08-07)

## Classification
MULTI_CAUSE (DIFFERENT_REAL_MODEL_DEFECT + ellipsis-repair delimiter gap)

## Recovery #1
- run_id: `20260807_131133_keysuri_global_tech_96d921fa`
- revision: `genie-blog-run-00282-mff` @ `23fbee8` (proven via Cloud Logs)
- error: `keysuri_korean_connector_ellipsis_blocked`
- NOT display-shell; schema/scaffold path OK; image generated; SMTP not sent
- Residual pattern: English title `..` before curly double quote U+201D

## Recovery #2
- run_id: `20260807_131359_keysuri_global_tech_5bf725d1`
- same revision `00282-mff`
- ellipsis patterns fully repaired → validation pass → owner-review SMTP accepted

## Two approvals
Two distinct human `POST .../approve-recovery` (13:11:32 and 13:13:58 KST).
Exactly-once = one execution per approval; re-approve after `recovery_failed` is intended.

## Patch
Extend ellipsis-before-delimiter class with U+201C/U+201D.
