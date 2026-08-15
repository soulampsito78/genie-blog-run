# KeeSuri 등급형 품질 판정 운영 정책

## 목적

KeeSuri Global/Korea는 운영자 검토 시스템이다. 안전하지만 편집상 불완전한 초안은 숨기지 않고 운영자에게 경고와 함께 제공한다. 고객 발송은 별도의 명시적 승인 경계이며 항상 fail-closed다. Today Genie의 금융 검증 정책은 이 문서의 적용 대상이 아니다.

표준 흐름은 다음 하나다.

`탐지기 → 필드별 결정적 수리 → 최종 가시 표면 → 단일 정식 판정기 → 전달 정책`

탐지기는 finding만 만든다. 탐지기의 `ok`, 역사적 코드명의 `_blocked`, 개별 말줄임표·제목 규칙은 SMTP를 직접 중지할 권한이 없다. 콘텐츠 전달 행동을 정하는 곳은 `keysuri_quality_adjudication._canonical_delivery_matrix` 하나뿐이다.

## 두 개의 독립 판정축

안전성(`safety_verdict`)은 다음 중 하나다.

- `SAFE`: 구조·근거·의미·보안·권한상 고객 검토 후보로 안전하다.
- `UNSAFE`: 등록된 하드 블록 finding이 남았다.
- `INCONCLUSIVE`: 알 수 없는 코드나 판정 불충분 상태가 있어 안전을 확정할 수 없다.

편집 품질(`editorial_verdict`)은 다음 중 하나다.

- `READY`: 잔존 REVIEW finding이 없다.
- `REVIEW`: 안전하지만 운영자 확인이 필요한 잔존 finding이 있다.
- `POOR`: 안전하지만 잔존 REVIEW finding이 많아 완성본처럼 보내기 부적절하다. 현재 기준은 서로 구분되는 잔존 finding 6개 이상이다.

안전성과 편집 품질은 섞지 않는다. `SAFE + REVIEW`는 장애가 아니며 재실행 필수 상태도 아니다.

## 하드 블록 가족

하드 블록은 registry가 `BLOCK`으로 등록한 다음 가족으로 제한한다.

1. 구조적 사용 불가: JSON/필수 계약 오류, TOP5 누락·개수 오류, 필수 구조 누락, 렌더링 불가
2. 사실·근거 위험: 근거 없는 주장, 출처 누락·불일치, TOP5에 없는 사건 사용, 수리할 수 없는 잘못된 수치·기간
3. 의미 훼손: 근거로 복구할 수 없는 의미 단절, 의미가 달라진 잘림, 모순된 핵심 가시 필드
4. 보안·개인정보: 비밀·자격증명·개인 수신자 정보·금지된 민감 정보
5. 전달 권한: 운영자 승인 누락, 불변 승인 스냅샷 불일치, SMTP 결과 불명확

등록되지 않은 코드는 이름이나 접미사로 추측하지 않고 `INCONCLUSIVE`로 닫는다.

## 운영자 검토로 전환되는 finding

다음은 먼저 결정적 수리를 시도하고, 안전한 잔존이면 `REVIEW`다.

- 어색한 조사, 혼합 언어, 제목·인용부호의 타이포그래피
- 의미가 완전한 compact slash taxonomy
- 비밀을 포함하지 않는 raw English·구현 템플릿 표현
- 카테고리 불일치, 반복 filler·문장 뼈대·낮은 정보량 라벨
- deep-dive 중복, 약한 체크포인트·소스 설명·문체

역사적 코드명이 `_blocked`로 끝나더라도 registry가 `REVIEW`이면 하드 블록이 아니다.

## 수리 계약과 필드 소유권

수리는 producer/finalizer만 수행하며 다음 조건을 모두 만족해야 한다.

- 결정적이고 네트워크·모델 호출이 없다.
- 필드 유형과 근거를 알고 수행한다.
- 한 필드당 한 번의 정식 pass로 제한한다.
- 멱등이다: `repair(repair(text)) == repair(text)`.
- source-owned title은 동일 `source_id`와 rank의 canonical title로 손상 span만 대체한다. 없는 단어를 만들지 않는다.

필드 소유권은 `canonical_source_headline`, `model_generated_title`, `normalized_prose`, `repaired_visible_field`, `rendered_visible_surface`로 구분한다. 렌더 후 탐지기는 텍스트를 다시 쓰지 않는다.

finding 생명주기는 `DETECTED → REPAIRED` 또는 `DETECTED → RESIDUAL/TERMINAL`이다. 저장 배열은 다음처럼 분리한다.

- `pre_repair_findings`
- `repair_history`
- `repaired_issue_codes`
- `review_issue_codes`
- `terminal_issue_codes`

`issue_codes`는 호환용 합계일 뿐 판정 근거가 아니다. `REPAIRED` finding은 terminal이 될 수 없다.

## 최종 가시 표면 불변식

운영자가 받을 제목, HTML 가시 텍스트, 카테고리, checkpoint, deep-dive, 출처 라벨을 한 번 만든 뒤 판정한다. REVIEW 경고 패널과 제목 표식은 정식 판정기가 최종 표면을 선택할 때 한 번만 추가한다. 그 뒤에는 MIME/CID 포장만 허용되며 의미 변환은 금지한다.

`ADJUDICATED_VISIBLE_SURFACE_SHA256 == OWNER_EMAIL_VISIBLE_SURFACE_SHA256`

POOR에서는 전체 후보와 알림 표면을 별도로 해시한다. 전체 후보는 Admin에 보존하고 SMTP에는 간결한 품질 알림만 보낸다.

## 운영자 검토 전달 행렬

| 안전성 | 편집 | 운영자 행동 | 고객 승인 |
|---|---|---|---|
| SAFE | READY | 정상 운영자 검토 메일 | 표준 승인 가능 |
| SAFE | REVIEW | 제목 `[운영자 검토][주의]`, 경고 패널을 포함한 운영자 메일 | 경고 확인 후 승인 가능 |
| SAFE | POOR | 전체 후보 저장, Admin deep link가 있는 품질 알림 | 제공하지 않음 |
| UNSAFE/INCONCLUSIVE | 모두 | 운영자 후보 메일 없음, 진단·보류 기록 | 제공하지 않음 |

운영자는 REVIEW에서 수정 요청, 거절/보류, 경고 확인 후 그대로 승인을 선택할 수 있다. 어떤 경우에도 운영자 검토 메일은 고객 발송으로 계산하지 않는다.

## 고객 승인 행렬

고객 발송은 다음을 모두 만족해야 한다.

1. `safety_verdict=SAFE`
2. `editorial_verdict`가 `READY` 또는 `REVIEW`
3. 운영자의 명시적 고객 발송 확인
4. 현재 콘텐츠·제목·이미지·수신자·품질축을 포함한 불변 approval snapshot 일치
5. REVIEW이면 snapshot에 결합된 별도 경고 확인

`POOR`, `UNSAFE`, `INCONCLUSIVE`, 품질축이 없는 legacy artifact는 승인할 수 없다. 별도 override 정책은 현재 없다.

## 블록 지점 통합 기록

2026-08-15 변경 전 직접 콘텐츠 품질 차단 지점은 15개였다. service smoke의 레거시 편집 검증 1개, producer/reissue의 말줄임표 전용 4개, text-only reissue 2개, text+image reissue 3개, main full-run 4개, customer HTML 재검사 1개다. 변경 후 콘텐츠 품질 전달 결정 지점은 정식 delivery matrix 1개다. parse/schema/source/image/권한 같은 실행 전제 실패는 이 숫자에 포함하지 않는다. service smoke는 이제 Gemini 호출과 `parsed_valid` 계약만 실행 전제로 사용하며, 중간 검증 실패는 누락 방지 finding과 함께 최종 판정기로 전달한다.

| # | 파일·함수 | finding 가족 / 입력 단계 | 변경 전 직접 부작용 | 운영자 차단 | 고객 차단 | 중복 탐지 |
|---:|---|---|---|---|---|---|
| 1 | `_run_keysuri_service_full_run_impl` | 레거시 smoke 편집 검증 / 중간 owner preview | `smoke.ok=False`이면 즉시 실패 | 예 | 예 | 최종 표면 검증과 중복 |
| 2 | `keysuri_service_full_run._regenerate_keysuri_text_from_snapshot` | 말줄임표 / 재생성 본문 | 재생성 오류 반환 | 예 | 예 | 최종 visible-text와 중복 |
| 3 | `_repair_reissue_top5_from_live_selection` | 말줄임표 / live 재선정 | 후보 폐기·다음 시도 | 예 | 예 | 같은 producer 검사와 중복 |
| 4 | `_regenerate_keysuri_text_from_source_pack` reissue | 말줄임표 / enrich 후 | 재발행 오류 반환 | 예 | 예 | 최종 HTML 검사와 중복 |
| 5 | `_regenerate_keysuri_text_from_source_pack` legacy | 말줄임표 / 생성 본문 | 재발행 오류 반환 | 예 | 예 | 최종 HTML 검사와 중복 |
| 6 | `run_keysuri_text_only_reissue` | 말줄임표 / 최종 HTML | 즉시 실패 반환 | 예 | 예 | post-render와 중복 |
| 7 | `run_keysuri_text_only_reissue` | post-render 편집 finding | SMTP 전 실패 반환 | 예 | 예 | visible-text와 중복 |
| 8 | `run_keysuri_text_and_image_reissue` | 말줄임표 / enrich 후 | 즉시 실패 반환 | 예 | 예 | 최종 HTML 검사와 중복 |
| 9 | `run_keysuri_text_and_image_reissue` | 말줄임표 / 최종 HTML | 즉시 실패 반환 | 예 | 예 | post-render와 중복 |
| 10 | `run_keysuri_text_and_image_reissue` | post-render 편집 finding | SMTP 전 실패 반환 | 예 | 예 | visible-text와 중복 |
| 11 | `_run_keysuri_service_full_run_impl` | visible-text / 생성 본문 | block artifact·SMTP 억제 | 예 | 예 | 제목·HTML 검사와 중복 |
| 12 | `_run_keysuri_service_full_run_impl` | visible-text / 제목 | block artifact·SMTP 억제 | 예 | 예 | 본문·HTML 검사와 중복 |
| 13 | `_run_keysuri_service_full_run_impl` | visible-text / 최종 HTML | block artifact·SMTP 억제 | 예 | 예 | post-render와 중복 |
| 14 | `_run_keysuri_service_full_run_impl` | post-render 편집 finding | block artifact·SMTP 억제 | 예 | 예 | visible-text와 중복 |
| 15 | `keysuri_customer_delivery.prepare_keysuri_customer_delivery` | 말줄임표 / 저장 HTML | 고객 렌더 즉시 거절 | 아니오 | 예 | 이미 판정된 surface 재검사 |

변경 후 네 운영자 경로(image-only, text-only, text+image, full-run)는 모두 `adjudicate_keysuri_owner_surface` 결과를 정확히 한 번 소비한다. 고객 경로는 저장된 같은 `safety_verdict`·`editorial_verdict`와 불변 승인 snapshot을 소비하며 콘텐츠를 별도 의미 판정하지 않는다. 따라서 `BLOCK_DECISION_SITES_BEFORE=15`, `BLOCK_DECISION_SITES_AFTER=1`이다.

## 회귀 계보

검토 범위는 `49b3f94..64997fb`, `64997fb..fa786de`, `fa786de..21f1c3a`와 관련 파일의 개별 `log -S/-G`·blame이다.

- Global 2026-08-14 12:30 false pass: 단일 신규 회귀로 입증되지 않은 다층 producer/detector 공백이다. `49b3f94`는 문제를 만든 커밋이 아니라 잠복 결함을 드러낸 가시 표면 탐지 강화다.
- Korea AI/로봇: `build_korea_one_line_checkpoint`의 raw `existing` 반환은 `6eb0d3d`에서 들어온 잠복 수리 범위 결함이다. `f9e5751`가 두 반환 모두에 정식 prose 수리를 적용했다.
- Korea dangling quoted title: 범용 quote 경계 제거는 `eaa4532`에서 시작된 repair-introduced 잠복 결함이다. `ec986a8`/`49b3f94`의 탐지 강화가 드러냈고 `21f1c3a`가 동일 source/rank의 canonical title fallback으로 수리했다.

운영자 검토는 원인이 아니다. Global false pass는 운영자가 발견했다.

## 코퍼스와 shadow 운영

sanitized 기대 행렬은 `tests/fixtures/keysuri_graded_validation_corpus_20260815.json`에 둔다. 실제 원문 HTML/개인정보는 저장소에 복제하지 않는다. 코퍼스에는 8월 7·10·11·13일 성공/실패, Global 8월 14일 12:30/13:53, Korea AI/로봇과 dangling title 전후, unsupported claim과 ungrounded truncation control이 포함된다.

send 동작 변경 전 shadow replay는 모델·이미지·SMTP·고객·자연 실행 상태를 모두 0으로 유지한다. 성공 Global/Korea는 READY, Global 12:30은 SAFE+POOR, 복구 가능한 역사 결함은 SAFE+REVIEW, 구조/근거/의미 control은 UNSAFE+HOLD여야 한다.

| 대표 코퍼스 | 이전 | 새 safety/editorial | 새 운영자 행동 |
|---|---|---|---|
| Global 8/14 13:53 및 최근 정상 Global | OWNER_SENT | SAFE / READY | 정상 운영자 메일 |
| 최근 정상 Korea | OWNER_SENT | SAFE / READY | 정상 운영자 메일 |
| Global 8/14 12:31 false pass | OWNER_SENT_FALSE_PASS | SAFE / POOR | 전체 후보 저장 + 품질 알림 |
| Korea AI/로봇 수리 전 | SUPPRESSED | SAFE / REVIEW | 경고 운영자 메일 |
| Korea AI/로봇 수리 후 | NOT_RUN | SAFE / READY | 정상 운영자 메일 |
| Korea dangling title 수리 전 | SUPPRESSED | SAFE / REVIEW | 경고 운영자 메일 |
| 동일 source/rank grounded fallback 후 | NOT_RUN | SAFE / READY | 정상 운영자 메일 |
| unsupported claim / ungrounded truncation | SUPPRESSED | UNSAFE / READY | HOLD |

배포 후에는 보호된 `POST /internal/jobs/keysuri-graded-validation-proof`가 동일 판정기와 두 producer 수리를 로드된 revision 안에서 재검증한다. 이 증명은 모델·이미지·SMTP·고객·자연 실행·Scheduler를 모두 0으로 유지한다.
