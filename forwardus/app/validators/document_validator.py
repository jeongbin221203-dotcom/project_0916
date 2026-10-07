"""Validation for user edits on trade document fields."""

from __future__ import annotations

import re

from app.processors.cost_calculator import INCOTERMS_INFO
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
    "dangerous_goods",
    "order_no", "consignee_city_zip", "date_ordered", "customer_order_no", "date_shipped",
    "attention", "shipped_via", "container_no", "invoice_no", "comments", "packed_by",
]

_INCOTERM_CODES = {row["code"] for row in INCOTERMS_INFO}
_CURRENCIES = {"USD", "EUR", "JPY", "CNY", "KRW"}
_MAX_QUANTITY = 999_999_999
_REQUIRED_NOT_BLANK = {"exporter": "Shipper / Exporter", "consignee": "Consignee"}


def _check_changed(key: str, new: str, old) -> None:
    """바뀐 칸만 봅니다(전수 점검 1회차). 통화 ZZZ · Incoterms XXX · HS abc · 수출자 빈 칸이 "저장했습니다"로
    받아들여졌습니다. 서식이 만들어 준 값을 사용자가 안 건드렸으면 새 규칙으로 막지 않습니다."""

    if new == str(old if old is not None else "").strip():
        return
    if key in _REQUIRED_NOT_BLANK and not new:
        raise ValidationError(f"{_REQUIRED_NOT_BLANK[key]}는 비울 수 없습니다.", key)
    if not new:
        return
    if key == "currency" and new.upper() not in _CURRENCIES:
        raise ValidationError(f"통화는 {', '.join(sorted(_CURRENCIES))} 중 하나로 적어 주세요. ('{new[:10]}')", key)
    if key == "incoterms":
        match = re.match(r"([A-Za-z]{3})\b", new)
        if not match or match.group(1).upper() not in _INCOTERM_CODES:
            raise ValidationError(f"Incoterms 코드를 알 수 없습니다. ('{new[:20]}') 예: FOB, CIF, DAP", key)
    if key in ("hs_code", "hs6"):
        digits = re.sub(r"[.\-\s]", "", new)
        if not digits.isdigit() or len(digits) not in (4, 6, 10):
            raise ValidationError(f"HS 부호는 숫자 4·6·10자리입니다. ('{new[:20]}')", key)
    if key in ("doc_date", "etd", "eta", "validity_date", "date_ordered", "date_shipped"):
        from app.processors.document_validator import _is_date

        if not _is_date(new):
            raise ValidationError(f"날짜로 읽히지 않습니다. ('{new[:30]}') 2026-10-21 처럼 적어 주세요.", key)


ITEM_NUMERIC = {"quantity": "수량", "unit_price": "단가", "amount": "금액"}

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
            text = str(value or "").strip()[:200]
            if key in ITEM_NUMERIC and text and text != str(rows[index][key]).strip():
                # 바뀐 칸만 — 숫자가 아니거나 음수·nan 이면 "품목 2줄 금액" 처럼 어느 칸인지 알려 줍니다.
                parse_number(text, f"품목 {index + 1}줄의 {ITEM_NUMERIC[key]}", allow_zero=True, field=name)
            rows[index][key] = text
    return rows


def _check_weights(updated: dict, current) -> None:
    """총중량이 순중량보다 작을 수 없습니다 — 둘 중 하나라도 이번에 바꿨을 때만."""

    current = current if isinstance(current, dict) else {}
    gross, net = updated.get("gross_weight_kg"), updated.get("net_weight_kg")
    if not isinstance(gross, (int, float)) or not isinstance(net, (int, float)):
        return
    if (gross, net) != (current.get("gross_weight_kg"), current.get("net_weight_kg")) and 0 < gross < net:
        raise ValidationError("총중량(Gross Weight)이 순중량(Net Weight)보다 작을 수 없습니다.", "gross_weight_kg")


OPTIONAL_NUMERIC = {"net_weight_kg"}


def clean_document_fields(form: dict, current: dict) -> dict:
    """Return a copy of ``current`` updated with validated form values."""

    if not isinstance(form, dict):
        form = {}
    updated = dict(current if isinstance(current, dict) else {})
    for key in EDITABLE_FIELDS:
        # 서식에 칸이 새로 생겨 예전에 만든 문서에 없는 항목도 고칠 수 있게 form 기준으로 봅니다.
        if key not in form:
            continue
        raw = form.get(key)
        if key in OPTIONAL_NUMERIC and (raw is None or (isinstance(raw, str) and not raw.strip())):
            # 계획 화면이 "(선택)"이라고 한 칸은 비워 둔 채로도 저장됩니다. 예전에는 다른 칸만 고쳐도
            # "Net Weight 값을 입력해주세요"로 막히고 고친 내용이 모두 사라졌습니다(전수 점검 4회차).
            updated[key] = ""
            continue
        if key in NUMERIC_FIELDS:
            number = parse_number(raw, NUMERIC_FIELDS[key], allow_zero=True, field=key)
            if key == "quantity":
                if not number.is_integer():
                    raise ValidationError("Quantity에는 정수만 입력할 수 있습니다.", key)
                if number > _MAX_QUANTITY:
                    raise ValidationError(f"Quantity는 {_MAX_QUANTITY:,} 이하로 적어 주세요.", key)
                number = int(number)
            updated[key] = number
        else:
            text = str(raw or "").strip()[:500]
            _check_changed(key, text, (current or {}).get(key) if isinstance(current, dict) else "")
            updated[key] = text.upper() if key == "currency" and text else text
    _check_weights(updated, current)
    if isinstance(current, dict) and current.get("items"):
        updated["items"] = clean_document_items(form, current["items"])
    return updated
