"""AI Export Assistant.

The assistant never computes numbers or rules on its own. Every answer is
assembled from Shipment data, processor results, and collector data, and only
explains them. Numbers come from code; the assistant describes them.
"""

from __future__ import annotations

from datetime import date

from app.collectors import customs_client
from app.processors.cashflow_calculator import calculate_cash_flow
from app.processors.cost_calculator import EXPORTER_PAYS
from app.processors.schedule_calculator import check_buyer_deadline
from app.repositories import shipment_repository
from app.services import ServiceError
from app.services.shipment_service import cost_groups
from app.validators import ValidationError
from app.validators.cargo_validator import MAX_INVOICE_VALUE, parse_number
from app.validators.shipment_validator import parse_date, require_text

STATUS_LABELS = {
    "confirmed": "확인됨",
    "check_required": "확인 필요",
    "not_applicable": "해당 없음",
    "unknown": "정보 없음",
}

# LCL typically stops being economical somewhere around this volume.
LCL_TO_FCL_REVIEW_CBM = 13

INTENT_KEYWORDS = {
    "readiness": ["수출", "규제", "인증", "hs", "통관", "등록", "가능", "필요", "라벨"],
    "cost": ["비용", "운임", "물류비", "견적", "비싸", "수익", "마진", "charge"],
    "exception": ["지연", "delay", "eta", "늦", "변경", "도착", "납기"],
    "cashflow": ["자금", "결제", "현금", "대금", "cash", "운전자금", "입금", "지급"],
}


def _won(value: float) -> str:
    return f"{round(value):,}원"


def export_readiness(shipment) -> dict:
    hs_code = shipment.cargo.hs_code if shipment.cargo else ""
    result = customs_client.fetch_regulations(hs_code, shipment.destination_country)
    if not result["success"]:
        return {"available": False, "message": result["message"], "source": result["source"]}

    items = result["data"]["items"]
    for item in items:
        item["status_label"] = STATUS_LABELS.get(item["status"], item["status"])
    counts = {status: sum(1 for item in items if item["status"] == status) for status in STATUS_LABELS}

    lines = []
    if not hs_code:
        lines.append("HS CODE가 입력되지 않아 품목별 규제 항목을 조회하지 못했습니다. 화물 정보에 HS CODE를 입력하면 더 구체적인 항목을 안내할 수 있습니다.")
    else:
        lines.append(f"HS CODE {hs_code} · 도착국 {shipment.destination_country} 기준으로 확인이 필요한 항목은 {counts['check_required']}건입니다.")
    if counts["check_required"]:
        lines.append("제품 성격과 판매 방식에 따라 관련 인증 또는 신고 요건이 적용될 수 있으므로 아래 항목을 관세사·Buyer와 함께 확인하세요.")
    if counts["unknown"]:
        lines.append(f"등록된 데이터가 없어 판단할 수 없는 항목이 {counts['unknown']}건 있습니다. 이 항목은 '문제없음'이 아니라 '확인되지 않음'을 뜻합니다.")
    lines.append("이 안내는 수출 가능 여부를 확정하지 않습니다. 최종 판단은 관계 기관 또는 관세사를 통해 확인하세요.")
    return {"available": True, "items": items, "counts": counts, "lines": lines, "source": result["source"]}


def cost_explanation(shipment) -> dict:
    groups = cost_groups(shipment)
    total = shipment.total_cost_krw
    if not total:
        return {"available": False, "lines": ["비용 데이터가 없습니다."]}

    totals = {group["category"]: group["total_krw"] for group in groups}
    freight = totals.get("Freight", 0)
    local = totals.get("Origin Charge", 0) + totals.get("Destination Charge", 0) + totals.get("Customs", 0)
    shares = [
        {"category": group["category"], "total_krw": group["total_krw"], "share": round(group["total_krw"] / total * 100, 1)}
        for group in groups
    ]

    lines = [f"현재 조건의 총 물류비는 {_won(total)}입니다. (계산: Python 비용 엔진, 운임·요율 출처: {shipment.schedule_source})"]
    if local > freight:
        lines.append(f"국제운임({_won(freight)})보다 출발지·도착지 Local Charge와 통관비 합계({_won(local)}) 비중이 높습니다.")
    else:
        lines.append(f"국제운임({_won(freight)})이 가장 큰 비용 항목입니다. 운임은 시황에 따라 변동되므로 선적 전 재견적을 권장합니다.")

    cargo = shipment.cargo
    if cargo:
        if shipment.sea_mode == "LCL" and cargo.total_cbm >= LCL_TO_FCL_REVIEW_CBM:
            lines.append(f"화물량이 {cargo.total_cbm:.1f} CBM으로 LCL 기준으로는 큰 편입니다. FCL 견적과 함께 비교해 보세요.")
        elif shipment.sea_mode == "LCL":
            lines.append("화물량이 증가할 경우 LCL과 FCL 견적을 함께 비교하는 것이 좋습니다.")
        if shipment.transport_mode == "AIR" and cargo.chargeable_weight_kg > cargo.total_weight_kg:
            lines.append(f"부피중량({cargo.chargeable_weight_kg:,.0f}kg)이 실중량({cargo.total_weight_kg:,.0f}kg)보다 커서 부피 기준으로 운임이 부과됩니다. 포장 부피를 줄이면 운임을 낮출 수 있습니다.")
        if cargo.total_cbm:
            lines.append(f"CBM당 물류비는 약 {_won(total / cargo.total_cbm)}, kg당 약 {_won(total / cargo.total_weight_kg)}입니다.")

    exporter_cost = sum(cost.krw_amount for cost in shipment.costs if _exporter_pays(shipment.incoterms, cost.category))
    lines.append(f"{shipment.incoterms} 조건에서 수출자 부담 비용은 약 {_won(exporter_cost)}, 나머지는 Buyer 부담입니다.")
    return {"available": True, "shares": shares, "lines": lines, "total_krw": total, "exporter_cost_krw": exporter_cost}


def _exporter_pays(incoterms: str, category: str) -> bool:
    group = {
        "Origin Charge": "origin",
        "Customs": "origin",
        "Freight": "freight",
        "Insurance": "insurance",
        "Destination Charge": "destination",
    }.get(category)
    return group in EXPORTER_PAYS.get(incoterms, set())


def exception_guide(shipment) -> dict:
    changes = [event for event in shipment.tracking_events if event.event_code == "eta_changed"]
    deadline = check_buyer_deadline(shipment.eta, shipment.buyer_required_date, shipment.transport_mode) if shipment.eta else None
    delay = shipment.delay_days

    if not changes and delay <= 0:
        lines = ["현재 기록된 ETA 변경이나 지연 이벤트가 없습니다."]
        if deadline:
            lines.append(f"현재 ETA 기준 Buyer 납기까지 여유는 {deadline['margin_days']}일입니다.")
        return {"has_exception": False, "lines": lines, "actions": [], "deadline": deadline}

    lines = [
        f"최초 계획 ETA {shipment.planned_eta.isoformat()} 대비 현재 ETA는 {shipment.eta.isoformat()}로 "
        f"{abs(delay)}일 {'지연' if delay > 0 else '단축'}되었습니다."
    ]
    actions = []
    if deadline:
        if deadline["on_time"]:
            lines.append(f"수입통관·배송 기간을 감안해도 Buyer 납기까지 {deadline['margin_days']}일 여유가 있습니다.")
        else:
            lines.append(f"수입통관·배송 기간을 감안하면 Buyer 납기를 {abs(deadline['margin_days'])}일 초과할 수 있습니다.")
    if delay > 0:
        actions = [
            "Buyer 납기일 영향 확인",
            "현지 Delivery 예약 변경 여부 확인",
            "도착지 Free Time(DEM/DET) 확인",
            "Buyer에게 ETA 변경 안내",
        ]
        if deadline and not deadline["on_time"]:
            actions.append("항공 분할 선적 등 대체 운송 검토")
    return {"has_exception": delay > 0, "lines": lines, "actions": actions, "deadline": deadline, "changes": changes}


def cash_flow(shipment) -> dict:
    payments = [
        {"id": payment.id, "label": payment.label, "amount_krw": payment.amount_krw, "due_date": payment.due_date,
         "source": payment.source}
        for payment in shipment.payments
    ]
    if not payments:
        return {
            "available": False,
            "lines": ["등록된 결제 일정이 없습니다. 생산대금·물류비·Buyer 입금 일정을 입력하면 필요한 운전자금을 계산합니다."],
            "result": None,
        }

    result = calculate_cash_flow(payments)
    lines = []
    if result["peak_funding_need_krw"] > 0:
        lines.append(
            f"현재 Shipment 기준으로 Buyer 대금 수령 전까지 최대 약 {_won(result['peak_funding_need_krw'])}의 운전자금이 필요합니다."
            f" (가장 부족한 시점: {result['peak_funding_date'].isoformat()})"
        )
    else:
        lines.append("입력된 일정 기준으로는 추가 운전자금이 필요하지 않습니다.")
    lines.append(f"총 입금 {_won(result['total_inflow_krw'])}, 총 지출 {_won(result['total_outflow_krw'])}, 순현금흐름 {_won(result['net_krw'])}입니다.")
    if not any(item["amount_krw"] > 0 for item in payments):
        lines.append("Buyer 입금 일정이 없어 순현금흐름이 음수로 표시됩니다. 대금 회수 일정을 입력하세요.")
    return {"available": True, "lines": lines, "result": result}


def add_payment(shipment, form: dict) -> None:
    label = require_text(form.get("label"), "항목명", max_length=100, field="label")
    direction = form.get("direction")
    if direction not in ("in", "out"):
        raise ValidationError("입금/지출을 선택해주세요.", "direction")
    amount = parse_number(form.get("amount_krw"), "금액", max_value=MAX_INVOICE_VALUE * 2000, field="amount_krw")
    due_date = parse_date(form.get("due_date"), "일자", field="due_date")
    shipment_repository.add_payment(
        shipment, label=label, amount_krw=round(amount) * (1 if direction == "in" else -1), due_date=due_date, source="manual"
    )
    shipment_repository.commit()


def add_logistics_payment(shipment) -> None:
    """Add the exporter-borne logistics cost as an outflow on the ETD (calculated)."""

    explanation = cost_explanation(shipment)
    if not explanation["available"]:
        raise ServiceError("비용 데이터가 없습니다.", "NO_COSTS")
    shipment_repository.add_payment(
        shipment,
        label="물류비 (수출자 부담분)",
        amount_krw=-explanation["exporter_cost_krw"],
        due_date=shipment.etd or date.today(),
        source="calculated",
    )
    shipment_repository.commit()


def remove_payment(shipment, payment_id: int) -> None:
    if not shipment_repository.delete_payment(shipment, payment_id):
        raise ServiceError("결제 항목을 찾을 수 없습니다.", "PAYMENT_NOT_FOUND", 404)
    shipment_repository.commit()


def classify_question(question: str) -> str | None:
    text = question.lower()
    scores = {intent: sum(1 for keyword in keywords if keyword in text) for intent, keywords in INTENT_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else None


def answer_question(shipment, question: str) -> dict:
    question = (question or "").strip()
    if not question:
        raise ValidationError("질문을 입력해주세요.", "question")
    intent = classify_question(question[:500])
    handlers = {
        "readiness": ("수출 가능성 판단", export_readiness),
        "cost": ("비용·수익성 해석", cost_explanation),
        "exception": ("예외·리스크 대응", exception_guide),
        "cashflow": ("결제·자금 관리", cash_flow),
    }
    if intent is None:
        return {
            "intent": None,
            "title": "안내",
            "lines": [
                "이 Shipment에 대해 답할 수 있는 주제는 수출 요건 확인, 물류비 해석, ETA 지연 대응, 자금 흐름입니다.",
                "예: '미국 수출하려면 무엇을 확인해야 해?', '물류비가 왜 이렇게 나와?', 'ETA가 늦어지면 어떻게 해?'",
            ],
            "actions": [],
        }
    title, handler = handlers[intent]
    result = handler(shipment)
    return {"intent": intent, "title": title, "lines": result.get("lines", []), "actions": result.get("actions", [])}
