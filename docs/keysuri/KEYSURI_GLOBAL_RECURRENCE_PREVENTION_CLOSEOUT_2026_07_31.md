# Kee-Suri Global 재발방지 클로즈아웃 — 2026-07-31

**Status: `KEESURI_GLOBAL_RECURRENCE_PREVENTION_COMPLETE`**

2026-07-30 KeeSuri Global 자연실행에서 연속 발생한 두 건의 장애와, 그 뒤 수행한
재발방지 컨트롤(A~D) 구현·배포의 정본 기록이다.

이 문서는 "모든 Global 장애가 불가능해졌다"는 선언이 아니다.
**식별된 재발 경로가 통제되었고, 검증된 장애는 닫혔으며, 이후 자연실행은 통상적인
운영 모니터링 대상으로 남는다.**

Status labels used here (only these): `사실`, `운영 판정`, `불변 조건`,
`미확인 사항`, `향후 자연실행 관찰 사항`.

---

## 1. 검증된 프로덕션 기준선 (사실)

| Item | Value |
|------|-------|
| commit | `f846f1bfc7cf14c238a0b41e12a293666d3d4e67` |
| commit message | `fix(keysuri): complete global generation recurrence controls` |
| Cloud Build | `f837c5f4-9e9f-4822-8a63-4d6b77b6a08c` (SUCCESS) |
| service / region | `genie-blog-run` / `asia-northeast3` |
| revision | `genie-blog-run-00268-fxh` |
| revision `commit-sha` label | `f846f1bfc7cf14c238a0b41e12a293666d3d4e67` (match) |
| image digest (build = deployed) | `sha256:a72ecb79f84c2eb813a8fa8ac72353e357f3cae7ce305c0693f466672365221f` |
| traffic | 100% (`latestRevision: true`) |
| Ready | `True` |
| health | `/health` → HTTP 200 |

**SHA 동일성 체인 (사실):**

```
tested SHA = committed SHA = Cloud Build source SHA = deployed revision commit-sha
= f846f1bfc7cf14c238a0b41e12a293666d3d4e67

build image digest = deployed image digest
= sha256:a72ecb79f84c2eb813a8fa8ac72353e357f3cae7ce305c0693f466672365221f
```

**테스트 결과 (사실):** recovery suite + recurrence harness `88 passed` ·
targeted regression `136 passed` · full suite `2436 passed, 21 failed, 1 skipped,
1 xfailed` · baseline 실패 목록 byte-identical · **신규 실패 0**.

21건은 이전부터 존재하는 baseline 실패이며 본 작업과 무관하다
(`test_keysuri_manual_opt_in_canary_runner` 7, `test_keysuri_offline_dry_run` 7,
`test_keysuri_prompt_input` 6, `test_keysuri_renderer` 1).

---

## 2. 장애 타임라인 (사실)

두 장애는 **서로 다른 원인**이며 하나의 단일 원인으로 묶지 않는다.

### 장애 1 — visible-text truncation 오탐

| | |
|---|---|
| 실행 | 자연 Scheduler 실행 |
| run_id | `20260730_185212_keysuri_global_tech_b09b8b02` |
| 증상 | `global_visible_text_truncated_deep_dive` 로 validation block |
| 도달 단계 | 소스 수집 → 생성 → 이미지 생성까지 완료 후 post-render QA에서 차단 |
| offending line | `구글 Gemini API 3.6 Flash 지원 및 훅 기능 추가` |

- **직접 원인:** `_find_truncated_visible_lines()` 의 조사(particle) 판정이
  마지막 어절의 **끝 음절 하나**만 검사했다. `추가`(명사)의 끝 음절 `가`가
  주격 조사 `가`와 겹쳐 정상 명사구 헤드라인이 절단으로 분류되었다.
- **기여 원인:** `가`/`과`/`로`/`이` 는 흔한 2음절 한자어 명사의 끝 음절과
  충돌한다(추가, 증가, 결과, 효과, 도로, 평가, 성과, 경로).
- **탐지 실패:** 헤드라인은 명사구로 끝나는 것이 정상인데, 검증기는 종결어미
  부재를 절단 신호로만 취급했다.
- **패치:** 조사 분기에 최소 Hangul 음절 수 조건을 추가. 절단된 꼬리는 보통
  3음절 이상(`발표가`, `투자에`, `기능을`)이라는 성질을 이용한다.
  ellipsis / dangling-connective 분기는 변경하지 않았다.
- **commit:** `e7f64caf2ec8f1d14e7d1ce160d3f3b2d79cd1f1`
- **revision:** `genie-blog-run-00266-6x5`

### 장애 2 — `program_id == ""` schema block

| | |
|---|---|
| 실행 | 자연 Scheduler 실행 |
| run_id | `20260730_202944_keysuri_global_tech_12c08526` |
| 증상 | `generated_briefing.program_id '' does not match 'keysuri_global_tech'` |
| 도달 단계 | 생성 후 schema validation에서 차단 (`called_image_api: false`) |

증거 (`parse_meta`, 사실):

```
expected_top_level_keys_present         []
top_5_news_present / deep_dive_present  false / false
json_candidate_count                    1
parser_recovery_used                    false
top_level_scope_heading_repair_applied  true
news_scope_actual_before_repair         null -> "global"
```

- **직접 원인:** 결정적(deterministic) 식별자 보정이 비대칭이었다.
  `news_scope` / `section_heading` 는 보정되었으나 `program_id` 는 보정 대상이
  아니어서 `""` 로 남았고, 그 결과가 headline 실패로 표면화되었다.
- **기여 원인:** raw model 응답이 파서 반환 시점에 폐기되어(문서화된 설계)
  응답 본문 형태를 사후 재구성할 수 없었다.
- **탐지 실패:** 실제 실패는 "필수 섹션이 전무한 응답"이었는데, 보고된 1차
  실패 코드는 `program_id_mismatch` 였다 — 오도(misleading) 분류.
- **패치:** sanitized model-output snapshot 추가, `program_id` 결정적 보정 추가
  (**missing/empty 한정**), 충돌하는 non-empty 식별자는 hard block 유지.
- **commit:** `14abfa5eed35485cc3694bf8a194cce7a55cb10a`
- **revision:** `genie-blog-run-00267-pxf`

### 자연 프로덕션 검증 실행

| | |
|---|---|
| run_id | `20260731_022412_keysuri_global_tech_36012cbb` |
| 결과 | validation pass · placeholder 없음 · truncation 없음 · 실제 기사 5건 완성 |
| 배송 | SMTP accepted · owner-review 메일 발송 · **Gmail 수신 owner 확인** · customer delivery 미발송 |
| 판정 | `KEESURI_GLOBAL_PRODUCTION_OWNER_REVIEW_PASS` (운영 판정) |

### 재발방지 리뷰에서의 발견 (사실)

Control A(bounded recovery)는 **이미 프로덕션 코드에 존재**했다:
`generate_keysuri_with_bounded_recovery()`,
`_run_global_bounded_contract_repair()`, `_GLOBAL_CONTRACT_REPAIR_CODES`,
기존 recovery diagnostics, 그리고 `tests/test_keysuri_generation_recovery.py`
52건. 따라서 Control A는 **재작성하지 않고 확장**했다.

실제 Control A 갭은 `GLOBAL_GENERATION_CALL_BUDGET = 3` 이었다 —
initial + optional MAX_TOKENS compact + optional full-contract repair 로
최대 3회 모델 호출이 가능했다.

---

## 3. 최종 컨트롤 설계 (불변 조건)

### Control A — bounded generation recovery

**불변 조건: 단일 KeeSuri Global 실행은 총 2회를 초과하는 모델 호출을 하지 않는다.**
(1) initial attempt, (2) 최대 1회의 eligible corrective attempt.

- `GLOBAL_GENERATION_CALL_BUDGET = 2`
- 재귀 없음, 무한 재시도 루프 없음, 숨겨진 3번째 호출 없음
- 재시도는 `_GLOBAL_CONTRACT_REPAIR_CODES` 에 명시된 코드에서만 허용
- 통상 validation 실패는 자동 재시도 대상이 아니다
- recovery 소진 시 image / email side effect 이전에 safe-fail
- recovery 성공 시 image 및 owner-review email 은 **정확히 1회**만 진행
- 실패한 recovery 는 side effect 이전에 진단을 보존
- 1차/2차 시도 정보는 구분 가능하게 유지

**식별자 3분류 (불변 조건):**

| 상태 | 처리 |
|---|---|
| missing `program_id` | 신뢰된 run context 로 결정적 보정 |
| empty `program_id` (`""`) | 신뢰된 run context 로 결정적 보정 |
| conflicting non-empty `program_id` | **hard block. 보정하지 않음. 재시도 대상 아님** |

충돌 식별자는 `_global_contract_repair_codes(['program_id_mismatch']) == []`
이므로 corrective 호출 자격이 없다.

### Control B — generation contract fingerprint

`generation_contract_record()` 가 시도마다 기록:

| 필드 | 목적 |
|---|---|
| `generation_contract_version` | 계약 버전 |
| `expected_program_id` | 기대 프로그램 식별자 |
| `expected_news_scope` | 기대 스코프 |
| `required_top_level_keys` | 필수 top-level 키 |
| `required_item_count` | 필수 기사 수 |
| `schema_fingerprint` | 스키마 지문 |
| `prompt_template_fingerprint` | 프롬프트 템플릿 지문 |
| `model_identifier` | 모델 식별자 |
| `generation_attempt` | 시도 번호 |
| `retry_reason` | 재시도 사유 |

**보안·프라이버시 불변 조건:** 지문만 저장하고 hidden prompt 본문은 저장하지
않는다. secret 미저장. raw model output 무제한 저장 금지. sanitized snapshot 은
**2000자 상한**이며 truncation 발생 여부를 함께 기록한다.

지문의 목적은 **system prompt 를 노출하지 않고** 두 실패가 동일한 generation
contract 하에서 났는지 판별하는 것이다.

### Control C — substantive failure priority

`classify_failure_priority()` 의 tier 순서 (구현 기준):

1. `no_extractable_json`
2. `contentless_or_missing_structure`
3. `conflicting_mode_or_identifier`
4. `missing_identifier_after_repair`
5. `section_schema_defect`
6. ordinary-content fall-through (`ordinary_content_validation_defect`)
7. `post_render_visible_text_defect`

- primary failure 는 가장 실행 가능한 root-classification 신호다
- secondary issue code 는 보존된다
- 후행 defect 가 선행 구조적 실패를 가리지 않는다
- 2026-07-30 contentless 응답 형태는 `top_5_news_missing`(구조 결손)이 primary 가
  되고 `program_id_mismatch` 는 secondary 로 강등된다

### Control D — recurrence observability

`keysuri_recurrence_metrics.py`:
`recurrence_counters_for_run()`, `aggregate_recurrence_counters()`,
`log_recurrence_counters()`.

카운터(구현 기준 실제 이름):

`generation_attempts`, `bounded_retry_count`, `retry_success`, `retry_exhausted`,
`json_extraction_failure`, `contentless_response_failure`,
`program_id_repair_count`, `conflicting_program_id_block_count`,
`schema_validation_failure`, `post_render_truncation_block`,
`global_run_success`, `global_run_safe_fail`

- 카운터는 **이미 저장된 진단**에서 파생된다
- 집계는 read-only 이며 side effect 가 없다
- secret 접근 불필요, live generation 호출 불필요
- 지표 이름은 incident 간 비교를 위해 안정적으로 유지한다

---

## 4. 시나리오 매트릭스 (테스트 기준)

`gen` = 최대 모델 시도 수. `img/email` = image 및 owner-review email 도달 가능 여부.
customer delivery 는 **모든 시나리오에서 불가** (owner 승인 별도 단계).

| # | 시나리오 | 분류 | 재시도 자격 | gen | 진행 | img/email | customer |
|---|---|---|---|---|---|---|---|
| 1 | known-good 응답 | — | 불필요 | 1 | 진행 | 가능 (1회) | 불가 |
| 2 | `추가` 로 끝나는 정상 국문 구 | — | 불필요 | 1 | 진행 | 가능 | 불가 |
| 3 | 실제 visible-text 절단 | `post_render_visible_text_defect` | 없음 | 1 | 차단 | 불가 | 불가 |
| 4 | missing `program_id` | 결정적 보정 | 불필요 | 1 | 진행 | 가능 | 불가 |
| 5 | empty `program_id` | 결정적 보정 | 불필요 | 1 | 진행 | 가능 | 불가 |
| 6 | conflicting non-empty `program_id` | `conflicting_mode_or_identifier` | **없음** | 1 | hard block | 불가 | 불가 |
| 7 | contentless → valid | `contentless_or_missing_structure` | 있음 | **2** | 진행 | 가능 (1회) | 불가 |
| 8 | contentless ×2 | `contentless_or_missing_structure` | 소진 | **2** | safe-fail | 불가 | 불가 |
| 9 | no-JSON → valid | `no_extractable_json` | 정책상 허용 시 | **2** | 정책에 따름 | 정책에 따름 | 불가 |
| 10 | no-JSON ×2 | `no_extractable_json` | 소진 | **2** | safe-fail | 불가 | 불가 |
| 11 | 통상 schema-invalid | `section_schema_defect` | **없음** | 1 | safe-fail | 불가 | 불가 |
| 12 | wrong-mode contamination | `conflicting_mode_or_identifier` | **없음** | 1 | hard block | 불가 | 불가 |
| 13 | placeholder title | `reissue_top5_placeholder_title` | 해당 없음 | — | 차단 | 불가 | 불가 |
| 14 | duplicate sentence | `reissue_top5_duplicate_sentence` | 해당 없음 | — | 차단 | 불가 | 불가 |
| 15 | secret sanitization | — | 해당 없음 | — | 진단만 | 불가 | 불가 |
| 16 | oversized snapshot | — | 해당 없음 | — | 2000자 절단 기록 | 불가 | 불가 |
| 17 | side-effect isolation | — | 해당 없음 | — | 실패 시 publishable payload 없음 | 불가 | 불가 |
| 18 | cross-mode regression | — | 해당 없음 | — | Global 보정 타 모드 미유출 | 불가 | 불가 |

---

## 5. 하네스 및 회귀 계약

- `tests/test_keysuri_generation_recovery.py` — 기존 recovery 하네스 **52건**
- `tests/test_keysuri_global_recurrence_harness.py` — 신규 recurrence 하네스 **36건**
- 합계 **88 passed** · targeted regression **136 passed**
- 하네스는 production parser / repair / classification / truncation / reissue /
  metrics 함수를 실제로 호출한다
- 외부 경계(model caller, send recorder)만 fake 로 대체한다
- production generation, network, Scheduler, image API, SMTP 는 사용하지 않는다

### 테스트 거버넌스 교훈 (자기검토 산출)

초기 하네스 일부가 다음을 단언했다:

```python
rec.smtp_calls == 0
```

그러나 그 recorder 는 production send path 에 **연결되어 있지 않았다**. 즉 이
단언은 **결코 실패할 수 없는** 무의미한 검증이었다.

해당 단언은 production-path gating 증거로 교체했다:

- `generated_briefing is None`
- 충돌 `program_id` 는 eligible contract-repair code 를 만들지 않음
  (`_global_contract_repair_codes(['program_id_mismatch']) == []`)
- 실제 send 횟수는 production send path 를 구동하는 기존 recovery suite 가 담당

**교훈 (불변 조건): fake/recorder 단언은 그 fake 가 실제로 대상 경로에 연결되어
있을 때에만 유효하다.**

---

## 6. Cross-mode 불변 조건

본 패치는 **Global 전용**이며 다음으로 유출되어서는 안 된다:
Today_Geenee, KeeSuri_Korea, Tomorrow_Geenee.

- Global 결정적 식별자 보정은 **다른 유효한 mode 식별자를 조용히 덮어쓰지 않는다**
- Today / Korea / Tomorrow 동작은 별도 승인 없이 변경되지 않는다
- cross-mode contamination 은 hard-block 조건이다
- recurrence 하네스는 cross-mode 회귀 커버리지를 유지한다
- 본 배포는 Scheduler 파일을 변경하지 않았다
- 본 배포는 Admin UI 를 변경하지 않았다
- 본 배포는 customer delivery 를 변경하지 않았다
- 본 배포는 Tomorrow 를 활성화하거나 복구하지 않았다

---

## 7. 미확인 사항 / 향후 자연실행 관찰 사항

**미확인 사항**

- 2026-07-30 `12c08526` 에서 모델이 contentless 응답을 반환한 **근본 이유**는
  미확인이다. 당시 raw 응답이 보존되지 않았다. 재발 시에는
  `raw_response_snapshot` 으로 귀속 판정이 가능하다.

**향후 자연실행 관찰 사항**

- 식별된 재발 경로는 통제되었으나, 이후 자연실행은 통상적인 운영 모니터링
  대상으로 남는다.
- `global_run_safe_fail`, `retry_exhausted`, `post_render_truncation_block`,
  `conflicting_program_id_block_count` 추세를 관찰한다.
- baseline 실패 21건은 별개 사안으로 남아 있다.

---

## 8. 최종 판정

**`KEESURI_GLOBAL_RECURRENCE_PREVENTION_COMPLETE`** (운영 판정)

식별된 재발 메커니즘 통제 완료 · 검증된 배포 완료 · 신규 회귀 실패 0 ·
통상 운영 모니터링 계속 필요.
