"""Buyer (consignee) model."""

from __future__ import annotations

from app.extensions import db, utc_now


class Buyer(db.Model):
    __tablename__ = "buyers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    country = db.Column(db.String(100), nullable=False, default="")
    address = db.Column(db.String(500), nullable=False, default="")
    contact_email = db.Column(db.String(200), nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    shipments = db.relationship("Shipment", back_populates="buyer")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "country": self.country,
            "address": self.address,
            "contact_email": self.contact_email,
        }
