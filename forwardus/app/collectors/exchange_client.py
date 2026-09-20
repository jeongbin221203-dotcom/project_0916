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
# 관세청이 고시하는 통화를 모두 받습니다. 고시 대상이 아닌 통화는 신고가격
# 환산에 쓸 수 없으므로, 이 목록이 화면에 보여줄 통화 목록이 됩니다.
# 화면 위쪽에 먼저 보여줄 주요 결제 통화.
MAJOR_CURRENCIES = ("USD", "EUR", "JPY", "CNY", "KRW")
# 관세환율은 100단위로 고시되는 통화가 있습니다. (예: JPY 100엔)
UNIT_100_CURRENCIES = {"JPY"}
# 주요 통화의 한글 이름. 나머지는 관세청 응답의 영문 단위명을 그대로 씁니다.
FALLBACK_CURRENCY_NAMES = {
    "USD": "미국 달러", "EUR": "유로", "JPY": "일본 엔", "CNY": "중국 위안", "KRW": "대한민국 원",
    "HKD": "홍콩 달러", "TWD": "대만 달러", "SGD": "싱가포르 달러", "VND": "베트남 동",
    "THB": "태국 바트", "MYR": "말레이시아 링깃", "IDR": "인도네시아 루피아", "PHP": "필리핀 페소",
    "INR": "인도 루피", "AUD": "호주 달러", "NZD": "뉴질랜드 달러", "CAD": "캐나다 달러",
    "MXN": "멕시코 페소", "BRL": "브라질 헤알", "GBP": "영국 파운드", "CHF": "스위스 프랑",
    "SEK": "스웨덴 크로나", "NOK": "노르웨이 크로네", "DKK": "덴마크 크로네", "PLN": "폴란드 즈워티",
    "CZK": "체코 코루나", "HUF": "헝가리 포린트", "RON": "루마니아 레우", "TRY": "튀르키예 리라",
    "RUB": "러시아 루블", "AED": "아랍에미리트 디르함", "SAR": "사우디 리얄", "QAR": "카타르 리얄",
    "KWD": "쿠웨이트 디나르", "BHD": "바레인 디나르", "OMR": "오만 리알", "ILS": "이스라엘 셰켈",
    "ZAR": "남아프리카 란드", "EGP": "이집트 파운드", "KZT": "카자흐스탄 텡게",
    "UZS": "우즈베키스탄 숨", "PKR": "파키스탄 루피", "BDT": "방글라데시 타카",
    "LKR": "스리랑카 루피", "KHR": "캄보디아 리엘", "MMK": "미얀마 짯", "MNT": "몽골 투그릭",
}


def is_currency_code(code: str) -> bool:
    """실제 결제에 쓰는 통화인지 봅니다.

    ISO 4217에서 X로 시작하는 코드는 통화가 아닙니다. (XAU 금, XDR 특별인출권,
    XXX 통화 없음 등) 이런 코드는 송장 통화로 고를 수 없습니다.
    """

    return len(code) == 3 and code.isalpha() and not code.startswith("X")


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
    applied = ""
    for row in root.iter("trifFxrtInfoQryRsltVo"):
        currency = (row.findtext("currSgn") or "").strip().upper()
        value = (row.findtext("fxrt") or "").strip()
        if not is_currency_code(currency) or not value:
            continue
        try:
            rate = float(value)
        except ValueError:
            continue
        rates[currency] = rate / 100 if currency in UNIT_100_CURRENCIES else rate
        # 관세환율은 주 단위로 고시됩니다. 적용 시작일을 함께 보여줍니다.
        applied = applied or (row.findtext("aplyBgnDt") or "").strip()

    if "USD" not in rates:
        return fail("API_MISSING_FIELD", "api", "관세환율 응답에 USD 환율이 없습니다.")
    return {**ok(rates, "api"), "applied_date": _as_iso(applied)}


def _as_iso(yyyymmdd: str) -> str:
    return (f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
            if len(yyyymmdd) == 8 and yyyymmdd.isdigit() else "")


def fetch_krw_rates() -> dict:
    """통화별 원화 환율. 관세청 고시 환율을 쓰고, 못 받으면 고정 환율로 버팁니다."""

    result = fetch_unipass_rates()
    if result["success"]:
        return result

    rates = dict(load_mock("exchange_rates")["krw_per_unit"])
    rates["USD"] = float(get_config("EXCHANGE_RATE_USD_KRW", rates["USD"]))
    rates["KRW"] = 1.0
    return {**ok(rates, "mock"), "applied_date": ""}


def list_currencies() -> list[dict]:
    """화면에 보여줄 통화 목록. 관세청 고시 통화를 그대로 씁니다.

    주요 결제 통화를 먼저 두고, 나머지는 코드 알파벳순입니다.
    """

    names = fetch_currency_names()
    codes = sorted(set(fetch_krw_rates()["data"]) | set(MAJOR_CURRENCIES))
    order = {code: index for index, code in enumerate(MAJOR_CURRENCIES)}
    codes.sort(key=lambda code: (order.get(code, len(order)), code))
    return [{"code": code, "name": names.get(code, code),
             "major": code in MAJOR_CURRENCIES} for code in codes]


def fetch_currency_names() -> dict[str, str]:
    """통화 코드 -> 이름. 관세청 응답의 통화 단위명을 씁니다."""

    key = _unipass_key()
    if not key:
        return dict(FALLBACK_CURRENCY_NAMES)
    result = request_text("GET", UNIPASS_FX_URL, params={
        "crkyCn": key, "qryYymmDd": date.today().strftime("%Y%m%d"), "imexTp": EXPORT_RATE_TYPE})
    if not result["success"]:
        return dict(FALLBACK_CURRENCY_NAMES)
    try:
        root = ET.fromstring(result["data"])
    except ET.ParseError:
        return dict(FALLBACK_CURRENCY_NAMES)
    names = dict(FALLBACK_CURRENCY_NAMES)
    for row in root.iter("trifFxrtInfoQryRsltVo"):
        code = (row.findtext("currSgn") or "").strip().upper()
        name = (row.findtext("mtryUtNm") or "").strip()
        if is_currency_code(code):
            names.setdefault(code, name or code)
    return names


def convert(amount: float, from_currency: str, to_currency: str, rates: dict) -> float:
    return amount * rates[from_currency] / rates[to_currency]
