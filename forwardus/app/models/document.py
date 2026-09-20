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
