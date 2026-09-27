"""한국무역보험공사 수출결제정보 (공공데이터포털 15144259).

"그 나라 바이어들은 대금을 어떻게, 얼마나 늦게 주는가"를 봅니다. 한국 수출기업이
무역보험에 붙인 해외 거래처의 실제 결제 기록을 나라별로 모은 통계입니다.

    GET https://apis.data.go.kr/B552696/exportPayment/getPaymentInfo
        serviceKey  공공데이터포털 키 (DATA_GO_KR_SERVICE_KEY)
        ctryCd      나라 코드 — ISO가 아니라 무역보험공사 숫자 코드입니다. (미국 450)
                    빼면 전체 나라 합계가 옵니다. 비교 기준으로 씁니다.

돌아오는 것 (해마다 한 줄씩, 최근 5년)
    paymentTerms              결제방식 비중(%) — O/A(T/T 포함)·L/C·D/A·D/P·CAD·COD·NET
    averagePaymentPeriod      평균 결제기간(일)
    latePaymentRate           연체율(%)
    averagelatePaymentPeriod  평균 연체기간(일)
    paymentPeriod             결제기간 분포(%) — 30일 이내 … 120일 초과

나라 코드표는 공공데이터포털 첨부 파일을 data/mock/ksure_countries.json으로 굳혀 두었습니다.
"""

from __future__ import annotations

import json

from app.collectors import file_cache
from app.collectors.base_client import fail, get_config, load_mock, ok, request_text

URL = "https://apis.data.go.kr/B552696/exportPayment/getPaymentInfo"
# 한 해에 한 번 갱신되는 통계입니다. (lastUpdateDate 2026.01.01) 하루 동안은 받아 둔 것을 씁니다.
CACHE_DAYS = 1

SIGNUP = {
    "label": "공공데이터포털 · 한국무역보험공사_수출결제정보",
    "url": "https://www.data.go.kr/data/15144259/openapi.do",
    "how": "위 주소에서 [활용신청]을 누르면 같은 인증키(DATA_GO_KR_SERVICE_KEY)로 바로 쓸 수 있습니다.",
}

# 사람들이 흔히 부르는 이름 → 코드표의 이름. 코드표는 "아랍에미리트 연합"처럼 적혀 있습니다.
ALIASES = {
    "미국": "미국", "usa": "미국", "us": "미국", "america": "미국", "미합중국": "미국",
    "중국": "중국", "china": "중국", "cn": "중국", "일본": "일본", "japan": "일본", "jp": "일본",
    "베트남": "베트남", "vietnam": "베트남", "vn": "베트남",
    "uae": "아랍에미리트 연합", "아랍에미리트": "아랍에미리트 연합", "아랍에미레이트": "아랍에미리트 연합",
    "두바이": "아랍에미리트 연합", "영국": "영국", "uk": "영국", "독일": "독일", "germany": "독일",
    "대만": "대만", "taiwan": "대만", "홍콩": "홍콩", "hongkong": "홍콩", "hong kong": "홍콩",
    "인도": "인도", "india": "인도", "인니": "인도네시아", "indonesia": "인도네시아",
    "러시아": "러시아", "russia": "러시아", "멕시코": "멕시코", "mexico": "멕시코",
    "태국": "태국", "thailand": "태국", "필리핀": "필리핀", "philippines": "필리핀",
    "말레이시아": "말레이시아", "malaysia": "말레이시아", "싱가포르": "싱가포르", "singapore": "싱가포르",
    "호주": "오스트레일리아", "australia": "오스트레일리아", "캐나다": "캐나다", "canada": "캐나다",
    "사우디": "사우디아라비아", "saudi": "사우디아라비아", "브라질": "브라질", "brazil": "브라질",
    "프랑스": "프랑스", "france": "프랑스", "이탈리아": "이탈리아", "italy": "이탈리아",
    "스페인": "스페인", "spain": "스페인", "폴란드": "폴란드", "poland": "폴란드",
    "튀르키예": "터키", "turkey": "터키", "터키": "터키",
}


def available() -> bool:
    return bool(get_config("DATA_GO_KR_SERVICE_KEY", ""))


def _countries() -> dict[str, str]:
    try:
        return load_mock("ksure_countries").get("countries") or {}
    except (OSError, ValueError, AttributeError):
        return {}


def _plain(text: str) -> str:
    return "".join(str(text or "").lower().split())


def find_country(name: str) -> dict | None:
    """나라 이름으로 무역보험공사 코드를 찾습니다. {"name", "code"} 또는 None.

    정확히 같은 이름 → 흔히 부르는 이름 → 이름의 앞부분이 같은 것 하나 순서로 봅니다.
    ("아랍에미리트" → "아랍에미리트 연합") 여럿이 걸리면 짐작하지 않고 None입니다.
    """

    countries = _countries()
    text = str(name or "").strip()
    if not text or not countries:
        return None
    if text in countries:
        return {"name": text, "code": countries[text]}
    alias = ALIASES.get(_plain(text)) or ALIASES.get(text.lower())
    if alias and alias in countries:
        return {"name": alias, "code": countries[alias]}
    plain = _plain(text)
    exact = [key for key in countries if _plain(key) == plain]
    if len(exact) == 1:
        return {"name": exact[0], "code": countries[exact[0]]}
    # "미국령 사모아"가 "미국"에 걸리지 않게, 이름이 이 말로 시작하는 것만 봅니다.
    head = [key for key in countries if _plain(key).startswith(plain)
            and not any(word in key for word in ("령 ", "령", "(", "군도"))]
    if len(head) == 1:
        return {"name": head[0], "code": countries[head[0]]}
    return None


def _number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _series(rows) -> list[dict]:
    """[{YEAR, VALUE(, CNT)}] → 해 순서대로 [{year, value(, count)}]."""

    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        value = _number(row.get("VALUE"))
        if value is None:
            continue
        entry = {"year": str(row.get("YEAR") or ""), "value": value}
        count = _number(row.get("CNT"))
        if count is not None:
            entry["count"] = int(count)
        out.append(entry)
    return sorted(out, key=lambda entry: entry["year"])


def _groups(rows, key: str) -> list[dict]:
    """결제방식·결제기간처럼 코드마다 해별 값이 달린 것."""

    return [{"code": str(row.get("CODE") or ""), "name": str(row.get("CODE_NM") or ""),
             "series": _series(row.get(key))}
            for row in rows or [] if isinstance(row, dict)]


def parse(item: dict) -> dict:
    """응답의 item 하나를 우리 모양으로."""

    return {
        "last_update": str(item.get("lastUpdateDate") or ""),
        "years": [str(year) for year in item.get("yearList") or []],
        "payment_terms": _groups(item.get("paymentTerms"), "PAYMENT_TERMS"),
        "payment_period": _groups(item.get("paymentPeriod"), "PAYMENT_PERIOD"),
        "average_payment_days": _series(item.get("averagePaymentPeriod")),
        "late_payment_rate": _series(item.get("latePaymentRate")),
        "average_late_days": _series(item.get("averagelatePaymentPeriod")),
    }


def payment_info(country_code: str = "") -> dict:
    """나라 코드(무역보험공사 숫자)의 결제 통계. 코드를 비우면 전체 나라 합계."""

    key = get_config("DATA_GO_KR_SERVICE_KEY", "")
    if not key:
        return fail("API_AUTH_FAILED", "api",
                    "무역보험공사 수출결제정보 키(DATA_GO_KR_SERVICE_KEY)가 없습니다.")
    code = "".join(ch for ch in str(country_code or "") if ch.isdigit())
    cache_name = f"ksure_payment_{code or 'all'}"
    cached = file_cache.read(cache_name)
    if cached and cached[1] < CACHE_DAYS:
        return ok(cached[0], "api")

    params = {"serviceKey": key}
    if code:
        params["ctryCd"] = code
    result = request_text("GET", URL, timeout=20, params=params)
    if not result["success"]:
        if result["error_code"] == "API_AUTH_FAILED":
            return fail("API_NOT_SUBSCRIBED", "api",
                        f"무역보험공사 수출결제정보 API에 활용신청이 되어 있지 않습니다. {SIGNUP['how']}")
        # 받지 못하면 예전에 받아 둔 것이라도 씁니다. (한 해에 한 번 바뀌는 통계입니다)
        return ok(cached[0], "cache") if cached else result
    try:
        response = json.loads(result["data"])["response"]
        header = response.get("header") or {}
        if str(header.get("resultCode")) == "3":
            return fail("API_NO_DATA", "api", "이 나라의 결제 통계가 없습니다.")
        items = ((response.get("body") or {}).get("items") or {}).get("item")
    except (ValueError, KeyError, TypeError, AttributeError):
        return fail("API_INVALID_RESPONSE", "api")
    if isinstance(items, list):
        items = items[0] if items else None
    if not isinstance(items, dict):
        return fail("API_NO_DATA", "api", "이 나라의 결제 통계가 없습니다.")
    data = parse(items)
    file_cache.write(cache_name, data)
    return ok(data, "api")


def sources() -> dict:
    return {"key": "ksure_payment", "label": "한국무역보험공사 수출결제정보",
            "env": "DATA_GO_KR_SERVICE_KEY", "ready": available(), "signup": SIGNUP}
