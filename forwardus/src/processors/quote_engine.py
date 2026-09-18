"""Detailed Forwardus quote calculation engine."""

from __future__ import annotations

import math
from collections import defaultdict

from src.collectors.mock_data import EXCHANGE_RATE, HS_CODES, SCHEDULES
from src.processors.cargo_calc import calculate_cargo_metrics, parse_positive_number


class QuoteValidationError(ValueError):
    """Raised when quote options are inconsistent or incomplete."""


VALID_MODES = {"fcl", "lcl", "air"}
VALID_DIRECTIONS = {"export", "import"}
AIR_INVALID_INCOTERMS = {"FOB", "CFR", "CIF"}


def _find_schedule(mode: str, schedule_id: str) -> dict:
    for schedule in SCHEDULES[mode]:
        if schedule["id"] == schedule_id:
            return schedule
    return SCHEDULES[mode][0]


def _find_duty_rate(hs_code: str) -> float:
    for item in HS_CODES:
        if item["code"] == hs_code:
            return float(item.get("fta_rate", item["mfn_rate"])) / 100
    return 0.0


def calculate_insurance_premium(
    declared_value_usd: float,
    freight_usd: float,
    exchange_rate: float,
    insurance_rate: float = 0.0035,
) -> float:
    """Calculate CIF 110 percent cargo insurance premium in KRW."""

    denominator = 1 - (1.1 * insurance_rate)
    if denominator <= 0:
        raise QuoteValidationError("보험요율을 확인해주세요.")
    insurance_value = (declared_value_usd + freight_usd) / denominator
    premium_krw = insurance_value * 1.1 * insurance_rate * exchange_rate
    return max(10_000, premium_krw)


def _make_item(category: str, code: str, name: str, currency: str, amount: float, exchange_rate: float, source: str) -> dict:
    krw_amount = amount if currency == "KRW" else amount * exchange_rate
    return {
        "category": category,
        "code": code,
        "name": name,
        "original_currency": currency,
        "original_amount": round(amount, 2),
        "krw_amount": round(krw_amount),
        "source": source,
        "is_imputed": source == "imputed",
    }


def build_quote(payload: dict) -> dict:
    """Build a detailed quote using normalized mock and calculated data."""

    mode = str(payload.get("transport_mode", "fcl")).lower()
    direction = str(payload.get("trade_direction", "export")).lower()
    incoterm = str(payload.get("incoterm", "FOB")).upper()
    if mode not in VALID_MODES:
        raise QuoteValidationError("지원하지 않는 운송 방식입니다.")
    if direction not in VALID_DIRECTIONS:
        raise QuoteValidationError("수출입 구분을 확인해주세요.")
    if mode == "air" and incoterm in AIR_INVALID_INCOTERMS:
        raise QuoteValidationError("항공 운송에는 FOB, CFR, CIF를 사용할 수 없습니다.")

    cargo_payload = payload.get("cargo") or {}
    metrics = calculate_cargo_metrics(cargo_payload)
    declared_value_usd = parse_positive_number(
        cargo_payload.get("declared_value_usd"), "신고가격", allow_zero=True
    )
    exchange_rate = float(EXCHANGE_RATE["rate"])
    schedule = _find_schedule(mode, str(payload.get("schedule_id", "")))
    freight_usd = float(schedule["freight_usd"])
    insurance_enabled = bool(payload.get("insurance_enabled")) or incoterm in {"CIF", "CIP"}
    duty_rate = _find_duty_rate(str(payload.get("hs_code", "3304.99")))

    origin_trucking = 190_000 if mode == "air" else 260_000
    warehouse = 98_000 if mode == "fcl" else 135_000
    terminal = 125_000 if mode == "air" else 210_000 if mode == "fcl" else 168_000
    destination_terminal = 145_000 if mode == "air" else 230_000
    documentation = 45_000 if mode == "air" else 65_000
    insurance_krw = (
        calculate_insurance_premium(declared_value_usd, freight_usd, exchange_rate)
        if insurance_enabled
        else 0
    )
    taxable_value_krw = (declared_value_usd + freight_usd) * exchange_rate
    duty_krw = taxable_value_krw * duty_rate

    items = [
        _make_item("출발지 비용", "origin_trucking", "출발지 내륙운송료", "KRW", origin_trucking, exchange_rate, "mock"),
        _make_item("출발지 비용", "export_customs", "수출 통관 수수료", "KRW", 55_000, exchange_rate, "mock"),
        _make_item("출발지 비용", "warehouse", "창고 임대료·보관료", "KRW", warehouse, exchange_rate, "imputed"),
        _make_item("서류·행정", "documentation", "AWB·서류 발행 비용" if mode == "air" else "B/L·서류 발행 비용", "KRW", documentation, exchange_rate, "mock"),
        _make_item("국제 운송", "freight", "항공운임" if mode == "air" else "해상운임", "USD", freight_usd, exchange_rate, "mock"),
        _make_item("국제 운송", "terminal", "선적지 터미널 처리 비용", "KRW", terminal, exchange_rate, "mock"),
        _make_item("보험", "insurance", "적하보험료", "KRW", insurance_krw, exchange_rate, "calculated"),
        _make_item("도착지 비용", "destination_terminal", "도착지 터미널 비용", "KRW", destination_terminal, exchange_rate, "mock"),
        _make_item("수입 통관·세금", "import_customs", "수입 통관 수수료", "KRW", 82_000, exchange_rate, "mock"),
        _make_item("수입 통관·세금", "duty", "관세", "KRW", duty_krw, exchange_rate, "calculated"),
        _make_item("도착지 비용", "destination_delivery", "도착지 내륙배송", "KRW", 310_000, exchange_rate, "mock"),
    ]

    total_krw = round(sum(item["krw_amount"] for item in items))
    budget_krw = parse_positive_number(payload.get("budget_krw", 0), "화주 예산", allow_zero=True)
    budget_gap = round(budget_krw - total_krw)
    budget_rate = (total_krw / budget_krw * 100) if budget_krw > 0 else 0
    seller_share = {"EXW": 0.22, "FCA": 0.30, "FOB": 0.45, "CFR": 0.62, "CIF": 0.68, "CPT": 0.62, "CIP": 0.70, "DAP": 0.86, "DDP": 1.0}.get(incoterm, 0.68)

    category_totals: dict[str, float] = defaultdict(float)
    for item in items:
        category_totals[item["category"]] += item["krw_amount"]

    return {
        "metrics": metrics,
        "items": items,
        "category_totals": [
            {"name": name, "value": round(value)} for name, value in category_totals.items()
        ],
        "total_krw": total_krw,
        "seller_cost_krw": round(total_krw * seller_share),
        "budget_gap_krw": budget_gap,
        "budget_rate": round(budget_rate, 1),
        "exchange_rate": exchange_rate,
        "schedule": schedule,
        "insurance_krw": round(insurance_krw),
        "duty_krw": round(duty_krw),
        "data_source": "mock",
    }

