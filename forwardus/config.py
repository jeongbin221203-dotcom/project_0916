"""견적 산출 기준 데이터(샘플) 및 상수 정의.

모든 운임·부대비용·세율·환율은 화면과 계산 로직 검증용 샘플 값임.
실제 서비스에서는 수집 모듈(API·공시 자료) 결과로 대체함.
"""

FX_BASE_DATE = "2026-09-17"
RATE_VALID_UNTIL = "2026-09-30"
FX_RATES = {"KRW": 1.0, "USD": 1418.5, "EUR": 1662.3}

ORIGIN_PORTS = {
    "KRPUS": {"code": "KRPUS", "name": "부산항"},
    "KRINC": {"code": "KRINC", "name": "인천항"},
    "ICN": {"code": "ICN", "name": "인천국제공항"},
}
SEA_ORIGIN_CODES = ("KRPUS", "KRINC")

DESTINATIONS = {
    "US": {"country_name": "미국", "port_code": "USLAX", "port_name": "로스앤젤레스", "airport_code": "LAX", "airport_name": "로스앤젤레스", "local_currency": "USD", "customs_value_basis": "FOB", "vat_rate": 0.0, "fta_name": "한·미 FTA", "season_profile": "TRANSPACIFIC"},
    "VN": {"country_name": "베트남", "port_code": "VNSGN", "port_name": "호치민", "airport_code": "SGN", "airport_name": "호치민", "local_currency": "USD", "customs_value_basis": "CIF", "vat_rate": 0.1, "fta_name": "한·베트남 FTA", "season_profile": "INTRA_ASIA"},
    "DE": {"country_name": "독일", "port_code": "DEHAM", "port_name": "함부르크", "airport_code": "FRA", "airport_name": "프랑크푸르트", "local_currency": "EUR", "customs_value_basis": "CIF", "vat_rate": 0.19, "fta_name": "한·EU FTA", "season_profile": "ASIA_EUROPE"},
}
DEST_ORDER = ("US", "VN", "DE")

TRANSPORT_MODES = ("FCL", "LCL", "AIR")
TRANSPORT_MODE_LABELS = {"FCL": "FCL", "LCL": "LCL", "AIR": "항공"}

CONTAINER_SPECS = {
    "20GP": {"usable_cbm": 28, "payload_kg": 21000},
    "40GP": {"usable_cbm": 58, "payload_kg": 26000},
    "40HC": {"usable_cbm": 68, "payload_kg": 26000},
}
CONTAINER_TYPES = ("20GP", "40GP", "40HC")

# 부산 출발 해상 기준 운임 (USD) — FCL: (기본운임, 할증료 A, 할증료 B), LCL: (R/T당 기본운임, R/T당 할증료)
BASE_SEA_RATES = {
    "US": {"fcl": {"20GP": (1650, 180, 250), "40GP": (2150, 300, 400), "40HC": (2250, 300, 400)}, "lcl": (62, 14), "surcharge_names": ("BAF", "PSS"), "transit_days": {"FCL": 13, "LCL": 18}},
    "VN": {"fcl": {"20GP": (230, 60, 0), "40GP": (390, 100, 0), "40HC": (410, 100, 0)}, "lcl": (18, 5), "surcharge_names": ("BAF", "PSS"), "transit_days": {"FCL": 7, "LCL": 10}},
    "DE": {"fcl": {"20GP": (1720, 220, 20), "40GP": (2680, 380, 38), "40HC": (2780, 380, 38)}, "lcl": (66, 12), "surcharge_names": ("BAF", "EU ETS"), "transit_days": {"FCL": 36, "LCL": 42}},
}
ORIGIN_RATE_FACTORS = {"KRPUS": {"US": 1.0, "VN": 1.0, "DE": 1.0}, "KRINC": {"US": 1.06, "VN": 1.03, "DE": 1.08}}
ORIGIN_TRANSIT_OFFSETS = {"KRPUS": {"US": 0, "VN": 0, "DE": 0}, "KRINC": {"US": 2, "VN": 1, "DE": 2}}

# 인천공항 출발 항공 기준 운임 (USD/kg)
BASE_AIR_RATES = {
    "US": {"rate_per_kg": 3.85, "fsc_per_kg": 1.1, "ssc_per_kg": 0.15, "min_charge": 95, "transit_days": 2},
    "VN": {"rate_per_kg": 2.05, "fsc_per_kg": 0.55, "ssc_per_kg": 0.15, "min_charge": 60, "transit_days": 1},
    "DE": {"rate_per_kg": 3.6, "fsc_per_kg": 1.05, "ssc_per_kg": 0.15, "min_charge": 95, "transit_days": 2},
}

# 수집 실패 필드 목록 (결측 처리 로직 검증용)
COLLECTION_GAPS = (
    {"origin": "KRINC", "dest": "DE", "mode": "LCL", "unit": "RT", "field": "surcharge_usd"},
    {"origin": "KRINC", "dest": "VN", "mode": "FCL", "unit": "40HC", "field": "transit_days"},
)

# 수출지 비용 (KRW, 수도권 출고 가정) — 소량 내륙운송: (기본료(3 CBM 이하), CBM당 추가)
ORIGIN_CHARGES = {
    "fcl_inland": {"KRPUS": {"20GP": 780000, "40GP": 880000, "40HC": 880000}, "KRINC": {"20GP": 340000, "40GP": 390000, "40HC": 390000}},
    "small_inland": {"KRPUS": (260000, 22000), "KRINC": (140000, 15000), "ICN": (150000, 18000)},
    "small_inland_base_cbm": 3,
    "fcl_thc": {"20GP": 165000, "40GP": 225000, "40HC": 225000},
    "seal_fee": 10000,
    "bl_fee": 45000,
    "lcl_cfs_thc_per_rt": 16500,
    "air_terminal_per_kg": 120,
    "air_terminal_min": 30000,
    "awb_fee": 35000,
}

# 수입지 비용 (현지 통화) — 소량 내륙배송: (기본료(2 CBM 이하), CBM당 추가)
DEST_CHARGES = {
    "US": {"fcl_terminal": {"20GP": 190, "40GP": 240, "40HC": 240}, "lcl_cfs_per_rt": 85, "lcl_cfs_min": 95, "air_handling_per_kg": 0.18, "air_handling_min": 75, "do_fee_sea": 75, "do_fee_air": 45, "clearance_fee": 165, "isf_fee": 45, "fcl_inland": {"20GP": 720, "40GP": 790, "40HC": 790}, "small_inland": (240, 16)},
    "VN": {"fcl_terminal": {"20GP": 185, "40GP": 300, "40HC": 300}, "lcl_cfs_per_rt": 22, "lcl_cfs_min": 30, "air_handling_per_kg": 0.09, "air_handling_min": 30, "do_fee_sea": 40, "do_fee_air": 25, "clearance_fee": 75, "isf_fee": 0, "fcl_inland": {"20GP": 135, "40GP": 175, "40HC": 175}, "small_inland": (70, 6)},
    "DE": {"fcl_terminal": {"20GP": 245, "40GP": 295, "40HC": 295}, "lcl_cfs_per_rt": 42, "lcl_cfs_min": 55, "air_handling_per_kg": 0.22, "air_handling_min": 55, "do_fee_sea": 55, "do_fee_air": 35, "clearance_fee": 95, "isf_fee": 0, "fcl_inland": {"20GP": 560, "40GP": 620, "40HC": 620}, "small_inland": (160, 14)},
}
DEST_SMALL_INLAND_BASE_CBM = 2

# HS CODE별 세율 (샘플) — 기본세율(MFN)과 FTA 특혜세율
HS_ITEMS = {
    "3304.99": {"name": "기초화장품", "mfn_rates": {"US": 0.0, "VN": 0.2, "DE": 0.0}, "fta_rates": {"US": 0.0, "VN": 0.0, "DE": 0.0}},
    "8708.99": {"name": "자동차 부품", "mfn_rates": {"US": 0.025, "VN": 0.1, "DE": 0.03}, "fta_rates": {"US": 0.0, "VN": 0.05, "DE": 0.0}},
    "6110.30": {"name": "니트 스웨터", "mfn_rates": {"US": 0.32, "VN": 0.2, "DE": 0.12}, "fta_rates": {"US": 0.0, "VN": 0.0, "DE": 0.0}},
    "3901.10": {"name": "폴리에틸렌 수지", "mfn_rates": {"US": 0.065, "VN": 0.03, "DE": 0.065}, "fta_rates": {"US": 0.0, "VN": 0.0, "DE": 0.0}},
}

INSURANCE_RATES = {"SEA": {"US": 0.0008, "VN": 0.0006, "DE": 0.0009}, "AIR": {"US": 0.00045, "VN": 0.00045, "DE": 0.00045}}
INSURANCE_COVERAGE_RATIO = 1.1
INSURANCE_MIN_PREMIUM_KRW = 10000
US_MPF = {"rate": 0.003464, "min_usd": 33.58, "max_usd": 651.5}
US_HMF_RATE = 0.00125
VOLUMETRIC_KG_PER_CBM = 166.67
LCL_MIN_REVENUE_TON = 1.0

# KPI 1 기준 단가 (샘플) 및 목표
BROKER_FEES = {"hs_review": 110000, "fta_review": 220000, "export_filing": 30000}
KPI_BROKER_SAVING_TARGET = 0.7

# 화물 흐름 8구간 (MECE 비용 체계)
SEGMENTS = (
    {"id": "origin_inland", "name": "출고지 내륙운송", "air_name": "출고지 내륙운송", "detail": "공장 → 선적지 운송"},
    {"id": "export_clearance", "name": "수출통관", "air_name": "수출통관", "detail": "수출신고 수수료"},
    {"id": "origin_terminal", "name": "선적지 터미널·서류", "air_name": "출발 공항 터미널·AWB", "detail": "THC·CFS·B/L·Seal (항공: 터미널·AWB)"},
    {"id": "main_carriage", "name": "국제운송 (운임·할증)", "air_name": "국제운송 (항공)", "detail": "O/F·A/F, BAF·PSS·ETS·FSC"},
    {"id": "insurance", "name": "적하보험", "air_name": "적하보험", "detail": "적하보험료"},
    {"id": "dest_terminal", "name": "도착지 터미널·D/O", "air_name": "도착 공항 핸들링·D/O", "detail": "THC·CFS·D/O (항공: 핸들링)"},
    {"id": "import_clearance", "name": "수입통관·제세", "air_name": "수입통관·제세", "detail": "통관 수수료, 관세, 부가세 등"},
    {"id": "dest_inland", "name": "도착지 내륙배송", "air_name": "도착지 내륙배송", "detail": "도착지 → 수입자 창고"},
)
ORIGIN_SEGMENT_IDS = ("origin_inland", "export_clearance", "origin_terminal")
ALL_SEGMENT_IDS = tuple(segment["id"] for segment in SEGMENTS)

INCOTERMS_RULES = {
    "EXW": {"label": "공장인도", "sea_only": False, "seller_segments": (), "risk_boundary": 0, "risk_label": "출고지 인도", "insurance_required": False, "min_cover": ""},
    "FCA": {"label": "운송인인도", "sea_only": False, "seller_segments": ORIGIN_SEGMENT_IDS, "risk_boundary": 3, "risk_label": "운송인 인도", "insurance_required": False, "min_cover": ""},
    "FOB": {"label": "본선인도", "sea_only": True, "seller_segments": ORIGIN_SEGMENT_IDS, "risk_boundary": 3, "risk_label": "본선 적재", "insurance_required": False, "min_cover": ""},
    "CFR": {"label": "운임포함", "sea_only": True, "seller_segments": ORIGIN_SEGMENT_IDS + ("main_carriage",), "risk_boundary": 3, "risk_label": "본선 적재", "insurance_required": False, "min_cover": ""},
    "CIF": {"label": "운임·보험료포함", "sea_only": True, "seller_segments": ORIGIN_SEGMENT_IDS + ("main_carriage", "insurance"), "risk_boundary": 3, "risk_label": "본선 적재", "insurance_required": True, "min_cover": "ICC(C)"},
    "CPT": {"label": "운송비지급", "sea_only": False, "seller_segments": ORIGIN_SEGMENT_IDS + ("main_carriage",), "risk_boundary": 3, "risk_label": "운송인 인도", "insurance_required": False, "min_cover": ""},
    "CIP": {"label": "운송비·보험료지급", "sea_only": False, "seller_segments": ORIGIN_SEGMENT_IDS + ("main_carriage", "insurance"), "risk_boundary": 3, "risk_label": "운송인 인도", "insurance_required": True, "min_cover": "ICC(A)"},
    "DAP": {"label": "도착지인도", "sea_only": False, "seller_segments": ORIGIN_SEGMENT_IDS + ("main_carriage", "insurance", "dest_terminal", "dest_inland"), "risk_boundary": 8, "risk_label": "지정 목적지", "insurance_required": False, "min_cover": ""},
    "DDP": {"label": "관세지급인도", "sea_only": False, "seller_segments": ALL_SEGMENT_IDS, "risk_boundary": 8, "risk_label": "지정 목적지", "insurance_required": False, "min_cover": ""},
}
INCOTERMS_ORDER = ("EXW", "FCA", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DDP")
SEA_TO_ANY_MODE_TERMS = {"FOB": "FCA", "CFR": "CPT", "CIF": "CIP"}
NEGOTIATION_TERMS = {
    "SEA": {"CIF": "FOB", "CFR": "FOB", "CIP": "FCA", "CPT": "FCA", "DAP": "CIF", "DDP": "DAP"},
    "AIR": {"CIP": "FCA", "CPT": "FCA", "DAP": "CIP", "DDP": "DAP"},
}

# 견적 명세서 표시 그룹
LINE_GROUPS = (
    {"id": "origin", "name": "수출지 비용", "line_ids": ("origin_inland", "export_clearance", "origin_terminal")},
    {"id": "main", "name": "국제 운송", "line_ids": ("base_freight", "surcharge")},
    {"id": "insurance", "name": "적하보험", "line_ids": ("insurance",)},
    {"id": "dest", "name": "수입지 비용", "line_ids": ("dest_terminal", "import_clearance", "dest_inland")},
    {"id": "tax", "name": "제세 (물류비 외)", "line_ids": ("duty", "other_tax", "vat")},
)

# 비용 구성비 범주 및 차트 색상 (라이트·다크 테마별 검증 팔레트)
CATEGORY_META = {
    "freight": {"name": "국제운임", "light": "#2a78d6", "dark": "#3987e5"},
    "local": {"name": "부대비용", "light": "#eb6834", "dark": "#d95926"},
    "insurance": {"name": "보험료", "light": "#1baf7a", "dark": "#199e70"},
    "tax": {"name": "관세·제세", "light": "#eda100", "dark": "#c98500"},
}
CHART_COLORS = {
    "light": {"primary": "#2a78d6", "muted": "#a9b3bd", "ink": "#0d1b2a", "ink_secondary": "#465666"},
    "dark": {"primary": "#3987e5", "muted": "#56626e", "ink": "#e8edf2", "ink_secondary": "#a9b5c1"},
}

# 운임 추이 모사 파라미터 (월별 계절 계수, 연간 추세)
SEASON_PROFILES = {
    "TRANSPACIFIC": (1.02, 0.95, 0.92, 0.93, 0.96, 1.0, 1.04, 1.07, 1.06, 1.03, 0.99, 1.01),
    "INTRA_ASIA": (1.08, 1.02, 0.95, 0.96, 0.98, 1.0, 1.02, 1.01, 1.0, 0.99, 0.99, 1.02),
    "ASIA_EUROPE": (1.06, 1.0, 0.94, 0.93, 0.96, 1.01, 1.05, 1.04, 1.01, 0.99, 0.98, 1.03),
    "AIR": (0.98, 0.93, 0.97, 0.98, 0.97, 0.97, 0.98, 0.99, 1.02, 1.06, 1.1, 1.07),
}
ANNUAL_TRENDS = {"TRANSPACIFIC": -0.04, "INTRA_ASIA": 0.02, "ASIA_EUROPE": -0.06, "AIR": 0.03}
SERIES_END = (2026, 9)
SERIES_LENGTH = 24
