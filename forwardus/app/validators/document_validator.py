"""Validation for user edits on trade document fields."""

from __future__ import annotations

import re

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
    "buyer", "lc_no", "other_references", "payment_terms", "shipping_marks", "signed_by", "validity_date",
    "po_no", "final_destination", "carriage_by", "country_of_origin", "shipment_time", "bank_info",
    "booking_no", "container_seal_no", "notify_party_2", "contact", "service_contract_no", "hs6",
    "routing_remark", "reefer", "prepaid_at", "collect_at", "confirmation_to",
    "order_no", "consignee_city_zip", "date_ordered", "customer_order_no", "date_shipped",
    "attention", "shipped_via", "container_no", "invoice_no", "comments", "packed_by",
    "dangerous_goods",
]

# 품목 표의 칸은 "item-<줄번호>-<칸이름>" 이름으로 들어옵니다.
ITEM_FIELD_PATTERN = re.compile(r"^item-(\d+)-([a-z_]+)$")


def clean_document_items(form: dict, current: list) -> list:
    """품목 표 수정분을 반영합니다. 줄 수와 칸은 원래 표를 따릅니다."""

    rows = [dict(row) for row in (current or [])]
    for name, value in form.items():
        match = ITEM_FIELD_PATTERN.match(name)
        if not match:
            continue
        index, key = int(match.group(1)), match.group(2)
        if 0 <= index < len(rows) and key in rows[index]:
            rows[index][key] = str(value or "").strip()[:200]
    return rows


def clean_document_fields(form: dict, current: dict) -> dict:
    """Return a copy of ``current`` updated with validated form values."""

    updated = dict(current)
    for key in EDITABLE_FIELDS:
        # 서식에 칸이 새로 생겨 예전에 만든 문서에 없는 항목도 고칠 수 있게 form 기준으로 봅니다.
        if key not in form:
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
    if current.get("items"):
        updated["items"] = clean_document_items(form, current["items"])
    return updated
