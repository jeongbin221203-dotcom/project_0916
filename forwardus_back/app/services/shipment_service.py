"""Shipment lookup, summary, and status transitions."""

from __future__ import annotations

from collections import OrderedDict

from app.models.document import DOCUMENT_TYPES
from app.processors.schedule_calculator import check_buyer_deadline
from app.repositories import document_repository, shipment_repository, tracking_repository
from app.services import ServiceError

# Allowed manual transitions (tracking events move the in-transit states).
MANUAL_TRANSITIONS = {
    "book": ({"quoted"}, "booked"),
    "close": ({"delivered"}, "closed"),
    "cancel": ({"draft", "quoted", "booked"}, "cancelled"),
}


def get_or_404(shipment_id: str):
    shipment = shipment_repository.get_by_shipment_id(shipment_id)
    if shipment is None:
        raise ServiceError("Shipment를 찾을 수 없습니다.", "SHIPMENT_NOT_FOUND", 404)
    return shipment


def list_shipments(status: str | None = None):
    return shipment_repository.list_shipments(status or None)


def cost_groups(shipment) -> list[dict]:
    groups: "OrderedDict[str, dict]" = OrderedDict()
    for cost in shipment.costs:
        group = groups.setdefault(cost.category, {"category": cost.category, "total_krw": 0, "lines": []})
        group["total_krw"] += cost.krw_amount
        group["lines"].append(cost)
    return list(groups.values())


def build_summary(shipment) -> dict:
    """Everything the Shipment Detail screen shows, gathered in one place."""

    documents = {doc.doc_type: doc for doc in document_repository.list_for_shipment(shipment)}
    events = tracking_repository.list_events(shipment)
    progress_events = [event for event in events if event.event_code != "eta_changed"]
    return {
        "shipment": shipment,
        "cost_groups": cost_groups(shipment),
        "deadline": check_buyer_deadline(shipment.eta, shipment.buyer_required_date, shipment.transport_mode)
        if shipment.eta else None,
        "documents": [
            {"doc_type": doc_type, "title": title, "document": documents.get(doc_type)}
            for doc_type, title in DOCUMENT_TYPES.items()
        ],
        "latest_event": progress_events[-1] if progress_events else None,
        "exceptions": [event for event in events if event.is_exception],
    }


def transition(shipment, action: str):
    if action not in MANUAL_TRANSITIONS:
        raise ServiceError("지원하지 않는 작업입니다.", "INVALID_ACTION")
    allowed_from, target = MANUAL_TRANSITIONS[action]
    if shipment.status not in allowed_from:
        raise ServiceError(f"현재 상태({shipment.status_label})에서는 이 작업을 할 수 없습니다.", "INVALID_TRANSITION")
    shipment.status = target
    shipment_repository.commit()
    return shipment
