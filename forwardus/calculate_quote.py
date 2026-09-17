"""견적 산출 엔진: 비용 라인 산출 · 인코텀즈 부담 배분 · KPI 시나리오."""

from dataclasses import dataclass, field, replace
import math

import config
from format_values import CURRENCY_SYMBOLS, format_krw_compact, format_number, format_rate_percent, round_half_up
from preprocess_data import find_rate_record


@dataclass(frozen=True)
class QuoteInputs:
    """사용자 입력 조건 (사이드바 위젯 키와 1:1 대응)."""

    origin_port: str = "KRPUS"
    dest_country: str = "US"
    transport_mode: str = "FCL"
    container_type: str = "20GP"
    box_length_cm: int = 60
    box_width_cm: int = 40
    box_height_cm: int = 40
    box_count: int = 120
    box_weight_kg: int = 18
    cargo_value_usd: int = 38000
    incoterms: str = "CIF"
    insurance_enabled: bool = True
    hs_code: str = "3304.99"
    fta_applied: bool = True
    export_filing: str = "broker"
    extra_duty_rate: float = 0.0
    budget_krw: int = 3_500_000


DEFAULT_INPUTS = QuoteInputs()


@dataclass
class QuoteLine:
    """견적 명세서 한 줄 (원통화 금액·원화 환산액·부담 주체 포함)."""

    line_id: str
    segment: str
    category: str
    name: str
    basis: str
    currency: str
    amount: float
    is_na: bool = False
    imputed_note: str = ""
    amount_krw: float = 0.0
    payer: str = "buyer"


@dataclass
class QuoteResult:
    """견적 산출 결과."""

    inputs: QuoteInputs
    rule: dict
    mode: str
    origin_code: str
    origin_name: str
    dest: dict
    dest_place_name: str
    cargo: dict
    rate_record: dict
    unit: str
    container_count: int
    transit_days: int
    transit_imputed: bool
    customs: dict
    lines: list = field(default_factory=list)
    totals: dict = field(default_factory=dict)
    category_totals: dict = field(default_factory=dict)
    segment_totals: list = field(default_factory=list)

    def find_line(self, line_id: str) -> QuoteLine:
        """식별자에 해당하는 명세서 라인 반환."""
        return next(line for line in self.lines if line.line_id == line_id)


def convert_to_krw(amount: float, currency: str) -> float:
    """원통화 금액을 기준일 매매기준율로 원화 환산."""
    return amount * config.FX_RATES[currency]


def normalize_incoterms(incoterms: str, transport_mode: str) -> str:
    """항공 운송 시 해상 전용 조건(FOB·CFR·CIF)을 복합운송 조건(FCA·CPT·CIP)으로 전환."""
    if transport_mode == "AIR" and config.INCOTERMS_RULES[incoterms]["sea_only"]:
        return config.SEA_TO_ANY_MODE_TERMS[incoterms]
    return incoterms


def get_mode_label(mode: str, container_type: str) -> str:
    """운송 모드 표시명 반환 (FCL은 규격 포함)."""
    if mode == "FCL":
        return f"FCL {container_type}"
    return "LCL" if mode == "LCL" else "항공"


def calculate_tiered_cost(tier: tuple[float, float], total_cbm: float, base_cbm: float) -> float:
    """기본료 + 기준 부피 초과분 가산 방식의 비용 산출."""
    base_fee, extra_fee_per_cbm = tier
    return base_fee + max(0.0, total_cbm - base_cbm) * extra_fee_per_cbm


def calculate_cargo_metrics(inputs: QuoteInputs) -> dict:
    """총 부피·중량, 운임톤(R/T), 청구중량, 규격별 컨테이너 수·적재율 산출."""
    box_cbm = (inputs.box_length_cm * inputs.box_width_cm * inputs.box_height_cm) / 1_000_000
    total_cbm = round_half_up(box_cbm * inputs.box_count, 3)
    total_weight_kg = inputs.box_weight_kg * inputs.box_count
    revenue_ton = max(total_cbm, total_weight_kg / 1000)
    volumetric_weight_kg = total_cbm * config.VOLUMETRIC_KG_PER_CBM
    container_plan = {}
    for container_type in config.CONTAINER_TYPES:
        spec = config.CONTAINER_SPECS[container_type]
        container_count = max(1, math.ceil(total_cbm / spec["usable_cbm"]), math.ceil(total_weight_kg / spec["payload_kg"]))
        container_plan[container_type] = {
            "container_count": container_count,
            "cbm_utilization": total_cbm / (spec["usable_cbm"] * container_count),
            "weight_utilization": total_weight_kg / (spec["payload_kg"] * container_count),
        }
    return {
        "total_cbm": total_cbm,
        "total_weight_kg": total_weight_kg,
        "revenue_ton": revenue_ton,
        "billable_revenue_ton": round_half_up(max(revenue_ton, config.LCL_MIN_REVENUE_TON), 2),
        "volumetric_weight_kg": volumetric_weight_kg,
        "chargeable_weight_kg": math.ceil(max(total_weight_kg, volumetric_weight_kg) * 2) / 2,
        "container_plan": container_plan,
    }


def calculate_quote(raw_inputs: QuoteInputs) -> QuoteResult:
    """입력 조건 기준 Door-to-Door 견적 산출 및 인코텀즈 부담 주체 배분."""
    incoterms = normalize_incoterms(raw_inputs.incoterms, raw_inputs.transport_mode)
    rule = config.INCOTERMS_RULES[incoterms]
    inputs = replace(raw_inputs, incoterms=incoterms, insurance_enabled=rule["insurance_required"] or raw_inputs.insurance_enabled)

    mode = inputs.transport_mode
    is_air = mode == "AIR"
    origin_code = "ICN" if is_air else inputs.origin_port
    origin_name = config.ORIGIN_PORTS[origin_code]["name"]
    dest = config.DESTINATIONS[inputs.dest_country]
    dest_place_name = f"{dest['airport_name']} 공항" if is_air else f"{dest['port_name']}항"
    dest_charges = config.DEST_CHARGES[inputs.dest_country]
    local_currency = dest["local_currency"]
    local_symbol = CURRENCY_SYMBOLS[local_currency]
    cargo = calculate_cargo_metrics(inputs)
    unit = inputs.container_type if mode == "FCL" else ("RT" if mode == "LCL" else "KG")
    rate_record = find_rate_record(origin_code, inputs.dest_country, mode, unit)
    container_count = cargo["container_plan"][inputs.container_type]["container_count"] if mode == "FCL" else 0
    revenue_ton = cargo["billable_revenue_ton"]
    chargeable_kg = cargo["chargeable_weight_kg"]
    origin_charges = config.ORIGIN_CHARGES
    lines: list[QuoteLine] = []

    def add_line(**line_values) -> None:
        line = QuoteLine(**line_values)
        line.amount_krw = convert_to_krw(line.amount, line.currency)
        lines.append(line)

    # 수출지 비용: 내륙운송 · 수출통관 · 터미널/서류
    if mode == "FCL":
        inland_fee = origin_charges["fcl_inland"][origin_code][inputs.container_type]
        add_line(line_id="origin_inland", segment="origin_inland", category="local", name="내륙운송", currency="KRW", amount=inland_fee * container_count,
                 basis=f"수도권 → {origin_name} · {format_number(inland_fee)}원 × {container_count}대")
    else:
        inland_tier = origin_charges["small_inland"][origin_code]
        add_line(line_id="origin_inland", segment="origin_inland", category="local", name="내륙운송", currency="KRW",
                 amount=calculate_tiered_cost(inland_tier, cargo["total_cbm"], origin_charges["small_inland_base_cbm"]),
                 basis=f"수도권 → {origin_name} · 기본 {format_number(inland_tier[0])}원 + 3 CBM 초과 × {format_number(inland_tier[1])}원")
    uses_broker_filing = inputs.export_filing == "broker"
    add_line(line_id="export_clearance", segment="export_clearance", category="local", name="수출통관 수수료", currency="KRW",
             amount=config.BROKER_FEES["export_filing"] if uses_broker_filing else 0,
             basis="관세사 신고 대행 1건" if uses_broker_filing else "UNI-PASS 자가 신고 (수수료 없음)")
    if mode == "FCL":
        thc_fee = origin_charges["fcl_thc"][inputs.container_type]
        add_line(line_id="origin_terminal", segment="origin_terminal", category="local", name="터미널·서류 비용", currency="KRW",
                 amount=(thc_fee + origin_charges["seal_fee"]) * container_count + origin_charges["bl_fee"],
                 basis=f"(THC {format_number(thc_fee)} + Seal {format_number(origin_charges['seal_fee'])}) × {container_count} + B/L {format_number(origin_charges['bl_fee'])}")
    elif mode == "LCL":
        add_line(line_id="origin_terminal", segment="origin_terminal", category="local", name="CFS·터미널·서류 비용", currency="KRW",
                 amount=origin_charges["lcl_cfs_thc_per_rt"] * revenue_ton + origin_charges["bl_fee"],
                 basis=f"CFS·THC {format_number(origin_charges['lcl_cfs_thc_per_rt'])}원 × {format_number(revenue_ton, 2)} R/T + B/L {format_number(origin_charges['bl_fee'])}원")
    else:
        terminal_fee = max(origin_charges["air_terminal_min"], origin_charges["air_terminal_per_kg"] * chargeable_kg)
        add_line(line_id="origin_terminal", segment="origin_terminal", category="local", name="공항 터미널·AWB", currency="KRW",
                 amount=terminal_fee + origin_charges["awb_fee"],
                 basis=f"터미널 {origin_charges['air_terminal_per_kg']}원 × {format_number(chargeable_kg, 1)} kg + AWB {format_number(origin_charges['awb_fee'])}원")

    # 국제 운송: 기본운임 · 할증료
    imputed_surcharge = next((item for item in rate_record["imputed_fields"] if item["field"] == "surcharge_usd"), None)
    if mode == "FCL":
        base_freight_usd = rate_record["base_usd"] * container_count
        surcharge_usd = rate_record["surcharge_usd"] * container_count
        base_basis = f"${format_number(rate_record['base_usd'])} × {inputs.container_type} {container_count}대"
        surcharge_basis = f"({rate_record['surcharge_label']}) × {container_count}대"
    elif mode == "LCL":
        base_freight_usd = rate_record["base_usd"] * revenue_ton
        surcharge_usd = rate_record["surcharge_usd"] * revenue_ton
        minimum_note = " (최소 1 R/T)" if cargo["revenue_ton"] < config.LCL_MIN_REVENUE_TON else ""
        base_basis = f"${format_number(rate_record['base_usd'], 1)} × {format_number(revenue_ton, 2)} R/T{minimum_note}"
        surcharge_basis = f"{rate_record['surcharge_label']} ${format_number(rate_record['surcharge_usd'], 1)} × {format_number(revenue_ton, 2)} R/T"
    else:
        raw_air_freight = rate_record["base_usd"] * chargeable_kg
        base_freight_usd = max(rate_record["min_charge_usd"], raw_air_freight)
        surcharge_usd = rate_record["surcharge_usd"] * chargeable_kg
        minimum_note = " (최저운임)" if raw_air_freight < rate_record["min_charge_usd"] else ""
        base_basis = f"${format_number(rate_record['base_usd'], 2)} × 청구중량 {format_number(chargeable_kg, 1)} kg{minimum_note}"
        surcharge_basis = f"({rate_record['surcharge_label']}) × {format_number(chargeable_kg, 1)} kg"
    add_line(line_id="base_freight", segment="main_carriage", category="freight", name="항공운임 (A/F)" if is_air else "해상운임 (O/F)",
             currency="USD", amount=base_freight_usd, basis=base_basis)
    add_line(line_id="surcharge", segment="main_carriage", category="freight", name="할증료", currency="USD", amount=surcharge_usd,
             basis=surcharge_basis, imputed_note=imputed_surcharge["method"] if imputed_surcharge else "")

    # 적하보험: CIF 가액의 110% 부보
    freight_total_usd = base_freight_usd + surcharge_usd
    insurance_rate = config.INSURANCE_RATES["AIR" if is_air else "SEA"][inputs.dest_country]
    coverage_factor = config.INSURANCE_COVERAGE_RATIO * insurance_rate
    fob_plus_freight_usd = inputs.cargo_value_usd + freight_total_usd
    premium_krw = convert_to_krw((fob_plus_freight_usd * coverage_factor) / (1 - coverage_factor), "USD")
    insurance_krw = max(config.INSURANCE_MIN_PREMIUM_KRW, premium_krw) if inputs.insurance_enabled else 0.0
    if inputs.insurance_enabled:
        required_note = f" · {incoterms} 의무" if rule["insurance_required"] else ""
        insurance_basis = f"(FOB + 운임) ${format_number(fob_plus_freight_usd)} × 110% × {format_rate_percent(insurance_rate)} · ICC(A){required_note}"
    else:
        insurance_basis = "미가입"
    add_line(line_id="insurance", segment="insurance", category="insurance", name="적하보험료", currency="KRW", amount=insurance_krw,
             is_na=not inputs.insurance_enabled, basis=insurance_basis)

    # 수입지 비용: 터미널/D·O · 수입통관 · 내륙배송
    if mode == "FCL":
        terminal_fee = dest_charges["fcl_terminal"][inputs.container_type]
        add_line(line_id="dest_terminal", segment="dest_terminal", category="local", name="도착지 터미널·D/O", currency=local_currency,
                 amount=terminal_fee * container_count + dest_charges["do_fee_sea"],
                 basis=f"터미널 {local_symbol}{terminal_fee} × {container_count} + D/O {local_symbol}{dest_charges['do_fee_sea']}")
    elif mode == "LCL":
        cfs_fee = max(dest_charges["lcl_cfs_min"], dest_charges["lcl_cfs_per_rt"] * revenue_ton)
        add_line(line_id="dest_terminal", segment="dest_terminal", category="local", name="도착지 CFS·D/O", currency=local_currency,
                 amount=cfs_fee + dest_charges["do_fee_sea"],
                 basis=f"CFS {local_symbol}{dest_charges['lcl_cfs_per_rt']} × {format_number(revenue_ton, 2)} R/T (최저 {local_symbol}{dest_charges['lcl_cfs_min']}) + D/O {local_symbol}{dest_charges['do_fee_sea']}")
    else:
        handling_fee = max(dest_charges["air_handling_min"], dest_charges["air_handling_per_kg"] * chargeable_kg)
        add_line(line_id="dest_terminal", segment="dest_terminal", category="local", name="도착 공항 핸들링·D/O", currency=local_currency,
                 amount=handling_fee + dest_charges["do_fee_air"],
                 basis=f"핸들링 {local_symbol}{dest_charges['air_handling_per_kg']} × {format_number(chargeable_kg, 1)} kg + D/O {local_symbol}{dest_charges['do_fee_air']}")
    isf_fee = 0 if is_air else dest_charges["isf_fee"]
    clearance_basis = f"통관 대행 {local_symbol}{dest_charges['clearance_fee']}"
    if isf_fee:
        clearance_basis += f" + ISF 신고 {local_symbol}{isf_fee}"
    add_line(line_id="import_clearance", segment="import_clearance", category="local", name="수입통관 수수료", currency=local_currency,
             amount=dest_charges["clearance_fee"] + isf_fee, basis=clearance_basis)
    if mode == "FCL":
        delivery_fee = dest_charges["fcl_inland"][inputs.container_type]
        add_line(line_id="dest_inland", segment="dest_inland", category="local", name="내륙배송", currency=local_currency,
                 amount=delivery_fee * container_count, basis=f"{dest_place_name} → 수입자 창고 · {local_symbol}{delivery_fee} × {container_count}대")
    else:
        delivery_tier = dest_charges["small_inland"]
        add_line(line_id="dest_inland", segment="dest_inland", category="local", name="내륙배송", currency=local_currency,
                 amount=calculate_tiered_cost(delivery_tier, cargo["total_cbm"], config.DEST_SMALL_INLAND_BASE_CBM),
                 basis=f"{dest_place_name} → 수입자 창고 · 기본 {local_symbol}{delivery_tier[0]} + 2 CBM 초과 × {local_symbol}{delivery_tier[1]}")

    # 제세: 관세 · 기타 수입제세 · 수입 부가세
    fob_krw = convert_to_krw(inputs.cargo_value_usd, "USD")
    cif_krw = fob_krw + convert_to_krw(freight_total_usd, "USD") + insurance_krw
    customs_value_krw = fob_krw if dest["customs_value_basis"] == "FOB" else cif_krw
    hs_item = config.HS_ITEMS[inputs.hs_code]
    mfn_rate = hs_item["mfn_rates"][inputs.dest_country]
    fta_rate = hs_item["fta_rates"][inputs.dest_country]
    applied_rate = fta_rate if inputs.fta_applied else mfn_rate
    extra_rate = max(0.0, inputs.extra_duty_rate) / 100
    duty_krw = customs_value_krw * (applied_rate + extra_rate)
    rate_text = f"{dest['fta_name']} {format_rate_percent(fta_rate)}" if inputs.fta_applied else f"기본세율 {format_rate_percent(mfn_rate)}"
    if extra_rate > 0:
        rate_text += f" + 추가 {format_rate_percent(extra_rate)}"
    add_line(line_id="duty", segment="import_clearance", category="tax", name="관세", currency=local_currency,
             amount=duty_krw / config.FX_RATES[local_currency],
             basis=f"과세가격({dest['customs_value_basis']}) {format_krw_compact(customs_value_krw)} × {rate_text}")
    if inputs.dest_country == "US":
        customs_value_usd = inputs.cargo_value_usd
        mpf_usd = 0.0 if inputs.fta_applied else min(config.US_MPF["max_usd"], max(config.US_MPF["min_usd"], customs_value_usd * config.US_MPF["rate"]))
        hmf_usd = 0.0 if is_air else customs_value_usd * config.US_HMF_RATE
        basis_parts = [] if is_air else [f"HMF 0.125% ${format_number(hmf_usd, 2)}"]
        basis_parts.append("MPF 면제 (FTA 원산지)" if inputs.fta_applied else f"MPF 0.3464% ${format_number(mpf_usd, 2)}")
        add_line(line_id="other_tax", segment="import_clearance", category="tax", name="기타 수입제세", currency="USD",
                 amount=mpf_usd + hmf_usd, basis=" + ".join(basis_parts))
    else:
        add_line(line_id="other_tax", segment="import_clearance", category="tax", name="기타 수입제세", currency=local_currency,
                 amount=0.0, is_na=True, basis="해당 없음")
    if dest["vat_rate"] > 0:
        add_line(line_id="vat", segment="import_clearance", category="tax", name="수입 부가세", currency=local_currency,
                 amount=((customs_value_krw + duty_krw) * dest["vat_rate"]) / config.FX_RATES[local_currency],
                 basis=f"(과세가격 + 관세) × {format_rate_percent(dest['vat_rate'])} · 매입세액 공제 대상")
    else:
        add_line(line_id="vat", segment="import_clearance", category="tax", name="수입 부가세", currency=local_currency,
                 amount=0.0, is_na=True, basis="수입 단계 부가세 없음")

    # 인코텀즈 부담 주체 배분 및 합계
    seller_segment_ids = set(rule["seller_segments"])
    for line in lines:
        line.payer = "seller" if line.segment in seller_segment_ids else "buyer"

    def sum_krw(predicate) -> float:
        return sum(line.amount_krw for line in lines if predicate(line))

    totals = {
        "logistics_krw": sum_krw(lambda line: line.category != "tax"),
        "tax_krw": sum_krw(lambda line: line.category == "tax"),
        "seller_krw": sum_krw(lambda line: line.payer == "seller"),
        "buyer_krw": sum_krw(lambda line: line.payer == "buyer"),
        "foreign_krw": sum_krw(lambda line: line.currency != "KRW"),
    }
    totals["total_krw"] = totals["logistics_krw"] + totals["tax_krw"]
    category_totals = {category_id: sum_krw(lambda line, category_id=category_id: line.category == category_id) for category_id in config.CATEGORY_META}
    segment_totals = [
        {
            **segment,
            "display_name": segment["air_name"] if is_air else segment["name"],
            "amount_krw": sum_krw(lambda line, segment_id=segment["id"]: line.segment == segment_id),
            "payer": "seller" if segment["id"] in seller_segment_ids else "buyer",
            "is_empty": all(line.is_na for line in lines if line.segment == segment["id"]),
        }
        for segment in config.SEGMENTS
    ]

    return QuoteResult(
        inputs=inputs, rule=rule, mode=mode, origin_code=origin_code, origin_name=origin_name, dest=dest,
        dest_place_name=dest_place_name, cargo=cargo, rate_record=rate_record, unit=unit, container_count=container_count,
        transit_days=int(rate_record["transit_days"]),
        transit_imputed=any(item["field"] == "transit_days" for item in rate_record["imputed_fields"]),
        customs={
            "customs_value_krw": customs_value_krw, "mfn_rate": mfn_rate, "fta_rate": fta_rate, "applied_rate": applied_rate,
            "duty_krw": duty_krw, "fta_saving_krw": customs_value_krw * max(0.0, mfn_rate - fta_rate),
        },
        lines=lines, totals=totals, category_totals=category_totals, segment_totals=segment_totals,
    )


def calculate_broker_saving(quote: QuoteResult) -> dict:
    """KPI 1: 관세사 의뢰 비용 대비 서비스 활용 시 절감액·절감률 산출."""
    uses_broker_filing = quote.inputs.export_filing == "broker"
    fees = config.BROKER_FEES
    rows = [
        {"항목": "HS 품목분류 사전 검토", "관세사 의뢰": fees["hs_review"], "Forwardus 활용": 0, "활용 방식": "HS·세율 자동 조회"},
        {"항목": "FTA 원산지·세율 검토", "관세사 의뢰": fees["fta_review"] if quote.inputs.fta_applied else 0, "Forwardus 활용": 0,
         "활용 방식": "협정세율 자동 적용" if quote.inputs.fta_applied else "FTA 미적용"},
        {"항목": "수출신고", "관세사 의뢰": fees["export_filing"], "Forwardus 활용": fees["export_filing"] if uses_broker_filing else 0,
         "활용 방식": "관세사 대행 유지" if uses_broker_filing else "UNI-PASS 자가 신고"},
    ]
    broker_total_krw = sum(row["관세사 의뢰"] for row in rows)
    service_total_krw = sum(row["Forwardus 활용"] for row in rows)
    saving_krw = broker_total_krw - service_total_krw
    return {
        "rows": rows,
        "broker_total_krw": broker_total_krw,
        "service_total_krw": service_total_krw,
        "saving_krw": saving_krw,
        "saving_rate": saving_krw / broker_total_krw if broker_total_krw else 0.0,
    }


def build_scenario_key(quote: QuoteResult) -> str:
    """시나리오 중복 판정 키 생성 (출발지·운송모드·규격·인코텀즈)."""
    container_type = quote.inputs.container_type if quote.mode == "FCL" else ""
    return "|".join((quote.origin_code, quote.mode, container_type, quote.inputs.incoterms))


def list_scenario_changes(base_quote: QuoteResult, next_quote: QuoteResult) -> list[str]:
    """현재 조건 대비 변경 항목 설명 목록 반환."""
    changes = []
    if base_quote.mode != next_quote.mode:
        changes.append(f"운송 {get_mode_label(base_quote.mode, base_quote.inputs.container_type)} → {get_mode_label(next_quote.mode, next_quote.inputs.container_type)}")
    elif next_quote.mode == "FCL" and base_quote.inputs.container_type != next_quote.inputs.container_type:
        changes.append(f"규격 {base_quote.inputs.container_type} → {next_quote.inputs.container_type}")
    if base_quote.mode != "AIR" and next_quote.mode != "AIR" and base_quote.origin_code != next_quote.origin_code:
        changes.append(f"출발항 {base_quote.origin_name} → {next_quote.origin_name}")
    if base_quote.inputs.incoterms != next_quote.inputs.incoterms:
        changes.append(f"인코텀즈 {base_quote.inputs.incoterms} → {next_quote.inputs.incoterms}")
    return changes


def choose_cheapest_container(inputs: QuoteInputs) -> QuoteResult:
    """FCL 규격 중 수출자 부담(동률 시 총액)이 가장 낮은 견적 반환."""
    best_quote = None
    for container_type in config.CONTAINER_TYPES:
        quote = calculate_quote(replace(inputs, transport_mode="FCL", container_type=container_type))
        if best_quote is None:
            best_quote = quote
            continue
        seller_gap = quote.totals["seller_krw"] - best_quote.totals["seller_krw"]
        if seller_gap < -1 or (abs(seller_gap) <= 1 and quote.totals["total_krw"] < best_quote.totals["total_krw"]):
            best_quote = quote
    return best_quote


def generate_budget_scenarios(current_quote: QuoteResult) -> list[dict]:
    """KPI 2: 출발항·운송모드·규격 변경안과 인코텀즈 협상안 생성."""
    base_inputs = current_quote.inputs
    seen_keys = {build_scenario_key(current_quote)}
    candidates = []

    def push_candidate(quote: QuoteResult, kind: str) -> None:
        scenario_key = build_scenario_key(quote)
        if scenario_key in seen_keys:
            return
        seen_keys.add(scenario_key)
        candidates.append({
            "quote": quote,
            "kind": kind,
            "changes": list_scenario_changes(current_quote, quote),
            "seller_krw": quote.totals["seller_krw"],
            "transit_delta": quote.transit_days - current_quote.transit_days,
        })

    for origin_port in config.SEA_ORIGIN_CODES:
        push_candidate(choose_cheapest_container(replace(base_inputs, origin_port=origin_port)), "operation")
        push_candidate(calculate_quote(replace(base_inputs, origin_port=origin_port, transport_mode="LCL")), "operation")
    push_candidate(calculate_quote(replace(base_inputs, transport_mode="AIR")), "operation")
    negotiation_map = config.NEGOTIATION_TERMS["AIR" if current_quote.mode == "AIR" else "SEA"]
    negotiated_term = negotiation_map.get(base_inputs.incoterms)
    if negotiated_term:
        push_candidate(calculate_quote(replace(base_inputs, incoterms=negotiated_term)), "negotiation")
    return candidates


def select_budget_recommendation(current_quote: QuoteResult, candidates: list[dict], budget_krw: float) -> dict:
    """예산 충족 여부 기준 추천안 선정 (운영 변경 우선 → 변경 수 최소 → 비용 최저)."""
    current_seller_krw = current_quote.totals["seller_krw"]
    by_cost = sorted(candidates, key=lambda candidate: candidate["seller_krw"])
    if current_seller_krw <= budget_krw:
        best_saving = next((candidate for candidate in by_cost if candidate["seller_krw"] < current_seller_krw - 1), None)
        return {"status": "within", "recommended": None, "best_saving": best_saving}
    within_budget = sorted(
        (candidate for candidate in candidates if candidate["seller_krw"] <= budget_krw),
        key=lambda candidate: (candidate["kind"] == "negotiation", len(candidate["changes"]), candidate["seller_krw"]),
    )
    if within_budget:
        return {"status": "adjusted", "recommended": within_budget[0]}
    return {"status": "infeasible", "recommended": None, "cheapest": by_cost[0] if by_cost else None}
