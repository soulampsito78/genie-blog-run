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

## Image pipeline status

Image refresh is frozen. Rejected registry assets must not be used. Routine previews may use the approved canary fallback (`keysuri_global_hero_105936`) until owner approves a replacement.
