"""관세청에 직접 물어보는 조회 모음.

지금까지는 운송 계획이나 서류 화면 안에서만 쓰던 관세청 자료를, 한 자리에서
바로 찾아볼 수 있게 모았습니다. 부킹 전에 선사 부호를 확인하거나, 받은
수출신고필증이 진짜인지 대조하는 것처럼 화면 흐름과 상관없이 필요한 것들입니다.

무엇이 되고 무엇이 안 되는지는 `catalog()`가 솔직하게 알려 줍니다.
"""

from __future__ import annotations

from app.collectors import carrier_client, customs_client, customs_extra_client
from app.services import ServiceError

# 조회 종류. key는 화면에서 고르는 값입니다.
LOOKUPS = {
    "shipping_company": {
        "label": "선사",
        "hint": "한글 상호로 찾습니다. (영문 상호로는 조회되지 않습니다)",
        "example": "에이치엠엠",
        "field": "선사명",
        "about": "B/L과 수출신고서에 쓰는 공식 선사부호를 확인합니다.",
    },
    "airline": {
        "label": "항공사",
        "hint": "한글 또는 영문 항공사명으로 찾습니다.",
        "example": "대한항공",
        "field": "항공사명",
        "about": "AWB와 수출신고서에 쓰는 항공사부호를 확인합니다.",
    },
    "forwarder": {
        "label": "포워더",
        "hint": "화물운송주선업자 상호로 찾습니다.",
        "example": "판토스",
        "field": "포워더 상호",
        "about": "등록된 포워더인지, 부호와 연락처가 무엇인지 봅니다.",
    },
    "clearance_code": {
        "label": "통관고유부호",
        "hint": "사업자등록번호 10자리를 넣습니다.",
        "example": "1248100998",
        "field": "사업자등록번호",
        "about": "수출신고서의 법정 기재사항입니다. 없으면 신고를 시작할 수 없습니다.",
    },
    "requirement_law": {
        "label": "수출요건 (세관장확인대상)",
        "hint": "HS부호 10자리를 넣습니다.",
        "example": "3305100000",
        "field": "HS부호",
        "about": "관세법 제226조에 따라 세관장이 확인하는 품목인지 봅니다.",
    },
    "refund_rate": {
        "label": "간이정액 환급율",
        "hint": "HS부호 10자리를 넣습니다.",
        "example": "3305100000",
        "field": "HS부호",
        "about": "수출한 뒤 돌려받을 수 있는 금액의 고시 단가입니다.",
    },
    "shortened_period": {
        "label": "수출이행기간 단축품목",
        "hint": "HS부호 10자리를 넣습니다.",
        "example": "3305100000",
        "field": "HS부호",
        "about": "적재기한이 30일보다 짧아지는 품목인지 봅니다.",
    },
    "trade_stats": {
        "label": "수출 실적 (이 품목이 어디로 나가나)",
        "hint": "HS부호 4~10자리를 넣습니다. 최근 1년 실적입니다.",
        "example": "3305",
        "field": "HS부호",
        "about": "이 품목을 어느 나라로 얼마나 내보내는지 봅니다. 시장을 고를 때 씁니다.",
    },
    "hs_code": {
        "label": "HS부호",
        "hint": "품명(한글)이나 HS부호 10자리로 찾습니다.",
        "example": "샴푸",
        "field": "품명 또는 HS부호",
        "about": "관세율표에 적힌 품명으로 찾습니다.",
    },
}

# 조회마다 어떤 환경변수 키를 쓰는지. 화면에서 준비 상태를 보여 줍니다.
KEY_NAMES = {
    "shipping_company": "SHIPPING_COMPANY_LIST",
    "airline": "AIRLINE_LIST",
    "forwarder": "FORWARDER_LIST",
    "clearance_code": "CUSTOMS_CLEARANCE_CODE",
    "requirement_law": "REQUIREMENT_APPROVAL",
    "refund_rate": "SIMPLE_REFUND_RATE",
    "shortened_period": "EXPORT_PERIOD_SHORTENING_ITEM",
    "hs_code": "HS_CODE_SEARCH",
}

# 관세청이 아닌 곳에서 오는 조회. 키 이름이 다릅니다.
OTHER_KEYS = {"trade_stats": "DATA_GO_KR_SERVICE_KEY"}

# 결과 표의 칸. (키, 보여 줄 이름)
COLUMNS = {
    "shipping_company": [("code", "선사부호"), ("korean_name", "한글 상호"),
                         ("english_name", "영문 상호"), ("representative", "대표자")],
    "airline": [("code", "항공사부호"), ("korean_name", "한글 상호"),
                ("english_name", "영문 상호"), ("representative", "대표자")],
    "forwarder": [("code", "부호"), ("korean_name", "한글 상호"),
                  ("english_name", "영문 상호"), ("representative", "대표자")],
    "clearance_code": [("clearance_code", "통관고유부호"), ("name", "상호"),
                       ("business_no", "사업자등록번호"), ("representative", "대표자")],
    "requirement_law": [("law_name", "법령"), ("agency", "요건승인기관"),
                        ("document", "확인 서류"), ("start_date", "적용 시작")],
    "refund_rate": [("hs_code", "HS부호"), ("spec", "규격"),
                    ("amount_krw", "환급액(원)"), ("basis", "기준"), ("start_date", "적용일")],
    "shortened_period": [("hs_code", "HS부호"), ("product", "품명"),
                         ("spec", "규격"), ("deadline", "이행기한")],
    "hs_code": [("code", "HS부호"), ("name", "품명"),
                ("quantity_unit", "수량단위"), ("weight_unit", "중량단위")],
    "trade_stats": [("country", "나라"), ("export_usd_thousand", "수출액(천달러)"),
                    ("export_weight_kg", "수출중량(kg)"),
                    ("import_usd_thousand", "수입액(천달러)"), ("period", "기간")],
}


def catalog() -> list[dict]:
    """조회 목록과 지금 쓸 수 있는지."""

    from app.collectors.base_client import get_config

    keys = get_config("UNIPASS_API_KEYS", {}) or {}
    rows = []
    for key, info in LOOKUPS.items():
        if key in OTHER_KEYS:
            env = OTHER_KEYS[key]
            ready = bool(get_config(env, ""))
        else:
            env = f"UNIPASS_KEY_{KEY_NAMES[key]}"
            ready = bool(keys.get(KEY_NAMES[key]))
        rows.append({"key": key, **info, "env": env, "ready": ready})
    return rows


def run(kind: str, query: str) -> dict:
    """고른 종류로 관세청에 물어봅니다."""

    if kind not in LOOKUPS:
        raise ServiceError("조회 종류를 확인해주세요.", "VALIDATION_ERROR")
    text = (query or "").strip()
    if not text:
        raise ServiceError(f"{LOOKUPS[kind]['field']}을(를) 입력해주세요.", "VALIDATION_ERROR")

    callers = {
        "shipping_company": lambda: carrier_client.search_shipping_companies(text),
        "airline": lambda: customs_extra_client.search_airlines(text),
        "forwarder": lambda: customs_extra_client.search_forwarders(text),
        "clearance_code": lambda: customs_extra_client.clearance_code(business_no=text),
        "requirement_law": lambda: customs_extra_client.export_requirement_laws(text),
        "refund_rate": lambda: customs_extra_client.refund_rate(text),
        "shortened_period": lambda: customs_extra_client.shortened_loading_period(text),
        "hs_code": lambda: customs_client.search_hs_codes(text),
        "trade_stats": lambda: _trade_rows(text),
    }
    result = callers[kind]()
    rows = result["data"] if result["success"] else []
    return {
        "kind": kind,
        "label": LOOKUPS[kind]["label"],
        "query": text,
        "success": result["success"],
        "source": result["source"],
        "message": result.get("message", ""),
        "columns": [{"key": key, "label": label} for key, label in COLUMNS[kind]],
        "rows": rows if isinstance(rows, list) else [rows],
    }


def _trade_rows(hs_code: str) -> dict:
    """무역통계는 결과가 dict로 와서 표에 맞게 줄 목록으로 폅니다."""

    from app.collectors import trade_stats_client

    result = trade_stats_client.top_destinations(hs_code)
    if not result["success"]:
        return result
    return {**result, "data": result["data"]["rows"]}


def verify_declaration(form: dict) -> dict:
    """받은 수출신고필증이 관세청 기록과 맞는지 대조합니다.

    여섯 가지가 모두 맞아야 "일치"가 나옵니다. 하나라도 다르면 위조이거나
    옮겨 적다 틀린 것입니다.
    """

    fields = {key: str(form.get(key) or "").strip() for key in
              ("publication_no", "declaration_no", "business_no",
               "origin_country", "product_name", "net_weight_kg")}
    missing = [key for key, value in fields.items() if not value]
    if missing:
        labels = {"publication_no": "발행번호", "declaration_no": "신고번호",
                  "business_no": "수출화주 사업자등록번호", "origin_country": "원산지 코드",
                  "product_name": "품명", "net_weight_kg": "순중량"}
        raise ServiceError(f"{'·'.join(labels[key] for key in missing)}을(를) 입력해주세요.",
                           "VALIDATION_ERROR")

    result = customs_extra_client.verify_export_declaration(**fields)
    if not result["success"]:
        return {"available": False, "message": result["message"], "source": result["source"]}
    return {"available": True, "source": "api", **result["data"],
            "note": ("여섯 항목이 모두 맞아야 일치로 나옵니다. "
                     "일치하지 않으면 옮겨 적은 값을 먼저 확인해 주세요.")}


# 이 앱이 쓰는 바깥 자료원 전부. 무엇이 연결됐고 무엇이 비었는지 한눈에 봅니다.
def data_sources() -> dict:
    """연결된 API와 아직 키가 없는 API를 모아 돌려줍니다."""

    from app.collectors import ai_client, carrier_client
    from app.collectors.base_client import get_config

    unipass = get_config("UNIPASS_API_KEYS", {}) or {}
    groups = [
        {
            "title": "관세청 UNI-PASS",
            "note": "서비스마다 키가 따로입니다. 유니패스 My메뉴에서 신청합니다.",
            "signup": "https://unipass.customs.go.kr",
            "rows": [{"label": label, "env": f"UNIPASS_KEY_{name}",
                       "ready": bool(unipass.get(name)), "used": name in _USED_UNIPASS}
                      for name, label in _unipass_services().items()],
        },
        {
            "title": "선사 · 공항",
            "note": "스케줄은 선사·공항이 따로 냅니다. 운임은 어디서도 공개하지 않습니다.",
            "signup": "https://apiportal.hmm21.com/signup",
            "rows": [{"label": row["label"], "env": row["env"], "ready": row["ready"],
                       "used": True, "signup": row.get("signup", "")}
                      for row in carrier_client.sources()],
        },
        {
            "title": "그 밖",
            "note": "환율은 관세청 고시환율을 씁니다. AI는 서류 대조와 상담에 씁니다.",
            "signup": "",
            "rows": [
                {"label": "OpenAI (서류 대조 · 고객 상담)", "env": "AI_API_KEY",
                 "ready": ai_client.available(), "used": True},
                {"label": "공공데이터포털 · 인천공항 화물기 정기운항",
                 "env": "DATA_GO_KR_SERVICE_KEY",
                 "ready": bool(get_config("DATA_GO_KR_SERVICE_KEY", "")), "used": True},
                {"label": "공공데이터포털 · 관세청 수출입무역통계 (활용신청 필요)",
                 "env": "DATA_GO_KR_SERVICE_KEY", "used": True,
                 "ready": _trade_stats_ready(),
                 "signup": "https://www.data.go.kr/tcs/dss/selectDataSetList.do?keyword=수출입무역통계"},
                {"label": "세계은행 WITS · 미국 HTS · 영국 관세율표 (키 없이 씁니다)",
                 "env": "", "ready": True, "used": True},
            ],
        },
    ]
    total = sum(len(group["rows"]) for group in groups)
    ready = sum(1 for group in groups for item in group["rows"] if item["ready"])
    return {"groups": groups, "total": total, "ready": ready}


def _unipass_services() -> dict:
    from config import UNIPASS_SERVICES

    return UNIPASS_SERVICES


# 우리 코드가 실제로 부르는 관세청 서비스.
_USED_UNIPASS = {
    "HS_CODE_SEARCH", "TARIFF_RATE", "STATISTICS_CODE", "CUSTOMS_EXCHANGE_RATE",
    "SHIPPING_COMPANY_LIST", "SHIPPING_COMPANY_DETAIL", "CARGO_CLEARANCE_PROGRESS",
    "CONTAINER_DETAIL", "EXPORT_PERFORMANCE_BY_DECLARATION",
    "REQUIREMENT_APPROVAL", "CUSTOMS_CLEARANCE_CODE", "SIMPLE_REFUND_RATE",
    "SIMPLE_REFUND_COMPANY", "EXPORT_DECLARATION_VERIFY", "EXPORT_PERIOD_SHORTENING_ITEM",
    "AIRLINE_LIST", "AIRLINE_DETAIL", "FORWARDER_LIST", "FORWARDER_DETAIL",
    "INSPECTION_QUARANTINE", "DECLARATION_ATTACHMENT_SUBMISSION",
    "DECLARATION_CORRECTION_STATUS", "ARRIVAL_REPORT_SEA", "ARRIVAL_REPORT_AIR",
    "DEPARTURE_PERMIT_SEA", "DEPARTURE_PERMIT_AIR", "ENTRY_DEPARTURE_REPORT",
    "HS_NAVIGATION", "REEXPORT_EXEMPTION_BALANCE", "EXPORT_PERFORMANCE_BY_VIN",
    "REEXPORT_CONDITIONAL_IMPORT_DEADLINE", "REEXPORT_COMPLETION_REPORT",
}


def _trade_stats_ready() -> bool:
    """무역통계는 키가 있어도 활용신청을 안 하면 열리지 않습니다.

    한 번 불러 봐야 알 수 있어, 화면을 열 때마다 부르지 않도록 결과를 기억합니다.
    """

    from app.collectors import trade_stats_client

    global _TRADE_STATS_READY
    if _TRADE_STATS_READY is None:
        result = trade_stats_client.item_trade("3305")
        _TRADE_STATS_READY = bool(result["success"])
    return _TRADE_STATS_READY


_TRADE_STATS_READY: bool | None = None
