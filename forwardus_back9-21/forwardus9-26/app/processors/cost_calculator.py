"""물류비 산출.

부대비용(내륙운송·터미널 처리비·서류비·통관 수수료·도착지 비용)은 아래 표준단가
표에서 뽑습니다. 이 값들은 어디에도 API로 공개되지 않습니다. 포워더마다 계약
단가가 달라 실제 청구액은 견적서를 받아야 확정됩니다. 그래서 "Mock"(가짜)이
아니라 "표준단가"(tariff)로 표시해 추정값임을 분명히 합니다.

해상·항공 운임도 마찬가지로 계약 단가라 공개 API가 없습니다. 스케줄은 선사
API에서 실제로 받아 오지만 운임은 추정치입니다.

계산 자체는 모두 파이썬 코드가 하고, AI는 결과를 설명만 합니다.
"""

from __future__ import annotations

from collections import defaultdict

# Local charges in KRW by service key: (FCL per container, LCL, AIR).
LOCAL_CHARGES_KRW = {
    "origin_trucking": {"FCL": 260_000, "LCL": 180_000, "AIR": 150_000},
    "terminal_handling": {"FCL": 210_000, "LCL": 168_000, "AIR": 125_000},
    "destination_charge": {"FCL": 410_000, "LCL": 230_000, "AIR": 145_000},
}
DOCUMENTATION_FEE_KRW = {"SEA": 65_000, "AIR": 45_000}
EXPORT_CUSTOMS_FEE_KRW = 55_000
LCL_CFS_CHARGE_KRW_PER_RT = 18_000
INSURANCE_RATE = 0.0035
INSURANCE_MIN_KRW = 10_000

# Which party pays which cost group under each Incoterm (exporter-side view).
EXPORTER_PAYS = {
    "EXW": set(),
    "FCA": {"origin"},
    "FAS": {"origin"},
    "FOB": {"origin"},
    "CFR": {"origin", "freight"},
    "CIF": {"origin", "freight", "insurance"},
    "CPT": {"origin", "freight"},
    "CIP": {"origin", "freight", "insurance"},
    "DAP": {"origin", "freight", "destination"},
    "DPU": {"origin", "freight", "destination"},
    "DDP": {"origin", "freight", "destination", "import"},
}

# Incoterms 2020 11개 규칙. 카드·툴팁·그림 팝업·상담 안내가 모두 이 표 하나를 씁니다.
# 설명을 고칠 때는 여기만 고치면 화면 세 곳이 함께 바뀝니다. (ICC Incoterms 2020 규칙
# A2/B2 인도, A3/B3 위험, A5 보험, A7/B7 통관, A9/B9 비용 배분을 기준으로 적었습니다)
#
#   short        카드에 들어가는 한두 줄. 다른 카드를 읽지 않아도 이해되게 씁니다.
#   summary      그림 팝업 머리에 쓰는 한 문장 요약
#   risk         위험이 Buyer에게 넘어가는 시점
#   seller_cost  판매자가 주로 내는 비용 / buyer_cost  Buyer가 주로 내는 비용
#   detail       처음 쓰는 분을 위한 풀이 / caution  자주 헷갈리는 부분
#   duties       보험·통관·적재·하역 의무. (누구, 설명) 쌍입니다.
#   flow         그림 팝업의 구간별 비용 부담(INCOTERMS_FLOW_STEPS 순서)과 위험 이전 지점
#
# flow.costs 값: S 판매자, B Buyer, P 인도 장소에 따라 다름, C 운송계약·목적지 확인
# flow.risk_at: 위험이 넘어가는 구간 경계(0 = 첫 구간 앞, 8 = 마지막 구간 뒤).
#               [a, b]이면 계약한 장소에 따라 그 사이 어딘가입니다.
INCOTERMS_FLOW_STEPS = [
    {"key": "origin_loading", "icon": "factory", "label": "출발지 적재",
     "note": "판매자 사업장에서 차량에 싣기"},
    {"key": "pre_carriage", "icon": "truck", "label": "출발지 내륙운송",
     "note": "사업장 → 터미널·항구·공항"},
    {"key": "origin_terminal", "icon": "terminal", "label": "출발지 터미널",
     "note": "터미널 반입·보관·처리비"},
    {"key": "main_loading", "icon": "crane", "label": "본선·항공기 적재",
     "note": "주운송 수단에 싣기"},
    {"key": "main_carriage", "icon": "main", "label": "주운송",
     "note": "해상·항공 등 국제 운임"},
    {"key": "dest_terminal", "icon": "crane", "label": "도착지 양하·터미널",
     "note": "도착항·공항에서 내리기·처리비"},
    {"key": "on_carriage", "icon": "truck", "label": "도착지 내륙운송",
     "note": "터미널 → 지정 목적지"},
    {"key": "dest_unloading", "icon": "warehouse", "label": "목적지 양하",
     "note": "지정 목적지에서 내리기"},
]

_NO_INSURANCE = ("none", "양측 모두 상대방을 위해 보험에 들 의무는 없습니다. 위험을 지는 쪽이 "
                         "필요하면 스스로 가입합니다.")
_EXPORT_BY_SELLER = ("seller", "판매자 의무 — 수출신고와 수출 허가·검사 비용")
_IMPORT_BY_BUYER = ("buyer", "Buyer 의무 — 수입신고, 관세·부가세 등 수입 제세. 판매자는 요청 시 서류·정보 협조")
_UNLOAD_BY_BUYER = ("buyer", "Buyer 의무 — 도착지에서 물품을 내리는 일과 그 비용")


def _unload_under_carriage(place: str) -> tuple[str, str]:
    return ("buyer", f"Buyer 의무 — 다만 판매자가 맺은 운송계약에 {place} 양하비가 들어 있으면 "
                     "그 비용은 판매자가 부담합니다. (운송계약 확인)")


INCOTERMS_INFO = [
    {"code": "EXW", "name": "Ex Works", "label": "공장 인도", "group": "E",
     "short": "판매자 사업장에서 Buyer가 인수",
     "summary": "판매자 사업장에서 인도하고, 싣는 일부터 운송·수출통관은 Buyer가 맡습니다.",
     "risk": "판매자 사업장 등 지정 장소에서 물품을 Buyer가 가져갈 수 있게 둔 때(싣기 전)",
     "seller_cost": "물품 준비·포장·화인, 인도 장소에서 넘겨주기까지의 비용",
     "buyer_cost": "적재, 모든 운송비, 수출·수입통관, 관세 등 인도 이후 모든 비용",
     "detail": "판매자는 자기 공장·창고 등 약정한 장소에서 물품을 Buyer가 가져갈 수 있게 준비해 두면 "
               "인도가 끝납니다. 차에 싣는 일, 수출통관, 운송은 Buyer가 맡습니다. 그래도 판매자에게는 "
               "물품·상업송장 제공, 포장·화인, 인도 준비 통지, 통관에 필요한 정보 협조 의무가 있습니다.",
     "caution": "판매자 의무가 '전혀 없는' 조건은 아닙니다. 수출신고가 Buyer 몫이라 외국 Buyer가 한국에서 "
                "직접 신고하기 어렵고 수출실적 관리도 까다로워, 실무에서는 FCA를 더 권합니다.",
     "duties": {
         "insurance": _NO_INSURANCE,
         "export": ("buyer", "Buyer 의무 — 판매자는 요청받으면 필요한 정보·서류를 협조합니다"),
         "import": _IMPORT_BY_BUYER,
         "loading": ("buyer", "판매자는 차량에 싣지 않아도 됩니다. 실무상 실어 주더라도 그 위험·비용은 Buyer 몫입니다"),
         "unloading": _UNLOAD_BY_BUYER,
     },
     "flow": {"costs": "BBBBBBBB", "risk_at": 0,
              "risk_label": "판매자 사업장 등 지정 장소(싣기 전)"}},
    {"code": "FCA", "name": "Free Carrier", "label": "운송인 인도", "group": "F",
     "short": "Buyer가 지정한 운송인에게 인도",
     "summary": "판매자가 수출통관 후 약정 장소에서 Buyer가 지정한 운송인에게 넘깁니다.",
     "risk": "지정 인도장소에서 Buyer가 지정한 운송인에게 넘긴 때",
     "seller_cost": "수출통관, 지정 인도장소까지 운송(사업장 인도면 적재까지)",
     "buyer_cost": "주운송 운임, 도착지 비용, 수입통관·관세",
     "detail": "판매자가 수출통관을 마치고, 약정한 장소에서 Buyer가 지정한 운송인에게 물품을 넘기면 "
               "인도가 끝납니다. 판매자 사업장에서 넘기면 Buyer 쪽 차량에 싣는 것까지 판매자가 하고, "
               "터미널 등 다른 장소면 판매자 차량에 실린 채 내릴 준비가 된 상태로 넘깁니다.",
     "caution": "컨테이너·항공 화물에 가장 알맞은 조건입니다. 2020 개정으로, 합의하면 Buyer가 운송인에게 "
                "지시해 판매자가 본선적재 선하증권(On-board B/L)을 받을 수 있습니다.",
     "duties": {
         "insurance": _NO_INSURANCE,
         "export": _EXPORT_BY_SELLER,
         "import": _IMPORT_BY_BUYER,
         "loading": ("varies", "판매자 사업장 인도: 판매자가 Buyer 쪽 차량에 싣습니다. 다른 장소 인도: 판매자 "
                               "차량에 실린 채 넘기고, 내리는 일은 Buyer가 합니다"),
         "unloading": _UNLOAD_BY_BUYER,
     },
     "flow": {"costs": "SPBBBBBB", "risk_at": [1, 2],
              "risk_label": "지정 인도장소 — 사업장이면 싣고 난 뒤, 다른 장소면 내리기 전"}},
    {"code": "FAS", "name": "Free Alongside Ship", "label": "선측 인도", "group": "F", "sea_only": True,
     "short": "선적항 본선 옆에 두면 인도",
     "summary": "판매자가 수출통관 후 선적항에서 본선 옆(선측)에 물품을 가져다 둡니다.",
     "risk": "지정 선적항에서 본선 옆(부두·부선)에 물품을 둔 때",
     "seller_cost": "수출통관, 선적항 본선 옆까지 운송",
     "buyer_cost": "본선 적재, 해상운임, 도착지 비용, 수입통관·관세",
     "detail": "판매자가 수출통관을 마치고 선적항에서 Buyer가 지정한 본선 옆(부두 또는 부선 위)에 "
               "물품을 두면 인도가 끝납니다. 본선에 싣는 비용과 그 이후 위험은 Buyer가 집니다.",
     "caution": "곡물·광석처럼 컨테이너에 넣지 않는 벌크 화물에 씁니다. 컨테이너는 터미널에 미리 반입하므로 "
                "FCA가 맞습니다.",
     "duties": {
         "insurance": _NO_INSURANCE,
         "export": _EXPORT_BY_SELLER,
         "import": _IMPORT_BY_BUYER,
         "loading": ("buyer", "본선 적재는 Buyer가 합니다. 판매자는 본선 옆까지만 가져다 둡니다"),
         "unloading": _UNLOAD_BY_BUYER,
     },
     "flow": {"costs": "SSSBBBBB", "risk_at": 3,
              "risk_label": "지정 선적항의 본선 옆(선측)"}},
    {"code": "FOB", "name": "Free On Board", "label": "본선 인도", "group": "F", "sea_only": True,
     "short": "선적항에서 본선에 실으면 인도",
     "summary": "판매자가 수출통관 후 선적항에서 Buyer가 지정한 본선에 물품을 싣습니다.",
     "risk": "지정 선적항에서 본선에 적재된 때",
     "seller_cost": "수출통관, 선적항 본선 적재까지의 비용",
     "buyer_cost": "해상운임, 도착지 비용, 수입통관·관세",
     "detail": "판매자가 수출통관을 마치고 선적항에서 Buyer가 지정한 본선에 물품을 실으면 인도가 끝납니다. "
               "해상운임은 Buyer가 운송계약을 맺고 부담합니다.",
     "caution": "컨테이너는 배에 싣기 며칠 전에 터미널에 반입하므로, 그 사이 사고의 책임이 애매해집니다. "
                "컨테이너라면 FOB보다 FCA가 맞습니다.",
     "duties": {
         "insurance": _NO_INSURANCE,
         "export": _EXPORT_BY_SELLER,
         "import": _IMPORT_BY_BUYER,
         "loading": ("seller", "판매자가 본선에 싣는 것까지 합니다"),
         "unloading": _UNLOAD_BY_BUYER,
     },
     "flow": {"costs": "SSSSBBBB", "risk_at": 4,
              "risk_label": "지정 선적항의 본선 위(적재 완료)"}},
    {"code": "CFR", "name": "Cost and Freight", "label": "운임 포함", "group": "C", "sea_only": True,
     "short": "해상운임은 판매자, 위험은 선적 때",
     "summary": "목적항까지 해상운임은 판매자가 내고, 위험은 선적항에서 본선 적재 때 넘어갑니다.",
     "risk": "선적항에서 본선에 적재된 때(목적항 도착 전)",
     "seller_cost": "수출통관, 본선 적재, 목적항까지 해상운임",
     "buyer_cost": "운송계약에 없는 목적항 양하·도착지 비용, 수입통관·관세",
     "detail": "판매자가 운송계약을 맺고 목적항까지 해상운임을 냅니다. 그러나 위험은 선적항에서 본선에 "
               "적재된 때 이미 Buyer에게 넘어가므로, 항해 중 사고의 손해는 Buyer가 집니다.",
     "caution": "비용이 넘어가는 지점(목적항)과 위험이 넘어가는 지점(선적항 본선)이 다릅니다. 판매자에게 "
                "보험 가입 의무가 없으니 Buyer가 필요하면 직접 들어야 합니다.",
     "duties": {
         "insurance": _NO_INSURANCE,
         "export": _EXPORT_BY_SELLER,
         "import": _IMPORT_BY_BUYER,
         "loading": ("seller", "판매자가 본선에 싣고, 목적항까지 운임도 냅니다"),
         "unloading": _unload_under_carriage("목적항"),
     },
     "flow": {"costs": "SSSSSCBB", "risk_at": 4,
              "risk_label": "선적항의 본선 위(적재 완료)"}},
    {"code": "CIF", "name": "Cost, Insurance and Freight", "label": "운임·보험 포함", "group": "C",
     "sea_only": True,
     "short": "해상운임·보험은 판매자, 위험은 선적 때",
     "summary": "목적항까지 해상운임과 최소 담보 적하보험은 판매자가, 위험은 본선 적재 때 넘어갑니다.",
     "risk": "선적항에서 본선에 적재된 때(목적항 도착 전)",
     "seller_cost": "수출통관, 본선 적재, 목적항까지 해상운임, 적하보험료",
     "buyer_cost": "운송계약에 없는 목적항 양하·도착지 비용, 수입통관·관세, 추가 담보 보험료",
     "detail": "판매자가 목적항까지 해상운임을 내고 Buyer를 위한 적하보험에도 가입합니다. 위험은 선적항에서 "
               "본선에 적재된 때 Buyer에게 넘어가며, 항해 중 사고는 그 보험으로 Buyer가 보상받습니다.",
     "caution": "판매자의 보험 의무는 최소 담보(ICC(C)), 보험금액은 매매대금의 110% 이상입니다. 더 넓은 "
                "담보가 필요하면 계약서에 따로 적어야 합니다. 컨테이너 화물에는 CIP가 더 맞습니다.",
     "duties": {
         "insurance": ("seller", "판매자 의무 — 최소 담보 ICC(C) 수준, 매매대금의 110% 이상. 더 넓은 담보는 "
                                 "계약에 따로 정해야 합니다"),
         "export": _EXPORT_BY_SELLER,
         "import": _IMPORT_BY_BUYER,
         "loading": ("seller", "판매자가 본선에 싣고, 목적항까지 운임도 냅니다"),
         "unloading": _unload_under_carriage("목적항"),
     },
     "flow": {"costs": "SSSSSCBB", "risk_at": 4,
              "risk_label": "선적항의 본선 위(적재 완료)"}},
    {"code": "CPT", "name": "Carriage Paid To", "label": "운송비 지급", "group": "C",
     "short": "운송비는 판매자, 위험은 인도 때",
     "summary": "지정 목적지까지 운송비는 판매자가 내고, 위험은 첫 운송인에게 넘길 때 이전됩니다.",
     "risk": "약정 인도지에서 첫 운송인에게 인도한 때(목적지 도착 전)",
     "seller_cost": "수출통관, 지정 목적지까지 운송비",
     "buyer_cost": "운송계약에 없는 도착지 비용, 수입통관·관세",
     "detail": "판매자가 운송계약을 맺고 지정 목적지까지 운송비를 냅니다. 위험은 약정 인도지에서 첫 "
               "운송인에게 물품을 넘긴 때 Buyer에게 넘어갑니다. 항공·복합운송을 포함한 모든 운송수단에 씁니다.",
     "caution": "비용은 목적지까지, 위험은 출발지 쪽 인도 시점까지라 둘이 다릅니다. 인도지를 정하지 않으면 "
                "판매자가 고른 첫 운송인 인도 때 위험이 넘어가므로 계약서에 인도지도 적어 두세요. "
                "판매자에게 보험 가입 의무는 없습니다.",
     "duties": {
         "insurance": _NO_INSURANCE,
         "export": _EXPORT_BY_SELLER,
         "import": _IMPORT_BY_BUYER,
         "loading": ("seller", "판매자가 운송계약을 맺고 약정 인도지에서 운송인에게 넘깁니다"),
         "unloading": _unload_under_carriage("목적지"),
     },
     "flow": {"costs": "SSSSSCCC", "risk_at": [1, 3],
              "risk_label": "약정 인도지에서 첫 운송인에게 넘길 때(계약마다 다름)"}},
    {"code": "CIP", "name": "Carriage and Insurance Paid To", "label": "운송비·보험 지급", "group": "C",
     "short": "운송비·보험은 판매자, 위험은 인도 때",
     "summary": "지정 목적지까지 운송비와 넓은 담보 적하보험은 판매자가, 위험은 운송인 인도 때 넘어갑니다.",
     "risk": "약정 인도지에서 첫 운송인에게 인도한 때(목적지 도착 전)",
     "seller_cost": "수출통관, 지정 목적지까지 운송비, 적하보험료(ICC(A))",
     "buyer_cost": "운송계약에 없는 도착지 비용, 수입통관·관세",
     "detail": "판매자가 지정 목적지까지 운송비를 내고 Buyer를 위한 적하보험에도 가입합니다. 위험은 약정 "
               "인도지에서 첫 운송인에게 넘긴 때 이전됩니다. 모든 운송수단에 쓸 수 있어 항공·컨테이너 "
               "화물에서 CIF 대신 씁니다.",
     "caution": "2020 개정으로 판매자는 ICC(A) 수준의 넓은 담보로 매매대금의 110% 이상 보험에 들어야 합니다"
                "(당사자 합의로 낮출 수 있음). 최소 담보 ICC(C)면 되는 CIF와 다릅니다.",
     "duties": {
         "insurance": ("seller", "판매자 의무 — ICC(A) 수준(면책위험을 뺀 전위험 담보), 매매대금의 110% 이상. "
                                 "합의하면 낮출 수 있습니다"),
         "export": _EXPORT_BY_SELLER,
         "import": _IMPORT_BY_BUYER,
         "loading": ("seller", "판매자가 운송계약을 맺고 약정 인도지에서 운송인에게 넘깁니다"),
         "unloading": _unload_under_carriage("목적지"),
     },
     "flow": {"costs": "SSSSSCCC", "risk_at": [1, 3],
              "risk_label": "약정 인도지에서 첫 운송인에게 넘길 때(계약마다 다름)"}},
    {"code": "DAP", "name": "Delivered at Place", "label": "도착지 인도", "group": "D",
     "short": "목적지 도착 후 내리기 전 인도",
     "summary": "판매자가 지정 목적지까지 운송해 내리기 전 상태로 인도하고, 수입통관은 Buyer가 합니다.",
     "risk": "지정 목적지에 도착해 운송수단 위에서 내릴 준비가 된 때",
     "seller_cost": "수출통관, 지정 목적지까지 모든 운송비",
     "buyer_cost": "목적지 하역(운송계약에 없으면), 수입통관·관세",
     "detail": "판매자가 지정 목적지까지 운송하고, 도착한 운송수단 위에서 내리지 않은 상태로 Buyer에게 "
               "넘깁니다. 물품을 내리는 일과 수입통관·관세는 Buyer가 맡습니다.",
     "caution": "목적지 하역 의무는 Buyer이지만, 판매자의 운송계약에 하역비가 들어 있으면 그 비용은 판매자가 "
                "부담합니다. 목적지는 항구·창고 등 계약마다 다르니 주소를 정확히 적으세요.",
     "duties": {
         "insurance": _NO_INSURANCE,
         "export": _EXPORT_BY_SELLER,
         "import": _IMPORT_BY_BUYER,
         "loading": ("seller", "판매자가 목적지까지 운송을 맡습니다"),
         "unloading": _unload_under_carriage("목적지"),
     },
     "flow": {"costs": "SSSSSSSC", "risk_at": 7,
              "risk_label": "지정 목적지(내리기 전)"}},
    {"code": "DPU", "name": "Delivered at Place Unloaded", "label": "도착지 양하 인도", "group": "D",
     "short": "목적지에서 물품을 내려서 인도",
     "summary": "판매자가 지정 목적지까지 운송하고 물품을 내려서 인도합니다. 수입통관은 Buyer가 합니다.",
     "risk": "지정 목적지에서 물품을 내린 뒤 넘긴 때",
     "seller_cost": "수출통관, 지정 목적지까지 운송비와 목적지 양하 비용",
     "buyer_cost": "수입통관·관세, 인도 이후 비용",
     "detail": "판매자가 지정 목적지까지 실어다 주고 물품을 내리는 것까지 책임집니다. "
               "11개 조건 가운데 판매자가 목적지 양하 의무를 지는 유일한 조건입니다.",
     "caution": "2020년에 DAT(터미널 인도)를 대신해 생겼습니다. 터미널뿐 아니라 어떤 장소든 지정할 수 있으니, "
                "그곳에서 판매자가 물품을 내릴 수 있는지 미리 확인해야 합니다.",
     "duties": {
         "insurance": _NO_INSURANCE,
         "export": _EXPORT_BY_SELLER,
         "import": _IMPORT_BY_BUYER,
         "loading": ("seller", "판매자가 목적지까지 운송을 맡습니다"),
         "unloading": ("seller", "판매자 의무 — 지정 목적지에서 물품을 내려 인도합니다"),
     },
     "flow": {"costs": "SSSSSSSS", "risk_at": 8,
              "risk_label": "지정 목적지(내린 뒤)"}},
    {"code": "DDP", "name": "Delivered Duty Paid", "label": "관세 지급 인도", "group": "D",
     "short": "수입통관·관세까지 판매자 부담",
     "summary": "판매자가 수입통관·관세까지 마치고 지정 목적지에서 내리기 전 상태로 인도합니다.",
     "risk": "수입통관을 마치고 지정 목적지에서 내릴 준비가 된 때",
     "seller_cost": "수출·수입통관, 관세·부가세, 지정 목적지까지 운송비",
     "buyer_cost": "목적지 하역(운송계약에 없으면)",
     "detail": "판매자가 수출통관, 지정 목적지까지 운송, 수입통관과 관세·부가세 납부까지 맡습니다. "
               "목적지에 도착해 내리기 전 상태로 넘기므로, 물품을 내리는 일은 Buyer 몫입니다.",
     "caution": "판매자 부담이 가장 큰 조건입니다. 수입통관·관세를 판매자가 낸다고 목적지 하역까지 맡는 것은 "
                "아닙니다. 수입국에서 판매자가 수입신고를 할 수 없는 경우가 많으니 미리 확인하세요.",
     "duties": {
         "insurance": _NO_INSURANCE,
         "export": _EXPORT_BY_SELLER,
         "import": ("seller", "판매자 의무 — 수입신고와 관세·부가세 등 수입 제세 납부"),
         "loading": ("seller", "판매자가 목적지까지 운송을 맡습니다"),
         "unloading": _unload_under_carriage("목적지"),
     },
     "flow": {"costs": "SSSSSSSC", "risk_at": 7,
              "risk_label": "지정 목적지(수입통관 후, 내리기 전)"}},
]


def calculate_insurance_premium(
    invoice_value_usd: float,
    freight_usd: float,
    exchange_rate: float,
    insurance_rate: float = INSURANCE_RATE,
) -> float:
    """Cargo insurance premium in KRW on CIF value × 110 %."""

    insured_value_usd = (invoice_value_usd + freight_usd) * 1.1
    return max(INSURANCE_MIN_KRW, insured_value_usd * insurance_rate * exchange_rate)


def _line(category: str, group: str, code: str, name: str, currency: str, amount: float, exchange_rate: float, source: str) -> dict:
    krw = amount if currency == "KRW" else amount * exchange_rate
    return {
        "category": category,
        "group": group,
        "code": code,
        "name": name,
        "original_currency": currency,
        "original_amount": round(amount, 2),
        "krw_amount": round(krw),
        "source": source,
    }


def calculate_logistics_cost(
    *,
    transport_mode: str,
    sea_mode: str | None,
    incoterms: str,
    freight_usd: float,
    freight_source: str,
    invoice_value_usd: float,
    metrics: dict,
    exchange_rate: float,
    exchange_source: str = "mock",
) -> dict:
    """Build an itemized logistics cost estimate in KRW."""

    service = "AIR" if transport_mode == "AIR" else (sea_mode or "FCL")
    containers = (metrics.get("container_quantity") or 1) if service == "FCL" else 1
    # 표준단가 표에서 뽑은 추정값. 실제 청구액은 포워더 견적으로 확정됩니다.
    rate_source = "tariff"

    lines = [
        _line("Origin Charge", "origin", "origin_trucking", "출발지 내륙운송", "KRW",
              LOCAL_CHARGES_KRW["origin_trucking"][service] * containers, exchange_rate, rate_source),
        _line("Origin Charge", "origin", "terminal_handling", "터미널 처리비(THC)", "KRW",
              LOCAL_CHARGES_KRW["terminal_handling"][service] * containers, exchange_rate, rate_source),
        _line("Origin Charge", "origin", "documentation", "AWB 발행비" if service == "AIR" else "B/L 발행비", "KRW",
              DOCUMENTATION_FEE_KRW["AIR" if service == "AIR" else "SEA"], exchange_rate, rate_source),
        _line("Customs", "origin", "export_customs", "수출통관 수수료", "KRW",
              EXPORT_CUSTOMS_FEE_KRW, exchange_rate, rate_source),
    ]
    if service == "LCL":
        lines.append(_line("Origin Charge", "origin", "cfs_charge", "CFS 작업료", "KRW",
                           LCL_CFS_CHARGE_KRW_PER_RT * metrics.get("billable_revenue_ton", 1), exchange_rate, "calculated"))

    lines.append(_line("Freight", "freight", "freight", "항공운임" if service == "AIR" else "해상운임", "USD",
                       freight_usd, exchange_rate, freight_source))

    insurance_krw = calculate_insurance_premium(invoice_value_usd, freight_usd, exchange_rate)
    lines.append(_line("Insurance", "insurance", "insurance", "적하보험료", "KRW", insurance_krw, exchange_rate, "calculated"))
    lines.append(_line("Destination Charge", "destination", "destination_charge", "도착지 비용(THC·D/O)", "KRW",
                       LOCAL_CHARGES_KRW["destination_charge"][service] * containers, exchange_rate, rate_source))

    exporter_groups = EXPORTER_PAYS.get(incoterms, set())
    for line in lines:
        line["payer"] = "exporter" if line["group"] in exporter_groups else "buyer"

    category_totals: dict[str, int] = defaultdict(int)
    for line in lines:
        category_totals[line["category"]] += line["krw_amount"]

    total = sum(line["krw_amount"] for line in lines)
    exporter_total = sum(line["krw_amount"] for line in lines if line["payer"] == "exporter")
    return {
        "lines": lines,
        "category_totals": dict(category_totals),
        "total_krw": total,
        "exporter_total_krw": exporter_total,
        "buyer_total_krw": total - exporter_total,
        "exchange_rate": exchange_rate,
        "exchange_source": exchange_source,
    }
