"""HS부호로 수출 전에 챙겨야 할 서류를 짚어 줍니다.

한국에서 물건을 내보낼 때 관세 신고 말고도 따로 받아야 하는 허가·증명이
있습니다. 무엇이 필요한지는 「대외무역법」 통합공고와 품목별 개별법이 정하고,
기준은 HS부호입니다.

여기 있는 규칙은 HS 류(앞 2~4자리)를 보고 "이 품목이면 이런 것을 확인해야
한다"를 알려 주는 안내입니다. 법령 원문을 대신하지 않습니다. 세번 하나까지
따지면 같은 류 안에서도 갈리는 경우가 있어, 항목마다 확인할 곳을 함께 답니다.

확인은 아래에서 합니다.
- 관세법령정보포털 세번별 수출입요건 (품목별 통합공고 확인)
- 전략물자관리시스템 자가판정 (전략물자 해당 여부)
"""

from __future__ import annotations

# 확인해야 할 곳. 화면에서 새 창으로 열어 줍니다.
LOOKUP_LINKS = {
    "통합공고": {
        "label": "관세법령정보포털 · 세번별 수출입요건",
        "url": "https://unipass.customs.go.kr/clip/index.do",
        "how": "세번(HS부호) 10자리를 넣으면 그 번호에 걸린 수출 요건이 모두 나옵니다.",
    },
    "전략물자": {
        "label": "전략물자관리시스템 · 자가판정",
        "url": "https://www.yestrade.go.kr",
        "how": "품목 사양을 넣어 전략물자인지 스스로 판정합니다. 판정서를 받아 두면 "
               "통관에서 다시 묻지 않습니다.",
    },
    "식품": {
        "label": "식품안전나라 · 해외 수출 정보",
        "url": "https://www.foodsafetykorea.go.kr",
        "how": "수입국이 요구하는 위생증명서 서식과 발급 절차를 확인합니다.",
    },
    "검역": {
        "label": "농림축산검역본부 · 수출검역",
        "url": "https://www.qia.go.kr",
        "how": "식물·동물·축산물은 수입국이 요구하는 검역 조건이 나라마다 다릅니다.",
    },
    "화장품": {
        "label": "식품의약품안전처 · 화장품 수출",
        "url": "https://www.mfds.go.kr",
        "how": "수입국이 요구하면 제조판매증명서(CFS)를 발급받습니다.",
    },
    "위험물": {
        "label": "화학물질정보처리시스템 · MSDS",
        "url": "https://msds.kosha.or.kr",
        "how": "물질안전보건자료(MSDS)를 내려받아 선사·항공사에 냅니다.",
    },
    "폐기물": {
        "label": "환경부 · 폐기물 수출입 신고",
        "url": "https://www.me.go.kr",
        "how": "바젤협약 대상 폐기물은 수출 전에 신고하고 수입국 동의를 받아야 합니다.",
    },
    "야생생물": {
        "label": "환경부 · CITES 수출허가",
        "url": "https://www.me.go.kr",
        "how": "멸종위기종과 그 가공품은 CITES 허가서 없이 내보낼 수 없습니다.",
    },
    "문화재": {
        "label": "국가유산청 · 국외반출 허가",
        "url": "https://www.khs.go.kr",
        "how": "오래된 물건은 일반 공산품처럼 보내지 못하고 반출 허가를 받아야 합니다.",
    },
}


def _rule(key, title, chapters, documents, agency, law, why, link, headings=()):
    return {
        "key": key, "title": title, "chapters": set(chapters), "headings": set(headings),
        "documents": documents, "agency": agency, "law": law, "why": why, "link": link,
    }


# HS 류(앞 2자리) 또는 호(앞 4자리)로 거릅니다.
RULES = [
    _rule(
        "food", "식품 · 위생증명",
        chapters=["04", "07", "08", "09", "10", "11", "15", "16", "17", "18", "19",
                  "20", "21", "22"],
        documents=["위생증명서 (Health Certificate)", "자유판매증명서 (CFS)",
                   "성분·제조공정 설명서"],
        agency="식품의약품안전처 · 지방식약청",
        law="식품위생법 · 수출입식품안전관리 특별법",
        why="식품은 수입국이 우리 정부가 발급한 위생증명서를 요구하는 경우가 많습니다. "
            "서식과 문구를 수입국이 정해 두어 미리 맞춰야 합니다.",
        link="식품",
    ),
    _rule(
        "plant", "농산물 · 식물검역",
        chapters=["06", "07", "08", "09", "10", "11", "12", "13", "14", "44"],
        documents=["식물검역증명서 (Phytosanitary Certificate)"],
        agency="농림축산검역본부",
        law="식물방역법",
        why="살아 있는 식물과 씨앗·과일·목재는 병해충이 옮을 수 있어 수입국이 검역증을 "
            "요구합니다. 목재 포장재도 소독(IPPC) 대상입니다.",
        link="검역",
    ),
    _rule(
        "animal", "축산물 · 동물검역",
        chapters=["01", "02", "03", "05", "16"],
        documents=["동물검역증명서 (Veterinary Certificate)", "도축·가공시설 등록 확인"],
        agency="농림축산검역본부",
        law="가축전염병 예방법",
        why="고기·유제품·알과 그 가공품은 수입국이 우리 검역기관의 증명서를 요구합니다. "
            "수출 가능한 작업장이 나라별로 따로 지정돼 있습니다.",
        link="검역",
    ),
    _rule(
        "pharma", "의약품 · 의료기기",
        chapters=["30", "90"],
        documents=["제조·판매증명서 (CPP / CFS)", "GMP 증명서", "성분 분석 성적서"],
        agency="식품의약품안전처",
        law="약사법 · 의료기기법",
        why="의약품과 의료기기는 수입국 허가 절차에 우리 정부의 제조·판매증명서가 "
            "들어갑니다. 발급에 시간이 걸려 미리 신청해야 합니다.",
        link="화장품",
    ),
    _rule(
        "cosmetic", "화장품",
        chapters=["33"],
        documents=["자유판매증명서 (CFS)", "성분표 (INCI)", "제조판매업 등록증"],
        agency="식품의약품안전처 · 대한화장품협회",
        law="화장품법",
        why="화장품은 수입국이 '한국에서 자유롭게 팔리는 제품'이라는 증명과 전성분표를 "
            "요구하는 경우가 많습니다.",
        link="화장품",
    ),
    _rule(
        "strategic", "전략물자 해당 여부",
        chapters=["28", "29", "38", "72", "73", "76", "81", "84", "85", "87", "88",
                  "89", "90", "93"],
        documents=["전략물자 판정서", "수출허가서 (해당하는 경우)"],
        agency="전략물자관리원 · 산업통상자원부",
        law="대외무역법 제19조",
        why="기계·전자·화학 품목은 사양에 따라 전략물자가 될 수 있습니다. 해당하는데 "
            "허가 없이 내보내면 형사처벌 대상이라 판정부터 받아야 합니다. "
            "HS부호만으로는 갈리지 않고 사양으로 갈립니다.",
        link="전략물자",
    ),
    _rule(
        "waste", "폐기물 · 재생원료",
        chapters=["26", "38", "39", "47", "72", "74"],
        headings=["3915", "4707", "7204", "7404", "7602", "8548"],
        documents=["폐기물 수출신고증", "수입국 동의서 (바젤협약 대상)"],
        agency="환경부 · 한국환경공단",
        law="폐기물의 국가 간 이동 및 그 처리에 관한 법률",
        why="고철·폐플라스틱·폐지 같은 재생원료는 바젤협약 대상이면 수출 전에 신고하고 "
            "수입국 동의를 받아야 합니다.",
        link="폐기물",
    ),
    _rule(
        "cites", "야생생물 · CITES",
        chapters=["01", "02", "03", "05", "06", "12", "41", "43", "44", "92", "96"],
        documents=["CITES 수출허가서", "인공증식증명서"],
        agency="환경부 · 국립생물자원관",
        law="야생생물 보호 및 관리에 관한 법률",
        why="멸종위기종과 그 가공품(가죽·모피·상아·일부 목재)은 허가서 없이 내보낼 수 "
            "없습니다. 가공품도 대상입니다.",
        link="야생생물",
    ),
    _rule(
        "heritage", "문화재 · 국외반출",
        chapters=["97"],
        documents=["문화유산 국외반출 허가서", "비문화재 확인서"],
        agency="국가유산청",
        law="문화유산의 보존 및 활용에 관한 법률",
        why="오래된 미술품·골동품은 문화재인지 먼저 확인받아야 합니다. 문화재가 아니면 "
            "'비문화재 확인서'를 받아 통관에 씁니다.",
        link="문화재",
    ),
]

# 위험물은 HS부호가 아니라 화물 자체의 성질로 정해집니다.
DANGEROUS_RULE = {
    "key": "dangerous",
    "title": "위험물 신고",
    "documents": ["물질안전보건자료 (MSDS)", "위험물 신고서 (Shipper's Declaration)",
                  "포장 성적서 (UN 표시)"],
    "agency": "선사 · 항공사 · 한국해사위험물검사원",
    "law": "IMDG Code (해상) · IATA DGR (항공)",
    "why": "위험물은 선사·항공사가 부킹 전에 MSDS와 신고서를 보고 실을지 정합니다. "
           "서류가 늦으면 배를 놓칩니다.",
    "link": "위험물",
}

ORIGIN_RULE = {
    "key": "origin",
    "title": "원산지증명서",
    "documents": ["원산지증명서 (C/O)"],
    "agency": "세관 · 대한상공회의소",
    "law": "대외무역법 · 각 FTA 협정",
    "why": "바이어가 관세를 깎으려면 원산지증명서가 필요합니다. 협정마다 서식과 "
           "발급 주체가 달라 어느 협정으로 받을지 먼저 정해야 합니다.",
    "link": "통합공고",
}


def _digits(hs_code: str) -> str:
    return "".join(ch for ch in (hs_code or "") if ch.isdigit())


def check(hs_code: str, *, is_dangerous: bool = False,
          buyer_wants_origin: bool = False) -> list[dict]:
    """이 품목에서 확인해야 할 요건을 모읍니다.

    "필요하다"가 아니라 "확인해야 한다"입니다. 같은 류 안에서도 세번에 따라
    갈리는 것이 있어, 우리가 단정하면 틀립니다.
    """

    digits = _digits(hs_code)
    chapter, heading = digits[:2], digits[:4]

    found = []
    if digits:
        for rule in RULES:
            if chapter in rule["chapters"] or (heading and heading in rule["headings"]):
                found.append(_as_item(rule))
    if is_dangerous:
        found.append(_as_item(DANGEROUS_RULE))
    if buyer_wants_origin:
        found.append(_as_item(ORIGIN_RULE))
    return found


def _as_item(rule: dict) -> dict:
    link = LOOKUP_LINKS[rule["link"]]
    return {
        "key": rule["key"],
        "title": rule["title"],
        "documents": list(rule["documents"]),
        "agency": rule["agency"],
        "law": rule["law"],
        "why": rule["why"],
        "lookup": link,
    }


def summary(hs_code: str, items: list[dict]) -> str:
    """한 줄 요약."""

    if not _digits(hs_code):
        return "HS부호를 입력하면 이 품목에 걸린 수출 요건을 짚어 드립니다."
    if not items:
        return ("이 류에는 흔히 걸리는 수출 요건이 없습니다. 그래도 세번 10자리 기준으로는 "
                "달라질 수 있어 관세법령정보포털에서 한 번 확인해 주세요.")
    titles = " · ".join(item["title"] for item in items)
    return f"확인할 것이 {len(items)}가지입니다. {titles}"
