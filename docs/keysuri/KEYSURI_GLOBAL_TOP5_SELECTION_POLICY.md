# Kee-Suri Global TOP5 Selection Policy

## Purpose

Kee-Suri global tech briefing must not pick the five newest RSS links. It must select the five most valuable global AI / big tech / platform / startup / policy / business signals for the owner (주인님).

Implementation: `keysuri_global_signal_scoring.py`  
Debug report: `output/keysuri_preview/debug/keysuri_global_top5_selection_report_<timestamp>.json`

## Scoring dimensions (total = A+B+C+D+E+F+G+H)

| Code | Dimension | Range |
|------|-----------|-------|
| A | Recency / 최신성 | 0–10 |
| B | Source reliability / 출처 신뢰도 | 0–10 |
| C | Structural impact / 구조 변화성 | 0–20 |
| D | Owner relevance / 주인님 관점 실효성 | 0–20 |
| E | Business leverage / 돈·일·기회 연결성 | 0–15 |
| F | Signal strength / 반복 신호성 | 0–10 |
| G | Actionability / 실행 가능성 | 0–10 |
| H | Hype risk penalty / 과장 위험 감점 | −15 to 0 |

## Classification bands

- **85+** — Deep-dive candidate
- **75–84** — Strong TOP5
- **60–74** — TOP5 candidate
- **45–59** — Watchlist only
- **Below 45** — Reject

## Hard rejects

- Duplicate story
- No source URL
- No date
- Low-trust repost without original source
- Marketing-only article with no strategic signal
- Article cannot be summarized beyond generic vendor claims
- English title/body leaked without Korean interpretation (content gate)
- No owner relevance
- No business/work/opportunity/risk connection

## TOP5 item output requirements (briefing)

Each selected item must include Korean fields with minimum depth:

1. 한국어 제목  
2. 원문 출처명  
3. 원문 URL  
4. 날짜  
5. 선정 점수  
6. 선정 이유 2–3문장  
7. 무슨 일이 있었나 — 최소 3문장  
8. 왜 지금 중요한가 — 최소 3문장  
9. 주인님 관점 — 최소 3문장  
10. 키수리 판단 (기회 / 관찰 / 경계 / 활용 후보 / 사업 신호 / 리스크 신호 / 추가 확인 필요)  
11. 다음 확인 포인트 — 최소 2개  
12. 과장 주의 여부  
13. 탈락/감점 사유 (if any)

## Reference case: OpenAI Endava Frontiers

URL: https://openai.com/index/endava-frontiers/

Expected framing:

- Latest official OpenAI page: yes  
- Source reliability: high  
- Product launch / breaking news: **no**  
- Customer / enterprise case study: **yes**  
- TOP5 candidate: possible (not rank-1 breaking news)  
- Hype penalty required  

Correct summary angle:

> OpenAI is using Endava as an enterprise case to show AI agents moving from coding assistance into software delivery, legal, project management, and operations workflows.

Incorrect framing:

> OpenAI launched a major new product.

## Same-run diversity, replacement pool, and cross-day exposure (2026-06-26)

These layers were added/hardened in the 2026-06-26 Kee-Suri recovery. They are
distinct: **same-run diversity** prevents repetition *within one briefing*, while
**cross-day dedup** prevents repeating items already shown on earlier days. The
first does not solve the second.

### Same-run TOP5 diversity gate — `DEPLOYED_SMOKE_PASS` (`3fe4bc2`, `68cc152`)

- same-source / entity / editorial_cluster diversity caps applied before final
  TOP5 selection; relax-to-fill retained when caps would leave fewer than 5.
- surfaced as `diversity_summary` / `diversity_rejected_items` in the prompt-input
  artifact, separate from the cross-day `dedup_summary`.
- entity/cluster detection is generalized (not NVIDIA-only): aliases such as
  OpenAI/Open AI, Microsoft/MS, Google/Alphabet, AWS/Amazon; expanded entities
  (Anthropic, Perplexity, Databricks, Oracle, Salesforce, Adobe, Broadcom, AMD,
  Intel, …) and clusters (platform_policy, enterprise_saas, cloud_infrastructure, …).
- the category classifier was **not** modified.

### Replacement pool preservation — `DEPLOYED_SMOKE_PASS` (`8bb93a9`, rev `genie-blog-run-00200-jbg`)

- preserves selected TOP5 + watchlist + safe rejected candidates so a duplicate
  reject can be replaced rather than shrinking the briefing.
- `downstream_candidate_source_ids` and `selection_pool` metadata exposed;
  `pre_diversity_candidate_count` may exceed 5; `selected_count = 5` retained.
- sufficient replacement → `relaxed = false`; insufficient → `diversity_relaxed = true`.
- `source_pack_funnel_summary` / `candidate_funnel_summary` surfaced.

### Cross-day owner-review exposure log — `DEPLOYED_SMOKE_PASS` (`0ef8fb9`, rev `genie-blog-run-00201-447`)

- `owner_review_exposure_log.json` (via `owner_review_exposure_log_store.py`) is a
  minimal foundation that feeds owner-review exposure rows into the existing
  `run_sent_news_dedup_gate` (merged with `recent_sent_news_log`). The dedup gate
  itself is unmodified.
- records only on a real owner-review send (`email_sent=True` /
  `artifact_status="emailed"`), and for body_only/body_and_image reissue only when
  selection differs from parent; never for stored/no-send/smoke/dry-run or
  image_only reissue. Reads fail-open.
- **completely separated from `sent_news_log.json`** (customer final-send log). An
  owner-review-only event must not pollute the customer final-send log.
- **cross-day entity/editorial_cluster matching is `OUT_OF_SCOPE_DEFERRED`**: the
  current pass only supplies exposure rows to the existing URL/title/source-title
  dedup gate.

Full recovery record:
[KEYSURI_RECOVERY_CLOSEOUT_2026_06_26.md](KEYSURI_RECOVERY_CLOSEOUT_2026_06_26.md).

## Image pipeline status

Image refresh is frozen. Rejected registry assets must not be used. Routine previews may use the approved canary fallback (`keysuri_global_hero_105936`) until owner approves a replacement.
