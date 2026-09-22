"""시작 화면에서 서류까지 한 번에.

상업송장과 포장명세서가 요구하는 칸을 묶음별로 보여 주고, 사람이 채우면
Shipment를 만들고 서류까지 냅니다.

이 자리를 따로 둔 이유가 있습니다. 서류에 `—`로 비어 나오는 칸들(L/C번호,
결제조건, 화인, 주문번호 같은 것)은 지금까지 아무 데서도 묻지 않았습니다.
묻지 않으니 채워질 리가 없고, 그대로 세관과 Buyer에게 나갔습니다.
여기서는 서식이 요구하는 것을 **전부 보여 주고** 비면 비었다고 말합니다.

금액은 특히 엄하게 봅니다. 품목 금액을 일부만 적으면 송장 줄의 합과 총액이
어긋납니다. 실제로 품목 두 줄 중 하나만 적어서 총액 3,000인데 한 줄이 5,000인
송장이 나온 적이 있습니다. 그런 서류는 세관에 낼 수 없습니다.
"""

from __future__ import annotations

from app.collectors import exchange_client
from app.processors.cost_calculator import INCOTERMS_INFO
from app.services import ServiceError, document_service, planning_service
from app.validators import ValidationError
from app.validators.cargo_validator import PACKAGE_TYPE_INFO, parse_number

MAX_ITEMS = 20

# 서류에만 쓰는 칸. Shipment에는 자리가 없어 만든 뒤 서류에 직접 넣습니다.
# 어느 서식의 어느 칸인지 적어 둡니다. 나중에 서식이 바뀌면 여기를 봅니다.
INVOICE_EXTRAS = ("buyer", "lc_no", "other_references", "payment_terms",
                  "shipping_marks", "remarks")
PACKING_EXTRAS = ("consignee_city_zip", "attention", "customer_order_no",
                  "date_ordered", "container_no", "comments")


def _options() -> dict:
    return {
        "incoterms": [{"value": row["code"], "label": f"{row['code']} · {row['label']}"}
                      for row in INCOTERMS_INFO],
        "currency": [{"value": row["code"], "label": f"{row['code']} · {row['name']}"}
                     for row in exchange_client.currency_options()],
        "package_type": [{"value": key, "label": info["label"]}
                         for key, info in PACKAGE_TYPE_INFO.items()],
    }


def checklist() -> dict:
    """서류에 필요한 것을 묶음별로. 화면은 이 목록 그대로 그립니다.

    칸 목록을 화면이 아니라 여기에 두는 이유는, 서식이 바뀌었을 때
    고칠 자리를 하나로 묶어 두기 위해서입니다.
    """

    options = _options()
    groups = [
        {"key": "when", "tab": "when", "label": "언제 보내나", "icon": "🗓",
         "note": "보내는 날이 상업송장의 출항일과 포장명세서의 DATE SHIPPED가 됩니다.",
         "fields": [
             {"name": "requested_departure_date", "label": "Seller 발송 예상일",
              "kind": "date", "required": True,
              "hint": "이 날에 맞춰 스케줄을 찾습니다"},
             {"name": "buyer_required_date", "label": "Buyer 요청 도착일", "kind": "date",
              "hint": "납기에 맞는지 함께 봅니다. 비워도 됩니다"},
         ]},
        {"key": "route", "tab": "plan", "label": "어디서 어디로", "icon": "🚢",
         "note": "상업송장 FROM/TO와 선박명이 여기서 정해집니다.",
         "fields": [
             {"name": "transport_mode", "label": "운송 모드", "kind": "choice", "required": True,
              "options": [{"value": "SEA", "label": "🚢 해상"}, {"value": "AIR", "label": "✈️ 항공"}]},
             {"name": "sea_mode", "label": "해상 운송 방식", "kind": "choice",
              "options": [{"value": "FCL", "label": "FCL"}, {"value": "LCL", "label": "LCL"}],
              "sea_only": True},
             {"name": "origin_code", "label": "출발지", "kind": "place", "role": "origin",
              "required": True, "placeholder": "부산, KRPUS…"},
             {"name": "destination_code", "label": "도착지", "kind": "place", "role": "destination",
              "required": True, "placeholder": "Los Angeles, USLAX…"},
         ]},
        {"key": "exporter", "tab": "doc", "label": "보내는 쪽", "icon": "🏢",
         "note": "상업송장 ①Seller와 포장명세서 PACKED BY에 들어갑니다.",
         "fields": [
             {"name": "exporter_name", "label": "수출자명", "required": True,
              "placeholder": "Forward Cosmetics Co., Ltd."},
             {"name": "exporter_address", "label": "수출자 주소", "wide": True,
              "placeholder": "Seoul, Korea"},
         ]},
        {"key": "buyer", "tab": "doc", "label": "받는 쪽", "icon": "📮",
         "note": "상업송장 ④Consignee와 포장명세서 SHIPPED TO에 들어갑니다.",
         "fields": [
             {"name": "buyer_name", "label": "Buyer(Consignee)명", "required": True,
              "placeholder": "ABC Beauty Inc."},
             {"name": "buyer_country", "label": "Buyer 국가", "placeholder": "US",
              "hint": "두 글자 국가 코드"},
             {"name": "buyer_address", "label": "Buyer 주소", "wide": True,
              "placeholder": "Los Angeles, CA"},
             {"name": "consignee_city_zip", "label": "도시 · 주 · 우편번호",
              "placeholder": "Los Angeles, CA 90001"},
             {"name": "buyer_email", "label": "Buyer 이메일", "placeholder": "a@b.com"},
             {"name": "attention", "label": "담당자 (ATTENTION)", "placeholder": "Mr. Kim"},
         ]},
        {"key": "terms", "tab": "doc", "label": "거래 · 결제 조건", "icon": "📝",
         "note": "비워 두면 상업송장의 TERMS OF PAYMENT와 L/C 칸이 —로 남습니다.",
         "fields": [
             {"name": "incoterms", "label": "Incoterms", "kind": "select", "required": True,
              "options": options["incoterms"]},
             {"name": "currency", "label": "통화", "kind": "select", "value": "USD",
              "options": options["currency"]},
             {"name": "payment_terms", "label": "결제 조건",
              "placeholder": "T/T 30 days after B/L date"},
             {"name": "lc_no", "label": "L/C 번호와 날짜", "placeholder": "비워도 됩니다"},
             {"name": "buyer", "label": "Buyer (Consignee와 다를 때)",
              "placeholder": "같으면 비워 두세요"},
             {"name": "other_references", "label": "기타 참조", "wide": True},
         ]},
        {"key": "extras", "tab": "doc", "label": "서류에만 쓰는 칸", "icon": "🏷",
         "note": "Shipment에는 자리가 없고 서류에만 들어갑니다. 비우면 —로 남습니다.",
         "fields": [
             {"name": "shipping_marks", "label": "화인 (Shipping Marks)", "wide": True,
              "placeholder": "ABC / LA / C-NO 1-20 / MADE IN KOREA"},
             {"name": "customer_order_no", "label": "Buyer 주문번호"},
             {"name": "date_ordered", "label": "주문일", "kind": "date"},
             {"name": "container_no", "label": "컨테이너 번호", "placeholder": "TEMU1234567"},
             {"name": "remarks", "label": "비고 (송장)", "wide": True},
             {"name": "comments", "label": "비고 (포장명세서)", "wide": True},
         ]},
    ]
    return {"groups": groups, "item_fields": _item_fields(options),
            "required_count": _required_count(groups)}


def _item_fields(options: dict) -> list[dict]:
    """품목 한 줄이 요구하는 칸. 송장 줄과 포장명세서 줄이 여기서 나옵니다."""

    return [
        {"name": "product_description", "label": "품명", "required": True, "wide": True,
         "placeholder": "Shampoo 500ml"},
        {"name": "hs_code", "label": "HS부호", "placeholder": "3305100000"},
        {"name": "package_type", "label": "포장", "kind": "select", "required": True,
         "options": options["package_type"]},
        {"name": "quantity", "label": "포장 개수", "kind": "number", "required": True},
        {"name": "length_cm", "label": "가로(cm)", "kind": "number", "required": True},
        {"name": "width_cm", "label": "세로(cm)", "kind": "number", "required": True},
        {"name": "height_cm", "label": "높이(cm)", "kind": "number", "required": True},
        {"name": "weight_per_package_kg", "label": "한 포장 무게(kg)", "kind": "number",
         "required": True},
        {"name": "net_weight_kg", "label": "순중량(kg)", "kind": "number"},
        {"name": "unit_price", "label": "단가", "kind": "number"},
        {"name": "amount", "label": "금액", "kind": "number", "required": True,
         "hint": "품목마다 적으면 합계가 송장 금액이 됩니다"},
    ]


def _required_count(groups: list[dict]) -> int:
    return sum(1 for group in groups for field in group["fields"] if field.get("required"))


# --- 만들기 ----------------------------------------------------------------------

def _text(payload: dict, key: str, limit: int = 300) -> str:
    return str(payload.get(key) or "").strip()[:limit]


def _invoice_value(items: list[dict]) -> float:
    """품목 금액의 합. 일부만 적으면 거절합니다.

    일부만 적으면 송장 줄의 합과 총액이 어긋난 서류가 나옵니다.
    그런 서류는 세관에서 되돌아옵니다.
    """

    amounts = []
    missing = []
    for number, item in enumerate(items, start=1):
        raw = item.get("amount")
        if raw in (None, ""):
            missing.append(number)
            continue
        amounts.append(parse_number(raw, f"품목 {number} 금액", field="amount"))

    if missing and amounts:
        adrift = ", ".join(str(number) for number in missing)
        raise ValidationError(
            f"품목 {len(items)}개 중 {adrift}번 금액이 비었습니다. "
            "일부만 적으면 송장 줄의 합과 총액이 어긋납니다. 전부 적어 주세요.",
            "amount")
    if not amounts:
        raise ValidationError("품목 금액을 적어 주세요. 송장 금액이 됩니다.", "amount")
    return round(sum(amounts), 2)


def create(payload: dict, user_id: int | None = None) -> dict:
    """채운 내용으로 Shipment를 만들고 서류까지 냅니다."""

    if not isinstance(payload, dict):
        raise ValidationError("입력을 읽지 못했습니다.", "payload")

    items = payload.get("items")
    items = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    if not items:
        raise ValidationError("품목을 하나 이상 적어 주세요.", "items")
    if len(items) > MAX_ITEMS:
        raise ValidationError(f"품목은 {MAX_ITEMS}개까지 넣을 수 있습니다.", "items")

    buyer_name = _text(payload, "buyer_name", 200)
    project_name = _text(payload, "project_name", 200) or _project_name(payload, items)

    plan = {
        "project_name": project_name,
        "transport_mode": _text(payload, "transport_mode", 10).upper() or "SEA",
        "sea_mode": _text(payload, "sea_mode", 10).upper(),
        "origin_code": _text(payload, "origin_code", 10).upper(),
        "destination_code": _text(payload, "destination_code", 10).upper(),
        "requested_departure_date": _text(payload, "requested_departure_date", 20),
        "buyer_required_date": _text(payload, "buyer_required_date", 20),
        "incoterms": _text(payload, "incoterms", 3).upper(),
        "incoterms_confirmed": payload.get("incoterms_confirmed"),
        "currency": _text(payload, "currency", 3).upper() or "USD",
        "invoice_value": _invoice_value(items),
        "cargo": {"items": items},
        "exporter_name": _text(payload, "exporter_name", 200),
        "exporter_address": _text(payload, "exporter_address", 500),
        "notify_party": _text(payload, "notify_party", 300),
        "buyer": {"name": buyer_name,
                  "country": _text(payload, "buyer_country", 2).upper(),
                  "address": _text(payload, "buyer_address", 500),
                  "contact_email": _text(payload, "buyer_email", 200)},
        "schedule_id": _text(payload, "schedule_id", 80),
    }

    shipment = planning_service.create_shipment(plan, user_id=user_id)
    document_service.generate_documents(shipment)
    _apply_extras(shipment, payload)

    return {"shipment_id": shipment.shipment_id,
            "project_name": shipment.project_name,
            "etd": shipment.etd.isoformat() if shipment.etd else "",
            "eta": shipment.eta.isoformat() if shipment.eta else "",
            "carrier": shipment.carrier or "",
            "invoice_value": shipment.invoice_value,
            "currency": shipment.currency,
            "still_empty": _still_empty(shipment)}


def _project_name(payload: dict, items: list[dict]) -> str:
    """견적명을 따로 묻지 않습니다. 도착지와 첫 품명으로 지어 둡니다."""

    where = _text(payload, "destination_code", 10).upper()
    what = str(items[0].get("product_description") or "").strip()
    return " ".join(part for part in (where, what) if part)[:200] or "수출 건"


def _apply_extras(shipment, payload: dict) -> None:
    """Shipment에 자리가 없는 칸을 서류에 직접 넣습니다."""

    for doc_type, keys in (("commercial_invoice", INVOICE_EXTRAS),
                           ("packing_list", PACKING_EXTRAS)):
        form = {key: _text(payload, key, 500) for key in keys if _text(payload, key, 500)}
        if form:
            document_service.update_document(shipment, doc_type, form)


def _still_empty(shipment) -> list[dict]:
    """만들고 나서도 —로 남은 칸. 숨기지 않고 그대로 알려 줍니다."""

    empty = []
    for doc_type, label in (("commercial_invoice", "상업송장"), ("packing_list", "포장명세서")):
        try:
            document = document_service.get_document(shipment, doc_type)
        except ServiceError:
            continue
        for field in document_service.DOCUMENT_FIELDS[doc_type]:
            if str(document.data.get(field) or "").strip():
                continue
            empty.append({"doc": label, "field": field,
                          "label": document_service.field_label(doc_type, field)})
    return empty
