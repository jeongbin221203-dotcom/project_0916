"""이미 만들어 둔 건에서 서류 작성 칸을 채워 옵니다.

같은 바이어에게 두 번째로 보내는 일이 흔합니다. 그때마다 주소·품목·조건을
처음부터 다시 적게 하면 오타가 납니다. 이미 있는 건을 골라 그 값을 가져옵니다.

고를 수 있는 것은 두 가지입니다.

    Shipment        스케줄까지 골라 확정한 건. 지난 건을 본떠 새로 쓸 때.
    DocumentDraft   아직 스케줄을 고르기 전, 이름만 붙여 둔 건. 이어서 쓸 때.

견적명은 둘을 다르게 다룹니다. 초안은 "그 건을 이어 쓰는" 것이라 이름을 그대로
가져오고, Shipment는 "지난 건을 본떠 새로 쓰는" 것이라 이름을 가져오지 않습니다.
같은 이름이 둘이 되면 대시보드에서 어느 것인지 알 수 없습니다.
"""

from __future__ import annotations

from app.services import ServiceError, document_draft_service, shipment_service

# 화면 칸 이름 = Shipment 칸 이름인 것들. (document_start_service.checklist 참고)
_SHIPMENT_FIELDS = (
    "transport_mode", "sea_mode", "origin_code", "origin_name",
    "destination_code", "destination_name", "incoterms", "currency",
    "exporter_name", "exporter_address", "notify_party",
)
# 이름이 다른 것: 화면 칸 ← Buyer 칸
_BUYER_FIELDS = {"buyer_name": "name", "buyer_country": "country",
                 "buyer_address": "address", "buyer_email": "contact_email"}
_ITEM_FIELDS = (
    "product_description", "hs_code", "package_type", "quantity",
    "length_cm", "width_cm", "height_cm", "weight_per_package_kg",
    "net_weight_kg", "unit_price", "amount",
)


def _text(value) -> str:
    """칸에 넣을 글자. 30.0처럼 소수점이 남으면 사람이 다시 지웁니다."""

    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _values(source, names) -> dict:
    return {name: _text(getattr(source, name, "")) for name in names}


def _from_shipment(shipment) -> dict:
    fields = _values(shipment, _SHIPMENT_FIELDS)
    fields["requested_departure_date"] = _text(shipment.requested_departure_date)
    fields["buyer_required_date"] = _text(shipment.buyer_required_date)
    if shipment.buyer:
        fields.update({name: _text(getattr(shipment.buyer, attr, ""))
                       for name, attr in _BUYER_FIELDS.items()})
    items = [_values(cargo, _ITEM_FIELDS) for cargo in shipment.cargos]
    # 견적명은 일부러 빼 둡니다. 화면이 도착지·품목으로 새로 제안합니다.
    return {"fields": {key: value for key, value in fields.items() if value},
            "items": items}


def _from_draft(record) -> dict:
    """초안은 화면 칸 이름 그대로 저장돼 있습니다. 품목만 떼어 냅니다."""

    draft = record.draft if isinstance(record.draft, dict) else {}
    fields = {key: _text(value) for key, value in draft.items()
              if key != "items" and _text(value)}
    # 이어 쓰는 것이므로 이름을 그대로 가져옵니다.
    if record.quote_title:
        fields["project_name"] = record.quote_title
    return {"fields": fields, "items": list(draft.get("items") or [])}


def list_sources(viewer) -> list[dict]:
    """골라서 가져올 수 있는 건. 이어 쓸 초안을 먼저, 지난 건을 뒤에 둡니다."""

    if viewer is None:
        return []
    rows = [{"kind": "draft", "id": str(record.id),
             "title": record.quote_title or "이름 없는 초안",
             "note": f"작성 중 · 서류 {len(record.kinds)}종"}
            for record in document_draft_service.list_open(viewer)]
    rows += [{"kind": "shipment", "id": shipment.shipment_id,
              "title": shipment.project_name,
              "note": f"{shipment.origin_code} → {shipment.destination_code}"}
             for shipment in shipment_service.list_shipments(viewer=viewer)]
    return rows


def load(viewer, kind: str, source_id: str) -> dict:
    """고른 건의 칸 값. 화면은 이것을 FORWARDUS_DOC_FILL에 그대로 넘깁니다."""

    if viewer is None:
        raise ServiceError("로그인이 필요합니다.", "AUTH_REQUIRED", 401)
    if kind == "draft":
        return _from_draft(document_draft_service.get(viewer, source_id))
    if kind == "shipment":
        return _from_shipment(shipment_service.get_or_404(source_id, viewer=viewer))
    raise ServiceError("가져올 수 없는 종류입니다.", "UNKNOWN_SOURCE", 404)
