"""저장하지 않고 서류 초안을 만듭니다.

대화로 받은 내용만으로 상업송장·포장명세서·견적송장을 그려 보여 줍니다.
**선박도 스케줄도 없어도 됩니다.** 아직 안 정해진 칸은 비워 두지 않고
"미정"이라고 적어, 무엇이 남았는지 사람이 바로 알게 합니다.

서식을 그리는 코드는 새로 쓰지 않았습니다. `document_service.build_reference()`와
`build_items()`는 DB를 전혀 건드리지 않고 `shipment.etd` 처럼 속성만 읽습니다.
그래서 같은 모양의 임시 객체를 만들어 넘기면 기존 코드가 그대로 돕니다.

저장은 하지 않습니다. `TradeDocument.shipment_pk`가 `nullable=False`라
Shipment 없이는 저장할 수 없고, 그게 맞습니다. 초안은 아직 확정이 아닙니다.
확정은 운송 계획에서 스케줄을 고른 뒤 `document_start_service.create()`가 합니다.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.collectors import location_client
from app.processors.cargo_calculator import calculate_cargo_lines
from app.services import ServiceError, document_service
from app.validators import ValidationError
from app.validators.cargo_validator import has_box, validate_commercial_line

# 스케줄이 있어야 채워지는 칸. 빈칸으로 두면 "안 적었나" 싶고,
# 지어내면 거짓말이 됩니다. 그래서 미정이라고 적습니다.
UNDECIDED = "미정 (운송 계획에서 정해집니다)"

SCHEDULE_FIELDS = {
    "commercial_invoice": ("etd", "vessel_or_flight", "carrier"),
    "packing_list": ("date_shipped", "shipped_via"),
    "packing_list_std": ("etd", "vessel_or_flight"),
    "proforma_invoice": ("shipment_time",),
}

# 초안으로 그릴 수 있는 서식.
#
# packing_list_std(표준 포장명세서 ①~⑯)는 초안에서만 씁니다.
# document_service.DOCUMENT_TYPES에 넣으면 Shipment를 만들 때마다 여섯 장이
# 생겨 버려서, 고를 수 있는 서식으로만 두었습니다.
FORMS = {
    "commercial_invoice": "상업송장 (Commercial Invoice)",
    "packing_list": "포장명세서 (ORDER # 양식)",
    "packing_list_std": "포장명세서 (표준 ①~⑯ 양식)",
    "proforma_invoice": "견적송장 (Proforma Invoice)",
}

# 표준 포장명세서는 상업송장과 같은 칸을 쓰되 순서와 이름이 서식대로입니다.
STD_PACKING_FIELDS = [
    "exporter", "exporter_address",        # ① Seller
    "consignee", "consignee_address",      # ② Consignee
    "etd",                                 # ③ Departure date
    "vessel_or_flight",                    # ④ Vessel/flight
    "pol",                                 # ⑤ From
    "pod",                                 # ⑥ To
    "invoice_no", "doc_date",              # ⑦ Invoice No. and date
    "buyer",                               # ⑧ Buyer (if other than consignee)
    "other_references",                    # ⑨ Other references
    "signed_by",                           # ⑯ Signed by
]

# ⑩~⑮ 품목 표
STD_PACKING_ITEMS = [
    ("shipping_marks", "⑩ Shipping Marks"),
    ("packages", "⑪ No.&kind of packages"),
    ("description", "⑫ Goods description"),
    ("net_weight", "⑬ Quantity or net weight"),
    ("total_weight", "⑭ Gross Weight"),
    ("measurement", "⑮ Measurement"),
]


def fields_for(kind: str) -> list[str]:
    """이 서식이 쓰는 칸 이름."""

    if kind == "packing_list_std":
        return list(STD_PACKING_FIELDS)
    return list(document_service.DOCUMENT_FIELDS[kind])


def item_columns(kind: str) -> list[dict]:
    """이 서식의 품목 표 머리글."""

    rows = (STD_PACKING_ITEMS if kind == "packing_list_std"
            else document_service.DOCUMENT_ITEM_FIELDS[kind])
    return [{"key": key, "label": label} for key, label in rows]


def _require_form(kind: str) -> None:
    if kind not in FORMS:
        raise ServiceError(f"그런 서식은 없습니다: {kind}", "UNKNOWN_FORM", 404)


# --- 임시 Shipment ----------------------------------------------------------------

def _place(code: str, fallback: str = "") -> tuple[str, str]:
    """항구·공항 코드를 이름으로. 못 찾으면 코드를 그대로 씁니다."""

    code = str(code or "").strip().upper()
    if not code:
        return "", fallback
    found = location_client.find_location(code)
    return code, (found["name_en"] if found else code)


def _as_shipment(draft: dict) -> SimpleNamespace:
    """build_reference가 읽는 모양의 임시 객체.

    DB에 넣지 않습니다. 속성 이름만 Shipment와 같으면 됩니다.
    """

    items = draft.get("items") or []
    if not isinstance(items, list) or not items:
        raise ValidationError("품목을 하나 이상 적어 주세요.", "items")

    # 부피·중량·컨테이너 수는 우리 계산기가 냅니다. 화면이 보낸 값을 믿지 않습니다.
    # 상자 크기가 없는 품목(오퍼시트로 만든 초안)은 송장에 필요한 것만 확인하고
    # 부피·중량은 비워 둡니다. 크기를 지어내 넣지 않습니다.
    lines = [_line(raw) for raw in items]

    cargos = []
    for raw, line in zip(items, lines):
        cargos.append(SimpleNamespace(
            # 계산기가 hs_code는 돌려주지 않아 입력에서 그대로 가져옵니다.
            hs_code=str(raw.get("hs_code") or "").strip(),
            **{key: line.get(key) for key in (
                "product_description", "package_type", "quantity",
                "length_cm", "width_cm", "height_cm", "weight_per_package_kg",
                "net_weight_kg", "unit_price", "amount",
                "unit_quantity", "price_unit", "units_per_package",
                "total_cbm", "total_weight_kg", "container_type", "container_quantity",
                "is_dangerous", "un_number", "dg_class", "packing_group",
                "proper_shipping_name")}))

    origin_code, origin_name = _place(draft.get("origin_code"))
    dest_code, dest_name = _place(draft.get("destination_code"))

    # 품목 금액을 모두 적었으면 그 합이 송장 금액입니다.
    amounts = [line.get("amount") for line in lines]
    invoice_value = (round(sum(amounts), 2) if amounts and all(a is not None for a in amounts)
                     else None)
    if invoice_value is None:
        invoice_value = _number(draft.get("invoice_value"))

    stand_in = SimpleNamespace(
        # 초안에는 아직 번호가 없습니다. 서식에 "DRAFT"라고 찍힙니다.
        shipment_id=str(draft.get("shipment_id") or "DRAFT"),
        project_name=str(draft.get("project_name") or ""),
        transport_mode=str(draft.get("transport_mode") or "SEA").upper(),
        sea_mode=str(draft.get("sea_mode") or "").upper() or None,
        origin_code=origin_code, origin_name=origin_name,
        destination_code=dest_code, destination_name=dest_name,
        incoterms=str(draft.get("incoterms") or "").upper(),
        currency=str(draft.get("currency") or "USD").upper(),
        invoice_value=invoice_value,
        exporter_name=str(draft.get("exporter_name") or ""),
        exporter_address=str(draft.get("exporter_address") or ""),
        notify_party=str(draft.get("notify_party") or ""),
        # 아직 스케줄이 없습니다. build_reference가 전부 `or ""`로 받아 줍니다.
        carrier=draft.get("carrier") or None,
        vessel_or_flight=draft.get("vessel_or_flight") or None,
        etd=_as_date(draft.get("etd")),
        eta=_as_date(draft.get("eta")),
        buyer=SimpleNamespace(
            name=str(draft.get("buyer_name") or ""),
            address=str(draft.get("buyer_address") or ""),
            contact_email=str(draft.get("buyer_email") or "")),
        cargos=cargos,
    )
    # Shipment.cargo는 cargos[0]을 주는 속성입니다. 임시 객체에는 그냥 붙입니다.
    stand_in.cargo = cargos[0]
    return stand_in


def _line(item: dict) -> dict:
    """품목 한 줄. 상자 크기가 있으면 부피·중량까지, 없으면 송장 칸만."""

    if has_box(item):
        return calculate_cargo_lines([item], strict=False)["lines"][0]
    line = validate_commercial_line(item)
    line["product_description"] = str(item.get("product_description") or "").strip()[:300]
    for key in ("length_cm", "width_cm", "height_cm", "weight_per_package_kg", "net_weight_kg",
                "total_cbm", "total_weight_kg", "container_type", "container_quantity"):
        line.setdefault(key, None)
    return line


def _number(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _as_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


# --- 그리기 -----------------------------------------------------------------------

def render(kind: str, draft: dict) -> dict:
    """서류 한 장의 내용. 저장하지 않습니다."""

    _require_form(kind)
    if not isinstance(draft, dict):
        raise ValidationError("입력을 읽지 못했습니다.", "draft")

    stand_in = _as_shipment(draft)
    # 서식마다 쓰는 칸이 달라도, 값은 한 벌에서 꺼냅니다.
    reference = document_service.build_reference(stand_in)
    reference.update(_draft_numbers(draft))
    reference.update(_extras(draft))

    data = {name: reference.get(name, "") for name in fields_for(kind)}
    data["items"] = _items(kind, stand_in)

    # 아직 안 정해진 칸을 표시합니다.
    undecided = []
    for name in SCHEDULE_FIELDS.get(kind, ()):
        if name in data and not str(data[name]).strip():
            data[name] = UNDECIDED
            undecided.append(name)

    return {"kind": kind, "title": FORMS[kind], "data": data,
            "columns": item_columns(kind), "undecided": undecided,
            "missing": _missing(kind, data)}


def _draft_numbers(draft: dict) -> dict:
    """날짜와 서류 번호.

    build_reference는 Shipment 번호로 "CI-DRAFT" 같은 것을 만들어 냅니다.
    초안에는 아직 번호가 없으니, 적어 주신 것이 있으면 그걸 쓰고 없으면
    비워 둡니다. 지어낸 번호가 서류에 찍히면 나중에 그게 진짜인 줄 압니다.
    날짜는 오늘로 둡니다. 서류를 만든 날이 맞습니다.
    """

    given = str(draft.get("invoice_no") or "").strip()
    return {
        "doc_date": date.today().isoformat(),
        "doc_no": given,
        "invoice_no": given,
        "order_no": str(draft.get("order_no") or "").strip(),
    }


def _extras(draft: dict) -> dict:
    """서식에만 있고 Shipment에는 자리가 없는 칸. 적어 주신 대로 씁니다."""

    # shipment_time은 견적송장 ⑬입니다. 오퍼시트의 "Within 30 days after L/C"는
    # 스케줄이 아니라 계약 조건이라, 적혀 있으면 "미정" 대신 그 문구를 씁니다.
    names = ("buyer", "lc_no", "other_references", "payment_terms", "shipping_marks",
             "remarks", "bank_info", "po_no", "validity_date", "signed_by", "shipment_time",
             "accepted_by", "consignee_city_zip", "attention", "customer_order_no",
             "date_ordered", "container_no", "comments", "packed_by", "invoice_no")
    extras = {name: str(draft.get(name) or "").strip()
              for name in names if str(draft.get(name) or "").strip()}
    # 가격 조건은 장소와 함께 적는 것이 맞습니다. "FOB" 대신 "FOB BUSAN".
    code = str(draft.get("incoterms") or "").strip().upper()
    place = str(draft.get("incoterms_place") or "").strip()
    if code and place:
        extras["incoterms"] = f"{code} {place}"
    return extras


def _items(kind: str, stand_in) -> list[dict]:
    """품목 표. 표준 포장명세서만 서식이 달라 따로 만듭니다."""

    if kind != "packing_list_std":
        return document_service.build_items(stand_in, kind)

    rows = []
    for cargo in stand_in.cargos:
        packages = document_service.packages_text(cargo)
        # ⑬은 "수량 또는 순중량"입니다. 낱개로 값을 매겼으면 그 수량을 먼저 적어
        # 송장의 수량(2,000 PCS)과 포장명세서가 같은 숫자를 말하게 합니다.
        amount_line = _kg(cargo.net_weight_kg)
        if document_service.priced_by_units(cargo):
            counted = f"{document_service.count_text(cargo.unit_quantity)} {cargo.price_unit}"
            amount_line = " / ".join(part for part in (counted, amount_line) if part)
        rows.append({
            "shipping_marks": "",
            "packages": packages,
            "description": cargo.product_description or "",
            "net_weight": amount_line,
            "total_weight": _kg(cargo.total_weight_kg),
            "measurement": f"{cargo.total_cbm:,.3f} CBM" if cargo.total_cbm else "",
        })
    return rows


def _kg(value) -> str:
    return f"{value:,.2f} KG" if value else ""


def with_private(draft: dict, private: dict | None) -> dict:
    """은행 정보·바이어 주소·연락처를 그림을 그리는 순간에만 합칩니다. 저장하지 않습니다.

    이 값들은 이용자 브라우저에만 있다가, 미리보기(가려서)나 PDF(그대로)를
    만들 때만 서버를 지나갑니다. 미리보기와 PDF가 같은 방식으로 합치도록
    한 곳에 둡니다.

    연락처는 바이어 주소 아랫줄에 붙입니다. 견적송장·상업송장·포장명세서에는
    연락처 칸이 따로 없어, 그렇게 하지 않으면 PDF 어디에도 찍히지 않습니다.
    """

    merged = dict(draft or {})
    private = private if isinstance(private, dict) else {}
    bank = str(private.get("bank_info") or "").strip()[:500]
    address = str(private.get("buyer_address") or "").strip()[:500]
    contact = str(private.get("buyer_contact") or "").strip()[:200]
    if bank:
        merged["bank_info"] = bank
    if address or contact:
        merged["buyer_address"] = "\n".join(part for part in (
            address or str(merged.get("buyer_address") or "").strip(), contact) if part)
    if contact:
        merged["buyer_email"] = contact
    return merged


# 미리보기에서 가리는 칸. 은행 정보와 바이어(이름·주소·연락처)입니다.
# 끝자리만 보이는 식이 아니라 전부 덮습니다. PDF에는 원래 값이 들어갑니다.
MASKED_FIELDS = ("bank_info", "consignee", "consignee_address", "attention", "buyer",
                 "notify_party", "consignee_city_zip")

# 빈 칸을 어디서 채우는지. 여기 없는 칸은 서류 작성 화면에서 채웁니다.
FROM_PLANNING = {"etd", "eta", "vessel_or_flight", "carrier", "pol", "pod", "final_destination",
                 "incoterms", "currency", "gross_weight_kg", "net_weight_kg", "total_cbm",
                 "date_shipped", "shipped_via", "equipment", "freight_term", "shipment_time",
                 "carriage_by", "invoice_value"}
ITEM_FROM_PLANNING = {"packages", "total_weight", "measurement", "net_weight", "unit_weight",
                      "shipped", "quantity"}
PLANNING_HINT = "운송 계획에서 입력하면 채워집니다"
DOCUMENT_HINT = "서류 작성에서 입력하면 채워집니다"


def _mark_for_preview(data: dict, *, masked: bool, hints: bool) -> dict:
    """미리보기용 사본. 가릴 칸은 가리고, 빈 칸에는 어디서 채우는지 적습니다."""

    from app.processors import document_form

    shown = dict(data)
    for name, value in data.items():
        if name == "items":
            continue
        text = str(value or "").strip()
        if masked and name in MASKED_FIELDS and text:
            shown[name] = document_form.MASKED
        elif hints and text == UNDECIDED:
            shown[name] = document_form.HINT + PLANNING_HINT
        elif hints and not text:
            where = PLANNING_HINT if name in FROM_PLANNING else DOCUMENT_HINT
            shown[name] = document_form.HINT + where
    if hints:
        shown["items"] = [
            {key: (value if str(value or "").strip() else document_form.HINT + (
                "운송 계획에서" if key in ITEM_FROM_PLANNING else "서류 작성에서"))
             for key, value in row.items()}
            for row in data.get("items") or []]
    return shown


def preview(kind: str, draft: dict, *, masked: bool = False, hints: bool = False) -> str:
    """대화창에 바로 붙일 수 있는 그림 한 장. data URI로 돌려줍니다.

    파일로 저장하지 않습니다. 초안은 아직 확정이 아니라 서버에 남길
    이유가 없고, 남기면 누가 언제 지울지가 또 일이 됩니다.

    masked=True면 은행·바이어 정보를 덮고, hints=True면 빈 칸에 어디서
    채우는지 빨간 글씨로 적습니다. 둘 다 그림에만 있고 PDF에는 없습니다.
    """

    import base64

    from app.processors import document_form

    rendered = render(kind, draft)
    data = _mark_for_preview(rendered["data"], masked=masked, hints=hints)
    page = document_form.draw_form(kind, data, rendered["columns"])
    png = document_form.as_png(document_form.crop_to_content(page))
    return "data:image/png;base64," + base64.b64encode(png).decode()


def pdf_bytes(kind: str, draft: dict) -> bytes:
    """내려받을 PDF. 화면에 보여 준 것과 같은 내용이되 A4 한 장 그대로입니다."""

    from app.processors import document_form

    rendered = render(kind, draft)
    page = document_form.draw_form(kind, rendered["data"], rendered["columns"])
    return document_form.as_pdf(page)


def file_name(kind: str) -> str:
    """내려받을 때 붙일 이름."""

    return {"commercial_invoice": "commercial_invoice",
            "packing_list": "packing_list",
            "packing_list_std": "packing_list",
            "proforma_invoice": "proforma_invoice"}.get(kind, kind) + "_draft.pdf"


def _missing(kind: str, data: dict) -> list[dict]:
    """아직 비어 있어 사람이 채워야 하는 칸. 숨기지 않습니다."""

    rows = []
    for name, value in data.items():
        if name == "items" or str(value).strip():
            continue
        rows.append({"field": name,
                     "label": document_service.field_label(
                         "packing_list" if kind == "packing_list_std" else kind, name)})
    return rows
