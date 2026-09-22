"""물류비 산출.

부대비용(내륙운송·터미널 처리비·서류비·통관 수수료·도착지 비용)은 아래 표준단가
표에서 뽑습니다. 이 값들은 어디에도 API로 공개되지 않습니다. 포워더마다 계약
단가가 달라 실제 청구액은 견적서를 받아야 확정됩니다. 그래서 "Mock"(가짜)이
아니라 "표준단가"(tariff)로 표시해 추정값임을 분명히 합니다.

해상·항공 운임도 마찬가지로 계약 단가라 공개 API가 없습니다. 스케줄은 선사
API에서 실제로 받아 오지만 운임은 추정치입니다.

계산 자체는 모두 파이썬 코드가 하고, AI는 결과를 설명만 합니다.
"""

from __future__ import annotations

from collections import defaultdict

# Local charges in KRW by service key: (FCL per container, LCL, AIR).
LOCAL_CHARGES_KRW = {
    "origin_trucking": {"FCL": 260_000, "LCL": 180_000, "AIR": 150_000},
    "terminal_handling": {"FCL": 210_000, "LCL": 168_000, "AIR": 125_000},
    "destination_charge": {"FCL": 410_000, "LCL": 230_000, "AIR": 145_000},
}
DOCUMENTATION_FEE_KRW = {"SEA": 65_000, "AIR": 45_000}
EXPORT_CUSTOMS_FEE_KRW = 55_000
LCL_CFS_CHARGE_KRW_PER_RT = 18_000
INSURANCE_RATE = 0.0035
INSURANCE_MIN_KRW = 10_000

# Which party pays which cost group under each Incoterm (exporter-side view).
EXPORTER_PAYS = {
    "EXW": set(),
    "FCA": {"origin"},
    "FOB": {"origin"},
    "CFR": {"origin", "freight"},
    "CIF": {"origin", "freight", "insurance"},
    "CPT": {"origin", "freight"},
    "CIP": {"origin", "freight", "insurance"},
    "DAP": {"origin", "freight", "destination"},
    "DPU": {"origin", "freight", "destination"},
    "DDP": {"origin", "freight", "destination", "import"},
}

# Incoterms 2020 11개 규칙. E·F·C·D 그룹 순서이며, sea_only는 해상·내수로 전용입니다.
# detail은 처음 쓰는 분을 위한 풀이, caution은 자주 틀리는 부분입니다.
INCOTERMS_INFO = [
    {"code": "EXW", "name": "Ex Works", "label": "공장 인도", "group": "E",
     "risk": "판매자 사업장에서 인도 시", "seller_cost": "거의 없음",
     "detail": "판매자는 자기 공장·창고에서 물건을 내어 주기만 하면 끝납니다. "
               "트럭에 싣는 일, 수출통관, 운임, 보험까지 모두 Buyer가 합니다.",
     "caution": "수출신고가 Buyer 몫이라 외국 Buyer가 한국에서 직접 통관하기 어렵습니다. "
                "수출실적 인정도 받기 어려워, 실무에서는 FCA를 더 많이 씁니다."},
    {"code": "FCA", "name": "Free Carrier", "label": "운송인 인도", "group": "F",
     "risk": "지정 운송인에게 인도 시", "seller_cost": "수출통관·출발지 비용",
     "detail": "판매자가 수출통관까지 마치고, Buyer가 지정한 운송인에게 물건을 넘기면 책임이 끝납니다. "
               "인도 장소가 판매자 사업장이면 차에 싣는 것까지, 그 밖의 장소면 내려주지 않은 상태로 넘깁니다.",
     "caution": "컨테이너 화물에 가장 알맞은 조건입니다. 2020년부터 Buyer가 요청하면 "
                "선적선하증권(On-board B/L)을 발행받을 수 있게 합의할 수 있습니다."},
    {"code": "FAS", "name": "Free Alongside Ship", "label": "선측 인도", "group": "F",
     "risk": "선적항 부두 선측에 둔 때", "seller_cost": "수출통관·선측까지 운송", "sea_only": True,
     "detail": "판매자가 배 옆(부두 또는 부선)까지 물건을 가져다 두면 책임이 끝납니다. "
               "배에 싣는 비용과 이후 위험은 Buyer가 집니다.",
     "caution": "곡물·광석처럼 컨테이너에 넣지 않는 벌크 화물에 씁니다. 컨테이너 화물에는 맞지 않습니다."},
    {"code": "FOB", "name": "Free On Board", "label": "본선 인도", "group": "F",
     "risk": "본선에 적재된 때", "seller_cost": "수출통관·선적항 비용", "sea_only": True,
     "detail": "물건이 배에 실리는 순간 위험이 Buyer에게 넘어갑니다. "
               "거기까지의 비용과 수출통관은 판매자가 맡고, 해상운임과 보험은 Buyer가 부담합니다.",
     "caution": "컨테이너는 배에 싣기 며칠 전에 터미널에 반입하므로, 그 사이 사고의 책임이 "
                "애매해집니다. 컨테이너라면 FOB보다 FCA가 맞습니다."},
    {"code": "CFR", "name": "Cost and Freight", "label": "운임 포함", "group": "C",
     "risk": "본선에 적재된 때", "seller_cost": "+ 해상운임", "sea_only": True,
     "detail": "판매자가 목적항까지의 해상운임을 냅니다. 다만 위험은 출발항에서 배에 실린 때 "
               "이미 Buyer에게 넘어갑니다.",
     "caution": "비용이 넘어가는 지점(목적항)과 위험이 넘어가는 지점(출발항 본선)이 다릅니다. "
                "보험은 판매자 의무가 아니므로 Buyer가 따로 들어야 합니다."},
    {"code": "CIF", "name": "Cost, Insurance and Freight", "label": "운임·보험 포함", "group": "C",
     "risk": "본선에 적재된 때", "seller_cost": "+ 해상운임·보험", "sea_only": True,
     "detail": "CFR에 적하보험이 더해진 조건입니다. 판매자가 운임과 보험료를 내고, "
               "위험은 출발항에서 배에 실린 때 Buyer에게 넘어갑니다.",
     "caution": "판매자가 드는 보험은 최소담보(ICC C)면 충분합니다. 더 넓은 담보가 필요하면 "
                "계약서에 따로 적어야 합니다. 보험금액은 송장가액의 110%가 기본입니다."},
    {"code": "CPT", "name": "Carriage Paid To", "label": "운송비 지급", "group": "C",
     "risk": "첫 운송인에게 인도한 때", "seller_cost": "+ 국제운임",
     "detail": "판매자가 목적지까지의 운임을 냅니다. 위험은 첫 번째 운송인에게 넘긴 때 "
               "Buyer에게 이전됩니다. 항공·복합운송을 포함해 모든 운송수단에 쓸 수 있습니다.",
     "caution": "CFR의 전(全)운송수단 버전입니다. 보험은 판매자 의무가 아닙니다."},
    {"code": "CIP", "name": "Carriage and Insurance Paid To", "label": "운송비·보험 지급", "group": "C",
     "risk": "첫 운송인에게 인도한 때", "seller_cost": "+ 국제운임·보험",
     "detail": "CPT에 적하보험이 더해진 조건입니다. 항공운송에서 CIF 대신 쓰는 조건입니다.",
     "caution": "2020년부터 판매자가 최대담보(ICC A)로 보험을 들어야 합니다. "
                "최소담보면 되는 CIF와 다른 점입니다."},
    {"code": "DAP", "name": "Delivered At Place", "label": "도착지 인도", "group": "D",
     "risk": "지정 목적지에 도착해 양하 준비된 때", "seller_cost": "+ 도착지 운송",
     "detail": "판매자가 지정한 목적지까지 실어다 주고, 내리지 않은 상태로 Buyer에게 넘깁니다. "
               "짐을 내리는 일과 수입통관·관세는 Buyer가 맡습니다.",
     "caution": "수입통관이 늦어져 생기는 비용도 Buyer 몫입니다. 목적지 주소를 계약서에 "
                "정확히 적어야 분쟁이 없습니다."},
    {"code": "DPU", "name": "Delivered at Place Unloaded", "label": "도착지 양하 인도", "group": "D",
     "risk": "목적지에서 양하를 마친 때", "seller_cost": "+ 양하 비용",
     "detail": "판매자가 목적지까지 실어다 주고 짐을 내려주는 것까지 책임집니다. "
               "11개 조건 가운데 판매자가 양하 의무를 지는 유일한 조건입니다.",
     "caution": "2020년에 DAT(터미널 인도)를 대신해 생겼습니다. 터미널뿐 아니라 어떤 장소든 "
                "지정할 수 있고, 그곳에서 짐을 내릴 수 있는지 미리 확인해야 합니다."},
    {"code": "DDP", "name": "Delivered Duty Paid", "label": "관세 지급 인도", "group": "D",
     "risk": "수입통관을 마치고 인도한 때", "seller_cost": "모든 비용·관세",
     "detail": "판매자가 수입통관과 관세·부가세까지 모두 부담해 Buyer 문 앞까지 배달합니다. "
               "판매자 의무가 가장 큰 조건입니다.",
     "caution": "수입국에 사업자등록이 없으면 판매자가 수입신고를 못 하는 나라가 많습니다. "
                "관세·부가세를 견적에 반드시 넣어야 손해를 보지 않습니다."},
]


def calculate_insurance_premium(
    invoice_value_usd: float,
    freight_usd: float,
    exchange_rate: float,
    insurance_rate: float = INSURANCE_RATE,
) -> float:
    """Cargo insurance premium in KRW on CIF value × 110 %."""

    insured_value_usd = (invoice_value_usd + freight_usd) * 1.1
    return max(INSURANCE_MIN_KRW, insured_value_usd * insurance_rate * exchange_rate)


def _line(category: str, group: str, code: str, name: str, currency: str, amount: float, exchange_rate: float, source: str) -> dict:
    krw = amount if currency == "KRW" else amount * exchange_rate
    return {
        "category": category,
        "group": group,
        "code": code,
        "name": name,
        "original_currency": currency,
        "original_amount": round(amount, 2),
        "krw_amount": round(krw),
        "source": source,
    }


def calculate_logistics_cost(
    *,
    transport_mode: str,
    sea_mode: str | None,
    incoterms: str,
    freight_usd: float,
    freight_source: str,
    invoice_value_usd: float,
    metrics: dict,
    exchange_rate: float,
    exchange_source: str = "mock",
) -> dict:
    """Build an itemized logistics cost estimate in KRW."""

    service = "AIR" if transport_mode == "AIR" else (sea_mode or "FCL")
    containers = (metrics.get("container_quantity") or 1) if service == "FCL" else 1
    # 표준단가 표에서 뽑은 추정값. 실제 청구액은 포워더 견적으로 확정됩니다.
    rate_source = "tariff"

    lines = [
        _line("Origin Charge", "origin", "origin_trucking", "출발지 내륙운송", "KRW",
              LOCAL_CHARGES_KRW["origin_trucking"][service] * containers, exchange_rate, rate_source),
        _line("Origin Charge", "origin", "terminal_handling", "터미널 처리비(THC)", "KRW",
              LOCAL_CHARGES_KRW["terminal_handling"][service] * containers, exchange_rate, rate_source),
        _line("Origin Charge", "origin", "documentation", "AWB 발행비" if service == "AIR" else "B/L 발행비", "KRW",
              DOCUMENTATION_FEE_KRW["AIR" if service == "AIR" else "SEA"], exchange_rate, rate_source),
        _line("Customs", "origin", "export_customs", "수출통관 수수료", "KRW",
              EXPORT_CUSTOMS_FEE_KRW, exchange_rate, rate_source),
    ]
    if service == "LCL":
        lines.append(_line("Origin Charge", "origin", "cfs_charge", "CFS 작업료", "KRW",
                           LCL_CFS_CHARGE_KRW_PER_RT * metrics.get("billable_revenue_ton", 1), exchange_rate, "calculated"))

    lines.append(_line("Freight", "freight", "freight", "항공운임" if service == "AIR" else "해상운임", "USD",
                       freight_usd, exchange_rate, freight_source))

    insurance_krw = calculate_insurance_premium(invoice_value_usd, freight_usd, exchange_rate)
    lines.append(_line("Insurance", "insurance", "insurance", "적하보험료", "KRW", insurance_krw, exchange_rate, "calculated"))
    lines.append(_line("Destination Charge", "destination", "destination_charge", "도착지 비용(THC·D/O)", "KRW",
                       LOCAL_CHARGES_KRW["destination_charge"][service] * containers, exchange_rate, rate_source))

    exporter_groups = EXPORTER_PAYS.get(incoterms, set())
    for line in lines:
        line["payer"] = "exporter" if line["group"] in exporter_groups else "buyer"

    category_totals: dict[str, int] = defaultdict(int)
    for line in lines:
        category_totals[line["category"]] += line["krw_amount"]

    total = sum(line["krw_amount"] for line in lines)
    exporter_total = sum(line["krw_amount"] for line in lines if line["payer"] == "exporter")
    return {
        "lines": lines,
        "category_totals": dict(category_totals),
        "total_krw": total,
        "exporter_total_krw": exporter_total,
        "buyer_total_krw": total - exporter_total,
        "exchange_rate": exchange_rate,
        "exchange_source": exchange_source,
    }
