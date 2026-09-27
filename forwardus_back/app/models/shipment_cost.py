"""Shipment cost lines and payment schedule."""

from __future__ import annotations

from app.extensions import db


class ShipmentCost(db.Model):
    __tablename__ = "shipment_costs"

    id = db.Column(db.Integer, primary_key=True)
    shipment_pk = db.Column(db.Integer, db.ForeignKey("shipments.id"), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    code = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    original_currency = db.Column(db.String(3), nullable=False)
    original_amount = db.Column(db.Float, nullable=False)
    krw_amount = db.Column(db.Integer, nullable=False)
    source = db.Column(db.String(20), nullable=False)

    shipment = db.relationship("Shipment", back_populates="costs")


class Payment(db.Model):
    """A cash movement for a shipment. Negative amounts are outflows."""

    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    shipment_pk = db.Column(db.Integer, db.ForeignKey("shipments.id"), nullable=False)
    label = db.Column(db.String(100), nullable=False)
    amount_krw = db.Column(db.Integer, nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    source = db.Column(db.String(20), nullable=False, default="manual")

    shipment = db.relationship("Shipment", back_populates="payments")
