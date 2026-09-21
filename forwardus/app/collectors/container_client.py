"""컨테이너·B/L 추적 (관세청 UNI-PASS).

세 가지를 씁니다. 셋 다 이미 키가 있습니다.

1. 화물통관 진행정보 (API001, CARGO_CLEARANCE_PROGRESS)
   화물관리번호나 B/L번호로 화물이 지금 어디까지 왔는지 봅니다.
   선박명·컨테이너번호·적재항·양륙항과 반출입 기록이 함께 옵니다.
   **한국으로 들어오는 화물(수입)** 기준입니다.

2. 컨테이너내역 (API020, CONTAINER_DETAIL)
   화물관리번호에 딸린 컨테이너 번호·규격·봉인번호를 줍니다.
   한 건에 컨테이너가 여러 개면 모두 나옵니다.

3. 수출신고번호별 수출이행내역 (API002, EXPORT_PERFORMANCE_BY_DECLARATION)
   **한국에서 나가는 화물(수출)** 쪽입니다. 수출신고번호나 B/L번호로
   실제로 배에 실렸는지(선적완료여부)와 출항일자, 그리고 적재의무기한을 줍니다.
   적재의무기한은 수출신고 수리일부터 30일이고, 넘기면 신고수리가 취소됩니다.

수출 화물의 해외 구간을 따라가는 것은 여기서 되지 않습니다. 그건 선사가
자기 시스템으로만 줍니다.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, datetime

from app.collectors.base_client import fail, get_config, ok, request_text

BASE = "https://unipass.customs.go.kr:38010/ext/rest/{svc}/{op}"

CARGO_PROGRESS = ("cargCsclPrgsInfoQry", "retrieveCargCsclPrgsInfo")
CONTAINER_DETAIL = ("cntrQryBrkdQry", "retrieveCntrQryBrkd")
EXPORT_PERFORMANCE = ("expDclrNoPrExpFfmnBrkdQry", "retrieveExpDclrNoPrExpFfmnBrkd")

# 컨테이너 번호는 영문 4자리 + 숫자 7자리입니다. (ISO 6346)
CONTAINER_NO = re.compile(r"^[A-Z]{4}\d{7}$")


def _key(service: str) -> str:
    return (get_config("UNIPASS_API_KEYS", {}) or {}).get(service, "")


def _call(service_key: str, endpoint: tuple[str, str], params: dict, label: str) -> dict:
    key = _key(service_key)
    if not key:
        return fail("API_AUTH_FAILED", "api", f"{label} API 키가 없습니다.")
    svc, op = endpoint
    result = request_text("GET", BASE.format(svc=svc, op=op),
                          params={"crkyCn": key, **params}, timeout=25)
    if not result["success"]:
        return result
    try:
        return ok(ET.fromstring(result["data"]), "api")
    except ET.ParseError:
        return fail("API_INVALID_RESPONSE", "api")


def _text(node, tag: str) -> str:
    return (node.findtext(tag) or "").strip()


def _iso_date(value: str) -> str:
    """20140916 -> 2014-09-16"""

    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(digits) != 8:
        return ""
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8])).isoformat()
    except ValueError:
        return ""


def _iso_datetime(value: str) -> str:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(digits) < 12:
        return _iso_date(value)
    try:
        return datetime(int(digits[:4]), int(digits[4:6]), int(digits[6:8]),
                        int(digits[8:10]), int(digits[10:12])).isoformat(sep=" ")
    except ValueError:
        return ""


def normalize_container_no(value: str) -> str:
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())


def is_container_no(value: str) -> bool:
    return bool(CONTAINER_NO.match(normalize_container_no(value)))


# --- 1. 화물통관 진행정보 -------------------------------------------------------

def cargo_progress(*, cargo_no: str = "", mbl_no: str = "", hbl_no: str = "",
                   bl_year: str = "") -> dict:
    """화물이 지금 어디까지 왔는지. (한국으로 들어오는 화물 기준)

    화물관리번호를 주면 한 건의 상세가, B/L번호를 주면 그 번호에 걸린 목록이
    옵니다. 목록이면 화물관리번호로 다시 부르라고 알려 줍니다.
    """

    params = {}
    if cargo_no:
        params["cargMtNo"] = cargo_no.strip().upper()
    if mbl_no:
        params["mblNo"] = mbl_no.strip().upper()
    if hbl_no:
        params["hblNo"] = hbl_no.strip().upper()
    if not params:
        return fail("VALIDATION_ERROR", "api", "화물관리번호 또는 B/L번호를 입력해주세요.")
    if (mbl_no or hbl_no):
        year = "".join(ch for ch in (bl_year or "") if ch.isdigit())[:4]
        if len(year) != 4:
            return fail("VALIDATION_ERROR", "api",
                        "B/L번호로 찾을 때는 입항년도(4자리)도 함께 입력해야 합니다.")
        params["blYy"] = year

    result = _call("CARGO_CLEARANCE_PROGRESS", CARGO_PROGRESS, params, "화물통관 진행정보")
    if not result["success"]:
        return result
    root = result["data"]

    notice = (root.findtext("ntceInfo") or "").strip()
    detail = root.find("cargCsclPrgsInfoQryVo")
    if detail is None:
        rows = [{
            "cargo_no": _text(row, "cargMtNo"),
            "mbl_no": _text(row, "mblNo"),
            "hbl_no": _text(row, "hblNo"),
            "arrival_date": _iso_date(_text(row, "etprDt")),
            "discharge_port": _text(row, "dsprNm"),
            "carrier": _text(row, "shcoFlco"),
        } for row in root.iter("cargCsclPrgsInfoQryVo")]
        if not rows:
            return ok(None, "api") if not notice else fail("API_NO_DATA", "api", notice)
        return ok({"kind": "list", "rows": rows}, "api")

    events = [{
        "kind": _text(row, "cargTrcnRelaBsopTpcd"),
        "detail": _text(row, "rlbrCn"),
        "at": _iso_datetime(_text(row, "rlbrDttm")) or _iso_datetime(_text(row, "prcsDttm")),
        "place": _text(row, "shedNm"),
        "declaration_no": _text(row, "dclrNo"),
        "packages": _text(row, "pckGcnt"),
        "package_unit": _text(row, "pckUt"),
        "weight": _text(row, "wght"),
        "weight_unit": _text(row, "wghtUt"),
        "notice": _text(row, "bfhnGdncCn"),
    } for row in root.iter("cargCsclPrgsInfoDtlQryVo")]
    # 최근 일이 위로 오게 둡니다.
    events.sort(key=lambda row: row["at"], reverse=True)

    return ok({
        "kind": "detail",
        "cargo_no": _text(detail, "cargMtNo"),
        "progress": _text(detail, "prgsStts"),
        "progress_code": _text(detail, "prgsStCd"),
        "clearance": _text(detail, "csclPrgsStts"),
        "mbl_no": _text(detail, "mblNo"),
        "hbl_no": _text(detail, "hblNo"),
        "bl_type": _text(detail, "blPtNm"),
        "carrier": _text(detail, "shcoFlco"),
        "carrier_code": _text(detail, "shcoFlcoSgn"),
        "forwarder": _text(detail, "frwrEntsConm"),
        "vessel": _text(detail, "shipNm"),
        "voyage": _text(detail, "vydf"),
        "vessel_country": _text(detail, "shipNatNm"),
        "load_port": _text(detail, "ldprNm"),
        "load_port_code": _text(detail, "ldprCd"),
        "discharge_port": _text(detail, "dsprNm"),
        "discharge_port_code": _text(detail, "dsprCd"),
        "arrival_customs": _text(detail, "etprCstm"),
        "arrival_date": _iso_date(_text(detail, "etprDt")),
        "product": _text(detail, "prnm"),
        "cargo_type": _text(detail, "cargTp"),
        "packages": _text(detail, "pckGcnt"),
        "package_unit": _text(detail, "pckUt"),
        "weight": _text(detail, "ttwg"),
        "weight_unit": _text(detail, "wghtUt"),
        "measurement": _text(detail, "msrm"),
        "container_count": _text(detail, "cntrGcnt"),
        "container_no": _text(detail, "cntrNo"),
        "managed_cargo": _text(detail, "mtTrgtCargYnNm"),
        "events": events,
    }, "api")


# --- 2. 컨테이너내역 -----------------------------------------------------------

CONTAINER_SIZE_NOTES = {
    "20": "20피트", "22": "20피트", "40": "40피트", "42": "40피트",
    "45": "40피트 하이큐브", "L5": "45피트",
}


def container_detail(cargo_no: str) -> dict:
    """화물관리번호에 딸린 컨테이너 번호·규격·봉인번호."""

    number = (cargo_no or "").strip().upper()
    if not number:
        return fail("VALIDATION_ERROR", "api", "화물관리번호를 입력해주세요.")

    result = _call("CONTAINER_DETAIL", CONTAINER_DETAIL, {"cargMtNo": number}, "컨테이너내역")
    if not result["success"]:
        return result
    root = result["data"]

    rows = []
    for row in root.iter("cntrQryBrkdQryVo"):
        size = _text(row, "cntrStszCd")
        seals = [_text(row, f"cntrSelgNo{index}") for index in (1, 2, 3)]
        rows.append({
            "container_no": _text(row, "cntrNo"),
            "size_code": size,
            "size_note": CONTAINER_SIZE_NOTES.get(size[:2], ""),
            "seals": [seal for seal in seals if seal],
        })
    rows = [row for row in rows if row["container_no"]]
    if not rows:
        notice = (root.findtext("ntceInfo") or "").strip()
        return fail("API_NO_DATA", "api", notice or "컨테이너 내역이 없습니다.") if notice else ok([], "api")
    return ok(rows, "api")


# --- 3. 수출이행내역 (우리 화물이 실제로 실렸는지) -------------------------------

def export_performance(*, declaration_no: str = "", bl_no: str = "") -> dict:
    """수출신고번호 또는 B/L번호로 실제 선적 여부와 적재의무기한을 봅니다."""

    params = {}
    if declaration_no:
        params["expDclrNo"] = "".join(ch for ch in declaration_no if ch.isalnum())
    if bl_no:
        params["blNo"] = bl_no.strip().upper()
    if not params:
        return fail("VALIDATION_ERROR", "api", "수출신고번호 또는 B/L번호를 입력해주세요.")

    result = _call("EXPORT_PERFORMANCE_BY_DECLARATION", EXPORT_PERFORMANCE, params,
                   "수출이행내역")
    if not result["success"]:
        return result
    root = result["data"]

    rows = []
    for row in root.iter():
        if not row.tag.endswith("RsltVo"):
            continue
        declaration = _text(row, "expDclrNo")
        if not declaration and not _text(row, "blNo"):
            continue
        # 고시에 "선적완료여부"의 태그 이름이 두 가지로 적혀 있어 둘 다 봅니다.
        shipped = _text(row, "shpmCmplYn") or _text(row, "shpmcmplYn")
        rows.append({
            "declaration_no": declaration,
            "bl_no": _text(row, "blNo"),
            "exporter": _text(row, "exppnConm"),
            "manufacturer": _text(row, "mnurConm"),
            "shipped": shipped.upper() == "Y",
            "shipped_label": "선적 완료" if shipped.upper() == "Y" else "미선적",
            "accepted_date": _iso_date(_text(row, "acptDt")),
            "load_deadline": _iso_date(_text(row, "loadDtyTmIm") or _text(row, "loadDtyTmlm")),
            "departure_date": _iso_date(_text(row, "tkofDt")),
            "vessel_or_flight": _text(row, "sanm"),
            "loading_place": _text(row, "shpmAirptPortNm"),
            "shipped_weight": _text(row, "shpmWght"),
            "cleared_weight": _text(row, "csclWght"),
            "shipped_packages": _text(row, "shpmPckGcnt"),
            "cleared_packages": _text(row, "csclPckGcnt"),
            "package_unit": _text(row, "shpmPckUt") or _text(row, "csclPckUt"),
        })

    merged = _merge_export_rows(rows)
    if not merged:
        notice = (root.findtext("ntceInfo") or "").strip()
        return fail("API_NO_DATA", "api", notice) if notice else ok([], "api")
    return ok(merged, "api")


def _merge_export_rows(rows: list[dict]) -> list[dict]:
    """머리 줄(신고 정보)과 딸린 줄(선적 실적)을 한 건으로 합칩니다.

    관세청 응답은 신고 정보가 먼저 오고, 그 아래에 실제 선적 줄이 따로 옵니다.
    화면에서는 한 줄로 보여야 읽힙니다.
    """

    merged: list[dict] = []
    for row in rows:
        target = None
        if row["declaration_no"]:
            target = next((item for item in merged
                           if item["declaration_no"] == row["declaration_no"]), None)
        elif merged:
            target = merged[-1]                       # 바로 앞 신고에 딸린 선적 줄
        if target is None:
            merged.append(row)
            continue
        for field, value in row.items():
            if value in ("", False, None):
                continue
            if not target.get(field):
                target[field] = value
        if row["shipped"]:
            target["shipped"] = True
            target["shipped_label"] = "선적 완료"
    return merged
