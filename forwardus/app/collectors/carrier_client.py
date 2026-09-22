"""선사·항공사 실데이터.

세 곳에서 받아옵니다. 셋 다 키가 필요하고, 우리가 이미 가진 것과 따로 발급받아야
하는 것이 나뉘어 있어 `sources()`로 어느 것이 살아 있는지 알려줍니다.

1. 관세청 UNI-PASS 선박회사 등록부 (UNIPASS_KEY_SHIPPING_COMPANY_LIST/_DETAIL)
   한국에 등록된 선사의 공식 부호(B/L·수출신고서에 쓰는 그 부호)와 상호입니다.
   이미 키가 있어 바로 씁니다. 스케줄은 주지 않습니다.
2. HMM Port-to-Port Schedule (HMM_API_KEY)
   실제 항차·환적항·소요일을 줍니다. 시간당 300회 제한이 명세에 적혀 있어
   같은 구간을 반복 조회하지 않도록 캐시해서 씁니다.
3. 인천국제공항공사 화물기 정기운항 일정 (DATA_GO_KR_SERVICE_KEY)
   인천공항을 드나드는 화물기 시간표입니다. 공공데이터포털에서 무료로 받습니다.

셋 다 "운임"은 주지 않습니다. 운임은 계약 단가라 API로 공개되지 않습니다.
그래서 스케줄은 실데이터로 쓰되 운임은 추정값임을 따로 표시합니다.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime

from app.collectors.base_client import fail, get_config, ok, request_text

UNIPASS_BASE = "https://unipass.customs.go.kr:38010/ext/rest/{svc}/{op}"
SHIP_LIST = ("shipCoLstQry", "retrieveShipCoLst")
SHIP_DETAIL = ("shipCoBrkdQry", "retrieveShipCoBrkd")

HMM_URL = "https://apigw.hmm21.com/gateway/ptpSchedule/v1/port-to-port-schedule"
# 명세에 적힌 제한입니다. 한 번 받은 구간은 하루 동안 다시 부르지 않습니다.
HMM_CALLS_PER_HOUR = 300
HMM_MAX_WEEKS = 4

ICN_SCHEDULE_URL = "https://apis.data.go.kr/B551177/CgoFltSched/getCgoFltSched{direction}"


def _unipass_key(service: str) -> str:
    return (get_config("UNIPASS_API_KEYS", {}) or {}).get(service, "")


def sources() -> list[dict]:
    """어느 자료원이 지금 쓸 수 있는지. 화면에서 솔직하게 알리는 데 씁니다."""

    return [
        {"key": "unipass_carriers", "label": "관세청 선박회사 등록부",
         "gives": "선사 공식 부호·상호", "env": "UNIPASS_KEY_SHIPPING_COMPANY_LIST",
         "ready": bool(_unipass_key("SHIPPING_COMPANY_LIST"))},
        {"key": "hmm", "label": "HMM 항구간 스케줄",
         "gives": "해상 항차·환적·소요일", "env": "HMM_API_KEY",
         "ready": bool(get_config("HMM_API_KEY", "")),
         "signup": "https://apiportal.hmm21.com/signup"},
        {"key": "icn_cargo", "label": "인천공항 화물기 정기운항",
         "gives": "항공 화물편 시간표", "env": "DATA_GO_KR_SERVICE_KEY",
         "ready": bool(get_config("DATA_GO_KR_SERVICE_KEY", "")),
         "signup": "https://www.data.go.kr/data/15095086/openapi.do"},
    ]


# --- 1. 관세청 선박회사 등록부 ------------------------------------------------

def search_shipping_companies(name: str) -> dict:
    """등록된 선사를 한글 상호로 찾습니다. (영문 상호로는 조회되지 않습니다)"""

    query = (name or "").strip()
    if not query:
        return fail("VALIDATION_ERROR", "api", "선사명을 입력해주세요.")
    key = _unipass_key("SHIPPING_COMPANY_LIST")
    if not key:
        return fail("API_AUTH_FAILED", "api", "선박회사목록 API 키가 없습니다.")

    svc, op = SHIP_LIST
    result = request_text("GET", UNIPASS_BASE.format(svc=svc, op=op),
                          params={"crkyCn": key, "shipCoNm": query}, timeout=20)
    if not result["success"]:
        return result
    return ok(_parse_ship_rows(result["data"], "shipCoLstQryRsltVo"), "api")


def shipping_company(code: str) -> dict:
    """선사 부호(예: MAEU)로 등록 내역을 봅니다."""

    sign = (code or "").strip().upper()
    if not sign:
        return fail("VALIDATION_ERROR", "api", "선사부호를 입력해주세요.")
    key = _unipass_key("SHIPPING_COMPANY_DETAIL")
    if not key:
        return fail("API_AUTH_FAILED", "api", "선박회사내역 API 키가 없습니다.")

    svc, op = SHIP_DETAIL
    result = request_text("GET", UNIPASS_BASE.format(svc=svc, op=op),
                          params={"crkyCn": key, "shipCoSgn": sign}, timeout=20)
    if not result["success"]:
        return result
    try:
        root = ET.fromstring(result["data"])
    except ET.ParseError:
        return fail("API_INVALID_RESPONSE", "api")

    row = next(root.iter("shipCoBrkdQryRsltVo"), None)
    if row is None:
        return ok(None, "api")

    def text(tag: str) -> str:
        return (row.findtext(tag) or "").strip()

    # 목록과 상세는 주는 항목이 다릅니다. 상세는 국내 선박대리점 정보가 나옵니다.
    return ok({
        "code": sign,
        "agency_name": text("shipAgncNm"),
        "representative": text("rppnNm"),
        "business_no": text("brno"),
        "agency_address": text("agncAddr"),
        "head_office_address": text("hdofAddr"),
        "country": text("cntyNm"),
        "country_code": text("shipCoNat"),
        "registration_no": text("rgsrNo"),
        "registered_on": _iso_date_compact(text("rgsrDt")),
        "tel": text("telno"),
        "fax": text("faxNo"),
    }, "api")


def _parse_ship_rows(xml: str, tag: str) -> list[dict]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    rows = []
    for row in root.iter(tag):
        rows.append({
            "code": (row.findtext("shipCoSgn") or "").strip(),
            "english_name": (row.findtext("shipCoEnglNm") or "").strip(),
            "korean_name": (row.findtext("shipCoKoreNm") or "").strip(),
            "representative": (row.findtext("rppnNm") or "").strip(),
        })
    return [row for row in rows if row["code"]]


# --- 2. HMM 항구간 스케줄 -----------------------------------------------------

def fetch_hmm_schedules(origin_code: str, destination_code: str, departure: date,
                        weeks: int = HMM_MAX_WEEKS, direct_only: bool = False) -> dict:
    """UN/LOCODE 두 항구 사이의 실제 배선 일정.

    `weeks`는 출발일부터 몇 주치를 볼지이고 명세상 최대 4주입니다.
    """

    key = get_config("HMM_API_KEY", "")
    if not key:
        return fail("API_AUTH_FAILED", "api",
                    "HMM 스케줄 API 키(HMM_API_KEY)가 없습니다. apiportal.hmm21.com에서 발급합니다.")
    pol, pod = (origin_code or "").strip().upper(), (destination_code or "").strip().upper()
    if len(pol) != 5 or len(pod) != 5:
        return fail("VALIDATION_ERROR", "api", "항구는 UN/LOCODE 다섯 자리로 지정합니다.")

    result = request_text("POST", HMM_URL, headers={"x-Gateway-APIKey": key}, timeout=30, params={
        "fromLocationCode": pol, "toLocationCode": pod,
        # CY = 컨테이너 야적장 인수/인도. 항구에서 항구까지 기준입니다.
        "receiveTermCode": "CY", "deliveryTermCode": "CY",
        "periodDate": departure.strftime("%Y%m%d"),
        "weekTerm": max(1, min(weeks, HMM_MAX_WEEKS)),
        "webSort": "D",                                   # 출항일 순
        "webPriority": "D" if direct_only else "A",
    })
    if not result["success"]:
        return result
    try:
        payload = json.loads(result["data"])
    except ValueError:
        return fail("API_INVALID_RESPONSE", "api")
    return ok([_hmm_row(row) for row in (payload.get("resultData") or [])], "api")


def _hmm_row(row: dict) -> dict:
    """HMM 응답 한 줄을 우리 스케줄 모양으로 바꿉니다."""

    vessels = row.get("vessel") or []
    first = vessels[0] if vessels else {}
    transship = (row.get("transshipPortCode") or "").strip()
    return {
        # 슬롯 운항사는 제휴 선사일 수 있어 HMM으로 단정하지 않습니다.
        "carrier": (row.get("vesselOperatorName") or "").strip() or "HMM",
        "vessel_or_flight": (first.get("vesselName") or "").strip(),
        "voyage_no": (first.get("voyageNumber") or first.get("voyageNo") or "").strip(),
        "etd": _iso_date(row.get("departureDate")),
        "eta": _iso_date(row.get("arrivalDate")),
        "transit_days": row.get("totalTransitDay"),
        "direct": not transship,
        "transship_port": (row.get("transshipPortName") or "").strip(),
        "origin_code": (row.get("loadingPortCode") or "").strip(),
        "destination_code": (row.get("dischargePortCode") or "").strip(),
        "origin_terminal": (row.get("loadingTerminalName") or "").strip(),
        "destination_terminal": (row.get("dischargeTerminalName") or "").strip(),
        # 서류·화물 마감. 일반 화물보다 앞서 마감돼 일정을 잡을 때 중요합니다.
        "cargo_cutoff": _iso_datetime(row.get("cargoCutOffTime")),
        "source": "api",
    }


def _iso_date(value: str | None) -> str:
    return (value or "")[:10]


def _iso_datetime(value: str | None) -> str:
    text = (value or "").strip()
    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ""


# --- 3. 인천공항 화물기 정기운항 ---------------------------------------------

def fetch_icn_cargo_flights(airport_code: str = "", arrivals: bool = False) -> dict:
    """인천공항 화물기 시간표. `airport_code`는 상대 공항 IATA 부호입니다."""

    key = get_config("DATA_GO_KR_SERVICE_KEY", "")
    if not key:
        return fail("API_AUTH_FAILED", "api",
                    "공공데이터포털 키(DATA_GO_KR_SERVICE_KEY)가 없습니다."
                    " data.go.kr에서 인천국제공항공사 화물기 운항 일정을 신청합니다.")

    url = ICN_SCHEDULE_URL.format(direction="Arrivals" if arrivals else "Departures")
    params = {"serviceKey": key, "type": "json", "numOfRows": "300", "pageNo": "1", "lang": "K"}
    if airport_code:
        params["airport"] = airport_code.strip().upper()
    result = request_text("GET", url, params=params, timeout=30)
    if not result["success"]:
        return result
    try:
        payload = json.loads(result["data"])
    except ValueError:
        return fail("API_INVALID_RESPONSE", "api")

    body = (payload.get("response") or {}).get("body") or {}
    # 이 API는 items를 배열로 바로 줍니다. 다른 공공데이터 API처럼 items.item으로
    # 한 겹 더 싸서 오는 경우도 있어 둘 다 받습니다.
    rows = body.get("items") or []
    if isinstance(rows, dict):
        rows = rows.get("item") or []
    if isinstance(rows, dict):
        rows = [rows]
    return ok([_icn_row(row) for row in rows], "api")


DAY_KEYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY_LABELS = ("월", "화", "수", "목", "금", "토", "일")


def _icn_row(row: dict) -> dict:
    """정기 화물편 한 줄. 요일 표시(Y/N)를 실제 운항 요일로 바꿉니다."""

    days = [label for key, label in zip(DAY_KEYS, DAY_LABELS)
            if str(row.get(key, "")).strip().upper() == "Y"]
    time_text = re.sub(r"\D", "", str(row.get("st") or ""))[:4]
    return {
        "carrier": (row.get("airline") or "").strip(),
        "vessel_or_flight": (row.get("flightid") or "").strip(),
        "counterpart_airport": (row.get("airport") or "").strip(),
        "counterpart_code": (row.get("airportCode") or "").strip(),
        "scheduled_time": f"{time_text[:2]}:{time_text[2:]}" if len(time_text) == 4 else "",
        "days": days,
        "days_label": "·".join(days) if days else "",
        "valid_from": _iso_date_compact(row.get("firstdate")),
        "valid_to": _iso_date_compact(row.get("lastdate")),
        "season": (row.get("season") or "").strip(),
        "source": "api",
    }


def _iso_date_compact(value: str | None) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}" if len(digits) == 8 else ""
