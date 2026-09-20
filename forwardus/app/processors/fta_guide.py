"""관세율 구분코드에서 협정과 대상국을 읽어냅니다.

관세청 "관세율 기본 조회"(API030)가 돌려주는 관세율구분명에는 상대국 이름이
그대로 들어 있습니다. ("한ㆍ칠레FTA협정세율(선택1)", "RCEP협정세율_일본(선택1)")
그 이름을 관세청 국가코드 목록(API019, statsSgnTp=A06)과 맞춰 나라를 정합니다.
협정이 새로 생겨도 코드를 고치지 않아도 됩니다.

나라 하나가 아닌 협정(EU·EFTA·아세안·중미·아시아태평양)의 회원국과 협정별
원산지증명 발급 정보는 관세청 FTA 포털에서 받아 둔
data/mock/fta_agreements.json 에서 읽습니다. (data/build_fta.py 가 만듭니다.
협정별 회원국을 주는 API는 없어 포털 페이지를 받아 파일로 굳혀 둡니다.)

주의: 이 세율은 **한국으로 수입할 때** 적용됩니다. 수출 시 상대국 관세는 그
나라가 정합니다. 화면에서는 "어떤 협정을 쓸 수 있고 어떤 원산지증명이 필요한지"를
알리는 데 씁니다.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "mock" / "fta_agreements.json"

# 협정 이름에 쓰는 줄임말을 관세청 국가명으로 바꿉니다.
NAME_ALIASES = {"미": "미국", "UAE": "아랍에미리트 연합", "터키": "튀르키예"}
# 관세율구분명의 상대국 표기를 FTA 포털의 협정 이름으로 잇습니다.
CERTIFICATE_ALIASES = {"미": "미국", "UAE": "아랍에미리트연합국(UAE)", "터키": "튀르키예"}
# 한·중미 FTA는 나라별로 관세율코드가 갈리지만 원산지증명 방식은 하나입니다.
CENTRAL_AMERICA = ("파나마", "코스타리카", "온두라스", "엘살바도르", "니카라과")

# 협정이 아닌 일반 세율. 참고용으로 함께 보여줍니다.
GENERAL_RATES = {
    "A": "기본세율 — 협정을 쓰지 않을 때 적용하는 세율입니다.",
    "C": "WTO 협정세율 — WTO 회원국에 적용하는 양허세율입니다.",
}
# 협정이 아니어서 나라를 따지지 않는 코드 (최빈국 특혜·북한산·긴급관세 등)
NON_AGREEMENT_PREFIXES = ("A", "C", "R", "U", "T", "W")

PROOF_UNKNOWN = "원산지증명 방식은 협정문과 관세청 안내를 확인해주세요."


@lru_cache(maxsize=1)
def seed() -> dict:
    """관세청 FTA 포털에서 받아 둔 자료."""

    try:
        return json.loads(_SEED_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"blocs": {}, "certificates": {}}


def blocs() -> dict[str, tuple[str, ...]]:
    """나라 하나로 특정되지 않는 협정의 회원국. {"EU": ("AT", "BE", ...)}"""

    return {name: tuple(codes) for name, codes in (seed().get("blocs") or {}).items()}


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


def countries_for(rate_code: str, rate_name: str, country_codes: dict[str, str]) -> tuple[str, ...]:
    """이 세율이 어느 나라에 적용되는지 알아냅니다.

    `country_codes`는 관세청 국가코드 목록({한글명: 코드})입니다.
    """

    code = (rate_code or "").strip().upper()
    if code in GENERAL_RATES or (
            code and code[0] in NON_AGREEMENT_PREFIXES and not code.startswith(("E1", "E2", "E3"))):
        return ()

    token = country_token(rate_name)
    if not token:
        return ()
    members = blocs()
    if token in members:
        return members[token]

    name = NAME_ALIASES.get(token, token)
    if name in country_codes:
        return (country_codes[name],)
    # 관세청 국가명이 조금 더 긴 경우 (예: "아랍에미리트 연합")
    for full, iso in country_codes.items():
        if full.startswith(name):
            return (iso,)
    return ()


def certificate_for(rate_code: str, rate_name: str) -> dict:
    """협정별 원산지증명 발급 정보. 발급방식·발급자·서식·유효기간."""

    certificates = seed().get("certificates") or {}
    if (rate_code or "").strip().upper().startswith("FRC"):
        return certificates.get("RCEP", {})

    token = country_token(rate_name)
    name = CERTIFICATE_ALIASES.get(token, token)
    if name in certificates:
        return certificates[name]
    if token in CENTRAL_AMERICA:
        return certificates.get("중미", {})
    return {}


# 발급 방식별로 어디에 가서 무엇을 해야 하는지. (관세청·대한상공회의소 공식 창구)
WHERE_AUTHORITY = ("세관(관세청 UNI-PASS 전자통관 → 원산지증명서 발급신청) 또는"
                   " 대한상공회의소 무역인증서비스센터(cert.korcham.net)에서 발급받습니다.")
WHERE_SELF = "수출자가 협정이 정한 서식(또는 송장 등 상업서류)에 원산지 문안을 적고 서명합니다."


def where_to_get(method: str) -> str:
    """발급방식 문구("기관발급", "자율발급", "자율/기관발급")로 발급처를 정합니다."""

    text = method or ""
    has_authority = "기관" in text
    has_self = "자율" in text
    if has_authority and has_self:
        return f"둘 다 가능합니다. 기관발급은 {WHERE_AUTHORITY} 자율발급은 {WHERE_SELF}"
    if has_authority:
        return WHERE_AUTHORITY
    if has_self:
        return WHERE_SELF
    return ""


def certificate_steps(info: dict) -> dict:
    """무엇을 · 어디서 · 어떤 서식으로 · 얼마 동안. 화면과 서류에서 같이 씁니다."""

    if not info:
        return {}
    return {
        "what": f"{info.get('method', '')} 원산지증명서".strip(),
        "where": where_to_get(info.get("method", "")),
        "issuer": info.get("issuer", ""),
        "form": info.get("form", ""),
        "valid_for": info.get("valid_for", ""),
    }


def proof_for(rate_code: str, rate_name: str = "") -> str:
    """원산지증명을 어떻게 받아야 하는지 한 줄로 알려줍니다."""

    info = certificate_for(rate_code, rate_name)
    if not info:
        return PROOF_UNKNOWN
    parts = [f"{info.get('method', '')} 원산지증명서".strip()]
    if info.get("form"):
        parts.append(f"서식: {info['form']}")
    if info.get("valid_for"):
        parts.append(f"유효기간 {info['valid_for']}")
    return " · ".join(part for part in parts if part.strip())


# 협정 종류를 우리말로 풀어 씁니다. 이름만으로는 무슨 협정인지 알기 어렵습니다.
KIND_NOTES = (
    ("FRC", "RCEP(역내포괄적경제동반자협정) — 아세안 10개국과 한국·중국·일본·호주·뉴질랜드가"
            " 함께 맺은 협정입니다."),
    ("E", "아시아·태평양 무역협정(APTA) — 아시아·태평양 개발도상국끼리 관세를 낮추기로 한"
          " 협정입니다."),
)
CEPA_NOTE = "CEPA(포괄적경제동반자협정) — 상품 관세뿐 아니라 서비스·투자까지 함께 다루는 협정입니다."
FTA_NOTE = "FTA(자유무역협정) — 두 나라 사이 관세를 낮추거나 없애기로 한 협정입니다."
FTA_BLOC_NOTE = "FTA(자유무역협정) — 여러 나라와 함께 관세를 낮추거나 없애기로 한 협정입니다."


def describe(rate_code: str, rate_name: str, countries: tuple[str, ...],
             country_names: dict[str, str]) -> str:
    """이 협정이 무엇인지 우리말로 한 줄 설명합니다.

    `country_names`는 {코드: 한글 국가명}입니다. 여러 나라가 묶인 협정이면
    어느 나라가 들어 있는지 함께 적습니다.
    """

    code = (rate_code or "").strip().upper()
    note = next((text for prefix, text in KIND_NOTES if code.startswith(prefix)), None)
    if note is None:
        note = (CEPA_NOTE if "CEPA" in (rate_name or "")
                else FTA_BLOC_NOTE if len(countries) > 1 else FTA_NOTE)

    if len(countries) > 1:
        names = [country_names.get(iso, iso) for iso in countries]
        shown = " · ".join(names[:4])
        more = f" 외 {len(names) - 4}개국" if len(names) > 4 else ""
        note += f" 적용국 {len(names)}곳: {shown}{more}."
    return note
