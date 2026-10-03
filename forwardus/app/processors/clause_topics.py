"""계약 조항 **주제** 분류 — 규칙이 놓친 문장을 '확인 필요'로 띄웁니다.

왜 있나 (2026-10-03)
  조항 판정(contract_clauses.py)은 낱말 규칙이라 **처음 보는 표현**을 놓칩니다.
  공개 계약 데이터(CUAD·LEDGAR·SEC EDGAR 공급계약)로 만든 주제 분류기가
  규칙이 손대지 못한 문장을 골라 "이 문장이 준거법 조항일 수 있습니다"라고
  알립니다.

지키는 것
  - **주제만** 말합니다. 유리·불리(독소 여부)는 규칙이 정합니다. 배심재판
    포기는 주제가 '배심'이어도 우리에게 유리합니다.
  - **판정을 바꾸지 않습니다.** 빠진 필수조항은 빠진 채로 두고 "이 문장일
    수 있습니다"를 덧붙입니다. 정해진 판정이 분류기 때문에 흔들리면 안 됩니다.
  - 확신 문턱은 학습에 안 쓴 데이터에서 **정밀도 90%** 에 맞췄습니다
    (data/build_clause_topics.py). 문턱이 없는 주제는 쓰지 않습니다.
  - 모델 파일이 없으면 조용히 빈 답을 냅니다. 바깥 호출·새 패키지가 없습니다.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "clause_topics.json"
MAX_CANDIDATES = 8
MAX_CHUNKS = 500
# 모든 주제에 공통인 최저선. (2026-10-03)
# 문턱은 시험 데이터(미국 기업 계약의 긴 문단)에서 정밀도 90% 로 맞췄는데, 짧은
# 무역 문장에서는 헐거웠습니다 — 차가 1.0 아래인 후보는 대개 틀렸습니다("sole
# representative" 를 '검사'로). 규칙에 없는 표현으로 맞게 띄운 것은 모두 1.44 이상.
MIN_MARGIN = 1.4

_WORD = re.compile(r"[a-z]{2,}")
_HANGUL = re.compile(r"[가-힣]+")
_HANGUL_CHAR = re.compile(r"[가-힣]")
_LATIN_CHAR = re.compile(r"[A-Za-z]")
STOP = set("the of and to in or by any such for be shall this as with on its is are at an "
           "that which from all other than under will may has have been not no it".split())


def tokens(text: str) -> set[str]:
    """영문 낱말·두 낱말 + 한글 두 글자. 숫자는 버립니다(금액·날짜는 주제가 아닙니다).

    **학습(data/build_clause_topics.py)도 이 함수를 씁니다.** 둘이 다르게 쪼개면
    가중치가 맞지 않습니다.
    """

    low = str(text).lower()
    words = [w for w in _WORD.findall(low) if w not in STOP]
    out = set(words)
    out.update(f"{a}_{b}" for a, b in zip(words, words[1:]))
    for run in _HANGUL.findall(low):
        out.update(run[i:i + 2] for i in range(len(run) - 1))
    return out


@lru_cache(maxsize=1)
def model() -> dict:
    try:
        return json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def score(text: str) -> list[tuple[float, str]]:
    """주제(와 '기타')마다 로그 점수. 높은 순.

    나이브 베이즈입니다 — 조항에 든 낱말마다 주제별 가중치를 더합니다. '기타'
    (주제와 무관한 조항)도 함께 겨룹니다. 가중치는 정수(×100)로 저장해 둡니다.
    """

    nb = model()
    table = nb.get("table") or {}
    toks = [t for t in tokens(text) if t in table]
    if not toks:
        return []
    # 로지스틱 회귀는 낱말 수로 나눠 학습했습니다(긴 조항이 점수를 독차지하지 않게).
    # 학습(build_clause_topics.score)과 **같은 계산**이어야 문턱이 맞습니다.
    scale = 1.0 / math.sqrt(len(toks)) if nb.get("norm") == "sqrt" else 1.0
    # 정수 그대로 더하고 마지막에 한 번만 바꿉니다 (32만 자 계약서가 4.7초 걸렸습니다)
    acc = [0] * len(nb["prior"])
    for t in toks:
        acc = [a + v for a, v in zip(acc, table[t])]
    sums = [(p + a * scale) / 100 for p, a in zip(nb["prior"], acc)]
    return sorted(zip(sums, nb["classes"]), reverse=True)


def classify(text: str) -> dict | None:
    """'기타'를 이기고, 2위와의 차가 그 주제의 문턱을 넘으면 그 주제. 아니면 None."""

    ranked = score(text)
    if len(ranked) < 2:
        return None
    (top, topic), (second, _) = ranked[0], ranked[1]
    if topic == "other":
        return None
    info = model()["topics"].get(topic) or {}
    threshold = info.get("threshold")
    margin = top - second
    if threshold is None or margin < max(threshold, MIN_MARGIN):
        return None
    # 정밀도는 **묶음 단위**로 맞췄습니다(준거법·관할·중재를 한 문단에 쓰는 일이
    # 흔해서). 그래서 이름도 묶음을 앞세웁니다 — "분쟁 해결: 관할 법원".
    family = info.get("family_title") or ""
    title = f"{family}: {info['title']}" if family else info["title"]
    return {"topic": topic, "title": title, "keys": list(info["keys"]),
            "score": round(margin, 2), "threshold": threshold}


# ── 조항 제목으로 알아보기 ─────────────────────────────────────────────────
#
# **국문과 재현율을 위해서입니다.** (2026-10-03)
#
# 분류기는 영문 자료로 배워 국문을 못 보고, 오탐을 막으려 문턱을 높여 영문도
# 절반쯤만 띄웁니다. 그런데 계약서는 거의 언제나 조항에 **제목**을 답니다 —
# "제12조(준거법)", "Article 12 Governing Law.", "12. FORCE MAJEURE:". 제목이
# 주제를 말해 주면 학습 자료가 없어도 정확합니다. 분류기가 못 보는 국문과
# 확신이 모자란 영문을 이것으로 메웁니다.
#
# 제목 **전체**가 사전의 꼴과 맞아야 합니다(fullmatch). "Article 12 The Buyer
# shall …" 의 "The Buyer shall" 은 어떤 주제와도 맞지 않아 지나갑니다.
#
# (주제, 이름, 우리 조항, 국문 제목, 영문 제목)
HEADINGS = [
    ("governing_law", "준거법", ("governing_law", "cisg_silent"),
     r"준거\s*법(?:률)?|적용\s*법(?:률)?|준거법\s*및\s*관할", r"governing\s+laws?|applicable\s+laws?|choice\s+of\s+law"
     r"|governing\s+law\s+and\s+jurisdiction"),
    ("jurisdiction", "관할 법원", ("foreign_forum",),
     r"(?:재판\s*)?관할(?:\s*법원)?|합의\s*관할", r"jurisdictions?|venue|forum|submission\s+to\s+jurisdiction"),
    ("disputes", "분쟁 해결·중재", ("arbitration", "foreign_forum", "china_domestic_arb"),
     r"중재|분쟁(?:의)?\s*해결|분쟁\s*처리|분쟁", r"arbitration|dispute\s+resolution|settlement\s+of\s+disputes|disputes"),
    ("confidential", "비밀유지", ("confidential", "one_way_nda"),
     r"(?:비밀|기밀)\s*(?:유지|준수|보호)?(?:\s*의무)?", r"confidentiality|non[- ]?disclosure|confidential\s+information"),
    ("amendment", "계약 변경·통지", ("amendment",),
     # '변경' 하나로 보면 "규격 변경"(사양 변경 — 다른 이야기)까지 계약 변경이 됩니다.
     r"계약(?:의)?\s*(?:변경|수정)|^(?:변경|수정)$|통지", r"amendments?|modifications?|variations?|notices?"),
    ("indemnity", "손해배상·면책", ("unlimited_damages", "own_negligence_indemnity", "eu_gdpr_indemnity",
                                   "us_class_action_pl"),
     r"손해\s*배상(?:\s*책임)?|배상(?:\s*책임)?|면책", r"indemnit(?:y|ies|ification)|damages|compensation"),
    ("liability_cap", "책임 한도", ("liability_cap", "unlimited_damages"),
     r"책임(?:의)?\s*(?:제한|한도)|손해\s*배상(?:의)?\s*(?:범위|한도|제한)", r"limitations?\s+(?:of|on)\s+liability"),
    ("liquidated", "지체상금·위약금", ("uncapped_ld",),
     r"지체\s*상금|지연\s*배상(?:금)?|위약(?:금|벌)", r"liquidated\s+damages|penalt(?:y|ies)|delay\s+damages"),
    ("termination", "해지", ("termination_at_will", "exit_buyback"),
     r"(?:계약(?:의)?\s*)?(?:해지|해제|종료)(?:\s*및\s*(?:해제|해지))?", r"termination|cancell?ation"),
    ("renewal", "계약 기간·갱신", ("evergreen",),
     r"계약\s*기간|유효\s*기간|존속\s*기간|갱신|자동\s*연장", r"term(?:\s+of\s+(?:the\s+)?(?:agreement|contract))?"
     r"|duration|renewal|term\s+and\s+renewal"),
    ("warranty", "품질 보증", ("claim_period", "open_warranty"),
     r"(?:품질\s*)?보증|하자\s*(?:담보|보수)?|품질", r"warrant(?:y|ies)|quality\s+guarantee|defects?|quality"),
    ("assignment", "양도", ("assignment_one_way",),
     r"양도|계약상\s*지위(?:의)?\s*(?:이전|승계)", r"assignments?|transfer\s+of\s+rights"),
    ("ip", "지식재산·금형", ("ip", "ip_assignment", "buyer_design_ip", "cn_tech_transfer", "tooling_free",
                            "cn_trademark_buyer"),
     r"(?:지식|지적|산업)\s*재산권?|금형|도면|상표(?:권)?", r"intellectual\s+property(?:\s+rights)?|tooling|moulds?|molds?"
     r"|trademarks?"),
    ("audit", "감사·장부", ("audit_rights",), r"감사|장부(?:\s*열람)?|실사", r"audits?|books\s+and\s+records|records"),
    ("mfn", "최혜 가격", ("mfn_price",), r"최혜(?:\s*(?:대우|가격|조건))?", r"most\s+favou?red\s+(?:nation|customer)"
     r"(?:\s+(?:pricing|treatment))?"),
    ("non_compete", "경업 금지", ("non_compete_wide",), r"경업\s*금지|경쟁\s*(?:제한|금지)",
     r"non[- ]?compet(?:e|ition)|restrictive\s+covenants?"),
    ("exclusivity", "독점·대리점", ("exclusive_no_moq", "agency_protection", "gulf_agent_lock", "agency_law_eu"),
     r"독점(?:\s*(?:판매)?권)?|총판|대리점", r"exclusivity|exclusive\s+(?:rights|distribution|distributor)"),
    ("min_order", "최소 주문", ("min_order",), r"최소\s*(?:주문|구매|발주)(?:\s*(?:수)?량)?",
     r"minimum\s+(?:order|purchase)(?:\s+(?:quantity|commitment|requirements?))?"),
    ("price", "가격", ("price_adjust", "retro_price_deduction"), r"가격(?:의)?(?:\s*조정)?|단가", r"prices?|pricing"
     r"|price\s+adjustments?"),
    ("sanctions", "제재·수출 규제", ("ru_sanctions_warranty", "export_licence", "reexport_control"),
     r"수출\s*(?:통제|규제|허가|승인)|제재", r"export\s+(?:control|controls|compliance|licen[cs]es?)|sanctions"),
    ("taxes", "세금·관세", ("tariff_absorption", "ddp_no_ior"), r"세금|조세|관세|제세\s*공과금?",
     r"taxes|duties|customs\s+duties|taxes\s+and\s+duties"),
    ("payment", "결제", ("payment", "lc_deadline", "docs_before_payment", "payment_retention", "payment_on_resale",
                        "suspend_delivery"),
     r"대금(?:의)?(?:\s*지급)?|결제(?:\s*조건)?|지급(?:\s*조건)?", r"payments?|terms\s+of\s+payment|payment\s+terms"),
    ("insurance", "보험", ("insurance",), r"(?:적하\s*)?보험|부보", r"insurance"),
    ("force_majeure", "불가항력", ("force_majeure",), r"불가항력", r"force\s+majeure|excusable\s+delays?"),
    ("title", "소유권·위험 이전", ("title",), r"소유권(?:\s*(?:및|과)\s*위험(?:\s*부담)?)?|위험\s*(?:부담|이전)"
     r"|소유권(?:의)?\s*(?:이전|유보)", r"title(?:\s+and\s+risk(?:\s+of\s+loss)?)?|risk\s+of\s+loss"
     r"|passing\s+of\s+(?:property|title)|retention\s+of\s+title"),
    ("inspection", "검사·인수", ("inspection", "inspection_buyer_sole", "full_inspection"),
     r"검사|검수|검품|인수\s*검사", r"inspections?|acceptance|testing|inspection\s+and\s+acceptance"),
    ("delivery", "인도·선적", ("shipment", "incoterms"), r"인도(?:\s*조건)?|선적(?:\s*조건)?|납품|납기|운송",
     r"deliver(?:y|ies)|shipments?|shipping|delivery\s+terms"),
    ("packing", "포장·화인", ("packing",), r"포장(?:\s*및\s*화인)?|화인", r"packing|packaging|marking|shipping\s+marks?"
     r"|packing\s+and\s+marking"),
    ("late_interest", "연체 이자", ("late_interest",), r"(?:지연|연체)\s*이자",
     r"late\s+payments?|interest\s+on\s+late\s+payments?"),
    ("set_off", "상계", ("no_set_off", "buyer_set_off"), r"상계(?:\s*금지)?", r"set[- ]?off|no\s+set[- ]?off"),
    ("goods", "물품 명세", ("goods",), r"물품|제품|품목|목적물|계약\s*물품",
     r"goods|products|description\s+of\s+goods|commodity"),
    ("quantity", "수량", ("quantity_tol",), r"수량(?:\s*과부족)?", r"quantity|quantities"),
]
_KO_HEAD = re.compile(r"^제\s*\d+\s*조\s*[(\[【<〔]?\s*(?P<h>[가-힣·\s]{1,20}?)\s*[)\]】>〕]")
_EN_HEAD = re.compile(r"^(?:(?:article|section|clause)\s+)?\d{1,2}(?:\.\d{1,2})?\.?\s*[-–:]?\s*\(?"
                      r"(?P<h>[A-Za-z][A-Za-z ,&/\-]{2,45}?)\)?\s*(?:[.:]\s|\s[-–]\s|$)", re.I)


# 국문 제목은 '들어 있으면' 보므로, 구체적인 것부터 맞춰 봅니다.
_KO_FIRST = ("set_off", "late_interest", "mfn", "min_order", "liability_cap", "liquidated", "title",
             "inspection", "packing", "force_majeure", "insurance", "governing_law", "jurisdiction",
             "disputes", "confidential", "non_compete", "exclusivity", "sanctions", "taxes", "ip", "audit",
             "assignment", "termination", "renewal", "indemnity", "payment", "delivery", "price",
             "warranty", "amendment", "quantity", "goods")
_KO_ORDER = sorted(HEADINGS, key=lambda row: _KO_FIRST.index(row[0]))


def heading_topic(chunk: str) -> dict | None:
    """조항 머리의 제목이 사전의 꼴과 **통째로** 맞으면 그 주제."""

    head = chunk.strip()
    m = _KO_HEAD.match(head)
    lang = "ko"
    if not m:
        m, lang = _EN_HEAD.match(head), "en"
    if not m:
        return None
    title = re.sub(r"\s+", " ", m.group("h")).strip(" ,-")
    # 국문 제목은 짧고 꾸밈말이 붙습니다 — "권리의 양도", "손해배상의 제한",
    # "선적 전 검사". 그래서 **들어 있으면** 봅니다. 대신 구체적인 주제부터
    # 맞춰 봅니다(_KO_ORDER) — "손해배상의 제한" 은 '배상'이 아니라 '책임 한도'.
    # 영문 제목은 통째로 맞아야 합니다. (2026-10-03)
    rows = _KO_ORDER if lang == "ko" else HEADINGS
    for topic, name, keys, ko, en in rows:
        hit = re.search(ko, title) if lang == "ko" else re.fullmatch(en, title, re.I)
        if hit:
            return {"topic": topic, "title": f"{name} (조항 제목 “{title}”)", "keys": list(keys),
                    "score": 99.0, "threshold": 0.0, "via": "heading"}
    return None


# 조항 단위로 자릅니다. 학습 데이터가 조항(문단) 단위라 문장 하나보다 낫습니다.
_ARTICLE = re.compile(r"(?=(?:\bArticle\s+\d+|\bSection\s+\d+|\bClause\s+\d+|제\s*\d+\s*조"
                      r"|(?<![\d.])\d{1,2}\.\s+[A-Z]))")


def chunks(text: str) -> list[str]:
    body = re.sub(r"\s+", " ", str(text or ""))
    parts = [p.strip() for p in _ARTICLE.split(body) if p.strip()]
    out = []
    for part in parts:
        if len(part) <= 700:
            out.append(part)
            continue
        # 긴 조항은 문장 몇 개씩 묶습니다
        sentences = re.split(r"(?<=[.;])\s+", part)
        buf = ""
        for s in sentences:
            if len(buf) + len(s) > 600 and buf:
                out.append(buf.strip())
                buf = ""
            buf += " " + s
        if buf.strip():
            out.append(buf.strip())
    return [c for c in out if len(c) >= 40]


# ── 수출자 입장 판정 ───────────────────────────────────────────────────────
#
# **우리는 수출자, 곧 매도인입니다.** (2026-10-03)
#
# '직접 확인'으로 띄우는 조항은 주제만 알려 줘서, "서울중앙지방법원 관할"처럼
# 우리에게 **유리한** 조항도 똑같이 확인하라고 했습니다. 문장에서 **누가 의무를
# 지고 누가 권리를 갖는지**를 보고 수출자 입장을 덧붙입니다.
#
# 원칙: 틀리게 '유리'라고 하면 사용자가 위험한 조항을 넘깁니다. 그래서 근거가
# 없으면 '확인 필요'로 둡니다 — '유리'는 문장이 분명히 말할 때만.

_SELLER = r"(?:the\s+)?(?:seller|supplier|manufacturer|exporter|vendor)s?"
_BUYER = r"(?:the\s+)?(?:buyer|purchaser|customer|importer|distributor)s?"
_MUTUAL_EN = re.compile(r"\b(?:neither\s+party|each\s+party|either\s+party|both\s+parties|the\s+parties"
                        r"|each\s+of\s+the\s+parties|neither\s+of\s+the\s+parties|mutual(?:ly)?)\b", re.I)
_MUTUAL_KO = re.compile(r"어느\s*당사자|각\s*당사자|양\s*당사자|쌍방|당사자\s*모두|상호")
_SELLER_KO = r"(?:매도인|공급자|수출자|판매자|제조자)"
_BUYER_KO = r"(?:매수인|바이어|구매자|수입자|구입자)"
# 우리 책임을 덜거나 없애는 말 — 주어가 우리면 유리, 상대면 불리
_RELIEF_EN = (r"not\s+be\s+(?:liable|responsible)|have\s+no\s+(?:liability|obligation|responsibility)"
              r"|be\s+excused|not\s+be\s+(?:required|obliged)")
# "면책한다"는 넣지 않습니다 — "매수인은 매도인을 면책한다"는 매수인이 매도인을
# **지켜 주는 의무**입니다. 주어의 책임이 줄어드는 것은 "면책된다"입니다. (2026-10-03)
_RELIEF_KO = r"책임을?\s*지지\s*아니|책임이\s*없|면책된다|의무가\s*없"
_RIGHT_EN = r"(?:may|can|shall\s+(?:be\s+entitled|have\s+the\s+right)|is\s+entitled|has\s+the\s+right)"
_DUTY_EN = r"(?:shall|must|will|agrees?\s+to|undertakes?)"
_SUBJECT_EN = re.compile(rf"\b(?P<who>{_SELLER}|{_BUYER})\b(?:'s)?\s+(?:\w+\s+){{0,2}}?"
                         rf"(?P<modal>{_RIGHT_EN}|{_DUTY_EN})\b(?P<rest>[^.;]{{0,80}})", re.I)
_SUBJECT_KO = re.compile(rf"(?P<who>{_SELLER_KO}|{_BUYER_KO})(?:은|는|이|가)(?P<rest>[^.]{{0,80}})")

_LABEL = {"favorable": "🟢 우리에게 유리", "unfavorable": "🔴 우리에게 불리할 수 있음",
          "mutual": "⚪ 양쪽에 같게 걸림", "unclear": "확인 필요"}


def _verdict(stance: str, why: str) -> dict:
    return {"stance": stance, "label": _LABEL[stance], "why": why}


def stance(text: str, topic: str = "") -> dict:
    """수출자(매도인) 입장에서 이 조항이 어떤가. Party A/B 는 미리 바꿔 읽어 넘깁니다."""

    from app.processors.contract_clauses import KOREA

    s = re.sub(r"\s+", " ", str(text or ""))
    low = s.lower()
    # 1) 주제가 방향을 정하는 것
    if topic in ("jurisdiction", "disputes", "governing_law"):
        courts = re.search(r"courts?\s+of|법원|중재|arbitration|laws?\s+of|법령|준거", s, re.I)
        # 한국 지명이 법원·법률·중재 **바로 옆**에 있어야 합니다. 문장 어디에 Korea 가
        # 있기만 해도 유리로 보면 "Goods made in Korea … laws of New York" 를 유리라고
        # 합니다 — 불리를 유리로 보는, 가장 나쁜 실수입니다. (2026-10-03)
        home = re.search(rf"(?:courts?\s+(?:of|in|sitting\s+in)|laws?\s+of|arbitration\s+(?:in|at)"
                         rf"|seat(?:ed)?\s+(?:of\s+arbitration\s+)?(?:shall\s+be\s+)?(?:in|at)?)"
                         rf"\s+(?:the\s+)?(?:republic\s+of\s+)?{KOREA}|\bKCAB\b|대한상사중재원"
                         rf"|{KOREA}[^.]{{0,12}}(?:법원|중재|법령|법률|법에)", s, re.I)
        if courts and home:
            return _verdict("favorable", "한국 법원·중재·법률입니다 — 우리 쪽에서 다툽니다.")
        if courts:
            return _verdict("unfavorable", "한국이 아닌 곳의 법원·법률로 보입니다 — 멀리서, 남의 법으로 다툽니다.")
    if topic == "jury_waiver" and re.search(r"waive|포기", low):
        return _verdict("favorable", "배심재판을 포기합니다 — 미국 배심의 큰 배상 판결을 피합니다.")
    # 2) 쌍방
    if _MUTUAL_EN.search(s) or _MUTUAL_KO.search(s):
        if topic in ("liability_cap", "indemnity") and re.search(
                r"not\s+be\s+liable|neither\s+party\s+shall\s+be\s+liable|exclud|shall\s+not\s+exceed"
                r"|limited\s+to|책임을?\s*지지\s*아니|한도", low):
            return _verdict("favorable", "양쪽 모두의 책임을 줄입니다 — 보통 배상 청구를 받는 쪽은 "
                                         "매도인이라 우리에게 더 이롭습니다.")
        return _verdict("mutual", "양쪽에 똑같이 걸리는 조항입니다.")
    # 3) 주어 + 의무·권리
    m = _SUBJECT_EN.search(s)
    if m:
        ours = re.fullmatch(_SELLER, m.group("who"), re.I) is not None
        rest = m.group("rest")
        right = re.fullmatch(_RIGHT_EN, m.group("modal"), re.I) is not None
        relief = re.search(_RELIEF_EN, m.group("modal") + rest, re.I) is not None
        # "The Seller's **liability** shall not exceed …" — 'shall' 만 보면 우리 의무로
        # 읽힙니다. 책임 한도는 우리 책임을 **덜어 줍니다**.
        if re.search(r"liabilit", m.group(0), re.I) and re.search(
                r"not\s+exceed|(?:be\s+)?limited\s+to|be\s+capped", rest, re.I):
            relief = True
        # "may **not**", "shall be entitled to **no** …" — 권리가 아니라 금지입니다.
        # 'may' 만 보고 우리 권리(유리)라 하면 불리를 유리로 보는 실수입니다.
        # "may **only** claim within 7 days, failing which all claims are waived" — 권리를
        # 주는 것이 아니라 **묶는** 것입니다. 공격에서 유리로 판정했습니다. (2026-10-03)
        if right and re.match(r"\s*(?:not\b|to\s+no\b|no\b|only\b)", rest, re.I):
            right = False
        who = "우리(매도인)" if ours else "상대(바이어)"
        # 우리가 권리를 **포기·상실**하는 말이 붙으면 불리합니다.
        if ours and re.search(r"waive|forfeit|deemed\s+(?:to\s+have\s+)?accepted|포기|상실", rest, re.I):
            return _verdict("unfavorable", "우리(매도인)의 권리를 포기·제한합니다.")
        if relief:
            return _verdict("favorable" if ours else "unfavorable", f"{who}의 책임을 덜어 줍니다.")
        if right:
            return _verdict("favorable" if ours else "unfavorable", f"{who}에게 권리를 줍니다.")
        return _verdict("unfavorable" if ours else "favorable", f"{who}에게 의무·제한을 지웁니다.")
    m = _SUBJECT_KO.search(s)
    if m:
        ours = re.fullmatch(_SELLER_KO, m.group("who")) is not None
        rest = m.group("rest")
        who = "우리(매도인)" if ours else "상대(바이어)"
        if re.search(_RELIEF_KO, rest):
            return _verdict("favorable" if ours else "unfavorable", f"{who}의 책임을 덜어 줍니다.")
        if re.search(r"할\s*수\s*있", rest):
            return _verdict("favorable" if ours else "unfavorable", f"{who}에게 권리를 줍니다.")
        # "해지할 수 없다", "하지 못한다" — 금지는 의무·제한입니다.
        if re.search(r"하여야|해야|한다|진다|부담|할\s*수\s*없|하지\s*못", rest):
            return _verdict("unfavorable" if ours else "favorable", f"{who}에게 의무·제한을 지웁니다.")
    # 4) 주어 없이 책임을 빼는 꼴 — "Punitive damages are expressly excluded"
    if topic in ("liability_cap", "indemnity") and re.search(
            r"(?:are|is|shall\s+be)\s+(?:expressly\s+)?excluded|shall\s+not\s+exceed|배제", low):
        return _verdict("favorable", "배상 범위를 줄입니다 — 보통 청구를 받는 쪽은 매도인입니다.")
    return _verdict("unclear", "누가 의무를 지는지 문장에서 가리지 못했습니다. 직접 확인하세요.")


def candidates(text: str, judged: dict, categories: dict) -> list[dict]:
    """규칙이 그 **주제를 하나도 판정하지 못한** 조항만 냅니다.

    judged      analyze()["clauses"] — 규칙이 본 조항
    categories  {key: "must"|"gain"|"toxic"}

    주제의 조항 가운데 하나라도 규칙이 봤으면(있음·부족·독소) 그 주제는 넘어
    갑니다 — 규칙이 이미 말한 것을 분류기가 되풀이하면 소음입니다.
    """

    from app.processors.contract_clauses import (
        _drop_page_furniture, _drop_table_of_contents, as_seller_with, our_side)

    # 목차를 먼저 지웁니다. 그대로 두면 "제12조(준거법) …… 5" 가 줄마다 후보가
    # 됩니다. 판정(contract_clauses.find_in)도 같은 것을 지우고 봅니다.
    body = _drop_page_furniture(_drop_table_of_contents(str(text or "")))
    # Party A/B 계약서 — 우리 쪽은 문서 머리에서 한 번 정하고, 조항마다 그것으로
    # 바꿔 읽어 입장을 봅니다. 보여 주는 문장은 원문 그대로입니다.
    side = our_side(body)
    best: dict[str, dict] = {}
    # 조항 수 상한 — 아주 긴 문서(부록·약관 묶음)에서 응답이 늘어지지 않게.
    for chunk in chunks(body)[:MAX_CHUNKS]:
        # 1) 조항 제목 — 국문도 봅니다. 제목이 주제를 말하면 그것이 가장 확실합니다.
        found = heading_topic(chunk)
        # 2) 분류기 — **국문 조항은 보지 않습니다.** 학습 자료가 거의 영문이라
        #    국문을 엉뚱한 주제로 붙였습니다.
        if not found and model() and len(_HANGUL_CHAR.findall(chunk)) <= len(_LATIN_CHAR.findall(chunk)):
            found = classify(chunk)
        if not found:
            continue
        keys = found["keys"]
        if any(k in judged for k in keys):
            continue
        kind = "must" if any(categories.get(k) == "must" for k in keys) else "check"
        item = {**found, "kind": kind,
                "sentence": chunk if len(chunk) <= 300 else chunk[:297] + "…",
                **stance(as_seller_with(side, chunk), found["topic"])}
        if found["topic"] not in best or item["score"] > best[found["topic"]]["score"]:
            best[found["topic"]] = item
    ranked = sorted(best.values(), key=lambda x: x["score"] - x["threshold"], reverse=True)
    return ranked[:MAX_CANDIDATES]
