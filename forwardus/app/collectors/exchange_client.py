"""환율 제공자.

관세청 UNI-PASS "관세환율정보조회" API를 우선 사용하고, 키가 없거나 호출이
실패하면 data/mock/exchange_rates.json 값을 씁니다. 관세환율은 수출입 신고
가격 산정에 쓰는 고시 환율이라 통관·과세 계산에 적합합니다.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date

from app.collectors.base_client import fail, get_config, load_mock, ok, request_text

UNIPASS_FX_URL = "https://unipass.customs.go.kr:38010/ext/rest/trifFxrtInfoQry/retrieveTrifFxrtInfo"
# imexTp: 1 = 수출, 2 = 수입. 수출 신고가격 환산에는 수출 환율을 씁니다.
EXPORT_RATE_TYPE = "1"
SUPPORTED_CURRENCIES = ("USD", "EUR", "JPY", "CNY")
# 관세환율은 100단위로 고시되는 통화가 있습니다. (예: JPY 100엔)
UNIT_100_CURRENCIES = {"JPY"}


def _unipass_key() -> str:
    return (get_config("UNIPASS_API_KEYS", {}) or {}).get("CUSTOMS_EXCHANGE_RATE", "")


def fetch_unipass_rates(query_date: date | None = None) -> dict:
    """관세청 고시 환율(KRW per 1 unit)을 조회합니다."""

    key = _unipass_key()
    if not key:
        return fail("API_AUTH_FAILED", "api", "관세환율 API 키(UNIPASS_KEY_CUSTOMS_EXCHANGE_RATE)가 없습니다.")

    params = {
        "crkyCn": key,
        "qryYymmDd": (query_date or date.today()).strftime("%Y%m%d"),
        "imexTp": EXPORT_RATE_TYPE,
    }
    result = request_text("GET", UNIPASS_FX_URL, params=params)
    if not result["success"]:
        return result

    raw = result["data"]
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return fail("API_INVALID_RESPONSE", "api")

    rates = {"KRW": 1.0}
    for row in root.iter("trifFxrtInfoQryRsltVo"):
        currency = (row.findtext("currSgn") or "").strip().upper()
        value = (row.findtext("fxrt") or "").strip()
        if currency not in SUPPORTED_CURRENCIES or not value:
            continue
        try:
            rate = float(value)
        except ValueError:
            continue
        rates[currency] = rate / 100 if currency in UNIT_100_CURRENCIES else rate

    if "USD" not in rates:
        return fail("API_MISSING_FIELD", "api", "관세환율 응답에 USD 환율이 없습니다.")
    return ok(rates, "api")


def fetch_krw_rates() -> dict:
    """통화별 원화 환율. 관세청 API를 먼저 쓰고, 실패하면 Mock 값을 씁니다."""

    result = fetch_unipass_rates()
    if result["success"]:
        return result

    rates = dict(load_mock("exchange_rates")["krw_per_unit"])
    rates["USD"] = float(get_config("EXCHANGE_RATE_USD_KRW", rates["USD"]))
    rates["KRW"] = 1.0
    return ok(rates, "mock")


def convert(amount: float, from_currency: str, to_currency: str, rates: dict) -> float:
    return amount * rates[from_currency] / rates[to_currency]
