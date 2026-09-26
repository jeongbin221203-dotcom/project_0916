"""수출 서류를 **어디서 어떻게** 받는지. 이름만 알려 주고 끝내지 않기 위한 표입니다.

왜 필요한가
  상담이 "위생증명서·성분분석서·COA 등이 필요할 수 있습니다"까지만 답하고 있었습니다.
  이름을 알아도 처음 수출하는 사람은 **어디로 가야 하는지**를 모릅니다. 검색하면
  대행업체 광고가 먼저 나오고, 정작 공식 창구는 한참 뒤에 있습니다.

  그래서 서류마다 발급기관·신청 방법·걸리는 시간·주소를 함께 둡니다.

무엇을 지키나
  - **주소는 이 표에서만 꺼냅니다.** AI가 주소를 지어내면 없는 창구로 보내게 됩니다.
  - 공식 기관만 적습니다. 대행업체는 넣지 않습니다.
  - 걸리는 시간은 "보통 이 정도"입니다. 기관 사정과 품목에 따라 달라집니다.
  - 모르는 것은 비워 둡니다. 수수료는 품목·건수마다 달라 대부분 적지 않았습니다.

찾는 방법
  서류 이름은 서식마다 다르게 적힙니다(위생증명서 / Health Certificate / 보건증).
  그래서 이름이 정확히 같은지 보지 않고, `keywords` 가운데 하나라도 들어 있으면
  같은 서류로 봅니다.

주소를 다시 확인하려면
      python scripts/check_doc_links.py

  몇 곳은 **기계가 두드리는 것을 막아** 자동 확인이 안 됩니다. 주소가 틀린 것이
  아니라 차단당한 것입니다. (2026-09-25 확인)
      FDA·access.fda.gov  기계 접속 차단 (abuse-detection으로 돌려보냄)
      FCC                 HTTP 403
      식약처·식품안전나라      연결 시간 초과
      한국해사위험물검사원      인증서 문제 (SSLError) — 브라우저에서는 열립니다
      관세청 UNI-PASS       기관 서버가 멈춰 있음
  이런 곳은 사람이 브라우저로 한 번 열어 보고 고쳐야 합니다.
"""

from __future__ import annotations

# 각 줄: 무엇을 · 어디서 · 어떻게 · 얼마나 걸리나 · 주소
#
# "how"는 **처음 하는 사람이 그대로 따라 할 수 있게** 적습니다. "신청하세요"가 아니라
# 어느 시스템에 들어가 무엇을 먼저 해야 하는지까지 적습니다.
ISSUERS = [
    {
        "key": "origin",
        "title": "원산지증명서 (C/O)",
        "keywords": ("원산지증명", "C/O", "CO 발급", "origin certificate"),
        "agency": "관세청(세관) 또는 대한상공회의소",
        "how": "협정이 기관발급이면 둘 중 한 곳에서 받습니다. 자율발급 협정(한·미 FTA 등)은 "
               "수출자가 협정 서식에 직접 적고 서명합니다. 어느 쪽인지는 협정마다 다릅니다.",
        "lead_time": "기관발급 1~3 영업일",
        "url": "https://cert.korcham.net",
        "extra": [
            ("관세청 FTA 포털 · 협정별 서식", "https://www.customs.go.kr/ftaportalkor/main.do"),
            ("FTA-PASS 원산지관리시스템 (무료)", "https://www.ftapass.or.kr"),
        ],
        "caution": "사후 검증이 5년 뒤에 옵니다. 원산지소명서·BOM·제조공정도를 함께 보관하세요.",
    },
    {
        "key": "health",
        "title": "위생증명서 (Health Certificate)",
        "keywords": ("위생증명", "health certificate", "보건증명"),
        "agency": "식품의약품안전처 · 지방식품의약품안전청",
        "how": "식품안전나라 또는 관할 지방식약청에 신청합니다. 제조업 등록과 "
               "품목제조보고가 먼저 되어 있어야 합니다.",
        "lead_time": "3~7 영업일",
        "url": "https://www.mfds.go.kr",
        "extra": [("식품안전나라", "https://www.foodsafetykorea.go.kr")],
        "caution": "수입국이 요구하는 서식이 따로 있는 경우가 많습니다. 바이어에게 서식을 먼저 받으세요.",
    },
    {
        "key": "cfs",
        "title": "자유판매증명서 (CFS)",
        "keywords": ("자유판매", "CFS", "free sale"),
        "agency": "식품의약품안전처 (화장품은 대한화장품협회도 발급)",
        "how": "국내에서 정상 유통되고 있음을 증명하는 서류입니다. 화장품은 "
               "대한화장품협회가, 식품·의약품은 식약처가 발급합니다.",
        "lead_time": "3~5 영업일",
        "url": "https://www.mfds.go.kr",
        "extra": [("대한화장품협회", "https://www.kcia.or.kr")],
        "caution": "영사확인(아포스티유)을 함께 요구하는 나라가 많습니다. 시간이 더 걸립니다.",
    },
    {
        "key": "coa",
        "title": "성분분석서 · 시험성적서 (COA)",
        "keywords": ("성분분석", "COA", "시험성적", "분석성적", "certificate of analysis"),
        "agency": "공인시험기관 (KTR · KTL · KCL 등)",
        "how": "시료를 보내고 수입국이 요구하는 항목으로 시험을 신청합니다. "
               "어떤 항목을 시험할지는 수입국 규제가 정합니다. 바이어에게 기준을 먼저 받으세요.",
        "lead_time": "품목에 따라 5~20 영업일",
        "url": "https://www.ktr.or.kr",
        "extra": [
            ("한국산업기술시험원 KTL", "https://www.ktl.re.kr"),
            ("한국건설생활환경시험연구원 KCL", "https://www.kcl.re.kr"),
        ],
        "caution": "제조사가 자체 발행한 COA를 안 받아 주는 나라가 있습니다. 공인기관 성적서인지 확인하세요.",
    },
    {
        "key": "msds",
        "title": "물질안전보건자료 (MSDS/SDS)",
        "keywords": ("MSDS", "SDS", "물질안전보건"),
        "agency": "제조사가 작성 · 안전보건공단에 제출",
        "how": "화학물질을 만든 곳이 작성합니다. 사 오는 원료면 공급사에 요청하세요. "
               "국내 유통용은 안전보건공단 제출 대상입니다.",
        "lead_time": "보유하고 있으면 바로",
        "url": "https://msds.kosha.or.kr",
        "extra": [],
        "caution": "위험물 신고서의 정식운송품명(PSN)은 MSDS 14번 항목에서 그대로 옮겨 적습니다.",
    },
    {
        "key": "dg",
        "title": "위험물 신고서 (Shipper's Declaration)",
        "keywords": ("위험물 신고", "shipper's declaration", "DGD", "위험물신고"),
        "agency": "수출자가 작성 · 선사/항공사가 접수",
        "how": "해상은 IMDG, 항공은 IATA 서식으로 씁니다. UN번호·급·포장등급·정식운송품명이 "
               "모두 맞아야 하며, 항공은 교육 이수자가 서명해야 접수됩니다.",
        "lead_time": "부킹과 함께",
        "url": "https://www.komdi.or.kr",
        "extra": [],
        "caution": "한 글자만 틀려도 반송됩니다. 포장 성적서(UN 표시)도 함께 요구합니다.",
    },
    {
        "key": "strategic",
        "title": "전략물자 판정서 · 수출허가",
        "keywords": ("전략물자", "수출허가", "yestrade"),
        "agency": "전략물자관리원 · 산업통상자원부",
        "how": "YesTrade에서 자가판정을 먼저 하고, 해당되면 허가를 신청합니다. "
               "해당 안 되어도 판정서를 받아 두면 통관에서 묻지 않습니다.",
        "lead_time": "판정 즉시~5일 · 허가 15일 이상",
        "url": "https://www.yestrade.go.kr",
        "extra": [],
        "caution": "허가 없이 보내면 형사처벌 대상입니다. 전자·기계·화학은 꼭 판정하세요.",
    },
    {
        "key": "quarantine",
        "title": "검역증명서 (식물·동물·수산물)",
        "keywords": ("검역증", "식물검역", "동물검역", "수산물", "phytosanitary"),
        "agency": "농림축산검역본부 (식물·동물) · 국립수산물품질관리원 (수산물)",
        "how": "선적 전에 검역 신청을 하고 현장 검사를 받습니다. 수입국이 요구하는 "
               "검역 조건을 미리 확인해야 재검사를 피합니다.",
        "lead_time": "신청 후 1~3 영업일",
        "url": "https://www.qia.go.kr",
        "extra": [("국립수산물품질관리원", "https://www.nfqs.go.kr")],
        "caution": "목재 포장재(팔레트·나무상자)를 쓰면 IPPC 소독 마크가 따로 필요합니다.",
    },
    {
        "key": "customs_requirement",
        "title": "세관장확인 요건승인",
        "keywords": ("세관장확인", "요건승인", "요건확인"),
        "agency": "품목별 요건확인기관 (식약처·환경부·산업부 등)",
        "how": "관세법 제226조 대상 품목은 수출신고 전에 해당 기관의 승인을 받아야 합니다. "
               "어느 기관인지는 HS부호로 정해집니다.",
        "lead_time": "기관마다 다름",
        "url": "https://unipass.customs.go.kr",
        "extra": [("관세청 세관장확인대상 조회", "https://www.data.go.kr/data/15101589/openapi.do")],
        "caution": "요건승인이 없으면 수출신고가 수리되지 않습니다.",
    },
    {
        "key": "ce",
        "title": "CE 마킹 (EU)",
        "keywords": ("CE 마킹", "CE 인증", "CE마크"),
        "agency": "EU 인증기관(Notified Body) · 품목에 따라 자가선언",
        "how": "해당 지침을 찾아 적합성 평가를 받고 적합성선언서(DoC)를 만듭니다. "
               "위험도가 낮은 품목은 자가선언이 가능합니다.",
        "lead_time": "품목에 따라 수 주~수 개월",
        "url": "https://ec.europa.eu/growth/tools-databases/nando/",
        "extra": [],
        "caution": "EU 역내 책임 경제운영자(대리인)가 없으면 판매할 수 없습니다. DoC와 기술문서는 10년 보관합니다.",
    },
    {
        "key": "fda",
        "title": "FDA 등록 · 신고 (미국)",
        "keywords": ("FDA",),
        "agency": "미국 식품의약국 (FDA)",
        "how": "식품·화장품·의료기기는 시설 등록과 품목 신고가 필요합니다. "
               "식품은 선적마다 Prior Notice를 따로 보내야 합니다.",
        "lead_time": "등록은 즉시~수 일 · Prior Notice는 도착 전",
        "url": "https://www.fda.gov/industry",
        "extra": [],
        "caution": "미국 내 대리인(U.S. Agent)이 있어야 등록됩니다.",
    },
    {
        "key": "fcc",
        "title": "FCC 인증 (미국 · 무선/전자)",
        "keywords": ("FCC",),
        "agency": "미국 연방통신위원회 (FCC) 인정 시험소",
        "how": "무선기기는 Certification, 일반 전자기기는 SDoC입니다. "
               "FCC 인정 시험소에서 시험한 뒤 등록합니다.",
        "lead_time": "2~8 주",
        "url": "https://www.fcc.gov/oet/ea",
        "extra": [],
        "caution": "FCC Covered List에 오른 부품이 들어가면 수입 자체가 막힙니다.",
    },
]


def find(name: str) -> dict | None:
    """서류 이름으로 발급 안내를 찾습니다. 없으면 None (지어내지 않습니다)."""

    text = str(name or "").strip()
    if not text:
        return None
    lowered = text.lower()
    for row in ISSUERS:
        if any(word.lower() in lowered for word in row["keywords"]):
            return row
    return None


def describe(row: dict) -> str:
    """한 서류의 발급 안내를 사람이 읽는 여러 줄로."""

    if not row:
        return ""
    lines = [f"**{row['title']}**",
             f"- 발급처: {row['agency']}",
             f"- 받는 법: {row['how']}"]
    if row.get("lead_time"):
        lines.append(f"- 걸리는 시간: {row['lead_time']}")
    if row.get("url"):
        lines.append(f"- 신청: {row['url']}")
    for label, url in row.get("extra", []):
        lines.append(f"- {label}: {url}")
    if row.get("caution"):
        lines.append(f"- ⚠ {row['caution']}")
    return "\n".join(lines)


def links_for(name: str) -> list[dict]:
    """그 서류를 받는 공식 창구. 화면의 링크 줄에 씁니다."""

    row = find(name)
    if not row:
        return []
    links = [{"label": row["agency"], "url": row["url"]}] if row.get("url") else []
    links += [{"label": label, "url": url} for label, url in row.get("extra", [])]
    return links


# --- 나라별 규제기관 --------------------------------------------------------------
#
# 위 ISSUERS는 **한국에서 받는** 서류입니다. 이건 **보내는 나라가** 요구하는 것을
# 어디에 물어야 하는지입니다. 둘은 다릅니다.
#
#   위생증명서  → 한국 식약처가 발급  (ISSUERS)
#   FDA 등록   → 미국 FDA에 직접 신고 (아래)
#
# "미국 FDA 인증이 필요합니다"까지만 말하면 사람은 또 검색해야 합니다. 검색하면
# 대행업체가 먼저 나옵니다. 공식 창구를 바로 짚어 줍니다.
#
# 여기 없는 나라는 비워 둡니다. 지어내지 않습니다.
COUNTRY_AGENCIES = {
    "US": [
        {"label": "FDA (식품·화장품·의약품·의료기기)", "url": "https://www.fda.gov",
         "note": "시설 등록과 품목 신고. 미국 내 대리인(U.S. Agent)이 있어야 합니다."},
        {"label": "FCC (무선·전자기기)", "url": "https://www.fcc.gov/oet/ea",
         "note": "무선은 Certification, 일반 전자기기는 SDoC입니다."},
        {"label": "CPSC (어린이제품·소비재 안전)", "url": "https://www.cpsc.gov",
         "note": "어린이제품은 CPC(적합성증명서)를 함께 보내야 합니다."},
        {"label": "CBP (통관)", "url": "https://www.cbp.gov",
         "note": "원산지 표시 규정이 엄격합니다. 물품 자체에 항구적으로 표시합니다."},
    ],
    "EU": [
        {"label": "NANDO · EU 인증기관(Notified Body) 찾기",
         "url": "https://ec.europa.eu/growth/tools-databases/nando/",
         "note": "CE 마킹에서 제3자 인증이 필요한 품목의 기관을 여기서 찾습니다."},
        {"label": "ECHA (화학물질 REACH)", "url": "https://echa.europa.eu",
         "note": "연 1톤 이상이면 등록 대상입니다. EU 역내 대리인이 필요합니다."},
        {"label": "Access2Markets · 품목별 요건·관세",
         "url": "https://trade.ec.europa.eu/access-to-markets/en/home",
         "note": "HS부호와 나라를 넣으면 그 품목에 걸리는 EU 요건이 모두 나옵니다."},
    ],
    "CN": [
        {"label": "SAMR · 국가시장감독관리총국", "url": "https://www.samr.gov.cn",
         "note": "CCC 강제인증을 관장합니다."},
        {"label": "중국 해관총서 (통관·검역)", "url": "http://www.customs.gov.cn",
         "note": "식품 수출자는 해관총서 등록(GACC)이 되어 있어야 합니다."},
    ],
    "JP": [
        {"label": "경제산업성 (전기용품 PSE)", "url": "https://www.meti.go.jp",
         "note": "특정전기용품은 국가등록 검사기관의 적합성검사가 필요합니다."},
        {"label": "후생노동성 (식품·의약품)", "url": "https://www.mhlw.go.jp",
         "note": "식품은 수입신고(식품등수입신고서)가 따로 있습니다."},
    ],
    "VN": [
        {"label": "베트남 과학기술부 (품질·CR 마크)", "url": "https://www.most.gov.vn",
         "note": "품목별 적합성인증(CR) 대상이 넓습니다."},
    ],
    "IN": [
        {"label": "BIS · 인도표준국", "url": "https://www.bis.gov.in",
         "note": "BIS 강제인증 품목이 계속 늘고 있습니다. 외국제조사 등록(FMCS)이 오래 걸립니다."},
    ],
    "ID": [
        {"label": "BPOM (식품·화장품·의약품)", "url": "https://www.pom.go.id",
         "note": "화장품·식품은 사전 등록(NIE)이 필요합니다."},
        {"label": "할랄청 BPJPH", "url": "https://bpjph.halal.go.id",
         "note": "식음료는 할랄 인증이 단계적으로 의무화되었습니다."},
    ],
    "TR": [
        {"label": "TSE · 튀르키예표준협회", "url": "https://www.tse.org.tr",
         "note": "CE와 별도로 TSE 인증을 요구하는 품목이 있습니다."},
        {"label": "TAREKS (수입 적합성 검사)", "url": "https://www.ticaret.gov.tr",
         "note": "무역부 전자시스템으로 수입 전 검사를 신청합니다."},
    ],
    "SA": [
        {"label": "SASO · 사우디표준청", "url": "https://www.saso.gov.sa",
         "note": "SABER 시스템에서 적합인증서(CoC)를 받아야 통관됩니다."},
    ],
    "AE": [
        {"label": "ESMA · UAE 표준측량청", "url": "https://www.moiat.gov.ae",
         "note": "ECAS 적합성 인증 대상 품목이 있습니다."},
    ],
    "GB": [
        {"label": "UKCA 적합성 표시 안내", "url": "https://www.gov.uk/guidance/using-the-ukca-marking",
         "note": "CE가 아니라 UKCA입니다. 영국 내 책임자(UK Responsible Person)가 필요합니다."},
    ],
    "AU": [
        {"label": "ACMA (무선·통신)", "url": "https://www.acma.gov.au",
         "note": "RCM 표시 대상입니다."},
        {"label": "호주 농업부 (검역)", "url": "https://www.agriculture.gov.au",
         "note": "검역이 세계에서 가장 엄격한 축에 듭니다. 목재 포장재를 특히 봅니다."},
    ],
    "CA": [
        {"label": "Health Canada (식품·화장품·의약품)", "url": "https://www.canada.ca/en/health-canada.html",
         "note": "화장품은 판매 전 신고(Cosmetic Notification)가 필요합니다."},
    ],
    "MX": [
        {"label": "NOM · 멕시코 공식규격 (경제부)", "url": "https://www.gob.mx/se",
         "note": "NOM 인증은 멕시코 내 인증기관에서만 받습니다. 수입자 명의가 필요합니다."},
    ],
    "BR": [
        {"label": "INMETRO (제품 인증)", "url": "https://www.gov.br/inmetro",
         "note": "강제인증 품목이 많고 현지 시험을 요구합니다."},
        {"label": "ANVISA (식품·화장품·의약품)", "url": "https://www.gov.br/anvisa",
         "note": "등록 없이는 통관되지 않습니다."},
    ],
}

# EU 회원국은 나라마다 따로 두지 않고 EU 묶음을 씁니다.
# (CE·REACH는 회원국이 아니라 EU가 정합니다)


def agencies_for(country_code: str) -> list[dict]:
    """그 나라 규제기관. 모르는 나라면 빈 목록입니다. 지어내지 않습니다."""

    code = str(country_code or "").strip().upper()
    if not code:
        return []
    if code in COUNTRY_AGENCIES:
        return COUNTRY_AGENCIES[code]
    from app.processors import country_export_guide
    return COUNTRY_AGENCIES["EU"] if code in country_export_guide._eu_members() else []
