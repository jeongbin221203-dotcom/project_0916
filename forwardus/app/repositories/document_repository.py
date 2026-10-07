"""Trade document persistence."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Shipment, TradeDocument


def get(shipment: Shipment, doc_type: str) -> TradeDocument | None:
    return TradeDocument.query.filter_by(shipment_pk=shipment.id, doc_type=doc_type).first()


def list_for_shipment(shipment: Shipment) -> list[TradeDocument]:
    return TradeDocument.query.filter_by(shipment_pk=shipment.id).order_by(TradeDocument.id).all()


def upsert(shipment: Shipment, doc_type: str, data: dict, status: str, source: str) -> TradeDocument:
    document = get(shipment, doc_type)
    if document is None:
        document = TradeDocument(shipment_pk=shipment.id, doc_type=doc_type)
        try:
            # 같은 서류를 두 탭·더블클릭으로 동시에 처음 만들면 UNIQUE(shipment_pk, doc_type) 에서 한쪽이 500 이었습니다
            # (전수 점검 5회차). 겹친 쪽만 세이브포인트로 되돌리고 먼저 만들어진 행을 갱신합니다.
            with db.session.begin_nested():
                db.session.add(document)
                db.session.flush()
        except IntegrityError:
            document = get(shipment, doc_type)
            if document is None:
                raise
    document.data = data
    document.status = status
    document.source = source
    return document
