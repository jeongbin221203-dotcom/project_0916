"""답변 아래에 붙일 "관련 링크"를 고릅니다.

왜 우리 코드가 고르는가
  AI에게 주소를 적게 하면 없는 주소를 만들어 냅니다. 사람은 그걸 믿고 눌렀다가
  헤맵니다. 그래서 주소는 **우리가 들고 있는 표**에서만 꺼냅니다. AI는 답만 쓰고,
  링크는 질문·답에 나온 말을 보고 여기서 붙입니다.

두 가지를 함께 냅니다.
  화면(screen)  우리 서비스 안에서 바로 할 수 있는 일 (서류 작성 · 관세청 조회 …)
  기관(agency)  실제로 신청·확인해야 하는 공공 창구 (관세청 · 식약처 · 검역본부 …)

기관 주소는 export_requirements.LOOKUP_LINKS와 fta_guide에 이미 정리된 것을 씁니다.
그 표가 화면 여러 곳에서 쓰이므로, 주소가 바뀌면 한 곳만 고치면 됩니다.
"""

from __future__ import annotations

import re

MAX_LINKS = 4

# 화면 안에서 이어서 할 일. url은 우리 라우트입니다. (#hs는 HS 간편 검색 창을 엽니다)
SCREEN_LINKS = [
    {"key": "documents", "label": "📄 서류 작성", "url": "/documents/new",
     "note": "상업송장·포장명세서를 칸 채워 만들기",
     "words": ("서류", "인보이스", "invoice", "송장", "패킹", "packing", "명세서", "b/l", "bl",
               "선하증권", "작성", "발행")},
    {"key": "planning", "label": "📦 운송 계획", "url": "/planning/new",
     "note": "출발·도착지와 화물로 스케줄·물류비 보기",
     "words": ("운임", "운송", "스케줄", "선적", "컨테이너", "lcl", "fcl", "cbm", "물류비",
               "견적", "항공", "해상", "포워더")},
    {"key": "lookup", "label": "🔎 관세청 조회", "url": "/lookup/",
     "note": "HS부호·관세율·수출입 통계",
     "words": ("관세", "세율", "hs", "품목분류", "통계", "실적", "수입국", "관세청")},
    {"key": "tracking", "label": "🚢 컨테이너 조회", "url": "/tracking/container",
     "note": "컨테이너·B/L 번호로 화물 위치 보기",
     # "어디"처럼 흔한 말은 넣지 않습니다. 원산지증명서를 "어디서 받나요"에도 붙습니다.
     "words": ("추적", "화물 위치", "어디쯤", "어디 있", "도착했", "컨테이너번호",
               "container no", "b/l no")},
    {"key": "dashboard", "label": "📊 Dashboard", "url": "/dashboard",
     "note": "내 Shipment 현황과 만든 서류",
     "words": ("내 건", "진행", "현황", "대시보드", "dashboard")},
]

# 기관 창구. 여기 없는 주제는 붙이지 않습니다. (억지로 붙이면 틀린 곳으로 보냅니다)
AGENCY_WORDS = {
    "통합공고": ("수출요건", "요건", "허가", "승인", "통합공고"),
    "전략물자": ("전략물자", "수출통제", "이중용도", "yestrade"),
    "식품": ("식품", "음료", "건강기능", "농산물"),
    "검역": ("검역", "식물", "동물", "축산", "목재"),
    "화장품": ("화장품", "의약외품", "기능성"),
    "위험물": ("위험물", "msds", "un번호", "un no", "배터리", "리튬"),
    "폐기물": ("폐기물", "재활용", "고철"),
    "멸종위기": ("cites", "멸종", "상아", "가죽"),
    "문화재": ("문화재", "골동", "미술품"),
}
FTA_WORDS = ("fta", "원산지", "협정", "특혜", "c/o", "원산지증명")


def _text(*parts: str) -> str:
    return " ".join(str(part or "") for part in parts).lower()


def _hit(words: tuple, text: str) -> bool:
    return any(word in text for word in words)


def _hs_query(question: str) -> str:
    """HS 간편 검색 창에 넣을 품명. 답이 이미 #hs 링크를 넣었으면 붙이지 않습니다."""

    match = re.search(r"([가-힣A-Za-z][가-힣A-Za-z0-9 ]{1,20})\s*(?:의|을|를)?\s*"
                      r"(?:hs\s*코드|hs부호|품목분류)", question, re.I)
    return match.group(1).strip() if match else ""


def pick(question: str, answer: str = "") -> list[dict]:
    """질문과 답에 맞는 링크. 없으면 빈 목록입니다. (억지로 채우지 않습니다)"""

    from app.processors import export_requirements, fta_guide

    text = _text(question, answer)
    links: list[dict] = []

    for row in SCREEN_LINKS:
        if _hit(row["words"], text):
            links.append({"kind": "screen", "label": row["label"], "url": row["url"],
                          "note": row["note"]})

    # HS부호를 물었으면 그 품명으로 검색 창을 여는 링크를 답 아래에도 둡니다.
    product = _hs_query(question)
    if product and "#hs:" not in answer:
        links.append({"kind": "screen", "label": f"🔎 HS CODE 간편 검색 · {product}",
                      "url": f"#hs:{product}", "note": "관세청 품목표에서 후보를 비교합니다"})

    for key, words in AGENCY_WORDS.items():
        row = export_requirements.LOOKUP_LINKS.get(key)
        if row and _hit(words, text):
            links.append({"kind": "agency", "label": row["label"], "url": row["url"],
                          "note": "신청·확인 창구"})

    if _hit(FTA_WORDS, text):
        for row in fta_guide.all_apply_links()[:2]:
            links.append({"kind": "agency", "label": row["label"], "url": row["url"],
                          "note": row.get("note", "")})

    # 같은 주소가 두 번 나오지 않게 하고, 너무 많이 붙이지 않습니다.
    seen, picked = set(), []
    for link in links:
        if link["url"] in seen:
            continue
        seen.add(link["url"])
        picked.append(link)
    return picked[:MAX_LINKS]
