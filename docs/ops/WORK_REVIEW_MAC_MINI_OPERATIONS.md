# Work review on the always-on Mac mini

Task `GENIE_KEESURI_DELEGATED_REVIEW_GATE_001`. This is the operating SSOT for
the second-pass reviewer. It replaces the obsolete Mac-independent cloud
reviewer requirement. Production generation remains on the existing service;
the Owner's 24/7 Mac mini is the approved Work execution host.

## Responsibilities and routing

Deterministic generation/validation is level 0. `gpt-5.3-codex-spark` at low
reasoning effort is the normal level-1 clerk. It must use actual Gmail content,
source search/browser reads and visible image/render evidence. Ambiguous source
or content cases escalate to Astra or Sol. Owner escalation is reserved for
business policy, customer rights, new cost, high-risk production changes or a
meaningful unresolved exception.

Allowed verdicts are `PASS`, `HOLD_ANOMALY`, `HOLD_INCOMPLETE`,
`REVIEW_UNAVAILABLE` and `STATE_CONFLICT`. Only complete authenticated `PASS`
for the exact frozen candidate may enter the delegated gate. A shadow PASS has
`approval_authority=NONE` and `customer_send_authorized=false`.

## Required Work contract

For the exact product, publication date and run ID:

1. Find the actual received Owner-review Gmail message; never select merely the
   newest message. Record the received message identity without retaining
   private routing headers or recipient addresses.
2. Check subject/body consistency, source-summary agreement, dates, companies,
   people, numbers, context, duplicates, contradictions, malformed prose and
   cross-edition contamination.
3. Open the original sources or an authoritative corroborating source in the
   browser. Check link health, freshness, trustworthiness and the material facts.
4. Inspect every required attachment pixel: Today top+bottom, Global top, Korea
   top+bottom. Inspect the actual Gmail layout and the final-customer render.
   An attachment name, CID, URL or hash is not visual inspection.
5. Confirm run identity, natural/recovery/manual lineage, stale/duplicate state,
   prior-send conflict and current customer-send state.
6. Persist one create-exclusive JSON verdict with evidence for every required
   class. Missing or inaccessible evidence cannot be marked PASS.

## Mac mini execution procedure (evidence-first)

1. Start Chrome through Playwright and open the approved reviewer message URL
   directly.
2. Verify in the message DOM:
   - product/publication date
   - exact run ID
   - sender identity and received timestamp
   - expected recipient and image/render links.
3. Run `pageAssets.list()` in the same browser context and record all candidate
   assets with `assetId`, `filename`, `cid`, and source URL.
4. Select required image candidates only and call `pageAssets.bundle()` for each
   image asset to materialize local files.
5. Run `view_image` for each bundled file and perform pixel-level visual checks
   (text overlays, watermark consistency, graph/table integrity, body/face
   legibility, cross-cut contamination).
6. Validate final-customer render URL in browser and capture the render evidence
   independently from Gmail previews.
7. Persist results as create-exclusive local JSON evidence entries. If any step
   is blocked (auth/session/access), capture the exact blocker and stop without
   attempting credential or route bypass.

No local URL rewrites or `file://` substitutes are allowed to replace the actual
Gmail/private-image/render access path.

Normal PASS stays silent. An exception is deduplicated and reported in this
shape: PRODUCT, RUN, WHAT HAPPENED, WHY IT MATTERS, WHAT WAS ALREADY DONE,
CURRENT SEND STATE, RECOMMENDED ACTION and OWNER DECISION REQUIRED.

## Scheduling and failure isolation

Natural publications are Today 06:30, Global 12:30 and Korea 18:30 KST on
weekdays excluding Republic of Korea holidays. The finite 2026-09-11/14/15/16/17
cohort checks at +3, +8, +13 and +18 minutes. Retries, recovery children and
manual runs never increase the publication-opportunity denominator.

The Spark reviewer runs as a local project automation with an explicit
Asia/Seoul recurrence and exact model selection. It checks existing immutable
evidence before doing work so later wakes are no-ops after a final verdict.
The earlier `genie-keesuri-15` heartbeat used a UTC-interpreted recurrence and
is not evidence of a correct natural wake.

An independent deterministic launchd watchdog polls the same manifest and
create-exclusive evidence directory. After the +18 deadline, missing evidence,
malformed evidence or any non-PASS verdict creates one decision-ready exception
record and one local notification. It never reviews content, retries generation,
changes production, authorizes delivery or sends a customer email. Reviewer and
watchdog therefore do not share the Codex scheduling failure domain.

## Delivery authority remains separate

`CONTENT_AND_VISUAL_REVIEW` is not `DELIVERY_ELIGIBILITY`. The legacy beta
address list is only an address inventory. It is not proof of verified email,
consent, entitlement, paid status or trial status. Delegated live send remains
blocked until the selected authority records real verification, consent basis,
product scope, delivery start date and current suppression/duplicate state for
each recipient. No migration may fabricate those facts.

The activation sequence is: prove review and watchdog execution; prove customer
authority and suppression ingress; reconcile delivery claims; merge; deploy with
`DELEGATED_SEND_MODE=OFF`; re-prove health and guarded manual fallback; then set
the reviewed policy/mode live only while every condition remains true.
