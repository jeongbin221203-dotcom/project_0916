"""작성 중인 수출 건 — 서류 작성과 운송 계획이 함께 쓰는 초안.

회원마다 한 벌입니다. 서류 작성에서 적은 값이 여기 저장되고, 운송 계획 화면이
열릴 때 이 값으로 칸을 미리 채웁니다. 확정 Shipment가 아니라 "적고 있는 것"입니다.
은행 정보·바이어 주소·연락처는 여기 두지 않습니다. (work_draft_service.SHARED_FIELDS)
"""

from __future__ import annotations

from app.extensions import db, utc_now


class WorkDraft(db.Model):
    __tablename__ = "work_drafts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    data = db.Column(db.JSON, nullable=False, default=dict)
    # 어디서 적었는지: "document"(서류 작성 화면) · "upload"(올린 서류) · "chat"(대화)
    source = db.Column(db.String(20), nullable=False, default="document")
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)
