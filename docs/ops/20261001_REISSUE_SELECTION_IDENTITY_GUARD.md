# 2026-10-01 재발행 기사 identity 차단

## 확인된 결함

새 기사 다섯 개와 본문 seed의 연결이 0/5인데도 live-selection repair가
일반 fallback 카드와 기존 도입부·딥다이브를 합성해 구조 검증 성공으로
반환했다. 원래 parent scaffold도 기사 변경 여부와 무관하게 허용했다.
뒤의 reader gate는 카드를 보류했지만 기존 narrative와 새 출처의 불일치는
owner 메일에 남았다. 구조 pass는 기사 의미 일치와 같지 않다.

## 가장 작은 변경

안티그래비티가 제한된 비식별 코드로 구현안을 반환하고 Work가 독립 검수했다.
실제 인터페이스 이름 불일치를 발견해 첫 반환안을 적용하지 않고 재요청했다.

- generated seed 연결이 0/5 또는 진단 불명이면 publishable repaired payload를 반환하지 않는다.
- parent scaffold는 양쪽 모두 정확히 다섯 개의 고유한 nonempty canonical URL이 같을 때만 허용한다.
- URL 없는 title/news_id fallback을 parent identity 증거로 인정하지 않는다.
- 기존 partial repair, 완전 정상 한국어·영어 seed 처리, positional conflict guard,
  최종 reader/source 검수, 고객 발송 권한 및 중복 차단은 유지한다.
- 새 회귀 테스트를 offline product release gate에 포함한다.

이 패치는 과거 HOLD 후보를 PASS로 변경하지 않는다. 새로운 고객 발송이나
추가 운영 재발행을 자동 실행하지 않는다. 원시 모델 출력의 identity가 왜
달라졌는지는 확인되지 않았으며, 이 문서로 모델 원인을 추정 확정하지 않는다.
