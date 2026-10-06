"""관세사에게 넘길 수출신고 자료를 모읍니다.

수출신고서는 수출자가 직접 쓰는 서류가 아닙니다. 관세사가 유니패스로 신고하고,
수출자는 신고에 필요한 자료를 넘깁니다. 그런데 무엇을 넘겨야 하는지 몰라
전화와 메일이 여러 번 오가는 일이 흔합니다.

이 파일은 Shipment에 이미 들어 있는 값을 관세사가 바로 쓸 수 있는 형태로 묶어
줍니다. 값을 지어내지 않고, 비어 있으면 비어 있다고 알려 줍니다.
"""

from __future__ import annotations

from app.timeutil import today_kst

from app.processors.korean import particle
from app.validators.cargo_validator import PACKAGE_TYPES, PACKAGE_UNITS, priced_by_units

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


def _country_label(code: str) -> str:
    """'US' → '미국 (US)'. 목록에 없으면 코드만 적습니다. **바깥을 부르지 않습니다.**"""

    code = str(code or "").strip().upper()
    if not code:
        return ""
    from app.collectors import location_client

    name = location_client.country_name(code)
    return f"{name} ({code})" if name and name != code else code


def lookup_clearance_code(business_no: str) -> dict:
    """사업자등록번호로 통관고유부호를 관세청에서 찾아 줍니다.

    통관고유부호는 수출신고서의 법정 기재사항(시행령 제246조 제1항 제5호)이고
    따로 신청해야 받습니다. 번호를 모르면 신고를 시작할 수 없습니다.
    """

    from app.collectors import customs_extra_client

    return customs_extra_client.clearance_code(business_no=business_no)


def refund_estimate(shipment) -> dict:
    """간이정액 환급으로 얼마를 돌려받을 수 있는지 어림합니다.

    관세청 환급율표는 "수출금액 1만원당 몇 원" 또는 "10달러당 몇 원"으로 줍니다.
    실제 환급액은 세관이 정하므로 여기서는 어림값이라고 밝힙니다.
    """

    from app.collectors import customs_extra_client

    rows = []
    for cargo in shipment.cargos:
        if not cargo.hs_code:
            continue
        found = customs_extra_client.refund_rate(cargo.hs_code)
        if not found["success"] or not found["data"]:
            continue
        for rate in found["data"]:
            rows.append({**rate, "line_no": cargo.line_no,
                         "product_description": cargo.product_description})

    eligible = None
    if shipment.exporter_business_no:
        codes = customs_extra_client.clearance_code(business_no=shipment.exporter_business_no)
        if codes["success"] and codes["data"]:
            company = customs_extra_client.refund_company(codes["data"][0]["clearance_code"])
            if company["success"] and company["data"]:
                eligible = company["data"][0]

    return {
        "available": bool(rows),
        "rates": rows,
        "company": eligible,
        "note": ("간이정액 환급율표는 관세청이 품목별로 고시합니다. "
                 "실제 환급액은 수출 실적과 서류를 보고 세관이 정합니다."),
    }


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
                # 목적국은 **나라**입니다. 예전에는 도착항 이름을 넣어
                # "목적국: Los Angeles (US)" 라고 적혔습니다. 수출신고서 ⑫목적국
                # 칸에 그대로 옮겨 적는 값이라 나라로 적습니다. 관세사가 선적서류와
                # 맞춰 볼 도착항은 아래에 따로 답니다. (2026-09-26)
                {"label": "목적국", "value": _country_label(shipment.destination_country)},
                {"label": "도착항 (POD)",
                 "value": " ".join(part for part in
                                   [shipment.destination_name,
                                    f"({shipment.destination_code})"
                                    if shipment.destination_code else ""] if part)},
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
            # 신고서의 수량·단가는 송장과 같은 기준이어야 합니다. 낱개로 값을 매겼으면
            # 낱개 수량과 그 단위를, 아니면 포장 개수를 씁니다.
            "quantity": cargo.unit_quantity if priced_by_units(cargo) else cargo.quantity,
            "unit": (cargo.price_unit if priced_by_units(cargo)
                     else PACKAGE_UNITS.get(cargo.package_type, cargo.package_type)),
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
    # 수출신고는 10자리 HSK 로 합니다. 6자리(3304.99)는 "완료"로 나가 관세사에게 그대로 전달됐습니다
    # (전수 점검 1회차). 앞의 6자리는 맞을 수 있으니 '10자리로 마저 적기'로 알립니다.
    missing += [f"품목 {item['line_no']} HS CODE 10자리(HSK) — 지금 {len(_digits(item['hs_code']))}자리"
                for item in lines
                if not _blank(item["hs_code"]) and len(_digits(item["hs_code"])) < 10]

    # 따로 발급받은 서류(원산지증명서·인증서·검역증 …)도 함께 넘깁니다.
    # 관세사는 신고할 때 이 파일들을 첨부합니다. 여기 없으면 "빠진 서류"가 됩니다.
    papers = [{"key": doc.requirement_key, "filename": doc.filename,
               "note": doc.agreement or "", "status": doc.review_label}
              for doc in shipment.requirement_documents]

    return {
        "shipment_id": shipment.shipment_id,
        "papers": papers,
        "sections": sections,
        # 값은 다 찼는데 **앞뒤가 안 맞는** 것. 비어 있는 칸(missing)과는 다릅니다.
        "mismatches": _mismatches(shipment),
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

    # 따로 발급받은 서류도 목록에 적어 둡니다. 관세사가 신고할 때 함께 첨부합니다.
    if sheet.get("papers"):
        lines += ["", "■ 함께 보내는 서류 (따로 발급받은 것)"]
        for paper in sheet["papers"]:
            tail = f" · {paper['note']}" if paper["note"] else ""
            lines.append(f"  - {paper['filename']}{tail}")

    if sheet["missing"]:
        lines += ["", "■ 아직 비어 있는 칸",
                  "  " + ", ".join(sheet["missing"])]
    # 값은 다 차 있어서 눈에 안 띄는 것. 관세사가 화면을 안 보고 글만 복사해
    # 가도 보여야 합니다. (2026-09-27)
    if sheet.get("mismatches"):
        lines += ["", "■ 값은 있는데 앞뒤가 안 맞는 것"]
        lines += [f"  - {row}" for row in sheet["mismatches"]]
    return "\n".join(lines)


def _digits(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _country_code(value) -> str:
    """'US' 는 그대로, '미국'·'United States' 는 코드로. 못 알아보면 비교하지 않습니다(오탐 방지)."""

    from app.collectors import location_client

    text = (value or "").strip()
    if len(text) == 2 and text.isascii() and text.isalpha():     # "미국" 도 두 글자라 ASCII 를 따집니다
        return text.upper()
    return location_client.find_country_by_name(text) or ""


def _mismatches(shipment) -> list[str]:
    """값은 다 찼는데 앞뒤가 안 맞는 것.

    비어 있는 칸은 사람이 바로 알아챕니다. 이건 다 채워져 있어서 안 보입니다.
    그대로 신고되고, 나중에 정정해야 합니다. (2026-09-27)
    """

    found = []
    buyer = _country_code(getattr(shipment.buyer, "country", ""))
    place = (shipment.destination_country or "").strip().upper()
    if buyer and place and buyer != place:
        found.append(
            f"받는 분 나라({buyer})와 도착지 나라({place})가 다릅니다. "
            "삼각무역이면 맞습니다. 아니라면 둘 중 하나를 고쳐 주세요 — "
            "수출신고서 목적국과 선적서류 수하인이 서로 다르게 나갑니다.")

    # 날짜가 앞뒤로 뒤집힌 것.
    #
    # 도착이 출발보다 빠르면 그 일정은 있을 수 없습니다. 스케줄을 고른 뒤에
    # 날짜를 손으로 고치면 이렇게 됩니다. 값이 다 차 있어 눈에 안 띕니다.
    if shipment.etd and shipment.eta and shipment.eta < shipment.etd:
        found.append(
            f"도착 예정일({shipment.eta})이 출항일({shipment.etd})보다 빠릅니다. "
            "있을 수 없는 일정입니다. 스케줄을 다시 골라 주세요.")

    # 바이어에게 약속한 날이 이미 지난 것. 그대로 두면 지키지 못할 약속으로
    # 일정을 짜게 됩니다.
    if shipment.buyer_required_date and shipment.eta             and shipment.buyer_required_date < shipment.eta:
        late = (shipment.eta - shipment.buyer_required_date).days
        found.append(
            f"Buyer 요청 도착일({shipment.buyer_required_date})보다 "
            f"도착 예정일({shipment.eta})이 {late}일 늦습니다. "
            "바이어에게 미리 알리거나 더 빠른 스케줄을 찾아 주세요.")

    # 출발 희망일이 이미 지난 것.
    #
    # 스케줄은 미래 것이 잡히므로 화면의 날짜는 멀쩡해 보입니다. 그런데 희망일
    # 자체가 과거로 남아 있으면, 나중에 그 날짜로 일정을 다시 짜거나 서류에
    # 적을 때 앞뒤가 안 맞습니다.
    from datetime import date as _date

    if shipment.requested_departure_date and shipment.requested_departure_date < today_kst():
        found.append(
            f"출발 희망일({shipment.requested_departure_date})이 이미 지난 날입니다. "
            f"실제 출항일은 {shipment.etd or '미정'}입니다. 희망일을 고쳐 두시면 "
            "나중에 일정을 다시 짤 때 헷갈리지 않습니다.")

    # 화물 준비일이 출항일보다 늦은 것. 준비가 안 끝났는데 배가 떠납니다.
    if shipment.cargo_ready_date and shipment.etd             and shipment.cargo_ready_date > shipment.etd:
        found.append(
            f"화물 준비일({shipment.cargo_ready_date})이 출항일({shipment.etd})보다 "
            "늦습니다. 그 배에는 싣지 못합니다.")

    # 부피와 무게가 서로 말이 안 되는 화물.
    #
    # 포장당 중량 칸에 전체 중량을 적는 것이 가장 흔한 실수입니다. 그러면
    # 운임 기준이 100배 틀립니다. 화면에서는 적을 때 알려 주지만, 건이 만들어진
    # 뒤에는 아무 데서도 안 보였습니다. 관세사에게 넘기기 전에 한 번 더 봅니다.
    from app.processors import cargo_calculator

    for index, cargo in enumerate(shipment.cargos, start=1):
        note = cargo_calculator.density_note(cargo.total_cbm or 0, cargo.total_weight_kg or 0)
        if note and cargo_calculator.density_suspect(cargo.total_cbm or 0,
                                                    cargo.total_weight_kg or 0):
            found.append(f"품목 {index}: {note}")
    return found


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

    # 자릿수만 보면 0000000000 도 통과해 수출신고서에 그대로 실립니다.
    # 국세청 검증번호까지 봅니다. (2026-09-26)
    from app.validators import business_no as business_no_rule

    business_no = business_no_rule.parse(form.get("exporter_business_no"),
                                         field="exporter_business_no")

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
