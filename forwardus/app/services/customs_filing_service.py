"""관세사에게 넘길 수출신고 자료를 모읍니다.

수출신고서는 수출자가 직접 쓰는 서류가 아닙니다. 관세사가 유니패스로 신고하고,
수출자는 신고에 필요한 자료를 넘깁니다. 그런데 무엇을 넘겨야 하는지 몰라
전화와 메일이 여러 번 오가는 일이 흔합니다.

이 파일은 Shipment에 이미 들어 있는 값을 관세사가 바로 쓸 수 있는 형태로 묶어
줍니다. 값을 지어내지 않고, 비어 있으면 비어 있다고 알려 줍니다.
"""

from __future__ import annotations

from app.processors.korean import particle
from app.validators.cargo_validator import PACKAGE_TYPES, PACKAGE_UNITS

# 관세청 수출신고서의 거래구분. 대부분의 일반 수출은 11입니다.
TRADE_KINDS = {
    "11": "11 · 일반형태 수출",
    "29": "29 · 위탁가공을 위한 원자재 수출",
    "83": "83 · 무상 수출 (견본품·선물 등)",
    "84": "84 · 수리·검사 후 재수출",
    "94": "94 · 임대 수출",
}
DEFAULT_TRADE_KIND = "11"

# 결제방법. Incoterms가 아니라 대금을 어떻게 받는지입니다.
PAYMENT_METHODS = {
    "LS": "LS · 일람불 신용장 (Sight L/C)",
    "LU": "LU · 기한부 신용장 (Usance L/C)",
    "TT": "TT · 단순송금방식 (T/T)",
    "DA": "DA · 인수인도조건 (D/A)",
    "DP": "DP · 지급인도조건 (D/P)",
    "GO": "GO · 무상",
}
DEFAULT_PAYMENT_METHOD = "TT"

TRANSPORT_LABELS = {"SEA": "10 · 해상", "AIR": "40 · 항공"}


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def filing_sheet(shipment) -> dict:
    """관세사에게 넘길 신고자료 한 장.

    `sections`는 화면과 복사용 글 모두에 쓰고, `missing`은 아직 비어 있어
    수출자가 채워야 하는 칸입니다.
    """

    buyer = shipment.buyer
    cargos = list(shipment.cargos)
    total_quantity = sum(cargo.quantity for cargo in cargos)
    total_gross = sum(cargo.total_weight_kg for cargo in cargos)
    net_values = [cargo.net_weight_kg for cargo in cargos if cargo.net_weight_kg is not None]
    total_net = sum(net_values) if len(net_values) == len(cargos) and cargos else None

    trade_kind = shipment.customs_trade_kind or DEFAULT_TRADE_KIND
    payment_method = shipment.customs_payment_method or DEFAULT_PAYMENT_METHOD

    sections = [
        {
            "title": "수출자 · 구매자",
            "rows": [
                {"label": "수출자 상호", "value": shipment.exporter_name},
                {"label": "수출자 주소", "value": shipment.exporter_address},
                {"label": "수출자 사업자등록번호", "value": shipment.exporter_business_no,
                 "hint": "수출신고에 반드시 들어갑니다. 관세사가 요청하기 전에 채워 주세요."},
                {"label": "구매자 상호", "value": buyer.name if buyer else ""},
                {"label": "구매자 주소", "value": buyer.address if buyer else ""},
                {"label": "구매자 국가", "value": buyer.country if buyer else ""},
            ],
        },
        {
            "title": "거래 조건",
            "rows": [
                {"label": "거래구분", "value": TRADE_KINDS.get(trade_kind, trade_kind)},
                {"label": "결제방법", "value": PAYMENT_METHODS.get(payment_method, payment_method)},
                {"label": "인도조건 (Incoterms)", "value": shipment.incoterms},
                {"label": "결제통화", "value": shipment.currency},
                {"label": "신고가격",
                 "value": (f"{shipment.currency} {shipment.invoice_value:,.2f}"
                           if shipment.invoice_value else ""),
                 "hint": "송장 금액입니다. FOB가 아닌 조건이면 관세사가 FOB로 환산합니다."},
            ],
        },
        {
            "title": "운송",
            "rows": [
                {"label": "운송수단", "value": TRANSPORT_LABELS.get(shipment.transport_mode, "")},
                {"label": "적재항 (POL)",
                 "value": f"{shipment.origin_name} ({shipment.origin_code})"},
                {"label": "목적국",
                 "value": f"{shipment.destination_name} ({shipment.destination_country})"},
                {"label": "선사 · 선박/편명",
                 "value": " · ".join(part for part in
                                     [shipment.carrier, shipment.vessel_or_flight] if part)},
                {"label": "출항 예정일 (ETD)",
                 "value": shipment.etd.isoformat() if shipment.etd else ""},
                {"label": "원산지", "value": shipment.country_of_origin or "KR · 대한민국"},
            ],
        },
        {
            "title": "포장 · 중량 합계",
            "rows": [
                {"label": "총 포장 수량",
                 "value": f"{total_quantity:,} {_units(cargos)}" if total_quantity else ""},
                {"label": "총중량 (Gross)", "value": f"{total_gross:,.2f} kg" if total_gross else ""},
                {"label": "순중량 (Net)",
                 "value": f"{total_net:,.2f} kg" if total_net is not None else "",
                 "hint": "수출신고서에 들어갑니다. 품목마다 순중량을 적으면 자동으로 더해집니다."},
            ],
        },
    ]

    lines = [
        {
            "line_no": cargo.line_no,
            "hs_code": cargo.hs_code,
            "product_description": cargo.product_description,
            # 규격은 포장 치수가 아니라 물품 자체의 규격입니다. 우리가 아는 것만 적습니다.
            "spec": f"{cargo.length_cm:g} × {cargo.width_cm:g} × {cargo.height_cm:g} cm / 포장",
            "quantity": cargo.quantity,
            "unit": PACKAGE_UNITS.get(cargo.package_type, cargo.package_type),
            "package_type": PACKAGE_TYPES.get(cargo.package_type, cargo.package_type),
            "net_weight_kg": cargo.net_weight_kg,
            "gross_weight_kg": cargo.total_weight_kg,
            "unit_price": cargo.unit_price,
            "amount": cargo.amount,
            "dangerous": (f"{cargo.un_number} CLASS {cargo.dg_class}"
                          if cargo.is_dangerous and cargo.un_number else ""),
        }
        for cargo in cargos
    ]

    missing = [row["label"] for section in sections for row in section["rows"] if _blank(row["value"])]
    missing += [f"품목 {item['line_no']} HS CODE" for item in lines if _blank(item["hs_code"])]

    return {
        "shipment_id": shipment.shipment_id,
        "sections": sections,
        # Jinja에서 dict.items()와 헷갈리지 않게 lines로 둡니다.
        "lines": lines,
        "missing": missing,
        "trade_kind": trade_kind,
        "payment_method": payment_method,
        "trade_kinds": TRADE_KINDS,
        "payment_methods": PAYMENT_METHODS,
        "note": "수출신고는 관세사가 유니패스로 합니다. 이 자료를 그대로 넘기면 됩니다.",
    }


def _units(cargos) -> str:
    """포장 단위가 섞여 있으면 'PKG'로 뭉뚱그립니다."""

    units = {PACKAGE_UNITS.get(cargo.package_type, cargo.package_type) for cargo in cargos}
    return units.pop() if len(units) == 1 else "PKG"


def as_text(sheet: dict) -> str:
    """메일이나 메신저에 그대로 붙여 넣을 수 있는 글."""

    lines = [f"[수출신고 자료] {sheet['shipment_id']}", ""]
    for section in sheet["sections"]:
        lines.append(f"■ {section['title']}")
        for row in section["rows"]:
            lines.append(f"  - {row['label']}: {row['value'] or '(미입력)'}")
        lines.append("")

    lines.append("■ 품목")
    for item in sheet["lines"]:
        parts = [
            f"  {item['line_no']}. {item['product_description'] or '(품명 미입력)'}",
            f"HS {item['hs_code'] or '(미입력)'}",
            f"{item['quantity']:,} {item['unit']}",
            f"총중량 {item['gross_weight_kg']:,.2f} kg",
        ]
        if item["net_weight_kg"] is not None:
            parts.append(f"순중량 {item['net_weight_kg']:,.2f} kg")
        if item["amount"] is not None:
            parts.append(f"금액 {item['amount']:,.2f}")
        if item["dangerous"]:
            parts.append(f"위험물 {item['dangerous']}")
        lines.append(" · ".join(parts))

    if sheet["missing"]:
        lines += ["", "■ 아직 비어 있는 칸",
                  "  " + ", ".join(sheet["missing"])]
    return "\n".join(lines)


def describe_missing(sheet: dict) -> str:
    """비어 있는 칸을 한 문장으로."""

    if not sheet["missing"]:
        return "신고에 필요한 칸이 모두 채워져 있습니다."
    first = sheet["missing"][0]
    rest = len(sheet["missing"]) - 1
    tail = f" 외 {rest}개" if rest else ""
    return f"{first}{particle(first, '이')}{tail} 아직 비어 있습니다."


def update_filing_fields(shipment, form: dict) -> None:
    """신고 자료에만 쓰는 칸을 저장합니다. 운송 정보는 건드리지 않습니다."""

    from app.repositories import shipment_repository
    from app.validators import ValidationError

    business_no = str(form.get("exporter_business_no") or "").strip()
    if business_no:
        digits = "".join(ch for ch in business_no if ch.isdigit())
        if len(digits) != 10:
            raise ValidationError("사업자등록번호는 숫자 10자리입니다.", "exporter_business_no")
        business_no = f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"

    trade_kind = str(form.get("customs_trade_kind") or DEFAULT_TRADE_KIND)
    if trade_kind not in TRADE_KINDS:
        raise ValidationError("거래구분을 확인해주세요.", "customs_trade_kind")

    payment_method = str(form.get("customs_payment_method") or DEFAULT_PAYMENT_METHOD)
    if payment_method not in PAYMENT_METHODS:
        raise ValidationError("결제방법을 확인해주세요.", "customs_payment_method")

    shipment.exporter_business_no = business_no
    shipment.customs_trade_kind = trade_kind
    shipment.customs_payment_method = payment_method
    shipment.country_of_origin = str(form.get("country_of_origin") or "").strip()[:60] or "KR · 대한민국"
    shipment_repository.commit()
