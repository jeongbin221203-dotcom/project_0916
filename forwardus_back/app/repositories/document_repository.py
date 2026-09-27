"""Trade document persistence."""

from __future__ import annotations

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
        db.session.add(document)
    document.data = data
    document.status = status
    document.source = source
    return document
