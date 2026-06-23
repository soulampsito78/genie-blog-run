# genie-blog-run 서비스 네이밍 & 카피 전략 (v2 — 외부 소개 범위 재정의)

작성 기준: **현재 레포(`soulampsito78/genie-blog-run`, HEAD `980f400`) 루트의 실제 코드·문서 직접 감사**
재검토 사유: v1이 레포에 존재하는 모든 mode를 외부 서비스 라인업으로 취급한 오류 수정
작성일: 2026-06-22

> 작업 위치 확인: `/.../git_Genie_Project/genie-blog-run` = `git@github.com:soulampsito78/genie-blog-run.git`. 본 문서의 모든 결론은 이 레포 파일을 근거로 한다.

---

## 0. 반드시 명시하는 3대 전제 (출력 규칙 준수)

- **“tomorrow_genie는 레포상 존재하지만 현재 외부 소개/네이밍 전략의 중심에서는 제외한다.”**
- **“keysuri_global_tech / keysuri_korea_tech의 실제 스케줄은 레포 또는 운영 설정에서 근거가 확인된 경우에만 표기한다.”**
- **“스케줄 근거가 없으면 서비스 카피에는 시간대를 쓰지 않는다.”**

---

## 1. 오류 진단 (v1 무엇이 틀렸나)

**① tomorrow_genie를 외부 소개 중심축에 넣은 것**
- 근거: `programs/registry.py`의 `PROGRAMS` 레지스트리에는 **today_geenee / keysuri_global_tech / keysuri_korea_tech 3개만** 등록되어 있고 **tomorrow_genie는 없다.** 이 레지스트리가 “separated GENIE lifecycle programs”의 정본(foundation)이다.
- tomorrow_genie는 `admin_store.py`(L15, L40, L55)·`main.py`(L92 `SUPPORTED_MODES`)·README에는 남아 있으나, **분리된 프로그램 정본에서 빠져 있음** → “레포에 코드가 있다”와 “현재 소개하는 상품 라인이다”는 다르다. v1은 이 둘을 혼동했다.
- 추가로 스케줄도 문서 간 충돌(README 15:00 / ROLLOUT·DEPLOY 14:00 / `SCHEDULE_OVERRIDE.md` 18:00)로 **운영 시각조차 정합되지 않은 상태** → 외부 소개에 올릴 안정성이 없다.

**② 키수리 스케줄을 06:30/15:00 식으로 단정한 것 (v1은 today_genie 06:30·tomorrow 15:00을 그대로 카피에 넣음)**
- 작성 당시 근거(2026-06-22, 이제 superseded): `docs/keysuri/KEYSURI_SCHEDULER_STATE_AND_FUTURE_WIRING_DESIGN.md` §1.1 — 당시 문서는 **“No active Key-Suri scheduler exists”, “Cron definition for Key-Suri: Not found in repo”** 라고 기록했었다. 이는 **2026-06-23 GCP 운영 감사로 무효화된 과거(stale) 진단**이다.
- **2026-06-23 GCP 감사로 확정된 현재 상태**: `KeeSuri_Global_Tech`(12:30 KST, 평일), `KeeSuri_Korea_Tech`(18:30 KST, 평일) 두 Cloud Scheduler 작업 모두 **ENABLED**. `programs/registry.py`의 `schedule_kst`(global 12:30 / korea 18:30)는 이제 **실제 운영 중인 cron 트리거와 일치**한다(`docs/keysuri/KEYSURI_SCHEDULER_STATE_AND_FUTURE_WIRING_DESIGN.md` §1.1, 2026-06-23 개정판 기준).
- v1의 오류는 “스케줄이 없는데 있다고 단정”한 것이 아니라 **today_genie/tomorrow_genie 시각을 키수리에 잘못 적용**한 부분만 유효하다. 키수리 자체 스케줄 부재 진단은 더 이상 유효하지 않다.

**③ “시장·테크·날씨 3축” 정의의 구조적 오류**
- 3축 중 ‘날씨’축(tomorrow_genie)이 정본 레지스트리에 없고 스케줄도 충돌 → 3축 정의는 **존재하지 않는 상품 구성을 광고**하는 셈. 폐기한다.

**④ 분리 원칙**
- “레포에 존재(코드/모드/검증기)” ≠ “현재 외부 소개 범위”. 앞으로 모든 결론에 근거 파일을 달되, 이 둘을 절대 합치지 않는다.

---

## 2. 수정된 서비스 본질 정의

**상위 정의**
AI가 매일 중요한 **시장·기술 신호를 구조화**하고, **운영자가 검수**한 뒤 **이메일로 전달**하는 **프라이빗 브리핑 서비스.**

근거:
- 검수 후 발송 구조: `admin_store.py` `approve_run`(L646~) — 승인 시에만 customer final email 발송. `can_approve_customer_send`(L548~)가 owner 승인·게이트 통과를 강제.
- 모든 프로그램이 승인 필수: `programs/registry.py` 각 스펙 `customer_send_requires_approval=True`.
- 환각 방지/근거 기반: 키수리 생성 프롬프트가 “private tech secretary” 정체성과 신호 정리 역할로 한정(`keysuri_generation_prompt.py` L282), today 라인은 금융 피드 게이트(`source_gate_profile="genie_finance_feed_gate"`).

**고객용 한 줄**
오늘 시장에서 먼저 볼 변수와, AI·테크 흐름의 기회·리스크를 — AI가 정리하고 운영자가 직접 확인한 브리핑만 이메일로 보냅니다.

**절대 쓰면 안 되는 정의**
- “AI 뉴스 자동 발행” → `approve_run` 없이는 발송 불가(`admin_store.py` L646~).
- “투자 추천” → 키수리/지니 모두 의사결정 대행 금지 톤.
- “실시간 뉴스” → 입력 데이터 부족 시 생성 축소/보류(today 피드 staleness 처리 `main.py` L197~).
- “날씨 포함 종합 생활 브리핑” → 해당 축(tomorrow_genie) 외부 소개 제외.

---

## 3. 수정된 지니 / 키수리 관계 정의

- **오늘의 지니(today_geenee)** 와 **키수리(keysuri_global_tech / keysuri_korea_tech)** 는 **병렬 서비스 라인**이다.
  - 근거: `programs/registry.py`에 두 페르소나(`persona_id="genie_today"` / `"keysuri"`)가 동급 프로그램으로 등록.
- **내일의 지니(tomorrow_genie)** 는 **현재 외부 소개 범위 제외**(future/별도 감사 전 scope). 홈페이지·랜딩·서비스명·10초/30초 소개문에 넣지 않는다.

| 라인 | program_id | 페르소나 | 역할(role) | 도메인 | 외부 소개 |
|------|-----------|---------|-----------|--------|----------|
| 오늘의 지니 | today_geenee (legacy today_genie) | genie_today | warm_morning_anchor | 장전 시장·금융 | **중심 포함** |
| 키수리(글로벌) | keysuri_global_tech | keysuri | 프리미엄 AI 테크 비서 | 글로벌 AI·빅테크·반도체·플랫폼·정책 | **중심 포함** |
| 키수리(국내) | keysuri_korea_tech | keysuri | 프리미엄 AI 테크 비서 | 국내 AI·스타트업·플랫폼·정책 | **중심 포함** |
| 내일의 지니 | tomorrow_genie | (genie) | 날씨·라이프 캐스터 | 날씨·생활 | **제외(PAUSED/retired — 현재 비활성)** |

키수리 정체성 근거: `keysuri_generation_prompt.py` L21 `IDENTITY_TITLE="테크 비서 키수리"`, L22 `IDENTITY_SUBTITLE="프라이빗 테크 비서"`, L311 이메일 제목 `[키수리 브리핑]` prefix.

---

## 4. 스케줄 감사 표 (2026-06-23 GCP 운영 감사 기준으로 갱신)

> 2026-06-23 `gcloud scheduler jobs list/describe` 직접 감사로 아래 표의 “운영 상태” 컬럼을 확정함. 이전(2026-06-22) 버전은 레포 내부 코드만 보고 “레포에 cron 근거 없음”이라 적었으나, 이는 **레포와 GCP 운영 설정의 차이를 반영하지 못한 stale 진단**이었다.

| 서비스/모드 | 스케줄(KST) | 근거 파일/설정 | endpoint | body/type | 운영 상태 (2026-06-23 GCP 감사 확정) | 외부 소개 반영 |
|---|---|---|---|---|---|---|
| **today_genie(오늘의 지니)** | **06:30**, 평일(주말 skip 가드 적용) | `programs/registry.py` `schedule_kst`, `genie_schedule_policy.py`(주말 skip) | `POST /internal/jobs/create-owner-review` (`internal_jobs.py` L259) | scheduler→owner-review, 주말 skip(`genie_schedule_policy.py`) | **Scheduler ENABLED**, 06:30 KST 평일(주말 가드 후) — owner-review→approve→customer delivery 경로 구현·운영 중 | **포함** (카피엔 ‘개장 전/장전’ 정성 표현, 확정 시각은 06:30로 명시 가능) |
| **keysuri_global_tech(키수리 글로벌)** | **12:30**, 평일 | `programs/registry.py` L66, GCP 작업명 `KeeSuri_Global_Tech` | `POST /internal/jobs/create-keysuri-owner-review` (`internal_jobs.py` L404) | 기본 smoke / `service_full_run=True` 시 실제 생성·메일 | **Scheduler ENABLED** — `KeeSuri_Global_Tech` 12:30 KST 평일, 2026-06-23 audit에서 200 OK 확인. 고객발송 코드(`approve_run`)도 운영 경로로 사용 중 | **포함**, 시간대 12:30 KST 명시 가능(“정기 테크 브리핑”) |
| **keysuri_korea_tech(키수리 국내)** | **18:30**, 평일 | `programs/registry.py` L90, GCP 작업명 `KeeSuri_Korea_Tech` | 동상 | 동상; 국내는 bottom-shot 베이스라인 게이트 추가 | **Scheduler ENABLED** — `KeeSuri_Korea_Tech` 18:30 KST 평일, 2026-06-23 audit에서 200 OK 확인 + korea bottom 게이트(`admin_store.py` L550) | **포함**, 시간대 18:30 KST 명시 가능 |
| **tomorrow_genie(내일의 지니)** | **PAUSED**(비활성/retired) | `README.md`, `ROLLOUT.md`, `DEPLOY.md`, `SCHEDULE_OVERRIDE.md` / **`programs/registry.py`엔 미등록** | `create-owner-review` 계열(모드 분기) | scheduler→owner-review | **PAUSED — 운영상 비활성/retired.** 현재 핵심(core) 서비스로 취급하지 않음 | **제외(PAUSED/retired, 외부 소개 범위 아님)** |

핵심: **2026-06-23 GCP Cloud Scheduler 직접 감사로 today_genie(06:30) / keysuri_global_tech(12:30) / keysuri_korea_tech(18:30) 세 작업의 ENABLED 상태와 시각이 모두 확정되었다.** tomorrow_genie만 PAUSED. → **today_genie·키수리 카피에는 확정 시각을 명시할 수 있다.**

추가 운영 상태 근거(고객 발송 가능 여부):
- today_genie: `approve_run`→`send_today_geenee_customer_final_email`(`admin_store.py` L666~). **고객 발송 경로 구현·운영 중.**
- keysuri global/korea: `approve_run`→`send_keysuri_customer_final_email`(`admin_store.py` L672~), 게이트 `can_approve_customer_send`(global: `customer_delivery_config_ready`; korea: bottom 베이스라인+config). **고객 발송 확인됨 — 2026-06-23 audit에서 `customer_delivery_status=smtp_accepted` 아티팩트로 확정.** 발송은 owner-review→`approve_run` 승인 후에만 발생(자동 발송 아님).
- 상태값: `pending_review → approved / reopened / approval_expired_manual_required`(`admin_store.py` L24), 파생 artifact_status `generated/validated/review_required/emailed`(L307~315).
- 베타 고객 수신자 관리: `/admin/customer-recipients`(admin UI) — env baseline + admin config 조합으로 수신자 목록 운영. 수신자 저장 자체는 이메일 발송을 트리거하지 않음(별도 `approve_run` 필요).

---

## 5. 수정된 서비스명 후보 TOP 20

원칙: **날씨·라이프·내일 준비 뉘앙스 전면 제외.** 축은 **시장 신호 + 테크 신호 + 프라이빗(검수형) 브리핑.**

| # | 후보 | 점수 | 메모(근거/적합성) |
|---|------|-----|------|
| 1 | **프라이빗 브리핑** | 9 | 키수리 정체성 `프라이빗 테크 비서`(코드)와 직결, 검수형 ‘당신에게만’ 뉘앙스 |
| 2 | **키수리 브리핑** | 8 | 이메일 제목 `[키수리 브리핑]`(코드)과 연속성 |
| 3 | 시그널 브리핑 | 8 | ‘신호 정리’ 본질 정확, 시장+테크 포괄 |
| 4 | 마켓·테크 시그널 | 7 | 2개 라인을 한 번에 표현 |
| 5 | 오늘의 지니 · 키수리 | 7 | 현 병렬 라인 그대로(가장 현실적) |
| 6 | 시그널 데스크 | 7 | 참모형 톤, 권위감 |
| 7 | 브리핑 데스크 | 7 | 업무형·직관 |
| 8 | 데일리 시그널 | 6 | 리듬감, 범용 |
| 9 | 커맨드 브리핑 | 7 | 의사결정자용 권위 |
| 10 | 참모 브리핑 | 7 | 추천 톤(대표 참모형)과 일치 |
| 11 | 프라이빗 시그널 | 7 | 1·3번 결합형 |
| 12 | 시그널 레터 | 6 | 세련, 단 ‘레터=뉴스레터’ 오해 주의 |
| 13 | 인사이트 브리핑 | 6 | 제안서 친화 |
| 14 | AI 큐레이션 브리핑 | 6 | 고급감, 단 길다 |
| 15 | 테크 비서 키수리 | 7 | 키수리 라인 단독 브랜드명 |
| 16 | 지니·키수리 | 7 | 기존 자산 유지 |
| 17 | 브리핑 OS | 7 | 확장형 상위 브랜드 |
| 18 | 시그널 OS | 6 | 플랫폼 확장 뉘앙스 |
| 19 | 브리핑 구독 | 6 | B2B 제안서 직삽입 |
| 20 | Briefia | 6 | 영문 상표 확장용 |

제외(이번 기준 위반): ‘내일 준비/모닝/굿모닝/날씨/라이프/데일리 라이프’ 류 일체.

---

## 6. 최종 추천 서비스명 TOP 5

1. **프라이빗 브리핑** — 코드 정체성(프라이빗 테크 비서)·검수 구조와 정확히 일치
2. **키수리 브리핑** — 기존 이메일 제목 패턴과 연속성, 인지자산 활용
3. **시그널 브리핑** — ‘신호 정리’ 본질을 가장 직관적으로
4. **오늘의 지니 · 키수리** — 현 병렬 라인을 그대로 노출하는 현실적 선택
5. **참모 브리핑** — 추천 톤(대표 참모형)과 직결, ‘판단은 대표가’ 포지션

---

## 7. 최종 1순위 서비스명

### **프라이빗 브리핑 by 지니·키수리**

- 상위 브랜드: **프라이빗 브리핑**(검수형·소수 전달 뉘앙스)
- 하위 병렬 라인: **오늘의 지니**(장전 시장) · **키수리**(글로벌/국내 테크)
- 근거: `keysuri_generation_prompt.py` L22 `프라이빗 테크 비서` + 전 프로그램 `customer_send_requires_approval=True`(검수 후 발송) → ‘프라이빗’이 서비스 구조와 정확히 맞는다.

---

## 8. 10초 소개문 (내일의 지니·날씨 언급 금지)

> AI가 매일 시장과 기술 신호를 정리하고, 사람이 검수한 브리핑만 이메일로 보냅니다.

대안:
- 시장과 테크의 핵심 신호를, 검수된 한 통으로.
- 읽기 전에 이미 정리돼 있는, 프라이빗 브리핑.

---

## 9. 30초 소개문 (오늘의 지니 + 키수리만)

> 오늘 개장 전 시장에서 먼저 봐야 할 변수와 리스크, 그리고 AI·빅테크·스타트업·정책으로 이어지는 테크 흐름 — 두 가지를 AI가 구조화하고 운영자가 직접 확인한 뒤 보냅니다.
> 오늘의 지니는 시장을, 키수리는 글로벌·국내 기술 기회를 읽습니다.
> 자동 발행이 아닙니다. 없는 수치를 만들지 않고, 사람이 검수한 브리핑만 당신의 이메일에 도착합니다.

---

## 10. 홈페이지 헤드라인 / 서브헤드 / CTA

(“시장·테크 신호” 중심 / 날씨·완전자동·투자추천 제외)

**헤드라인 5**
1. 열기 전에, 이미 정리되어 있습니다.
2. AI가 초안을 쓰고, 사람이 검수해 보냅니다.
3. 시장과 기술, 두 신호를 한 통으로.
4. 뉴스를 읽지 않아도 되는 하루.
5. 대표가 판단할 수 있는 형태로, 매일 한 통.

**서브헤드 5**
1. AI가 시장·테크 신호를 구조화하고, 운영자가 검수한 브리핑만 이메일로 도착합니다.
2. 오늘의 지니는 장전 시장을, 키수리는 글로벌·국내 테크 흐름을 정리합니다.
3. 없는 수치를 만들지 않습니다. 근거 없는 내용은 보내지 않습니다.
4. 뉴스 요약이 아니라, 오늘 먼저 봐야 할 신호 정리입니다.
5. 공개 피드가 아닌, 검수된 프라이빗 브리핑입니다.

**CTA 8**
1. 프라이빗 브리핑 받기 / 2. 오늘의 지니 시작하기 / 3. 키수리 테크 브리핑 신청
4. 브리핑 구독하기 / 5. 첫 브리핑 받아보기 / 6. 이메일로 받기 / 7. 데모 브리핑 보기 / 8. 지금 신청하기

---

## 11. 제안서용 소개문

> 본 서비스는 **AI 기반 브리핑 초안화 + 운영자 검수 후 이메일 전달 시스템**입니다. 매일 **장전 시장·금융 신호(오늘의 지니)** 와 **글로벌·국내 테크 신호(키수리)** 를 구조화된 이메일 브리핑으로 지정 수신자에게 전달합니다. AI 생성과 고객 발송 사이에 **운영자 검수·승인 단계가 반드시 포함**되며(`approve_run` 승인 시에만 발송), 입력 데이터가 부족하면 생성을 축소하거나 발송을 보류하는 안전장치가 내재되어 있습니다. 정기 발송 시각은 운영 환경(Cloud Scheduler) 설정을 따릅니다.

---

## 12. 블로그 / 랜딩페이지 장문 소개문

> 매일 아침 시장이 열리기 전, 어젯밤 미국 증시가 어떻게 움직였는지, 오늘 확인해야 할 변수가 무엇인지 — AI가 먼저 정리합니다. 그리고 AI·빅테크·반도체·플랫폼·정책으로 이어지는 기술 흐름을, 키수리가 글로벌과 국내 두 갈래로 나눠 신호 카드와 딥-다이브로 정리합니다.
>
> 이 서비스는 단순한 뉴스 요약이 아닙니다. AI가 시장·테크 신호를 입력받아 구조화된 브리핑 초안을 작성하고, **운영자가 직접 검수한 내용만** 고객 이메일로 전달합니다. 없는 수치를 만들지 않고, 입력 데이터가 충분하지 않으면 그 사실을 그대로 반영합니다.
>
> 두 개의 라인이 있습니다. **오늘의 지니**는 장전 시장에서 먼저 볼 변수와 리스크를 정리합니다. **키수리**는 글로벌·국내 테크의 기회와 리스크를 읽는 프라이빗 테크 비서입니다.
>
> 자동 발행이 아닙니다. AI가 초안을 쓰고, 운영자가 검수하고, 사람이 승인한 뒤에야 당신의 이메일에 도착합니다.
>
> 매일 직접 정보를 모으고 판단하는 데 쓰던 시간을, 이미 정리된 브리핑 한 통을 읽는 시간으로 줄이고 싶다면 — 그것이 이 서비스가 존재하는 이유입니다.

(※ 날씨/내일 준비 라인은 의도적으로 제외. 현재 외부 소개 범위가 아님.)

---

## 13. 금지어 / 오해 표현

| 금지 표현 | 사유(근거) |
|---|---|
| 자동 발행 / 완전 자동 | `approve_run` 승인 없이는 미발송(`admin_store.py` L646~) |
| 무인 운영 | owner-review는 항상 사람(검수 게이트 `can_approve_customer_send`) |
| 투자 추천 / 매수·매도 타이밍 / 수익 보장 | 의사결정 대행 금지 톤, 법적 위험 |
| 실시간 뉴스 | 데이터 부족 시 생성 축소/보류(`main.py` staleness 처리) |
| 날씨까지 포함한 종합 생활 브리핑 | tomorrow_genie 외부 소개 제외 |
| 시장·테크·날씨 3종 패키지 | 동일 — 3축 정의 폐기 |
| ~~(키수리) 12:30·18:30 등 확정 시각은 금지~~ | **해제(2026-06-23)**: GCP 감사로 `KeeSuri_Global_Tech` 12:30 KST, `KeeSuri_Korea_Tech` 18:30 KST ENABLED 확정 → 카피에 시간대 명시 가능 |

---

## 14. 새 카피 방향 (확정)

- “시장과 기술 신호를 매일 정리하는 **프라이빗 브리핑**”
- “**오늘의 지니는 시장을, 키수리는 기술 기회를 읽는다**”
- “뉴스 요약이 아니라, **대표가 판단할 수 있는 신호 정리**”
- “**AI가 초안을 만들고, 운영자가 검수해 보내는** 브리핑”
- “장전 시장 브리핑 + 테크 인사이트 브리핑”

추천 톤: **대표 참모형** — “알아서 다 해드립니다”가 아니라 “필요한 신호를 미리 정리해 드립니다. 판단은 대표님이 하십니다.” → 레포의 검수(approve) 아키텍처와 가장 정합.

---

## 15. 다음에 검증할 질문 (운영콘솔/오너 확인 필요)

1. ~~실제 GCP Cloud Scheduler 시각 미확인~~ — **해결됨(2026-06-23 GCP 감사)**: today_genie 06:30 KST 평일, keysuri_global_tech 12:30 KST 평일, keysuri_korea_tech 18:30 KST 평일, 모두 **ENABLED** 확정. tomorrow_genie는 PAUSED.
2. ~~키수리 고객 발송 활성화 여부 미확인~~ — **해결됨**: 2026-06-23 audit에서 `customer_delivery_status=smtp_accepted` 아티팩트로 키수리 고객 발송 확인됨. 발송은 owner-review 승인(`approve_run`) 후에만 발생.
3. **tomorrow_genie 재도입 시점** — 정본 레지스트리 편입·스케줄 정합 후에만 외부 소개 재검토. 현재는 PAUSED/retired 상태이며 core 서비스로 취급하지 않음.
4. **수신자 규모/유료화** — `EMAIL_TO` 기반 소수 큐레이션 vs 오픈 구독(레포에 구독 DB·결제 구조 미확인). 베타 수신자 관리는 `/admin/customer-recipients`(admin UI)에서 운영 중.
