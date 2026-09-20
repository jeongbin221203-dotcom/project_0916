"""Shipment persistence."""

from __future__ import annotations

from sqlalchemy import func

from app.extensions import db
from app.models import Payment, Shipment, ShipmentCost


def get_by_shipment_id(shipment_id: str) -> Shipment | None:
    return Shipment.query.filter_by(shipment_id=shipment_id).first()


def list_shipments(status: str | None = None) -> list[Shipment]:
    query = Shipment.query
    if status:
        query = query.filter_by(status=status)
    return query.order_by(Shipment.created_at.desc()).all()


def next_shipment_id(year: int) -> str:
    """Return the next EXP-YYYY-NNNNN identifier for the given year."""

    prefix = f"EXP-{year}-"
    latest = db.session.query(func.max(Shipment.shipment_id)).filter(Shipment.shipment_id.like(f"{prefix}%")).scalar()
    sequence = int(latest.removeprefix(prefix)) + 1 if latest else 1
    return f"{prefix}{sequence:05d}"


def add(shipment: Shipment) -> Shipment:
    db.session.add(shipment)
    db.session.flush()
    return shipment


def replace_costs(shipment: Shipment, lines: list[dict]) -> None:
    shipment.costs.clear()
    for line in lines:
        shipment.costs.append(ShipmentCost(
            category=line["category"],
            code=line["code"],
            name=line["name"],
            original_currency=line["original_currency"],
            original_amount=line["original_amount"],
            krw_amount=line["krw_amount"],
            source=line["source"],
        ))


def add_payment(shipment: Shipment, **fields) -> Payment:
    payment = Payment(**fields)
    shipment.payments.append(payment)
    return payment


def delete_payment(shipment: Shipment, payment_id: int) -> bool:
    for payment in shipment.payments:
        if payment.id == payment_id:
            db.session.delete(payment)
            return True
    return False


def delete(record) -> None:
    """어떤 레코드든 지웁니다. (업로드한 증빙 서류 등)"""

    db.session.delete(record)


def commit() -> None:
    db.session.commit()
