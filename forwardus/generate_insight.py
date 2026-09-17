"""시사점 문장 · 예산 조정 코멘트 · LLM 요청 페이로드 생성 모듈.

문장은 Streamlit 마크다운으로 출력함. 굵게 표시(**) 구간은 숫자·문자로 끝나거나
뒤에 공백·문장부호가 오도록 구성하여 강조 해석 오류를 방지함.
"""

from dataclasses import replace

from calculate_quote import QuoteResult, calculate_quote, choose_cheapest_container, get_mode_label
from format_values import format_krw, format_number, format_percent, format_signed_percent

IMPUTED_FIELD_NAMES = {"base_usd": "기본운임", "surcharge_usd": "할증료", "transit_days": "운송기간"}


def attach_topic_particle(word: str) -> str:
    """한글 받침 유무에 따라 보조사(은/는)를 붙인 문자열 반환."""
    last_character = word[-1]
    if "가" <= last_character <= "힣" and (ord(last_character) - ord("가")) % 28:
        return f"{word}은"
    return f"{word}는"


def describe_quote_brief(quote: QuoteResult) -> str:
    """시나리오 요약 문자열 반환 (출발지 · 운송모드 · 인코텀즈)."""
    origin_text = "인천공항" if quote.mode == "AIR" else quote.origin_name
    return f"{origin_text} · {get_mode_label(quote.mode, quote.inputs.container_type)} · {quote.inputs.incoterms}"


def describe_transit_change(transit_delta: int) -> str:
    """운송기간 증감 설명 구절 반환 (변화 없으면 빈 문자열)."""
    if transit_delta > 0:
        return f", 운송기간은 {transit_delta}일 늘어납니다"
    if transit_delta < 0:
        return f", 운송기간은 {-transit_delta}일 줄어듭니다"
    return ""


def generate_insights(quote: QuoteResult, trend_stats: dict) -> list[str]:
    """운임 추이 · 인코텀즈 · 운송모드 · 환율 민감도 · 데이터 품질 시사점 문장 생성."""
    insights = []
    inputs = quote.inputs
    route_text = f"{quote.origin_name}→{quote.dest_place_name}"
    mode_text = get_mode_label(quote.mode, inputs.container_type)
    peak_note = "성수기 할증료(PSS) 반영으로 " if quote.mode != "AIR" and "PSS" in quote.rate_record["surcharge_label"] else ""
    qoq_direction = "높은" if trend_stats["qoq_change"] >= 0 else "낮은"
    yoy_direction = "높습니다" if trend_stats["yoy_change"] >= 0 else "낮습니다"
    insights.append(
        f"선택하신 **{route_text}** {mode_text} 항로는 {peak_note}국제운임이 {trend_stats['previous_quarter_label']} 평균보다 "
        f"**약 {format_percent(abs(trend_stats['qoq_change']))} {qoq_direction}** 상태이며, "
        f"전년 같은 달보다는 {format_percent(abs(trend_stats['yoy_change']))} {yoy_direction}."
    )

    is_air = quote.mode == "AIR"
    free_term = "FCA" if is_air else "FOB"
    insured_term = "CIP" if is_air else "CIF"
    current_term = inputs.incoterms
    seller_krw = quote.totals["seller_krw"]
    if "main_carriage" in quote.rule["seller_segments"]:
        free_quote = calculate_quote(replace(inputs, incoterms=free_term))
        reduction_krw = seller_krw - free_quote.totals["seller_krw"]
        reduction_ratio = reduction_krw / seller_krw if seller_krw else 0.0
        reduction_text = f"**{format_krw(reduction_krw)} ({format_percent(reduction_ratio)})**"
        if quote.rule["risk_boundary"] == 3:
            insights.append(
                f"현재 {current_term} 조건에서 수출자 부담은 **{format_krw(seller_krw)}**입니다. "
                f"{free_term}로 계약하면 부담이 {reduction_text} 줄고 운임 변동도 바이어가 떠안습니다. "
                f"다만 {free_term}와 {current_term}는 위험 이전 시점({quote.rule['risk_label']})이 같으므로, "
                "차이는 위험이 아니라 비용과 운임 변동을 누가 지느냐입니다."
            )
        else:
            insights.append(
                f"현재 {current_term} 조건은 수출자가 도착지까지 비용과 위험을 함께 지므로 부담이 **{format_krw(seller_krw)}**입니다. "
                f"{free_term}로 계약하면 {reduction_text} 줄어들고, 위험도 선적지에서 바이어에게 넘어갑니다."
            )
    else:
        insured_quote = calculate_quote(replace(inputs, incoterms=insured_term, insurance_enabled=True))
        increase_krw = insured_quote.totals["seller_krw"] - seller_krw
        closing_text = (
            "EXW는 수출신고 주체가 바이어라 계약서에 명시해야 합니다."
            if current_term == "EXW" else f"위험 이전 시점은 {current_term}와 같습니다."
        )
        insights.append(
            f"현재 {current_term} 조건은 국제운임을 바이어가 내므로 운임 변동({trend_stats['previous_quarter_label']} 대비 "
            f"{format_signed_percent(trend_stats['qoq_change'])})이 수출자 원가에 반영되지 않습니다. "
            f"{insured_term}로 제안하면 가격 경쟁력은 높일 수 있지만 수출자 부담이 **{format_krw(increase_krw)}** 늘어나며, {closing_text}"
        )

    logistics_krw = quote.totals["logistics_krw"]
    if quote.mode == "FCL":
        plan = quote.cargo["container_plan"][inputs.container_type]
        lcl_quote = calculate_quote(replace(inputs, transport_mode="LCL"))
        difference_krw = logistics_krw - lcl_quote.totals["logistics_krw"]
        utilization_text = f"**{format_percent(plan['cbm_utilization'], 0)}**"
        if difference_krw > 0:
            insights.append(
                f"컨테이너 부피 적재율이 {utilization_text} 수준이라 LCL로 바꾸면 물류비가 "
                f"**{format_krw(difference_krw)} ({format_percent(difference_krw / logistics_krw)})** 줄어듭니다. "
                f"대신 운송기간이 {lcl_quote.transit_days - quote.transit_days}일 늘어납니다."
            )
        else:
            insights.append(
                f"부피 적재율이 {utilization_text} 수준에서는 FCL이 LCL보다 물류비가 **{format_krw(-difference_krw)}** 적어 현재 운송 모드가 유리합니다."
            )
    elif quote.mode == "LCL":
        fcl_quote = choose_cheapest_container(replace(inputs, transport_mode="FCL"))
        difference_krw = logistics_krw - fcl_quote.totals["logistics_krw"]
        revenue_ton_text = f"**{format_number(quote.cargo['revenue_ton'], 2)} R/T**"
        if difference_krw > 0:
            insights.append(
                f"운임톤 {revenue_ton_text}에서는 FCL {fcl_quote.inputs.container_type}가 LCL보다 물류비가 **{format_krw(difference_krw)}** 적습니다. "
                "컨테이너를 단독으로 쓰면 CFS 작업과 혼재 대기도 줄어듭니다."
            )
        else:
            insights.append(
                f"운임톤 {revenue_ton_text}에서는 LCL이 FCL {fcl_quote.inputs.container_type}보다 물류비가 **{format_krw(-difference_krw)}** 적어 현재 운송 모드가 유리합니다."
            )
    else:
        sea_quotes = [calculate_quote(replace(inputs, transport_mode="LCL")), choose_cheapest_container(replace(inputs, transport_mode="FCL"))]
        sea_quote = min(sea_quotes, key=lambda candidate: candidate.totals["logistics_krw"])
        cost_ratio = logistics_krw / sea_quote.totals["logistics_krw"] if sea_quote.totals["logistics_krw"] else 0.0
        insights.append(
            f"항공 물류비는 해상 {get_mode_label(sea_quote.mode, sea_quote.inputs.container_type)}의 **{format_number(cost_ratio, 1)}배**입니다. "
            f"긴급 화물이 아니라면 해상으로 바꿔 **{format_krw(logistics_krw - sea_quote.totals['logistics_krw'])}** 줄일 수 있습니다"
            f"(운송기간 +{sea_quote.transit_days - quote.transit_days}일)."
        )

    total_krw = quote.totals["total_krw"]
    foreign_share = quote.totals["foreign_krw"] / total_krw if total_krw else 0.0
    insights.append(
        f"환율이 1% 오르면 원화 견적은 약 **{format_krw(quote.totals['foreign_krw'] * 0.01)}** 늘어납니다"
        f"(외화 표시 비용 비중 {format_percent(foreign_share, 0)})."
    )

    imputed_fields = quote.rate_record["imputed_fields"]
    if imputed_fields:
        imputed_text = "·".join(IMPUTED_FIELD_NAMES[item["field"]] for item in imputed_fields)
        insights.append(
            f"데이터 품질: 이 항로의 **{attach_topic_particle(imputed_text)}** 수집 누락으로 {imputed_fields[0]['method']} 값을 썼습니다."
        )
    return insights


def generate_budget_comment(quote: QuoteResult, candidates: list[dict], recommendation: dict) -> str:
    """KPI 2 예산 조정 코멘트 생성 (OpenAI 연동 전 규칙 기반 문장)."""
    budget_krw = quote.inputs.budget_krw
    seller_krw = quote.totals["seller_krw"]
    current_label = describe_quote_brief(quote)
    status = recommendation["status"]
    if status == "within":
        comment = f"현재 조건({current_label})의 수출자 부담은 {format_krw(seller_krw)}이며, 예산 안에서 **{format_krw(budget_krw - seller_krw)} 여유**가 있습니다."
        best_saving = recommendation.get("best_saving")
        if best_saving:
            comment += (
                f" 비용을 더 줄이려면 ‘{', '.join(best_saving['changes'])}’ 조건이 {format_krw(seller_krw - best_saving['seller_krw'])} 저렴합니다"
                f"{describe_transit_change(best_saving['transit_delta'])}."
            )
        return comment
    if status == "adjusted":
        recommended = recommendation["recommended"]
        transit_text = describe_transit_change(recommended["transit_delta"]) or ", 운송기간은 같습니다"
        comment = (
            f"현재 조건({current_label})은 예산을 **{format_krw(seller_krw - budget_krw)} 초과**합니다. "
            f"**‘{', '.join(recommended['changes'])}’** 조건으로 바꾸면 수출자 부담이 {format_krw(recommended['seller_krw'])} 수준으로 줄어 "
            f"예산 안(여유 {format_krw(budget_krw - recommended['seller_krw'])})에 들어오며{transit_text}."
        )
        negotiation = next(
            (candidate for candidate in candidates
             if candidate["kind"] == "negotiation" and candidate is not recommended and candidate["seller_krw"] <= budget_krw),
            None,
        )
        if negotiation:
            comment += (
                f" 바이어와 {negotiation['quote'].inputs.incoterms}로 다시 계약하는 안({format_krw(negotiation['seller_krw'])})도 있지만 "
                "판매가격 조정이 필요합니다."
            )
        return comment
    cheapest = recommendation.get("cheapest")
    cheapest_krw = cheapest["seller_krw"] if cheapest else seller_krw
    cheapest_label = ", ".join(cheapest["changes"]) if cheapest else "현재 조건"
    return (
        f"현재 조건과 대안 {len(candidates)}개 모두 예산을 넘습니다. 가장 저렴한 안은 **‘{cheapest_label}’** ({format_krw(cheapest_krw)})이며, "
        f"예산을 **{format_krw(cheapest_krw - budget_krw)} 이상** 늘리거나 판매가격에 물류비를 반영해야 합니다."
    )


def summarize_quote_for_payload(quote: QuoteResult) -> dict:
    """LLM 전달용 견적 요약 딕셔너리 생성."""
    pod_code = quote.dest["airport_code"] if quote.mode == "AIR" else quote.dest["port_code"]
    return {
        "route": f"{quote.origin_code}-{pod_code}",
        "mode": quote.mode,
        "container_type": quote.inputs.container_type if quote.mode == "FCL" else None,
        "incoterms": quote.inputs.incoterms,
        "seller_cost_krw": round(quote.totals["seller_krw"]),
        "total_cost_krw": round(quote.totals["total_krw"]),
        "transit_days": quote.transit_days,
    }


def build_llm_payload(quote: QuoteResult, candidates: list[dict], recommendation: dict) -> dict:
    """OpenAI 연동 시 전달할 요청 페이로드 생성 (금액 재계산 금지 규칙 포함)."""
    sorted_candidates = sorted(candidates, key=lambda candidate: candidate["seller_krw"])
    return {
        "task": "budget_fit_explanation",
        "locale": "ko-KR",
        "rules": ["금액은 제공된 값만 인용", "재계산·추정 금지", "변경 조건과 트레이드오프를 3문장 이내로 설명"],
        "budget_krw": quote.inputs.budget_krw,
        "current": summarize_quote_for_payload(quote),
        "candidates": [
            {**summarize_quote_for_payload(candidate["quote"]), "kind": candidate["kind"], "changes": candidate["changes"]}
            for candidate in sorted_candidates[:4]
        ],
        "rule_engine_decision": recommendation["status"],
    }
