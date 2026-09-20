"""수출요건 증빙 서류 업로드 기록."""

from __future__ import annotations

from app.extensions import db, utc_now

# AI가 낸 판정. 사람이 다시 볼 수 있게 상태를 따로 둡니다.
REVIEW_STATUSES = {
    "pending": "분석 대기",
    "ok": "적격",
    "check": "확인 필요",
    "mismatch": "이 건과 맞지 않음",
    "failed": "분석 실패",
}


class RequirementDocument(db.Model):
    __tablename__ = "requirement_documents"

    id = db.Column(db.Integer, primary_key=True)
    shipment_pk = db.Column(db.Integer, db.ForeignKey("shipments.id"), nullable=False)

    # export_requirements의 규칙 key (food, strategic, dangerous ...)
    requirement_key = db.Column(db.String(40), nullable=False, default="")
    requirement_title = db.Column(db.String(120), nullable=False, default="")

    filename = db.Column(db.String(300), nullable=False)
    stored_name = db.Column(db.String(300), nullable=False)
    content_type = db.Column(db.String(120), nullable=False, default="")
    size_bytes = db.Column(db.Integer, nullable=False, default=0)

    review_status = db.Column(db.String(20), nullable=False, default="pending")
    review_summary = db.Column(db.Text, nullable=False, default="")
    # AI가 짚은 항목들. [{"label": ..., "verdict": ..., "detail": ...}]
    review_findings = db.Column(db.JSON, nullable=False, default=list)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    uploaded_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    shipment = db.relationship("Shipment", back_populates="requirement_documents")

    @property
    def review_label(self) -> str:
        return REVIEW_STATUSES.get(self.review_status, self.review_status)
