"""Normalized mock data for the Forwardus prototype."""

from __future__ import annotations

from copy import deepcopy


EXCHANGE_RATE = {
    "currency": "USD",
    "base_currency": "KRW",
    "rate": 1380,
    "source": "mock",
    "label": "예상값",
}

KOREA_LOCATIONS = {
    "fcl": {"code": "KRPUS", "name": "부산항", "country": "대한민국", "kind": "port"},
    "lcl": {"code": "KRPUS", "name": "부산항", "country": "대한민국", "kind": "port"},
    "air": {"code": "ICN", "name": "인천국제공항", "country": "대한민국", "kind": "airport"},
}

FOREIGN_LOCATIONS = [
    {"code": "USLAX", "name": "로스앤젤레스항", "country": "미국", "kind": "port"},
    {"code": "CNSHA", "name": "상하이항", "country": "중국", "kind": "port"},
    {"code": "DEHAM", "name": "함부르크항", "country": "독일", "kind": "port"},
    {"code": "VNSGN", "name": "호찌민항", "country": "베트남", "kind": "port"},
    {"code": "LAX", "name": "로스앤젤레스국제공항", "country": "미국", "kind": "airport"},
    {"code": "PVG", "name": "상하이푸둥국제공항", "country": "중국", "kind": "airport"},
    {"code": "FRA", "name": "프랑크푸르트공항", "country": "독일", "kind": "airport"},
    {"code": "SGN", "name": "떤선녓국제공항", "country": "베트남", "kind": "airport"},
]

PACKING_TYPES = [
    {"value": "carton", "label": "카톤 박스", "note": "일반 소비재·소형 화물"},
    {"value": "pallet", "label": "팔레트", "note": "지게차 상하차가 필요한 화물"},
    {"value": "wooden_crate", "label": "목재 상자", "note": "기계·파손 위험 화물"},
    {"value": "drum", "label": "드럼", "note": "액체·분말 원료"},
    {"value": "flexible_bag", "label": "플렉시블 백", "note": "벌크 분말·원료"},
]

INCOTERMS = [
    {"code": "EXW", "label": "공장 인도", "seller": 12, "risk": "판매자 사업장 인도 시"},
    {"code": "FCA", "label": "운송인 인도", "seller": 30, "risk": "첫 운송인 인도 시"},
    {"code": "FOB", "label": "본선 인도", "seller": 45, "risk": "본선 적재 완료 시", "sea_only": True},
    {"code": "CFR", "label": "운임 포함", "seller": 62, "risk": "본선 적재 완료 시", "sea_only": True},
    {"code": "CIF", "label": "운임·보험 포함", "seller": 68, "risk": "본선 적재 완료 시", "sea_only": True},
    {"code": "CPT", "label": "운송비 지급", "seller": 62, "risk": "첫 운송인 인도 시"},
    {"code": "CIP", "label": "운송비·보험 지급", "seller": 70, "risk": "첫 운송인 인도 시"},
    {"code": "DAP", "label": "도착지 인도", "seller": 86, "risk": "지정 목적지 도착 시"},
    {"code": "DDP", "label": "관세 지급 인도", "seller": 100, "risk": "수입 통관 후 인도 시"},
]

HS_CODES = [
    {"code": "3304.99", "name": "기타 미용·메이크업용 제품", "mfn_rate": 6.5, "fta_rate": 0, "regulation": "성분표·현지 화장품 등록", "recommended": True},
    {"code": "3304.10", "name": "입술 화장용 제품", "mfn_rate": 5.8, "fta_rate": 0, "regulation": "성분표·라벨 심사"},
    {"code": "3401.30", "name": "피부 세정용 유기계면활성제품", "mfn_rate": 4, "fta_rate": 0, "regulation": "일반 소비재 표시"},
]

SCHEDULES = {
    "fcl": [
        {"id": "hmm-201", "carrier": "HMM", "service": "Pacific Express", "etd": "09.24", "eta": "10.07", "transit_days": 13, "freight_usd": 1580, "reliability": 98, "direct": True, "badge": "정시도착 98%", "accent": "#1546a0"},
        {"id": "one-305", "carrier": "ONE", "service": "Pink Bridge", "etd": "09.26", "eta": "10.11", "transit_days": 15, "freight_usd": 1460, "reliability": 94, "direct": True, "badge": "최저 운임", "accent": "#b31678"},
        {"id": "maersk-118", "carrier": "MAERSK", "service": "Eco Ocean", "etd": "09.22", "eta": "10.09", "transit_days": 17, "freight_usd": 1640, "reliability": 96, "direct": False, "badge": "친환경 선박", "accent": "#007c95"},
    ],
    "lcl": [
        {"id": "hmm-lcl", "carrier": "HMM", "service": "Weekly Consolidation", "etd": "09.25", "eta": "10.10", "transit_days": 15, "freight_usd": 740, "reliability": 96, "direct": True, "badge": "추천 혼재화물", "accent": "#1546a0"},
        {"id": "sinokor-lcl", "carrier": "SINOKOR", "service": "Smart LCL", "etd": "09.23", "eta": "10.12", "transit_days": 19, "freight_usd": 660, "reliability": 91, "direct": False, "badge": "최저 운임", "accent": "#e4572e"},
        {"id": "one-lcl", "carrier": "ONE", "service": "Priority LCL", "etd": "09.27", "eta": "10.09", "transit_days": 12, "freight_usd": 880, "reliability": 95, "direct": True, "badge": "최단 운송", "accent": "#b31678"},
    ],
    "air": [
        {"id": "ke-902", "carrier": "KOREAN AIR", "service": "Cargo Priority", "etd": "09.21", "eta": "09.22", "transit_days": 1, "freight_usd": 2120, "reliability": 99, "direct": True, "badge": "정시도착 99%", "accent": "#2b66f6"},
        {"id": "oz-204", "carrier": "ASIANA", "service": "Cargo Standard", "etd": "09.22", "eta": "09.24", "transit_days": 2, "freight_usd": 1940, "reliability": 97, "direct": True, "badge": "최저 운임", "accent": "#d52b1e"},
        {"id": "cx-330", "carrier": "CATHAY CARGO", "service": "Connect", "etd": "09.21", "eta": "09.25", "transit_days": 4, "freight_usd": 1830, "reliability": 93, "direct": False, "badge": "특가 운임", "accent": "#006564"},
    ],
}

TREND_DATA = [106, 101, 108, 118, 114, 109, 104, 99, 96, 102, 98, 94]


def get_locations(mode: str) -> list[dict]:
    """Return normalized foreign locations for the selected transport mode."""

    kind = "airport" if mode == "air" else "port"
    return deepcopy([item for item in FOREIGN_LOCATIONS if item["kind"] == kind])


def get_schedules(mode: str, sort_by: str = "recommended") -> list[dict]:
    """Return schedules sorted by the requested comparison criterion."""

    items = deepcopy(SCHEDULES.get(mode, SCHEDULES["fcl"]))
    if sort_by == "price":
        items.sort(key=lambda item: item["freight_usd"])
    elif sort_by == "duration":
        items.sort(key=lambda item: item["transit_days"])
    else:
        items.sort(key=lambda item: item["reliability"], reverse=True)
    return items


def get_hs_codes(keyword: str = "") -> list[dict]:
    """Return HS code candidates filtered by code or item name."""

    normalized = keyword.strip().lower()
    if not normalized:
        return deepcopy(HS_CODES)
    return deepcopy(
        [
            item
            for item in HS_CODES
            if normalized in item["code"].lower() or normalized in item["name"].lower()
        ]
    )


def get_bootstrap_data() -> dict:
    """Return initial data required to render the application."""

    return {
        "exchange_rate": deepcopy(EXCHANGE_RATE),
        "korea_locations": deepcopy(KOREA_LOCATIONS),
        "foreign_locations": deepcopy(FOREIGN_LOCATIONS),
        "packing_types": deepcopy(PACKING_TYPES),
        "incoterms": deepcopy(INCOTERMS),
        "hs_codes": deepcopy(HS_CODES),
        "schedules": deepcopy(SCHEDULES),
        "trend_data": deepcopy(TREND_DATA),
    }

