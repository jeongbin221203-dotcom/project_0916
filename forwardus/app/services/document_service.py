"""Trade document generation, editing, and cross-document validation."""

from __future__ import annotations

from datetime import date

from app.models.document import DOCUMENT_TYPES, document_role
from app.services import planning_service
from app.processors.document_validator import validate_documents
from app.repositories import document_repository, shipment_repository
from app.services import ServiceError
from app.validators import ValidationError
from app.validators.cargo_validator import PACKAGE_UNITS, priced_by_units
from app.validators.document_validator import clean_document_fields

PREPAID_INCOTERMS = {"CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"}

# Fields each document carries, in display order. 항목 구성은 실무에서 쓰는 표준 서식
# (상업송장·포장명세서 관세청 권장 서식, Proforma Invoice, 선사 Booking Request,
# Shipping Request)의 칸을 그대로 따릅니다.
DOCUMENT_FIELDS = {
    # 상업송장(COMMERCIAL INVOICE) 표준 서식 ①Seller ~ ⑱Signed by
    "commercial_invoice": [
        "exporter", "exporter_address", "consignee", "consignee_address", "etd", "vessel_or_flight",
        "pol", "pod", "carrier", "doc_no", "doc_date", "lc_no", "buyer", "notify_party",
        "other_references", "incoterms", "payment_terms", "shipping_marks", "product_description",
        "hs_code", "quantity", "package_type", "unit_price", "invoice_value", "currency",
        "gross_weight_kg", "net_weight_kg", "remarks", "signed_by",
    ],
    # 포장명세서(PACKING LIST): 사용자가 지정한 주문 서식
    # (ORDER # / SHIPPED TO / 품목표 / Comments / PACKED BY)
    "packing_list": [
        "order_no", "doc_date", "consignee", "consignee_address", "consignee_city_zip",
        "date_ordered", "customer_order_no", "date_shipped", "attention",
        "shipped_via", "container_no", "invoice_no",
        "product_description", "quantity", "package_type",
        "net_weight_kg", "gross_weight_kg", "total_cbm", "comments", "packed_by",
    ],
    "proforma_invoice": [
        "doc_no", "doc_date", "validity_date", "po_no", "exporter", "exporter_address", "consignee",
        "consignee_address", "pol", "pod", "final_destination", "incoterms", "carriage_by",
        "country_of_origin", "shipment_time", "product_description", "hs_code", "quantity", "package_type",
        "unit_price", "invoice_value", "currency", "shipping_marks", "payment_terms", "bank_info", "remarks",
        # 견적송장은 서명이 둘입니다. ㉔ Buyer가 받아들이고 ㉕ Seller가 냅니다.
        "accepted_by", "signed_by",
    ],
    "shipping_instruction": [
        "doc_no", "doc_date", "booking_no", "exporter", "exporter_address", "consignee", "consignee_address",
        "notify_party", "pol", "pod", "carrier", "vessel_or_flight", "etd", "shipping_marks",
        "product_description", "hs_code", "quantity", "package_type", "gross_weight_kg", "total_cbm",
        "container_seal_no", "freight_term", "incoterms", "dangerous_goods", "remarks", "signed_by",
    ],
    "booking_request": [
        "doc_no", "doc_date", "exporter", "exporter_address", "consignee", "consignee_address", "notify_party",
        "notify_party_2", "contact", "service_contract_no", "carrier", "vessel_or_flight", "pol", "etd", "pod",
        "eta", "hs6", "routing_remark", "product_description", "quantity", "package_type", "gross_weight_kg",
        "total_cbm", "equipment", "reefer", "freight_term", "prepaid_at", "collect_at", "confirmation_to", "dangerous_goods",
        "remarks",
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
    # 표준 서식에 있는 칸. Shipment에 없는 값은 비워 두고 서류에서 직접 적습니다.
    "buyer": "Buyer (if other than consignee)",
    "lc_no": "L/C No. and date",
    "other_references": "Other references",
    "payment_terms": "Payment Terms",
    "shipping_marks": "Shipping Marks",
    "signed_by": "Signed by",
    # 견적송장에만 있는 Buyer 쪽 서명란입니다.
    "accepted_by": "Accepted by (Buyer)",
    "validity_date": "Validity date of P/I",
    "po_no": "Buyer's P/O Number",
    "final_destination": "Final destination",
    "carriage_by": "Carriage By",
    "country_of_origin": "Country of Origin",
    "shipment_time": "Shipment (Time of delivery)",
    "bank_info": "Seller's Bank Information",
    "booking_no": "Booking number",
    "container_seal_no": "Container No. / Seal No.",
    "notify_party_2": "2nd Notify Party",
    "contact": "Information Contact",
    "service_contract_no": "Service Contract Number",
    "hs6": "HS6 Code",
    "routing_remark": "Special Remark on Routing",
    "reefer": "Reefer (Temperature / Humidity)",
    "dangerous_goods": "Dangerous Goods (UN No. / Class / PG)",
    "prepaid_at": "Prepaid at",
    "collect_at": "Collect at",
    "confirmation_to": "Booking Confirmation Deliver To",
    # 포장명세서(주문 서식)의 칸
    "order_no": "ORDER #",
    "consignee_city_zip": "CITY, STATE, ZIP",
    "date_ordered": "DATE ORDERED",
    "customer_order_no": "CUSTOMER ORDER NUMBER",
    "date_shipped": "DATE SHIPPED",
    "attention": "ATTENTION",
    "shipped_via": "SHIPPED VIA",
    "container_no": "CONTAINER NUMBER",
    "invoice_no": "OUR INVOICE NUMBER",
    "comments": "Comments",
    "packed_by": "PACKED BY",
}

# 같은 값이라도 서식마다 인쇄된 칸 이름이 다릅니다. 서식에 적힌 이름을 그대로 씁니다.
DOC_FIELD_LABELS = {
    "commercial_invoice": {
        "exporter": "① Seller", "consignee": "② Consignee", "etd": "③ Departure date",
        "vessel_or_flight": "④ Vessel / flight", "pol": "⑤ From", "pod": "⑥ To",
        "doc_no": "⑦ Invoice No.", "doc_date": "⑦ Invoice date", "lc_no": "⑧ L/C No. and date",
        "buyer": "⑨ Buyer (if other than consignee)", "other_references": "⑩ Other references",
        "incoterms": "⑪ Terms of delivery", "payment_terms": "⑪ Terms of payment",
        "signed_by": "⑱ Signed by",
    },
    "packing_list": {
        "consignee": "NAME", "consignee_address": "ADDRESS", "doc_date": "DATE",
        "product_description": "DESCRIPTION (합계)", "quantity": "QUANTITY (합계)",
    },
}


def field_label(doc_type: str, key: str) -> str:
    return DOC_FIELD_LABELS.get(doc_type, {}).get(key) or FIELD_LABELS.get(key, key)

# 품목이 여러 개인 서류는 표로 적습니다. 서식마다 칸 이름이 달라 따로 둡니다.
DOCUMENT_ITEM_FIELDS = {
    "commercial_invoice": [
        ("shipping_marks", "Shipping Marks"), ("packages", "No. & kind of packages"),
        ("description", "Goods description"), ("quantity", "Quantity"),
        ("unit_price", "Unit price"), ("amount", "Amount"),
    ],
    # 첨부 서식의 표 머리글. 품목을 넣은 만큼 줄이 생깁니다.
    "packing_list": [
        ("item_number", "ITEM NUMBER"), ("quantity", "QUANTITY"), ("shipped", "SHIPPED"),
        ("backordered", "BACKORDERED"), ("description", "DESCRIPTION"),
        ("unit_weight", "UNIT WEIGHT"), ("total_weight", "TOTAL WEIGHT"),
    ],
    "proforma_invoice": [
        ("description", "Item"), ("quantity", "Quantity"), ("unit", "UNIT"),
        ("unit_price", "Unit Price"), ("amount", "Amount"),
    ],
    # 선적 서류의 화물 표시란 (Marks and numbers / Description of goods)
    "shipping_instruction": [
        ("shipping_marks", "Marks & numbers"), ("packages", "No. of Pkgs"),
        ("description", "Description of goods"), ("total_weight", "Gross Weight (kg)"),
        ("measurement", "Measurement (CBM)"),
    ],
    "booking_request": [
        ("description", "Description of goods"), ("packages", "Packages"),
        ("total_weight", "Gross Weight (kg)"), ("measurement", "Measurement (CBM)"),
    ],
}

# 서식에 인쇄된 고정 문구
PACKING_LIST_NOTE = ("NOTE: When referring to this shipment be sure to give order # and shipping date. "
                     "품명·수량·포장 수는 상업송장과 일치시켜 주세요.")

# 실제 서식처럼 칸을 묶어 보여줍니다. cols는 그 줄에 나란히 놓을 칸 수이고,
# {"items": True}는 품목 표가 들어갈 자리입니다.
DOCUMENT_SECTIONS = {
    "packing_list": [
        {"cols": 2, "fields": ["order_no", "doc_date"]},
        {"title": "SHIPPED TO", "cols": 1,
         "fields": ["consignee", "consignee_address", "consignee_city_zip"],
         "note": PACKING_LIST_NOTE},
        {"cols": 4, "fields": ["date_ordered", "customer_order_no", "date_shipped", "attention"]},
        {"cols": 3, "fields": ["shipped_via", "container_no", "invoice_no"]},
        {"items": True},
        {"cols": 3, "fields": ["net_weight_kg", "gross_weight_kg", "total_cbm"]},
        {"title": "합계 (송장과 대조되는 값)", "cols": 3,
         "fields": ["product_description", "quantity", "package_type"]},
        {"cols": 2, "fields": ["comments", "packed_by"]},
    ],
    "commercial_invoice": [
        {"cols": 2, "fields": ["exporter", "doc_no",
                               "exporter_address", "doc_date",
                               "consignee", "lc_no",
                               "consignee_address", "buyer",
                               "notify_party", "other_references"]},
        {"cols": 4, "fields": ["etd", "vessel_or_flight", "pol", "pod"]},
        {"cols": 3, "fields": ["carrier", "incoterms", "payment_terms"]},
        {"items": True},
        {"cols": 3, "fields": ["invoice_value", "currency", "unit_price"]},
        {"title": "합계 (송장과 대조되는 값)", "cols": 4,
         "fields": ["product_description", "hs_code", "quantity", "package_type"]},
        {"cols": 3, "fields": ["gross_weight_kg", "net_weight_kg", "shipping_marks"]},
        {"cols": 2, "fields": ["remarks", "signed_by"]},
    ],
    "proforma_invoice": [
        {"cols": 3, "fields": ["doc_no", "doc_date", "validity_date"]},
        {"title": "SELLER / BUYER", "cols": 2,
         "fields": ["exporter", "consignee", "exporter_address", "consignee_address", "po_no"]},
        {"title": "SHIPMENT", "cols": 3,
         "fields": ["pol", "pod", "final_destination", "incoterms", "carriage_by",
                    "country_of_origin", "shipment_time"]},
        {"items": True},
        {"cols": 3, "fields": ["invoice_value", "currency", "unit_price"]},
        {"title": "합계 (송장과 대조되는 값)", "cols": 4,
         "fields": ["product_description", "hs_code", "quantity", "package_type"]},
        {"cols": 2, "fields": ["shipping_marks", "payment_terms"]},
        {"cols": 2, "fields": ["bank_info", "remarks"]},
        {"cols": 1, "fields": ["signed_by"]},
    ],
    # Shipping Request (S/I) 서식: 왼쪽 Shipper·Consignee·Notify, 오른쪽 Booking number·Remarks
    "shipping_instruction": [
        {"cols": 2, "fields": ["exporter", "booking_no",
                               "exporter_address", "doc_no",
                               "consignee", "doc_date",
                               "consignee_address", "remarks",
                               "notify_party", "incoterms"]},
        {"title": "ROUTE", "cols": 4,
         "fields": ["pol", "pod", "vessel_or_flight", "etd", "carrier", "freight_term"]},
        {"items": True},
        {"cols": 3, "fields": ["gross_weight_kg", "total_cbm", "container_seal_no"]},
        {"title": "합계 (송장과 대조되는 값)", "cols": 4,
         "fields": ["product_description", "hs_code", "quantity", "package_type"]},
        {"cols": 2, "fields": ["shipping_marks", "dangerous_goods"]},
        {"cols": 1, "fields": ["signed_by"]},
    ],
    "booking_request": [
        {"cols": 3, "fields": ["doc_no", "doc_date", "service_contract_no"]},
        {"title": "SHIPPER / CONSIGNEE / NOTIFY", "cols": 2,
         "fields": ["exporter", "consignee", "exporter_address", "consignee_address",
                    "notify_party", "notify_party_2", "contact", "confirmation_to"]},
        {"title": "ROUTE", "cols": 4,
         "fields": ["carrier", "vessel_or_flight", "pol", "etd", "pod", "eta",
                    "hs6", "routing_remark"]},
        {"items": True},
        {"title": "합계 (송장과 대조되는 값)", "cols": 3,
         "fields": ["product_description", "quantity", "package_type"]},
        {"cols": 3, "fields": ["gross_weight_kg", "total_cbm", "equipment"]},
        {"cols": 2, "fields": ["reefer", "dangerous_goods"]},
        {"cols": 3, "fields": ["freight_term", "prepaid_at", "collect_at"]},
        {"cols": 1, "fields": ["remarks"]},
    ],
}

# 칸이 넓어야 읽기 좋은 항목 (주소·품명·화인·비고 등)
WIDE_FIELDS = {"product_description", "exporter_address", "consignee_address", "remarks", "shipping_marks",
               "bank_info", "routing_remark", "payment_terms", "container_seal_no", "other_references"}

DOC_PREFIX = {
    "commercial_invoice": "CI",
    "packing_list": "PL",
    "proforma_invoice": "PI",
    "shipping_instruction": "SI",
    "booking_request": "BR",
}


def _port(name: str, code: str) -> str:
    """"Busan (KRPUS)". 아직 항구를 안 정했으면(초안) " ()"가 아니라 빈 값입니다."""

    if not code:
        return ""
    return f"{name} ({code})"


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
    prepaid = shipment.incoterms in PREPAID_INCOTERMS
    hs_digits = "".join(ch for ch in (cargo.hs_code if cargo else "") or "" if ch.isdigit())
    return {
        # 위험물은 선사·항공사에 반드시 신고합니다. 한 건에 여럿이면 모두 적습니다.
        "dangerous_goods": " / ".join(
            " ".join(part for part in [
                item.un_number, f"CLASS {item.dg_class}",
                f"PG {item.packing_group}" if item.packing_group else "",
                item.proper_shipping_name] if part)
            for item in shipment.cargos if item.is_dangerous and item.un_number),
        "exporter": shipment.exporter_name,
        "exporter_address": shipment.exporter_address,
        "consignee": buyer.name if buyer else "",
        "consignee_address": buyer.address if buyer else "",
        "notify_party": shipment.notify_party,
        "incoterms": f"{shipment.incoterms}",
        "pol": _port(shipment.origin_name, shipment.origin_code),
        "pod": _port(shipment.destination_name, shipment.destination_code),
        "carrier": shipment.carrier or "",
        "vessel_or_flight": shipment.vessel_or_flight or "",
        "etd": shipment.etd.isoformat() if shipment.etd else "",
        "eta": shipment.eta.isoformat() if shipment.eta else "",
        "product_description": cargo.product_description if cargo else "",
        "hs_code": cargo.hs_code if cargo else "",
        "quantity": cargo.quantity if cargo else None,
        "package_type": PACKAGE_UNITS.get(cargo.package_type, cargo.package_type) if cargo else "",
        "unit_price": _summary_unit_price(shipment, cargo),
        "invoice_value": shipment.invoice_value,
        "currency": shipment.currency,
        "gross_weight_kg": gross,
        # Net weight is only filled when the user entered it; never invented.
        "net_weight_kg": cargo.net_weight_kg if cargo and cargo.net_weight_kg is not None else "",
        "total_cbm": cargo.total_cbm if cargo else None,
        "freight_term": "FREIGHT PREPAID" if prepaid else "FREIGHT COLLECT",
        "equipment": equipment,
        "remarks": "",
        # 표준 서식 칸 가운데 Shipment에서 바로 채울 수 있는 것
        "country_of_origin": "THE REPUBLIC OF KOREA",
        "carriage_by": "AIR" if shipment.transport_mode == "AIR" else "SEA",
        "final_destination": _port(shipment.destination_name, shipment.destination_code),
        "hs6": f"{hs_digits[:4]}.{hs_digits[4:6]}" if len(hs_digits) >= 6 else "",
        "shipment_time": f"ON OR ABOUT {shipment.etd.isoformat()}" if shipment.etd else "",
        "signed_by": shipment.exporter_name,
        # 운임 선불이면 출발항에서, 후불이면 도착항에서 냅니다.
        "prepaid_at": shipment.origin_name if prepaid else "",
        "collect_at": "" if prepaid else shipment.destination_name,
        # 아래는 거래 조건에 따라 달라 서류에서 직접 적습니다.
        "buyer": "", "lc_no": "", "other_references": "", "payment_terms": "", "shipping_marks": "",
        "validity_date": "", "po_no": "", "bank_info": "", "booking_no": "", "container_seal_no": "",
        "notify_party_2": "", "contact": "", "service_contract_no": "", "routing_remark": "", "reefer": "",
        "confirmation_to": "",
        # 포장명세서(주문 서식)의 칸. 사람이 고쳐 쓸 수 있게 알 수 있는 값만 채웁니다.
        "order_no": shipment.shipment_id,
        "consignee_city_zip": "",
        "date_ordered": "",
        "customer_order_no": "",
        "date_shipped": shipment.etd.isoformat() if shipment.etd else "",
        "attention": buyer.contact_email if buyer else "",
        "shipped_via": " / ".join(part for part in [shipment.carrier, shipment.vessel_or_flight] if part),
        "container_no": "",
        "invoice_no": f"CI-{shipment.shipment_id}",
        "comments": "",
        "packed_by": shipment.exporter_name,
    }


# 단가가 찍히는 서류. 여기서는 낱개 기준으로 값을 매겼으면 그 기준을 그대로 씁니다.
INVOICE_TYPES = ("commercial_invoice", "proforma_invoice")


def packages_text(cargo) -> str:
    """"100 CTN". 포장 개수를 모르면(오퍼시트에 없으면) 빈 값입니다. "None CTN"을 찍지 않습니다."""

    if cargo.quantity is None:
        return ""
    unit = PACKAGE_UNITS.get(cargo.package_type, cargo.package_type)
    return f"{cargo.quantity} {unit}"


def count_text(value) -> str:
    """2000.0 → '2,000', 12.5 → '12.5'. 수량에 쓸데없는 .0을 붙이지 않습니다."""

    number = float(value)
    if number.is_integer():
        return f"{number:,.0f}"
    return f"{number:,.4f}".rstrip("0").rstrip(".")


def _summary_unit_price(shipment, cargo):
    """서류 아래 합계 칸의 단가.

    낱개 기준이면 적힌 단가에 단위를 붙여 씁니다("3.2 / PCS"). 금액을 포장
    개수로 나눈 값(64.0)은 오퍼시트·L/C와 다른 단가라 쓰지 않습니다.
    """

    if not cargo:
        return None
    if priced_by_units(cargo):
        return f"{cargo.unit_price:g} / {cargo.price_unit}" if cargo.unit_price is not None else ""
    return round(shipment.invoice_value / cargo.quantity, 4) if cargo.quantity else None


def build_items(shipment, doc_type: str) -> list[dict]:
    """화물 품목을 그 서류의 표 모양으로 바꿉니다.

    품목이 하나뿐이면 송장 금액을 그 줄에 넣을 수 있지만, 여러 개면 금액을
    어떻게 나눌지 우리가 알 수 없어 비워 둡니다. (지어내지 않습니다)

    단가를 낱개로 매긴 품목이면 송장에는 낱개 수량과 그 단가를 씁니다.
    포장 개수는 포장명세서와 송장의 포장 칸(No. & kind of packages)에만 씁니다.
    """

    columns = DOCUMENT_ITEM_FIELDS.get(doc_type)
    if not columns:
        return []

    cargos = list(shipment.cargos)
    # 품목마다 금액을 적었으면 그 값을 씁니다. 안 적었고 품목이 하나뿐이면
    # 송장 금액이 곧 그 품목의 금액입니다. 여러 개인데 안 적었으면 비워 둡니다.
    single = len(cargos) == 1
    rows = []
    for cargo in cargos:
        if doc_type in INVOICE_TYPES and priced_by_units(cargo):
            rows.append({key: _unit_priced_row(cargo, doc_type).get(key, "") for key, _ in columns})
            continue
        unit = PACKAGE_UNITS.get(cargo.package_type, cargo.package_type)
        dangerous = (f"{cargo.un_number} · {cargo.proper_shipping_name}"
                     if cargo.is_dangerous and cargo.un_number else "")
        row = {
            "item_number": cargo.hs_code or "",
            "shipped": cargo.quantity if cargo.quantity is not None else "",
            "backordered": 0,
            "unit_weight": cargo.weight_per_package_kg,
            "description": " / ".join(part for part in [cargo.product_description, dangerous] if part),
            "quantity": cargo.quantity if cargo.quantity is not None else "",
            # 포장명세서 ⑬칸은 "수량 또는 순중량"입니다. 순중량을 적었으면 그 값을 씁니다.
            "net_quantity": (f"{cargo.net_weight_kg} kg" if cargo.net_weight_kg is not None
                             else packages_text(cargo)),
            "unit": unit,
            "packages": packages_text(cargo),
            "unit_weight": cargo.weight_per_package_kg,
            "total_weight": cargo.total_weight_kg,
            "measurement": cargo.total_cbm,
            "shipping_marks": "",
            "unit_price": (cargo.unit_price if cargo.unit_price is not None
                           else (round(shipment.invoice_value / cargo.quantity, 4)
                                 if single and cargo.quantity else "")),
            "amount": (cargo.amount if cargo.amount is not None
                       else (shipment.invoice_value if single else "")),
        }
        rows.append({key: row.get(key, "") for key, _ in columns})
    return rows


def _unit_priced_row(cargo, doc_type: str) -> dict:
    """낱개 기준 품목의 송장 줄. 오퍼시트에 적힌 그대로 "2,000 PCS × 3.2"입니다.

    단가가 비어 있으면 비워 둡니다. 금액을 수량으로 나눠 채우지 않습니다.
    그 계산이 맞는지는 검증기가 이미 봤고, 맞지 않으면 비워 두었습니다.
    """

    dangerous = (f"{cargo.un_number} · {cargo.proper_shipping_name}"
                 if cargo.is_dangerous and cargo.un_number else "")
    count = count_text(cargo.unit_quantity)
    return {
        "description": " / ".join(part for part in [cargo.product_description, dangerous] if part),
        # 견적송장은 단위 칸이 따로 있고, 상업송장은 수량 칸에 단위까지 적습니다.
        "quantity": count if doc_type == "proforma_invoice" else f"{count} {cargo.price_unit}",
        "unit": cargo.price_unit,
        "unit_price": cargo.unit_price if cargo.unit_price is not None else "",
        "amount": cargo.amount if cargo.amount is not None else "",
        "packages": packages_text(cargo),
        "shipping_marks": "",
    }


def item_columns(doc_type: str) -> list[dict]:
    return [{"key": key, "label": label} for key, label in DOCUMENT_ITEM_FIELDS.get(doc_type, [])]


def _generate_data(shipment, doc_type: str, reference: dict) -> dict:
    data = {field: reference.get(field, "") for field in DOCUMENT_FIELDS[doc_type]}
    if "doc_no" in data:
        data["doc_no"] = f"{DOC_PREFIX[doc_type]}-{shipment.shipment_id}"
    if "doc_date" in data:
        data["doc_date"] = date.today().isoformat()
    items = build_items(shipment, doc_type)
    if items:
        data["items"] = items
    return data


def _require_document_type(doc_type: str) -> None:
    if doc_type not in DOCUMENT_TYPES:
        raise ServiceError("지원하지 않는 문서 유형입니다.", "INVALID_DOCUMENT_TYPE", 404)


def list_documents(shipment) -> list[dict]:
    existing = {doc.doc_type: doc for doc in document_repository.list_for_shipment(shipment)}
    return [{"doc_type": key, "title": title, "document": existing.get(key),
             **document_role(key)}
            for key, title in DOCUMENT_TYPES.items()]


def is_outdated(document) -> bool:
    """서식이 바뀐 뒤에 만들어진 문서인지 봅니다.

    서식에 칸이 더해지거나 빠져도 이미 만들어 둔 문서는 예전 칸을 그대로
    들고 있습니다. 그러면 화면에서 "양식이 안 바뀐" 것처럼 보이므로
    다시 만들 대상으로 잡습니다.
    """

    wanted = set(DOCUMENT_FIELDS.get(document.doc_type, []))
    have = set(document.data) - {"items"}
    if wanted != have:
        return True
    # 품목 표가 생긴 서식인데 표가 없으면 그것도 예전 문서입니다.
    return bool(DOCUMENT_ITEM_FIELDS.get(document.doc_type)) and "items" not in document.data


def generate_documents(shipment, doc_types: list[str] | None = None, *, overwrite: bool = False) -> list:
    """Create documents from Shipment data.

    서식이 바뀐 문서는 새 서식으로 다시 만들되, 사람이 직접 적어 둔 값은
    새 서식에도 있는 칸이면 그대로 살립니다.
    """

    reference = build_reference(shipment)
    generated = []
    for doc_type in doc_types or list(DOCUMENT_TYPES):
        _require_document_type(doc_type)
        existing = document_repository.get(shipment, doc_type)
        stale = existing is not None and is_outdated(existing)
        if existing and not overwrite and not stale:
            continue

        data = _generate_data(shipment, doc_type, reference)
        if existing and stale and not overwrite:
            # 예전 문서에 사람이 적어 둔 값은 새 서식에 남아 있는 칸에만 옮깁니다.
            data.update({key: value for key, value in existing.data.items()
                         if key in data and value not in ("", None)})
        generated.append(document_repository.upsert(
            shipment, doc_type, data, "generated",
            "manual" if existing and existing.source == "manual" else "calculated"))
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

    # 서식 목록에서 빠진 문서(예: 선사가 발행하는 B/L)는 예전 데이터가 남아 있어도
    # 화면에 없으니 검증에서도 뺍니다. 고칠 수 없는 칸을 지적하면 혼란만 줍니다.
    documents = [doc for doc in document_repository.list_for_shipment(shipment)
                 if doc.doc_type in DOCUMENT_TYPES]
    if not documents:
        return None
    return validate_documents(
        {doc.doc_type: doc.data for doc in documents},
        build_reference(shipment),
        DOCUMENT_TYPES,
        DOCUMENT_FIELDS,
    )


def validate_shipment_documents(shipment) -> dict:
    """Validate and update each document's status (validated or back to generated)."""

    result = check_documents(shipment)
    if result is None:
        raise ServiceError("검증할 문서가 없습니다. 먼저 문서를 생성해주세요.", "NO_DOCUMENTS")
    documents = [doc for doc in document_repository.list_for_shipment(shipment)
                 if doc.doc_type in DOCUMENT_TYPES]
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
        {"key": key, "label": field_label(document.doc_type, key), "value": document.data.get(key, ""),
         "wide": key in WIDE_FIELDS}
        for key in DOCUMENT_FIELDS[document.doc_type]
    ]


def document_sections(document) -> list[dict]:
    """서식 모양대로 칸을 묶어 돌려줍니다. 정의가 없으면 한 덩어리로 보여줍니다."""

    values = {field["key"]: field for field in document_view(document)}
    sections = DOCUMENT_SECTIONS.get(document.doc_type)
    if not sections:
        return [{"title": "", "cols": 2, "items": False, "fields": list(values.values())}]

    out = []
    for section in sections:
        if section.get("items"):
            out.append({"title": section.get("title", ""), "cols": 1, "items": True,
                        "fields": [], "note": section.get("note", "")})
            continue
        fields = [values[key] for key in section["fields"] if key in values]
        if fields:
            out.append({"title": section.get("title", ""), "cols": section.get("cols", 2),
                        "items": False, "fields": fields, "note": section.get("note", "")})
    return out


def document_items(document) -> dict:
    """서류의 품목 표. 칸 이름과 줄을 함께 돌려줍니다."""

    columns = item_columns(document.doc_type)
    if not columns:
        return {}
    return {"columns": columns, "rows": document.data.get("items") or [],
            "note": PACKING_LIST_NOTE if document.doc_type == "packing_list" else ""}


def origin_certificate_guide(shipment) -> dict:
    """이 건에 쓸 수 있는 협정과 필요한 원산지증명서를 정리합니다.

    원산지증명서는 협정마다 서식과 발급 주체가 달라 우리가 대신 만들어 줄 수
    없습니다. (기관발급은 세관·상공회의소가 발급하고, 자율발급도 협정문이 정한
    서식을 씁니다.) 그래서 "무엇을 어디서 어떤 서식으로 받아야 하는지"만
    알려줍니다.
    """

    cargo = shipment.cargo
    hs_code = (cargo.hs_code if cargo else "") or ""
    country = shipment.destination_country or ""
    from app.processors import fta_guide
    from app.services import requirement_service

    uploaded = requirement_service.origin_certificates(shipment)
    # 신청 창구와 비특혜 증명서 안내는 협정을 못 찾아도 늘 보여줍니다.
    common = {"uploads": uploaded, "agreement_names": [],
              "apply_links": fta_guide.all_apply_links(),
              "non_preferential": fta_guide.NON_PREFERENTIAL}
    if not hs_code or not country:
        return {**common, "available": False,
                "reason": "HS부호와 도착국이 있어야 적용 협정을 확인할 수 있습니다."}

    guide = planning_service.tariff_guide(hs_code, country)
    if not guide.get("available"):
        return {**common, "available": False, "reason": guide.get("message", ""),
                "country": guide.get("country", country)}

    agreements = [{
        "agreement": row["agreement"],
        "rate": row["rate"],
        "about": row.get("about", ""),
        "certificate": row.get("certificate") or {},
        "steps": row.get("steps") or {},
    } for row in guide["agreements"]]

    return {
        **common,
        "available": True,
        "country": guide["country"],
        "hs_code": guide["hs_code"],
        "agreements": agreements,
        "agreement_names": [row["agreement"] for row in agreements],
        "note": ("원산지증명서는 협정이 정한 서식으로 발급받아야 합니다."
                 " 기관발급은 세관 또는 상공회의소에, 자율발급은 수출자가 직접 작성합니다."),
        "source": "관세청 FTA 포털",
    }
