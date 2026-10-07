"""나라 이름을 대면 그 나라로 수출하는 법을 정리해 줍니다. (237개국 모두)

왜 글로 다 적어 두지 않는가
  나라마다 규제를 한 장씩 손으로 적으면 237장이 되고, 그중 220장은 확인할 길이
  없는 채로 낡아 갑니다. 낡은 규제 정보는 없는 것보다 나쁩니다. 사람이 그걸 믿고
  준비했다가 통관에서 막히기 때문입니다.

그래서 이렇게 나눕니다.
  **어디에나 같은 것**   수출 절차, 서류, 준비 순서 — 우리가 들고 있는 글에서 옵니다.
  **나라마다 다른 것**   FTA 적용 여부, 대표 인증, 조심할 점 — 확실한 것만 아래 표에 둡니다.
  **확인해야 하는 것**   나머지는 "어디서 확인하는지"를 알려 줍니다. 지어내지 않습니다.

표에 없는 나라도 답이 빕니다만 빈손으로 보내지 않습니다. 공통 절차와 확인 창구
(KOTRA 국가정보·TradeNAVI·FTA 강국 KOREA)를 함께 냅니다.
"""

from __future__ import annotations

from app.processors import korean

import re

# 한국과 FTA가 발효된 나라 (양자 협정). 지역 협정은 아래 blocs에서 옵니다.
BILATERAL = {
    "US": "한·미 FTA", "CN": "한·중 FTA", "VN": "한·베트남 FTA", "IN": "한·인도 CEPA",
    "AU": "한·호주 FTA", "CA": "한·캐나다 FTA", "NZ": "한·뉴질랜드 FTA",
    "SG": "한·싱가포르 FTA", "CL": "한·칠레 FTA", "PE": "한·페루 FTA",
    "CO": "한·콜롬비아 FTA", "TR": "한·튀르키예 FTA", "GB": "한·영 FTA",
    "IL": "한·이스라엘 FTA", "KH": "한·캄보디아 FTA", "ID": "한·인도네시아 CEPA",
    "PH": "한·필리핀 FTA",
    # 중동 산유국과 맺은 첫 협정입니다. 사우디를 포함한 한·GCC FTA는 아직 발효 전이라
    # 같은 GCC라도 관세 조건이 다릅니다. (중동을 한 묶음으로 보면 안 됩니다)
    "AE": "한·UAE CEPA",
}
# RCEP 회원국 (한국 포함 15개국 중 한국을 뺀 나라)
RCEP = ("BN", "KH", "ID", "LA", "MY", "MM", "PH", "SG", "TH", "VN",
        "CN", "JP", "AU", "NZ")
# APTA (아시아·태평양 무역협정)
APTA = ("CN", "IN", "LK", "BD", "LA", "MN")

# 나라별로 확실한 것만 적습니다. knowledge는 더 자세한 글(app/knowledge/*.md)입니다.
NOTES: dict[str, dict] = {
    "MX": {"certs": ["**NOM 강제인증** — 없으면 통관 거부", "COFEPRIS(식품·화장품·의료기기) 위생등록",
                     "스페인어 라벨·매뉴얼·보증서"],
           "watch": ["인증서가 **멕시코 수입자 명의**로만 발급됩니다",
                     "수입자의 Padrón de Importadores(수입자 등록) 확인",
                     "한국과 FTA가 없습니다. 일반세율이 적용됩니다"],
           "knowledge": "cert-mexico-nom"},
    "US": {"certs": ["무선·전자기기 **FCC**", "식품·화장품·의료기기 **FDA 등록/신고**",
                     "섬유 라벨 **FTC**, 어린이제품 **CPSC(CPC)**",
                     "전기설비는 사실상 **UL·ETL(NRTL)**"],
           "watch": ["식품은 선적마다 **Prior Notice**", "원산지 표시는 **물품 자체에** 항구적으로",
                     "FCC Covered List 부품이 들어가면 수입 금지"],
           "knowledge": "cert-usa"},
    "CN": {"certs": ["**CCC(3C) 강제인증**", "식품은 **GACC 해외생산기업 등록**", "중문 라벨"],
           "watch": ["공장심사(현지 심사원 방문)가 필요합니다",
                     "주요 부품을 바꾸면 변경신고·재인증 대상입니다",
                     "SAMR 공고 2025년 제57호 — 전동공구·용접기·소형 전동기·스위치·자동차 안전부품 등 16개 품목이 자가선언에서 제3자 CCC 인증으로 전환됩니다. **2026년 7월부터 인증 신청을 받고, 2027년 1월 1일부터는 인증·마크가 없으면 판매·수입할 수 없는 것으로 알려져 있습니다**(HS로 해당 여부 확인)"],
           "knowledge": "cert-china-ccc"},
    "JP": {"certs": ["전기용품 **PSE**(마름모/원형)", "식품은 건별 **식품등 수입신고**",
                     "건축·공공조달은 **JIS**"],
           "watch": ["PSE 신고사업자는 **일본 수입자**입니다",
                     "어댑터만 마름모 PSE인 경우가 많습니다",
                     "식품용 기구·용기포장 **포지티브리스트** 전면 시행"],
           "knowledge": "cert-japan-pse"},
    "VN": {"certs": ["품목별 **적합성인증(CR 마크)**", "식품·화장품은 공표·등록 절차"],
           "watch": ["한·베트남 FTA와 아세안·RCEP 중 **유리한 협정을 고를 수 있습니다**",
                     "2026년 7월 1일부터 식품·식품접촉 포장·의료기기·의약품(보건부)과 무선장비(과학기술부)에 위험등급별 관리 체계가 새로 적용되는 것으로 알려져 있습니다 — 내 HS가 어느 목록인지 현지 수입자를 통해 확인하세요(화장품은 별도 확인)"],
           "knowledge": "cert-vietnam"},
    "ID": {"certs": ["**SNI 인증**(품목별 강제)", "**할랄 인증** 단계적 의무화",
                     "BPOM 등록(식품·화장품·의약품)"],
           "watch": ["**수입 식음료 할랄 의무가 2026년 10월 17일 시행**됩니다",
                     "인증서가 현지 법인 명의입니다", "인도네시아어 라벨"],
           "knowledge": "cert-indonesia"},
    "IN": {"certs": ["**BIS 인증(ISI 마크 / CRS 등록)**", "무선기기 **WPC/ETA**", "FSSAI(식품)"],
           "watch": ["BIS 시험소는 **인도 국내뿐**입니다. 시료를 보내야 합니다",
                     "CRS는 60일·90일 이중 기한이 있습니다",
                     "한·인도 CEPA와 APTA 중 유리한 쪽을 확인하세요"],
           "knowledge": "cert-india"},
    "TH": {"certs": ["**TISI 인증**(품목별)", "식품·화장품 **Thai FDA** 등록"],
           "watch": ["서류가 태국어이고 최대 5개월 걸립니다", "TIS 마크에 **QR코드**가 함께 있어야 합니다"],
           "knowledge": "cert-thailand"},
    "MY": {"certs": ["**SIRIM** 인증·등록", "할랄(식품)", "통신기기 MCMC"],
           "watch": ["**ST COA는 1년마다 갱신**입니다", "무선이 있으면 MCMC 라벨을 함께 붙입니다"],
           "knowledge": "cert-malaysia"},
    "SG": {"certs": ["대부분 품목이 자유롭습니다", "안전품목 **CPS(Consumer Protection Scheme)**",
                     "식품 SFA 허가"],
           "watch": ["관세는 대부분 0%지만 **GST 9%**가 붙습니다",
                     "소비자제품 안전(CPS)·계량 업무가 2025년 7월 1일부터 Enterprise Singapore에서 CCCS(경쟁소비자위원회)로 넘어갔습니다 — 신청·문의 창구는 CCCS 안내를 확인하세요"],
           "knowledge": "cert-singapore"},
    "PH": {"certs": ["**PS/ICC 마크**(BPS)", "식품·화장품 **FDA PH** 등록"],
           "watch": ["**한·필리핀 FTA(2024.12.31 발효)**는 자율발급이 됩니다",
                     "ICC는 선적마다 반복됩니다. 사전 시험성적서(1년 유효)를 쓰세요"],
           "knowledge": "cert-philippines"},
    "AU": {"certs": ["전기 **RCM 마크**(전기안전+EMC)", "식품 FSANZ 기준", "검역(생물보안)이 엄격"],
           "watch": ["**한국 기업은 EESS에 직접 등록할 수 없습니다** (현지 법인 필요)",
                     "목재 포장재 **ISPM 15** 처리 필수"],
           "knowledge": "cert-australia"},
    "NZ": {"certs": ["전기 **RCM**", "검역(MPI) 엄격"],
           "watch": ["목재·식물성 포장재 검역"]},
    "CA": {"certs": ["전기 **CSA/cUL**", "식품 **SFCR 허가·라벨**", "불어·영어 병기 라벨"],
           "watch": ["**미국 UL 단독 마크는 무효**입니다. cUL·CSA 등 \"c\" 마크가 필요합니다",
                     "퀘벡 Bill 96 — 상표 안 설명 문구까지 프랑스어"],
           "knowledge": "cert-canada"},
    "GB": {"certs": ["**UKCA**(CE와 별도)", "영국 책임자 지정"],
           "watch": ["**대부분 일반 공산품은 UKCA가 아니라 CE가 무기한 인정**되는 것으로 알려져 있습니다 (의료기기·건설제품·해양장비는 별도 기한·UKCA 요건이 있으니 품목별 확인)",
                     "라벨에 **GB 수입자 상호·주소**를 반드시 적습니다"],
           "knowledge": "cert-uk"},
    "TR": {"certs": ["**CE + TSE**", "TAREKS 수입검사"],
           "watch": ["TAREKS 수입검사 승인 번호가 있어야 통관됩니다",
                     "보증서·설명서·제품 화면 언어까지 튀르키예어"],
           "knowledge": "cert-turkiye"},
    "AE": {"certs": ["**ECAS/EQM**(에미리트 적합성)", "할랄(식품)", "통신 TDRA"],
           "watch": ["**한·UAE CEPA가 2026년 5월 1일 발효**했습니다 (원산지증명 방식은 관세청 FTA 포털에서 확인하세요)",
                     "무선모듈이 있으면 TDRA가 추가됩니다"],
           "knowledge": "cert-uae"},
    "SA": {"certs": ["**SABER/SALEEM 적합성증(CoC)**", "할랄", "SFDA(식품·의료기기)"],
           "watch": ["**SCoC는 선적 전에 발급돼 있어야** 합니다. 없으면 반송입니다",
                     "비규제품목도 SABER 등록 대상입니다"],
           "knowledge": "cert-saudi"},
    "BR": {"certs": ["**INMETRO 인증**", "ANATEL(통신), ANVISA(식품·화장품·의료기기)"],
           "watch": ["**CNPJ를 가진 브라질 법인만 인증 명의인**이 됩니다",
                     "한·브라질 MRA가 없어 KC·CE·FCC가 전용되지 않습니다",
                     "수입신고가 DUIMP(단일수입신고)로 전환 중이며 2026년 중 단계적으로 의무화되는 것으로 알려져 있습니다(연기된 사례도 있어 통관대리인과 Siscomex 일정표 확인)"],
           "knowledge": "cert-brazil"},
    "RU": {"certs": ["**EAC 인증**(유라시아경제연합 공통)", "GOST 관련 규격"],
           "watch": ["**수출통제·제재 확인이 인증보다 먼저**입니다 (yesTrade)",
                     "EAC 증서는 EAEU 현지 법인 명의여야 합니다"],
           "knowledge": "cert-russia"},
    "TW": {"certs": ["**BSMI 인증**", "통신 NCC", "식품 TFDA"],
           "watch": ["**한국·대만 FTA가 없습니다.** 일반세율(MFN)입니다",
                     "NCC 표첨과 BSMI 표식은 서로 대체되지 않습니다"],
           "knowledge": "cert-taiwan"},
    "HK": {"certs": ["대부분 자유항이라 관세가 없습니다", "식품·의약품은 별도 규제"],
           "watch": ["통관에서 안 물어볼 뿐 **사후 단속·기소** 대상입니다",
                     "수입·수출 후 **14일 이내 신고** 의무가 있습니다"],
           "knowledge": "cert-hongkong"},
}
# 아래 나라는 EU 규정을 함께 적용받습니다. (EU 회원국 목록은 fta_guide에서 가져옵니다)
# 자료가 없던 나라를 채운 표(country_notes_extra.py) — 기존 항목은 덮어쓰지 않습니다.
from app.processors.country_notes_extra import EXTRA_NOTES  # noqa: E402

for _code, _note in EXTRA_NOTES.items():
    NOTES.setdefault(_code, _note)

EU_NOTE = {"certs": ["**CE 마킹**(해당 지침이 있는 품목)", "**GPSR**(EU 2023/988, 2024년 12월 13일 적용) — 일반 소비재도 EU 책임자 필요",
                     "RoHS·REACH·배터리 규정", "판매국 공용어 설명서"],
           "watch": ["EU 역내 **책임 경제운영자(EU 대리인)**가 없으면 판매할 수 없습니다",
                     "DoC와 기술문서를 10년 보관해야 합니다"],
           "knowledge": "cert-eu-ce"}

# 나라 이름과 함께 나와야 "그 나라로 수출하는 법"을 묻는 것입니다.
ASK_WORDS = ("수출", "보내", "통관", "인증", "규제", "절차", "서류", "팔", "진출", "요건")
ALIASES = {"미국": "US", "유럽": "EU", "eu": "EU", "영국": "GB", "중국": "CN", "일본": "JP",
           "베트남": "VN", "인니": "ID", "아랍에미리트": "AE", "두바이": "AE", "uae": "AE",
           "사우디": "SA", "러시아": "RU", "대만": "TW", "홍콩": "HK", "터키": "TR",
           "호주": "AU", "뉴질랜드": "NZ", "캐나다": "CA", "멕시코": "MX", "브라질": "BR",
           "인도": "IN", "태국": "TH", "말레이시아": "MY", "싱가포르": "SG", "필리핀": "PH",
           "인도네시아": "ID"}


def _countries() -> dict[str, str]:
    """{국가코드: 한국어 이름}. 우리가 이미 들고 있는 목록을 그대로 씁니다."""

    from app.collectors import location_client

    return {code: row["name"] for code, row in location_client._countries().items()}


def _eu_members() -> tuple[str, ...]:
    from app.processors import fta_guide

    return tuple(fta_guide.blocs().get("EU", ()))


# 흔한 말과 겹치는 짧은 나라 이름 — 나라 뜻으로 쓴 것이 **분명할 때만** 인정합니다.
# "서류 가나다순 수출"이 가나로, "오만한 바이어"가 오만으로, "말리 수 있나"가 말리로 갔습니다(전수 점검).
_SHORT_NOT_COUNTRY_AFTER = ("조건", "장소", "받", "하", "네시아", "가", "되", "다순", "한", "수 ")
_HANGUL = re.compile(r"[가-힣]")
_ASK_AFTER = re.compile(r"^(?:으?로|에|의|은|는|이|가)?(?:" + "|".join(ASK_WORDS) + r"|수입|관세|제재|금수)")
_COMMON_WORD_NAMES = {"수단", "가나", "말리", "오만", "도미니카"}

# 정식 표기와 흔한 별칭(2회차 전수 검사에서 못 찾던 것)
_MORE_ALIASES = {"튀르키예": "TR", "타이완": "TW", "마카오": "MO", "중앙아프리카공화국": "CF", "적도기니": "GQ",
                 "도미니카공화국": "DO", "콩고민주공화국": "CD", "다알씨": "CD", "인도네시아": "ID"}


def find_country(text: str) -> tuple[str, str] | None:
    """물어본 글에서 나라를 찾습니다. 없으면 None.

    긴 이름부터, 띄어쓰기를 무시하고 찾습니다 — "인도네시아"가 "인도"보다 먼저 맞아야 하고 "적도 기니"가 "기니"로
    가면 안 됩니다. 짧은 이름은 앞뒤 글자를 보고 다른 낱말의 일부(개인도·인도조건)를 거릅니다.
    """

    asked = str(text or "")
    if not any(word in asked for word in ASK_WORDS):
        return None
    squeezed = re.sub(r"\s+", "", asked.lower())
    # "미국 말고 인도로 수출" — 도착국은 부정어 **뒤**의 나라입니다.
    for negation in ("말고", "아니고", "아니라", "빼고", "제외하고"):
        if negation in squeezed:
            tail = squeezed.split(negation)[-1]
            found = _find_in(tail)
            if found:
                return found
    return _find_in(squeezed)


def _find_in(squeezed: str) -> tuple[str, str] | None:
    names = _countries()
    keys: dict[str, tuple[str, str]] = {}
    for alias, code in {**ALIASES, **_MORE_ALIASES}.items():
        if code == "EU" or code in names:
            keys[alias.replace(" ", "")] = (code, "유럽연합(EU)" if code == "EU" else names[code])
    for code, name in names.items():
        if len(name.replace(" ", "")) >= 2:
            keys.setdefault(name.replace(" ", "").lower(), (code, name))
    for key in sorted(keys, key=len, reverse=True):
        start = squeezed.find(key)
        while start != -1:
            end = start + len(key)
            before, after = squeezed[start - 1:start] if start else "", squeezed[end:]
            ok = True
            if len(key) <= 2 or key in _COMMON_WORD_NAMES:
                if before and _HANGUL.match(before):
                    ok = False
                elif after.startswith(_SHORT_NOT_COUNTRY_AFTER):
                    ok = False
                elif key in _COMMON_WORD_NAMES and not _ASK_AFTER.match(after):
                    ok = False
            if ok:
                return keys[key]
            start = squeezed.find(key, start + 1)
    return None


def agreements(code: str) -> list[str]:
    """그 나라에 쓸 수 있는 협정. 발효 여부는 늘 확인하라고 덧붙입니다."""

    from app.processors import fta_guide

    found = []
    blocs = fta_guide.blocs()
    if code in BILATERAL:
        found.append(BILATERAL[code])
    if code in blocs.get("EU", ()):
        found.append("한·EU FTA")
    if code in blocs.get("EFTA", ()):
        found.append("한·EFTA FTA")
    if code in blocs.get("아세안", ()):
        found.append("한·아세안 FTA")
    if code in blocs.get("중미", ()):
        found.append("한·중미 FTA")
    if code in RCEP:
        found.append("RCEP")
    if code in APTA:
        found.append("APTA")
    return list(dict.fromkeys(found))


# --- 도착국 세번(HS) -------------------------------------------------------------
#
# HS 6자리는 세계 공통입니다. **그 뒤는 나라마다 다릅니다.** 6자리만 들고 견적을
# 내면, 정작 세율과 수입요건이 갈리는 자리를 못 봅니다. 미국은 10자리, 대만은
# 11자리, 중국은 신고할 때 13자리를 씁니다.
#
# 우리 쪽 HSK 10자리를 그대로 도착국에 쓸 수 없습니다. 앞 6자리만 같습니다.
#
# 자릿수와 조회처는 2026-09-26에 하나씩 확인했습니다. 모르는 나라는 비워 둡니다.
ASEAN_TARIFF = ("8자리 AHTN (아세안 공통)", "https://www.tradenavi.or.kr")
EAEU_TARIFF = ("10자리 TN VED (유라시아경제연합 공통)", "https://eec.eaeunion.org/en/")

TARIFF_CODES = {
    "US": ("10자리 HTSUS", "https://hts.usitc.gov/"),
    "EU": ("10자리 TARIC (신고는 8자리 CN)",
           "https://ec.europa.eu/taxation_customs/dds2/taric/taric_consultation.jsp?Lang=en"),
    "GB": ("10자리 UK Global Tariff", "https://www.trade-tariff.service.gov.uk/"),
    "JP": ("9자리 실행관세율표", "https://www.customs.go.jp/english/tariff/"),
    "CN": ("13자리 (세칙 8 + 감독관리 2 + 검사검역 3)",
           "http://www.customs.gov.cn/customs/302427/302442/jckszcx/index.html"),
    "TW": ("11자리 CCC", "https://fbfh.trade.gov.tw/fh/ap/listCCCf.do"),
    "CA": ("10자리", "https://www.cbsa-asfc.gc.ca/trade-commerce/tariff-tarif/menu-eng.html"),
    "AU": ("8자리 Working Tariff",
           "https://www.abf.gov.au/importing-exporting-and-manufacturing/tariff-classification"),
    "IN": ("8자리 ITC(HS)", "https://www.icegate.gov.in/"),
    # GCC 6개국은 2025-01부터 12자리 통합관세로 바뀌었습니다. 예전 8자리 자료를
    # 그대로 쓰면 뒤 네 자리가 비어 신고가 반려됩니다. (2026-09-26 확인)
    "SA": ("12자리 GCC 통합관세", "https://zatca.gov.sa/en/"),
    "AE": ("12자리 GCC 통합관세", "https://www.dubaicustoms.gov.ae/en/"),
    "BH": ("12자리 GCC 통합관세", "https://www.customs.gov.bh/"),
    "KW": ("12자리 GCC 통합관세", "https://www.customs.gov.kw/"),
    "OM": ("12자리 GCC 통합관세", "https://www.customs.gov.om/"),
    "QA": ("12자리 GCC 통합관세", "https://www.customs.gov.qa/"),
    "TR": ("12자리 GTİP",
           "https://www.trade.gov.tr/customs-formalities/frequently-asked-questions/tariff"),
    "MX": ("8자리 TIGIE (통계용 NICO 2자리가 더 붙기도 합니다)", "https://www.snice.gob.mx/"),
    "BR": ("8자리 NCM (메르코수르 공통)", "https://portalunico.siscomex.gov.br/classif/#/sumario"),
    "NZ": ("8자리 Working Tariff", "https://www.customs.govt.nz/business/tariffs/"),
    "HK": ("8자리 HKHS", "https://www.censtatd.gov.hk/en/index_hs_code.html"),
    "RU": EAEU_TARIFF,
    "BY": EAEU_TARIFF, "KZ": EAEU_TARIFF, "KG": EAEU_TARIFF, "AM": EAEU_TARIFF,
    "VN": ASEAN_TARIFF, "TH": ASEAN_TARIFF, "MY": ASEAN_TARIFF, "PH": ASEAN_TARIFF,
    "ID": ASEAN_TARIFF, "SG": ASEAN_TARIFF, "BN": ASEAN_TARIFF, "KH": ASEAN_TARIFF,
    "LA": ASEAN_TARIFF, "MM": ASEAN_TARIFF,
}


def tariff_code(code: str) -> tuple[str, str] | None:
    """그 나라 세번 자릿수와 관세율표 조회처. 모르면 None (지어내지 않습니다)."""

    code = str(code or "").strip().upper()
    if code in TARIFF_CODES:
        return TARIFF_CODES[code]
    return TARIFF_CODES["EU"] if code == "EU" or code in _eu_members() else None


def guide(code: str, name: str) -> str:
    """그 나라로 수출하는 법 한 장. (마크다운)"""

    eu = code == "EU" or code in _eu_members()
    note = EU_NOTE if (eu and code not in NOTES) else NOTES.get(code, {})
    deals = agreements(code) if code != "EU" else ["한·EU FTA"]

    from app.processors import trade_controls

    control = trade_controls.note(code)
    control_level = trade_controls.level(code)
    lines = [f"## {name} 수출하기", ""]
    if control:
        # 제재·수출통제 대상은 다른 모든 안내보다 **먼저** 말합니다(전수 점검).
        lines += [f"> {control}", ""]
    if control_level == "blocked":
        # 막힌 나라에 "순서는 같습니다 … 포워더 부킹 → 수출신고 → 선적"을 이어 보이면 앞뒤가 모순입니다(기업 점검).
        return "\n".join(lines + ["이 서비스에서는 이 나라로 견적과 서류를 만들지 않습니다. 승인·허가 절차를 먼저 확인하세요."])
    if control_level == "strict":
        return "\n".join(lines + [
            "### 먼저 확인할 것", "",
            "1. **전략물자 해당 여부** — 품목이 통제 대상인지 [yesTrade](https://www.yestrade.go.kr)에서 판정",
            "2. **거래 상대방** — 제재 명단(미국 OFAC·EU·UN 등)에 있는지, 최종 사용자와 최종 목적지가 맞는지",
            "3. **결제 경로** — 은행이 이 나라 거래를 받아 주는지(신용장·송금 모두)",
            "4. **재수출 통제** — 제3국을 거쳐 통제 대상국으로 가지 않는지",
            "", "위 네 가지가 정리된 뒤에 견적·서류를 진행하세요. 일반 수출 절차와 관세 안내는 그 다음 단계입니다."])
    lines += ["어느 나라든 **순서는 같습니다.** 다른 것은 ③ 도착국 규제뿐입니다.", "",
             "1. HS 부호 10자리 확정 → 우리 쪽 수출요건 확인",
             "2. 계약(인코텀즈·결제조건) → 바이어 신용 확인",
             "3. **도착국 인증·라벨 확인** ← 여기가 나라마다 다릅니다",
             "4. 포워더 부킹 → 수출신고 → 선적",
             "5. 서류 발송(송장·포장명세서·B/L·C/O) → 대금 회수 → 관세환급·영세율", ""]

    lines += ["### 관세 (FTA)", ""]
    if control_level in ("blocked", "strict"):
        lines.append("관세·FTA 안내는 **거래가 가능한지 확인한 뒤**에 보세요. 이 나라는 일반세율 적용 여부를 떠나 "
                     "수출통제·제재 판정이 먼저입니다.")
    elif deals:
        lines.append(f"적용해 볼 수 있는 협정: **{' · '.join(deals)}**")
        lines.append("")
        lines.append("협정이 둘 이상이면 **세율이 낮은 쪽을 골라** 원산지증명서를 받으면 됩니다. "
                     "협정마다 원산지 기준과 서식이 다르니 [FTA 강국 KOREA](https://www.fta.go.kr)에서 HS 6자리로 확인하세요.")
    else:
        # 나라 이름은 우리가 들고 있는 말이라 조사를 정확히 고를 수 있습니다.
        # "남아프리카공화국와(과)는"처럼 나오면 읽는 사람이 먼저 걸립니다.
        lines.append(f"{korean.josa(name, '와')}는 한국이 맺은 FTA가 확인되지 않습니다. **일반세율(MFN)**이 "
                     "적용될 가능성이 큽니다. 협정 발효 상황은 바뀌므로 "
                     "[FTA 강국 KOREA](https://www.fta.go.kr)에서 다시 확인하세요.")
    lines.append("")

    # HS 6자리만 알고 끝내면, 정작 세율이 갈리는 자리를 못 봅니다.
    found_code = tariff_code(code)
    lines += ["### 도착국 세번(HS)", "",
              "HS **앞 6자리는 세계 공통**입니다. 그 뒤는 나라마다 다릅니다. "
              "우리 쪽 HSK 10자리를 그대로 쓸 수 없고, 앞 6자리만 같습니다."]
    if found_code:
        digits, url = found_code
        lines.append(f"- {name}: **{digits}** — [그 나라 관세율표에서 찾기]({url})")
    else:
        lines.append(f"- {name}의 자릿수는 우리가 들고 있지 않습니다. "
                     f"[TradeNAVI](https://www.tradenavi.or.kr)에 HS 6자리와 나라를 "
                     "넣으면 그 나라 세번과 세율이 나옵니다.")
    lines += ["- 우리 쪽(수출신고)은 **HSK 10자리**입니다 — "
              "[관세청 품목분류](https://unipass.customs.go.kr/clip/index.do)", ""]

    lines += ["### 도착국 규제·인증", ""]
    if note.get("certs"):
        lines += [f"- {row}" for row in note["certs"]]
    else:
        lines += ["- **이 나라는 우리가 정리해 둔 인증 자료가 없습니다.** 아래는 일반 안내이며, KOTRA 해외시장뉴스와 "
                  "현지 수입자에게 강제 인증·선적 전 검사 제도가 있는지 먼저 확인하세요.",
                  "- 이 나라의 강제 인증은 **품목(HS)에 따라** 갈립니다. 아래 창구에서 "
                  "품목을 넣어 확인하세요.",
                  "- 전기·전자는 안전·전파 인증, 식품·화장품은 등록·성분 규제, 섬유·완구는 "
                  "라벨 규정이 걸리는 것이 일반적입니다.",
                  "- 목재 포장재를 쓰면 **ISPM 15 열처리 마크**는 거의 모든 나라에서 요구합니다."]
    lines.append("")

    if note.get("watch"):
        lines += ["### 이 나라에서 조심할 것", ""]
        lines += [f"- {row}" for row in note["watch"]]
        lines.append("")

    # 이름만 굵게 적어 두면 사람은 또 검색해야 합니다. 주소를 바로 겁니다. (2026-09-26)
    lines += ["### 어디서 확인하나", "",
              "- [**KOTRA 해외시장뉴스** 국가·지역정보](https://dream.kotra.or.kr/kotranews/index.do)"
              " — 나라별 통관·인증·시장 자료",
              "- [**TradeNAVI**](https://www.tradenavi.or.kr)"
              " — HS 부호를 넣으면 나라별 관세·수입요건을 모아 보여 줍니다",
              "- [**FTA 강국 KOREA**](https://www.fta.go.kr) — 협정별 세율과 원산지 기준",
              "- 인증이 걸리면 KTR·KTL·KTC 같은 국내 시험인증기관에 품목·사양을 주고 "
              "먼저 견적과 기간을 받아 보세요. **인증은 몇 주에서 몇 달**이 걸립니다. "
              "계약 납기를 정하기 전에 확인하셔야 합니다."]
    if note.get("knowledge"):
        lines += ["", f"이 나라는 더 자세한 자료가 있습니다. **\"{name} 인증\"**이라고 물어보세요."]
    return "\n".join(lines)


def links(code: str, name: str) -> list[dict]:
    """나라별로 바로 열 수 있는 창구. 주소는 우리가 들고 있는 것만 씁니다.

    예전에는 `] if not quote else []` 로 끝나 **늘 빈 목록**을 돌려주었습니다.
    quote는 불러 온 함수라 언제나 참이어서, 이 함수가 하는 일이 없었습니다.
    (2026-09-26)
    """

    rows = [
        {"label": f"KOTRA 해외시장뉴스 · {name}", "url": "https://dream.kotra.or.kr/kotranews/index.do"},
        {"label": "TradeNAVI (품목별 나라 관세·요건)", "url": "https://www.tradenavi.or.kr"},
        {"label": "FTA 강국, KOREA (협정 세율·원산지 기준)", "url": "https://www.fta.go.kr"},
        {"label": "관세청 (수출통관·요건)", "url": "https://www.customs.go.kr"},
    ]
    found = tariff_code(code)
    if found:
        rows.insert(1, {"label": f"{name} 관세율표 ({found[0]})", "url": found[1]})
    return rows


def answer(question: str) -> dict | None:
    """나라 이름이 들어 있으면 그 나라 수출 안내를 만듭니다. 아니면 None."""

    found = find_country(question)
    if not found:
        return None
    code, name = found
    return {"key": f"country-{code.lower()}", "title": f"{name} 수출 안내",
            "body": guide(code, name), "see": [], "render": "",
            "links": [
                {"label": f"KOTRA 해외시장뉴스 · {name}",
                 "url": "https://dream.kotra.or.kr/kotranews/index.do"},
                {"label": "TradeNAVI (품목별 나라 관세·요건)", "url": "https://www.tradenavi.or.kr"},
                {"label": "FTA 강국, KOREA", "url": "https://www.fta.go.kr"},
                {"label": "관세청", "url": "https://www.customs.go.kr"},
            ]}
