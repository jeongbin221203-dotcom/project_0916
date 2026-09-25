"""관세청 UNI-PASS 나머지 서비스.

customs_client(HS부호·관세율·통계부호), exchange_client(환율),
carrier_client(선사), container_client(화물·컨테이너·수출이행)에서 쓰지 않는
서비스를 여기에 모았습니다.

호출 규칙은 모두 같습니다.
    https://unipass.customs.go.kr:38010/ext/rest/<서비스>/<오퍼레이션>?crkyCn=<키>&...
응답은 XML이고 JSON은 없습니다. 서비스마다 키가 따로라 이름으로만 다룹니다.

각 서비스의 파라미터·응답 항목은 관세청 「OPEN API 연계가이드 v2.0」을 따랐습니다.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date

from app.collectors import snapshot
from app.collectors.base_client import fail, get_config, ok, request_text

BASE = "https://unipass.customs.go.kr:38010/ext/rest/{svc}/{op}"

# (환경변수 이름, 서비스, 오퍼레이션)
SERVICES = {
    # (세관장확인대상은 공공데이터포털로 옮겼습니다 — 아래 export_requirement_laws 참고.
    #  UNI-PASS의 ccctLworCdQry는 이 프로젝트 키로는 "인증키상의 API 불일치"가 납니다)
    "clearance_code": ("CUSTOMS_CLEARANCE_CODE", "ecmQry", "retrieveEcm"),
    "refund_rate": ("SIMPLE_REFUND_RATE", "simlXamrttXtrnUserQry", "retrieveSimlXamrttXtrnUser"),
    "refund_company": ("SIMPLE_REFUND_COMPANY", "simlFxamtAplyNnaplyEntsQry",
                       "retrieveSimlFxamtAplyNnaplyEnts"),
    "declaration_verify": ("EXPORT_DECLARATION_VERIFY", "expDclrCrfnVrfcInfoQry",
                           "retrieveExpDclrCrfnVrfc"),
    "shortened_period": ("EXPORT_PERIOD_SHORTENING_ITEM", "expFfmnPridShrtTrgtPrlstQry",
                         "retrieveExpFfmnPridShrtTrgtPrlst"),
    "airline_list": ("AIRLINE_LIST", "flcoLstQry", "retrieveFlcoLst"),
    "airline_detail": ("AIRLINE_DETAIL", "flcoBrkdQry", "retrieveFlcoBrkd"),
    "forwarder_list": ("FORWARDER_LIST", "frwrLstQry", "retrieveFrwrLst"),
    "forwarder_detail": ("FORWARDER_DETAIL", "frwrBrkdQry", "retrieveFrwrBrkd"),
    "inspection": ("INSPECTION_QUARANTINE", "xtrnUserInscQuanBrkdQry",
                   "retrieveXtrnUserInscQuanBrkd"),
    "requirement_approval": ("REQUIREMENT_APPROVAL", "xtrnUserReqApreBrkdQry",
                             "retrieveXtrnUserReqApreBrkd"),
    "attachment": ("DECLARATION_ATTACHMENT_SUBMISSION", "expImpAffcSbmtInfoQry",
                   "retrieveExpImpAffcSbmtInfo"),
    "correction": ("DECLARATION_CORRECTION_STATUS", "apfmPrcsStusQry", "retrieveApfmPrcsStus"),
    "arrival_sea": ("ARRIVAL_REPORT_SEA", "etprRprtQryBrkdQry", "retrieveetprRprtQryBrkd"),
    "arrival_air": ("ARRIVAL_REPORT_AIR", "etprRprtQryBrkdQry", "retrieveetprRprtQryBrkd"),
    "departure_air": ("DEPARTURE_PERMIT_AIR", "tkofWrprQry", "retrieveFlghTkofPerm"),
    "departure_sea": ("DEPARTURE_PERMIT_SEA", "tkofWrprQry", "retrieveTkofWrpr"),
    "entry_departure": ("ENTRY_DEPARTURE_REPORT", "ioprRprtQry", "retrieveIoprRprtBrkd"),
    "hs_navigation": ("HS_NAVIGATION", "cmtrStatsQry", "retrieveCmtrStats"),
    "reexport_balance": ("REEXPORT_EXEMPTION_BALANCE", "expCmdtRsqtyInfoQry",
                         "retrieveExpCmdtRsqtyInfo"),
    "vin_export": ("EXPORT_PERFORMANCE_BY_VIN", "expFfmnBrkdCbnoQry",
                   "retrieveExpFfmnBrkdCbnoQryRtnVo"),
    "reexport_deadline": ("REEXPORT_CONDITIONAL_IMPORT_DEADLINE", "rexpFfmnTmlmInfoQry",
                          "retrieveRexpFfmnTmlmInfo"),
    "reexport_done": ("REEXPORT_COMPLETION_REPORT", "rexpFfmnCmplRprtQry",
                      "retrieveRexpFfmnCmplRprt"),
}


def _call(name: str, params: dict, label: str, timeout: int = 25) -> dict:
    env_name, svc, op = SERVICES[name]
    key = (get_config("UNIPASS_API_KEYS", {}) or {}).get(env_name, "")
    if not key:
        return fail("API_AUTH_FAILED", "api", f"{label} API 키가 없습니다.")
    result = request_text("GET", BASE.format(svc=svc, op=op),
                          params={"crkyCn": key, **params}, timeout=timeout)
    if not result["success"]:
        return result
    try:
        return ok(ET.fromstring(result["data"]), "api")
    except ET.ParseError:
        return fail("API_INVALID_RESPONSE", "api")


def _text(node, tag: str) -> str:
    return (node.findtext(tag) or "").strip()


def hs_navigation(hs_code: str) -> dict:
    """API043: ranked product-line counts for one HSK, not declaration counts."""
    digits = "".join(ch for ch in hs_code if ch.isdigit())
    if len(digits) != 10:
        return fail("VALIDATION_ERROR", "api", "HS부호 10자리가 필요합니다.")
    result = _call("hs_navigation", {"hsSgn": digits}, "HS 내비게이션", timeout=8)
    if not result["success"]:
        return snapshot.recall(f"hs_nav_{digits}", "law") or result
    root = result["data"]
    if root.tag != "cmtrStatsQryRtnVo":
        return fail("API_INVALID_RESPONSE", "api")
    notice = _text(root, "ntceInfo")
    if notice:
        return fail("API_INVALID_REQUEST", "api", notice)
    rows = []
    for row in root.findall("cmtrStatsQryRsltVo"):
        code = _text(row, "hs10Sgn")
        count = _text(row, "prlstLnCnt").replace(",", "")
        rank = _text(row, "acrsTcntRnk")
        if code != digits or not count.isascii() or not count.isdigit():
            return fail("API_INVALID_RESPONSE", "api", "내비게이션 건수를 확인할 수 없습니다.")
        rows.append({"code": code, "name": _text(row, "prlstNm"),
                     "count": int(count), "rank": int(rank) if rank.isdigit() else None})
    return snapshot.remember(f"hs_nav_{digits}", ok(rows, "api"))


def _iso(value: str) -> str:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())[:8]
    if len(digits) != 8:
        return ""
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:])).isoformat()
    except ValueError:
        return ""


def _rows(root, *tags) -> list:
    for tag in tags:
        found = list(root.iter(tag))
        if found:
            return found
    return []


def _notice(root) -> str:
    return (root.findtext("ntceInfo") or "").strip()


def _empty(root, label: str) -> dict:
    notice = _notice(root)
    return fail("API_NO_DATA", "api", notice or f"{label} 조회 결과가 없습니다.") if notice \
        else ok([], "api")


# --- 1. 세관장확인대상: 이 품목을 보낼 때 걸리는 법령 ---------------------------
# 이 서비스만 UNI-PASS가 아니라 공공데이터포털(apis.data.go.kr)에 있습니다.
#   관세청_세관장확인대상물품(GW) · https://www.data.go.kr/data/15101589/openapi.do
#   GET /1220000/retrieveCcctLworCd/getRetrieveCcctLworCd
#       serviceKey · hsSgn(HSK 10자리) · imexTpcd(1 수출 · 2 수입) · pageNo · numOfRows
# 키는 .env의 UNIPASS_KEY_CUSTOMS 입니다. (이름만 UNIPASS_이고 실제로는 포털 키입니다)

CUSTOMS_CONFIRM_URL = ("https://apis.data.go.kr/1220000/retrieveCcctLworCd/"
                       "getRetrieveCcctLworCd")
CUSTOMS_CONFIRM_SIGNUP = {
    "label": "공공데이터포털 · 관세청 세관장확인대상물품(GW)",
    "url": "https://www.data.go.kr/data/15101589/openapi.do",
    "how": "위 주소에서 [활용신청]을 누르고 받은 인증키를 .env의 UNIPASS_KEY_CUSTOMS 에 넣습니다.",
}
EXPORT, IMPORT = "1", "2"


def export_requirement_laws(hs_code: str, direction: str = EXPORT) -> dict:
    """HSK 10자리로 세관장확인대상인지 봅니다. (관세법 제226조)

    걸리는 법령·요건승인기관·요건확인서류·적용시작일이 나옵니다.
    direction은 "1" 수출(기본) · "2" 수입입니다. 수입국 규제가 아니라 **한국** 기준입니다.

    결과가 비어 있는 것은 "규제가 없다"가 아니라 "이 조회에서 걸리는 법령이 없다"입니다.
    품목분류가 틀렸을 수도 있어 부르는 쪽에서 그렇게 안내합니다.
    """

    digits = "".join(ch for ch in (hs_code or "") if ch.isdigit())
    if len(digits) != 10:
        return fail("VALIDATION_ERROR", "api", "HS부호 10자리를 입력해주세요.")
    key = get_config("CUSTOMS_CONFIRM_API_KEY", "")
    if not key:
        return fail("API_AUTH_FAILED", "api",
                    "세관장확인대상물품 API 키가 없습니다. "
                    f"{CUSTOMS_CONFIRM_SIGNUP['how']}")

    result = request_text("GET", CUSTOMS_CONFIRM_URL, timeout=25,
                          params={"serviceKey": key, "hsSgn": digits,
                                  "imexTpcd": direction if direction in (EXPORT, IMPORT) else EXPORT,
                                  "pageNo": "1", "numOfRows": "50"})
    snap = f"laws_{digits}_{direction}"
    if not result["success"]:
        # 걸리는 법령은 법이 바뀔 때만 바뀝니다. 지난번에 받아 둔 것으로 답합니다.
        return snapshot.recall(snap, "law") or result
    try:
        root = ET.fromstring(result["data"])
    except ET.ParseError:
        return fail("API_INVALID_RESPONSE", "api")

    code = (root.findtext(".//resultCode") or "").strip()
    message = (root.findtext(".//resultMsg") or "").strip()
    if code and code != "00":
        # 포털은 200으로 답하면서 본문에 실패를 적습니다. 성공으로 넘기면 안 됩니다.
        return fail("API_NO_DATA" if code == "03" else "API_INVALID_RESPONSE", "api",
                    message or "세관장확인대상물품 조회에 실패했습니다.")

    rows = [{
        "hs_code": _text(row, "hsSgn") or digits,
        "law_code": _text(row, "dcerCfrmLworCd"),
        "law_name": _text(row, "dcerCfrmLworNm"),
        "agency_code": _text(row, "reqApreIttCd"),
        "agency": _text(row, "reqApreIttNm"),
        "document": _text(row, "reqCfrmIstmNm"),
        # 1 사전 · 2 사후 · 3 실시간. 통관 전에 갖춰야 하는지가 갈립니다.
        "timing_code": _text(row, "bfhnAffcRtmTpcd"),
        "start_date": _iso(_text(row, "aplyStrtDt")),
        # 이 서비스는 종료일을 주지 않습니다. 모르는 것을 지어내지 않고 비워 둡니다.
        "end_date": "",
    } for row in root.iter("item")]
    rows = [row for row in rows if row["law_name"] or row["agency"]]
    return snapshot.remember(snap, ok(rows, "api"))


# --- 2. 통관고유부호: 사업자등록번호로 찾습니다 ---------------------------------

def clearance_code(*, business_no: str = "", code: str = "") -> dict:
    """수출신고서에 반드시 들어가는 통관고유부호를 찾아 줍니다."""

    params = {}
    if business_no:
        digits = "".join(ch for ch in business_no if ch.isdigit())
        if len(digits) != 10:
            return fail("VALIDATION_ERROR", "api", "사업자등록번호는 숫자 10자리입니다.")
        params["brno"] = digits
    if code:
        params["ecm"] = code.strip().upper()
    if not params:
        return fail("VALIDATION_ERROR", "api", "사업자등록번호나 통관고유부호를 입력해주세요.")

    result = _call("clearance_code", params, "통관고유부호")
    if not result["success"]:
        return result
    root = result["data"]

    rows = [{
        "clearance_code": _text(row, "ecm"),
        "name": _text(row, "conmNm"),
        "business_no": _text(row, "bsnsNo"),
        "representative": _text(row, "rppnNm"),
        "in_use": _text(row, "useYn").upper() == "Y",
    } for row in _rows(root, "ecmQryRsltVo", "ecmQryVo")]
    rows = [row for row in rows if row["clearance_code"]]
    return ok(rows, "api") if rows else _empty(root, "통관고유부호")


# --- 3. 간이정액 환급: 얼마를 돌려받을 수 있는지 -------------------------------

def refund_rate(hs_code: str, base_date: date | None = None) -> dict:
    """간이정액 환급율. 수출 신고 금액에 곱해 돌려받을 돈을 어림합니다."""

    digits = "".join(ch for ch in (hs_code or "") if ch.isdigit())
    if len(digits) != 10:
        return fail("VALIDATION_ERROR", "api", "HS부호 10자리를 입력해주세요.")

    result = _call("refund_rate", {"baseDt": (base_date or date.today()).strftime("%Y%m%d"),
                                   "hsSgn": digits}, "간이정액 환급율표")
    if not result["success"]:
        return result
    root = result["data"]

    rows = []
    for row in _rows(root, "simlXamrttXtrnUserQryRsltVo", "simlXamrttXtrnUserQryVo"):
        basis = _text(row, "drwbAmtBaseTpcd")
        rows.append({
            "hs_code": _text(row, "hs10") or digits,
            "spec": _text(row, "stsz"),
            "amount_krw": _text(row, "prutDrwbWncrAmt"),
            # 1이면 수출금액 10달러당, 2면 1만원당 환급액입니다.
            "basis_code": basis,
            "basis": {"1": "수출금액 10달러당", "2": "수출금액 1만원당"}.get(basis, ""),
            "start_date": _iso(_text(row, "aplyDd")),
            "stop_date": _iso(_text(row, "ceseDt")),
        })
    rows = [row for row in rows if row["amount_krw"]]
    return (snapshot.remember(f"refund_rate_{digits}", ok(rows, "api")) if rows
            else _empty(root, "간이정액 환급율표"))


def refund_company(clearance_code_value: str) -> dict:
    """그 업체가 간이정액 환급을 쓸 수 있는지."""

    code = (clearance_code_value or "").strip().upper()
    if not code:
        return fail("VALIDATION_ERROR", "api", "통관고유부호를 입력해주세요.")

    result = _call("refund_company", {"ecm": code}, "간이정액 적용업체")
    if not result["success"]:
        return result
    root = result["data"]

    rows = []
    for row in _rows(root, "simlFxamtAplyNnaplyEntsQryRsltVo", "simlFxamtAplyNnaplyEntsQryVo"):
        excluded_on = _iso(_text(row, "simlFxamtNnaplyApreDt"))
        rows.append({
            "name": _text(row, "conm"),
            "customs_office": _text(row, "rgsrCstmNm"),
            "applied_on": _iso(_text(row, "simlFxamtAplyApreDt")),
            "excluded_on": excluded_on,
            "excluded_reason": _text(row, "simlFxamtNnaplyApntRsn"),
            # 비적용 승인일이 있으면 간이정액을 쓸 수 없습니다.
            "eligible": not excluded_on,
        })
    rows = [row for row in rows if row["name"]]
    return ok(rows, "api") if rows else _empty(root, "간이정액 적용업체")


# --- 4. 수출신고필증 검증 -------------------------------------------------------

def verify_export_declaration(*, publication_no: str, declaration_no: str,
                              business_no: str, origin_country: str,
                              product_name: str, net_weight_kg) -> dict:
    """받은 수출신고필증이 진짜인지 관세청에 대조합니다.

    여섯 가지가 모두 맞아야 "일치"가 나옵니다. 하나라도 다르면 위조이거나
    옮겨 적다 틀린 것입니다.
    """

    digits = "".join(ch for ch in (business_no or "") if ch.isdigit())
    if len(digits) != 10:
        return fail("VALIDATION_ERROR", "api", "수출화주 사업자등록번호는 숫자 10자리입니다.")
    try:
        weight = float(str(net_weight_kg).replace(",", ""))
    except (TypeError, ValueError):
        return fail("VALIDATION_ERROR", "api", "순중량을 숫자로 입력해주세요.")

    result = _call("declaration_verify", {
        "expDclrCrfnPblsNo": "".join(ch for ch in (publication_no or "") if ch.isalnum()),
        "expDclrNo": "".join(ch for ch in (declaration_no or "") if ch.isdigit()),
        "txprBrno": digits,
        "orcyCntyCd": (origin_country or "").strip().upper()[:2],
        "prnm": (product_name or "").strip()[:300],
        "ntwg": f"{weight:g}",
    }, "수출신고필증검증")
    if not result["success"]:
        return result
    root = result["data"]

    # 이 서비스는 결과가 루트에 바로 붙습니다. tCnt가 일치 여부입니다.
    code = (root.findtext("tCnt") or "").strip()
    label = (root.findtext("vrfcRsltCn") or "").strip()
    return ok({
        "match": code == "1",
        "code": code,
        "label": label or {"1": "일치함", "0": "일치하지 않음",
                           "-1": "관세청 시스템 장애"}.get(code, "알 수 없음"),
        "system_error": code == "-1",
    }, "api")


# --- 5. 수출이행기간 단축 대상 품목 ---------------------------------------------

def shortened_loading_period(hs_code: str) -> dict:
    """적재기한이 30일보다 짧아지는 품목인지 봅니다."""

    digits = "".join(ch for ch in (hs_code or "") if ch.isdigit())
    if len(digits) != 10:
        return fail("VALIDATION_ERROR", "api", "HS부호 10자리를 입력해주세요.")

    result = _call("shortened_period", {"hsSgn": digits}, "수출이행기간 단축대상")
    if not result["success"]:
        return result
    root = result["data"]

    rows = [{
        "hs_code": _text(row, "hsSgn") or digits,
        "product": _text(row, "prnm"),
        "spec": _text(row, "stszNm"),
        "deadline": _iso(_text(row, "ffmnTmlmDt")),
        "import_end_date": _iso(_text(row, "trgtImpEndDt")),
    } for row in _rows(root, "expFfmnPridShrtTrgtPrlstQryRsltVo",
                       "expFfmnPridShrtTrgtPrlstQryVo")]
    rows = [row for row in rows if row["product"] or row["deadline"]]
    return (snapshot.remember(f"short_period_{digits}", ok(rows, "api")) if rows
            else _empty(root, "수출이행기간 단축대상"))


# --- 6. 항공사 · 포워더 ---------------------------------------------------------

def search_airlines(name: str) -> dict:
    """항공사를 이름으로 찾습니다. (선사 조회와 짝입니다)"""

    query = (name or "").strip()
    if not query:
        return fail("VALIDATION_ERROR", "api", "항공사명을 입력해주세요.")

    result = _call("airline_list", {"flcoNm": query}, "항공사 목록")
    if not result["success"]:
        # 항공사 등록부는 거의 바뀌지 않습니다. 지난번에 받아 둔 것으로 답합니다.
        return snapshot.recall(f"airlines_{query}", "registry") or result
    root = result["data"]

    rows = [{
        "code": _text(row, "flcoSgn"),
        "korean_name": _text(row, "flcoKoreNm"),
        "english_name": _text(row, "flcoEngNm"),
        "representative": _text(row, "rppnNm"),
    } for row in _rows(root, "flcoLstQryRsltVo", "flcoLstQryVo")]
    rows = [row for row in rows if row["code"]]
    return (snapshot.remember(f"airlines_{query}", ok(rows, "api")) if rows
            else _empty(root, "항공사 목록"))


def airline(code: str) -> dict:
    """항공사 부호로 등록 내역을 봅니다."""

    sign = (code or "").strip().upper()
    if not sign:
        return fail("VALIDATION_ERROR", "api", "항공사부호를 입력해주세요.")

    result = _call("airline_detail", {"flcoSgn": sign}, "항공사 내역")
    if not result["success"]:
        return result
    root = result["data"]

    row = next(iter(_rows(root, "flcoBrkdQryRsltVo", "flcoBrkdQryVo")), None)
    if row is None:
        return _empty(root, "항공사 내역")
    return ok({
        "code": sign,
        "korean_name": _text(row, "flcoKoreConm"),
        "english_name": _text(row, "flcoEnglConm"),
        "english_code": _text(row, "flcoEnglSgn"),
        "numeric_code": _text(row, "flcoNumSgn"),
        "business_no": _text(row, "brno"),
        "representative": _text(row, "rppnFnm"),
        "country": _text(row, "cntyNm"),
        "country_code": _text(row, "flcoNat"),
        "address": _text(row, "hdofAddr"),
        "tel": _text(row, "telno"),
        "fax": _text(row, "faxNo"),
    }, "api")


def search_forwarders(name: str) -> dict:
    """화물운송주선업자(포워더)를 상호로 찾습니다."""

    query = (name or "").strip()
    if not query:
        return fail("VALIDATION_ERROR", "api", "포워더 상호를 입력해주세요.")

    result = _call("forwarder_list", {"frwrNm": query}, "화물운송주선업자 목록")
    if not result["success"]:
        return snapshot.recall(f"forwarders_{query}", "registry") or result
    root = result["data"]

    rows = [{
        "code": _text(row, "frwrSgn"),
        "korean_name": _text(row, "frwrKoreNm"),
        "english_name": _text(row, "frwrEnglNm"),
        "representative": _text(row, "rppnNm"),
    } for row in _rows(root, "frwrLstQryRsltVo", "frwrLstQryVo")]
    rows = [row for row in rows if row["code"]]
    return (snapshot.remember(f"forwarders_{query}", ok(rows, "api")) if rows
            else _empty(root, "화물운송주선업자 목록"))


def forwarder(code: str) -> dict:
    """포워더 부호로 주소·전화번호를 봅니다."""

    sign = (code or "").strip().upper()
    if not sign:
        return fail("VALIDATION_ERROR", "api", "포워더 부호를 입력해주세요.")

    result = _call("forwarder_detail", {"frwrSgn": sign}, "화물운송주선업자 내역")
    if not result["success"]:
        return result
    root = result["data"]

    row = next(iter(_rows(root, "frwrBrkdQryRsltVo", "frwrBrkdQryVo")), None)
    if row is None:
        return _empty(root, "화물운송주선업자 내역")
    return ok({
        "code": sign,
        "korean_name": _text(row, "frwrKoreNm") or _text(row, "frwrKoreConm"),
        "english_name": _text(row, "frwrEnglNm") or _text(row, "frwrEnglConm"),
        "representative": _text(row, "rppnNm") or _text(row, "rppnFnm"),
        "business_no": _text(row, "brno"),
        "address": _text(row, "hdofAddr") or _text(row, "addr"),
        "tel": _text(row, "telno"),
        "fax": _text(row, "faxNo"),
    }, "api")


# --- 7. 신고 뒤의 진행 상태 -----------------------------------------------------

def attachment_status(submission_no: str, business: str = "EXP") -> dict:
    """신고서에 첨부서류를 냈는지 봅니다. (수출통관은 EXP)"""

    number = (submission_no or "").strip()
    if not number:
        return fail("VALIDATION_ERROR", "api", "신고서 제출번호를 입력해주세요.")

    result = _call("attachment", {"dclrBsopDtlTpcd": business.upper()[:3],
                                  "dcshSbmtNo": number}, "첨부서류 제출유무")
    if not result["success"]:
        return result
    root = result["data"]

    rows = [{
        "form_name": _text(row, "elctDocNm"),
        "submission_no": _text(row, "dcshSbmtNo"),
        "submitted_on": _iso(_text(row, "sbmtDttm")),
        "submitted": _text(row, "attchSbmtYn").upper() == "Y",
    } for row in _rows(root, "expImpAffcSbmtInfoQryRsltVo", "expImpAffcSbmtInfoQryVo")]
    rows = [row for row in rows if row["form_name"] or row["submission_no"]]
    return ok(rows, "api") if rows else _empty(root, "첨부서류 제출유무")


def requirement_status(request_no: str) -> dict:
    """통관단일창구에 낸 요건 신청이 어디까지 갔는지."""

    number = "".join(ch for ch in (request_no or "") if ch.isalnum())
    if not number:
        return fail("VALIDATION_ERROR", "api", "요건 신청번호를 입력해주세요.")

    result = _call("correction", {"reqRqstNo": number}, "통관단일창구 처리이력")
    if not result["success"]:
        return result
    root = result["data"]

    rows = [{
        "request_no": _text(row, "reqRqstNo"),
        "document": _text(row, "elctDocNm") or _text(row, "relaDocNm"),
        "status_code": _text(row, "reqRqstPrcsStcd"),
        "status": _text(row, "reqRqstPrcsSttsNm"),
        "direction": _text(row, "trsnTpNm"),
        "at": _text(row, "rcpnDttm"),
        "agency_result_no": _text(row, "reqIttRsltInfmNo"),
    } for row in _rows(root, "apfmPrcsStusQryRsltVo", "apfmPrcsStusQryVo")]
    rows = [row for row in rows if row["status"] or row["document"]]
    return ok(rows, "api") if rows else _empty(root, "통관단일창구 처리이력")


def inspection_result(*, agency_code: str, notice_no: str, sequence: str = "1") -> dict:
    """검사·검역 결과. 합격 여부와 불합격 조치를 줍니다."""

    if not (agency_code or "").strip() or not (notice_no or "").strip():
        return fail("VALIDATION_ERROR", "api", "검사검역기관 부호와 통지번호를 입력해주세요.")

    result = _call("inspection", {"inscQuanItt": agency_code.strip()[:3],
                                  "ntfcNo": notice_no.strip(),
                                  "dgcnt": str(sequence or "1")}, "검사검역 내역")
    if not result["success"]:
        return result
    root = result["data"]

    row = next(iter(_rows(root, "xtrnUserInscQuanBrkdQryRsltVo",
                          "xtrnUserInscQuanBrkdQryVo")), None)
    if row is None:
        return _empty(root, "검사검역 내역")
    passed = _text(row, "inscQuanPsxaYn")
    return ok({
        "notice_no": _text(row, "ntfcNo"),
        "agency_code": _text(row, "inscQuanIttSgn"),
        "requested_on": _iso(_text(row, "rqstDt")),
        "decided_on": _iso(_text(row, "inscQuanDtrmDt")),
        "shipped_on": _iso(_text(row, "shpmDt")),
        "loading_port": _text(row, "lprt"),
        "passed": passed.upper().startswith("Y") or "합격" in passed,
        "result": passed,
        "failure_action": _text(row, "dsqfTkacBrkd"),
    }, "api")


# --- 8. 선박·항공기 실제 움직임 -------------------------------------------------

def arrival_report(*, call_sign: str = "", submission_no: str = "") -> dict:
    """그 배가 실제로 입항했는지. (선박호출부호 또는 입출항제출번호)"""

    params = {}
    if submission_no:
        params["ioprSbmtNo"] = submission_no.strip().upper()
    if call_sign:
        params["shipCallSgn"] = call_sign.strip().upper()
    if not params:
        return fail("VALIDATION_ERROR", "api", "선박호출부호나 입출항제출번호를 입력해주세요.")

    result = _call("arrival_sea", params, "입항보고내역")
    if not result["success"]:
        return result
    root = result["data"]

    rows = [{
        "manifest_no": _text(row, "mrn"),
        "vessel": _text(row, "shipFlgtNm"),
        "imo_no": _text(row, "shipCallImoNo"),
        "country_code": _text(row, "shipAirCntyCd"),
        "arrived_at": _text(row, "etprDttm"),
        "accepted_at": _text(row, "acptDttm"),
        "berth": _text(row, "shipLamrPlcNm"),
        "berth_code": _text(row, "shipLamrPlcCd"),
        "customs_code": _text(row, "cstmSgn"),
    } for row in _rows(root, "etprRprtQryBrkdQryRsltVo", "etprRprtQryBrkdQryVo")]
    rows = [row for row in rows if row["vessel"] or row["manifest_no"]]
    return ok(rows, "api") if rows else _empty(root, "입항보고내역")


def departure_permit(*, permit_no: str = "", submission_no: str = "",
                     air: bool = False) -> dict:
    """출항허가 내역. 실제 출항 일시와 목적지 항구가 나옵니다."""

    params = {}
    if permit_no:
        params["tkofPermNo"] = "".join(ch for ch in permit_no if ch.isalnum())
    if submission_no:
        params["ioprSbmtNo"] = submission_no.strip().upper()
    if not params:
        return fail("VALIDATION_ERROR", "api", "출항허가번호나 제출번호를 입력해주세요.")

    result = _call("departure_air" if air else "departure_sea", params, "출항허가")
    if not result["success"]:
        return result
    root = result["data"]

    rows = [{
        "vessel_or_flight": _text(row, "shipFlgtNm"),
        "country_code": _text(row, "shipAirCntyCd"),
        "call_sign": _text(row, "shipCallImoNo"),
        "departed_at": _text(row, "tkofDttm"),
        "destination_port": _text(row, "arvlCntyPortAirptCd"),
        "next_port": _text(row, "nextPortAirptCd"),
        "cargo_type": _text(row, "ioprCargCdNm"),
        "loaded_tons": _text(row, "loadTtn") or _text(row, "loadWght"),
        "dangerous_tons": _text(row, "dnarWght"),
        "master": _text(row, "masrPiltNm"),
        "issued_by": _text(row, "audtEmpSgn"),
    } for row in _rows(root, "tkofWrprQryRsltVo", "tkofWrprQryVo")]
    rows = [row for row in rows if row["vessel_or_flight"]]
    return ok(rows, "api") if rows else _empty(root, "출항허가")


# --- 9. 재수출 (수리·전시·임대로 들여온 물건을 다시 내보낼 때) -----------------

def reexport_status(declaration_no: str) -> dict:
    """재수출 조건으로 들여온 물건의 이행 기한과 남은 수량.

    고쳐서 돌려보내거나 전시 후 반출하는 건은 기한을 넘기면 관세를 물립니다.
    """

    number = "".join(ch for ch in (declaration_no or "") if ch.isalnum())
    if not number:
        return fail("VALIDATION_ERROR", "api", "수입신고번호를 입력해주세요.")

    deadline = _call("reexport_deadline", {"impDclrNo": number}, "재수출 이행기한")
    balance = _call("reexport_balance", {"impDclrNo": number}, "재수출면세 잔량")

    rows = []
    if deadline["success"]:
        for row in _rows(deadline["data"], "rexpFfmnTmlmInfoQryRsltVo",
                         "rexpFfmnTmlmInfoQryVo"):
            rows.append({"kind": "기한",
                         "deadline": _iso(_text(row, "rexpFfmnTmlmDt")),
                         "declaration_no": _text(row, "impDclrNo") or number})
    if balance["success"]:
        for row in _rows(balance["data"], "expCmdtRsqtyInfoQryRsltVo",
                         "expCmdtRsqtyInfoQryVo"):
            rows.append({"kind": "잔량",
                         "remaining": _text(row, "rsqty") or _text(row, "rsqtyWght"),
                         "unit": _text(row, "qtyUt") or _text(row, "wghtUt"),
                         "declaration_no": _text(row, "impDclrNo") or number})

    if rows:
        return ok(rows, "api")
    # 둘 다 실패했으면 먼저 온 실패 이유를 그대로 전합니다.
    return deadline if not deadline["success"] else balance


def sources() -> list[dict]:
    """어느 서비스가 지금 쓸 수 있는지. 화면에서 솔직하게 알리는 데 씁니다."""

    keys = get_config("UNIPASS_API_KEYS", {}) or {}
    labels = {
        "requirement_law": "세관장확인대상 (수출요건)",
        "clearance_code": "통관고유부호",
        "refund_rate": "간이정액 환급율표",
        "refund_company": "간이정액 적용업체",
        "declaration_verify": "수출신고필증 검증",
        "shortened_period": "수출이행기간 단축품목",
        "airline_list": "항공사 목록",
        "forwarder_list": "화물운송주선업자 목록",
        "inspection": "검사·검역 결과",
        "attachment": "첨부서류 제출유무",
        "correction": "통관단일창구 처리이력",
        "arrival_sea": "입항보고내역",
        "departure_sea": "출항허가(해상)",
    }
    return [{"key": key, "label": label, "env": f"UNIPASS_KEY_{SERVICES[key][0]}",
             "ready": bool(keys.get(SERVICES[key][0]))}
            for key, label in labels.items()]
