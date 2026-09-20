"""관세율 구분코드에서 협정과 대상국을 읽어냅니다.

관세청 "관세율 기본 조회"(API030)가 돌려주는 관세율구분명에는 상대국 이름이
그대로 들어 있습니다. ("한ㆍ칠레FTA협정세율(선택1)", "RCEP협정세율_일본(선택1)")
그 이름을 관세청 국가코드 목록(API019, statsSgnTp=A06)과 맞춰 나라를 정합니다.
협정이 새로 생겨도 코드를 고치지 않아도 됩니다.

나라 하나가 아닌 협정(EU·EFTA·아세안·아시아태평양)만 회원국을 적어 둡니다.
회원국은 협정문에 정해진 것이라 API로는 받을 수 없습니다.

주의: 이 세율은 **한국으로 수입할 때** 적용됩니다. 수출 시 상대국 관세는 그
나라가 정합니다. 화면에서는 "어떤 협정을 쓸 수 있고 어떤 원산지증명이 필요한지"를
알리는 데 씁니다.
"""

from __future__ import annotations

import re

# 나라 하나로 특정되지 않는 협정의 회원국 (협정문 기준)
BLOCS: dict[str, tuple[str, ...]] = {
    # 유럽연합 27개국
    "EU": ("AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR",
           "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO",
           "SE", "SI", "SK"),
    # 유럽자유무역연합
    "EFTA": ("CH", "IS", "LI", "NO"),
    # 아세안 10개국
    "아세안": ("BN", "ID", "KH", "LA", "MM", "MY", "PH", "SG", "TH", "VN"),
    # 아시아·태평양 무역협정(APTA) 회원국 (한국 제외)
    "일반": ("BD", "CN", "IN", "LA", "LK", "MN"),
}

# 협정 이름에 쓰는 줄임말을 관세청 국가명으로 바꿉니다.
NAME_ALIASES = {"미": "미국", "UAE": "아랍에미리트 연합", "터키": "튀르키예"}

# 원산지증명 방식. 협정마다 발급 주체가 달라 수출 준비물이 달라집니다.
SELF = "자율발급 — 수출자가 원산지증명서를 직접 작성합니다."
APPROVED = ("인증수출자 원산지신고서 — 송장 등에 원산지 문구를 적습니다."
            " 일정 금액을 넘으면 인증수출자 자격이 필요합니다.")
AUTHORITY = "기관발급 — 세관이나 상공회의소에서 원산지증명서를 발급받습니다."
RCEP_PROOF = "기관발급 또는 인증수출자 자율발급 중 하나를 씁니다."

# 원산지증명 방식은 협정문에 정해진 것이라 관세율 API에는 없습니다.
# 코드 앞부분으로 맞추고, 모르는 협정은 "확인 필요"로 둡니다.
PROOF_BY_PREFIX = {
    "FEU": APPROVED, "FGB": APPROVED,
    "FEF": SELF, "FTR": SELF, "FUS": SELF, "FIL": SELF, "FAU": SELF, "FNZ": SELF,
    "FCA": SELF, "FCL": SELF, "FPE": SELF, "FCO": SELF, "FCE": SELF,
    "FAS": AUTHORITY, "FCN": AUTHORITY, "FVN": AUTHORITY, "FIN": AUTHORITY,
    "FSG": AUTHORITY, "FID": AUTHORITY, "FKH": AUTHORITY, "FPH": AUTHORITY,
    "FAE": AUTHORITY, "E": AUTHORITY,
    "FRC": RCEP_PROOF,
}
PROOF_UNKNOWN = "원산지증명 방식은 협정문과 관세청 안내를 확인해주세요."

# 협정이 아닌 일반 세율. 참고용으로 함께 보여줍니다.
GENERAL_RATES = {
    "A": "기본세율 — 협정을 쓰지 않을 때 적용하는 세율입니다.",
    "C": "WTO 협정세율 — WTO 회원국에 적용하는 양허세율입니다.",
}
# 협정이 아니어서 나라를 따지지 않는 코드 (최빈국 특혜·북한산·긴급관세 등)
NON_AGREEMENT_PREFIXES = ("A", "C", "R", "U", "T", "W")


def agreement_label(rate_name: str) -> str:
    """관세율구분명에서 "(선택1)" 같은 꼬리를 떼어 협정 이름만 남깁니다."""

    name = re.sub(r"\(선택\d*\)|\(.*?\d\)", "", rate_name or "").strip()
    return name.replace("ㆍ", "·").replace("협정세율", "").replace("_", " ").strip(" ·")


def country_token(rate_name: str) -> str:
    """관세율구분명에서 나라(또는 협정체) 이름을 뽑아냅니다."""

    name = (rate_name or "").strip()
    if "_" in name:                                     # RCEP협정세율_일본(선택1)
        return name.split("_", 1)[1].split("(")[0].strip()
    asia_pacific = re.match(r"아시아ㆍ태평양 협정세율\((.+?)\)", name)
    if asia_pacific:                                    # 아시아ㆍ태평양 협정세율(라오스)
        return asia_pacific.group(1).strip()
    if name.startswith("한ㆍEFTA"):                      # "EFTA FTA"라 잘리지 않게 먼저 봅니다.
        return "EFTA"
    partner = re.match(r"한ㆍ(.+?)\s*(?:FTA|CEPA|협정세율|\()", name)
    return partner.group(1).strip() if partner else ""


def proof_for(rate_code: str) -> str:
    """관세율구분코드로 원산지증명 방식을 찾습니다."""

    code = (rate_code or "").strip().upper()
    for prefix in sorted(PROOF_BY_PREFIX, key=len, reverse=True):
        if code.startswith(prefix):
            return PROOF_BY_PREFIX[prefix]
    return PROOF_UNKNOWN


def countries_for(rate_code: str, rate_name: str, country_codes: dict[str, str]) -> tuple[str, ...]:
    """이 세율이 어느 나라에 적용되는지 알아냅니다.

    `country_codes`는 관세청 국가코드 목록({한글명: 코드})입니다.
    """

    code = (rate_code or "").strip().upper()
    if code in GENERAL_RATES or (code and code[0] in NON_AGREEMENT_PREFIXES and not code.startswith(("E1", "E2", "E3"))):
        return ()

    token = country_token(rate_name)
    if not token:
        return ()
    if token in BLOCS:
        return BLOCS[token]

    name = NAME_ALIASES.get(token, token)
    if name in country_codes:
        return (country_codes[name],)
    # 관세청 국가명이 조금 더 긴 경우 (예: "아랍에미리트 연합")
    for full, iso in country_codes.items():
        if full.startswith(name):
            return (iso,)
    return ()
