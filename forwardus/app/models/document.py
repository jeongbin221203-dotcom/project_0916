"""Trade document model."""

from __future__ import annotations

from app.extensions import db, utc_now

DOCUMENT_STATUSES = ["draft", "generated", "validated", "final"]

DOCUMENT_TYPES = {
    "commercial_invoice": "Commercial Invoice",
    "packing_list": "Packing List",
    "proforma_invoice": "Proforma Invoice",
    "shipping_instruction": "Shipping Request (S/I)",
    "booking_request": "Booking Request",
}

# 서류마다 수출자가 지는 책임이 다릅니다. 화면에서 이것부터 구분해 보여줍니다.
#   required  수출자가 반드시 직접 작성해서 내는 서류
#   reference 주문 확정 전에 쓰는 참고용 서류
#   sample    선사·포워더가 자기 양식을 주므로 여기서는 예시로만 만드는 서류
DOCUMENT_ROLES = {
    "commercial_invoice": "required",
    "packing_list": "required",
    "proforma_invoice": "reference",
    "shipping_instruction": "sample",
    "booking_request": "sample",
}

DOCUMENT_ROLE_LABELS = {
    "required": "필수",
    "reference": "참고용",
    "sample": "예시 양식",
}

DOCUMENT_ROLE_NOTES = {
    "commercial_invoice": "수출신고와 대금 결제의 기준이 되는 서류입니다. 반드시 직접 작성합니다.",
    "packing_list": "무엇이 몇 개씩 어떻게 포장돼 있는지 적습니다. 반드시 직접 작성합니다.",
    "proforma_invoice": "주문이 확정되기 전에 조건을 확인하려고 주고받는 견적 송장입니다. "
                        "필요할 때만 작성하면 됩니다.",
    "shipping_instruction": "선사·포워더가 자기 양식을 줍니다. 여기 있는 것은 어떤 내용을 "
                            "채워 보내야 하는지 보여 주는 예시입니다.",
    "booking_request": "선사·포워더가 자기 양식을 줍니다. 여기 있는 것은 어떤 내용을 "
                       "채워 보내야 하는지 보여 주는 예시입니다.",
}


def document_role(doc_type: str) -> dict:
    role = DOCUMENT_ROLES.get(doc_type, "reference")
    return {"role": role, "role_label": DOCUMENT_ROLE_LABELS[role],
            "role_note": DOCUMENT_ROLE_NOTES.get(doc_type, "")}


class TradeDocument(db.Model):
    __tablename__ = "trade_documents"
    __table_args__ = (db.UniqueConstraint("shipment_pk", "doc_type"),)

    id = db.Column(db.Integer, primary_key=True)
    shipment_pk = db.Column(db.Integer, db.ForeignKey("shipments.id"), nullable=False)
    doc_type = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="draft")
    data = db.Column(db.JSON, nullable=False, default=dict)
    source = db.Column(db.String(20), nullable=False, default="calculated")
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    shipment = db.relationship("Shipment", back_populates="documents")

    @property
    def title(self) -> str:
        return DOCUMENT_TYPES.get(self.doc_type, self.doc_type)
