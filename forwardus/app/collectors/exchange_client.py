"""환율 제공자.

관세청 UNI-PASS "관세환율정보조회"를 먼저 씁니다. 관세환율은 수출입 신고
가격 산정에 쓰는 고시 환율이라 통관·과세 계산에 적합합니다.

관세청이 막혔을 때 곧장 예시 환율로 내려가지 않습니다. 예시 환율(USD 1,380 ·
통화 4개)로 견적이 나가면 그 숫자가 맞는지 화면만 봐서는 알 수 없기 때문입니다.
차례는 이렇습니다.

    1. 관세청 고시 관세환율
    2. 시장 환율 (Open Exchange Rates) — 고시환율은 아니지만 실제 값
    3. 저장해 둔 지난 실환율 — 서버를 다시 켜도 남아 있습니다
    4. 예시 고정 환율 — 여기까지 와야만 씁니다

1·2로 받아 낸 값은 파일로 남겨 두었다가 3에서 씁니다.
무엇으로 환산했는지는 rate_basis()가 한 줄로 알려 줍니다.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import date
from time import monotonic

from app.collectors import file_cache
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


# 받아 둔 것을 잠시 기억해 둡니다.
#
# 관세환율은 하루에 한 번 고시되는데, 화면을 열 때마다 관세청에 물어보고
# 있었습니다. 기관이 멈추면 연결이 끊길 때까지(8초) 기다리고, 한 화면에서
# 두 번 물어보니 열 때마다 16초가 걸렸습니다. 운송 계획 화면이 그랬습니다.
#
# 실패도 잠깐 기억합니다. 안 되는 곳을 매번 8초씩 다시 두드릴 이유가 없습니다.
_CACHE: dict[str, tuple[float, object]] = {}
LIVE_TTL = 3_600       # 고시환율은 하루 한 번 바뀝니다.
FAILED_TTL = 60        # 기관이 멈췄을 때 다시 두드리기까지.


def clear_cache() -> None:
    """기억해 둔 것을 버립니다. (테스트에서 씁니다)"""

    _CACHE.clear()


def _remember(key: str, make):
    """make()는 (값, 살려 둘 초)를 돌려줍니다."""

    now = monotonic()
    found = _CACHE.get(key)
    if found and now < found[0]:
        return found[1]
    value, ttl = make()
    _CACHE[key] = (now + ttl, value)
    return value


# 출처마다 화면에 뭐라고 적을지. 한 곳에서 정합니다. 쓰는 곳이 제각각 판단하면
# 같은 환율을 어디서는 "고시환율", 어디서는 "임시 환율"이라고 부르게 됩니다.
RATE_SOURCES = {
    "api": "관세청 고시환율",
    "market": "시장 환율 (고시환율을 받지 못해 실제 시장 환율로 환산)",
    "stored": "지난번에 받아 둔 환율",
    "mock": "예시 고정 환율 — 실제 거래에 쓰지 마세요",
}


# --- 받아 온 환율 표를 거릅니다 ------------------------------------------------------
#
# 왜 필요한가
#   환율은 견적 금액에 **그대로 곱해집니다.** 기관이 자릿수를 하나 틀리거나
#   응답 모양이 바뀌면 견적이 통째로 틀립니다. 그런데 받아 온 표를 아무 검사
#   없이 쓰고 있었습니다. 넣어 본 값이 전부 그대로 통과했습니다.
#     USD 1.3805  (1,000배 작음 — 달러 기준 표를 잘못 읽은 모양)
#     USD -1380.5 · USD "1380.5"(글자) · USD None
#     KRW 1000    (원화가 1이 아니면 모든 환산이 1,000배 틀립니다)
#     빈 표       (success 는 참인데 값이 없음)
#   이런 값이 오면 **그 출처를 실패로 보고 다음 단계로 내려갑니다.** 끝까지 가면
#   예시 환율이 나오는데, 예시는 화면에 "실제 거래에 쓰지 마세요"라고 적힙니다.
#   틀린 숫자를 진짜처럼 보여 주는 것보다 낫습니다. (2026-09-26)

# 달러가 이 밖이면 그 표는 믿지 않습니다. 원/달러는 1997년에도 2,000원 아래였고
# 1990년대에도 700원 위였습니다. 넉넉히 잡아도 이 밖은 자릿수 실수입니다.
USD_KRW_BAND = (300.0, 5_000.0)
# 통화 하나가 이 밖이면 그 통화만 버립니다. 가장 싼 통화(VND 약 0.055원)와
# 가장 비싼 통화(KWD 약 4,500원)를 넉넉히 감쌉니다.
RATE_BAND = (0.01, 100_000.0)


def sound_rates(rates) -> dict | None:
    """쓸 수 있는 환율만 남깁니다. 표 자체를 못 믿겠으면 None."""

    if not isinstance(rates, dict):
        return None
    kept = {}
    for code, value in rates.items():
        code = str(code or "").upper()
        if code == "KRW" or not is_currency_code(code):
            continue
        # bool 은 int 의 자식이라 따로 막습니다. True 가 1.0원이 되면 곤란합니다.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        value = float(value)
        if not RATE_BAND[0] <= value <= RATE_BAND[1]:
            continue
        kept[code] = value
    usd = kept.get("USD")
    if usd is None or not USD_KRW_BAND[0] <= usd <= USD_KRW_BAND[1]:
        return None
    # 원화는 언제나 1입니다. 받아 온 표가 뭐라고 하든 여기서 못 박습니다.
    kept["KRW"] = 1.0
    return kept


def rate_is_real(result: dict) -> bool:
    """지어낸 값이 아닌지. 예시 고정 환율만 거짓입니다."""

    return result.get("source") in ("api", "market", "stored")


def rate_basis(result: dict) -> str:
    """"무슨 환율로 환산했는지"를 화면에 적을 한 줄."""

    source = result.get("source") or "mock"
    label = RATE_SOURCES.get(source, RATE_SOURCES["mock"])
    applied = result.get("applied_date") or ""
    if source == "stored":
        days = result.get("stored_days")
        when = f"{applied} 기준" if applied else f"{result.get('saved_date', '')} 저장"
        ago = f" · {days}일 지난 값" if isinstance(days, int) and days > 0 else ""
        return f"{label} ({when}{ago}). 최신 환율을 받지 못했습니다."
    return f"{label}{f' · {applied} 적용' if applied else ''}"


def fetch_krw_rates() -> dict:
    """통화별 원화 환율. 관세청 고시 환율을 쓰고, 못 받으면 고정 환율로 버팁니다."""

    return _remember("rates", _read_krw_rates)


# 마지막으로 **진짜** 받아 낸 환율을 디스크에 남겨 둡니다.
#
# 왜 필요한가
#   관세청이 막히면 지금까지는 곧장 예시 환율(USD 1,380 · 통화 4개)로 내려갔습니다.
#   그 값으로 견적이 나가고, 화면에는 그냥 숫자로 보입니다. 서버를 다시 켜면
#   기억해 둔 것도 사라져 또 예시로 갑니다.
#   실제로 받아 낸 환율은 며칠 지났어도 예시보다 훨씬 정확합니다. 그러니 남깁니다.
LAST_GOOD_FILE = "krw_rates_last_good"
# 저장해 둔 환율을 이 날수까지만 씁니다. 그 뒤로는 너무 옛날 값이라
# 예시와 다를 바 없어, 며칠 지난 값이라고 분명히 말해 줍니다.
STORED_MAX_DAYS = 30


def _save_last_good(rates: dict, applied_date: str, origin: str) -> None:
    """받아 낸 환율을 파일로 남깁니다. 실패해도 조회를 멈추지 않습니다."""

    file_cache.write(LAST_GOOD_FILE, {
        "krw_per_unit": {code: value for code, value in rates.items() if value},
        "applied_date": applied_date,
        "origin": origin,
        "saved_date": date.today().isoformat(),
    })


def _last_good() -> dict | None:
    """저장해 둔 환율. 없거나 너무 오래됐으면 None."""

    found = file_cache.read(LAST_GOOD_FILE)
    if not found:
        return None
    data, age_days = found
    rates = (data or {}).get("krw_per_unit") or {}
    if not rates.get("USD") or age_days > STORED_MAX_DAYS:
        return None
    rates = dict(rates)
    rates["KRW"] = 1.0
    return {**ok(rates, "stored"),
            "applied_date": data.get("applied_date") or "",
            "saved_date": data.get("saved_date") or "",
            "stored_days": round(age_days),
            "origin": data.get("origin") or ""}


def _from_open_exchange_rates() -> dict | None:
    """시장 환율(달러 기준)을 원화 기준으로 바꿔 씁니다.

    관세환율과 쓰임이 다릅니다. 신고가격 환산에 쓰는 고시 환율이 아니라
    시장 환율이라, 이 값을 쓸 때는 화면에 그렇다고 적어야 합니다.
    다만 예시 고정 환율보다는 비교할 수 없이 정확합니다.
    """

    app_id = get_config("OPEN_EXCHANGE_RATES_APP_ID", "")
    if not app_id:
        return None

    result = request_text("GET", "https://openexchangerates.org/api/latest.json",
                          timeout=15, params={"app_id": app_id})
    body = None
    if result["success"]:
        try:
            body = json.loads(result["data"])
        except ValueError:
            body = None
    if not isinstance(body, dict) or body.get("error") or not (body.get("rates") or {}).get("KRW"):
        # 받지 못했으면 fx 시세표가 받아 둔 파일이라도 씁니다.
        found = file_cache.read("fx_oxr_latest")
        body = found[0] if found else None
    per_usd = (body or {}).get("rates") or {}
    krw = per_usd.get("KRW")
    if not krw:
        return None

    # per_usd[code] = 1달러당 그 통화 몇 단위. 원화 환산은 KRW ÷ 그 값입니다.
    # 기준이 달러이므로 1달러는 곧 KRW 값 그대로입니다. (응답이 USD를 적어 주든 말든)
    rates = {"KRW": 1.0, "USD": float(krw)}
    for code, value in per_usd.items():
        code = code.upper()
        if code in ("KRW", "USD") or not value or not is_currency_code(code):
            continue
        rates[code] = krw / value
    stamp = body.get("timestamp")
    applied = (date.fromtimestamp(int(stamp)).isoformat() if stamp else date.today().isoformat())
    return {**ok(rates, "market"), "applied_date": applied}


def _read_krw_rates() -> tuple[dict, float]:
    """받는 곳을 차례로 내려갑니다. 예시 환율은 **맨 마지막**입니다.

      1. 관세청 고시 관세환율   — 신고가격 환산에 맞는 값
      2. 시장 환율(OXR)        — 고시환율은 아니지만 실제 값
      3. 저장해 둔 지난 실환율   — 며칠 지났어도 예시보다 정확
      4. 예시 고정 환율         — 여기까지 오면 화면에 경고가 떠야 합니다
    """

    result = fetch_unipass_rates()
    sound = sound_rates(result["data"]) if result["success"] else None
    if sound:
        _save_last_good(sound, result.get("applied_date", ""), "customs")
        return {**result, "data": sound}, LIVE_TTL

    market = _from_open_exchange_rates()
    sound = sound_rates(market["data"]) if market else None
    if sound:
        _save_last_good(sound, market.get("applied_date", ""), "market")
        return {**market, "data": sound}, LIVE_TTL

    stored = _last_good()
    sound = sound_rates(stored["data"]) if stored else None
    if sound:
        return {**stored, "data": sound}, FAILED_TTL

    rates = dict(load_mock("exchange_rates")["krw_per_unit"])
    rates["USD"] = float(get_config("EXCHANGE_RATE_USD_KRW", rates["USD"]))
    # 설정으로 넣은 값도 거릅니다. 오타 하나로 견적이 1,000배 틀립니다.
    rates = sound_rates(rates) or {**load_mock("exchange_rates")["krw_per_unit"], "KRW": 1.0}
    # 예시 환율로 답하는 동안에도 기관이 살아났는지 이따금 다시 봅니다.
    return {**ok(rates, "mock"), "applied_date": ""}, FAILED_TTL


def currency_options() -> list[dict]:
    """통화를 고르는 칸에 넣을 목록. **바깥을 부르지 않습니다.**

    고를 수 있는 통화가 무엇인지는 거의 바뀌지 않습니다. 그런데 이걸
    관세청에 물어보느라 화면이 통째로 기다리고 있었습니다. 기관이 막히면
    운송 계획 화면 한 번 여는 데 16초가 걸렸습니다.

    실제 환산에 쓰는 환율은 fetch_krw_rates()로 따로 받습니다. 그쪽은
    숫자가 맞아야 하니 기관을 부르는 것이 맞습니다.
    """

    order = {code: index for index, code in enumerate(MAJOR_CURRENCIES)}
    codes = sorted(FALLBACK_CURRENCY_NAMES,
                   key=lambda code: (order.get(code, len(order)), code))
    return [{"code": code, "name": FALLBACK_CURRENCY_NAMES[code],
             "major": code in MAJOR_CURRENCIES} for code in codes]


def list_currencies() -> list[dict]:
    """관세청이 실제로 고시한 통화 목록. 기관을 부릅니다.

    화면의 고르는 칸에는 currency_options()를 쓰세요.
    """

    names = fetch_currency_names()
    codes = sorted(set(fetch_krw_rates()["data"]) | set(MAJOR_CURRENCIES))
    order = {code: index for index, code in enumerate(MAJOR_CURRENCIES)}
    codes.sort(key=lambda code: (order.get(code, len(order)), code))
    return [{"code": code, "name": names.get(code, code),
             "major": code in MAJOR_CURRENCIES} for code in codes]


def fetch_currency_names() -> dict[str, str]:
    """통화 코드 -> 이름. 관세청 응답의 통화 단위명을 씁니다."""

    return _remember("names", _read_currency_names)


def _read_currency_names() -> tuple[dict, float]:
    names = _fetch_currency_names_now()
    # 기관에서 받아온 이름이면 오래 두고, 우리 기본 이름이면 잠깐만 둡니다.
    return names, (FAILED_TTL if names == FALLBACK_CURRENCY_NAMES else LIVE_TTL)


def _fetch_currency_names_now() -> dict[str, str]:
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


def convert(amount: float, from_currency: str, to_currency: str, rates: dict):
    """환산합니다. 환율표에 없는 통화면 **None**입니다. (지어내지 않습니다)

    예전에는 없는 통화를 물으면 KeyError로 터졌습니다. 화면에서 고를 수 있는
    통화는 어느 단계의 환율표에도 다 들어 있어 실제로는 안 터졌지만,
    저장해 둔 환율이 잘린 채로 돌아오면 그대로 500이 났습니다.
    모르면 모른다고 하는 편이 낫습니다. (2026-09-26)
    """

    one = rates.get(str(from_currency or "").upper())
    other = rates.get(str(to_currency or "").upper())
    if not one or not other:
        return None
    return amount * one / other
