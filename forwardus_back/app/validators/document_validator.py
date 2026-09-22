"""Validation for user edits on trade document fields."""

from __future__ import annotations

from app.validators import ValidationError
from app.validators.cargo_validator import parse_number

NUMERIC_FIELDS = {
    "quantity": "Quantity",
    "gross_weight_kg": "Gross Weight",
    "net_weight_kg": "Net Weight",
    "invoice_value": "Invoice Value",
    "unit_price": "Unit Price",
}

EDITABLE_FIELDS = [
    "doc_no",
    "doc_date",
    "freight_term",
    "equipment",
    "exporter",
    "exporter_address",
    "consignee",
    "consignee_address",
    "notify_party",
    "incoterms",
    "pol",
    "pod",
    "product_description",
    "hs_code",
    "quantity",
    "package_type",
    "gross_weight_kg",
    "net_weight_kg",
    "total_cbm",
    "unit_price",
    "invoice_value",
    "currency",
    "carrier",
    "vessel_or_flight",
    "etd",
    "eta",
    "remarks",
]


def clean_document_fields(form: dict, current: dict) -> dict:
    """Return a copy of ``current`` updated with validated form values."""

    updated = dict(current)
    for key in EDITABLE_FIELDS:
        if key not in form or key not in current:
            continue
        raw = form.get(key)
        if key in NUMERIC_FIELDS:
            number = parse_number(raw, NUMERIC_FIELDS[key], allow_zero=True, field=key)
            if key == "quantity":
                if not number.is_integer():
                    raise ValidationError("Quantity에는 정수만 입력할 수 있습니다.", key)
                number = int(number)
            updated[key] = number
        else:
            updated[key] = str(raw or "").strip()[:500]
    return updated
