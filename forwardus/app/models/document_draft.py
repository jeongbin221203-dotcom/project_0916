"""이름 붙여 저장해 둔 서류 초안 — Shipment 없이도 남는 한 건.

스케줄을 고르기 전에도, 서류부터 먼저 쓰더라도 사람이 지은 **견적명**과
검토 창에서 고친 서류 값이 그대로 남아야 합니다. 그 자리입니다.

왜 새 표인가
  WorkDraft   회원마다 **한 벌**입니다(user_id UNIQUE). "지금 적고 있는 것"이라
              서류 작성과 운송 계획이 같이 쓰는 칠판입니다. 여러 건을 목록으로
              둘 수 없습니다.
  TradeDocument  shipment_pk가 nullable=False입니다. Shipment 없이는 저장할 수
              없고, 그게 맞습니다. 확정된 건의 서류니까요.
  그래서 "아직 확정은 아니지만 이름 붙여 남겨 둔 것"은 여기에 둡니다.

승격(promotion)
  나중에 스케줄을 골라 Shipment를 만들면 shipment_pk가 채워집니다. 그때부터
  대시보드는 이 줄을 Shipment로 보여 주고, 견적명은 Shipment.project_name으로
  그대로 옮겨 갑니다. (document_draft_service.promote)
"""

from __future__ import annotations

from app.extensions import db, utc_now

MAX_TITLE = 200


class DocumentDraft(db.Model):
    __tablename__ = "document_drafts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)

    # 사람이 지은 이름. 대시보드 목록의 대표 제목입니다.
    # 안 적으면 도착국가_대표품목_날짜로 지어 넣습니다. (processors/document_defaults)
    quote_title = db.Column(db.String(MAX_TITLE), nullable=False, default="")

    # 검토 창에서 고친 서류 값 그대로. [{kind, title, data}, ...]
    # 여기 있는 값이 PDF에 찍힌 것과 같습니다.
    documents = db.Column(db.JSON, nullable=False, default=list)

    # 이 서류들을 만든 초안(칸 값 + 품목). Shipment로 승격할 때 씁니다.
    draft = db.Column(db.JSON, nullable=False, default=dict)

    # 어디서 만들었는지: "chat"(대화) · "upload"(올린 서류) · "document"(서류 작성 화면)
    source = db.Column(db.String(20), nullable=False, default="chat")

    # 승격되면 채워집니다. 비어 있으면 아직 확정 전(Draft)입니다.
    shipment_pk = db.Column(db.Integer, db.ForeignKey("shipments.id"), nullable=True, index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    shipment = db.relationship("Shipment", backref="document_drafts")

    @property
    def is_promoted(self) -> bool:
        return self.shipment_pk is not None

    @property
    def kinds(self) -> list[str]:
        return [str(row.get("kind") or "") for row in (self.documents or [])
                if isinstance(row, dict)]
