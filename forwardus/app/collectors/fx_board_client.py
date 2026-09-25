"""실시간 환율 시세표 — 사이드바 [💱 환율] 창이 씁니다.

모든 통화의 매매기준율(원화), 전일 대비 변동, 송금 받을 때(TTB)·보낼 때(TTS) 환율을
한 모양으로 돌려줍니다. 받는 곳은 셋이고, 앞의 것이 안 되면 다음 것을 씁니다.

1. 한국수출입은행 현재환율 API (EXCHANGE_API_KEY)
   은행 고시 TTB·TTS·매매기준율이 모두 옵니다. 영업일 11시쯤 고시되고, 주말·고시 전에는
   빈 목록이 오므로 가장 최근 영업일로 거슬러 찾습니다.
2. Open Exchange Rates (OPEN_EXCHANGE_RATES_APP_ID)
   170개 가까운 통화의 시장 환율(달러 기준)을 원화로 바꿔 매매기준율로 씁니다.
   **송금 환율(TTB·TTS)은 주지 않습니다.** 지어내지 않고 비워 두며, 화면이
   "매매기준율 ± 스프레드(기본 1%)" 추정으로 계산하고 그렇다고 밝힙니다.
3. 관세청 고시 관세환율 → 마지막엔 data/mock의 고정 환율. (둘 다 전일 대비는 없습니다)

금액 단위: 원화는 "그 통화 unit개당 몇 원"입니다. 수출입은행처럼 JPY·IDR은 100단위.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from time import monotonic

from app.collectors import exchange_client, file_cache
from app.collectors.base_client import fail, get_config, ok, request_text

KOREAEXIM_URLS = ("https://oapi.koreaexim.go.kr/site/program/financial/exchangeJSON",
                  "https://www.koreaexim.go.kr/site/program/financial/exchangeJSON")
OXR_LATEST = "https://openexchangerates.org/api/latest.json"
OXR_HISTORICAL = "https://openexchangerates.org/api/historical/{day}.json"
OXR_NAMES = "https://openexchangerates.org/api/currencies.json"

# 수출입은행이 100단위로 고시하는 통화. 다른 곳에서 받아도 같은 단위로 맞춥니다.
UNIT_100 = {"JPY", "IDR"}
# 법정통화가 아니거나 더는 쓰지 않는 코드. (X로 시작하는 금·SDR 등은 따로 거릅니다)
NOT_CURRENCIES = {"BTC", "CLF", "CNH", "MRO", "STD", "VEF", "CUC", "GGP", "IMP", "JEP", "SSP", "SLL"}
# 무역에 자주 쓰는 통화를 표 맨 위에 둡니다.
PINNED = ("USD", "EUR", "JPY", "CNY", "GBP", "HKD", "CAD", "AUD", "SGD", "VND", "MXN",
          "THB", "INR", "IDR", "AED", "CHF")
# 받는 곳의 호출 한도가 작습니다(OXR 무료 월 1,000회). 한 시간은 받아 둔 것을 씁니다.
LIVE_TTL = 3_600
FAILED_TTL = 60
DEFAULT_SPREAD_PCT = 1.0

_CACHE: dict[str, tuple[float, dict]] = {}


def clear_cache() -> None:
    _CACHE.clear()


def _number(text) -> float | None:
    try:
        return float(str(text).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _name(code: str, english: str = "") -> str:
    return exchange_client.FALLBACK_CURRENCY_NAMES.get(code) or english or code


def _order(rows: list[dict]) -> list[dict]:
    rank = {code: index for index, code in enumerate(PINNED)}
    return sorted(rows, key=lambda row: (rank.get(row["code"], len(rank)), row["code"]))


def _row(code: str, unit: int, deal: float, prev: float | None, *, name: str = "",
         name_en: str = "", ttb: float | None = None, tts: float | None = None) -> dict:
    change = round(deal - prev, 4) if prev else None
    return {
        "code": code, "unit": unit, "cur_unit": f"{code}({unit})" if unit != 1 else code,
        "name": name or _name(code, name_en), "name_en": name_en,
        "deal": round(deal, 4), "prev_deal": round(prev, 4) if prev else None,
        "change": change, "change_pct": round(change / prev * 100, 2) if prev else None,
        "ttb": round(ttb, 4) if ttb else None, "tts": round(tts, 4) if tts else None,
    }


# --- 1. 한국수출입은행 -----------------------------------------------------------------

def _koreaexim_day(key: str, day: date) -> list[dict] | None:
    """그날 고시 목록. 고시가 없는 날(주말·11시 전)은 [], 부르지 못하면 None."""

    for url in KOREAEXIM_URLS:
        result = request_text("GET", url, timeout=10, params={
            "authkey": key, "searchdate": day.strftime("%Y%m%d"), "data": "AP01"})
        if not result["success"]:
            continue
        try:
            rows = json.loads(result["data"])
        except ValueError:
            return None
        if not isinstance(rows, list):
            return None
        # result: 1 성공, 2 DATA 코드 오류, 3 인증키 오류, 4 일일 한도 초과
        if rows and any(str(row.get("result")) != "1" for row in rows if isinstance(row, dict)):
            return None
        return [row for row in rows if isinstance(row, dict)]
    return None


def _latest_koreaexim(key: str, start: date, skip: date | None = None) -> tuple[date, list] | None:
    for back in range(0, 8):
        day = start - timedelta(days=back)
        if skip and day >= skip:
            continue
        rows = _koreaexim_day(key, day)
        if rows is None:
            return None
        if rows:
            return day, rows
    return None


def from_koreaexim(today: date | None = None) -> dict:
    key = get_config("EXCHANGE_API_KEY", "")
    if not key:
        return fail("API_AUTH_FAILED", "koreaexim", "수출입은행 환율 키(EXCHANGE_API_KEY)가 없습니다.")
    today = today or date.today()
    latest = _latest_koreaexim(key, today)
    if not latest:
        return fail("API_ERROR", "koreaexim", "수출입은행 환율을 받지 못했습니다.")
    day, rows = latest
    before = _latest_koreaexim(key, day - timedelta(days=1))
    prev = {}
    for row in (before[1] if before else []):
        prev[str(row.get("cur_unit", "")).upper()] = _number(row.get("deal_bas_r"))

    out = []
    for row in rows:
        cur_unit = str(row.get("cur_unit", "")).upper()
        code = cur_unit[:3]
        if code == "KRW" or not exchange_client.is_currency_code(code):
            continue
        deal = _number(row.get("deal_bas_r"))
        if not deal:
            continue
        unit = 100 if "(100)" in cur_unit else 1
        out.append(_row(code, unit, deal, prev.get(cur_unit), name=str(row.get("cur_nm") or "").strip(),
                        ttb=_number(row.get("ttb")), tts=_number(row.get("tts"))))
    if not out:
        return fail("API_NO_DATA", "koreaexim", "수출입은행 환율 목록이 비어 있습니다.")
    return ok({
        "source": "koreaexim", "source_label": "한국수출입은행 현재환율",
        "as_of": day.isoformat(), "prev_date": before[0].isoformat() if before else "",
        "spread": "bank",
        "note": "은행 고시 환율입니다. 실제 거래 환율은 은행·우대율에 따라 다릅니다.",
        "rows": _order(out),
    }, "api")


# --- 2. Open Exchange Rates -------------------------------------------------------------

def _oxr(url: str, app_id: str, cache_name: str, max_age_days: float) -> dict | None:
    cached = file_cache.read(cache_name)
    if cached and cached[1] < max_age_days:
        return cached[0]
    params = {"app_id": app_id} if app_id else {}
    result = request_text("GET", url, timeout=15, params=params)
    if not result["success"]:
        return cached[0] if cached else None
    try:
        body = json.loads(result["data"])
    except ValueError:
        return cached[0] if cached else None
    if not isinstance(body, dict) or body.get("error"):
        return cached[0] if cached else None
    file_cache.write(cache_name, body)
    return body


def from_open_exchange_rates() -> dict:
    app_id = get_config("OPEN_EXCHANGE_RATES_APP_ID", "")
    if not app_id:
        return fail("API_AUTH_FAILED", "openexchangerates",
                    "Open Exchange Rates 키(OPEN_EXCHANGE_RATES_APP_ID)가 없습니다.")
    latest = _oxr(OXR_LATEST, app_id, "fx_oxr_latest", LIVE_TTL / 86_400)
    rates = (latest or {}).get("rates") or {}
    if not rates.get("KRW"):
        return fail("API_ERROR", "openexchangerates", "Open Exchange Rates 환율을 받지 못했습니다.")
    stamp = datetime.fromtimestamp(int(latest.get("timestamp") or 0), tz=timezone.utc)
    # 전일 대비: 하루 전(UTC) 마감 환율과 견줍니다.
    prev_day = (stamp - timedelta(days=1)).date()
    historical = _oxr(OXR_HISTORICAL.format(day=prev_day.isoformat()), app_id,
                      f"fx_oxr_{prev_day.isoformat()}", 30) or {}
    prev_rates = historical.get("rates") or {}
    names = _oxr(OXR_NAMES, "", "fx_oxr_names", 30) or {}

    krw, prev_krw = rates["KRW"], prev_rates.get("KRW")
    out = []
    for code, per_usd in rates.items():
        code = code.upper()
        if (code == "KRW" or code in NOT_CURRENCIES or not exchange_client.is_currency_code(code)
                or not per_usd):
            continue
        unit = 100 if code in UNIT_100 else 1
        deal = krw / per_usd * unit
        prev = (prev_krw / prev_rates[code] * unit) if prev_krw and prev_rates.get(code) else None
        out.append(_row(code, unit, deal, prev, name_en=str(names.get(code) or "")))
    kst = stamp.astimezone(timezone(timedelta(hours=9)))
    return ok({
        "source": "openexchangerates", "source_label": "Open Exchange Rates 실시간 시장 환율",
        "as_of": kst.strftime("%Y-%m-%d %H:%M"), "prev_date": prev_day.isoformat() if prev_rates else "",
        "spread": "estimate",
        "note": ("매매기준율은 시장 환율(달러 기준)을 원화로 환산한 값입니다. 송금 받을 때(TTB)·보낼 때(TTS) "
                 "환율은 이 곳에서 제공하지 않아, 매매기준율에 스프레드를 더하고 뺀 추정치로 계산합니다."),
        "rows": _order(out),
    }, "api")


# --- 3. 관세청 고시 환율 · 고정 환율 -------------------------------------------------------

def from_customs() -> dict:
    result = exchange_client.fetch_krw_rates()
    rates = result["data"]
    live = result["source"] == "api"
    # 고시환율이 아니어도 시장 환율·저장해 둔 환율은 실제 값입니다. 그것까지
    # "예시 고정 환율"이라 적으면 쓸 수 있는 값을 못 쓰게 만듭니다.
    real = exchange_client.rate_is_real(result)
    out = [_row(code, 100 if code in UNIT_100 else 1,
                value * (100 if code in UNIT_100 else 1), None)
           for code, value in rates.items() if code != "KRW" and value]
    return ok({
        "source": "customs" if live else result["source"],
        "source_label": ("관세청 고시 관세환율(주간)" if live
                         else exchange_client.RATE_SOURCES.get(result["source"], "예시 고정 환율")),
        "as_of": result.get("applied_date") or "", "prev_date": "", "spread": "estimate",
        "note": ("수출입 신고 가격 환산용 관세환율입니다. 전일 대비는 제공하지 않습니다." if live
                 else exchange_client.rate_basis(result)),
        "rows": _order(out),
    }, "api" if real else "mock")


def board() -> dict:
    """시세표 전체. 앞의 받는 곳이 안 되면 다음 곳으로 내려갑니다. (한 시간 기억)"""

    now = monotonic()
    found = _CACHE.get("board")
    if found and now < found[0]:
        return found[1]
    tried = []
    for source in (from_koreaexim, from_open_exchange_rates):
        result = source()
        if result["success"]:
            result["data"]["tried"] = tried
            result["data"]["default_spread_pct"] = DEFAULT_SPREAD_PCT
            _CACHE["board"] = (now + LIVE_TTL, result)
            return result
        tried.append(result["message"])
    result = from_customs()
    result["data"]["tried"] = tried
    result["data"]["default_spread_pct"] = DEFAULT_SPREAD_PCT
    _CACHE["board"] = (now + FAILED_TTL, result)
    return result
