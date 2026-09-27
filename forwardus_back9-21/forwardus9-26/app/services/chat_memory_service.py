"""무역 상담의 기억 (Entity) — 대화 전체를 남기고, 오래된 것은 요약해서 들고 다닙니다.

왜 나누는가
  무역 상담(Entity)   "지난번에 말한 그 건"을 알아들어야 합니다. 그래서 주고받은 말을
                      전부 DB에 남기고, 지울 때만 지웁니다.
  운송 계획·서류(State) 필요한 것은 말이 아니라 값입니다. 항구·품목·수량·금액만
                      work_drafts에 남기고 대화 원문은 저장하지 않습니다.

AI에게는 대화를 통째로 보내지 않습니다. 길어지면 토큰이 낭비되고 답이 흐려집니다.
오래된 부분은 한 번 요약해 두고(요약은 DB에 남습니다), 최근 몇 턴만 원문으로 보냅니다.
원문은 지우지 않으므로 나중에 다시 볼 수 있습니다.
"""

from __future__ import annotations

from app.collectors import ai_client
from app.extensions import db
from app.models.chat_memory import ROLES, ChatMessage, ChatThread
from app.processors import bank_redaction

# AI에게 원문으로 보낼 최근 대화 수. (주고받은 말 하나씩 셉니다)
RECENT_TURNS = 8
# 이보다 많이 쌓이면 오래된 것을 요약으로 접습니다.
SUMMARIZE_OVER = 20
# 요약에 한 번에 넣을 최대 메시지 수. 너무 길면 요약 자체가 비쌉니다.
SUMMARIZE_BATCH = 40
MAX_TEXT = 4_000
MAX_SUMMARY = 2_000

SUMMARY_PROMPT = """당신은 무역 상담 기록을 요약하는 사람입니다.
아래는 수출 상담에서 주고받은 말입니다. 다음 상담에서 참고할 수 있게 줄여 주세요.

지켜야 할 것
- 사실만 남깁니다. 없는 말을 만들지 마세요.
- 이 건의 값(출발지·도착지·품목·수량·금액·통화·Incoterms·기한)은 숫자까지 그대로 남깁니다.
- 이미 답해 드린 결론과, 아직 정하지 못한 것을 각각 적습니다.
- 한국어로, 800자 안쪽으로 씁니다.

앞선 요약(있으면 이어서 정리):
{summary}"""


def _thread(user_id: int) -> ChatThread:
    thread = ChatThread.query.filter_by(user_id=user_id).first()
    if thread is None:
        thread = ChatThread(user_id=user_id, summary="", summarized_until_id=0)
        db.session.add(thread)
    return thread


def remember(user, role: str, text: str, source: str = "consult") -> None:
    """주고받은 말을 남깁니다. 로그인하지 않았으면 남기지 않습니다."""

    if user is None or role not in ROLES:
        return
    # 계좌번호는 DB에도 남기지 않습니다. (AI로도 보내지 않는 값입니다)
    clean = bank_redaction.strip_bank_numbers(str(text or "").strip())[0][:MAX_TEXT]
    if not clean:
        return
    db.session.add(ChatMessage(user_id=user.id, role=role, text=clean, source=source))
    _thread(user.id)
    db.session.commit()


def messages(user, limit: int | None = None) -> list[ChatMessage]:
    """남아 있는 대화 전체(또는 최근 limit개). 화면에서 지난 상담을 다시 볼 때 씁니다."""

    if user is None:
        return []
    query = ChatMessage.query.filter_by(user_id=user.id).order_by(ChatMessage.id)
    rows = query.all()
    return rows[-limit:] if limit else rows


def context(user) -> dict:
    """AI에게 넘길 기억. {"summary": 오래된 대화 요약, "history": 최근 대화 원문}"""

    if user is None:
        return {"summary": "", "history": []}
    thread = ChatThread.query.filter_by(user_id=user.id).first()
    recent = messages(user, RECENT_TURNS)
    return {"summary": (thread.summary if thread else "") or "",
            "history": [{"role": row.role, "content": row.text} for row in recent]}


def summarize(user) -> str:
    """오래된 대화를 요약으로 접습니다. 원문은 그대로 둡니다. (요약 글을 돌려줍니다)

    AI 키가 없거나 실패하면 앞선 요약을 그대로 둡니다. 기억이 사라지지는 않습니다.
    """

    if user is None:
        return ""
    rows = messages(user)
    thread = _thread(user.id)
    older = [row for row in rows[:-RECENT_TURNS] if row.id > thread.summarized_until_id]
    if len(rows) <= SUMMARIZE_OVER or not older or not ai_client.available():
        return thread.summary or ""

    older = older[:SUMMARIZE_BATCH]
    lines = "\n".join(f"{'사용자' if row.role == 'user' else '상담'}: {row.text}" for row in older)
    result = ai_client.chat(
        [{"role": "system", "content": SUMMARY_PROMPT.format(summary=thread.summary or "(없음)")},
         {"role": "user", "content": lines}], max_tokens=700)
    if not result["success"]:
        return thread.summary or ""
    thread.summary = str(result["data"]).strip()[:MAX_SUMMARY]
    thread.summarized_until_id = older[-1].id
    db.session.commit()
    return thread.summary


def forget(user) -> None:
    """이 회원의 상담 기억을 모두 지웁니다. ("새 대화"를 눌렀을 때)"""

    if user is None:
        return
    ChatMessage.query.filter_by(user_id=user.id).delete()
    ChatThread.query.filter_by(user_id=user.id).delete()
    db.session.commit()
