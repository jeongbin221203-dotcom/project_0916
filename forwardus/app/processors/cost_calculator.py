"""Logistics cost breakdown calculation.

Tariff figures are prototype estimates (source = mock). The calculation itself
is deterministic Python logic; the AI assistant only explains the result.
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

INCOTERMS_INFO = [
    {"code": "EXW", "name": "Ex Works", "label": "공장 인도", "risk": "판매자 사업장에서 인도 시", "seller_cost": "거의 없음"},
    {"code": "FCA", "name": "Free Carrier", "label": "운송인 인도", "risk": "지정 운송인에게 인도 시", "seller_cost": "수출통관·출발지 비용"},
    {"code": "FOB", "name": "Free On Board", "label": "본선 인도", "risk": "본선 적재 시", "seller_cost": "수출통관·선적항 비용", "sea_only": True},
    {"code": "CFR", "name": "Cost and Freight", "label": "운임 포함", "risk": "본선 적재 시", "seller_cost": "+ 해상운임", "sea_only": True},
    {"code": "CIF", "name": "Cost, Insurance and Freight", "label": "운임·보험 포함", "risk": "본선 적재 시", "seller_cost": "+ 해상운임·보험", "sea_only": True},
    {"code": "CPT", "name": "Carriage Paid To", "label": "운송비 지급", "risk": "첫 운송인 인도 시", "seller_cost": "+ 국제운임"},
    {"code": "CIP", "name": "Carriage and Insurance Paid To", "label": "운송비·보험 지급", "risk": "첫 운송인 인도 시", "seller_cost": "+ 국제운임·보험"},
    {"code": "DAP", "name": "Delivered At Place", "label": "도착지 인도", "risk": "지정 목적지 도착 시", "seller_cost": "+ 도착지 운송"},
    {"code": "DPU", "name": "Delivered at Place Unloaded", "label": "도착지 양하 인도", "risk": "목적지 양하 완료 시", "seller_cost": "+ 양하 비용"},
    {"code": "DDP", "name": "Delivered Duty Paid", "label": "관세 지급 인도", "risk": "수입통관 후 인도 시", "seller_cost": "모든 비용·관세"},
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
    rate_source = "mock"

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
