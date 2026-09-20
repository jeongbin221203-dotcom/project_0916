"""관세율 구분코드와 FTA 협정 대상국.

관세청 "관세율 기본 조회"(API030)가 돌려주는 관세율구분코드를 협정 단위로 묶고,
각 협정이 어느 나라에 적용되는지 정리합니다. 코드 목록은 실제 API 응답에서
확인한 값입니다.

주의: 이 API의 세율은 **한국으로 수입할 때** 적용되는 세율입니다. 수출 시
상대국이 매기는 관세는 그 나라가 정합니다. 화면에서는 "어떤 협정을 쓸 수 있고
어떤 원산지증명이 필요한지"를 알리는 데 씁니다.
"""

from __future__ import annotations

# 유럽연합 27개국
EU_COUNTRIES = ("AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR",
                "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO",
                "SE", "SI", "SK")
# 유럽자유무역연합
EFTA_COUNTRIES = ("CH", "IS", "LI", "NO")
# 아세안 10개국
ASEAN_COUNTRIES = ("BN", "ID", "KH", "LA", "MM", "MY", "PH", "SG", "TH", "VN")
# 아시아·태평양 무역협정(APTA) 회원국
APTA_COUNTRIES = ("BD", "CN", "IN", "LA", "LK", "MN")
# RCEP 회원국 (한국 제외)
RCEP_COUNTRIES = ASEAN_COUNTRIES + ("AU", "CN", "JP", "NZ")

# 원산지증명 방식. 협정마다 발급 주체가 달라 수출 준비물이 달라집니다.
SELF = "자율발급 — 수출자가 원산지증명서를 직접 작성합니다."
APPROVED = "인증수출자 원산지신고서 — 송장 등에 원산지 문구를 적습니다. 일정 금액을 넘으면 인증수출자 자격이 필요합니다."
AUTHORITY = "기관발급 — 세관이나 상공회의소에서 원산지증명서를 발급받습니다."
RCEP_PROOF = "기관발급 또는 인증수출자 자율발급 중 하나를 씁니다."

# 관세율구분코드 앞부분 → (협정 이름, 적용 국가, 원산지증명 방식)
# 긴 코드부터 맞춰야 FAS(아세안)와 FASPH(아세안 상호대응)를 구분할 수 있습니다.
AGREEMENTS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "FUS": ("한·미 FTA", ("US",), SELF),
    "FEU": ("한·EU FTA", EU_COUNTRIES, APPROVED),
    "FGB": ("한·영국 FTA", ("GB",), APPROVED),
    "FEF": ("한·EFTA FTA", EFTA_COUNTRIES, SELF),
    "FTR": ("한·튀르키예 FTA", ("TR",), SELF),
    "FCN": ("한·중국 FTA", ("CN",), AUTHORITY),
    "FVN": ("한·베트남 FTA", ("VN",), AUTHORITY),
    "FIN": ("한·인도 CEPA", ("IN",), AUTHORITY),
    "FSG": ("한·싱가포르 FTA", ("SG",), AUTHORITY),
    "FID": ("한·인도네시아 CEPA", ("ID",), AUTHORITY),
    "FKH": ("한·캄보디아 FTA", ("KH",), AUTHORITY),
    "FPH": ("한·필리핀 FTA", ("PH",), AUTHORITY),
    "FAE": ("한·아랍에미리트 CEPA", ("AE",), AUTHORITY),
    "FIL": ("한·이스라엘 FTA", ("IL",), SELF),
    "FAU": ("한·호주 FTA", ("AU",), SELF),
    "FNZ": ("한·뉴질랜드 FTA", ("NZ",), SELF),
    "FCA": ("한·캐나다 FTA", ("CA",), SELF),
    "FCL": ("한·칠레 FTA", ("CL",), SELF),
    "FPE": ("한·페루 FTA", ("PE",), SELF),
    "FCO": ("한·콜롬비아 FTA", ("CO",), SELF),
    "FCECR": ("한·중미 FTA (코스타리카)", ("CR",), SELF),
    "FCEHN": ("한·중미 FTA (온두라스)", ("HN",), SELF),
    "FCENI": ("한·중미 FTA (니카라과)", ("NI",), SELF),
    "FCEPA": ("한·중미 FTA (파나마)", ("PA",), SELF),
    "FCESV": ("한·중미 FTA (엘살바도르)", ("SV",), SELF),
    "FASPH": ("한·아세안 FTA 상호대응세율 (필리핀)", ("PH",), AUTHORITY),
    "FAS": ("한·아세안 FTA", ASEAN_COUNTRIES, AUTHORITY),
    "FRCAS": ("RCEP (아세안)", ASEAN_COUNTRIES, RCEP_PROOF),
    "FRCAU": ("RCEP (호주)", ("AU",), RCEP_PROOF),
    "FRCNZ": ("RCEP (뉴질랜드)", ("NZ",), RCEP_PROOF),
    "FRCCN": ("RCEP (중국)", ("CN",), RCEP_PROOF),
    "FRCJP": ("RCEP (일본)", ("JP",), RCEP_PROOF),
    "E2": ("아시아·태평양 무역협정 (방글라데시 양허)", ("BD",), AUTHORITY),
    "E3": ("아시아·태평양 무역협정 (라오스 양허)", ("LA",), AUTHORITY),
    "E1": ("아시아·태평양 무역협정", APTA_COUNTRIES, AUTHORITY),
}

# 협정이 아닌 일반 세율. 참고용으로 함께 보여줍니다.
GENERAL_RATES = {
    "A": "기본세율 — 협정을 쓰지 않을 때 적용하는 세율입니다.",
    "C": "WTO 협정세율 — WTO 회원국에 적용하는 양허세율입니다.",
}

# 긴 코드부터 맞춥니다.
_PREFIXES = sorted(AGREEMENTS, key=len, reverse=True)


def match_agreement(rate_code: str) -> tuple[str, tuple[str, ...], str] | None:
    """관세율구분코드가 어느 협정 것인지 찾습니다."""

    code = (rate_code or "").strip().upper()
    for prefix in _PREFIXES:
        if code.startswith(prefix):
            return AGREEMENTS[prefix]
    return None


def agreements_for(country_code: str) -> list[str]:
    """해당 국가와 맺은 협정 이름 목록. 중복은 한 번만 담습니다."""

    country = (country_code or "").strip().upper()
    names: list[str] = []
    for prefix in _PREFIXES:
        name, countries, _ = AGREEMENTS[prefix]
        if country in countries and name not in names:
            names.append(name)
    return names
