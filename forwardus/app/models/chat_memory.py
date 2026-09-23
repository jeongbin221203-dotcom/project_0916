"""무역 상담 대화 기억 (Entity).

상담은 사람이 한 말과 우리가 한 답을 **전부** 남깁니다. 지난주에 하던 이야기를
오늘 이어서 물어도 알아들어야 하기 때문입니다.

  ChatMessage   주고받은 말 한 줄씩. 지우지 않습니다.
  ChatThread    회원마다 하나. 오래된 대화를 줄인 누적 요약과, 어디까지 요약했는지.

운송 계획·서류 작성은 여기 두지 않습니다. 그쪽은 대화 원문이 아니라 "핵심 값"만
work_drafts(State)에 둡니다. (app/services/work_draft_service.py)
"""

from __future__ import annotations

from app.extensions import db, utc_now

ROLES = ("user", "assistant")


class ChatMessage(db.Model):
    __tablename__ = "chat_messages"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)
    text = db.Column(db.Text, nullable=False)
    # 화면이 어디서 물었는지: "consult"(무역 상담) · "support"(고래 상담창)
    source = db.Column(db.String(20), nullable=False, default="consult")
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now, index=True)


class ChatThread(db.Model):
    __tablename__ = "chat_threads"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    # 오래된 대화를 줄여 둔 글. AI에게는 이 요약 + 최근 대화를 함께 보냅니다.
    summary = db.Column(db.Text, nullable=False, default="")
    # 여기까지의 메시지는 요약에 들어가 있습니다. (ChatMessage.id)
    summarized_until_id = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)
