"""Trade document generation, editing, and cross-document validation."""

from __future__ import annotations

from datetime import date

from app.models.document import DOCUMENT_TYPES
from app.processors.document_validator import validate_documents
from app.repositories import document_repository, shipment_repository
from app.services import ServiceError
from app.validators import ValidationError
from app.validators.cargo_validator import PACKAGE_UNITS
from app.validators.document_validator import clean_document_fields

PREPAID_INCOTERMS = {"CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"}

# Fields each document carries, in display order.
DOCUMENT_FIELDS = {
    "commercial_invoice": [
        "doc_no", "doc_date", "exporter", "exporter_address", "consignee", "consignee_address", "notify_party",
        "incoterms", "pol", "pod", "carrier", "vessel_or_flight", "etd", "product_description", "hs_code",
        "quantity", "package_type", "unit_price", "invoice_value", "currency", "gross_weight_kg", "net_weight_kg",
        "remarks",
    ],
    "packing_list": [
        "doc_no", "doc_date", "exporter", "exporter_address", "consignee", "consignee_address", "notify_party",
        "pol", "pod", "vessel_or_flight", "etd", "product_description", "hs_code", "quantity", "package_type",
        "gross_weight_kg", "net_weight_kg", "total_cbm", "remarks",
    ],
    "proforma_invoice": [
        "doc_no", "doc_date", "exporter", "exporter_address", "consignee", "consignee_address", "incoterms",
        "pol", "pod", "etd", "product_description", "hs_code", "quantity", "package_type", "unit_price",
        "invoice_value", "currency", "remarks",
    ],
    "shipping_instruction": [
        "doc_no", "doc_date", "exporter", "exporter_address", "consignee", "consignee_address", "notify_party",
        "pol", "pod", "carrier", "vessel_or_flight", "etd", "product_description", "hs_code", "quantity",
        "package_type", "gross_weight_kg", "total_cbm", "freight_term", "incoterms", "remarks",
    ],
    "booking_request": [
        "doc_no", "doc_date", "exporter", "pol", "pod", "carrier", "vessel_or_flight", "etd", "eta",
        "product_description", "quantity", "package_type", "gross_weight_kg", "total_cbm", "equipment",
        "freight_term", "remarks",
    ],
    "bl_draft": [
        "doc_no", "exporter", "exporter_address", "consignee", "consignee_address", "notify_party", "pol", "pod",
        "vessel_or_flight", "etd", "product_description", "hs_code", "quantity", "package_type",
        "gross_weight_kg", "total_cbm", "freight_term", "remarks",
    ],
}

FIELD_LABELS = {
    "doc_no": "Document No.",
    "doc_date": "Date",
    "exporter": "Exporter / Shipper",
    "exporter_address": "Exporter Address",
    "consignee": "Consignee",
    "consignee_address": "Consignee Address",
    "notify_party": "Notify Party",
    "incoterms": "Incoterms",
    "pol": "Port of Loading (POL)",
    "pod": "Port of Discharge (POD)",
    "carrier": "Carrier",
    "vessel_or_flight": "Vessel / Flight",
    "etd": "ETD",
    "eta": "ETA",
    "product_description": "Description of Goods",
    "hs_code": "HS CODE",
    "quantity": "Quantity",
    "package_type": "Package",
    "unit_price": "Unit Price",
    "invoice_value": "Invoice Value",
    "currency": "Currency",
    "gross_weight_kg": "Gross Weight (kg)",
    "net_weight_kg": "Net Weight (kg)",
    "total_cbm": "Measurement (CBM)",
    "freight_term": "Freight Term",
    "equipment": "Equipment",
    "remarks": "Remarks",
}

DOC_PREFIX = {
    "commercial_invoice": "CI",
    "packing_list": "PL",
    "proforma_invoice": "PI",
    "shipping_instruction": "SI",
    "booking_request": "BR",
    "bl_draft": "BL",
}


def build_reference(shipment) -> dict:
    """Expected values for every shared field, taken from the Shipment record."""

    cargo = shipment.cargo
    buyer = shipment.buyer
    gross = cargo.total_weight_kg if cargo else None
    equipment = ""
    if shipment.sea_mode == "FCL" and cargo and cargo.container_quantity:
        equipment = f"{cargo.container_quantity} x {cargo.container_type}"
    elif shipment.sea_mode == "LCL":
        equipment = "LCL"
    elif shipment.transport_mode == "AIR":
        equipment = "AIR CARGO"
    return {
        "exporter": shipment.exporter_name,
        "exporter_address": shipment.exporter_address,
        "consignee": buyer.name if buyer else "",
        "consignee_address": buyer.address if buyer else "",
        "notify_party": shipment.notify_party,
        "incoterms": f"{shipment.incoterms}",
        "pol": f"{shipment.origin_name} ({shipment.origin_code})",
        "pod": f"{shipment.destination_name} ({shipment.destination_code})",
        "carrier": shipment.carrier or "",
        "vessel_or_flight": shipment.vessel_or_flight or "",
        "etd": shipment.etd.isoformat() if shipment.etd else "",
        "eta": shipment.eta.isoformat() if shipment.eta else "",
        "product_description": cargo.product_description if cargo else "",
        "hs_code": cargo.hs_code if cargo else "",
        "quantity": cargo.quantity if cargo else None,
        "package_type": PACKAGE_UNITS.get(cargo.package_type, cargo.package_type) if cargo else "",
        "unit_price": round(shipment.invoice_value / cargo.quantity, 4) if cargo and cargo.quantity else None,
        "invoice_value": shipment.invoice_value,
        "currency": shipment.currency,
        "gross_weight_kg": gross,
        # Net weight is only filled when the user entered it; never invented.
        "net_weight_kg": cargo.net_weight_kg if cargo and cargo.net_weight_kg is not None else "",
        "total_cbm": cargo.total_cbm if cargo else None,
        "freight_term": "FREIGHT PREPAID" if shipment.incoterms in PREPAID_INCOTERMS else "FREIGHT COLLECT",
        "equipment": equipment,
        "remarks": "",
    }


def _generate_data(shipment, doc_type: str, reference: dict) -> dict:
    data = {field: reference.get(field, "") for field in DOCUMENT_FIELDS[doc_type]}
    if "doc_no" in data:
        data["doc_no"] = f"{DOC_PREFIX[doc_type]}-{shipment.shipment_id}"
    if "doc_date" in data:
        data["doc_date"] = date.today().isoformat()
    return data


def _require_document_type(doc_type: str) -> None:
    if doc_type not in DOCUMENT_TYPES:
        raise ServiceError("지원하지 않는 문서 유형입니다.", "INVALID_DOCUMENT_TYPE", 404)


def list_documents(shipment) -> list[dict]:
    existing = {doc.doc_type: doc for doc in document_repository.list_for_shipment(shipment)}
    return [{"doc_type": key, "title": title, "document": existing.get(key)} for key, title in DOCUMENT_TYPES.items()]


def generate_documents(shipment, doc_types: list[str] | None = None, *, overwrite: bool = False) -> list:
    """Create documents from Shipment data. Existing edits are kept unless ``overwrite``."""

    reference = build_reference(shipment)
    generated = []
    for doc_type in doc_types or list(DOCUMENT_TYPES):
        _require_document_type(doc_type)
        existing = document_repository.get(shipment, doc_type)
        if existing and not overwrite:
            continue
        generated.append(document_repository.upsert(
            shipment, doc_type, _generate_data(shipment, doc_type, reference), "generated", "calculated"
        ))
    shipment_repository.commit()
    return generated


def get_document(shipment, doc_type: str):
    _require_document_type(doc_type)
    document = document_repository.get(shipment, doc_type)
    if document is None:
        generate_documents(shipment, [doc_type])
        document = document_repository.get(shipment, doc_type)
    return document


def update_document(shipment, doc_type: str, form: dict):
    document = get_document(shipment, doc_type)
    if document.status == "final":
        raise ServiceError("확정(final)된 문서는 수정할 수 없습니다.", "DOCUMENT_FINAL")
    data = clean_document_fields(form, document.data)
    # Edited content must be validated again.
    document_repository.upsert(shipment, doc_type, data, "generated", "manual")
    shipment_repository.commit()
    return document


def check_documents(shipment) -> dict | None:
    """Run the cross-document comparison without changing any status."""

    documents = document_repository.list_for_shipment(shipment)
    if not documents:
        return None
    return validate_documents(
        {doc.doc_type: doc.data for doc in documents},
        build_reference(shipment),
        DOCUMENT_TYPES,
    )


def validate_shipment_documents(shipment) -> dict:
    """Validate and update each document's status (validated or back to generated)."""

    result = check_documents(shipment)
    if result is None:
        raise ServiceError("검증할 문서가 없습니다. 먼저 문서를 생성해주세요.", "NO_DOCUMENTS")
    documents = document_repository.list_for_shipment(shipment)
    flagged = {finding["document"] for finding in result["findings"]}
    for doc in documents:
        if doc.status == "final":
            continue
        doc.status = "generated" if doc.doc_type in flagged else "validated"
    shipment_repository.commit()
    return result


def finalize_document(shipment, doc_type: str):
    document = get_document(shipment, doc_type)
    if document.status != "validated":
        raise ValidationError("문서 검증을 통과한 뒤 확정할 수 있습니다.", "status")
    document.status = "final"
    shipment_repository.commit()
    return document


def document_view(document) -> list[dict]:
    return [
        {"key": key, "label": FIELD_LABELS.get(key, key), "value": document.data.get(key, "")}
        for key in DOCUMENT_FIELDS[document.doc_type]
    ]
