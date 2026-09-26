"""AI Export Assistant.

The assistant never computes numbers or rules on its own. Every answer is
assembled from Shipment data, processor results, and collector data, and only
explains them. Numbers come from code; the assistant describes them.
"""

from __future__ import annotations

from datetime import date

from app.collectors import customs_client
from app.processors.cashflow_calculator import calculate_cash_flow
from app.processors.cost_calculator import EXPORTER_PAYS, INSURANCE_PAID_BY_EXPORTER
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
    # 적하보험료는 의무 표가 아니라 **누가 내는가**로 봅니다.
    # D조건은 수출자가 도착지까지 위험을 지므로 보험도 수출자가 듭니다.
    # (cost_calculator.INSURANCE_PAID_BY_EXPORTER 의 주석을 보세요)
    if group == "insurance":
        return incoterms in INSURANCE_PAID_BY_EXPORTER
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
    return {"intent": intent, "title": title, "lines": result.get("lines", []),
            "actions": result.get("actions", []), "source": "rule"}


# --- AI 답변 -------------------------------------------------------------------

AI_SYSTEM_PROMPT = """당신은 한국 중소 수출기업의 담당자를 돕는 상담원입니다.
지금 보고 있는 수출 건(Shipment)의 계산 결과를 함께 받습니다.

반드시 지킬 것
- 숫자는 주어진 자료에 있는 값만 쓰세요. 없는 숫자를 만들지 마세요.
  자료에 없으면 "그 값은 아직 계산되지 않았습니다"라고 하세요.
- "수출 가능합니다", "인증이 면제됩니다" 같은 단정을 하지 마세요.
  최종 판단은 세관과 수입국이 합니다.
- **"확인할 요건이 없습니다"라고 절대 말하지 마세요.** 목록이 비어 있는 것은
  "요건이 없다"가 아니라 "우리가 찾은 것이 없다"입니다. HS부호가 정확하지
  않거나 기관 조회가 막혀 못 찾았을 수 있습니다. 그럴 때는
  "우리 자료에서는 걸리는 것을 찾지 못했습니다. 다만 …"처럼
  **찾지 못한 것인지 없는 것인지 구분해서** 말하세요.
- 자료에 `요건조회_상태`가 "일부 실패"면 무엇을 못 봤는지 반드시 덧붙이세요.
- 한국어로, 짧은 문장으로 씁니다. 무역 용어는 처음 쓸 때 우리말로 풀어 주세요.
- 결론부터 말하고 이유를 덧붙이세요. 6문장을 넘기지 마세요.
- 자료에서 위험해 보이는 것(납기 초과, 적재기한 임박, 요건 미확인)이 있으면 먼저 말하세요."""


def ai_context(shipment) -> dict:
    """AI에게 넘길 이 건의 사실. 전부 우리가 계산했거나 기관에서 받은 값입니다."""

    from app.processors import export_requirements

    cargo = shipment.cargo
    buyer = shipment.buyer
    cost = cost_explanation(shipment)
    exception = exception_guide(shipment)
    flow = cash_flow(shipment)

    # 요건은 내부 규칙표만 보면 안 됩니다.
    #
    # 예전에는 export_requirements.check()만 돌렸습니다. 그 표에 없는 품목
    # (예: 볼체인 HS 7117)이면 빈 목록이 되고, AI는 그것을 "요건이 없습니다"로
    # 읽었습니다. **찾지 못한 것을 없다고 답하면 사람을 위험에 빠뜨립니다.**
    # 이제 도착국 인증·세관장확인·FTA 원산지증명서까지 한 곳에서 모읍니다.
    from app.services import required_docs_service

    requirements, checked = [], {"규칙표": True}
    try:
        collected = required_docs_service.collect(shipment, use_ai=False)
        for row in collected["documents"]:
            requirements.append({"확인할 것": row["title"], "필요한 서류": row.get("documents") or [],
                                 "어디서": row.get("agency", ""), "왜": row.get("why", ""),
                                 "출처": row.get("source", "")})
        checked["도착국_인증"] = any(r["출처"] == "country" for r in requirements) or True
        checked["세관장확인"] = any(r["출처"] == "customs" for r in requirements)
    except Exception:                                         # noqa: BLE001
        # 모으다 실패해도 답은 나와야 합니다. 다만 못 봤다고 분명히 적습니다.
        for item in shipment.cargos:
            for rule in export_requirements.check(item.hs_code, is_dangerous=item.is_dangerous):
                requirements.append({"품목": item.product_description, "확인할 것": rule["title"],
                                     "필요한 서류": rule["documents"], "어디서": rule["agency"]})
        checked["도착국_인증"] = False
        checked["세관장확인"] = False

    missing_hs = [item.product_description for item in shipment.cargos if not (item.hs_code or "").strip()]
    status = "모두 확인" if all(checked.values()) and not missing_hs else "일부 실패"
    limits = []
    if not checked.get("세관장확인"):
        limits.append("관세청 세관장확인대상 조회를 하지 못했습니다(기관 응답 없음 또는 키 없음).")
    if missing_hs:
        limits.append(f"HS부호가 비어 있는 품목이 있습니다: {', '.join(missing_hs)}. "
                      "HS부호가 정해져야 걸리는 요건을 찾을 수 있습니다.")

    return {
        "건번호": shipment.shipment_id,
        "상태": shipment.status_label,
        "구간": f"{shipment.origin_name} ({shipment.origin_code}) → "
                f"{shipment.destination_name} ({shipment.destination_code})",
        "운송수단": f"{shipment.transport_mode} {shipment.sea_mode or ''}".strip(),
        "인도조건": shipment.incoterms,
        "송장금액": f"{shipment.currency} {shipment.invoice_value:,.2f}" if shipment.invoice_value else "",
        "구매자": buyer.name if buyer else "",
        "출항예정": shipment.etd.isoformat() if shipment.etd else "",
        "도착예정": shipment.eta.isoformat() if shipment.eta else "",
        "최초계획도착": shipment.planned_eta.isoformat() if shipment.planned_eta else "",
        "지연일수": shipment.delay_days,
        "구매자_요청도착일": (shipment.buyer_required_date.isoformat()
                             if shipment.buyer_required_date else ""),
        "선사_선박": " · ".join(part for part in [shipment.carrier, shipment.vessel_or_flight] if part),
        "화물": [{
            "품명": item.product_description, "HS부호": item.hs_code,
            "수량": item.quantity, "CBM": item.total_cbm, "총중량_kg": item.total_weight_kg,
            "순중량_kg": item.net_weight_kg, "금액": item.amount,
            "위험물": (f"{item.un_number} CLASS {item.dg_class}"
                       if item.is_dangerous and item.un_number else ""),
        } for item in shipment.cargos],
        "컨테이너": (f"{cargo.container_quantity} x {cargo.container_type}"
                    if cargo and cargo.container_quantity else ""),
        "물류비_총액_원": shipment.total_cost_krw,
        "물류비_설명": cost.get("lines", []),
        "수출자부담_원": cost.get("exporter_cost_krw"),
        "지연_설명": exception.get("lines", []),
        "납기": exception.get("deadline"),
        "자금흐름_설명": flow.get("lines", []),
        "확인해야_할_수출요건": requirements,
        # 목록이 비었을 때 "없다"가 아니라 "못 찾았다"임을 AI가 알아야 합니다.
        "요건조회_상태": status,
        "요건조회_못한_것": limits,
        "요건목록_읽는_법": ("이 목록은 우리가 찾은 것입니다. 비어 있어도 '요건이 없다'는 뜻이 "
                            "아닙니다. HS부호가 정확하지 않거나 기관 조회가 막히면 빠집니다."),
        "B_L번호": shipment.bl_no or "",
        "수출신고번호": shipment.export_declaration_no or "",
    }


def ai_answer(shipment, question: str) -> dict:
    """AI가 이 건의 계산 결과를 보고 답합니다.

    키가 없거나 호출이 실패하면 예전의 규칙 기반 답으로 돌아갑니다.
    그래야 키가 없어도 화면이 죽지 않습니다.
    """

    import json

    from app.collectors import ai_client

    text = (question or "").strip()
    if not text:
        raise ValidationError("질문을 입력해주세요.", "question")

    if not ai_client.available():
        fallback = answer_question(shipment, text)
        fallback["note"] = ("AI 상담 키(AI_API_KEY)가 없어 규칙 기반으로 답했습니다. "
                            ".env에 키를 넣으면 자유롭게 물어볼 수 있습니다.")
        return fallback

    result = ai_client.chat([
        {"role": "system", "content": AI_SYSTEM_PROMPT},
        {"role": "system", "content": "이 건의 자료입니다.\n"
                                      + json.dumps(ai_context(shipment), ensure_ascii=False,
                                                   default=str)},
        {"role": "user", "content": text[:1000]},
    ])
    if not result["success"]:
        fallback = answer_question(shipment, text)
        fallback["note"] = f"AI 답변을 받지 못해 규칙 기반으로 답했습니다. ({result['message']})"
        return fallback

    return {"intent": None, "title": "답변", "source": "ai", "actions": [],
            "lines": [line.strip() for line in result["data"].splitlines() if line.strip()]}
