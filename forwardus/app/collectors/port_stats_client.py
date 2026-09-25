"""해양수산부 항만 통계 (공공데이터포털).

"이 항구가 실제로 얼마나 바쁜가"를 봅니다. 출발항을 고를 때, 그리고 컨테이너
물량이 몰리는 시기를 피할 때 씁니다.

    항만별 선박 입출항: /1192000/SsopVsslEtryndHarbor2/YM
    지역별 선박 입출항: /1192000/SsopVsslEtryndArea2/YM
    컨테이너 처리실적:  /1192000/SsopCargContnOutnin2/Ym

세 API 모두 조회 기간을 `sym`(시작 연월) `eym`(종료 연월)로 받고, XML로
답합니다. 한 줄 안에 <details><detail> 로 세부가 또 들어 있어 펴서 씁니다.

주의: 통계는 한두 달 늦게 올라옵니다. 오늘 달을 물으면 비어 있을 수 있습니다.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date

from app.collectors import snapshot
from app.collectors.base_client import fail, get_config, ok, request_text

HARBOR_URL = "https://apis.data.go.kr/1192000/SsopVsslEtryndHarbor2/YM"
AREA_URL = "https://apis.data.go.kr/1192000/SsopVsslEtryndArea2/YM"
CONTAINER_URL = "https://apis.data.go.kr/1192000/SsopCargContnOutnin2/Ym"

SIGNUP = {
    "label": "공공데이터포털 · 해양수산부 항만 통계",
    "url": "https://www.data.go.kr/tcs/dss/selectDataSetList.do?keyword=선박입출항실적",
    "how": "'항만별 선박입출항실적', '외내항컨테이너처리실적'을 각각 활용신청합니다.",
}


def available() -> bool:
    return bool(get_config("DATA_GO_KR_SERVICE_KEY", ""))


def _period(months: int = 6) -> tuple[str, str]:
    """최근 몇 달. 통계가 늦게 올라와 두 달 앞에서 끊습니다."""

    today = date.today()
    year, month = today.year, today.month - 2       # 최근 두 달은 아직 없습니다.
    while month <= 0:
        year, month = year - 1, month + 12
    end = f"{year}{month:02d}"

    year, month = year, month - months + 1
    while month <= 0:
        year, month = year - 1, month + 12
    return f"{year}{month:02d}", end


def _call(url: str, params: dict, label: str) -> dict:
    key = get_config("DATA_GO_KR_SERVICE_KEY", "")
    if not key:
        return fail("API_AUTH_FAILED", "api", f"{label} 키(DATA_GO_KR_SERVICE_KEY)가 없습니다.")

    result = request_text("GET", url, timeout=25,
                          params={"serviceKey": key, "pageNo": 1, "numOfRows": 100, **params})
    if not result["success"]:
        if result["error_code"] == "API_AUTH_FAILED":
            return fail("API_NOT_SUBSCRIBED", "api",
                        f"{label} API에 활용신청이 되어 있지 않습니다. {SIGNUP['how']}")
        return result

    try:
        root = ET.fromstring(result["data"])
    except ET.ParseError:
        return fail("API_INVALID_RESPONSE", "api")

    code = (root.findtext(".//resultCode") or "").strip()
    if code and code not in ("00", "0"):
        message = (root.findtext(".//resultMsg") or "").strip()
        return fail("API_NO_DATA", "api", f"{label}: {message or '조회하지 못했습니다.'}")
    return ok(root, "api")


def _number(value) -> float:
    try:
        return float(str(value).replace(",", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def _flatten(root) -> list[dict]:
    """<item><useYm/><prtAgNm/><details><detail/>...</details></item> 를 폅니다."""

    rows = []
    for item in root.iter("item"):
        base = {child.tag: (child.text or "").strip()
                for child in item if child.tag != "details"}
        details = list(item.iter("detail"))
        if not details:
            rows.append(base)
            continue
        for detail in details:
            row = dict(base)
            row.update({child.tag: (child.text or "").strip() for child in detail})
            rows.append(row)
    return rows


def port_traffic(months: int = 6) -> dict:
    """항만별 선박 입출항 실적. 어느 항구가 얼마나 바쁜지 봅니다."""

    start, end = _period(months)
    result = _call(HARBOR_URL, {"sym": start, "eym": end}, "항만별 선박입출항실적")
    if not result["success"]:
        # 통계는 한두 달 늦게 올라옵니다. 기관이 막혔다고 빈 화면을 주느니
        # 지난번에 받아 둔 값을 "며칠 전 값"이라고 밝히고 보여 줍니다.
        return snapshot.recall(f"port_traffic_{months}", "stats") or result

    rows = [{
        "period": row.get("useYm", ""),
        "port": row.get("prtAgNm", ""),
        "kind": row.get("nm", ""),                  # 국적선 · 외국선 · 연안
        "entered_ships": int(_number(row.get("etrVsslCo"))),
        "entered_tonnage": _number(row.get("etrGrtg")),
        "departed_ships": int(_number(row.get("satVsslCo"))),
        "departed_tonnage": _number(row.get("satGrtg")),
    } for row in _flatten(result["data"])]
    rows = [row for row in rows if row["port"]]
    return snapshot.remember(f"port_traffic_{months}", ok(
        {"from": start, "to": end, "rows": rows,
         "note": "척수와 총톤수입니다. 통계는 한두 달 늦게 올라옵니다."}, "api"))


def container_throughput(months: int = 6) -> dict:
    """컨테이너 처리실적(TEU). 물량이 몰리는 시기를 피할 때 씁니다."""

    start, end = _period(months)
    result = _call(CONTAINER_URL, {"sym": start, "eym": end}, "외내항컨테이너처리실적")
    if not result["success"]:
        return result

    rows = []
    for row in _flatten(result["data"]):
        full = _number(row.get("fnshpFcontnTeu")) + _number(row.get("intrvsslFcontnTeu"))
        empty = _number(row.get("fnshpEcontnTeu")) + _number(row.get("intrvsslEcontnTeu"))
        rows.append({
            "period": row.get("useYm", ""),
            "port": row.get("prtAgNm", ""),
            "kind": row.get("nm", ""),              # 외항-입항 · 외항-출항 · 내항
            "full_teu": round(full, 1),
            "empty_teu": round(empty, 1),
            "total_teu": round(full + empty, 1),
        })
    rows = [row for row in rows if row["port"]]
    return ok({"from": start, "to": end, "rows": rows,
               "note": "TEU는 20피트 컨테이너 한 대를 1로 센 단위입니다."}, "api")


def busiest_ports(months: int = 6, limit: int = 10) -> dict:
    """컨테이너를 가장 많이 처리한 항구 순서. 출발항을 고를 때 씁니다."""

    result = container_throughput(months)
    if not result["success"]:
        return result

    by_port: dict[str, dict] = {}
    for row in result["data"]["rows"]:
        found = by_port.setdefault(row["port"], {
            "port": row["port"], "full_teu": 0.0, "empty_teu": 0.0, "total_teu": 0.0})
        for field in ("full_teu", "empty_teu", "total_teu"):
            found[field] += row[field]

    rows = sorted(by_port.values(), key=lambda row: -row["total_teu"])[:max(1, limit)]
    for row in rows:
        for field in ("full_teu", "empty_teu", "total_teu"):
            row[field] = round(row[field], 1)
    return ok({**result["data"], "rows": rows,
               "note": f"{result['data']['from']}~{result['data']['to']} 합계입니다. "
                       "TEU는 20피트 컨테이너 한 대를 1로 셉니다."}, "api")


def region_traffic(months: int = 6) -> dict:
    """지역별(상대 지역) 선박 입출항. 어느 항로가 붐비는지 봅니다."""

    start, end = _period(months)
    result = _call(AREA_URL, {"sym": start, "eym": end}, "지역별 선박입출항실적")
    if not result["success"]:
        return result

    rows = [{
        "period": row.get("useYm", ""),
        "port": row.get("prtAgNm", ""),
        "region": row.get("nm", ""),                # 일본 · 극동아시아 · 북미 ...
        "coastal_ships": int(_number(row.get("intrvsslCo"))),
        "coastal_tonnage": _number(row.get("intrvsslGrtg")),
        "ocean_ships": int(_number(row.get("fnshpCo"))),
        "ocean_tonnage": _number(row.get("fnshpGrtg")),
    } for row in _flatten(result["data"])]
    rows = [row for row in rows if row["port"] and row["region"]]
    return ok({"from": start, "to": end, "rows": rows,
               "note": "외항선 척수가 많을수록 그 지역으로 가는 배가 많습니다."}, "api")
