"""Date-bound, time-neutral copy rules for Today frozen-selection replays.

This describes preparation, never SMTP delivery or the current trading session.
No market-opening time is inferred and no prose or source fact is rewritten here.
"""
from datetime import date, datetime
import re
from typing import Any, Dict, Iterator, Tuple
from zoneinfo import ZoneInfo

from genie_schedule_policy import holiday_calendar_covers, is_korean_publishing_day

CONTEXT_KEY = "today_replay_context"
CONTEXT_SCHEMA = "today-replay-context-v1"
_PARENT = re.compile(r"(?P<day>[0-9]{8})_[0-9]{6}_today_genie_[0-9a-f]{8}")
_TOP_FIELDS = ("title", "greeting", "summary", "market_setup", "closing_message")
_CARD_FIELDS = {
    "key_watchpoints": ("headline", "detail", "what_happened", "why_it_matters_today", "what_to_watch_in_korea"),
    "risk_check": ("risk", "detail"),
    "opportunities": ("theme", "reason"),
}


def replay_context_valid(context: Any) -> bool:
    if not isinstance(context, dict) or context.get("schema") != CONTEXT_SCHEMA:
        return False
    try:
        target = date.fromisoformat(context["target_date"])
        if target.isoformat() != context["target_date"]:
            return False
        parent = _PARENT.fullmatch(context["parent_run_id"])
        prepared = datetime.fromisoformat(context["prepared_at_kst"])
        if not parent or prepared.tzinfo is None or prepared.utcoffset() is None:
            return False
        return (
            parent["day"] == target.strftime("%Y%m%d")
            and prepared.astimezone(ZoneInfo("Asia/Seoul")).date() == target
            and holiday_calendar_covers(target)
            and is_korean_publishing_day(target)
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def build_today_replay_context(runtime_input: Dict[str, Any], parent_run_id: str) -> Dict[str, str]:
    context = {"schema": CONTEXT_SCHEMA, "parent_run_id": parent_run_id,
               "target_date": runtime_input.get("target_date"),
               "prepared_at_kst": runtime_input.get("briefing_generated_at_kst")}
    if not replay_context_valid(context):
        raise ValueError("today_replay_context_unavailable_or_date_mismatch")
    context["prepared_at_kst"] = datetime.fromisoformat(context["prepared_at_kst"]).astimezone(ZoneInfo("Asia/Seoul")).isoformat()
    return context


def is_today_replay(payload: Dict[str, Any]) -> bool:
    return replay_context_valid(payload.get(CONTEXT_KEY))


def replay_prepared_label(context: Dict[str, Any]) -> str:
    if not replay_context_valid(context):
        return ""
    prepared = datetime.fromisoformat(context["prepared_at_kst"]).astimezone(ZoneInfo("Asia/Seoul"))
    return prepared.strftime("%Y.%m.%d %H:%M KST")


def replay_context_prompt(runtime_input: Dict[str, Any]) -> str:
    context = runtime_input.get(CONTEXT_KEY)
    if not replay_context_valid(context):
        return ""
    return f"""[TODAY_REPLAY_TIME_CONTEXT — overrides pre-open style instructions]
    이 본문은 {context['target_date']}의 재발행본이며 작성 기준시각은 {context['prepared_at_kst']}이다.
    title, channel_drafts.email_subject, channel_drafts.naver_blog_title,
    greeting, summary, market_setup, key_watchpoints의 전체 문장, opportunities,
    risk_check, closing_message 모두 시점 중립 문체로 쓴다.
    '오늘 장전', '장을 시작해야 합니다', '개장을 앞두고'처럼 개장 전으로 되돌리는 지시와
    '첫 30분을 확인해야 한다' 같은 이미 경과할 수 있는 시간대의 미래 권고를 쓰지 않는다.
    개장 여부, 장중 실시간 지수·수급 또는 첫 30분의 실제 결과를 추정하거나 만들어 넣지 않는다.
    입력의 기사·순서·식별자·URL·수치·불확실성과 표시된 마감 세션 기준을 보존한다.
    작성 기준시각은 발송·실수신 시각이 아니다. 내부 문맥 키를 모델 출력에 생성하지 않는다.
    """


def customer_text_values(data: Dict[str, Any]) -> Iterator[Tuple[str, str]]:
    for key in _TOP_FIELDS:
        if isinstance(data.get(key), str):
            yield key, data[key]
    drafts = data.get("channel_drafts")
    if isinstance(drafts, dict):
        for key in ("email_subject", "naver_blog_title"):
            if isinstance(drafts.get(key), str):
                yield f"channel_drafts.{key}", drafts[key]
    for collection, fields in _CARD_FIELDS.items():
        rows = data.get(collection)
        if isinstance(rows, list):
            for index, row in enumerate(rows):
                if isinstance(row, dict):
                    for key in fields:
                        if isinstance(row.get(key), str):
                            yield f"{collection}[{index}].{key}", row[key]


def replay_temporal_conflicts(data: Dict[str, Any]) -> list[str]:
    """Conservative editorial findings; do not replace historical statements."""
    conflicts = []
    for field, text in customer_text_values(data):
        # Inspect clauses, never rewrite them. A reference to a past time window
        # is allowed; a current reader instruction about that window is not.
        inspected = _PAST_WINDOW.sub("과거 시간대", text)
        inspected = _COMPLETED_WINDOW.sub("완료된 사건", inspected)
        label = field in ("title", "channel_drafts.email_subject", "channel_drafts.naver_blog_title")
        if ((label and _PREOPEN_EDITION.search(inspected))
                or _START_INSTRUCTION.search(inspected)
                or _WINDOW_INSTRUCTION.search(inspected)):
            conflicts.append(field)
    return conflicts


_TIME_WINDOW = r"(?:첫\s*30\s*분|장\s*초반|장전|개장\s*전)"
_PAST_WINDOW = re.compile(r"(?:전일|어제|지난\s*거래일|당시)\s*(?:개장\s*후\s*)?" + _TIME_WINDOW)
_COMPLETED_WINDOW = re.compile(
    _TIME_WINDOW + r"\s*(?:에\s*)?(?:발표|공개|집계|관측|확인|확정|발생|기록)(?:된|한|됐|되었)"
)
_PREOPEN_EDITION = re.compile(r"장전|개장\s*전")
_START_INSTRUCTION = re.compile(
    r"장을\s*시작(?:해야|하겠|합시다|하세요|합니다|할\s*준비(?:를)?\s*하세요)"
)
_ADVICE = (
    r"(?:(?:확인|점검|관찰|체크|정리|대비|준비|재정렬)"
    r"(?:해야|하겠|합니다|하세요|합시다|해\s*(?:보세요|봅시다|주세요)|할\s*(?:필요|예정|수))"
    r"|(?:살펴|지켜)(?:봅니다|보세요|봐야|보겠|볼\s*필요))"
)
_WINDOW_INSTRUCTION = re.compile(_TIME_WINDOW + r"[^.!?\n]*" + _ADVICE)

# The known noun/verb splice produced by the retired phrase replacement.
# This is a narrow regression diagnostic, not a general Korean grammar model.
_MALFORMED_FLOW = re.compile(r"수급\s*흐름\s*(?:하는|하기|할|해야|하겠|하며|하면서|하여|하면)")


def known_copy_grammar_conflicts(data: Dict[str, Any]) -> list[str]:
    return [field for field, text in customer_text_values(data) if _MALFORMED_FLOW.search(text)]
