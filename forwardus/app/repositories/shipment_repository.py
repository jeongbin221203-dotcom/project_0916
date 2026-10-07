"""Shipment persistence."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models import Payment, Shipment, ShipmentCost


def get_by_shipment_id(shipment_id: str) -> Shipment | None:
    return Shipment.query.filter_by(shipment_id=shipment_id).first()


def list_shipments(status: str | None = None, user_id: int | None = None) -> list[Shipment]:
    """user_id를 주면 그 회원의 것만, 주지 않으면 전부 돌려줍니다."""

    # buyer·costs·cargos 를 미리 불러옵니다. 목록·통계·CSV 가 건마다 이것들을 읽어, 300건이면 질의가 610번
    # 나갔습니다(관리자 점검 2회차). 왕복이 느린 운영 DB(Render)에서는 건수에 비례해 느려집니다.
    query = Shipment.query.options(joinedload(Shipment.buyer), selectinload(Shipment.costs),
                                   selectinload(Shipment.cargos))
    if user_id is not None:
        query = query.filter_by(user_id=user_id)
    if status:
        query = query.filter_by(status=status)
    return query.order_by(Shipment.created_at.desc()).all()


def next_shipment_id(year: int) -> str:
    """Return the next EXP-YYYY-NNNNN identifier for the given year."""

    prefix = f"EXP-{year}-"
    latest = db.session.query(func.max(Shipment.shipment_id)).filter(Shipment.shipment_id.like(f"{prefix}%")).scalar()
    sequence = int(latest.removeprefix(prefix)) + 1 if latest else 1
    return f"{prefix}{sequence:05d}"


def add_unique(shipment: Shipment, year: int, attempts: int = 5) -> Shipment:
    """저장하되, 번호(shipment_id)가 겹치면 번호를 다시 받아 재시도합니다.

    next_shipment_id 는 max()+1 을 읽고 한참 뒤에 저장하므로, 서로 다른 회원이 동시에 건을 만들면 같은
    번호를 받아 한쪽이 UNIQUE 위반으로 500 을 받았습니다(관리자 점검 2회차, PostgreSQL).
    세이브포인트 안에서 저장하므로 겹쳤을 때 이 건만 되돌아가고, 앞서 저장한 바이어 등은 남습니다.
    """

    from sqlalchemy.exc import IntegrityError

    for attempt in range(attempts):
        try:
            with db.session.begin_nested():
                db.session.add(shipment)
                db.session.flush()
            return shipment
        except IntegrityError:
            if attempt == attempts - 1:
                raise
            shipment.shipment_id = next_shipment_id(year)
    return shipment


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
