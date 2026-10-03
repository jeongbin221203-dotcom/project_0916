"""수출계약서 조항표 — 있어야 할 것, 챙기면 이로운 것, 있으면 위험한 것.

왜 필요한가
  견적과 서류는 우리가 만들어 주는데, 정작 **돈을 떼이거나 물리는 자리**는
  계약서입니다. 서류가 아무리 맞아도 계약서에 "바이어가 언제든 해지할 수
  있다"가 들어 있으면 실어 놓고 물립니다. 그런데 그 문장은 서류 어디에도
  안 나오니, 우리 화면만 보고는 알 수가 없었습니다.

무엇을 하고 무엇을 안 하나
  - **합니다**: 이 건(인코텀즈·결제조건)에 필요한 조항을 짚어 주고, 올린
    계약서에서 빠진 필수조항과 들어 있는 독소조항을 찾아 주고, 붙여 쓸
    문안을 내 줍니다.
  - **안 합니다**: 법률 자문이 아닙니다. 계약서 검토는 변호사가 합니다.
    여기 적힌 문안은 **출발점**이지 완성본이 아닙니다.

세 갈래
  must   필수 — 빠지면 다툼이 났을 때 기댈 곳이 없습니다
  gain   이익 — 없어도 계약은 되지만, 있으면 우리가 덜 잃습니다
  toxic  독소 — 있으면 우리가 크게 물립니다. 지우거나 고쳐야 합니다

detect
  올린 계약서에서 그 조항이 보이는지 찾는 말입니다. 영문 계약서가 대부분이라
  영문을 먼저 보고 국문도 함께 봅니다. **보인다/안 보인다만** 말하고,
  "이 조항이 우리에게 유리하게 쓰여 있다"고는 말하지 않습니다.
"""

from __future__ import annotations

import re

CATEGORIES = {"must": "필수", "gain": "이익", "toxic": "독소"}
CATEGORY_NOTE = {
    "must": "빠지면 다툼이 났을 때 기댈 곳이 없습니다.",
    "gain": "없어도 계약은 되지만, 있으면 우리가 덜 잃습니다.",
    "toxic": "있으면 우리가 크게 물립니다. 지우거나 고쳐 달라고 하세요.",
}

CLAUSES: list[dict] = []

# 한국어 부정 가드. 찾은 말 **뒤** 40자 안에 부정말이 오면 그 조항이 아닙니다.
#
# "전량 반품을 요구할 수 **없다**" 는 우리를 보호하는 문장이고,
# "금형은 매수인에게 귀속하지 **아니한다**" 도 그렇습니다. 이것까지 독소로
# 짚으면 사용자가 멀쩡한 조항을 지웁니다. 오탐이 미탐보다 나쁩니다.
NO_NEG_KO = r"(?![^.]{0,40}(없|못하|아니하|아니한|금지))"

# 뜻풀이 문장. 의무를 정한 것이 아니라 **낱말의 뜻**을 적은 것입니다.
#
#   "Chargeback" means any deduction asserted by a customer of the Buyer.
# 이걸 독소조항으로 짚으면, 정의 조항을 지우라고 하게 됩니다. 독소조항 전부에
# 겁니다 — 뜻풀이가 의무인 경우는 없습니다. (2026-10-02)
DEFINITION = (r"\bmeans\b", r"\bshall mean\b", r"\bis defined as\b",
              r"(이|가)?\s*라\s*함은", r"(을|를)\s*말한다", r"(으)?로\s*정의한다")

# 최소 구매량. 독점 공급이라도 이것이 함께 있으면 한쪽만 묶이지 않습니다.
MINIMUM_PURCHASE = (r"minimum\s+(?:annual\s+)?(?:purchase|quantity|order|volume)",
                    r"\bMOQ\b", r"purchases? a minimum of",
                    r"최소\s*(?:구매|주문|발주)\s*(?:량|수량|물량)")

# **상계를 하지 못한다**는 꼴. buyer_set_off 는 예문("whether liquidated or not")에
# 부정말이 들어 있어 통짜 부정 가드를 못 씁니다. 그래서 상계 자체를 부정하는
# 말만 봅니다. "The Buyer shall not set off any claim" 은 우리에게 유리합니다.
SET_OFF_DENIED = (r"\b(?:shall|may|must|will|can)\s+not\s+(?:\w+\s+){0,2}?"
                  r"(?:set[- ]?off|deduct|withhold)",
                  r"\bcannot\s+(?:set[- ]?off|deduct|withhold)",
                  r"\bno\s+set[- ]?off\b",
                  # 국문 — "매수인은 어떠한 공제도 **하지 못한다**". 이익조항(상계
                  # 금지)과 짝으로 판정하면서 드러났습니다. (2026-10-02)
                  r"(?:상계|공제)[^.]{0,10}(?:할\s*수\s*없|하지\s*못|금지|불가)")

# **자동 연장되지 않는다**는 꼴. evergreen 도 예문("해지 통보가 없으면")에 부정말이
# 있어 통짜 가드를 못 씁니다. "shall not be automatically renewed" 는 유리합니다.
RENEWAL_DENIED = (r"\b(?:shall|will|may)\s+not\s+(?:be\s+)?(?:automatically\s+)?"
                  r"(?:renew|extend|roll)",
                  r"\bno\s+automatic\s+(?:renewal|extension)")

# 문장 안의 **한국 법원·중재기관**. 이것이 있으면 상대국 법원이 아닙니다.
# 뒤에 오는 지명만 보던 탓에 "서울중앙지방법원**을** 전속관할로 한다" 를
# 상대국 법원으로 짚었습니다. 낱말 순서로 놓친 것이 일곱 번째입니다.
KOREAN_FORUM = (r"(?:서울|부산|인천|대구|광주|대전|수원|울산|창원|대한민국|한국)"
                r"[^.]{0,12}(?:지방|중앙|고등)?\s*법원",
                r"대한상사중재원", r"\bKCAB\b",
                r"courts?\s+of\s+(?:the\s+Republic\s+of\s+)?(?:Korea|Seoul|Busan)")

# 부정말. 찾은 자리가 든 문장에 이 말이 있으면 그 자리는 세지 않습니다.
# 당사자가 **뒤바뀐** 꼴. 이런 문장은 우리에게 유리하므로 독소가 아닙니다.
#
# 기계적으로 당사자를 맞바꿔 보니 독소 39개 중 17개가 그대로 걸렸습니다.
# 그런데 바꾼 문장 대부분은 실제 계약서에 없을 꼴이라(공급자가 바이어를 감사하는
# 계약은 수출 거래에 없습니다), **실무에서 흔한 셋**만 거릅니다. (2026-10-02)
BUYER_SUPPLIES = (r"(?:provided|supplied|furnished|made available)\s+(?:to the seller\s+)?"
                  r"by the buyer",
                  r"(?:매수인|바이어)[^.]{0,20}(?:제공|공급|지급)")
INDEMNIFY_SELLER = (r"indemnif\w*[^.]{0,30}the seller",
                    r"hold\s+(?:the\s+)?seller\s+harmless",
                    r"buyer shall[^.]{0,30}indemnif",
                    r"(?:매수인|바이어)[^.]{0,30}(?:매도인|공급자)[^.]{0,20}면책")
# **주격 조사를 요구합니다.** "매수인은 **매도인에 대한** 채권으로 상계할 수
# 있다" 는 바이어가 상계하는 문장인데, '매도인'이 '상계' 가까이 있다는 이유만으로
# 걸렀습니다. 목적어를 주어로 읽은 것입니다. (2026-10-02)
SELLER_SETS_OFF = (r"seller\s+(?:may|shall|is entitled to)[^.]{0,30}set[- ]?off",
                   r"(?:매도인|공급자)(?:은|는|이|가)[^.]{0,30}상계")

NEGATION = (r"\b(?:shall|will|may|must|does|do|is|are|can|could|would)\s+not\b",
            r"\bnever\b",
            r"(없|못하|아니하|아니한|않는|않으)",
            # **낱말 가운데를 조심합니다.** 한국어에는 낱말 경계가 없어서
            # "대**금지**급" 의 '금지' 가 부정말로 읽혔습니다. 그래서 재판매
            # 조건부 결제 조항을 못 찾았습니다. (2026-10-02)
            r"금지(?!급)")

# 한국 법원·중재기관. 관할 조항 뒤에 이 말이 오면 "상대국 법원"이 아닙니다.
# 서울중앙지방법원 전속관할은 우리에게 **유리한** 조항입니다.
KOREA = r"(?:대한민국|한국|서울|부산|인천|대구|광주|수원|Korea|Seoul|Busan|KCAB)"

# 권리를 **포기·배제**하는 문구까지 보는 가드.
#
# 배심재판·징벌적 손해배상은 "포기한다"가 우리에게 **유리**합니다. 그런데
# 포기는 부정말이 아니라서 NO_NEG_KO 로는 안 걸러집니다. 실제로
# "배심재판을 받을 권리를 포기한다"를 독소로 짚었습니다. (2026-10-02)
#
# NO_NEG_KO 에 포기를 넣지 않는 이유: 다른 조항에서는 포기가 반대로 쓰입니다.
# "매도인은 항변권을 포기한다" 는 우리에게 불리합니다. 그래서 따로 둡니다.
NO_WAIVE_KO = r"(?![^.]{0,40}(없|못하|아니하|아니한|금지|포기|배제|제외))"

# **면책의 방향.** 보호받는 쪽이 Buyer 인 꼴만 봅니다.
#
# "The Buyer shall indemnify the Seller" 는 우리에게 **유리**합니다. 같은 낱말이
# 쓰이므로 방향을 안 보면 유리한 조항을 지우라고 하게 됩니다. 실제로 GDPR·집단소송
# 조항이 그랬습니다. (2026-10-02)
# 리콜 비용에 **한정·상한**이 붙은 꼴. 이런 문장은 좋은 조항이라 빼야 합니다.
RECALL_CAPPED = (r"(?:up to|limited to|shall not exceed|not to exceed|solely"
                 r"|only to the extent|caused by the seller'?s"
                 r"|한도|상한|초과하지)")

INDEMNIFY_BUYER = (r"(?:indemnif\w*\s+(?:and\s+(?:defend|hold)\s+)?(?:the\s+)?buyer"
                   r"|hold\s+(?:the\s+)?buyer\s+harmless"
                   r"|seller\s+shall\s+(?:\w+\s+){0,3}?(?:indemnif|defend|hold harmless))")


def _clause(key, title, category, why, risk, text_en, text_ko, detect,
            applies=("always",), fix="", countries=(), avoid=(), weak=(),
            require=None, context=(), neg_ok=False, strict=()):
    """조항 한 줄.

    countries
      이 조항이 **특히 흔한 나라**. ISO 2자리(또는 EU·GULF 같은 묶음)입니다.
      비어 있으면 어느 나라든 똑같이 봅니다.

      **찾는 일에는 쓰지 않습니다.** 도착국을 모를 때도 찾아야 하고, 중국
      중재 조항은 어디로 보내든 독소입니다. 보여 줄 때 앞세우는 데만 씁니다.
      (2026-10-02)

    avoid
      찾은 자리가 **이 말이 든 문장 안이면** 그 자리는 세지 않습니다.
      영어는 부정이 앞에 와서("shall not send") 규칙 안에 가드를 못 끼웁니다.
      그래서 찾은 뒤에 거릅니다. 부정이 **뜻의 일부**인 조항(최혜대우·경업금지)
      에는 붙이지 않습니다 — 붙이면 영영 못 찾습니다. (2026-10-02)

    아래 넷은 **필수·이익조항**에만 씁니다. 낱말이 보여도 그 조항이 제 구실을
    하는지는 따로 봐야 합니다. "Incoterms to be agreed later" 는 가격조건이
    **없는** 것이고, "no price adjustment" 는 가격조정이 **안 되는** 것입니다.
    전에는 둘 다 '있다'고 해서, 사용자를 안심시켰습니다. (2026-10-02)

    weak     ((문장 규칙, 까닭), …) — 찾은 자리의 문장이 이 꼴이면 '적혀 있으나
             불리'로 봅니다. 예: 금형이 바이어에게 귀속.
    require  ((규칙, …), 까닭) — 찾은 자리 둘레에 이 중 하나가 없으면 '적혀
             있으나 빈 조항'입니다. 예: 선적 조항인데 시기가 없음.
    context  문서 어디에든 이 중 하나가 있어야 이 조항을 봅니다. 가공계약에만
             있는 조항(위탁 원자재)을 보통 매매계약에서 찾지 않게 합니다.
    neg_ok   부정이 **뜻의 일부**인 조항(비밀유지·상계 금지·분할선적 금지)은
             앞뒤의 부정말로 약하다고 보지 않습니다.
    strict   **avoid 를 거치지 않는** 규칙. 부정이 독소의 뜻 그 자체인 문장
             — "shall not make any payment … unless the officials approve",
             "최종매수인이 지급하지 않는 경우 … 지급되지 않는다" — 은 avoid 의
             부정 가드가 통째로 걸러 버립니다. 이런 규칙은 극성을 **규칙 안에서**
             직접 봅니다. 뜻풀이(DEFINITION)만은 여기서도 거릅니다. (2026-10-03)
    """

    CLAUSES.append({
        "key": key, "title": title, "category": category, "why": why, "risk": risk,
        "text_en": text_en.strip(), "text_ko": text_ko.strip(),
        "detect": tuple(detect), "applies": tuple(applies), "fix": fix,
        "countries": tuple(countries), "avoid": tuple(avoid),
        "weak": tuple(weak), "require": require, "context": tuple(context),
        "neg_ok": bool(neg_ok), "strict": tuple(strict),
    })


# 나라 묶음. 도착국 2자리를 주면 이 묶음까지 함께 봅니다.
COUNTRY_GROUPS = {
    "EU": ("AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR",
           "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO",
           "SE", "SI", "SK"),
    "GULF": ("AE", "SA", "QA", "KW", "BH", "OM"),
}


def groups_for(country: str) -> set[str]:
    """도착국 2자리 -> 그 나라와 그 나라가 든 묶음."""

    code = (country or "").strip().upper()
    if not code:
        return set()
    found = {code}
    for name, members in COUNTRY_GROUPS.items():
        if code in members:
            found.add(name)
    return found


def for_country(country: str) -> list[dict]:
    """그 나라에서 **특히 흔한** 조항. 도착국을 알 때 앞세워 보여 줍니다."""

    tags = groups_for(country)
    if not tags:
        return []
    return [row for row in CLAUSES if tags & set(row["countries"])]


# ── 필수조항 ────────────────────────────────────────────────────────────────

_clause(
    "goods", "물품 명세 (Description of Goods)", "must",
    why="무엇을 파는지가 계약서에 없으면, 나중에 “이 물건이 아니다”라는 말을 막을 수 없습니다.",
    risk="규격이 빠지면 바이어가 임의 기준으로 불합격을 주장합니다. HS부호가 빠지면 관세 다툼이 생깁니다.",
    text_en="""1. DESCRIPTION OF GOODS
The Seller shall sell and the Buyer shall purchase the goods specified below
(the "Goods"). The specifications set out in Annex 1 form an integral part of
this Contract. Any deviation shall require the Seller's prior written consent.
  Commodity / HS Code / Specification / Quantity / Unit : as per Annex 1""",
    text_ko="품명·HS부호·규격·수량·단위를 **별지로 붙이고, 별지가 계약의 일부**임을 적습니다.",
    # "Annex 1: Specification (attached)" 한 줄에도 걸리던 것을 좁혔습니다.
    # 별지 제목만 있는 것은 물품 명세 조항이 아닙니다. (2026-09-26)
    detect=[r"description of goods", r"\bcommodity\b",
            r"specifications?\b.{0,20}(set (out|forth)|of the goods|shall (be|form))",
            r"물품\s*의?\s*명세", r"품명[^.]{0,30}(규격|수량|HS)",
            # 오퍼 시트는 조항이 아니라 **표**로 적습니다. 머리글만 있는 것은
            # 빼려고, 머리글 뒤에 금액(1,234.00)이 실제로 오는 꼴만 봅니다.
            # OCR 이 "Unit" 을 "보메" 로 읽어도 걸리게 사이를 넓게 둡니다. (2026-10-02)
            r"\bdescription\b.{0,40}\bquantity\b.{0,40}\bprice\b.{0,250}\d[\d,]*\.\d{2}\b",
            r"\bgoods\s*(?:&|and)\s*packing\s+details\b", r"\bitem\s+name\s*:"],
)

_clause(
    "incoterms", "가격조건 (Price & Incoterms 2020)", "must",
    why="비용과 위험이 어디서 넘어가는지가 여기서 정해집니다. 조건만 쓰고 장소를 안 적으면 뜻이 반쪽입니다.",
    risk="“CIF”만 적고 항구를 안 적으면 어디까지 우리 부담인지 다툽니다. 판(2020)을 안 적으면 옛 규칙을 주장합니다.",
    text_en="""2. PRICE AND TRADE TERMS
The unit price and total contract value are stated in Annex 1, on
<INCOTERMS> <NAMED PLACE> terms as defined in Incoterms(R) 2020 published by
the International Chamber of Commerce. All prices are in <CURRENCY>.""",
    text_ko="**조건 + 지정장소 + Incoterms 2020**을 한 줄에 다 적습니다. 예: CIF Yokohama, Incoterms 2020.",
    detect=[r"\bincoterms?\b", r"\b(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)\b",
            r"가격\s*조건", r"인코텀즈"],
)

_clause(
    "payment", "결제조건 (Payment Terms)", "must",
    why="언제 어떻게 받는지가 없으면 대금 회수의 근거가 없습니다.",
    risk="“선적 후 협의” 같은 문구는 사실상 무담보 외상입니다.",
    text_en="""3. PAYMENT
Payment shall be made by <L/C at sight | T/T> in <CURRENCY>.
Where payment is by documentary credit, the Buyer shall cause an irrevocable
letter of credit to be issued in favour of the Seller by a first-class bank
acceptable to the Seller, at least <30> days before the shipment date, and it
shall remain valid for at least <21> days after the latest shipment date.
The Buyer shall bear all banking charges outside the Seller's country.""",
    text_ko="**언제 개설하는지**와 **은행 수수료를 누가 내는지**까지 적어야 다툼이 없습니다.",
    detect=[r"대금\s*지급",
            r"결제\s*조건",
            r"전신환",
            r"\bpayment\b", r"letter of credit", r"\bL/?C\b", r"\bT/?T\b", r"결제\s*조건"],
)

_clause(
    "shipment", "선적조건 (Shipment · Partial · Transhipment)", "must",
    why="선적 기일과 분할·환적 허용 여부가 L/C 조건과 어긋나면 은행이 서류를 반송합니다.",
    risk="분할선적 금지인데 두 번에 나눠 실으면 대금을 못 받습니다.",
    text_en="""4. SHIPMENT
Latest date of shipment: <DATE>. Partial shipment: <ALLOWED / NOT ALLOWED>.
Transhipment: <ALLOWED / NOT ALLOWED>.
The date of the bill of lading (or air waybill) shall be conclusive evidence
of the date of shipment.""",
    text_ko="**선적 기일 · 분할선적 · 환적** 세 가지를 L/C와 **같은 말로** 적습니다.",
    detect=[r"분할\s*선적",
            r"환적",
            r"선적\s*기일",
            r"\bshipment\b", r"partial shipment", r"trans?[hs]ipment", r"선적\s*조건",
            # "선적은 2027년 3월 15일까지 한다" — 국문 본문 꼴을 못 봤습니다.
            # 시기는 아래 require 가 따로 봅니다. (2026-10-02)
            r"선적(?:은|을|일|\s*시기|\s*기한)"],
    # "PAYMENT : BY T/T BEFORE **SHIPMENT**" 의 낱말 하나로 '선적 조건이 있다'고
    # 했습니다. 실물 오퍼 시트에는 선적 기일이 어디에도 없었습니다. (2026-10-02)
    # 금액·수량의 숫자("by T/T 30% deposit")는 시기가 아닙니다. 날짜·일수 꼴만.
    require=((r"\d+\s*(?:\(\d+\)\s*)?(?:calendar\s+|business\s+|working\s+)?days",
              r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b",
              r"\b(?:sixty|thirty|ninety|forty[- ]five|fifteen|ten|seven)\s+(?:\(\d+\)\s*)?(?:calendar\s+|business\s+|working\s+)?days",
              r"\b(?:19|20)\d{2}\b", r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?",
              r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\b",
              r"partial|trans[hs]ipment|분할|환적", r"선적\s*기일", r"\d+\s*일", r"까지|이내"),
             "선적 시기(기일·기간)가 없습니다. '선적'이라는 낱말만 있습니다.", "absent"),
    neg_ok=True,
)

_clause(
    "inspection", "검사·품질 (Inspection)", "must",
    why="누가 어디서 무슨 기준으로 검사하는지가 없으면, 도착지에서 바이어 마음대로 불합격을 줍니다.",
    risk="검사 기한이 없으면 몇 달 뒤에도 클레임이 들어옵니다.",
    text_en="""5. INSPECTION
Inspection shall be carried out by <INSPECTOR> at the port of loading, and the
certificate so issued shall be final and binding on both parties as to quality
and quantity. Any claim shall be notified in writing within <15> days after
arrival of the Goods at the destination, failing which the Goods shall be
deemed accepted.""",
    text_ko="**선적지 검사를 최종으로** 하고, **도착 후 며칠 안에 통보하지 않으면 인수한 것으로 본다**를 넣습니다.",
    detect=[r"(?:quality|quantity)[^.]{0,60}(?:shall be )?inspect",
            r"inspect(?:ed|ion)[^.]{0,60}(?:quality|quantity|before shipment|at the port)",
            r"품질\s*검사",
            r"검수",
            r"검사[^.]{0,30}(?:실시|한다|받는다)",
            r"\binspection\b", r"certificate of inspection", r"검사\s*(기관|조건|증명)"],
    # "within ten business days **after inspection**" — 언제 검사하는지가 없으면
    # 상대가 몇 달 뒤에 검사하고 클레임을 겁니다. (2026-10-02 실물 보세가공 계약서)
    require=((r"before shipment|prior to (?:shipment|loading|dispatch)|pre-?shipment",
              r"at the (?:port|place|factory|warehouse|premises)|port of (?:loading|shipment|discharge)",
              r"(?:upon|after|on) (?:arrival|receipt|delivery)|at (?:the )?destination",
              r"\bby\s+(?:an?\s+|the\s+)?(?:independent|third|surveyor|inspector|SGS|BV|Intertek|Bureau)",
              r"surveyor|certificate|\bSGS\b|Intertek|Bureau Veritas",
              # "claim … within 10 days after inspection" 의 10일은 **통지** 기한이지
              # 검사 시기가 아닙니다. 검사에 붙은 기한만 셉니다.
              r"inspect\w*[^.]{0,30}within\s+\d",
              r"final and binding|conclusive|quality|quantity",
              # 방식·기준을 정한 문장도 검사 조항입니다 — "by sampling in accordance
              # with AQL 2.5", "전수검사를 실시한다". (2026-10-03 회귀 감사)
              r"\bAQL\b|sampling|\b100\s*%|standard|\bISO\b|전수|샘플링|발췌|기준",
              r"선적\s*전|선적지|도착|검사\s*기관|공인|검사증|이내[^.]{0,15}검사|품질|수량"),
             "검사를 언제·어디서·누가 하는지가 없습니다. 상대가 아무 때나 검사하고 클레임을 걸 수 있습니다.",
             "absent"),
)

_clause(
    "insurance", "보험 (Insurance)", "must",
    why="CIF·CIP는 우리가 보험을 듭니다. 부보 조건과 금액을 안 적으면 최저 담보만 들어도 된다고 다툽니다.",
    risk="CIP인데 ICC(C)만 들면 협정 위반입니다. 2020판 CIP는 ICC(A)가 기본입니다.",
    text_en="""6. INSURANCE
Where the agreed trade term requires the Seller to procure insurance, the
Seller shall insure the Goods for 110% of the invoice value in the currency of
this Contract, on <ICC(A) for CIP | ICC(C) for CIF> terms, with claims payable
at the destination.""",
    text_ko="**110% · 계약 통화 · 담보 범위**를 적습니다. CIF는 ICC(C), CIP는 **ICC(A)** 가 기본입니다.",
    detect=[r"marine cargo insurance",
            r"적하\s*보험",
            r"해상\s*보험",
            r"부보",
            r"\binsurance\b", r"\bICC\s*\(", r"보험\s*(조건|금액|부보)"],
    applies=("CIF", "CIP"),
)

_clause(
    "force_majeure", "불가항력 (Force Majeure)", "must",
    why="전쟁·천재지변·항만 파업·수출규제로 못 실었을 때 면책되는 근거입니다.",
    risk="없으면 우리 잘못이 아닌 지연에도 지연배상금을 물립니다.",
    text_en="""7. FORCE MAJEURE
Neither party shall be liable for any delay or failure to perform arising from
acts of God, war, civil commotion, epidemic, strike or lock-out, port
congestion, embargo, or export or import restriction, or any other cause
beyond its reasonable control. The affected party shall notify the other
within <10> days. If such event continues for more than <60> days, either
party may terminate this Contract without liability.""",
    text_ko="**사유 목록 · 통보 기한 · 장기화 시 해지**를 함께 적습니다. 수출규제를 목록에 꼭 넣으세요.",
    detect=[r"beyond[^.]{0,30}(?:reasonable\s+)?control",
            r"통제[^.]{0,20}(?:할 수 없|밖|범위)",
            r"force majeure", r"acts? of god", r"불가항력"],
    weak=((r"\bseller\b[^.]{0,30}not\s+(?:be\s+)?(?:excused|relieved|exempt(?:ed)?)"
           r"|not\s+(?:be\s+)?(?:excused|relieved|exempt(?:ed)?)[^.]{0,30}\bseller\b"
           r"|force majeure[^.]{0,60}(?:shall|does|will)\s+not\s+(?:apply|excuse|relieve)[^.]{0,30}seller",
           "불가항력 면책이 **우리(매도인)에게는** 적용되지 않게 적혀 있습니다."),
          (r"(?:매도인|공급자)[^.]{0,30}불가항력[^.]{0,30}(?:면책되지|적용하지|적용되지)",
           "불가항력 면책이 **우리(매도인)에게는** 적용되지 않게 적혀 있습니다.")),
)

_clause(
    "governing_law", "준거법 (Governing Law)", "must",
    why="어느 나라 법으로 판단할지가 없으면, 다툼이 났을 때 그것부터 싸웁니다.",
    risk="상대국 법으로 정해 두면 우리가 모르는 규정으로 판단받습니다.",
    text_en="""8. GOVERNING LAW
This Contract shall be governed by and construed in accordance with the laws
of the Republic of Korea. The United Nations Convention on Contracts for the
International Sale of Goods (CISG) <shall apply | shall not apply>.""",
    text_ko="**한국법**을 우선 제안합니다. CISG 적용 여부도 **명시**해야 합니다(안 적으면 기본 적용).",
    detect=[r"governed by[^.]{0,60}law",
            r"construed[^.]{0,40}(?:under|in accordance with)[^.]{0,40}law",
            r"(?:대한민국|한국)\s*법[^.]{0,30}(?:에 의|따른|따라|적용)",
            r"governing law", r"\bCISG\b", r"준거법"],
)

_clause(
    "arbitration", "분쟁해결 (Arbitration)", "must",
    why="외국 법원 판결은 상대국에서 집행이 어렵습니다. 중재 판정은 뉴욕협약으로 170여 개국에서 집행됩니다.",
    risk="소송으로 가면 상대국에서 몇 년이 걸리고, 이겨도 집행을 못 합니다.",
    text_en="""9. ARBITRATION
All disputes arising out of or in connection with this Contract shall be
finally settled by arbitration in Seoul, Republic of Korea, in accordance with
the International Arbitration Rules of the Korean Commercial Arbitration Board
(KCAB INTERNATIONAL). The language of the arbitration shall be English. The
award shall be final and binding upon both parties.""",
    text_ko="**중재지 · 기관 · 규칙 · 언어** 네 가지를 다 적어야 합니다. 하나라도 빠지면 그것부터 다툽니다.",
    detect=[r"arbitrat", r"\bKCAB\b", r"\bSIAC\b", r"중재"],
)

_clause(
    "title", "소유권 유보 (Retention of Title)", "must",
    why="대금을 다 받기 전에는 물건이 우리 것이라는 근거입니다.",
    risk="없으면 바이어가 부도났을 때 우리 물건이 그쪽 파산재단으로 들어갑니다.",
    text_en="""10. RETENTION OF TITLE
Title to the Goods shall pass to the Buyer only upon receipt by the Seller of
payment in full. Risk shall pass in accordance with the agreed Incoterms(R)
2020 term. The Buyer shall store the Goods separately and identifiably until
title passes.""",
    text_ko="**소유권은 대금 완납 시, 위험은 인코텀즈대로** — 둘을 갈라 적는 것이 핵심입니다.",
    detect=[r"ownership[^.]{0,80}(?:remain|pass|retain)",
            r"소유권[^.]{0,60}(?:유보|이전|귀속|남는)",
            r"retention of title", r"title .{0,30}shall pass",
            r"reservation of ownership", r"소유권\s*유보",
            # 판례에 나온 꼴 — ownership 이 아니라 property·owner 로 씁니다.
            # (Coutinho v. Tracomex 2015 BCSC 787 · Usinor v. Leeco 2002, 2026-10-03)
            r"remain\w*\s+the\s+(?:sole\s+|exclusive\s+)?(?:property|owner)\s+of\s+"
            r"(?:the\s+)?(?:seller|goods)[^.]{0,80}(?:until|up\s+to|unless)[^.]{0,40}pa(?:id|yment)",
            r"\btitle\b[^.]{0,30}(?:remain|retain|vest)\w*[^.]{0,30}seller[^.]{0,60}"
            r"until[^.]{0,40}pa(?:id|yment)"],
    # **인도·선적 때 넘어가면 유보가 아닙니다.** "title shall pass" 만 보고 '있다'고
    # 해서, 소유권이 대금 전에 넘어가는 계약서를 안심시켰습니다. 대금 말이 같은
    # 문장에 있으면(“provided that the price has been paid”) 유보입니다. (2026-10-03)
    weak=((r"^(?![^.]*(?:pa(?:id|yment)|price\s+has\s+been))[^.]*(?:pass|transfer|vest)\w*"
           r"[^.]{0,40}buyer[^.]{0,40}(?:upon|on|at|when|once)\s+(?:the\s+)?"
           r"(?:goods\s+(?:are|have\s+been)\s+)?(?:deliver|ship|load|arriv|hand|tender|discharg)",
           "소유권이 **대금과 상관없이** 인도·선적 때 넘어갑니다. 대금 전에 바이어가 부도나면 "
           "물건을 되찾을 근거가 없습니다."),
          (r"^(?![^.]*(?:대금|완납|지급|결제))[^.]*소유권[^.]{0,30}(?:선적|인도|도착|적재|하역)\s*"
           r"(?:시|와\s*동시에|하는\s*때|한\s*때)[^.]{0,30}(?:매수인|바이어)[^.]{0,10}(?:이전|귀속|넘어)",
           "소유권이 **대금과 상관없이** 인도·선적 때 넘어갑니다. 대금 전에 바이어가 부도나면 "
           "물건을 되찾을 근거가 없습니다.")),
)

# ── 이익조항 ────────────────────────────────────────────────────────────────

_clause(
    "late_interest", "지연이자 (Late Payment Interest)", "gain",
    why="늦게 줘도 손해가 없으면 늦게 줍니다.",
    risk="없으면 90일 연체를 해도 원금만 받습니다.",
    text_en="""LATE PAYMENT
Any amount not paid when due shall bear interest at <0.05>% per day from the
due date until actual payment, without prejudice to any other remedy of the
Seller. The Seller may suspend further shipments while any amount is overdue.""",
    text_ko="**일할 이자 + 연체 중 선적 중단권**을 함께 넣어야 실제로 압박이 됩니다.",
    detect=[r"이자[^.]{0,30}(?:부담|가산|지급|붙)",
            r"연\s*\d{1,2}(?:\.\d+)?\s*%[^.]{0,30}이자",
            r"late payment", r"interest at", r"overdue", r"지연\s*이자", r"연체\s*이자"],
    weak=((r"\bno\s+(?:late\s+|default\s+|penalty\s+)?interest\b|interest\s+shall\s+not|without\s+interest"
           r"|이자[^.]{0,10}(?:없|아니|않)",
           "연체 이자가 **없다**고 적혀 있습니다."),),
)

_clause(
    "price_adjust", "가격 조정 (Price Adjustment)", "gain",
    why="환율과 원자재가 움직이면 고정가는 우리 손해로만 갑니다.",
    risk="1년 고정가 계약에서 환율이 10% 움직이면 이익이 통째로 사라집니다.",
    text_en="""PRICE ADJUSTMENT
If, between the date of this Contract and the date of shipment, the exchange
rate of <CURRENCY> against KRW moves by more than <3>%, or the price of the
principal raw material moves by more than <5>%, either party may request a
price review. Failing agreement within <14> days, either party may cancel the
affected order without liability.""",
    text_ko="**기준(환율·원자재) · 변동 폭 · 협의 기한 · 안 되면 취소**까지 적어야 작동합니다.",
    detect=[r"price[^.]{0,60}(?:may be |subject to |shall be )?adjust",
            r"adjust[^.]{0,60}price",
            r"(?:단가|가격)[^.]{0,50}(?:조정|재협의|재산정|변경)",
            r"원자재[^.]{0,50}(?:변동|상승|등락)",
            r"price adjustment", r"price review", r"exchange rate .{0,40}(move|fluctuat)",
            r"가격\s*조정"],
    weak=((r"(?:shall|will|may)\s+not\s+be\s+(?:adjusted|changed|revised|increased)"
           r"|not\s+subject\s+to\s+(?:any\s+)?(?:adjustment|revision|change)"
           r"|조정(?:하지|되지)\s*(?:아니|않)|변경\s*불가",
           "가격을 **조정할 수 없다**고 적혀 있습니다."),),
)

_clause(
    "liability_cap", "책임 한도 (Limitation of Liability)", "gain",
    why="배상액의 상한이 없으면 1만 달러짜리 거래로 100만 달러를 물 수 있습니다.",
    risk="간접손해·일실이익까지 물면 회사가 흔들립니다.",
    text_en="""LIMITATION OF LIABILITY
The Seller's aggregate liability under or in connection with this Contract
shall not exceed the invoice value of the Goods giving rise to the claim. In
no event shall the Seller be liable for indirect, incidental, special or
consequential loss, or loss of profit, revenue or business.""",
    text_ko="**총액 상한(송장 금액) + 간접손해 배제** 두 문장이 한 쌍입니다.",
    # **흔한 문구 다섯을 놓치고 있었습니다.** (2026-10-02 공격해 보다 찾음)
    #
    # 이익조항의 미탐은 **이미 넣은 사람에게 "넣으세요"** 라고 하는 것입니다.
    # 그 말을 들은 사람은 다음부터 이 화면을 믿지 않습니다.
    #
    # `consequential` 을 홀로 보던 것도 고쳤습니다. "liable for all direct,
    # indirect and consequential damages **without limitation**" 은 무제한
    # 배상 조항인데 "책임 한도가 있다"로 읽혔습니다. 정반대입니다.
    detect=[r"limitation of liability",
            r"(?:aggregate|total|maximum|overall)\s+liability",
            r"liability[^.]{0,60}(?:shall )?not exceed",
            r"(?:in no event|under no circumstances)[^.]{0,80}"
            r"liability[^.]{0,40}exceed",
            r"liability[^.]{0,40}(?:is|shall be)?\s*limited to",
            # 간접·결과적 손해를 **빼는** 문맥일 때만 봅니다.
            r"(?:not be liable|no liability|exclude[sd]?|disclaim)"
            r"[^.]{0,80}(?:indirect|consequential)",
            r"(?:indirect|consequential)[^.]{0,60}"
            r"(?:excluded|disclaimed|shall not (?:be )?(?:apply|recoverable))",
            r"책임\s*(?:의)?\s*한도" + NO_NEG_KO,
            r"손해배상\s*(?:의)?\s*한도" + NO_NEG_KO,
            r"(?:배상|책임)[^.]{0,40}(?:초과하지|넘지)\s*(?:아니|않)",
            r"(?:배상|책임)[^.]{0,30}(?:으로|로)\s*한정" + NO_NEG_KO,
            # "compensate … for **direct loss** proved" — 간접손해를 빼는 한정.
            # 실물 보세가공 계약서 제6조. (2026-10-02)
            r"(?:compensate|liable|indemnif\w*)[^.]{0,80}\bdirect\s+(?:loss|losses|damages?)\b"],
    weak=((r"\bunlimited\b|without\s+(?:any\s+)?(?:monetary\s+|financial\s+)?limit",
           "책임 한도가 **없다**고 적혀 있습니다."),),
)

_clause(
    "export_licence", "수출허가 조건 (Export Control)", "gain",
    why="전략물자 판정이나 수출허가가 안 나오면 우리 잘못이 아닌데도 불이행이 됩니다.",
    risk="허가 미취득으로 못 실었는데 지연배상금을 물 수 있습니다.",
    text_en="""EXPORT CONTROL
This Contract is subject to the Seller obtaining all export licences and
approvals required under the laws of the Republic of Korea. If any such
licence is refused or withdrawn, the Seller may cancel the affected order
without liability, and the Buyer shall not claim any damages.""",
    text_ko="**허가를 못 받으면 면책**임을 적습니다. 전략물자·이중용도 품목이면 반드시 넣으세요.",
    detect=[r"export (?:approval|permit|authoris|authoriz)",
            r"수출\s*(?:승인|허가|신고)",
            r"export licen[cs]e", r"export control", r"수출\s*허가"],
    neg_ok=True,
)

_clause(
    "ip", "금형·도면 소유권 (Tooling & IP)", "gain",
    why="바이어 주문으로 만든 금형과 도면이 누구 것인지 안 적으면 거래가 끊길 때 가져갑니다.",
    risk="금형을 내주면 다음 해부터 다른 공장에서 같은 물건이 나옵니다.",
    text_en="""TOOLING AND INTELLECTUAL PROPERTY
All tooling, moulds, drawings and technical know-how developed or used by the
Seller shall remain the sole property of the Seller, notwithstanding any
contribution by the Buyer to their cost, unless otherwise agreed in writing.""",
    text_ko="**비용을 바이어가 냈더라도 우리 것**이라고 적어 두는 것이 핵심입니다.",
    detect=[r"(?:drawings?|technical data|designs?)[^.]{0,80}(?:propert|belong|remain)[^.]{0,40}seller",
            r"(?:금형|치공구|도면|지그)[^.]{0,50}(?:소유권|귀속)[^.]{0,30}(?:매도인|공급자)",
            r"\btooling\b", r"\bmou?lds?\b", r"intellectual property", r"금형", r"도면"],
    weak=((r"(?:vest|belong|remain|transfer|pass)\w*[^.]{0,30}(?:in|to|with)\s+(?:the\s+)?buyer"
           r"|property of the buyer|buyer\s+shall\s+own"
           r"|(?:매수인|바이어)(?:에게|의)\s*(?:귀속|소유|있)",
           "금형·도면이 **상대(바이어) 소유**로 적혀 있습니다."),),
)

_clause(
    "min_order", "최소 주문·취소 수수료 (MOQ & Cancellation)", "gain",
    why="독점권만 주고 최소 물량이 없으면, 우리는 묶이고 상대는 자유롭습니다.",
    risk="독점 계약 1년 동안 한 건도 안 사도 우리는 다른 데 못 팝니다.",
    text_en="""MINIMUM ORDER AND CANCELLATION
The Buyer shall purchase not less than <QUANTITY> per <PERIOD>. Orders
confirmed by the Seller may not be cancelled or reduced after the Seller has
commenced production; in such case the Buyer shall pay <30>% of the order
value as a cancellation charge.""",
    text_ko="독점을 주면 **최소 물량**을 반드시 붙이세요. 취소 수수료는 생산 착수 시점 기준으로 적습니다.",
    detect=[r"cancellation (?:fee|charge|cost)",
            r"취소\s*수수료",
            r"최소\s*(?:주문|구매|발주)\s*(?:수량|물량|량)",
            r"minimum (order|purchase)", r"\bMOQ\b", r"cancellation charge", r"최소\s*주문"],
)

# ── 독소조항 ────────────────────────────────────────────────────────────────

# 간접손해·영업손실. unlimited_damages 에서 씁니다. (2026-10-03)
_INDIRECT_EN = (r"(?:\b(?:indirect|consequential|special|incidental)\b[^.]{0,40}?"
                r"\b(?:damages?|loss(?:es)?)\b"
                r"|\bloss(?:es)?\s+of\s+(?:profits?|business|production|revenue|goodwill)\b"
                r"|\blost\s+profits?\b)")
# "NEITHER PURCHASER **NOR SELLER** SHALL BE LIABLE … CONSEQUENTIAL" 은 빼는 조항입니다.
CONSEQUENTIAL_EN = (r"(?<!nor )(?<!neither )"
                    r"\b(?:seller|supplier|vendor)\s+(?:shall|will|must|agrees?\s+to|undertakes?\s+to)"
                    r"\s+(?:also\s+|further\s+|fully\s+)?(?:be\s+)?"
                    r"(?:liable|responsible|indemnify|compensate|reimburse)\b"
                    # 동사와 손해 사이 — 빼거나 한정하는 말이 끼면 아닙니다.
                    r"(?:(?!\b(?:not|no|nor|but|except|other\s+than|exclud\w*|limited)\b)[^.]){0,150}?"
                    + _INDIRECT_EN +
                    # 문장 끝까지 — 한도가 붙으면 무제한이 아닙니다.
                    r"(?![^.]*\b(?:limited\s+to|not\s+(?:to\s+)?exceed\w*|up\s+to|cap(?:ped)?|maximum)\b)")
# 국문은 주제 조사(은·는)만 봅니다. "매수인은 매도인**이** 입은 간접손해를" 은
# 바이어가 무는 문장입니다. 손해 낱말 뒤 40자에 부정·제외·한도가 오면 아닙니다.
CONSEQUENTIAL_KO = (r"(?:매도인|공급자|수출자|판매자)(?:은|는)[^.]{0,60}?"
                    r"(?:간접\s*손해|특별\s*손해|결과\s*적?\s*손해|파생\s*손해|일실\s*이익"
                    r"|영업\s*손실|기대\s*이익|이익\s*상실)"
                    # "배**상한**다" 의 상한은 한도가 아닙니다 — 낱말 가운데를 조심합니다.
                    r"(?![^.]{0,40}(?:없|아니|않|제외|배제|면제|한도|(?<![배보])상한|초과하지))"
                    r"[^.]{0,40}(?:배상|보상|책임을\s*진|부담)")

_clause(
    "unlimited_damages", "무제한 손해배상", "toxic",
    why="상한이 없는 배상 약속은 거래 규모와 무관하게 회사를 무너뜨릴 수 있습니다.",
    risk="송장 1만 달러짜리 건에서 바이어의 영업손실 전부를 물게 됩니다.",
    text_en="""(지울 문구의 예)
The Seller shall indemnify the Buyer against any and all losses, damages and
expenses of whatever nature, including loss of profit, without limitation.""",
    text_ko="without limitation · any and all · loss of profit 이 함께 나오면 이 조항입니다.",
    # **`without limitation` 을 맨 낱말로 보면 안 됩니다.** (2026-10-02)
    #
    # 영문 계약서에서 "including without limitation" 은 "~를 포함하되 이에
    # 한정되지 않는"이라는 상투어이고, 책임 한도와 상관이 없습니다. 이 말은
    # 실무 계약서 대부분에 들어가서, 전에는 **거의 매번** 이 조항이 떴습니다.
    #   "The Goods shall include, without limitation, packaging and manuals."
    # 책임·손해 이야기일 때만 봅니다.
    detect=[r"liabilit(?:y|ies)[^.]{0,40}(?:shall be |is )?unlimited",
            # **낱말 경계와 배상 이야기에 묶습니다.** 경계가 없어 "notice"·"nor"·
            # "Sicap"·"Expense Cap" 에서 걸렸고, 가격 인상의 "no escalation cap" 도
            # 걸렸습니다(실제 계약서 2 차 검증, 2026-10-03).
            r"(?:liabilit|damages|indemnif|indemnit|compensat|loss)[^.]{0,80}"
            r"\bno\s+(?:\w+\s+){0,2}?(?:financial\s+|monetary\s+)?(?:ceiling|cap)\b",
            r"\bno\s+(?:financial\s+|monetary\s+)?(?:ceiling|cap)\b[^.]{0,60}"
            r"(?:liabilit|damages|indemnif|compensat)",
            r"(?:배상|책임)[^.]{0,30}(?:상한|한도)[^.]{0,20}(?:두지|정하지)[^.]{0,10}(?:아니|않)",
            r"제한\s*없이[^.]{0,20}배상",
            # **우리가 무는 문장일 때만.** (2026-10-03)
            # 전에는 "any and all losses" 와 책임 낱말 옆의 "without limitation" 을
            # 방향 없이 봐서, 실제 계약서 1,310 건 중 539 건이 걸렸는데 우리(매도인)가
            # 무는 문장은 5 건이었습니다 — 간접손해를 **빼는** 조항("Neither party
            # shall be liable … including, without limitation, lost profits"), 세금
            # 조항, 바이어가 무는 조항이 걸렸고, 그러면 책임 한도 조항까지 '무력'으로
            # 바뀌었습니다. 이제는 Seller 가 배상 동사의 주어이고, "including, without
            # limitation" 상투어가 아니고, 문장에 상한이 없을 때만 봅니다.
            # "will **not** be responsible and disclaims" · "**nor** Seller shall be liable"
            # 은 면책을 거부하거나 빼는 문장입니다 — 건너뛰는 낱말에 부정을 넣지 않습니다.
            r"(?<!nor )(?<!neither )"
            r"\b(?:seller|supplier|vendor|manufacturer|exporter)\s+(?:shall|will|must|hereby\s+agrees?\s+to"
            r"|agrees?\s+to|undertakes?\s+to)\s+(?:(?!not\b|never\b)\w+,?\s+){0,5}?(?:indemnif\w*|defend|hold\s+harmless"
            r"|be\s+(?:fully\s+)?(?:liable|responsible)|compensate|reimburse)\b[^.]{0,160}?"
            r"(?:any\s+and\s+all\s+(?:losses|damages|liabilit\w+|claims|costs)"
            r"|(?<!including )(?<!including, )(?<!includes )(?<!include )without\s+(?:any\s+)?limitation)"
            r"(?![^.]*\b(?:not\s+(?:to\s+)?exceed\w*|limited\s+to|in\s+no\s+event|aggregate\s+liability"
            r"|cap(?:ped)?)\b)",
            r"unlimited liability",
            r"무제한\s*(으로)?[^.]{0,6}(배상|책임)",
            r"(한도|상한|제한)[^.]{0,3}없이[^.]{0,30}배상",
            r"배상[^.]{0,15}(한도|상한)[^.]{0,6}없",
            # "for all losses … **without monetary limit**" — 실물 보세가공 계약서
            # 제9조. limitation 이 아니라 limit 이고, any and all 이 아니라 all
            # 이라 놓쳤습니다. 배상 이야기 뒤에 올 때만 봅니다. (2026-10-02)
            r"(?:liabilit|damages|indemnif|indemnit|losses|compensat)[^.]{0,300}"
            r"without\s+(?:any\s+)?(?:monetary|financial|maximum|upper)\s+"
            r"(?:limit|limitation|cap|ceiling)\b",
            r"\bno\s+(?:monetary|financial|maximum|upper)\s+limit\b[^.]{0,60}"
            r"(?:liabilit|damages|indemnif|indemnit|losses)",
            # **간접손해·영업손실을 우리가 떠안는 꼴.** (2026-10-03)
            #   "The Seller shall be liable for all indirect, consequential and
            #    special damages, including loss of profit"
            # 상한 없는 배상에서 가장 흔한 꼴인데 위 말들이 안 들어 있어 놓쳤습니다.
            # 그런데 간접손해라는 말은 **빼는** 조항("Neither party shall be liable
            # for … consequential damages")에 훨씬 자주 나옵니다. 그래서
            #   - 주어가 Seller 이고 바로 뒤에 배상 동사가 와야 하고
            #     ("In no event shall the Seller be liable" 은 이 꼴이 아닙니다)
            #   - 동사와 손해 사이에 not·excluding·other than·but 이 없어야 하고
            #   - 문장에 한도(limited to · not exceed · up to)가 없어야 합니다.
            # 걸리면 안 되는 문장은 tests/test_contract_consequential.py 에 있습니다.
            CONSEQUENTIAL_EN,
            CONSEQUENTIAL_KO],
    fix="책임 한도(Limitation of Liability) 조항을 넣어 **송장 금액 상한**과 **간접손해 배제**로 바꿔 달라고 하세요.",
    # 서로 배상하는 상호 조항("hold one another harmless")은 우리만 무는 것이 아닙니다.
    avoid=INDEMNIFY_SELLER + (r"\bone\s+another\b", r"\beach\s+other\b"),
)

_clause(
    "termination_at_will", "바이어의 일방적 해지권", "toxic",
    why="상대가 언제든 이유 없이 끊을 수 있으면, 우리가 들인 준비 비용은 전부 우리 손해입니다.",
    risk="원자재를 사 두고 생산에 들어간 뒤 해지 통보를 받습니다.",
    text_en="""(지울 문구의 예)
The Buyer may terminate this Contract at any time for convenience upon written
notice, without liability.""",
    text_ko="for convenience · at any time · without liability 가 붙어 있으면 이 조항입니다.",
    detect=[r"(?:cancel|terminate|end)[^.]{0,70}(?:sole|absolute)\s+discretion",
            r"(?:walk away|withdraw)[^.]{0,70}(?:for convenience|at any time)",
            r"재량[^.]{0,30}(?:해지|해제|종료)",
            r"사유[^.]{0,15}없(?:이|어도)[^.]{0,30}(?:해지|종료|취소)",
            r"terminate.{0,60}for convenience", r"at any time.{0,40}without (liability|cause)",
            r"일방적으로\s*해지", r"사유[^.]{0,10}불문[^.]{0,40}해지",
            r"언제든지[^.]{0,40}해지", r"이유\s*없이[^.]{0,30}해지",
            r"임의\s*로[^.]{0,20}해지"],
    fix="해지에 **사유와 예고기간**을 붙이고, 생산 착수 뒤에는 **취소 수수료**를 물도록 바꿉니다.",
    # **방향이 뒤집힌 꼴은 우리에게 유리합니다.** 예문의 Seller ↔ Buyer 를 맞바꿔도
    # 걸려서, 아래 꼴은 거릅니다. (tests/test_contract_direction.py, 2026-10-03)
    avoid=(r"^(?![^.]*\b(?:buyer|purchaser|either\s+party|each\s+party|both\s+parties)\b[^.]{0,60}"
           r"\b(?:may|right|entitled)\b)[^.]*\b(?:seller|supplier)\s+(?:may|shall\s+have\s+the\s+right\s+to"
           r"|is\s+entitled\s+to)\s+(?:\w+\s+){0,3}?(?:terminate|cancel)",
           r"^(?![^.]*(?:매수인|바이어)[^.]{0,30}(?:해지|해제)할\s*수)[^.]*(?:매도인|공급자)(?:은|는)"
           r"[^.]{0,40}(?:해지|해제)할\s*수\s*있"),
)

_clause(
    "foreign_forum", "상대국 법원 전속관할", "toxic",
    why="상대 나라 법원에서 그 나라 법으로 다투면, 비용과 시간에서 우리가 크게 불리합니다.",
    risk="이겨도 집행에 몇 년이 걸리고, 변호사 비용이 청구금액을 넘습니다.",
    text_en="""(지울 문구의 예)
The courts of <BUYER'S COUNTRY> shall have exclusive jurisdiction over any
dispute arising out of this Contract.""",
    text_ko="exclusive jurisdiction 과 상대국 이름이 함께 나오면 이 조항입니다. 중재 조항과 **같이** 있으면 서로 모순됩니다.",
    # **법원이 어디인지 봅니다.** (2026-10-02)
    #
    # 전에는 `exclusive jurisdiction` 과 `전속적 관할` 만 보아, 서울중앙지방법원
    # 전속관할도 독소로 짚었습니다. 한국 법원 전속관할은 우리에게 **유리한**
    # 조항입니다. 그걸 지우라고 하면 안 됩니다.
    #
    # 뒤에 한국 지명이 오면 뺍니다. 영문에서 지명이 **앞**에 오는 꼴
    # ("courts of Seoul shall have exclusive jurisdiction")은 파이썬 정규식이
    # 길이가 변하는 뒤돌아보기를 못 하므로, `courts of` 쪽에서 가립니다 —
    # 그래서 맨 뒤 `exclusive jurisdiction` 규칙은 **of/in 이 뒤따르는 꼴만**
    # 봅니다. 지명이 앞에 오면 그 뒤에는 보통 "over any dispute"가 옵니다.
    detect=[rf"exclusive jurisdiction\s+(?:of|in)\s+(?![^.]{{0,40}}{KOREA})",
            rf"courts? of (?![^.]{{0,40}}{KOREA})[^.]{{0,40}}(?:shall have|exclusive)",
            rf"전속\s*적?[^.]{{0,4}}관할(?![^.]{{0,40}}{KOREA})",
            r"관할\s*법원[^.]{0,30}(매수인|바이어)",
            # "disputes **go to** the courts of New York" — shall have 가 없는 꼴 (2026-10-02)
            rf"(?:disputes?|claims?)[^.]{{0,40}}(?:go|be\s+(?:referred|submitted|brought|heard))\s+"
            rf"(?:to|in|before)\s+the\s+courts?\s+of\s+(?![^.]{{0,40}}{KOREA})"],
    fix="**중재(KCAB, 서울)** 로 바꾸거나, 최소한 **제3국 중재**로 바꿔 달라고 하세요.",
    avoid=NEGATION + KOREAN_FORUM,
)

_clause(
    "payment_on_resale", "재판매 대금 수령 조건부 결제", "toxic",
    why="바이어가 팔아야 우리가 받는 구조입니다. 안 팔리면 영영 못 받습니다.",
    risk="사실상 위탁판매인데 계약서는 매매로 되어 있어, 물건도 돈도 없는 상태가 됩니다.",
    text_en="""(지울 문구의 예)
Payment shall be made within 30 days after the Buyer receives payment from its
end customer.""",
    text_ko="after the Buyer receives payment · upon resale 이 나오면 이 조항입니다.",
    detect=[r"payment[^.]{0,50}due only (?:once|after|when)",
            r"proceeds of (?:the )?resale",
            r"(?:최종\s*수요자|최종\s*고객|제3자)[^.]{0,40}(?:회수|수령)[^.]{0,40}(?:지급|정산)",
            r"(?:판매|회수)[^.]{0,20}대금[^.]{0,30}회수[^.]{0,20}후[^.]{0,20}(?:지급|정산)",
            r"after the buyer .{0,20}receive[sd]? payment", r"upon resale",
            r"from its (end )?customer",
            r"재판매[^.]{0,30}(대금|수령|지급)",
            r"최종\s*(고객|수요자|구매자)[^.]{0,30}(대금|수령|지급)"],
    # **부정이 뜻 그 자체인 꼴.** 신용장 특수조건으로 들어옵니다. (대법원
    # 2000.5.30. 98다47443 — 이 조건을 유효한 지급거절 조건으로 봤습니다.)
    #   "최종매수인이 … 75일 내에 … 대금을 지급하지 않는 경우 인수된 어음과
    #    서류들은 만기일에 지급되지 않는다"
    strict=[r"최종\s*(?:매수인|고객|수요자|구매자|바이어)[^.]{0,80}(?:지급|결제)하지\s*않는\s*"
            r"(?:경우|때)[^.]{0,80}(?:지급|결제|인수|매입)(?:되|하)지\s*(?:않|아니)",
            r"(?:shall|will)\s+not\s+be\s+(?:paid|honou?red)[^.]{0,80}\bunless\b[^.]{0,60}"
            r"(?:end|final|ultimate)\s+(?:customer|buyer|purchaser)\w*[^.]{0,30}(?:pa(?:y|id)|remit)"],
    fix="**선적일 또는 B/L일 기준**으로 기한을 바꾸고, 안 되면 L/C나 수출보험으로 막으세요.",
    # "최종 고객이 지급하지 **않더라도** 매수인은 지급한다" 는 우리를 지키는
    # 문장입니다. '않더라도' 는 NEGATION 의 꼴(않는·않으)에 안 걸려서 짚었습니다.
    avoid=NEGATION + (r"(?:않|없)더라도", r"관계\s*없이", r"무관하게", r"불구하고",
                      r"\bregardless\b", r"\birrespective\b"),
)

_clause(
    "open_warranty", "기간 제한 없는 하자보증", "toxic",
    why="보증 기간이 없으면 몇 년 뒤 클레임에도 대응해야 합니다.",
    risk="3년 전 선적분으로 전량 교체를 요구받습니다.",
    text_en="""(지울 문구의 예)
The Seller warrants the Goods against any defect without time limitation.""",
    text_ko="보증에 **기간**과 **범위**가 없으면 이 조항입니다.",
    # 제목이 "**기간 제한 없는** 하자보증"인데 국문 규칙은 `무기한` 하나뿐이어서
    # "기간의 제한 없이 하자를 보수하여야 한다"를 못 찾았습니다. 실무에서는
    # "무기한"보다 "기간 제한 없이"·"기한 없이"·"영구히"를 더 많이 씁니다. (2026-10-02)
    #
    # 기간을 **정한** 문장("하자보증기간은 12개월로 한다")은 그대로 통과해야 하므로
    # '없' 또는 '영구'가 함께 있을 때만 봅니다.
    detect=[r"(?:warrant|guarantee)[^.]{0,50}indefinite",
            r"indefinite[^.]{0,30}period[^.]{0,30}(?:warrant|defect)",
            r"no time bar",
            r"(?:하자|담보)\s*책임[^.]{0,30}기간[^.]{0,20}정하지[^.]{0,10}아니",
            r"기한[^.]{0,10}(?:의\s*)?정함\s*없",
            r"warrant.{0,80}without (any )?(time )?limit",
            r"perpetual warranty",
            r"(warrant|defects?)[^.]{0,60}in perpetuity",
            r"무기한\s*(보증|하자)",
            r"(기간|기한)[^.]{0,8}(제한[^.]{0,4})?없[^.]{0,30}(보증|보수|수리|교체|하자)",
            r"(보증|보수|하자)[^.]{0,30}(기간|기한)[^.]{0,8}(제한[^.]{0,4})?없",
            r"영구[^.]{0,20}(보증|보수|하자)"],
    fix="**선적일로부터 12개월 또는 도착 후 6개월 중 먼저 오는 날**처럼 기한을 박으세요.",
)

_clause(
    "uncapped_ld", "상한 없는 지연배상금", "toxic",
    why="하루씩 무한히 쌓이면 계약금액을 넘습니다.",
    risk="선적이 한 달 늦으면 대금보다 배상금이 커집니다.",
    text_en="""(살펴볼 문구의 예)
The Seller shall pay liquidated damages of 1% of the contract value for each
day of delay.""",
    text_ko="지연배상금에 **상한(cap)** 이 없으면 이 조항입니다.",
    detect=[r"liquidated damages[^.]{0,70}(?:without|no)[^.]{0,25}(?:maximum|cap|ceiling|limit)",
            r"(?:accumulate|accrue)[^.]{0,50}no\s+(?:ceiling|cap|maximum|limit)",
            r"지체상금[^.]{0,40}(?:상한|한도)[^.]{0,25}(?:두지|없|아니)",
            r"(?:지연|납기)[^.]{0,20}배상금[^.]{0,40}한도[^.]{0,25}(?:아니|없)",
            r"liquidated damages", r"penalt(y|ies) .{0,30}per day", r"지연\s*배상금"],
    fix="“**총 계약금액의 5%를 넘지 않는다**”는 상한 문장을 반드시 붙이세요.",
    # **방향이 뒤집힌 꼴은 우리에게 유리합니다.** 예문의 Seller ↔ Buyer 를 맞바꿔도
    # 걸려서, 아래 꼴은 거릅니다. (tests/test_contract_direction.py, 2026-10-03)
    avoid=(r"\b(?:buyer|purchaser)\s+shall\s+pay\s+(?:to\s+the\s+seller\s+)?(?:liquidated\s+damages"
           r"|a\s+penalty|late\s+(?:payment\s+)?(?:fees?|charges?|interest))",
           r"delay\s+in\s+(?:the\s+)?payment", r"overdue\s+(?:amount|sum|payment)",
           r"(?:매수인|바이어)(?:은|는|이|가)[^.]{0,30}(?:지체상금|위약금|지연\s*손해금)",
           r"(?:대금|지급)\s*지연"),
)

_clause(
    "term_conflict", "인코텀즈와 어긋나는 비용·위험 문구", "toxic",
    why="“FOB인데 도착지까지 위험은 판매자가 진다” 같은 문장은 조건을 통째로 뒤집습니다.",
    risk="FOB 가격을 받고 DAP 책임을 지게 됩니다.",
    text_en="""(살펴볼 문구의 예)
Notwithstanding the trade term, the Seller shall bear all risks and costs until
the Goods are delivered to the Buyer's warehouse.""",
    text_ko="notwithstanding the trade term · regardless of Incoterms 가 보이면 그 뒤를 꼭 읽으세요.",
    detect=[r"irrespective of[^.]{0,50}(?:trade term|incoterm)",
            r"(?:인코텀즈|가격조건|무역조건)[^.]{0,25}(?:와\s*)?(?:무관|불구)",
            r"notwithstanding .{0,40}(trade term|incoterms)",
            r"regardless of .{0,30}incoterms",
            r"bear all risks? and costs? until",
            r"인코텀즈[^.]{0,30}불구하고", r"(가격|거래)\s*조건[^.]{0,20}불구하고",
            r"목적지[^.]{0,20}인도[^.]{0,40}(위험|비용)[^.]{0,20}부담"],
    fix="인코텀즈 조건과 **같은 뜻**이 되게 고치거나, 아예 그 조건으로 가격을 다시 매기세요.",
)

_clause(
    "evergreen", "자동 연장 + 과도한 해지 예고", "toxic",
    why="가만히 두면 계속 연장되고, 끊으려면 아주 일찍 알려야 합니다.",
    risk="손해가 나는 조건에 1년 더 묶입니다.",
    text_en="""(살펴볼 문구의 예)
This Contract shall be automatically renewed for successive one-year periods
unless either party gives written notice at least 180 days before expiry.""",
    text_ko="automatically renewed 와 함께 **90일이 넘는 예고기간**이 붙어 있으면 조심하세요.",
    detect=[r"\d+\s*일\s*전[^.]{0,30}통지[^.]{0,20}없으면",
            r"(?:통지|통보)[^.]{0,15}없으면[^.]{0,30}(?:갱신|연장)",
            r"renew[^.]{0,70}(?:successive|further|additional|annual)",
            r"roll(?:s|ed|ing)?\s+over",
            r"자동[^.]{0,12}(?:으로\s*)?(?:연장|갱신)(?![^.]{0,25}(?:되지\s*아니|되지\s*않|하지\s*아니|하지\s*않))",
            r"\d+\s*일\s*전[^.]{0,45}(?:통지|통보)[^.]{0,25}없으면",
            r"(?:해지|종료)\s*(?:통보|통지)[^.]{0,25}없는\s*한",
            r"automatically renew", r"successive .{0,30}periods", r"자동\s*(연장|갱신)(?![^.]{0,25}(?:되지\s*아니|되지\s*않|하지\s*아니))"],
    fix="예고기간을 **30~60일**로 줄이거나, 자동 연장을 빼고 **합의 연장**으로 바꾸세요.",
    avoid=RENEWAL_DENIED,
)

_clause(
    "mfn_price", "최혜대우 가격 조항 (MFN)", "toxic",
    why="다른 어느 바이어에게도 이보다 싸게 팔 수 없게 묶는 조항입니다.",
    risk="신규 거래처에 판촉가를 주면 이 바이어에게 소급해서 차액을 물어 줘야 합니다.",
    text_en="""(살펴볼 문구의 예)
The Seller shall not sell the Goods to any third party at a price lower than
that offered to the Buyer, and shall refund the difference if it does so.""",
    text_ko="most favoured · no less favourable · price lower than 이 나오면 이 조항입니다.",
    detect=[r"(?:타|다른)\s*거래처[^.]{0,40}(?:낮은|유리한)[^.]{0,20}(?:가격|조건)",
            r"소급[^.]{0,25}(?:차액|차익)[^.]{0,20}(?:보전|환급|지급)",
            r"no other (?:customer|buyer|purchaser|party)[^.]{0,70}(?:more favourable|more favorable|better|lower)",
            r"more favo(?:u)?rable[^.]{0,35}(?:pricing|price|terms)",
            r"(?:lower|better)[^.]{0,35}(?:figure|price|quote)[^.]{0,45}elsewhere",
            r"제3자[^.]{0,35}(?:더\s*)?유리한[^.]{0,25}(?:조건|가격)",
            r"(?:타|다른)\s*거래처[^.]{0,35}(?:낮은|유리한)\s*(?:가격|조건)",
            r"most favou?red", r"no less favou?rable",
            r"price lower than that (offered|charged)",
            r"최혜[^.]{0,10}(대우|가격|조건)",
            r"불리하지\s*아니?하?[^.]{0,20}(가격|조건)",
            r"다른[^.]{0,20}(고객|거래처)[^.]{0,30}(보다|가격)[^.]{0,20}(유리|낮)"],
    fix="적용 **기간·물량·시장**을 좁히거나, 소급 환불 부분을 빼 달라고 하세요.",
)

_clause(
    "full_return", "불합격 시 전량 반품·비용 전가", "toxic",
    why="일부 불량으로 전량을 돌려받고 왕복 운임까지 무는 구조입니다.",
    risk="1% 불량으로 컨테이너 전체가 돌아오고 운임·보관료를 다 냅니다.",
    text_en="""(살펴볼 문구의 예)
If any part of the shipment fails inspection, the Buyer may reject the entire
shipment and the Seller shall bear all return freight, duties and storage.""",
    text_ko="reject the entire shipment 과 return freight 이 함께 나오면 이 조항입니다.",
    # 간격을 6 -> 20자로 넓히고 **부정 가드**를 붙였습니다. (2026-10-02)
    #
    # 전에는 거꾸로 돌았습니다.
    #   "전량 반품을 요구할 수 **없다**"        간격 1자 -> 잡힘  (오탐)
    #   "물품 전량을 매도인에게 반품할 수 있으며"  간격 8자 -> 놓침  (미탐)
    # 자연스러운 한국어는 "전량을 매도인에게 반품"처럼 사이에 말이 들어갑니다.
    # 그리고 "전량 반품을 요구할 수 없다"는 **우리를 보호하는** 문장입니다.
    detect=[r"(?:일부|한 ?건)[^.]{0,20}불합격[^.]{0,30}(?:전체|전부|전량)",
            r"(?:전체|전부)\s*로트",
            r"(?:send back|return)[^.]{0,45}(?:the )?(?:whole|entire)[^.]{0,25}(?:consignment|shipment|lot|quantity|delivery)",
            r"(?:entire|whole) lot[^.]{0,45}(?:refused|rejected|returned)",
            r"(?:전체|전부)\s*(?:로트|수량|물량|납품분)[^.]{0,25}반송",
            r"반송[^.]{0,15}(?:드는\s*)?(?:운임|비용|보관료)",
            r"reject the entire", r"return freight",
            r"전량[^.]{0,20}반품" + NO_NEG_KO,
            r"전부[^.]{0,20}반품" + NO_NEG_KO,
            r"반송\s*(운임|비용)[^.]{0,30}매도인"],
    # **'만족하지 않으면' 무조건 반품.** 조건절의 not 때문에 avoid 에 걸러져서
    # 극성을 규칙 안에서 봅니다 — 반품 바로 앞의 not 은 반품 금지입니다.
    # (절강성 고급인민법원 (2011) 浙商外终字 第16号, 2026-10-03)
    #   "if the buyer is not satisfied … can be returned unconditionally"
    strict=[r"(?<!not be )(?<!not )(?<!never be )(?:return(?:ed)?|sent\s+back)\s+"
            r"(?:\w+\s+){0,3}?unconditionally",
            r"\bunconditional(?:ly)?\s+returns?\b",
            r"(?:not\s+satisfied|dissatisfied|unsatisfied)[^.]{0,100}(?<!not be )(?<!not )"
            r"(?:return(?:ed)?|sent\s+back)\b(?![^.]{0,20}\bonly\s+(?:after|if)\b)",
            r"(?:만족하지\s*(?:않|못)|불만족)[^.]{0,60}반품"
            r"(?![^.]{0,20}(?:할\s*수\s*없|하지\s*못|불가|금지))"],
    fix="**불량분만 교체·감액**으로 바꾸고, 불합격 판정은 **선적지 검사기관**이 하도록 하세요.",
    avoid=NEGATION,
)



# ── 국가별 독소조항 ─────────────────────────────────────────────────────────
#
# 같은 문장도 나라에 따라 되돌릴 수 있는지가 다릅니다. 찾는 일은 나라와 무관하게
# 하고, 보여 줄 때만 도착국에 흔한 것을 앞세웁니다. (2026-10-02)

_clause(
    "cn_tech_transfer", "기술자료·도면 제공 의무 (중국)", "toxic",
    why="도면·BOM·공정서를 넘기면 같은 물건을 그쪽에서 만들 수 있습니다. "
        "중국은 특허·상표가 **선출원주의**라, 받은 쪽이 먼저 출원하면 되돌리기 어렵습니다.",
    risk="2년 뒤 같은 제품이 더 싸게 나오고, 우리가 침해 주장을 받는 쪽이 됩니다.",
    text_en="""(지울 문구의 예)
The Seller shall provide the Buyer with complete technical drawings, bills of
materials and manufacturing process documentation for the Products.""",
    text_ko="technical drawings · bill of materials · process documentation 을 "
            "**넘기라**고 적혀 있으면 이 조항입니다.",
    # 영어는 두 순서로 다 씁니다. 하나만 보면 절반을 놓칩니다. (2026-10-02)
    #   "technical drawings shall be provided"      <- 자료가 먼저
    #   "shall provide ... technical drawings"      <- 동사가 먼저
    # **방향을 봅니다.** (2026-10-02)
    #
    # 바이어가 제 도면을 우리에게 주는 것("The Buyer shall provide the Seller
    # with technical drawings")은 흔하고 위험이 없습니다. 전에는 그것도 짚었습니다.
    # 주는 쪽이 매도인이거나 받는 쪽이 매수인인 꼴만 봅니다.
    #
    # 영어는 낱말 순서가 둘입니다 — 자료가 먼저("drawings shall be provided"),
    # 동사가 먼저("shall provide ... drawings"). 둘 다 봅니다.
    detect=[r"(?:manufacturing|production|technical) documentation[^.]{0,60}(?:released|disclosed|provided|made available)",
            r"(?:released|disclosed|made available)[^.]{0,60}(?:manufacturing|production|technical) documentation",
            r"hand(?:s|ed)? over[^.]{0,70}(?:drawings?|documentation|know-how)",
            r"(?:released|disclosed|made available)[^.]{0,40}to the (?:buyer|purchaser)[^.]{0,70}(?:documentation|drawings?|know-how)",
            r"(?:설계)?도면[^.]{0,25}일체[^.]{0,40}(?:넘긴|넘겨|교부|제공)",
            r"(?:공정|기술)\s*(?:기술)?자료[^.]{0,40}(?:교부|제공|넘긴|넘겨)",
            # 자료가 먼저 — 주는 쪽/받는 쪽을 뒤에서 확인
            r"(technical|engineering) (drawings?|documentation|data|specifications?)"
            r"[^.]{0,60}(?:shall )?be (?:provided|furnished|delivered|disclosed)"
            r"[^.]{0,20}(?:by the seller|to the buyer)",
            # 동사가 먼저 — 매도인이 주는 꼴
            r"seller shall (?:\w+ ){0,3}?(?:provide|furnish|deliver|supply|disclose)"
            r"[^.]{0,80}(technical|engineering) (drawings?|documentation|data)",
            # 동사가 먼저 — 매수인이 받는 꼴
            r"(?:provide|furnish|deliver|supply|disclose)\s+(?:the\s+)?buyer\s+with"
            r"[^.]{0,80}(technical|engineering) (drawings?|documentation|data)",
            # 부품표·공정서도 같은 방향으로
            r"(?:bill of materials?|(?:manufacturing|production) process"
            r"[^.]{0,30}(?:documentation|know-how))"
            r"[^.]{0,60}(?:by the seller|to the buyer)",
            r"seller shall (?:\w+ ){0,3}?(?:provide|furnish|deliver|disclose)"
            r"[^.]{0,80}(?:bill of materials?|process documentation)",
            r"(?:provide|furnish|deliver|disclose)\s+(?:the\s+)?buyer\s+with"
            r"[^.]{0,80}(?:bill of materials?|process documentation)",
            # 국문 — 주는 쪽이 매도인이거나 받는 쪽이 매수인
            r"(도면|기술\s*자료|제조\s*공정\s*서|부품\s*표)[^.]{0,40}"
            r"(매수인|바이어)[^.]{0,20}(제공|교부|인도|제출)" + NO_NEG_KO,
            r"매도인[^.]{0,60}(도면|기술\s*자료|제조\s*공정\s*서|부품\s*표)"
            r"[^.]{0,40}(제공|교부|인도|제출)" + NO_NEG_KO],
    fix="도면은 **필요한 범위만** 주고, 비밀유지·역설계 금지·**용도 제한**을 함께 적습니다. "
        "금형 소유권은 우리에게 둡니다(이익조항 ip).",
    countries=("CN",),
    avoid=NEGATION,
)

_clause(
    "cn_trademark_buyer", "상표를 바이어 명의로 등록 (중국)", "toxic",
    why="우리 상표를 바이어 이름으로 등록하면 그 나라에서는 **바이어가 상표권자**입니다. "
        "중국은 선출원주의라 나중에 되찾는 데 몇 년이 걸립니다.",
    risk="거래를 끊으면 우리 상표로 우리 물건을 못 팝니다. 역수입도 막힙니다.",
    text_en="""(지울 문구의 예)
The Buyer shall register the Seller's trademarks in the Territory in the Buyer's
own name and shall be the sole registrant thereof.""",
    text_ko="register ... trademark ... in the Buyer's own name 이 나오면 이 조항입니다.",
    detect=[r"(?:등록|출원)\s*명의자[^.]{0,25}(?:바이어|매수인|대리점|판매점)",
            r"(?:브랜드|상표)[^.]{0,25}(?:등록|출원)\s*명의",
            r"(?:trade ?marks?|brand)[^.]{0,70}(?:filed|registered|stand)[^.]{0,45}in the (?:name of the )?(?:buyer|purchaser|distributor|agent)",
            r"in the (?:distributor|buyer|purchaser|agent)\'?s? (?:own )?name",
            r"(?:상표|브랜드)[^.]{0,35}(?:출원|등록)[^.]{0,25}(?:판매점|대리점|바이어|매수인)[^.]{0,12}명의",
            r"(?:등록|출원)\s*명의자[^.]{0,25}(?:바이어|매수인|대리점|판매점)",
            r"register[^.]{0,60}(trademarks?|trade marks?|brand)[^.]{0,60}"
            r"(in (its|the buyer'?s) own name|as (the )?(sole )?registrant)",
            r"(trademarks?|brand)[^.]{0,40}shall be registered[^.]{0,40}buyer",
            r"상표[^.]{0,40}(매수인|바이어|대리점)[^.]{0,20}명의[^.]{0,20}등록" + NO_NEG_KO],
    fix="상표는 **우리 명의로 우리가 직접** 출원·등록하고, 바이어에게는 **사용권만** 줍니다. "
        "거래 시작 전에 출원해 두는 것이 가장 안전합니다.",
    countries=("CN",),
    avoid=NEGATION,
)

_clause(
    "eu_gdpr_indemnity", "개인정보 과징금 전가 (EU · GDPR)", "toxic",
    why="GDPR 과징금 상한은 **전세계 연매출 4% 또는 2천만 유로 중 큰 금액**입니다. "
        "바이어가 제 잘못으로 맞은 과징금까지 우리가 물게 됩니다.",
    risk="우리 매출과 무관한 규모의 금액이 청구됩니다. 보험으로도 안 덮입니다.",
    text_en="""(지울 문구의 예)
The Seller shall indemnify and hold the Buyer harmless against any fines or
penalties imposed under the General Data Protection Regulation.""",
    text_ko="GDPR · data protection 과 indemnify · fines 가 함께 나오면 이 조항입니다.",
    # **방향을 봅니다.** (2026-10-02)
    #
    # "The Buyer shall indemnify the Seller against GDPR fines" 는 우리에게
    # 유리합니다. 전에는 방향을 안 봐서 이것도 독소로 짚었습니다.
    # 보호받는 쪽이 Buyer 인 꼴만 봅니다.
    detect=[r"hold[^.]{0,25}(?:the )?(?:buyer|purchaser)[^.]{0,15}harmless[^.]{0,90}(?:GDPR|General Data Protection|data protection)",
            r"(?:GDPR|General Data Protection|data protection)[^.]{0,90}(?:hold[^.]{0,25}(?:the )?(?:buyer|purchaser)[^.]{0,15}harmless|indemnif\w*[^.]{0,25}(?:the )?(?:buyer|purchaser)|reimbursed by the (?:seller|supplier)|borne by the (?:seller|supplier))",
            # 방향을 봐야 합니다. "The **Buyer** shall indemnify the **Seller**
            # against fines under the GDPR" 은 우리에게 유리합니다.
            r"(?:penalt|fine)[^.]{0,60}(?:GDPR|General Data Protection)[^.]{0,80}(?:borne by|reimbursed by|at the expense of)[^.]{0,25}(?:seller|supplier)",
            r"(?:과징금|제재금|과태료)[^.]{0,45}(?:매도인|공급자)[^.]{0,25}(?:부담|보전)",
            r"(?:GDPR|개인정보보호규정)[^.]{0,45}(?:위반\s*)?(?:과징금|제재금)",
            rf"(GDPR|General Data Protection Regulation)[^.]{{0,100}}{INDEMNIFY_BUYER}",
            rf"{INDEMNIFY_BUYER}[^.]{{0,100}}(GDPR|General Data Protection)",
            r"(GDPR|개인정보보호규정|일반\s*데이터\s*보호)[^.]{0,60}"
            r"(과징금|과태료)[^.]{0,40}(매도인|공급자)[^.]{0,20}(부담|배상)" + NO_NEG_KO],
    fix="우리가 **개인정보를 받지 않는다면** 이 조항은 뺍니다. 받는다면 책임을 "
        "**우리가 처리한 범위로 한정**하고 금액 상한을 둡니다.",
    countries=("EU",),
    avoid=NEGATION,
)

_clause(
    "us_class_action_pl", "제조물책임·집단소송 무한 면책 (미국)", "toxic",
    why="미국은 **집단소송**과 **징벌적 손해배상**이 있어 한 건이 회사 규모를 넘습니다. "
        "그걸 상한 없이 우리가 떠안는 조항입니다.",
    risk="송장 1만 달러짜리 거래에서 수백만 달러 소송의 방어비용까지 우리가 냅니다.",
    text_en="""(지울 문구의 예)
The Seller shall defend, indemnify and hold harmless the Buyer against all
product liability claims, including class actions, without limitation.""",
    text_ko="product liability · class action 과 indemnify · without limitation 이 "
            "함께 나오면 이 조항입니다.",
    # **방향을 봅니다.** 바이어가 우리를 면책하는 것은 유리한 조항입니다.
    detect=[r"hold[^.]{0,30}(?:the )?(?:purchaser|buyer)[^.]{0,20}harmless[^.]{0,90}(?:product liability|class action)",
            r"(?:defence|defense) costs[^.]{0,70}class action",
            r"(?:제조물\s*책임|집단\s*소송)[^.]{0,45}(?:면책|부담|방어비용)",
            rf"class action[^.]{{0,100}}{INDEMNIFY_BUYER}",
            rf"{INDEMNIFY_BUYER}[^.]{{0,100}}class action",
            r"product liability[^.]{0,80}(without limitation|unlimited|all claims)",
            r"(제조물\s*책임|집단\s*소송)[^.]{0,60}(매도인|공급자)[^.]{0,30}"
            r"(면책|배상|방어|부담)" + NO_NEG_KO],
    fix="면책 범위를 **우리 제조상 결함으로 한정**하고, 금액 상한과 "
        "**보험 한도 내**라는 조건을 붙입니다. 방어비용은 따로 다룹니다.",
    countries=("US",),
    avoid=NEGATION,
)

_clause(
    "ru_sanctions_warranty", "제재 보증·면책 (러시아 등 제재 대상국)", "toxic",
    why="제재 목록은 **수시로 바뀌고 우리가 통제할 수 없습니다.** 그런데 "
        "'제재에 걸리지 않음을 보증한다'고 적으면 바뀌는 것까지 우리 책임이 됩니다.",
    risk="거래 뒤 목록이 바뀌어 대금이 동결되면, 그 손해까지 우리가 뭅니다.",
    text_en="""(지울 문구의 예)
The Seller warrants that neither the Goods nor the transaction is subject to any
sanctions, and shall indemnify the Buyer for all consequences thereof.""",
    text_ko="sanctions 와 warrant · indemnify 가 함께 나오면 이 조항입니다.",
    detect=[r"(?:represents?|guarantees?)[^.]{0,50}(?:no sanction|sanction[- ]free)",
            r"(?:제재|수출통제)[^.]{0,30}(?:비해당|저촉)[^.]{0,30}(?:보증|담보)",
            r"sanctions?[^.]{0,80}(warrant|indemnif|hold harmless)",
            r"(warrant|represent)[^.]{0,60}not[^.]{0,40}subject to[^.]{0,40}sanctions?",
            r"(제재|수출\s*통제)[^.]{0,60}(보증|담보|면책|배상)" + NO_NEG_KO],
    fix="보증을 **계약 시점 기준**으로 한정하고, 뒤에 목록이 바뀌면 "
        "**불가항력 또는 해지 사유**가 되도록 적습니다.",
    countries=("RU", "BY", "IR", "KP", "SY", "CU"),
    # **방향이 뒤집힌 꼴은 우리에게 유리합니다.** 예문의 Seller ↔ Buyer 를 맞바꿔도
    # 걸려서, 아래 꼴은 거릅니다. (tests/test_contract_direction.py, 2026-10-03)
    avoid=INDEMNIFY_SELLER + (
           r"\b(?:buyer|purchaser)\s+(?:hereby\s+)?(?:warrants|represents|undertakes|certifies|confirms)",
           r"(?:매수인|바이어)(?:은|는)[^.]{0,20}(?:보증|확약|진술)"),
)

_clause(
    "gulf_agent_lock", "등록 대리인 독점·해지 제한 (걸프)", "toxic",
    why="걸프 국가들은 **상사대리인 등록제**가 있어, 등록된 대리인은 계약을 끊어도 "
        "독점과 보상을 주장할 수 있습니다. 계약서에 독점·해지 제한까지 적으면 더 묶입니다.",
    risk="대리인이 안 팔아도 다른 경로로 못 팝니다. 바꾸려면 합의금을 줘야 합니다.",
    text_en="""(지울 문구의 예)
The Agent shall have the exclusive right to import and distribute the Products
in the Territory. This Agreement may not be terminated without the Agent's
written consent.""",
    text_ko="exclusive right to import/distribute 와 may not be terminated 가 "
            "함께 나오면 이 조항입니다.",
    # **문장을 넘어갑니다.** (2026-10-02)
    #
    # 실제 계약서는 독점을 한 문장, 해지 제한을 다음 문장에 적습니다.
    # 다른 규칙이 쓰는 `[^.]` 는 문장에서 끊기므로 이 조항만 `.`(re.S) 로 넘깁니다.
    # 독점만 있고 해지가 자유로우면 짚지 않습니다 — 그건 흔한 독점 조항입니다.
    detect=[r"(?:독점\s*판매권|독점\s*수입권|독점\s*대리)[^.]{0,40}(?:승낙|동의)[^.]{0,25}없(?:이|으면)[^.]{0,40}(?:종료|해지)",
            r"(?:sole|exclusive)[^.]{0,50}(?:right to import|importation rights?).{0,200}(?:terminat|consent|approval)",
            r"(?:독점\s*수입권|독점\s*판매권)[^.]{0,90}(?:해지|종료)[^.]{0,25}(?:할 수 없|못|동의|승낙)",
            r"(sole|exclusive) (agent|distributor|right to (import|distribute))"
            r".{0,240}(may not be terminated|shall not be terminated|"
            r"without the (agent|distributor)'?s.{0,20}consent)",
            r"(독점|배타적)[^.]{0,30}(대리인|대리점|수입|판매)[^.]{0,80}"
            r"(해지[^.]{0,20}(할 수 없|불가|동의))"],
    fix="독점을 **기간·실적 조건부**로 하고(최소 구매량 미달 시 자동 해제), "
        "현지 **등록 전에** 조건을 확정합니다. 등록되면 바꾸기 어렵습니다.",
    countries=("GULF",),
)


# ── 바이어 유형별 독소조항 ──────────────────────────────────────────────────
#
# 대형 유통·브랜드 공급계약에서 되풀이되는 것들입니다. 나라와 무관합니다.

_clause(
    "retro_price_deduction", "소급 단가 인하·판촉비 공제", "toxic",
    why="이미 납품한 건까지 단가를 내리거나, 판촉비·진열비를 **대금에서 빼고** 넣습니다. "
        "우리는 받을 금액을 미리 알 수 없습니다.",
    risk="송장 100을 보내고 82가 들어옵니다. 다툴 근거가 계약서에 없습니다.",
    text_en="""(지울 문구의 예)
The Buyer may deduct any agreed rebate, markdown allowance or promotional
funding from any payment due, including retroactively.""",
    text_ko="rebate · markdown · allowance · promotional funding 과 deduct 가 "
            "함께 나오면 이 조항입니다.",
    detect=[r"(?:netted off|net(?:ted)? off|offset)[^.]{0,50}(?:against )?(?:any )?invoice",
            r"withhold[^.]{0,50}(?:trade )?allowance",
            r"(?:리베이트|판매장려금|장려금)[^.]{0,40}(?:차감|공제)",
            r"소급[^.]{0,25}단가",
            r"(rebate|markdown|allowance|promotional (funding|support)|co-?op)"
            r"[^.]{0,80}deduct",
            r"deduct[^.]{0,80}(rebate|markdown|allowance|promotional)",
            r"retroactive(ly)?[^.]{0,60}(price|discount|rebate)",
            r"소급[^.]{0,30}(단가|가격|할인)[^.]{0,30}(인하|적용|조정)" + NO_NEG_KO,
            r"(판촉|진열|행사)[^.]{0,20}(비용|분담금)[^.]{0,40}(공제|차감)" + NO_NEG_KO],
    fix="공제는 **미리 합의한 항목·금액만**, 그리고 **송장별로** 서면 통지 뒤에 하도록 "
        "바꿉니다. 소급 적용은 뺍니다.",
    avoid=NEGATION,
)

_clause(
    "chargeback_penalty", "납기 벌금을 대금에서 공제 (챠지백·OTIF)", "toxic",
    why="납기가 하루 늦거나 수량이 모자라면 주문액의 몇 %를 벌금으로 매기고, "
        "그걸 **다른 건 대금에서 빼** 갑니다.",
    risk="선사 스케줄이 밀려 생긴 지연까지 우리 벌금이 됩니다. 운임보다 벌금이 큽니다.",
    text_en="""(지울 문구의 예)
Late or short deliveries shall incur a chargeback of 5% of the order value,
which the Buyer may deduct from any invoice then outstanding.""",
    text_ko="chargeback · OTIF · on-time in-full 과 deduct 가 함께 나오면 이 조항입니다.",
    # `(?<!no )` 로 앞쪽 부정을 막습니다. (2026-10-02)
    #
    # "No chargebacks shall be permitted" 는 **좋은 문장**인데 전에는 짚었습니다.
    # 부정이 앞에 있어 뒤를 보는 가드로는 못 걸립니다. 파이썬 정규식은 길이가
    # 변하는 뒤돌아보기를 못 하지만 "no " 는 길이가 고정이라 됩니다.
    detect=[r"(?:수량\s*부족|납기\s*미준수|지연)[^.]{0,30}(?:벌과금|위약벌|위약금)[^.]{0,30}(?:송장|대금)",
            r"penalt\w*[^.]{0,70}set[- ]?off[^.]{0,45}invoice",
            r"on[- ]time in[- ]full[^.]{0,70}(?:deduction|deduct)",
            r"(?:위약벌|벌과금|위약금|과징)[^.]{0,40}(?:대금|송장)[^.]{0,25}(?:차감|공제)",
            r"(?<!no )charge-?backs?",
            r"on[- ]time in[- ]full|\bOTIF\b",
            r"(penalt|liquidated damages)[^.]{0,80}deduct[^.]{0,40}invoice",
            r"(벌금|위약금|지체상금)[^.]{0,60}(대금|송장)[^.]{0,30}(공제|차감)" + NO_NEG_KO],
    fix="벌금에 **상한**을 두고, **우리 책임인 지연에만** 걸리게 합니다(선사 지연·불가항력 제외). "
        "공제가 아니라 **별도 청구**로 바꿉니다.",
    avoid=NEGATION,
)

_clause(
    "audit_rights", "예고 없는 무제한 감사·실사", "toxic",
    why="언제든 예고 없이 우리 공장·장부·거래처를 들여다볼 수 있게 하는 조항입니다. "
        "원가와 다른 거래처 정보가 함께 드러납니다.",
    risk="원가가 드러나면 다음 협상에서 그만큼 깎입니다. 다른 바이어 정보가 새면 그쪽 계약 위반입니다.",
    text_en="""(지울 문구의 예)
The Buyer may audit the Seller's facilities, books and records at any time
without prior notice.""",
    text_ko="audit 과 at any time · without prior notice 가 함께 나오면 이 조항입니다.",
    detect=[r"(?:inspect|audit|access)[^.]{0,70}(?:books|accounts|premises|factor)[^.]{0,70}(?:without[^.]{0,25}(?:advance|prior)|at any time|on demand)",
            r"(?:사전\s*)?예고\s*없이[^.]{0,40}(?:열람|감사|실사|출입)",
            r"언제든지[^.]{0,40}(?:출입|실사|점검|열람)",
            r"audit[^.]{0,80}(at any time|without (prior )?notice)",
            r"(right to )?(audit|inspect)[^.]{0,60}(books|records|accounts)"
            r"[^.]{0,60}(at any time|without (prior )?notice)",
            r"(감사|실사|현장\s*점검)[^.]{0,60}(언제든지|사전\s*통지\s*없이)" + NO_NEG_KO,
            # 한국어는 어찌말이 앞에 옵니다 — "언제든지 ... 점검할 수 있다".
            # 뒤 순서만 보면 절반을 놓칩니다. (2026-10-02)
            r"(언제든지|사전\s*통지\s*없이|예고\s*없이)[^.]{0,60}"
            r"(감사|실사|현장\s*점검|점검|열람)" + NO_NEG_KO],
    fix="**연 1회·영업일·사전 서면통지**로 한정하고, 범위를 **이 계약 관련 자료만**으로 "
        "좁힙니다. 제3자 비밀정보는 제외하고, 감사인에게 비밀유지를 걸게 합니다.",
    # **방향이 뒤집힌 꼴은 우리에게 유리합니다.** 예문의 Seller ↔ Buyer 를 맞바꿔도
    # 걸려서, 아래 꼴은 거릅니다. (tests/test_contract_direction.py, 2026-10-03)
    avoid=(r"\b(?:seller|supplier)\s+(?:may|shall\s+have\s+the\s+right\s+to|is\s+entitled\s+to)\s+"
           r"(?:\w+\s+){0,2}?(?:audit|inspect|examine)",
           r"(?:buyer|purchaser|distributor)'?s?\s+(?:sales\s+)?(?:books|records|accounts)"),
)

_clause(
    "exclusive_no_moq", "독점 공급 의무 — 최소 구매량을 함께 보세요", "toxic",
    why="우리는 그 시장에서 다른 데 못 팔는데, 바이어는 **얼마를 사야 하는 의무가 없는** "
        "구조입니다. 한쪽만 묶입니다.",
    risk="바이어가 한 해 동안 거의 안 사도 우리는 다른 거래처를 못 잡습니다. 시장을 잃습니다.",
    text_en="""(지울 문구의 예)
The Seller shall supply the Products exclusively to the Buyer in the Territory
and shall not sell to any other party therein.""",
    text_ko="supply exclusively · shall not sell to any other 가 나오면 이 조항입니다. "
            "**최소 구매량(MOQ) 조항이 함께 있는지** 꼭 보세요.",
    detect=[r"deal(?:s|ing)? solely with[^.]{0,45}(?:buyer|purchaser)",
            r"refrain from (?:supplying|selling)[^.]{0,70}(?:third part|competitor|any other)",
            r"(?:매수인|바이어)\s*외에는[^.]{0,25}공급",
            r"역내[^.]{0,25}제3자[^.]{0,25}판매",
            r"(supply|sell)[^.]{0,40}exclusively[^.]{0,40}(to the )?buyer",
            r"shall not (sell|supply|distribute)[^.]{0,60}(any other|third part)"
            r"[^.]{0,40}(territory|region|country)",
            r"(독점|배타적)[^.]{0,20}(공급|판매)[^.]{0,30}(의무|한다|하여야)" + NO_NEG_KO],
    fix="독점을 **연간 최소 구매량과 묶고**, 미달하면 독점이 자동으로 풀리게 합니다. "
        "이익조항 min_order(최소 주문·취소 수수료)를 함께 넣으세요.",
    avoid=MINIMUM_PURCHASE,
)


# ── 돈을 못 받는 자리 · 원가가 새는 자리 ────────────────────────────────────
#
# 앞의 조항들이 '권리를 잃는' 쪽이라면, 이쪽은 **실어 놓고 돈을 못 받거나
# 원가가 새는** 쪽입니다. 실무에서 더 자주 터집니다. (2026-10-02)

_clause(
    "payment_fx_approval", "외환 승인·수입허가 조건부 결제", "toxic",
    why="대금 지급을 **상대국 중앙은행 승인이나 수입허가가 나오면** 하기로 한 조항입니다. "
        "승인은 우리가 손쓸 수 없고, 언제 날지도 모릅니다.",
    risk="물건은 이미 도착했는데 대금은 승인을 기다립니다. 외환 통제가 걸리면 몇 달, "
         "심하면 영영 못 받습니다. 그 사이 물건은 상대 손에 있습니다.",
    text_en="""(지울 문구의 예)
Payment shall be made subject to and upon receipt of approval from the Central
Bank and the issuance of the import licence.""",
    text_ko="subject to ... approval · upon receipt of the import licence 가 "
            "대금 조항에 붙어 있으면 이 조항입니다.",
    # 영문에도 부정 가드를 둡니다. (2026-10-02)
    # "Payment shall **not** be subject to any import licence" 를 짚었습니다.
    # 국문에는 NO_NEG_KO 가 있었는데 영문에는 없었습니다.
    detect=[r"remittance[^.]{0,50}conditional upon",
            r"(?:settlement|payment)[^.]{0,50}(?:follow|after)[^.]{0,50}(?:import permit|import licen|approval|clearance)",
            r"(?:송금|결제|지급)[^.]{0,40}(?:외국환|외환)[^.]{0,25}(?:당국|허가|승인)",
            r"수입승인[^.]{0,25}(?:난|받은|이후)",
            r"payment(?![^.]{0,20}\b(?:not|never)\b)[^.]{0,80}subject to[^.]{0,60}"
            r"(central bank|foreign exchange|fx|import licen[cs]e|approval)",
            r"(central bank|foreign exchange|import licen[cs]e)[^.]{0,60}"
            r"(approval|permit)[^.]{0,60}(payment|remit)",
            r"remittance[^.]{0,60}subject to[^.]{0,40}approval",
            r"(대금|지급|송금)[^.]{0,60}(외환|중앙은행|수입\s*허가|수입\s*승인)"
            r"[^.]{0,30}(승인|허가)[^.]{0,20}(후|조건|받은)" + NO_NEG_KO,
            r"(외환|중앙은행)[^.]{0,20}승인[^.]{0,40}(대금|지급|송금)" + NO_NEG_KO],
    fix="대금은 **선적서류 기준**으로 받습니다 — 취소불능 L/C 또는 선적 전 일부 선금. "
        "승인 지연은 **바이어 위험**으로 적고, 일정 기간이 지나면 지연이자와 해지권을 둡니다.",
    countries=("IN", "BD", "PK", "EG", "NG", "AR", "ET", "UZ", "VN", "DZ"),
    avoid=NEGATION,
)

_clause(
    "fx_risk_local", "현지 통화 결제 + 환율 위험 전가", "toxic",
    why="대금을 상대국 통화로 받고, 환율이 움직인 손해까지 우리가 지는 조항입니다. "
        "통화가 크게 흔들리는 나라에서는 받는 순간 값이 줄어 있습니다.",
    risk="송장일과 입금일 사이에 통화가 20% 빠지면 그만큼 그냥 손해입니다. "
         "마진이 10%면 팔수록 손해입니다.",
    text_en="""(지울 문구의 예)
Payment shall be made in the local currency at the exchange rate prevailing on
the invoice date, and the Seller shall bear any exchange rate fluctuation.""",
    text_ko="local currency 와 exchange rate ... Seller shall bear 가 함께 나오면 "
            "이 조항입니다.",
    detect=[r"local currency[^.]{0,90}(?:currency risk|exchange risk|carries the)",
            r"devaluation[^.]{0,70}(?:seller|supplier)\'?s? account",
            r"환차손[^.]{0,25}(?:매도인|공급자)",
            r"통화[^.]{0,25}(?:가치\s*)?하락[^.]{0,45}(?:공급자|매도인)[^.]{0,25}(?:부담|감수)",
            r"(exchange rate|currency)[^.]{0,80}"
            r"(seller shall bear|borne by the seller|at the seller'?s risk)",
            r"seller shall bear[^.]{0,60}(exchange|currency|devaluation)",
            r"(환율|환차손|환\s*변동)[^.]{0,60}(매도인|공급자)[^.]{0,20}"
            r"(부담|책임|위험)" + NO_NEG_KO,
            r"(매도인|공급자)[^.]{0,30}(환율|환차손|환\s*변동)[^.]{0,20}부담" + NO_NEG_KO],
    fix="**미국 달러 등 기축통화로** 받고, 환율 기준일을 **입금일이 아니라 송장일**로 "
        "박습니다. 현지 통화로 받아야 하면 **환율 변동 구간을 넘으면 단가를 다시 정한다**를 "
        "함께 넣습니다(이익조항 price_adjust).",
    countries=("TR", "AR", "EG", "NG", "BR", "ID", "VN", "IN", "ZA", "RU"),
    avoid=NEGATION,
)

_clause(
    "recall_cost", "리콜·고객 보상 비용 전가", "toxic",
    why="리콜은 물건 값이 아니라 **회수·폐기·고객 보상·광고**에 돈이 듭니다. "
        "그걸 상한 없이 우리가 떠안는 조항입니다.",
    risk="10만 달러짜리 납품 건에서 리콜 비용이 수백만 달러가 됩니다. "
         "바이어가 자발적으로 하는 리콜까지 우리가 내게 됩니다.",
    text_en="""(살펴볼 문구의 예)
The Seller shall bear all costs of any recall, including retrieval, destruction,
customer compensation and public notice, whether voluntary or mandated.""",
    text_ko="recall 과 all costs · Seller shall bear 가 함께 나오면 이 조항입니다. "
            "**voluntary(자발적)** 가 들어 있는지 꼭 보세요.",
    # **한정·상한이 있으면 뺍니다.** (2026-10-02)
    #
    # "shall bear recall costs caused **solely** by the Seller's defect, **up to**
    # the invoice value" 는 우리가 권하는 좋은 꼴입니다. 그걸 독소로 짚으면
    # 고친 조항을 다시 지우게 됩니다.
    detect=[r"(?:seller|supplier)[^.]{0,40}(?:funds?|finances?|pays? for)[^.]{0,60}(?:recall|withdrawal)",
            r"(?:product )?(?:withdrawal|recall)[^.]{0,90}(?:falls on|borne by|funded by|met by)[^.]{0,35}(?:seller|supplier)",
            r"회수\s*조치[^.]{0,45}비용[^.]{0,35}(?:매도인|공급자)",
            r"recall(?![^.]{0,160}" + RECALL_CAPPED + r")[^.]{0,100}"
            r"(all costs|costs and expenses|seller shall bear|"
            r"borne by the seller|at the seller'?s (cost|expense))",
            r"(seller shall bear|borne by the seller)"
            r"(?![^.]{0,160}" + RECALL_CAPPED + r")[^.]{0,80}recall",
            r"(리콜|회수\s*조치)[^.]{0,80}(매도인|공급자)[^.]{0,20}"
            r"(부담|비용|책임)" + NO_NEG_KO,
            r"(매도인|공급자)[^.]{0,40}(리콜|회수)[^.]{0,30}비용[^.]{0,20}부담" + NO_NEG_KO],
    fix="**우리 결함이 원인인 리콜로 한정**하고 금액 상한과 **보험 한도 내**를 붙입니다. "
        "자발적 리콜은 바이어가 단독으로 결정하지 못하게, **사전 협의**를 넣습니다.",
    countries=("JP", "US", "EU", "AU", "CA", "GB"),
    avoid=NEGATION,
)

_clause(
    "inspection_buyer_sole", "합격 판정을 바이어가 단독으로", "toxic",
    why="검사 합격·불합격을 바이어가 **혼자, 최종적으로** 정하는 조항입니다. "
        "기준이 계약서에 없으면 사실상 바이어 마음입니다.",
    risk="시장이 나빠지면 '품질 미달'로 값을 깎거나 받지 않습니다. 다툴 근거가 없습니다.",
    text_en="""(지울 문구의 예)
The Buyer's inspection and determination of conformity shall be final, conclusive
and binding on the Seller.""",
    text_ko="inspection ... shall be final · sole discretion 이 검사 조항에 "
            "붙어 있으면 이 조항입니다.",
    # **판정하는 쪽이 매수인인 꼴만 봅니다.** (2026-10-02)
    #
    # 전에는 "the determination of **SGS** at the port of loading shall be final"
    # 도 짚었습니다. 그런데 이 조항의 fix 가 권하는 해결책이 바로 "제3 검사기관
    # (SGS·BV)이 정하도록 하세요" 입니다. **우리가 권한 해결책을 우리가 독소라고
    # 한 것**입니다. 그 말을 들은 사람은 고친 조항을 다시 지웁니다.
    detect=[r"(?:바이어|매수인)[^.]{0,25}(?:검수|검사)\s*결과[^.]{0,30}최종",
            r"최종적이며[^.]{0,30}(?:매도인|공급자)[^.]{0,20}구속",
            r"acceptance[^.]{0,45}rests[^.]{0,45}(?:buyer|purchaser)",
            r"(?:buyer|purchaser)[^.]{0,25}alone[^.]{0,45}determin",
            r"(?:합격|검수)[^.]{0,40}(?:매수인|바이어)[^.]{0,25}(?:판단|결과)",
            r"이의를?\s*제기할\s*수\s*없",
            r"buyer'?s?\s+(inspection|determination|decision|judg(e)?ment)"
            r"[^.]{0,80}(shall be )?(final|conclusive|binding)",
            r"(inspection|determination|decision)\s+(?:by|of)\s+the\s+buyer"
            r"[^.]{0,80}(shall be )?(final|conclusive|binding)",
            r"buyer'?s (sole|absolute) discretion[^.]{0,80}"
            r"(inspect|conformity|accept|reject|quality)",
            r"(inspect|conformity|accept|reject|quality)[^.]{0,80}"
            r"buyer'?s (sole|absolute) discretion",
            r"(검사|검수|합격|불합격)[^.]{0,60}(매수인|바이어)[^.]{0,30}"
            r"(단독|최종|임의)[^.]{0,20}(판단|결정|정한)" + NO_NEG_KO,
            r"(매수인|바이어)[^.]{0,30}(단독|최종)[^.]{0,20}(판단|결정)"
            r"[^.]{0,40}(검사|합격|품질)" + NO_NEG_KO,
            # **도착지·수입국 검사기관을 최종으로** 정한 꼴. 매도인이 진 판례입니다.
            # (CIETAC 심천 1999.4.7 — 광동 수출입상품검험국 증명서 "final and
            # binding") 선적지 검사가 최종인 꼴은 우리에게 유리하므로 도착지 말이
            # **최종보다 앞에** 와야 합니다. (2026-10-03)
            r"(?:at\s+(?:the\s+)?(?:port\s+of\s+)?(?:destination|discharge|unloading)"
            r"|import\w*\s+(?:and\s+export\s+)?commodit\w*\s+inspection|\bCIQ\b"
            r"|buyer'?s?\s+country)"
            r"[^.]{0,160}(?<!not )(?:(?:shall\s+be|is|are)\s+(?:deemed\s+)?(?:final|conclusive)\b"
            r"|final\s+and\s+(?:binding|conclusive))"],
    fix="합격 기준을 **별지에 숫자로** 박고, 다툼이 생기면 **제3 검사기관(SGS·BV 등)**이 "
        "정하도록 합니다. 검사는 **선적지에서** 하도록 하세요 — 도착지 검사는 반송 위험을 "
        "우리가 집니다.",
)

_clause(
    "spec_change_no_price", "규격을 바꿀 수 있는데 단가는 그대로", "toxic",
    why="바이어가 규격·포장·라벨을 일방적으로 바꿀 수 있는데 **단가와 납기는 그대로**인 "
        "조항입니다. 바뀐 만큼 원가가 오르는데 받는 돈은 같습니다.",
    risk="포장 규격이 바뀌어 금형을 다시 파고, 남은 자재는 버립니다. 그 비용을 우리가 냅니다.",
    text_en="""(지울 문구의 예)
The Buyer may change the specifications, packaging or labelling at any time, and
such change shall not affect the price or the delivery date.""",
    text_ko="change the specifications ... shall not affect the price 가 나오면 "
            "이 조항입니다.",
    detect=[r"(?:사양|규격|디자인)\s*변경[^.]{0,30}단가[^.]{0,25}(?:종전|동일|그대로|변동\s*없)",
            r"(?:revise|amend|change|modify)[^.]{0,50}(?:drawings?|artwork|design|specification)[^.]{0,90}price[^.]{0,40}(?:remains? unchanged|shall not)",
            r"(?:design|specification)[^.]{0,35}(?:amendments?|changes?)[^.]{0,70}(?:not give rise|no)[^.]{0,35}price",
            r"사양\s*변경[^.]{0,40}단가[^.]{0,25}(?:종전|동일|그대로)",
            r"(?:디자인|규격|사양)\s*(?:수정|변경)[^.]{0,50}(?:가격|단가)\s*인상[^.]{0,25}(?:아니|않)",
            r"(change|modify|amend)[^.]{0,60}(specification|packaging|labell?ing|design)"
            r"[^.]{0,120}(shall not affect|without any (change|adjustment) (in|to) the )"
            r"[^.]{0,30}(price|cost)",
            r"(specification|packaging|labell?ing)[^.]{0,60}"
            r"(change|modif)[^.]{0,80}no (price|cost) (change|adjustment|increase)",
            r"(규격|포장|라벨|디자인)[^.]{0,40}(변경|수정)[^.]{0,80}"
            r"(단가|가격|대금)[^.]{0,30}(변경|조정|인상)[^.]{0,10}(없|않|아니)",
            r"(매수인|바이어)[^.]{0,40}(규격|포장|라벨)[^.]{0,20}(변경|수정)"
            r"[^.]{0,60}(단가|가격)[^.]{0,20}(동일|그대로|불변)"],
    fix="규격을 바꾸면 **단가와 납기를 다시 정한다**를 함께 적습니다. 남은 자재·금형 "
        "폐기 비용은 **바이어 부담**으로 박습니다. 변경은 **서면 합의**로만 하게 하세요.",
    # **방향이 뒤집힌 꼴은 우리에게 유리합니다.** 예문의 Seller ↔ Buyer 를 맞바꿔도
    # 걸려서, 아래 꼴은 거릅니다. (tests/test_contract_direction.py, 2026-10-03)
    avoid=(r"^(?![^.]*\b(?:buyer|purchaser)\s+may\b)[^.]*\b(?:seller|supplier)\s+may\s+"
           r"(?:\w+\s+){0,2}?(?:change|modify|alter|amend)",
           r"^(?![^.]*(?:매수인|바이어)[^.]{0,20}변경할\s*수)[^.]*(?:매도인|공급자)(?:은|는)[^.]{0,40}"
           r"변경할\s*수\s*있"),
)

_clause(
    "tooling_free", "금형·치공구를 무상으로 요구", "toxic",
    why="금형과 치공구를 우리 돈으로 만들어 **무상으로 제공**하라는 조항입니다. "
        "선투자를 우리가 다 하고, 물량 보장은 없습니다.",
    risk="금형에 수천만 원을 넣었는데 주문이 몇 백 개로 끝납니다. "
         "금형을 바이어가 가져가면 다른 공장에서 같은 물건을 만듭니다.",
    text_en="""(살펴볼 문구의 예)
All tooling, moulds and jigs required for the Products shall be provided by the
Seller free of charge and shall become the property of the Buyer.""",
    text_ko="tooling/moulds 와 free of charge · at no cost 가 함께 나오면 이 조항입니다. "
            "**소유권이 누구에게 가는지** 함께 보세요.",
    detect=[r"(?:seller|supplier)[^.]{0,40}bears?[^.]{0,40}(?:entire|whole|full|all)[^.]{0,20}cost[^.]{0,50}(?:jigs?|dies|moulds?|molds?|tooling)",
            r"(?:moulds?|molds?|tooling|jigs?|dies|fixtures?)[^.]{0,90}(?:at (?:its|the seller\'?s|their) own expense|seller bears|bears? the (?:entire|whole) cost)",
            r"(?:금형|치공구|지그)[^.]{0,40}(?:제작비|비용)[^.]{0,40}(?:매도인|공급자)[^.]{0,25}(?:부담|전액)",
            r"자비로[^.]{0,25}(?:제작|공급|제공)",
            r"(tooling|moulds?|molds?|jigs?|dies)[^.]{0,100}"
            r"(free of charge|at no cost|without charge|no charge to the buyer)",
            r"(free of charge|at no cost)[^.]{0,80}(tooling|moulds?|molds?|jigs?)",
            r"(금형|치공구|사출\s*금형|지그)[^.]{0,60}(무상|무료)[^.]{0,30}"
            r"(제공|공급|제작)" + NO_NEG_KO,
            r"(무상|무료)[^.]{0,30}(금형|치공구|지그)[^.]{0,30}(제공|공급|제작)" + NO_NEG_KO],
    fix="금형비는 **별도로 청구**하거나, 무상으로 하려면 **최소 물량을 보장**받고 "
        "미달 시 금형비를 청구할 수 있게 합니다. **소유권은 우리에게** 두세요 "
        "(이익조항 ip · 독소조항 ip_assignment 를 함께 보세요).",
    countries=("CN", "VN", "IN", "ID"),
    avoid=NEGATION + BUYER_SUPPLIES,
)


# ── 필수조항 보탬 ───────────────────────────────────────────────────────────
#
# **필수의 '찾기'는 독소와 뜻이 다릅니다.** 독소는 있으면 지우라는 말이고,
# 필수는 없으면 넣으라는 말입니다. 그래서 필수의 오탐은 "없는데 있다"가 되어
# 그 조항 없이 계약하게 만듭니다. 규칙을 좁게 씁니다. (2026-10-02)

_clause(
    "packing", "포장·화인 (Packing & Marking)", "must",
    why="포장 규격이 계약에 없으면, 깨져서 도착했을 때 '포장이 부실했다'는 말을 "
        "막을 수 없습니다. 화인(shipping mark)이 없으면 혼적 화물에서 우리 짐을 "
        "못 가립니다.",
    risk="해상 사고가 나도 보험사가 '포장 불량'을 들어 지급을 줄입니다. "
         "수입통관에서 화인 불일치로 검사 대상이 됩니다.",
    text_en="""5. PACKING AND MARKING
The Goods shall be packed in export standard seaworthy packing suitable for long
distance ocean transport. Each package shall bear the shipping marks specified in
Annex 2. Packing shall comply with ISPM 15 where wooden material is used.""",
    text_ko="**수출 표준 포장**임을 적고, 화인은 별지로 붙입니다. 목재 포장재를 "
            "쓰면 **ISPM 15(열처리·훈증)** 를 지켜야 합니다 — 안 지키면 도착지에서 "
            "반송됩니다.",
    detect=[r"packing (and|&) marking", r"shipping marks?",
            r"(export )?(standard )?seaworthy packing",
            r"\bISPM[\s-]?15\b",
            r"포장\s*(및|·)?\s*화인", r"수출\s*표준\s*포장",
            r"화인[^.]{0,30}(별지|부속서|표시)",
            # 오퍼 시트의 꼴 — "PACKING SPECIFICATIONS" 표, "EXPORT STANDARD
            # PACKED", "Packing: … 50 PCS per export carton". packing list(서류
            # 이름)는 포장 조건이 아니므로 걸리지 않게 둡니다. (2026-10-02)
            r"\bpacking\s+specifications?\b",
            r"\bexport\s+standard\s+pack(?:ed|ing)\b",
            r"\bpacking\b\s*:?[^.]{0,80}\b\d+\s*(?:pcs|pieces|units|sets)\s*"
            r"(?:/|per)\s*(?:export\s+)?cartons?\b"],
    fix="",
)

_clause(
    "confidential", "비밀유지 (Confidentiality)", "must",
    why="단가·원가·도면·거래처가 새면 다음 협상에서 그만큼 깎이고, 같은 물건이 "
        "다른 공장에서 나옵니다. 비밀유지 조항이 없으면 막을 근거가 없습니다.",
    risk="바이어가 우리 도면을 다른 공장에 보내 견적을 받아도 따질 수 없습니다.",
    text_en="""18. CONFIDENTIALITY
Each party shall keep confidential all technical, commercial and financial
information disclosed by the other party, shall use it only for the purpose of
this Contract, and shall not disclose it to any third party without prior written
consent. This obligation shall survive for three (3) years after termination.""",
    text_ko="**양쪽 모두**에게 걸리게 하고(한쪽만이면 이익조항이 아니라 독소입니다), "
            "**목적 제한**(이 계약 이행에만 쓴다)과 **존속기간**을 적습니다.",
    detect=[r"누설[^.]{0,20}(?:아니|않|못)",
            r"기밀",
            r"confidentiality\b", r"confidential information",
            r"keep confidential", r"non[- ]disclosure",
            # 조사가 끼어듭니다 — "비밀**을** 유지한다". \s 만으로는 안 걸립니다.
            r"비밀[^.]{0,6}유지", r"기밀[^.]{0,6}유지",
            r"비밀[^.]{0,20}(정보|자료)[^.]{0,30}(공개|누설)[^.]{0,20}(아니|않|금지)"],
    fix="",
    neg_ok=True,
)

_clause(
    "quantity_tol", "수량 과부족 허용 (More or Less Clause)", "must",
    why="산물·벌크·원단처럼 정확히 못 맞추는 물건이 있습니다. 허용 범위가 없으면 "
        "1%만 모자라도 계약 위반이 됩니다.",
    risk="컨테이너를 꽉 채우려다 2% 더 실었는데 초과분 대금을 못 받습니다. "
         "신용장 거래면 서류 불일치로 은행이 지급을 거절합니다.",
    text_en="""2. QUANTITY TOLERANCE
A tolerance of five percent (5%) more or less in quantity and amount shall be
acceptable, at the Seller's option, and shall be settled at the contract unit
price.""",
    text_ko="**±5% 같은 허용 범위**와, 그 차이를 **계약 단가로 정산**한다는 말을 "
            "함께 적습니다. 신용장 거래면 L/C 문구에도 같은 범위를 넣어야 합니다.",
    detect=[r"more or less", r"(quantity|amount) tolerance",
            r"tolerance of [^.]{0,20}(percent|%)[^.]{0,20}(more or less|in quantity)",
            r"(수량|중량)[^.]{0,20}과부족", r"과부족[^.]{0,20}(허용|인정)",
            r"(±|플러스마이너스)\s*\d{1,2}\s*%[^.]{0,30}(수량|중량)"],
    fix="",
)

_clause(
    "amendment", "계약 변경·통지 (Amendment & Notices)", "must",
    why="구두나 메신저로 합의한 것이 나중에 '그런 말 한 적 없다'가 됩니다. "
        "그리고 해지·클레임 통지는 **어디로 어떻게** 보내야 유효한지가 적혀 있어야 합니다.",
    risk="담당자끼리 주고받은 메일이 계약 변경인지 아닌지로 다툽니다. "
         "해지 통지를 보냈는데 '못 받았다'고 하면 그 기간이 날아갑니다.",
    text_en="""19. AMENDMENT AND NOTICES
No amendment to this Contract shall be effective unless made in writing and
signed by the authorised representatives of both parties. All notices shall be
given in writing to the addresses set out below, and shall be deemed received
three (3) business days after dispatch by courier or upon confirmed email receipt.""",
    text_ko="**서면 + 서명**으로만 변경되게 하고, 통지는 **주소·방법·도달 간주 시점**을 "
            "적습니다. 메일로 한다면 '수신 확인'까지 적어야 다툼이 없습니다.",
    detect=[r"no (amendment|modification|variation)[^.]{0,60}(unless|except)"
            r"[^.]{0,40}(writing|written)",
            r"(amendment|modification)[^.]{0,40}in writing[^.]{0,40}signed",
            r"notices? shall be (given|made|sent)[^.]{0,40}(in writing|to the address)",
            r"(계약|본\s*계약)[^.]{0,20}변경[^.]{0,40}서면[^.]{0,30}(합의|서명)",
            r"통지[^.]{0,40}(서면|주소)[^.]{0,30}(한다|하여야|발송)",
            # "Changes require mutual written agreement." — 실물 오퍼의 꼴.
            # "revised **dates** require …" 는 날짜만의 이야기라 세지 않습니다. (2026-10-02)
            r"\b(?:changes?|amendments?|modifications?|variations?)\b"
            r"(?:\s+to\s+(?:this|the)\s+(?:contract|offer|agreement|order))?\s+"
            r"(?:shall\s+|will\s+)?(?:requires?|be\s+subject\s+to)\s+(?:the\s+)?"
            r"(?:mutual\s+)?(?:prior\s+)?written\s+(?:agreement|consent)"],
    fix="",
)


# ── 이익조항 보탬 ───────────────────────────────────────────────────────────
#
# 독소를 지우라고만 하면 반쪽입니다. **우리가 넣어야 할 것**도 알려 줍니다.
# 아래 넷은 독소조항과 짝입니다 — 상대가 넣자고 하는 것의 반대편입니다.
#     no_set_off   <-> buyer_set_off
#     claim_period <-> open_warranty
#     exit_buyback <-> termination_at_will
#     buyer_design_ip <-> ip_assignment

_clause(
    "suspend_delivery", "대금 연체 시 선적 중단권 (Suspension)", "gain",
    why="앞 선적 대금이 안 들어왔는데 다음 선적을 계속하면, 떼이는 금액만 커집니다. "
        "멈출 권리가 계약에 있어야 멈춰도 계약 위반이 아닙니다.",
    risk="없으면 연체 중에도 계속 실어야 하고, 멈추면 **우리가** 위반이 됩니다.",
    text_en="""(넣을 문구의 예)
If any payment is overdue by more than fifteen (15) days, the Seller may suspend
further shipments and production without liability, until all overdue amounts
have been received.""",
    text_ko="**연체 일수**를 박고(예: 15일), 그동안의 **지연에 책임을 지지 않는다**는 "
            "말을 함께 넣습니다. 그래야 납기 지연 벌금을 안 뭅니다.",
    detect=[r"withhold[^.]{0,80}deliver",
            r"(?:출하|선적|납품|공급)[^.]{0,30}(?:보류|중단|정지)",
            r"suspend[^.]{0,80}(shipment|delivery|production)",
            r"(withhold|stop)[^.]{0,40}(further )?(shipment|delivery)"
            r"[^.]{0,60}(overdue|unpaid|payment)",
            r"(대금|지급)[^.]{0,30}(연체|지연)[^.]{0,60}(선적|출하|생산)"
            r"[^.]{0,20}(중단|보류|정지)",
            # 실물 꼴 (2026-10-02) — 이미 있는데 '넣으세요'라고 했습니다.
            #   "shipment shall not be required until the corresponding credit is operative"
            #   "Shipment by April 19, subject to receipt of deposit and balance"
            #   "Production begins upon receipt of full payment"
            r"(?:shipment|delivery)\s+shall\s+not\s+be\s+required\s+until[^.]{0,80}(?:credit|payment|paid)",
            r"\bnot\s+(?:be\s+)?(?:obliged|obligated|required)\s+to\s+(?:ship|deliver|make\s+shipment)"
            r"[^.]{0,80}until",
            r"(?:shipment|production|dispatch|delivery)[^.]{0,60}(?:subject to|upon|after|provided)\s+"
            r"(?:the\s+)?(?:receipt of|full)\s+(?:the\s+)?(?:full\s+)?(?:payment|deposit)",
            r"(?:대금|선수금|계약금)[^.]{0,20}(?:입금|수령)[^.]{0,10}(?:후|뒤)[^.]{0,20}(?:선적|생산|출하)"],
    fix="",
    neg_ok=True,
)

_clause(
    "no_set_off", "바이어의 상계 금지 (No Set-off)", "gain",
    why="상계를 막아 두지 않으면, 바이어가 다른 건의 클레임을 핑계로 이번 대금에서 "
        "빼고 넣습니다. 독소조항 buyer_set_off 의 반대편입니다.",
    risk="없으면 송장 100에 82가 들어와도 따질 근거가 약합니다.",
    text_en="""(넣을 문구의 예)
The Buyer shall pay all amounts in full without any set-off, counterclaim,
deduction or withholding of any kind.""",
    text_ko="**without any set-off, deduction or withholding** 를 대금 조항에 "
            "한 줄 넣습니다. 짧지만 힘이 셉니다.",
    detect=[r"free of[^.]{0,60}(?:counterclaim|withholding|set[- ]?off|deduction)",
            r"without any (set[- ]?off|deduction|withholding)",
            r"no set[- ]?off[^.]{0,40}(deduction|counterclaim|withholding)",
            r"(상계|공제)[^.]{0,30}(없이|아니하고)[^.]{0,30}(전액|지급)",
            r"(매수인|바이어)[^.]{0,30}(상계|공제)[^.]{0,20}(할 수 없|하지 못|금지)"],
    fix="",
    neg_ok=True,
)

_clause(
    "claim_period", "클레임 기한 (Claim Period)", "gain",
    why="하자 통지 기한이 없으면 1년 뒤에도 클레임이 들어옵니다. "
        "독소조항 open_warranty 의 반대편입니다.",
    risk="없으면 재고가 안 팔릴 때 '품질 문제'로 뒤늦게 반품이 들어옵니다. "
         "그때는 증거도 남아 있지 않습니다.",
    text_en="""(넣을 문구의 예)
Any claim shall be notified in writing within thirty (30) days after arrival at
the port of destination, together with an inspection report issued by an
internationally recognised surveyor. Claims notified later shall be deemed waived.""",
    text_ko="**도착 후 30일** 같은 기한을 박고, **제3 검사기관 보고서**를 함께 내게 "
            "합니다. 기한이 지나면 **포기한 것으로 본다**까지 적어야 닫힙니다.",
    detect=[r"(?:claim|notif)[^.]{0,80}within[^.]{0,30}(?:seven|ten|fourteen|fifteen|twenty|thirty|sixty|ninety)\s+days",
            r"claims?[^.]{0,80}within[^.]{0,20}\(?\d{1,3}\)?[^.]{0,20}days",
            r"(claim|notification)[^.]{0,60}deemed waived",
            r"(클레임|이의|하자)[^.]{0,40}\d{1,3}\s*일[^.]{0,30}(이내|내에)"
            r"[^.]{0,30}(통지|서면)",
            r"(기한|기간)[^.]{0,20}(지나|경과)[^.]{0,30}(포기|소멸)[^.]{0,20}(간주|본다)",
            # 법원이 유효하다고 본 문구 셋 (2026-10-03) — complaint · notice of
            # defects 로 쓰고 숫자로 적습니다. 선적 통지("notify … of the shipment
            # within 7 days")와 섞이지 않게 **하자·클레임 말**에 묶습니다.
            #   Tokyo District Court 2020.12.8 · OLG Saarbrücken 1993 · Arnhem 2009
            # 실제 계약서에서 "불만은 90 일 안에 종결", "하자는 30 일 안에 수리" 가
            # 걸려서, 클레임을 **내는** 동사가 있어야 합니다.
            r"(?:complain\w*|claims?|notice\s+of\s+(?:defects?|non-?conformit\w*)|defects?|rejections?)"
            r"[^.]{0,120}\b(?:made|raised|notif\w*|reported|submitted|given|lodged|filed|asserted|occur)\b"
            r"[^.]{0,60}within\s+\(?\d{1,3}\)?\s*(?:working\s+|business\s+|calendar\s+)?days"],
    fix="",
)

_clause(
    "lc_deadline", "신용장 개설 기한 (L/C Opening Deadline)", "gain",
    why="L/C 거래인데 개설 기한이 없으면, 우리는 원자재를 사 두고 기다리기만 합니다. "
        "L/C 가 안 열리면 선적도 못 하고 돈도 못 받습니다.",
    risk="생산을 시작한 뒤 L/C 가 안 열리면 재고가 그대로 남습니다. "
         "취소해도 받을 돈이 없습니다.",
    text_en="""(넣을 문구의 예)
The Buyer shall open an irrevocable Letter of Credit at sight in favour of the
Seller by 15 November 2026. If the L/C is not established by that date, the
Seller may cancel this Contract and claim the costs already incurred.""",
    text_ko="**개설 기한 날짜**를 박고, 미개설이면 **해지권과 기발생 비용 청구**까지 "
            "적습니다. 날짜가 없으면 아무 효력이 없습니다.",
    detect=[r"(?:open|establish)[^.]{0,80}(?:l/?c|letter of credit)",
            # "certificate **issued by** SGS" 의 by 는 기한이 아닙니다. (2026-10-03)
            r"(?:l/?c|letter of credit)[^.]{0,80}(?<!issued )(?<!advised )(?<!confirmed )"
            r"(?<!negotiated )(?<!payable )(?:\bby\b|before|no later than|not later than)",
            r"(?:신용장|L/?C)[^.]{0,60}(?:까지|전까지)[^.]{0,30}개설",
            # 한국어는 기한이 **앞**에 오기도 합니다 — "선적 30일 전까지
            # 신용장을 개설". 낱말 순서로 놓친 것이 **네 번째**입니다.
            r"(?:까지|전까지|이내)[^.]{0,40}(?:신용장|L/?C)[^.]{0,30}개설",
            r"(open|establish)[^.]{0,60}letter of credit[^.]{0,80}"
            r"(by|no later than|within)",
            r"(l/c|letter of credit)[^.]{0,60}(not (be )?(opened|established))"
            r"[^.]{0,60}(cancel|terminate)",
            r"(신용장|L/?C)[^.]{0,40}(개설|개설일)[^.]{0,40}(까지|이내|기한)",
            # 한국어는 기한이 **앞**에 옵니다 — "11월 15일까지 개설한다".
            # 낱말 순서로 놓친 것이 이번이 세 번째입니다. (2026-10-02)
            r"(신용장|L/?C)[^.]{0,40}(까지|이내|기한)[^.]{0,20}개설",
            r"(신용장|L/?C)[^.]{0,40}(미개설|개설되지)[^.]{0,40}(해지|취소)"],
    fix="",
    # **바이어가 여는** 신용장의 **기한**이어야 이익조항입니다. (2026-10-02)
    # 실물 보세가공 계약서에서 **우리가** 원사 대금 신용장을 여는 문장을 보고
    # '있다'고 했습니다. 정작 상대 신용장에는 기한이 없었습니다.
    avoid=(r"\bseller\s+shall\s+(?:open|establish|issue)",
           r"(?:매도인|공급자)(?:은|는|이|가)[^.]{0,30}(?:신용장|L/?C)[^.]{0,20}개설"),
    # 금액(USD 45,000)은 기한이 아닙니다. 날짜·일수 꼴만. 실물 제3조가 그랬습니다.
    require=((r"\d+\s*(?:\(\d+\)\s*)?(?:calendar\s+|business\s+|working\s+|banking\s+)?days",
              r"\b(?:19|20)\d{2}\b", r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?",
              r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\b", r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b",
              r"\d+\s*(?:일|월)",
              r"\b(?:one|two|three|five|seven|ten|fifteen|twenty|thirty|forty[- ]five|sixty)\s+(?:\(\d+\)\s*)?(?:calendar\s+|business\s+|banking\s+)?days",
              r"까지|이내|기한", r"cancel|terminat|해지|취소"),
             "신용장을 연다고만 적혀 있고 **언제까지** 열어야 하는지가 없습니다."),
)

_clause(
    "buyer_design_ip", "바이어 도면의 권리 보증 (Buyer's Design Indemnity)", "gain",
    why="바이어가 준 도면·상표로 만들었는데 제3자 특허·상표를 침해하면, 만든 우리가 "
        "먼저 걸립니다. 그 책임을 바이어에게 돌려 두어야 합니다.",
    risk="주문자상표(OEM) 생산에서 상표권 분쟁이 나면 **제조자**가 피고가 됩니다. "
         "세관에서 압류되면 그 손해도 우리 것이 됩니다.",
    text_en="""(넣을 문구의 예)
The Buyer warrants that the designs, drawings and trademarks supplied by it do
not infringe any third party rights, and shall indemnify and hold the Seller
harmless against any claim arising therefrom, including legal costs.""",
    text_ko="바이어가 준 **도면·상표**에 한정해서 **바이어가 보증하고 면책**하게 "
            "합니다. OEM·ODM 거래라면 꼭 넣으세요.",
    detect=[r"indemnif\w*[^.]{0,40}(?:the )?seller[^.]{0,100}(?:buyer'?s?\s+)?(?:design|specification|drawing|trademark)",
            r"buyer warrants[^.]{0,80}(design|drawing|trademark|specification)"
            r"[^.]{0,60}(not infringe|no infringement)",
            r"(design|drawing|trademark)[^.]{0,40}(supplied|provided) by the buyer"
            r"[^.]{0,100}(indemnif|hold the seller harmless)",
            r"(매수인|바이어)[^.]{0,40}(제공|지급)[^.]{0,20}(도면|디자인|상표)"
            r"[^.]{0,80}(보증|면책|배상)"],
    fix="",
)

_clause(
    "exit_buyback", "해지 시 재고·금형 인수 (Exit Buy-back)", "gain",
    why="해지당하면 그 바이어 전용으로 만든 재고와 금형이 그대로 남습니다. "
        "다른 데 팔 수 없는 물건입니다. 독소조항 termination_at_will 의 반대편입니다.",
    risk="전용 포장재·라벨이 붙은 재고는 폐기밖에 길이 없습니다. "
         "금형도 그 바이어 모델 전용이면 고철이 됩니다.",
    text_en="""(넣을 문구의 예)
Upon termination for any reason other than the Seller's breach, the Buyer shall
purchase all finished goods, work in progress and dedicated raw materials at the
contract price, and shall reimburse the unamortised tooling cost.""",
    text_ko="**완제품·재공품·전용 자재**를 계약 단가로 사 가게 하고, **금형 미상각분**도 "
            "받습니다. '우리 잘못으로 해지된 경우는 뺀다'를 함께 적으세요.",
    detect=[r"(upon|on) termination[^.]{0,120}"
            r"(buyer shall (purchase|buy|take over)|reimburse)",
            r"(finished goods|work in progress|raw materials?)[^.]{0,80}"
            r"(buyer shall (purchase|buy)|repurchase)",
            r"unamorti[sz]ed[^.]{0,40}(tooling|mould|mold)",
            r"해지[^.]{0,60}(재고|완제품|재공품|자재)[^.]{0,40}"
            r"(매수인|바이어)[^.]{0,20}(인수|매입|구매)",
            r"(금형|치공구)[^.]{0,40}(미상각|잔존)[^.]{0,30}(보전|지급|정산)"],
    fix="",
)


# ── 돈을 떼이는 자리 ────────────────────────────────────────────────────────
#
# 앞의 독소들이 '권리를 잃거나 원가가 새는' 쪽이라면, 이쪽은 **물건은 넘어갔는데
# 돈이 안 들어오는** 자리입니다. 한 번 터지면 되돌릴 방법이 거의 없습니다.
# (2026-10-02)

_clause(
    "docs_before_payment", "선적서류 원본을 대금 전에 인도", "toxic",
    why="선하증권(B/L) 원본은 **물건을 찾아가는 권리**입니다. 대금을 받기 전에 "
        "넘기면 상대가 물건을 찾아간 뒤 돈을 안 줄 수 있습니다.",
    risk="물건도 없고 돈도 없습니다. 이미 통관되어 팔린 뒤라 되찾을 수도 없습니다. "
         "소유권 유보 조항이 있어도 실제로 집행하기 어렵습니다.",
    text_en="""(지울 문구의 예)
The Seller shall send the original Bill of Lading and other shipping documents
directly to the Buyer by courier immediately after shipment.""",
    text_ko="original B/L ... directly to the Buyer 가 **대금 조항보다 앞서** 나오면 "
            "이 조항입니다. 'telex release' 나 'surrendered B/L' 도 같은 뜻입니다.",
    # **대금을 받은 뒤 넘기는 것은 좋은 꼴**입니다. 빼야 합니다. (2026-10-02)
    #   "released to the Buyer only after full payment has been received"
    detect=[r"원본\s*(?:운송|선적)?\s*서류[^.]{0,40}(?:바이어|매수인)[^.]{0,25}(?:직접|교부|송부|발송)",
            r"forward[^.]{0,50}(?:full set of )?original[^.]{0,40}documents?",
            r"original[^.]{0,45}transport documents?",
            r"(?:선하증권|운송서류|선적서류)\s*원본[^.]{0,45}(?:발송|교부|송부|직접)",
            r"original[^.]{0,40}(bill of lading|b/l|shipping documents?)"
            r"[^.]{0,80}(directly )?to the buyer"
            r"(?![^.]{0,60}(?:after|upon|against)[^.]{0,40}payment)",
            r"(telex release|surrender(ed)? b/?l|express release)"
            r"[^.]{0,80}(before|prior to)[^.]{0,40}payment",
            r"(send|dispatch|courier)[^.]{0,60}original[^.]{0,40}"
            r"(b/?l|bill of lading)[^.]{0,60}(immediately|upon shipment)",
            r"(선하증권|B/?L)\s*원본[^.]{0,60}(매수인|바이어)[^.]{0,30}"
            r"(직접|송부|교부|발송)" + NO_NEG_KO,
            r"(대금|결제)[^.]{0,20}(전|이전)[^.]{0,40}(선적서류|원본)[^.]{0,30}"
            r"(인도|교부|송부)" + NO_NEG_KO],
    fix="서류는 **은행을 거쳐** 보냅니다 — 신용장(L/C) 또는 추심(D/P). "
        "굳이 직접 보내야 하면 **대금 전액 선수금**을 받은 뒤에 보냅니다. "
        "B/L 수하인(consignee)은 'to order' 로 두세요.",
    avoid=NEGATION,
)

_clause(
    "lc_soft_clause", "우리가 못 맞추는 신용장 조건 (소프트 조항)", "toxic",
    why="신용장은 **서류가 조건과 맞아야** 은행이 돈을 줍니다. 그런데 조건 가운데 "
        "바이어가 서명해야 나오는 서류나, 바이어가 지정해야 정해지는 것이 섞여 있으면 "
        "**우리 힘으로 맞출 수 없습니다.**",
    risk="바이어가 검사증명서에 서명해 주지 않으면 서류가 불일치가 되고, "
         "은행은 지급을 거절합니다. 신용장이 사실상 무담보가 됩니다.",
    text_en="""(살펴볼 문구의 예)
Inspection certificate issued and signed by the Buyer's representative, whose
signature must correspond with the specimen held by the issuing bank, and
shipment to be effected only upon the Buyer's written nomination of the vessel.""",
    text_ko="신용장 조건에 **바이어가 서명·지정해야 나오는 서류**가 있으면 소프트 "
            "조항입니다. signed by the buyer · specimen signature · buyer's "
            "nomination 이 보이면 의심하세요.",
    detect=[r"선적[^.]{0,30}(?:바이어|매수인)[^.]{0,25}서면[^.]{0,20}지정",
            r"countersigned by[^.]{0,45}(?:buyer|purchaser)",
            r"신용장[^.]{0,45}(?:매수인|바이어)[^.]{0,25}서명",
            r"(signed|issued|countersigned) by[^.]{0,40}(the )?buyer'?s?"
            r"[^.]{0,40}representative",
            r"specimen signature[^.]{0,60}(issuing|advising) bank",
            r"(inspection|quality) certificate[^.]{0,60}"
            r"(signed|countersigned) by[^.]{0,30}buyer",
            r"(shipment|vessel)[^.]{0,60}buyer'?s? (written )?"
            r"(nomination|approval|instruction)",
            r"(신용장|L/?C)[^.]{0,60}(매수인|바이어)[^.]{0,30}(서명|지정|승인)"
            r"[^.]{0,30}(서류|증명서)",
            # ── 판례에 인용된 소프트 조항 (2026-10-03) ──
            # 개설의뢰인(applicant)·수입자(importer) 도 바이어입니다.
            r"(?:countersigned|signed|issued|stamped)\s+by[^.]{0,45}"
            r"(?:applicant|importer|opener)\b",
            # "Inspection Cert. Issued by MR. LIU YUE HONG of …" (대법원 2000다63691)
            # — 줄임표 마침표 때문에 [^.] 로는 못 건넙니다.
            r"\b(?:inspection|quality|acceptance|analysis)\s+cert(?:ificate)?\.?\s+"
            r"(?:issued|signed|stamped)\s+by\s+(?:mr|mrs|ms|miss|dr)\b",
            # 특정 개인 서명 (Gian Singh v. Banque de l'Indochine, PC 1974)
            r"certificate[^.]{0,30}signed\s+by[^.]{0,60}(?:holder\s+of|passport)",
            # 개설은행 전문으로 운송사를 지정 (Hamilton Bank v. Kookmin Bank, 2d Cir. 2001)
            r"(?:telex|swift|message|advice)\s+from\s+(?:the\s+)?issuing\s+bank[^.]{0,120}"
            r"(?:nominat|approv|authori[sz])\w*",
            r"\bnominat\w*\s+(?:the\s+)?(?:transporting|shipping|carrying)\s+(?:company|vessel|line)",
            # 개설의뢰인의 지급동의서·승인서 (대법원 2017다235036)
            r"(?:개설의뢰인|매수인|바이어|수입자)[^.]{0,20}(?:지급|결제)\s*(?:동의서|승인서|승낙서)",
            r"payment[^.]{0,40}(?:subject\s+to|upon|against|only\s+after|conditional\s+(?:up)?on)"
            r"[^.]{0,30}(?:applicant|buyer|importer)'?s?\s+(?:consent|approval|acceptance|authori[sz]ation)",
            r"(?:applicant|buyer|importer)'?s?\s+(?:payment\s+)?(?:consent|approval|authori[sz]ation)"
            r"\s+(?:to|for)\s+(?:the\s+)?payment"],
    # **"지급하지 않는다 … 승인하지 않으면"** — 부정이 조건의 뜻입니다. avoid 의
    # 부정 가드에 통째로 걸러지므로 규칙 안에서 봅니다.
    # (Hilaturas Miel v. Republic of Iraq, S.D.N.Y. 2008)
    strict=[r"(?:shall|will|may)\s+not\s+(?:make\s+any\s+|effect\s+any\s+)?(?:pay|payment|honou?r)"
            r"[^.]{0,80}\bunless\b[^.]{0,100}(?:approv|consent|authori[sz]|confirm)\w*"],
    fix="신용장 조건은 **우리가 혼자 만들 수 있는 서류**로만 채웁니다. "
        "검사증명서가 필요하면 **제3 검사기관(SGS·BV)** 발행으로 바꾸고, "
        "선박 지정이 필요하면 **개설 전에** 확정해 둡니다.",
    avoid=NEGATION,
)

_clause(
    "payment_retention", "하자가 없어도 대금 일부를 묶어 둠", "toxic",
    why="대금의 일정 비율을 '보증금' 명목으로 몇 달 동안 묶어 두는 조항입니다. "
        "하자가 없어도 그 돈은 안 들어옵니다.",
    risk="마진이 10%인데 10%를 묶으면 그 거래의 이익이 통째로 잠깁니다. "
         "묶인 돈은 흐지부지 안 주는 경우가 많습니다.",
    text_en="""(지울 문구의 예)
Ten percent (10%) of the invoice value shall be retained by the Buyer as a
performance guarantee for twelve (12) months after delivery.""",
    text_ko="retention · retained by the Buyer · performance guarantee 가 대금 "
            "조항에 붙어 있으면 이 조항입니다. **언제 돌려주는지**가 적혀 있는지 보세요.",
    detect=[r"(?:five|ten|fifteen|twenty|thirty)\s+percent[^.]{0,70}(?:held back|holdback|retained|retention)",
            r"대금[^.]{0,20}\d{1,2}\s*%[^.]{0,40}(?:보증|하자)[^.]{0,20}(?:경과|지난|후)",
            r"\d{1,2}\s*%[^.]{0,40}(?:보증기간|하자\s*기간)[^.]{0,25}(?:경과|지난|후)",
            r"\d{1,2}\s*(?:percent|%)[^.]{0,70}(?:held back|holdback|retained|retention)",
            r"(?:performance )?holdback",
            r"(?:하자보증|보증)\s*(?:금)?\s*명목[^.]{0,25}유보",
            r"(?:보증기간|하자\s*기간)[^.]{0,25}(?:경과|지난)\s*후[^.]{0,25}지급",
            r"(retention|retained|withheld)[^.]{0,60}"
            r"(\d{1,2}\s*(percent|%)|invoice value)[^.]{0,60}"
            r"(guarantee|warranty|security)",
            r"\d{1,2}\s*(percent|%)[^.]{0,40}(shall be )?retained by the buyer",
            r"(대금|송장)[^.]{0,30}\d{1,2}\s*%[^.]{0,40}"
            r"(유보|보류|예치)" + NO_NEG_KO,
            r"(하자\s*)?보증금[^.]{0,40}(공제|유보|보류)[^.]{0,30}"
            r"(개월|년|후)" + NO_NEG_KO],
    fix="유보 대신 **은행 보증서(P-Bond)** 로 바꿉니다 — 돈이 묶이지 않습니다. "
        "유보를 받아들여야 하면 **비율·기간·반환 조건**을 날짜로 박고, "
        "반환이 늦으면 **지연이자**가 붙게 하세요.",
    avoid=NEGATION,
)

_clause(
    "buyer_nominated_cost", "바이어가 지정하고 비용은 우리가", "toxic",
    why="운송사·보험사·검사기관을 바이어가 정하는데 비용은 우리가 내는 구조입니다. "
        "우리는 값을 비교할 수도, 바꿀 수도 없습니다.",
    risk="지정 포워더가 시세보다 비싸도 그대로 내야 합니다. 바이어와 그 포워더 "
         "사이에 리베이트가 있는 경우도 있습니다.",
    text_en="""(지울 문구의 예)
The Seller shall use the forwarder, carrier and insurer nominated by the Buyer,
and shall bear all costs and charges thereof.""",
    text_ko="nominated by the Buyer 와 Seller shall bear 가 함께 나오면 이 조항입니다.",
    # 주어가 문장 앞에 있으면 "seller shall bear" 가 붙어 나오지 않습니다.
    #   "The Seller shall use the forwarder nominated by the Buyer and
    #    **shall bear all costs** thereof."
    # 맨 "shall bear ... costs" 도 봅니다. (2026-10-02)
    detect=[r"(?:designated|nominated|appointed) by the (?:buyer|purchaser)[^.]{0,60}(?:pay|bear)[^.]{0,30}(?:the )?(?:premium|cost|fee|charge)",
            r"(?:appointed|designated|nominated)[^.]{0,45}(?:forwarder|carrier|insurer|surveyor)[^.]{0,90}(?:seller|supplier)\'?s? expense",
            r"(?:매수인|바이어)[^.]{0,25}지정[^.]{0,40}(?:선사|검사기관|포워더|보험사)[^.]{0,50}(?:매도인|공급자)",
            r"(nominated|designated|appointed) by the buyer[^.]{0,100}"
            r"(seller shall bear|at the seller'?s (cost|expense)|borne by the seller"
            r"|shall bear[^.]{0,20}(all )?costs?)",
            r"(seller shall bear|at the seller'?s (cost|expense))[^.]{0,100}"
            r"(nominated|designated) by the buyer",
            r"(매수인|바이어)[^.]{0,20}(지정|선정)[^.]{0,40}"
            r"(포워더|운송인|선사|보험사|검사기관)[^.]{0,60}"
            r"(매도인|공급자)[^.]{0,20}부담" + NO_NEG_KO],
    fix="지정은 받아들이되 **비용은 바이어 부담**으로 바꾸거나, 비용을 우리가 내면 "
        "**업체를 우리가 고르게** 합니다. 인코텀즈와도 맞춰야 합니다 — FOB 인데 "
        "목적지 비용을 우리가 내면 조건이 어긋납니다(독소 term_conflict).",
    avoid=NEGATION,
)

_clause(
    "one_way_nda", "비밀유지가 우리에게만 걸림", "toxic",
    why="비밀유지 의무가 **매도인에게만** 있고 바이어는 자유로운 조항입니다. "
        "우리 원가·도면은 묶이고, 바이어가 받은 정보는 아무 데나 쓸 수 있습니다.",
    risk="우리 도면이 다른 공장으로 가도 따질 수 없습니다. "
         "'서로' 가 아니라 '매도인은' 으로 적혀 있는지 보세요.",
    text_en="""(지울 문구의 예)
The Seller shall keep confidential all information received from the Buyer and
shall not disclose it to any third party.""",
    text_ko="**The Seller shall keep confidential** 처럼 한쪽만 적혀 있으면 "
            "이 조항입니다. Each party · both parties 로 바꿔야 합니다.",
    # **가드가 문장을 넘어가야 합니다.** (2026-10-02)
    #
    # 실제 계약서는 쌍방 의무를 두 문장으로 나눠 씁니다.
    #   "The Seller shall keep confidential ... from the Buyer.
    #    The Buyer shall likewise keep confidential ... from the Seller."
    # 다른 규칙이 쓰는 `[^.]` 는 첫 문장에서 끊겨 뒤 문장을 못 봅니다. 그래서
    # **쌍방인데 일방이라고** 짚었습니다. 이 가드만 `.`(re.S) 로 넘깁니다.
    detect=[r"(?:seller|supplier)[^.]{0,50}(?:undertakes to )?treat[^.]{0,45}confidential(?!.{0,320}(?:each party|both parties|mutual|buyer shall.{0,40}confidential))",
            r"(?:seller|supplier)[^.]{0,50}hold(?:s)? in confidence(?!.{0,320}(?:each party|both parties|mutual))",
            r"(?:매도인|공급자)[^.]{0,50}(?:비밀로|기밀을)[^.]{0,25}(?:유지|지)(?!.{0,320}(?:양\s*당사자|쌍방|상호))",
            r"seller shall (keep|treat|hold)[^.]{0,40}confidential"
            r"(?!.{0,320}(each party|both parties|mutual|reciprocal"
            r"|buyer shall.{0,40}confidential))",
            r"(매도인|공급자)[^.]{0,30}(비밀|기밀)[^.]{0,20}유지"
            r"(?!.{0,320}(양\s*당사자|쌍방|상호|매수인.{0,40}(비밀|기밀)))"],
    fix="**Each party / 양 당사자**로 바꿉니다. 바꿔 주지 않으면 그 자체가 신호입니다 — "
        "우리 정보를 쓸 생각이 있다는 뜻입니다.",
)

_clause(
    "non_compete_wide", "범위·기간이 넓은 경업금지", "toxic",
    why="'비슷한 제품을 어디에도 팔지 않는다'처럼 범위가 넓은 경업금지는 "
        "우리 사업 자체를 묶습니다. 기간까지 길면 다른 바이어를 못 잡습니다.",
    risk="그 바이어가 안 사도 우리는 다른 데 못 팝니다. 공장이 놀아도 어쩔 수 없습니다. "
         "독점 공급(exclusive_no_moq)과 겹치면 더 심해집니다.",
    text_en="""(지울 문구의 예)
The Seller shall not manufacture, sell or supply any similar or competing
products to any other party worldwide during the term and for three (3) years
thereafter.""",
    text_ko="similar or competing products · worldwide · thereafter 가 함께 나오면 "
            "이 조항입니다. **범위(지역·제품)와 기간**을 꼭 보세요.",
    detect=[r"전\s*세계[^.]{0,30}어디[^.]{0,40}(?:유사|경쟁)",
            r"refrain from (?:producing|manufacturing)[^.]{0,70}(?:comparable|similar|competing)",
            r"may not deal in[^.]{0,45}competing",
            r"(?:유사|경쟁)\s*제품[^.]{0,50}(?:공급|제조|취급)[^.]{0,25}(?:아니|않|못)",
            r"전\s*세계[^.]{0,50}(?:유사|경쟁)",
            r"shall not (manufacture|sell|supply|produce)[^.]{0,80}"
            r"(similar|competing|identical)[^.]{0,60}products?",
            r"non[- ]competition[^.]{0,80}(worldwide|any (other )?(party|territory))",
            r"(경업\s*금지|경쟁\s*제품)[^.]{0,80}(제조|판매|공급)"
            r"[^.]{0,20}(아니|않|못)",
            r"(유사|경쟁)\s*제품[^.]{0,60}(제3자|타사|다른)[^.]{0,30}"
            r"(판매|공급)[^.]{0,20}(아니|않|못|금지)"],
    fix="**지역·제품군·기간을 좁힙니다** — 그 바이어의 판매 지역, 그 바이어 모델에 "
        "한정, 계약 기간 중에만. 그리고 **최소 구매량과 묶어** 미달하면 풀리게 하세요.",
    # **방향이 뒤집힌 꼴은 우리에게 유리합니다.** 예문의 Seller ↔ Buyer 를 맞바꿔도
    # 걸려서, 아래 꼴은 거릅니다. (tests/test_contract_direction.py, 2026-10-03)
    avoid=(r"\b(?:buyer|purchaser|distributor)\s+shall\s+not\s+(?:\w+,?\s+){0,4}?"
           r"(?:manufacture|sell|supply|distribute|purchase|deal|market)",
           r"(?:매수인|바이어|대리점)(?:은|는)[^.]{0,60}(?:판매|제조|취급)하여서는\s*아니"),
)

_clause(
    "assignment_one_way", "양도가 바이어만 자유", "toxic",
    why="바이어는 계약을 마음대로 넘길 수 있는데 우리는 못 넘기는 조항입니다. "
        "상대가 누구로 바뀔지 모르는 채로 묶입니다.",
    risk="신용도가 낮은 회사로 넘어가도 우리는 계속 공급해야 합니다. "
         "그 회사가 부도나면 받을 돈이 날아갑니다.",
    text_en="""(지울 문구의 예)
The Buyer may assign this Contract to any affiliate or third party without the
Seller's consent. The Seller shall not assign without the Buyer's prior written
consent.""",
    text_ko="Buyer may assign ... without consent 와 Seller shall not assign 이 "
            "**함께** 나오면 이 조항입니다.",
    detect=[r"(?:바이어|매수인)[^.]{0,25}지위\s*이전[^.]{0,30}동의",
            r"(?:buyer|purchaser) may (?:transfer|assign)[^.]{0,70}(?:freely|without)",
            r"novation by the (?:buyer|purchaser)",
            r"(?:매수인|바이어)[^.]{0,40}자유로이[^.]{0,25}양도",
            r"(?:지위\s*이전|양도)[^.]{0,25}동의가?\s*필요\s*없",
            r"buyer may assign[^.]{0,80}without[^.]{0,40}"
            r"(seller'?s|prior)[^.]{0,20}consent",
            r"buyer may assign[^.]{0,200}seller shall not assign",
            r"(매수인|바이어)[^.]{0,40}(양도|이전)[^.]{0,30}(할 수 있|자유)"
            r"[^.]{0,200}(매도인|공급자)[^.]{0,40}(양도|이전)[^.]{0,20}(할 수 없|못|금지)"],
    fix="**양쪽 모두 상대 동의를 받게** 바꿉니다. 바이어의 계열사 양도를 허용하더라도 "
        "**바이어가 연대책임을 진다**는 말을 넣으세요.",
)

_clause(
    "cert_test_cost", "인증·시험·검사 비용 전가", "toxic",
    why="수입국 인증, 매 선적 시험, 공장 심사 비용을 모두 우리가 내는 조항입니다. "
        "인증은 한 번에 수천만 원이 들고, 바뀔 때마다 다시 듭니다.",
    risk="주문이 한 건인데 인증비가 주문액을 넘는 일이 생깁니다. "
         "인증 명의가 바이어 앞으로 나면 그 바이어와만 거래해야 합니다.",
    text_en="""(지울 문구의 예)
All costs of certification, testing and factory audits required in the Buyer's
country, including annual renewals, shall be borne by the Seller.""",
    text_ko="certification · testing · factory audit 과 borne by the Seller 가 "
            "함께 나오면 이 조항입니다. **인증 명의가 누구 앞인지**도 보세요.",
    detect=[r"(?:seller|supplier)[^.]{0,60}(?:pay|bear)[^.]{0,60}(?:conformity assessment|certification|type approval|homologation)",
            r"(?:적합성\s*평가|형식승인|인증|시험)\s*(?:비용|수수료)[^.]{0,30}(?:매도인|공급자)[^.]{0,20}(?:낸|부담|지급)",
            r"(?:homologation|type approval|conformity assessment)[^.]{0,90}(?:seller|supplier)",
            r"(?:형식승인|공장심사|적합성\s*평가)[^.]{0,45}(?:비용|수수료)[^.]{0,40}(?:매도인|공급자)",
            r"(certification|testing|test reports?|factory audit|inspection)"
            r"[^.]{0,100}(borne by the seller|at the seller'?s (cost|expense)|"
            r"seller shall bear)",
            r"(borne by the seller|seller shall bear)[^.]{0,100}"
            r"(certification|testing|factory audit)",
            r"(인증|시험|검사|공장\s*심사)[^.]{0,60}(비용|수수료)[^.]{0,40}"
            r"(매도인|공급자)[^.]{0,20}부담" + NO_NEG_KO],
    fix="인증비는 **나눠 부담**하거나 **주문 물량에 녹여** 받습니다. "
        "**인증 명의는 우리 앞**으로 내세요 — 바이어 명의면 그 바이어를 못 떠납니다. "
        "갱신 비용은 따로 다룹니다.",
    avoid=NEGATION,
)


# ── 나라가 비어 있던 곳 ─────────────────────────────────────────────────────
#
# 수출 상위 상대국 32개 중 8개(HK·TW·SG·MX·MY·PH·TH·CL)에 조항이 하나도
# 없었습니다. 그 빈 곳을 메웁니다. (2026-10-02)

_clause(
    "ddp_no_ior", "DDP 인데 현지 수입자가 될 수 없음", "toxic",
    why="DDP 는 **매도인이 수입통관까지** 하는 조건입니다. 그런데 여러 나라에서 "
        "현지에 법인이 없는 외국 매도인은 **수입자(importer of record)로 등록할 수 "
        "없습니다.** 그러면 우리는 약속한 일을 할 수가 없습니다.",
    risk="통관이 막혀 물건이 보세창고에 쌓이고, 보관료는 날마다 늘어납니다. "
         "우리가 못 하는 일을 약속했으니 **우리가 계약 위반**이 됩니다. "
         "현지 부가세 환급도 받을 수 없습니다.",
    text_en="""(바꿀 문구의 예)
Delivery shall be DDP the Buyer's warehouse, Incoterms 2020, with the Seller
responsible for import clearance, duties and local taxes.""",
    text_ko="DDP 와 import clearance/duties 가 매도인 책임으로 적혀 있으면 이 조항입니다. "
            "**도착국에서 우리가 수입자가 될 수 있는지** 먼저 확인하세요.",
    detect=[r"\bDDP\b[^.]{0,120}(?:import (?:clearance|customs|duties|formalities)"
            r"|importer of record)",
            r"(?:import (?:clearance|customs|duties)|importer of record)"
            r"[^.]{0,120}\bDDP\b",
            r"seller[^.]{0,60}(?:responsible for|shall (?:effect|arrange|bear))"
            r"[^.]{0,60}import (?:clearance|customs|duties|formalities)",
            r"\bDDP\b[^.]{0,80}(?:매도인|공급자)[^.]{0,40}(?:수입\s*통관|관세|수입세)",
            # 한국어는 목적어가 **앞**에 오기도 합니다 — "수입통관과 관세는 매도인이
            # 부담한다". 낱말 순서로 놓친 것이 **다섯 번째**입니다.
r"\bDDP\b[^.]{0,80}(?:수입\s*통관|관세|수입세)[^.]{0,40}(?:매도인|공급자)",
            r"(?:매도인|공급자)[^.]{0,50}(?:수입\s*통관|수입\s*신고)[^.]{0,30}"
            r"(?:책임|부담|이행)" + NO_NEG_KO],
    fix="**DAP 또는 CIP 로 바꿉니다** — 수입통관은 현지 수입자가 합니다. "
        "꼭 DDP 로 해야 하면, 바이어를 **수입자로 세우고(DDP, VAT unpaid)** 관세만 "
        "우리가 부담하는 식으로 나눕니다. 도착국에서 비거주자가 수입자가 될 수 "
        "있는지 **계약 전에** 현지 관세사에게 확인하세요.",
    countries=("BR", "MX", "RU", "CN", "IN", "AR", "ID", "TR", "VN", "TH", "PH", "CL"),
    avoid=NEGATION,
)

_clause(
    "reexport_control", "재수출·최종용도를 통제하지 않음", "toxic",
    why="중계무역 거점으로 보낸 물건이 **제재 대상국으로 다시 나가면**, 수출신고를 한 "
        "우리가 책임지는 쪽이 됩니다. 그런데 계약서에 재수출 제한과 최종용도 확인이 "
        "없으면 막을 근거가 없습니다.",
    risk="우리 이름으로 전략물자 수출 위반이 잡힙니다. 수출입 자격이 정지되면 "
         "그 거래 하나가 아니라 **회사 전체의 수출이 멈춥니다.**",
    text_en="""(넣어야 할 문구의 예 — 없으면 이 조항입니다)
The Buyer shall not re-export the Goods to any sanctioned destination, shall
disclose the end user and end use on request, and shall pass these obligations
to any subsequent purchaser.""",
    text_ko="중계무역 거점(홍콩·싱가포르·두바이 등)으로 보내는데 **재수출 제한·최종용도 "
            "확인**이 없으면 이 조항입니다. 계약서에서 re-export 와 end use 를 찾아보세요.",
    detect=[r"(?:buyer|purchaser)[^.]{0,80}(?:free to|may)[^.]{0,40}re[- ]?(?:export|sell)"
            r"[^.]{0,60}(?:any|without)",
            r"no restriction[^.]{0,60}(?:re[- ]?export|destination|end use)",
            r"(?:매수인|바이어)[^.]{0,50}(?:재수출|전매)[^.]{0,40}"
            r"(?:제한\s*없|자유)" + NO_NEG_KO,
            r"(?:최종\s*용도|최종\s*수요자)[^.]{0,40}(?:확인|고지)[^.]{0,20}"
            r"(?:하지\s*아니|없|면제)"],
    fix="**재수출 금지 대상국**을 적고, **최종용도·최종수요자 확인서(End User "
        "Certificate)** 를 받도록 넣습니다. 바이어가 다시 파는 상대에게도 같은 의무가 "
        "넘어가게(pass-through) 적습니다. 전략물자관리원 사전판정도 함께 받아 두세요.",
    countries=("HK", "SG", "TW", "AE", "MY", "TR", "KZ", "GE", "AM"),
)

_clause(
    "eu_epr_cost", "확대생산자책임(EPR) 등록·분담금 전가 (EU)", "toxic",
    why="EU 는 포장재·전기전자·배터리를 내놓는 사업자에게 **회원국마다** 등록과 "
        "분담금을 물립니다. 그걸 공급자인 우리에게 떠넘기는 조항입니다. "
        "비EU 사업자는 보통 직접 등록이 어려워 현지 대리인까지 세워야 합니다.",
    risk="나라가 늘수록 비용이 곱절로 늡니다. 등록이 안 된 채로 팔리면 **판매 금지와 "
         "과태료**가 나오는데, 정작 우리는 현지에서 등록할 자격이 없습니다.",
    text_en="""(지울 문구의 예)
All extended producer responsibility registrations, fees and reporting
obligations in each Member State shall be undertaken and paid by the Seller.""",
    text_ko="extended producer responsibility · EPR · packaging waste 와 "
            "Seller 부담이 함께 나오면 이 조항입니다.",
    # 이 조항의 예문("registrations, fees and reporting obligations in each Member
    # State … paid by the Seller")이 100자를 넘어 못 찾았습니다. (2026-10-03)
    detect=[r"extended producer responsibility[^.]{0,180}"
            r"(?:seller|supplier|borne by|at the expense)",
            r"\bEPR\b[^.]{0,80}(?:registration|fee|levy)[^.]{0,80}"
            r"(?:seller|supplier|borne by)",
            r"(?:packaging waste|WEEE|batter(?:y|ies))[^.]{0,60}(?:registration|lev(?:y|ies)|fees?|charges?)"
            r"[^.]{0,80}(?:seller|supplier|borne by)",
            r"(?:확대\s*생산자\s*책임|생산자\s*책임\s*재활용|EPR)[^.]{0,60}"
            r"(?:분담금|비용|등록)[^.]{0,40}(?:매도인|공급자)" + NO_NEG_KO],
    fix="EPR 은 **시장에 내놓는 사업자(바이어)** 의 의무입니다. 바이어가 등록하고 "
        "분담금을 내도록 바꿉니다. 우리가 부담해야 하면 **나라와 금액 상한**을 적고, "
        "단가에 미리 반영하세요.",
    countries=("EU",),
    # 바이어(수입자)가 내는 꼴은 우리에게 유리합니다 — "borne by" 만으로 걸렸습니다.
    avoid=NEGATION + (r"(?:borne|paid|undertaken)\s+by\s+the\s+(?:buyer|purchaser|importer)",
                      r"(?:매수인|바이어|수입자)[^.]{0,10}(?:이|가)\s*부담"),
)

_clause(
    "tariff_absorption", "관세 인상분을 공급자가 흡수", "toxic",
    why="수입 관세가 오르면 그 차액을 우리가 떠안는 조항입니다. 관세는 **나라가 "
        "정하는 것**이고 우리가 어찌할 수 없습니다.",
    risk="무역분쟁으로 관세가 하루아침에 25% 붙으면 마진이 통째로 날아갑니다. "
         "이미 받은 주문도 소급해 물어 주게 되는 경우가 있습니다.",
    text_en="""(지울 문구의 예)
Any increase in customs duties, tariffs or import charges shall be absorbed by
the Seller, and the agreed price shall remain unchanged.""",
    text_ko="increase in customs duties/tariffs 와 absorbed by the Seller 가 함께 "
            "나오면 이 조항입니다.",
    detect=[r"(?:increase|rise|change)[^.]{0,50}(?:customs dut|tariff|import charge)"
            r"[^.]{0,100}(?:absorbed by|borne by|at the cost of)[^.]{0,30}"
            r"(?:seller|supplier)",
            r"(?:seller|supplier)[^.]{0,60}(?:absorb|bear)[^.]{0,60}"
            r"(?:any )?(?:increase|additional)[^.]{0,40}(?:dut|tariff)",
            r"(?:관세|수입세)[^.]{0,30}(?:인상|증가|추가)[^.]{0,60}"
            r"(?:매도인|공급자)[^.]{0,25}(?:부담|흡수)" + NO_NEG_KO,
            # 한국어는 수식어가 **앞**에 옵니다 — "**추가 관세**는 공급자가
            # 부담한다". 낱말 순서로 놓친 것이 **여섯 번째**입니다.
            r"(?:추가|인상|증가)\s*(?:관세|수입세)[^.]{0,40}(?:매도인|공급자)"
            r"[^.]{0,25}(?:부담|흡수)" + NO_NEG_KO,
            r"(?:매도인|공급자)[^.]{0,40}(?:관세\s*인상분|추가\s*관세)[^.]{0,25}부담"
            + NO_NEG_KO],
    fix="관세는 **인코텀즈가 정한 쪽**이 냅니다(FOB·CIF 면 바이어). 조항을 빼거나, "
        "**관세가 일정 폭 이상 오르면 단가를 다시 정한다**로 바꿉니다. "
        "이미 받은 주문에는 소급하지 않는다는 말도 함께 넣으세요.",
    countries=("US", "CN", "EU", "IN", "BR", "MX", "TR"),
    avoid=NEGATION,
)

_clause(
    "psi_cost_delay", "선적 전 검사(PSI) 비용·지연 책임 전가", "toxic",
    why="수입국이 요구하는 **선적 전 검사**의 비용과, 검사기관 일정 때문에 생긴 "
        "지연까지 우리가 지는 조항입니다. 검사기관은 바이어나 그 나라가 고릅니다.",
    risk="검사 예약이 2주 밀려 선적이 늦으면 **우리가 납기 지연 벌금**을 뭅니다. "
         "검사비도 건당 수백 달러씩 듭니다.",
    text_en="""(지울 문구의 예)
Pre-shipment inspection by the agency appointed by the importing country shall
be arranged and paid for by the Seller, who shall also bear any resulting delay.""",
    text_ko="pre-shipment inspection · PSI 와 Seller 부담·지연 책임이 함께 나오면 "
            "이 조항입니다.",
    detect=[r"pre[- ]?shipment inspection[^.]{0,100}"
            r"(?:paid for by|at the cost of|borne by|arranged by)[^.]{0,30}"
            r"(?:seller|supplier)",
            r"\bPSI\b[^.]{0,80}(?:seller|supplier)[^.]{0,40}(?:cost|expense|bear)",
            r"(?:선적\s*전\s*검사|선적전검사)[^.]{0,60}(?:매도인|공급자)"
            r"[^.]{0,30}(?:부담|비용)" + NO_NEG_KO,
            r"(?:검사\s*지연|검사\s*일정)[^.]{0,50}(?:매도인|공급자)"
            r"[^.]{0,25}(?:책임|부담)" + NO_NEG_KO],
    fix="검사비는 **바이어 부담**으로 바꾸거나 단가에 반영합니다. 무엇보다 "
        "**검사기관 일정으로 생긴 지연은 납기에서 뺀다**를 꼭 넣으세요 — "
        "우리가 어찌할 수 없는 일로 벌금을 물면 안 됩니다.",
    countries=("NG", "EG", "DZ", "BD", "KE", "ID", "PH", "CD", "UZ", "IR"),
    avoid=NEGATION,
)

_clause(
    "full_inspection", "전수검사 의무와 비용 전가", "toxic",
    why="표본검사가 아니라 **하나하나 다 보는** 전수검사를 요구하고 그 비용을 우리가 "
        "지는 조항입니다. 수량이 많으면 검사 인건비가 제품 원가를 넘습니다.",
    risk="10만 개를 전수검사하면 그 비용만으로 거래 이익이 사라집니다. "
         "불합격이 나오면 재검사까지 또 우리 몫입니다.",
    text_en="""(살펴볼 문구의 예)
The Seller shall carry out 100% inspection of every unit prior to shipment at
its own cost, and shall re-inspect at its own cost if any defect is found.""",
    text_ko="100% inspection · every unit · 전수검사 와 Seller 부담이 함께 나오면 "
            "이 조항입니다. **표본검사(AQL)** 로 바꿀 수 있는지 보세요.",
    detect=[r"100\s*%\s*inspection",
            r"inspect(?:ion)?[^.]{0,40}(?:of )?(?:each|every) (?:unit|piece|item)",
            # **누가 내는지 봐야 합니다.** "전수검사 비용은 매수인이 부담한다" 는
            # 우리에게 유리합니다. (2026-10-02)
r"(?:전수|전량)\s*검사[^.]{0,40}(?:매도인|공급자)[^.]{0,25}(?:부담|비용|실시)",
            r"(?:매도인|공급자)[^.]{0,40}(?:전수|전량)\s*검사",
            r"(?:매도인|공급자)[^.]{0,50}(?:전수|전량)[^.]{0,20}검사[^.]{0,30}"
            r"(?:비용|부담)" + NO_NEG_KO],
    fix="**표본검사(AQL 기준)** 로 바꾸고, 전수검사가 필요하면 **비용을 바이어가** "
        "내거나 단가에 반영하도록 합니다. 재검사 횟수에도 상한을 두세요.",
    countries=("JP", "TW", "DE"),
    avoid=NEGATION,
)

def by_key(key: str) -> dict | None:
    return next((row for row in CLAUSES if row["key"] == key), None)


def for_category(category: str) -> list[dict]:
    return [row for row in CLAUSES if row["category"] == category]


def applies_to(row: dict, incoterms: str = "") -> bool:
    """이 건에 이 조항이 걸리는가. 조건을 안 적은 조항은 늘 걸립니다."""

    if "always" in row["applies"]:
        return True
    return (incoterms or "").upper() in row["applies"]


# 목차. 계약서 앞에 조항 **제목만** 줄줄이 적힌 덩어리입니다.
#
#     1. DESCRIPTION OF GOODS
#     2. PRICE AND INCOTERMS
#     3. PAYMENT TERMS
#
# 걷어내지 않으면 **내용이 하나도 없는데 필수조항을 다 갖췄다**고 하게 됩니다.
# 실제로 14개 중 13개를 '있다'고 했습니다. 사용자는 그 조항 없이 계약합니다.
# (2026-10-02 공격해 보다 찾았습니다)
#
# 제목만 있는 줄이 **넷 넘게 이어질 때만** 걷어냅니다. 진짜 조항은 제목 뒤에
# 본문이 따라오므로 제목 줄이 연달아 나오지 않습니다.
_HEADING_LINE = re.compile(
    r"^\s*(?:\d{1,2}|[IVXivx]{1,5})\s*[.)]?\s+[A-Z가-힣][^.]{0,70}$")
# 본문에 있는 말. 이것이 있으면 제목이 아니라 조항 내용입니다.
_OBLIGATION = re.compile(r"\b(shall|will|must|may)\b|하여야|한다\b|됩니다|한다\.", re.I)
TOC_RUN = 4


def _drop_table_of_contents(text: str) -> str:
    """목차 덩어리를 걷어냅니다. 제목만 있는 줄이 TOC_RUN 개 넘게 이어질 때만."""

    lines = text.split("\n")
    heading = [bool(_HEADING_LINE.match(line)) and not _OBLIGATION.search(line)
               for line in lines]
    drop = [False] * len(lines)
    start = None
    for index, is_heading in enumerate(heading + [False]):
        if is_heading and start is None:
            start = index
        elif not is_heading and start is not None:
            if index - start > TOC_RUN:
                for pos in range(start, index):
                    drop[pos] = True
            start = None
    return "\n".join(line for line, skip in zip(lines, drop) if not skip)


# 쪽 번호·머리글·바닥글. 계약서는 여러 쪽이라 **문장 한가운데** 이런 줄이 끼어듭니다.
#   "…at a price lower than"  /  "- 16 -"  /  "that offered to the Buyer…"
# 그러면 "price lower than that offered" 를 찾는 규칙이 끊깁니다. 흔들어 보니
# 최혜대우(MFN) 조항을 1만 부 중 36부에서 놓쳤습니다. 이런 줄은 계약 내용일
# 수가 없으므로 걷어 내고 봅니다. **줄 전체가** 이 모양일 때만 지웁니다.
# (2026-09-26)
_PAGE_FURNITURE = re.compile(
    r"""^\s*(?:
          [-–—]?\s*\d{1,4}\s*[-–—]?            # - 16 -   ·   16
        | (?:page|쪽|페이지)\s*\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?   # Page 3 of 12
        | \d{1,4}\s*(?:of|/)\s*\d{1,4}         # 3 / 12
        | .{0,60}\((?:cont(?:'|’)?d|continued|계속)\)   # SALES CONTRACT (cont'd)
    )\s*$""",
    re.I | re.X)


def _drop_page_furniture(text: str) -> str:
    return "\n".join(line for line in text.split("\n")
                     if not _PAGE_FURNITURE.match(line))


# ── 전 세계 단위 독소조항 (2026-09-27 사용자 지시) ──────────────────────────────
#
# 위 열 가지는 **어느 나라에서나 위험한** 일반 조항입니다. 아래는 다릅니다.
#
#   ① 나라·지역의 **강행법**에서 오는 것
#      계약서에 "준거법은 한국법" 이라고 적어도 **그 나라 법이 이깁니다.**
#      중동 대리점법·EU 상업대리인 지침이 그렇습니다. 계약서만 보면 안전해
#      보이는데 실제로는 물립니다. 그래서 "빠져 있음"을 위험으로 봅니다.
#
#   ② 국제매매 공통 규범(CISG)에서 오는 것
#      우리나라와 상대국이 모두 CISG 가입국이면 **아무 말 안 해도 적용됩니다.**
#      모르고 지나가면 내가 기대한 규칙과 다른 규칙으로 다투게 됩니다.
#
#   ③ 상대국 사법제도에서 오는 것
#      미국의 배심재판·징벌적 손해배상, 중국의 중재기관 선택 문제가 그렇습니다.
#
# **법률 자문이 아닙니다.** 아래 내용은 "이런 것이 있으니 변호사에게 확인하라"는
# 표시이지 판단이 아닙니다. 나라마다 법이 바뀌고 예외가 많습니다.
#
# 근거로 본 것 (2026-09-27 확인)
#   EU 상업대리인 지침 86/653/EEC — 해지 통지기간과 보상권은 초강행 규정이고
#     외국법을 골라도 배제되지 않습니다. 보상은 통상 연평균 수수료 1년치가 상한.
#   UAE 상업대리법 제8·9조 — 정당한 사유 없이 해지 불가, 해지 시 보상 의무.
#     등록된 대리점에는 외국법 선택이 통하지 않습니다.
#   사우디 상업대리 규정 — 기간 정함 없는 계약은 근속 1년당 1개월 통지.
#     보상 청구는 해지 후 1년 내에 해야 하고 지나면 소멸합니다.
#   CISG 제39조 — 하자 통지는 합리적 기간 내에, **늦어도 인도 후 2년** 내.
#     제38·39조는 계약으로 달리 정할 수 있습니다.

_clause(
    "agency_protection", "대리점 계약 — 그 나라 대리점 보호법 확인", "gain",
    why="UAE·사우디 등에서 대리점이 등록되면, 계약서에 무엇을 적었든 그 나라 법이 "
        "해지를 막고 보상을 물립니다. 준거법을 한국법으로 적어도 소용없습니다.",
    risk="거래를 끊으려는데 해지가 안 되고, 끊으면 보상금을 물립니다. "
         "그 나라에서 다른 대리점을 쓰지도 못합니다.",
    text_en="""(확인할 것 — 대리점·총판 계약일 때)
Registration of this Agreement with the local commercial agency registry shall
require the prior written consent of the Principal.
The Parties agree that this Agreement is non-exclusive and shall not be
registered as a commercial agency.""",
    text_ko="대리점 등록 여부와 해지·보상 조건을 반드시 확인하세요. 등록되면 되돌리기 어렵습니다.",
    detect=[r"commercial agenc(y|ies)",
            r"(sole|exclusive) (agent|distributor|representative)",
            # "exclusive agent" 말고 "exclusive **right to sell**" 로 적는 꼴.
            r"(?:sole|exclusive) right to (?:sell|distribute|import|market)",
            r"agency (registration|registry)",
            r"(총판|독점\s*(대리점|판매권|대리인))",
            r"대리점\s*등록"],
    applies=("always",),
    fix="중동·중남미로 대리점 계약을 맺기 전에 **그 나라 대리점법**을 변호사에게 확인하세요. "
        "등록을 막거나 기간을 정한 계약으로 하고, 해지 사유와 보상 산정을 미리 적어 둡니다.",
)

_clause(
    "agency_law_eu", "EU 상업대리인 보상 — 계약으로 못 없앱니다", "toxic",
    why="EU 안에서 활동하는 대리인에게는 지침 86/653 의 통지기간과 영업권 보상이 "
        "**초강행 규정**으로 적용됩니다. 비EU 법을 골라도 그 권리는 남습니다.",
    risk="계약 종료 시 통상 **연평균 수수료 1년치**까지 보상 청구를 받을 수 있습니다.",
    text_en="""(확인할 것 — EU 대리인·판매대리 계약일 때)
Upon termination the Agent shall not be entitled to any indemnity or
compensation whatsoever.""",
    text_ko="'어떤 보상도 없다'고 적어 두어도 EU 안에서는 그대로 통하지 않습니다.",
    detect=[r"(?:영업권\s*보상|보상금|보상청구)[^.]{0,30}(?:청구하지|받지)[^.]{0,15}못",
            r"no claim to goodwill indemnity",
            r"waive[^.]{0,70}compensation[^.]{0,50}(?:86/653|directive)",
            r"(?:영업권\s*보상|보상청구권)[^.]{0,40}(?:청구하지|포기)",
            r"not be entitled to any[^.]{0,30}(indemnity|compensation)",
            r"no [^.]{0,20}(indemnity|compensation) (shall be|is) (due|payable)",
            r"waive[^.]{0,40}(goodwill|indemnity|compensation)",
            r"commercial agent",
            r"보상[^.]{0,10}(청구)?[^.]{0,6}(권리)?[^.]{0,6}없"],
    applies=("always",),
    fix="보상이 발생한다는 전제로 **금액과 산정 방법을 미리 합의**하거나, 대리인이 아닌 "
        "매매(판매점) 구조로 갈 수 있는지 변호사와 검토하세요.",
    countries=("EU",),
)

_clause(
    "cisg_silent", "CISG 적용·배제를 적었는가", "gain",
    why="우리나라와 상대국이 모두 가입국이면 **아무 말이 없어도 CISG 가 적용됩니다.** "
        "내가 아는 국내법 규칙으로 다툴 생각이었다면 그때부터 어긋납니다.",
    risk="하자 통지 기간·해제 요건·위험 이전이 내가 생각한 것과 다르게 판단됩니다.",
    text_en="""(넣을 문구의 예 — 둘 중 하나를 고르세요)
This Contract shall be governed by the United Nations Convention on Contracts
for the International Sale of Goods (CISG).
-- 또는 --
The application of the United Nations Convention on Contracts for the
International Sale of Goods (CISG) is hereby expressly excluded.""",
    text_ko="쓸 것인지 뺄 것인지를 **문장으로 적어 두세요.** 안 적으면 자동으로 적용됩니다.",
    detect=[r"CISG", r"Convention on Contracts for the International Sale of Goods",
            r"(국제물품매매계약에\s*관한\s*)?유엔\s*협약", r"비엔나\s*협약"],
    applies=("always",),
    fix="준거법 조항 옆에 CISG 적용 또는 배제를 **한 문장으로** 적으세요. "
        "어느 쪽이 유리한지는 품목과 거래 구조에 따라 다르니 변호사와 정합니다.",
)



_clause(
    "china_domestic_arb", "중국 국내 중재기관 전속", "toxic",
    why="중국 상대 계약에서 분쟁을 중국 국내 중재기관에만 맡기면, 우리가 고를 수 있는 "
        "다른 길(홍콩·싱가포르·대한상사중재원)을 스스로 닫는 것입니다.",
    risk="말이 통하지 않는 절차에서 다투게 되고, 비용과 기간을 가늠하기 어렵습니다.",
    text_en="""(확인할 것)
All disputes shall be submitted to arbitration in [city, PRC] under the rules
of [domestic institution], whose award shall be final.""",
    text_ko="중재지·중재기관·언어·중재인 수를 함께 적어야 합니다. 하나라도 비면 다툼이 됩니다.",
    detect=[r"CIETAC",
            r"arbitration.{0,40}(Beijing|Shanghai|Shenzhen|Guangzhou|PRC|China)",
            r"(Beijing|Shanghai|Shenzhen|Guangzhou|China\w*)\s+Arbitration (Commission|Centre|Center)",
            r"중국\s*국제경제무역중재",
            r"중재[^.]{0,20}(북경|베이징|상해|상하이|심천|선전)"],
    applies=("always",),
    fix="홍콩(HKIAC)·싱가포르(SIAC)·대한상사중재원(KCAB) 같은 **제3지 중재**를 제안해 보세요. "
        "중재지·기관·언어·중재인 수를 한 조항에 모두 적습니다.",
    countries=("CN",),
)


_clause(
    "ip_assignment", "개발 결과물·금형의 권리가 넘어갑니다", "toxic",
    why="OEM·주문생산에서 '이 거래로 만들어진 모든 것의 권리는 바이어에게 귀속' 이라고 "
        "적으면, 우리가 쌓은 기술과 금형까지 함께 넘어갑니다.",
    risk="거래가 끝난 뒤 그 바이어가 우리 금형과 도면으로 다른 공장에 맡깁니다.",
    text_en="""(지울 문구의 예)
All intellectual property rights in any designs, tooling, moulds, know-how or
improvements arising from this Contract shall vest exclusively in the Buyer.""",
    text_ko="금형·도면·개선 기술이 어디에 귀속되는지 문장으로 갈라 두세요.",
    detect=[r"title to[^.]{0,60}(?:moulds?|molds?|tooling)[^.]{0,80}(?:passes?|transfers?)[^.]{0,30}(?:to the )?(?:buyer|purchaser)",
            r"(?:results? of development|development results?)[^.]{0,70}vest",
            r"(?:개발\s*성과물|지적재산권)[^.]{0,50}(?:매수인|바이어)[^.]{0,25}(?:이전|귀속)",
            r"(intellectual property|IP) rights[^.]{0,120}(vest|assign|belong)[^.]{0,30}Buyer",
            r"(tooling|moulds?|dies)[^.]{0,80}(vest|property of|owned by|belong)[^.]{0,30}Buyer",
            r"work made for hire",
            r"(지식재산권|지적재산권|금형|사출|치공구)[^.]{0,30}(갑|매수인|바이어)[^.]{0,10}(에게)?[^.]{0,6}(귀속|양도|이전)(?![^.]{0,40}(없|못하|아니하|아니한|금지))"],
    applies=("always",),
    fix="바이어가 비용을 댄 **금형 자체의 소유권**과 우리가 가진 **제조 노하우**를 갈라 "
        "적으세요. 개선 기술은 우리에게 남기고 사용권만 주는 방식도 있습니다.",
    avoid=NEGATION,
)



_clause(
    "buyer_set_off", "바이어가 마음대로 상계합니다", "toxic",
    why="'어떤 사유로든 공제하고 지급할 수 있다'고 적으면, 상대가 클레임을 이유로 "
        "대금을 깎아 보내고 우리는 받은 뒤에 다퉈야 합니다.",
    risk="대금이 들어오지 않은 채 분쟁만 남습니다. 신용장 거래에서도 문제가 됩니다.",
    text_en="""(지울 문구의 예)
The Buyer may set off or deduct from any amounts due any claim it may have
against the Seller, whether liquidated or not.""",
    text_ko="상계·공제는 **확정된 금액**에 대해서만 가능하도록 좁혀야 합니다.",
    detect=[r"apply any amount owing[^.]{0,70}reduction",
            r"net off[^.]{0,50}(?:claims?|against)[^.]{0,40}(?:purchase )?price",
            r"(?:매수인|바이어)[^.]{0,50}채권[^.]{0,25}(?:으로\s*)?대금[^.]{0,25}공제",
            r"Buyer (may|shall be entitled to|has the right to).{0,60}set[- ]?off",
            r"Buyer.{0,40}(deduct|withhold).{0,40}(any|whatsoever)",
            r"set[- ]?off.{0,40}(any|whatsoever).{0,30}claim",
            r"(갑|매수인|바이어)[^.]{0,30}(상계|공제)(?![^.]{0,40}(없|못하|아니하|아니한|금지))"],
    applies=("always",),
    fix="상계를 **양 당사자가 서면으로 인정했거나 확정판결·중재판정이 있는 금액**으로 "
        "한정하는 문장으로 바꿔 달라고 하세요.",
    avoid=SELLER_SETS_OFF + SET_OFF_DENIED,
)



_clause(
    "us_jury_punitive", "미국 법원 관할 — 배심재판·징벌적 손해배상", "toxic",
    why="미국 법원으로 가면 배심원이 손해액을 정합니다. 주에 따라 실제 손해의 몇 배를 "
        "물리는 징벌적 손해배상도 있습니다. 우리 기준으로는 가늠이 안 되는 금액이 나옵니다.",
    risk="송장 금액과 무관한 배상 판결을 받고, 변호사 비용만으로도 거래 이익을 넘깁니다.",
    text_en="""(확인할 것 — 이런 문구가 있으면 미국 법원으로 끌려갑니다)
The Parties hereby submit to the exclusive jurisdiction of the courts of
New York, and waive any objection to venue therein.""",
    text_ko="배심재판 포기와 징벌적·간접 손해 배제를 **함께** 넣어야 뜻이 있습니다. "
            "('trial by jury'·'punitive damages' 라는 낱말 자체는 찾지 않습니다 — "
            "포기·면책 문장에도 똑같이 나와 편을 가릴 수 없습니다. 미국 관할이 "
            "보이면 이 위험을 함께 알립니다)",
    # **제목이 약속한 배심재판·징벌적 손해배상을 실제로 봅니다.** (2026-10-02)
    #
    # 전에는 규칙 다섯 개에 jury · punitive · 배심 · 징벌적 이 하나도 없어,
    # 미국 법원을 적지 않고 배심재판만 넣은 계약서는 통과했습니다.
    #
    # **포기(waive)는 빼야 합니다.** "배심재판을 포기한다"는 우리에게
    # 유리한 문장입니다. 그것까지 독소로 짚으면 지우라고 하게 됩니다.
    detect=[r"(?:캘리포니아|뉴욕|델라웨어|텍사스)\s*(?:주)?\s*법원",
            r"federal courts? of (?:Delaware|New York|California|Texas)",
            r"exemplary damages",
            r"(?:캘리포니아|뉴욕|델라웨어|텍사스)[^.]{0,25}(?:주)?\s*법원",
            r"(courts?|jurisdiction) of .{0,40}(New York|California|Texas|Delaware|the United States)",
            r"(submit|consent).{0,40}jurisdiction.{0,40}(United States|U\.S\.|New York)",
            r"exclusive jurisdiction.{0,40}(United States|U\.S\.|New York|California)",
            r"미국\s*법원[^.]{0,20}(관할|전속)(?![^.]{0,40}(없|못하|아니하|아니한))",
            r"(뉴욕|캘리포니아|델라웨어)\s*(주)?\s*법원[^.]{0,20}관할",
            # 배심재판 — 포기·배제는 뺍니다.
            r"(?:consent|agree|submit)[^.]{0,40}trial by jury",
            r"right[^.]{0,20}to[^.]{0,10}(?:a )?jury trial(?![^.]{0,40}waiv)",
            r"배심\s*재판" + NO_WAIVE_KO,
            # 징벌적 손해배상 — 배제 문구는 뺍니다.
            r"punitive damages(?![^.]{0,60}(?:waiv|exclud|disclaim|shall not|no ))",
            r"징벌적\s*손해\s*배상" + NO_WAIVE_KO],
    applies=("always",),
    fix="중재(뉴욕협약)로 바꾸는 것이 가장 낫습니다. 미국 법원을 피할 수 없다면 "
        "**배심재판 포기**와 **징벌적·간접손해 배제**를 반드시 넣으세요.",
    countries=("US",),
    avoid=NEGATION,
)

# ── 실물 보세가공 계약서에서 (2026-10-02) ─────────────────────────────────
#
# 우리는 수출자(매도인)입니다. 가공무역에서는 상대가 원자재를 보내고, 우리가
# 가공해 되팝니다. 보통 매매계약에는 없는 위험이 둘 있습니다.

# 가공계약인가 — 상대(바이어)가 우리에게 원자재를 대는가. (_as_seller 뒤의 글)
PROCESSING = (r"\bbuyer\s+shall\s+(?:supply|provide|furnish|deliver|consign)\s+(?:to\s+the\s+seller\s+)?"
              r"[^.]{0,80}(?:yarn|materials?|components?|parts|fabrics?|resin|raw)",
              r"(?:materials?|yarn|components?|parts)\s+(?:supplied|provided|furnished|consigned)\s+by\s+the\s+buyer",
              r"\b(?:bonded|consignment|toll)\s+processing\b|\bprocessing\s+trade\b",
              r"(?:매수인|바이어|위탁자)[^.]{0,30}(?:원자재|원사|자재|부품)[^.]{0,20}(?:공급|제공)",
              r"(?:매수인|바이어|위탁자)[^.]{0,20}(?:공급|제공)한\s*(?:원자재|원사|자재|부품)",
              r"(?:위탁|보세)\s*가공")

_clause(
    "own_negligence_indemnity", "상대 과실까지 우리가 배상", "toxic",
    why="상대의 지시나 과실로 생긴 손해까지 우리가 물어 주는 조항입니다. 우리가 "
        "막을 방법이 없는 손해를 떠안습니다.",
    risk="상대가 보낸 원자재가 불량이거나 상대가 잘못 지시해서 생긴 손해도 우리가 "
         "전부 배상합니다. 보험으로도 잘 안 막힙니다.",
    text_en="""(지울 문구의 예)
The Seller shall indemnify the Buyer for all losses, including losses caused in
whole or in part by the Buyer's own instructions or negligence.""",
    text_ko="caused … by the Buyer's own negligence · regardless of fault · "
            "매수인의 과실을 불문하고 가 배상 문장에 붙어 있으면 이 조항입니다.",
    detect=[r"indemnif\w*[^.]{0,250}(?:caused|arising|resulting)\s+(?:in\s+whole\s+or\s+in\s+part\s+)?"
            r"(?:by|from)\s+(?:the\s+)?buyer'?s?\s+(?:own\s+)?(?:\w+\s+(?:or|and)\s+)?(?:gross\s+)?"
            r"(?:negligen|fault|instruction)",
            r"indemnif\w*[^.]{0,250}(?:even if|whether or not|regardless of whether)[^.]{0,60}"
            r"(?:caused by|due to|attributable to)[^.]{0,20}(?:the\s+)?buyer",
            r"indemnif\w*[^.]{0,200}regardless of (?:the\s+buyer'?s?\s+)?(?:fault|negligence)",
            r"(?:매수인|바이어)\s*(?:의)?\s*(?:고의|과실|귀책|지시)[^.]{0,40}(?:포함|불문|관계없이)"
            r"[^.]{0,40}(?:배상|면책|책임)",
            r"(?:과실|귀책)\s*(?:여부|유무)[^.]{0,6}(?:를|와)?\s*(?:불문|관계없이)[^.]{0,40}"
            r"(?:매도인|공급자)(?:은|는|이|가)?[^.]{0,30}(?:배상|책임)"],
    fix="**각자 자기 과실 범위에서만** 책임지게(\"to the extent caused by its own "
        "negligence\") 바꾸고, 상대 원자재·지시로 생긴 손해는 상대 부담으로 적어 달라고 하세요.",
    # 통짜 NEGATION 은 못 씁니다 — "과실과 관계**없**이" 의 '없'이 부정말로 읽혀
    # 이 조항을 스스로 못 찾습니다. 배상 자체를 부정하는 말만 봅니다.
    avoid=INDEMNIFY_SELLER + (
        r"\b(?:shall|will|need)\s+not\s+(?:be\s+(?:required|obliged)\s+to\s+)?indemnif",
        r"배상(?:하지|할\s*책임이)\s*(?:아니|않|없)"),
)

_clause(
    "consigned_material_lock", "상대 원자재를 동의 없이 가공 못 함", "toxic",
    why="상대가 보낸 원자재의 대금이 정산되기 전에는 상대 동의 없이 가공할 수 "
        "없게 묶는 조항입니다. 대금이 늦어지면 생산이 멈추는데, 납기는 그대로입니다.",
    risk="신용장 서류 하자로 원자재 대금 지급이 늦어지면 공장이 섭니다. 그래도 "
         "완제품 선적 기한을 넘기면 우리가 위반입니다.",
    text_en="""(지울 문구의 예)
Until the price is received, the buyer shall not resell, pledge, mix or process
the goods without the seller's written consent.""",
    text_ko="가공계약에서 원자재 소유권 유보와 '동의 없이 가공 금지'가 함께 있으면 "
            "이 조항입니다. 보통 매매계약에서는 우리에게 **유리**하므로 짚지 않습니다.",
    detect=[r"(?:shall|may|must)\s+not\s+(?:[a-z]+,?\s+(?:or\s+|and\s+)?){0,5}process\s+"
            r"(?:them|it|the\s+(?:goods|materials?|yarn|fabrics?|components?|parts))"
            r"[^.]{0,60}without[^.]{0,40}consent",
            r"(?:원자재|원사|자재|부품)[^.]{0,60}(?:동의|승낙)\s*없이[^.]{0,20}"
            r"가공(?:할 수 없|하지 못|금지)"],
    fix="**신용장 개설(또는 대금 지급 절차 개시)로 가공에 동의한 것**으로 보게 하고, "
        "원자재 대금이 늦어지면 **완제품 납기도 그만큼** 늦추게 해 달라고 하세요.",
    context=PROCESSING,
)

_clause(
    "material_yield", "가공 손모율·잔량 처리 (Yield & Surplus)", "gain",
    why="원자재 10,000kg 으로 완제품 9,000m 를 만들라는 계약에서, 불량·손실을 "
        "얼마까지 인정하는지와 남은 원자재를 어떻게 하는지가 없으면 모자란 만큼 "
        "우리가 물어냅니다.",
    risk="원자재 품질 탓에 수율이 떨어져도 계약 수량을 못 맞춘 책임은 우리에게 "
         "갑니다. 보세 원자재 잔량은 세관 정산 대상입니다.",
    text_en="""(넣을 문구의 예)
A processing loss of up to <3>% of the materials supplied by the Buyer shall be
allowed. Any shortfall caused by defective materials shall be borne by the Buyer.
Surplus materials shall be returned to the Buyer or disposed of as agreed in
writing, in accordance with applicable customs requirements.""",
    text_ko="**손모 허용률(%)**, **원자재 불량에 따른 부족은 상대 부담**, **잔량 반송·처분 "
            "방법**을 함께 적습니다.",
    detect=[r"(?:processing\s+)?(?:wastage|loss|yield|scrap)\s+(?:rate|allowance|ratio)",
            r"processing\s+loss", r"(?:surplus|remaining|leftover|excess)\s+(?:yarn|materials?)",
            r"(?:손모|로스)\s*율?", r"잔량|잔여\s*(?:원자재|원사|자재)"],
    fix="",
    context=PROCESSING,
)



# ── 실제 분쟁에서 나온 독소조항 (2026-10-03) ─────────────────────────────────
#
# 판결문·중재판정에 **인용된 문구**를 모아(CISG 판례 52 · 결제·신용장 35 · 국내
# 41 · 해외 26건) 기존 조항과 맞춰 보니, 어디에도 안 들어가는 유형이 여럿
# 나왔습니다. 그중 **여러 사건에서 매도인이 진** 것만 넣습니다. 사건과 문구는
# tests/test_contract_disputes.py 에 있습니다.

# 다른 나라 말. 영문·국문이 우선하는 꼴은 우리에게 문제가 없습니다.
_FOREIGN_LANG = (r"(?:chinese|japanese|vietnamese|russian|arabic|spanish|portuguese|french"
                 r"|german|italian|indonesian|thai|turkish|hindi|polish|dutch|persian|farsi"
                 r"|malay|mongolian|uzbek|kazakh)")

_clause(
    "battle_of_forms", "바이어 발주서·구매약관이 우선", "toxic",
    why="계약서를 잘 써 두어도 바이어 발주서(PO)나 구매약관이 우선한다고 적혀 있으면, "
        "우리가 넣은 책임 한도·중재·클레임 기한이 **통째로 밀려납니다**.",
    risk="판례에서 가장 자주 다툰 자리입니다. 바이어 약관의 지연 공제로 대금이 깎이고"
         "(OGH 2017), 우리 PI 의 중재 조항이 PO 와 충돌해 관할을 다투느라 5년이 걸렸습니다"
         "(KCAB·서울중앙지법 2020~2024).",
    text_en="""(지울 문구의 예)
The terms and conditions of the Buyer's purchase order shall prevail over any
terms of the Seller's quotation, proforma invoice or order acknowledgement.""",
    text_ko="Buyer's purchase order · our purchase terms 와 prevail · exclusively 가 함께 "
            "나오면 이 조항입니다.",
    detect=[r"(?:buyer|purchaser)'?s?\s+(?:purchase\s+orders?|P\.?O\.?s?|general\s+(?:terms|conditions)"
            r"(?:\s+of\s+purchase)?|purchase\s+(?:terms|conditions)|standard\s+terms"
            r"|terms\s+and\s+conditions(?:\s+of\s+purchase)?)[^.]{0,80}"
            r"(?:prevail|govern|control|take\s+precedence|apply\s+exclusively)",
            r"\bexclusive\w*\s+(?:validity\s+of\s+)?our\s+(?:general\s+)?purchas\w*\s+(?:terms|conditions)",
            r"\bour\s+(?:general\s+)?purchas\w*\s+(?:terms|conditions)\b[^.]{0,60}"
            r"(?:exclusive|prevail|apply|govern)",
            r"(?:received|accepted)\s+solely\s+(?:under|on)\s+the\s+(?:conditions|terms)\s+(?:herein|stated)",
            r"(?:매수인|바이어)[^.]{0,10}(?:발주서|주문서|구매\s*(?:약관|조건)|일반\s*거래\s*조건)"
            r"[^.]{0,40}(?:우선(?:하여)?\s*적용|우선한다|우선함|에\s*따른다)" + NO_NEG_KO],
    fix="'**본 계약이 바이어 발주서·약관보다 우선하며, 발주서의 다른 조건은 효력이 없다**'로 "
        "바꿉니다. 우리 약관은 **원문을 첨부**해야 효력이 있습니다(BGH 2001 — 참조만 하고 "
        "첨부하지 않은 면책 조항은 무효). PO 를 받으면 다른 조건을 **서면으로 거절**하세요.",
    avoid=NEGATION + (r"subject\s+to\s+(?:this|the)\s+(?:contract|agreement)",
                      r"\b(?:this|the)\s+(?:contract|agreement)\s+(?:shall\s+)?prevail",
                      r"prevail\w*\s+over\s+(?:the\s+|any\s+)?(?:terms\s+(?:of|in)\s+(?:the\s+|any\s+)?)?"
                      r"(?:buyer|purchaser)",
                      r"seller'?s?\s+(?:general\s+)?(?:terms|conditions)[^.]{0,40}prevail",
                      r"본\s*계약[^.]{0,10}우선"),
)

_clause(
    "foreign_language_prevails", "상대 언어로 쓴 본이 우선", "toxic",
    why="영문과 중문(또는 다른 언어)으로 함께 쓰고 **상대 언어본이 우선**하면, 우리가 "
        "읽지 못하는 글이 계약이 됩니다. 두 본에 서로 다른 중재 조항이 들어가 있어도 모릅니다.",
    risk="영문본은 '영문 우선', 중문본은 '중문 우선 · CIETAC 중재'로 적힌 계약에서 법원은 "
         "중재 합의가 **없다**고 봤습니다(NY Dept. of Health v. Rusi Technology, 2022). "
         "상대가 읽지 못한 언어의 약관은 거꾸로 우리 클레임 기한을 무력하게 했습니다"
         "(MCC-Marble, 11th Cir. 1998).",
    text_en="""(지울 문구의 예)
This Contract is made in Chinese and English. In case of any discrepancy,
the Chinese text shall prevail.""",
    text_ko="Chinese · Vietnamese · Russian … version(text) 과 prevail 이 함께 나오면 이 조항입니다.",
    detect=[_FOREIGN_LANG + r"\s+(?:version|text|language|original)\b"
            r"(?:(?!english|korean|reference)[^.]){0,40}"
            r"(?:(?:shall|will|is\s+to|to)\s+(?:prevail|govern|control|take\s+precedence"
            r"|be\s+(?:the\s+)?(?:authoritative|binding|controlling))|\b(?:prevails|governs|controls)\b)",
            r"precedence\s+(?:shall\s+be\s+)?given\s+to\s+(?:the\s+)?" + _FOREIGN_LANG,
            r"(?:중국어|중문|일본어|일문|베트남어|러시아어|아랍어|스페인어|포르투갈어|프랑스어|독일어"
            r"|인도네시아어|태국어|터키어)\s*(?:본|판|계약서|원문)?[^.]{0,25}"
            r"(?:우선|기준으로\s*한다|효력을\s*가진다)" + NO_NEG_KO],
    fix="**영문 한 본만 정본**으로 하고, 번역본은 '참고용(for reference only)'이라고 적습니다. "
        "여러 언어로 쓸 때는 **모든 본에 같은 우선 언어 조항**을 넣으세요.",
    avoid=NEGATION,
)

_clause(
    "acceptance_signature_payment", "바이어 서명이 있어야 대금 지급이 시작됨", "toxic",
    why="검수·시운전 확인서에 **바이어가 서명해야** 지급 기한이 시작되면, 바이어는 서명을 "
        "미루는 것만으로 대금을 미룰 수 있습니다.",
    risk="러시아 바이어가 시운전 확인서 서명을 거부하며 '아직 지급기가 아니다'라고 버텨, "
         "한국 매도인은 **대법원까지 가서야** 116만 달러를 받았습니다(대법원 2025.3.27. "
         "2021다242185).",
    text_en="""(지울 문구의 예)
The first instalment shall become due on the date on which the commissioning
confirmation document is signed by the Buyer.""",
    text_ko="payment(instalment) 과 acceptance · commissioning certificate … signed 가 함께 "
            "나오고 **'서명하지 않으면 인수로 본다'가 없으면** 이 조항입니다.",
    detect=[r"(?:payment|instal+ments?|balance|price|amount)[^.]{0,80}(?:upon|after|against|following"
            r"|on\s+the\s+date\s+on\s+which|from\s+the\s+date\s+(?:on\s+which|of)|subject\s+to)[^.]{0,40}"
            r"(?:acceptance|commissioning|completion|installation|final\s+inspection|performance)\s+"
            r"(?:test\s+)?(?:certificate|confirmation|protocol|document|report)",
            r"(?:acceptance|commissioning|completion|installation)\s+(?:test\s+)?"
            r"(?:certificate|confirmation|protocol|document|report)[^.]{0,40}(?:signed|issued|approved)\s+by\s+"
            r"the\s+(?:buyer|purchaser|end\s+user|customer)[^.]{0,80}(?:payment|paid|payable)",
            r"(?:검수|인수|시운전|설치|성능\s*시험)\s*(?:완료)?\s*(?:확인서|증명서|보고서)[^.]{0,40}"
            r"(?:서명|발급|날인)[^.]{0,60}(?:지급|결제|기산)",
            r"(?:지급|결제)[^.]{0,40}(?:검수|인수|시운전)\s*(?:완료)?\s*(?:확인서|증명서)[^.]{0,20}(?:서명|발급)"],
    fix="'**시운전 완료 후 N일 안에 서면 이의가 없으면 인수한 것으로 본다(deemed acceptance)**'를 "
        "함께 넣고, 늦어도 **선적 후 N일**에는 지급기가 오도록 상한을 둡니다.",
    avoid=NEGATION + (r"\bdeemed\b", r"간주", r"(?:fail|refus)\w*\s+to\s+sign",
                      r"\bin\s+any\s+event\b", r"늦어도",
                      # 우리가 서명하는 확인서는 우리 손에 있습니다.
                      r"(?:signed|issued|approved)\s+by\s+the\s+(?:seller|supplier)",
                      r"(?:매도인|공급자)(?:이|가)\s*(?:서명|발급)"),
)

_clause(
    "on_demand_bond", "청구만 하면 지급되는 이행·선수금 보증", "toxic",
    why="'**청구하면 증빙 없이 조건 없이 지급**'하는 보증은 바이어가 우리 잘못을 증명하지 "
        "않고도 돈을 찾아갈 수 있습니다. 은행은 우리에게 그대로 구상합니다.",
    risk="바이어가 신용장을 열지도 않고 이행보증을 청구했는데 은행은 지급해야 했습니다"
         "(Edward Owen v. Barclays, 1978). 이란 바이어의 청구를 권리남용이라고 다퉜지만 "
         "대법원은 '객관적으로 명백'하지 않다며 받아들이지 않았습니다(대법원 2014.8.26. "
         "2013다53700).",
    text_en="""(지울 문구의 예)
The Seller shall furnish a performance guarantee payable on first written demand,
without proof or conditions.""",
    text_ko="performance(advance payment) bond · guarantee 와 on (first) demand · without proof 가 "
            "함께 나오면 이 조항입니다. '수익자가 판단하여 서면으로 청구하면 조건 없이'도 같습니다.",
    detect=[r"(?:performance|advance\s+payment|down\s*payment|refund|warranty|retention)\s+"
            r"(?:bond|guarantee|security|standby)[^.]{0,120}"
            r"(?:on\s+(?:first\s+)?(?:written\s+)?demand|first\s+(?:written\s+)?demand)",
            r"(?:payable|pay)\s+(?:up)?on\s+(?:first\s+)?(?:written\s+)?demand\s+without\s+"
            r"(?:any\s+)?(?:proof|conditions?|objection|reference)"],
    # **'조건 없이'** 의 '없' 은 NEGATION 에 걸립니다. 부정이 뜻의 일부라 규칙
    # 안에서 봅니다 — 끝에 지급을 부정하는 말이 오면 아닙니다.
    strict=[r"보증[^.]{0,80}(?:판단하여|청구만으로|서면\s*청구|청구하면|요구\s*즉시)[^.]{0,60}"
            r"(?:조건\s*없이|무조건|즉시|이의\s*없이)(?![^.]{0,30}(?:아니한다|않는다|하지\s*않))",
            r"(?:이행|선수금\s*환급|계약\s*이행|하자\s*보수)\s*보증[^.]{0,60}"
            r"(?:조건\s*없이|무조건|청구\s*즉시|청구만으로)(?![^.]{0,30}(?:아니한다|않는다|하지\s*않))",
            r"(?:청구만으로|청구\s*즉시|요구\s*즉시)[^.]{0,30}(?:조건\s*없이|무조건)?[^.]{0,20}"
            r"지급(?:되는|하는)\s*(?:이행|선수금\s*환급|계약\s*이행|하자\s*보수)?\s*보증"],
    fix="보증은 **계약에 맞는 L/C 를 받은 뒤** 효력이 생기게 하고, 청구에는 **중재판정이나 "
        "제3자(검사기관) 확인**을 붙입니다. 금액은 **선적분만큼 줄고**, 만료일을 박으세요. "
        "제재로 이행할 수 없는 경우는 청구 사유에서 뺍니다.",
    avoid=NEGATION + (r"(?:buyer|purchaser)\s+shall\s+(?:procure|provide|furnish|open|issue|arrange|cause)",
                      r"in\s+favou?r\s+of\s+the\s+seller",
                      r"against\s+(?:a\s+)?(?:final\s+)?(?:arbitral\s+award|court\s+judg)"),
)

_clause(
    "time_essence_cancel", "조금만 늦어도 바로 해제", "toxic",
    why="'time is of the essence'나 '7일 늦으면 취소'는 **유예기간 없이** 계약을 끝낼 "
        "근거가 됩니다. 이미 만든 물건이 그대로 남습니다.",
    risk="선적 7일 지연 해제권이 있는 계약에서 한국 무역상이 선수금에 연 20% 이자를 얹어 "
         "돌려줬습니다(서울고법 2014.10.17. 2012나29719). 바이어가 납기를 중요하다고 알린 "
         "것만으로도 지연이 곧 해제 사유가 됐습니다(ICC Award 8128).",
    text_en="""(지울 문구의 예)
Time of delivery is of the essence. If shipment is delayed by more than seven (7)
days, the Buyer may cancel the order without liability.""",
    text_ko="time is of the essence, 또는 '지연되면 바이어가 취소·해제할 수 있다'가 "
            "**추가 기간 없이** 나오면 이 조항입니다.",
    # **납기에 묶인 것만** 봅니다. 미국 계약서 1,310 건에서 "Time is of the essence
    # of this Agreement" 가 88 건 나왔는데, 납기와 무관한 상투어입니다. (2026-10-03)
    detect=[r"\btime\s+of\s+(?:delivery|shipment)\s+(?:is|shall\s+be)\s+of\s+the\s+essence",
            r"\btime\s+(?:is|shall\s+be)\s+of\s+the\s+essence[^.]{0,120}"
            r"(?:deliver|shipment|ship\b|delivery\s+dates?|lead\s+time)",
            r"\b(?:delivery|shipment)\s+dates?\s+(?:is|are|shall\s+be)\s+(?:of\s+the\s+)?essen",
            r"(?:delay\w*|late|fails?\s+to\s+(?:ship|deliver))[^.]{0,100}(?:buyer|purchaser)\s+"
            r"(?:may|shall\s+be\s+entitled\s+to|has\s+the\s+right\s+to|is\s+entitled\s+to)\s+"
            r"(?:immediately\s+)?(?:cancel|terminate|rescind|avoid)\b[^.]{0,40}"
            r"(?:order|contract|agreement|purchase)",
            r"(?:선적|인도|납기)[^.]{0,30}(?:지연|늦)[^.]{0,60}(?:매수인|바이어)[^.]{0,20}"
            r"(?:즉시\s*)?(?:계약|주문)?[^.]{0,10}(?:해제|해지|취소)할\s*수\s*있"],
    fix="해제 전에 **서면 최고 + 추가 기간(예: 15~30일)**을 주게 하고, 해제는 **늦은 선적분에만** "
        "미치게 합니다. 원공급사 지연·불가항력은 지연에서 빼세요.",
    avoid=NEGATION + (r"additional\s+period", r"grace\s+period", r"(?:after|following)\s+(?:a\s+)?written\s+notice",
                      r"\bnachfrist\b", r"force\s+majeure", r"유예\s*기간", r"최고", r"불가항력",
                      r"(?:for|of|as\s+to|in)\s+(?:the\s+)?payment", r"payment\s+(?:date|obligations?)",
                      # 30 일 넘게 기다린 뒤의 해제는 유예가 있는 것입니다 (Bitmain 공급계약)
                      r"(?:after|within)\s+(?:\w+\s+)?\(?(?:[3-9]\d|[1-9]\d{2})\)?\s+"
                      r"(?:calendar\s+|working\s+|business\s+)?days",
                      # "more than sixty (60) days" — 낱말 숫자 뒤에 괄호 숫자가 옵니다.
                      r"(?:more\s+than|exceed\w*|over|beyond|longer\s+than)\s+(?:\w+\s+)?"
                      r"\(?(?:[3-9]\d|[1-9]\d{2})\)?\s+(?:calendar\s+|working\s+)?days",
                      # 달 단위 유예, 바이어가 새 납기를 준 뒤의 해제 (실제 공급계약)
                      r"\(?\d+\)?\s+months?\b", r"\brevised\s+(?:delivery\s+)?date"),
)

_clause(
    "cover_purchase", "대체 구매 차액을 우리가 무한정 부담", "toxic",
    why="늦거나 안 맞으면 바이어가 **다른 데서 사고 차액을 우리에게 청구**합니다. 값이 "
        "오른 시장에서는 계약금액보다 큰 돈이 됩니다.",
    risk="분할선적 한 회분이 빠지자 바이어가 나머지를 해제하고 대체 구매 차액에 항공 운임까지 "
         "받아 갔습니다(서울고법 2009.7.23. 2008나14857). 원자재가 상승을 이유로 한 면책은 "
         "인정되지 않았고 대체 구매 손해를 물었습니다(CRCICA 2023).",
    text_en="""(지울 문구의 예)
If the Seller fails to deliver on time, the Buyer may purchase substitute goods
from a third party and the Seller shall bear all excess costs.""",
    text_ko="substitute(replacement) goods 와 Seller's cost · Seller shall bear 가 함께 나오고 "
            "**상한이 없으면** 이 조항입니다.",
    detect=[r"(?:purchase|procure|buy|obtain|source)\s+(?:substitute|replacement|equivalent|alternative|similar)\s+"
            r"goods[^.]{0,150}(?:(?:seller|supplier|vendor)'?s?\s+(?:cost|expense|account|risk)"
            r"|(?:seller|supplier)\s+shall\s+(?:bear|pay|reimburse|compensate|be\s+liable))",
            r"\bcover\s+(?:purchases?|costs?)\b[^.]{0,80}(?:seller|supplier)",
            r"(?:대체\s*(?:구매|조달|품)|제3자로부터\s*(?:구매|조달)|다른\s*(?:곳|공급자)(?:에서|로부터)\s*"
            r"(?:구매|조달))[^.]{0,80}(?:차액|추가\s*비용|비용)[^.]{0,30}(?:매도인|공급자)[^.]{0,10}"
            r"(?:부담|배상|지급)" + NO_NEG_KO],
    fix="대체 구매 차액에 **상한(예: 늦은 물품 대금의 10%)**을 두고, 대체 구매 전에 **서면 통지와 "
        "추가 기간**을 주게 합니다. 분할선적이면 해제가 **그 회분에만** 미치게 하세요.",
    avoid=NEGATION + (r"not\s+(?:to\s+)?exceed", r"limited\s+to", r"\bup\s+to\b", r"한도", r"상한"),
)

_clause(
    "one_way_force_majeure", "불가항력이 바이어에게만 적용", "toxic",
    why="불가항력이 **바이어만 면책**하면, 같은 전쟁·봉쇄·감염병에서 우리는 그대로 물립니다.",
    risk="매도인의 불가항력 주장은 판례에서 거의 받아들여지지 않습니다 — 공급사 생산 중단·"
         "통관 문제(서울중앙지법 2014.11.7. 2013가합68479), 수입국 규제(Macromex v. Globex, "
         "2008). 반대로 **매도인에게만** 적용되는 불가항력은 한국 수출자를 지켰습니다"
         "(Standard Retail v. G.S. Global, 봄베이 고등법원 2020).",
    text_en="""(지울 문구의 예)
Force majeure shall excuse only the Buyer's performance. The Seller shall not be
relieved of its obligations by any force majeure event.""",
    text_ko="force majeure 와 only the Buyer, 또는 'Seller shall not be relieved'가 함께 나오면 "
            "이 조항입니다.",
    detect=[r"force\s+majeure[^.]{0,80}\b(?:only|solely|exclusively)\s+(?:to\s+|by\s+|for\s+)?(?:the\s+)?"
            r"(?:buyer|purchaser)",
            r"force\s+majeure[^.]{0,60}(?:apply|available|invoked?)\w*\s+(?:only\s+)?(?:to|by)\s+"
            r"(?:the\s+)?(?:buyer|purchaser)\s+only",
            r"불가항력[^.]{0,60}(?:매수인|바이어)(?:에게만|만|에\s*한하여)[^.]{0,30}(?:적용|면책|원용)"],
    # "Seller shall **not** be relieved" — 부정이 뜻 그 자체입니다. 통지 요건
    # ("… unless notified within 7 days")은 흔한 정상 조항이라 뺍니다.
    strict=[r"(?:seller|supplier)\s+shall\s+not\s+be\s+(?:relieved|excused|released|discharged)[^.]{0,80}"
            r"force\s+majeure(?![^.]*\bunless\b)",
            r"force\s+majeure\s+(?:events?\s+|circumstances?\s+)?shall\s+not\s+"
            r"(?:relieve|excuse|release|discharge)\s+the\s+(?:seller|supplier)(?![^.]*\bunless\b)",
            r"\bno\s+force\s+majeure\s+(?:event\s+)?shall\s+(?:relieve|excuse|release|discharge)\s+the\s+"
            r"(?:seller|supplier)(?![^.]*\bunless\b)",
            r"(?:매도인|공급자)(?:은|는)[^.]{0,40}불가항력[^.]{0,40}"
            r"(?:면책되지\s*(?:않|아니)|책임을\s*면하지\s*못)"],
    fix="불가항력은 **양쪽 모두**에 적용하고, 사유에 **수출허가 거부·제재·원공급사 불이행·"
        "수입국 규제 변경·항만 폐쇄**를 적어 둡니다. 판례는 적혀 있지 않은 사유를 거의 "
        "인정하지 않습니다.",
    avoid=NEGATION,
)

_clause(
    "unilateral_amendment", "바이어가 혼자 조건을 바꿈", "toxic",
    why="바이어가 **통지만으로** 약관·단가·조건을 바꿀 수 있으면, 계약서에 적은 것이 "
        "언제든 달라질 수 있습니다.",
    risk="바이어가 L/C 조건변경으로 단가를 30달러에서 25달러로 깎았는데, 수익자가 거절 "
         "의사를 바로 밝히지 않아 분쟁이 됐습니다(대한상의 무역클레임 상담사례).",
    text_en="""(지울 문구의 예)
The Buyer may amend these terms and conditions at any time by written notice to
the Seller, and such amendments shall bind the Seller.""",
    text_ko="Buyer may amend(modify·change) these terms(prices) 가 나오면 이 조항입니다.",
    detect=[r"(?:buyer|purchaser)\s+(?:may|reserves\s+the\s+right\s+to|shall\s+be\s+entitled\s+to|has\s+the\s+right\s+to)\s+"
            r"(?:unilaterally\s+|at\s+any\s+time\s+)?(?:amend|modify|change|revise|update|vary|alter)\s+"
            r"(?:these|this|the|any)\s+(?:terms|conditions|agreement|contract|purchase\s+terms|prices?|unit\s+prices?)",
            r"(?:매수인|바이어)(?:은|는|이|가)?[^.]{0,20}(?:일방적으로|임의로|언제든지|통지만으로)[^.]{0,30}"
            r"(?:계약|조건|약관|단가|가격)[^.]{0,20}(?:변경|수정)할\s*수\s*있"],
    fix="'계약 변경은 **양 당사자가 서명한 서면**으로만 효력이 있다'로 바꿉니다. 신용장 "
        "조건변경으로 단가·수량이 바뀌면 **받는 즉시 서면으로 거절**하세요(UCP600 제10조).",
    avoid=NEGATION + (r"by\s+mutual", r"both\s+parties", r"signed\s+by\s+both", r"쌍방", r"서면\s*합의"),
)

# ── 독소조항 묶음 (2026-10-03) ──────────────────────────────────────────────
#
# 55개가 한 줄로 늘어서면 읽히지 않습니다. 수출자가 먼저 묻는 것 — **돈을 못
# 받는가, 얼마나 물리는가** — 순서로 묶어 화면과 내려받는 문안에 씁니다.
# 새 독소조항을 넣으면 여기에도 붙이세요(tests/test_contract_toxic_groups.py).
TOXIC_GROUPS = [
    ("payment", "① 대금을 못 받거나 늦게 받음"),
    ("liability", "② 상한 없는 배상"),
    ("quality", "③ 품질·검사"),
    ("termination", "④ 계약을 끊거나 바꿈"),
    ("cost", "⑤ 무역조건·비용 전가"),
    ("ip", "⑥ 기술·지재권·영업 제한"),
    ("dispute", "⑦ 분쟁 해결·언어"),
    ("sanctions", "⑧ 제재·대리점·가공"),
]
TOXIC_GROUP = {
    **dict.fromkeys(("payment_on_resale", "payment_fx_approval", "fx_risk_local",
                     "docs_before_payment", "lc_soft_clause", "payment_retention",
                     "acceptance_signature_payment", "buyer_set_off", "retro_price_deduction",
                     "chargeback_penalty", "on_demand_bond"), "payment"),
    **dict.fromkeys(("unlimited_damages", "uncapped_ld", "own_negligence_indemnity",
                     "us_class_action_pl", "recall_cost", "eu_gdpr_indemnity",
                     "cover_purchase", "open_warranty"), "liability"),
    **dict.fromkeys(("inspection_buyer_sole", "full_return", "full_inspection",
                     "cert_test_cost", "psi_cost_delay"), "quality"),
    **dict.fromkeys(("termination_at_will", "time_essence_cancel", "unilateral_amendment",
                     "spec_change_no_price", "evergreen", "assignment_one_way",
                     "battle_of_forms"), "termination"),
    **dict.fromkeys(("term_conflict", "buyer_nominated_cost", "ddp_no_ior",
                     "tariff_absorption", "eu_epr_cost"), "cost"),
    **dict.fromkeys(("cn_tech_transfer", "cn_trademark_buyer", "ip_assignment", "tooling_free",
                     "one_way_nda", "non_compete_wide", "mfn_price", "exclusive_no_moq",
                     "audit_rights"), "ip"),
    **dict.fromkeys(("foreign_forum", "china_domestic_arb", "us_jury_punitive",
                     "foreign_language_prevails", "one_way_force_majeure"), "dispute"),
    **dict.fromkeys(("ru_sanctions_warranty", "reexport_control", "gulf_agent_lock",
                     "agency_law_eu", "consigned_material_lock"), "sanctions"),
}
_GROUP_ORDER = {group_id: i for i, (group_id, _) in enumerate(TOXIC_GROUPS)}
_GROUP_LABEL = dict(TOXIC_GROUPS)


def toxic_group(key: str) -> tuple[int, str, str]:
    """(순서, id, 소제목). 독소조항이 아니면 묶음 없이 맨 뒤입니다."""

    group_id = TOXIC_GROUP.get(key, "")
    return _GROUP_ORDER.get(group_id, len(TOXIC_GROUPS)), group_id, _GROUP_LABEL.get(group_id, "")


# **이 독소가 있으면 이 보호 조항은 무력합니다.** (2026-10-02)
#
# 실물 보세가공 계약서 제6조는 "직접손해만 배상"으로 한도를 걸었는데, 앞머리에
# "Subject to Article 9" 가 붙어 있고 제9조가 한도 없는 배상입니다. 제6조만
# 보고 '책임 한도 있음'이라고 하면 사용자는 안심합니다.
DEFEATED_BY = {
    "liability_cap": (("unlimited_damages", "own_negligence_indemnity"),
                      "한도가 적혀 있지만, 한도 없는 배상 조항이 함께 있어 밀릴 수 있습니다."),
    "ip": (("ip_assignment", "tooling_free"),
           "금형·도면 조항이 있지만, 상대에게 넘기는 조항이 함께 있습니다."),
    "confidential": (("one_way_nda",), "비밀유지가 있지만 **우리에게만** 걸려 있습니다."),
    "no_set_off": (("buyer_set_off",), "상계 금지가 있지만, 상대의 상계를 허용하는 조항이 함께 있습니다."),
    "claim_period": (("open_warranty",), "클레임 기한이 있지만, 기한 없는 보증 조항이 함께 있습니다."),
    "arbitration": (("foreign_forum",), "중재 조항이 있지만, 상대국 법원 전속관할과 함께 있어 서로 모순됩니다."),
}


def find_in(text: str) -> set[str]:
    """올린 계약서에서 **제 구실을 하는** 조항의 key.

    독소조항은 보이면 들어갑니다. 필수·이익조항은 '적혀 있으나 미정·불리'
    (analyze 의 weak)인 것을 뺍니다 — 그건 있는 것이 아닙니다. (2026-10-02)
    """

    return {key for key, row in analyze(text)["clauses"].items()
            if row["status"] == "present"}


def analyze(text: str) -> dict:
    """조항마다 판정과 근거.

    clauses  {key: {"status": "present"|"weak", "evidence": 근거 문장,
                    "reason": weak 의 까닭}}  — 안 보인 조항은 없습니다.
    context  문서가 맞춘 context 조항의 key (가공계약 조항 등)
    side     Party A/B 계약서에서 우리로 읽은 쪽 (our_side)
    """

    # **줄바꿈을 지웁니다.**
    #
    # 찾는 말은 "price lower than that offered"처럼 여러 낱말입니다. 그런데
    # PDF에서 읽은 계약서는 줄이 꺾여 있어 "than"과 "that" 사이에 줄바꿈이
    # 들어갑니다. 그러면 한 칸(space)을 찾는 규칙이 안 맞아, **실제 계약서에서만
    # 못 잡습니다.** 시험에서는 한 줄로 넣어 잘 잡혔습니다. (2026-09-26)
    body = _drop_table_of_contents(str(text or ""))
    body = _drop_page_furniture(body)
    # **줄 끝에서 하이픈으로 갈린 낱말을 도로 붙입니다.**
    #
    # PDF 는 제 폭대로 줄을 꺾으면서 긴 낱말을 "interrup-\ntion" 처럼 자릅니다.
    # 그대로 두면 "interruption" 을 찾는 규칙이 안 맞습니다. 흔들어 본 결과
    # 다른 왜곡(줄 다시 꺾기·쪽 머리글·대소문자)은 모두 0%인데 이것만
    # 4.5%에서 조항을 놓쳤습니다. (2026-09-26)
    #
    # 낱말이 갈린 경우에만 붙입니다. 뒤가 소문자로 이어질 때만 보므로
    # "CIF-\nBasis" 같은 진짜 붙임표는 그대로 둡니다.
    body = re.sub(r"(?<=[A-Za-z])-\s*\n\s*(?=[a-z])", "", body)
    body = re.sub(r"\s+", " ", body)
    if not body.strip():
        # **쪽 번호·머리글만 있던 글.** 전에는 set() 을 돌려줘 find_in·review 가
        # 500 을 냈습니다("Page 1 of 2" 만 읽힌 스캔본). 같은 모양으로 비워서
        # 내고, empty 로 '못 읽었다'를 알립니다. (2026-10-03)
        return {"clauses": {}, "context": set(), "side": None, "empty": True}
    # 바꿔 읽기 **전에** 정합니다. 바꾼 뒤에는 Party 표지가 없어 못 찾습니다.
    side = our_side(body)
    body = _as_seller(body)
    context = {row["key"] for row in CLAUSES
               if row["context"] and any(re.search(p, body, re.I) for p in row["context"])}
    out: dict[str, dict] = {}
    for row in CLAUSES:
        if row["context"] and row["key"] not in context:
            continue
        # 뜻풀이 문장은 **독소조항 전부**에서 거릅니다. 낱말의 뜻을 적은 것이지
        # 의무를 정한 것이 아닙니다. (2026-10-02)
        avoid = (row.get("avoid") or ())
        if row["category"] == "toxic":
            avoid = avoid + DEFINITION
        best = None
        rules = [(p, avoid) for p in row["detect"]]
        rules += [(p, DEFINITION) for p in row["strict"]]
        for pattern, veto in rules:
            # **자리마다** 봅니다. 첫 자리가 부정문·미정이어도 다른 자리에 진짜가
            # 있을 수 있습니다.
            for hit in re.finditer(pattern, body, re.I | re.S):
                if veto and _vetoed(body, hit.start(), veto):
                    continue
                reason = "" if row["category"] == "toxic" else _weakness(row, body, hit)
                if reason is None:
                    continue
                judged = {"status": "weak" if reason else "present",
                          "evidence": _evidence(body, hit, side), "reason": reason}
                if not reason:
                    best = judged
                    break
                best = best or judged
            if best and best["status"] == "present":
                break
        if best:
            out[row["key"]] = best
    # 짝 독소가 함께 있으면, 보호 조항은 **있어도 무력**합니다.
    #   제6조 "직접손해만 배상" + 제9조 "한도 없이 배상" — 제6조가 제9조에 밀립니다.
    for key, (toxics, reason) in DEFEATED_BY.items():
        mine = out.get(key)
        hits = [t for t in toxics if t in out]
        if mine and mine["status"] == "present" and hits:
            names = ", ".join(by_key(t)["title"] for t in hits)
            mine.update(status="weak", reason=f"{reason} (함께 있는 독소: {names})")
    return {"clauses": out, "context": context, "side": side}


# 찾은 자리 **바로 뒤**의 미정 문구. "Incoterms to be agreed later",
# "Payment terms: TBA". 낱말 셋까지 건너뜁니다 — "Payment **terms** to be advised".
_UNDECIDED_AFTER = re.compile(
    r"^\W{0,3}(?:[\w/]+\W{1,3}){0,3}?"
    r"(?:to\s+be\s+(?:agreed|advised|confirmed|determined|decided|discussed|negotiated|fixed)"
    r"|TB[ADC]\b|추후\s*(?:협의|결정|통지|확정)|미정|협의\s*(?:예정|후\s*결정))", re.I)
# 찾은 자리 **바로 앞**의 부정어. "There shall be **no** price adjustment".
# 바로 앞만 봅니다 — "shall not be liable for delay … force majeure" 는 정상 조항입니다.
_NEG_BEFORE = re.compile(r"\b(?:no|not|without|nor|never)\s+(?:any\s+|the\s+|a\s+|such\s+)?$", re.I)
# 한국어는 부정이 **뒤**에 옵니다. "가격 조정은 **없다**". 조건("없으면")·
# "서면 합의 없이는" 은 부정이 아니라서 좁게 씁니다.
_NEG_AFTER_KO = re.compile(
    r"^\s*(?:은|는|이|가|을|를|도)?\s*(?:없(?:다|음|으며|고|이\s)|두지\s*아니|하지\s*아니|하지\s*않)")


def _scope(body: str, start: int, end: int, reach: int = 150) -> str:
    """찾은 자리가 든 문장. 표처럼 마침표가 없는 글은 앞뒤 reach 자로 자릅니다."""

    left = max(body.rfind(".", 0, start) + 1, start - reach)
    right = body.find(".", end)
    right = min(len(body) if right < 0 else right, end + reach)
    return body[left:right]


def _words(body: str, start: int, end: int) -> str:
    """[start:end] 를 **낱말 경계**에 맞춰 자릅니다 — "s 11 and 13", "proc" 처럼
    낱말 가운데서 끊기지 않게. 문장 처음·끝이면 그대로 둡니다."""

    start, end = max(0, start), min(len(body), end)
    if 0 < start < len(body) and body[start - 1].isalnum() and body[start].isalnum():
        nxt = body.find(" ", start, end)
        start = nxt + 1 if nxt != -1 else start
    if 0 < end < len(body) and body[end - 1].isalnum() and body[end].isalnum():
        prev = body.rfind(" ", start, end)
        end = prev if prev > start else end
    return body[start:end].strip(" ,;:")


def _evidence(body: str, hit, side: dict | None = None) -> str:
    """찾은 자리의 문장. **계약서에 적힌 그대로** 보여 줍니다.

    Party A/B 계약서는 Seller·Buyer 로 바꿔 읽은 글에서 찾으므로, 근거도 바뀐
    글로 나왔습니다("the Seller shall indemnify the Buyer"). 원문 인용이라면서
    원문에 없는 말을 보여 주면 사용자가 계약서에서 그 문장을 못 찾습니다.
    _as_seller 가 넣은 꼴(소문자 the + 대문자 Seller/Buyer)만 되돌립니다. (2026-10-03)
    """

    # **찾은 자리를 중심으로** 자릅니다. 문장 앞에서 260자만 보여 주니, 긴 배상
    # 문장에서 정작 "Party A's own instructions or negligence" 직전에서 잘렸습니다
    # (2026-10-03 브라우저 확인). 찾은 자리의 끝이 꼭 들어가게 합니다.
    left = max(body.rfind(".", 0, hit.start()) + 1, hit.start() - 110)
    stop = body.find(".", hit.end())
    right = min(len(body) if stop < 0 else stop, hit.end() + 110)
    if right - left <= 260:
        text = _words(body, left, right)
    elif hit.end() - hit.start() > 150:
        # 찾은 범위 자체가 길면 **앞과 끝을 함께** — 누가 누구에게("Party B shall
        # indemnify Party A")와 결정적인 끝("… own negligence, without monetary limit").
        head = _words(body, max(left, hit.start() - 30), hit.start() + 110)
        tail = _words(body, hit.end() - 90, min(right, hit.end() + 30))
        text = f"{head} … {tail}"
    else:
        text = "…" + _words(body, max(left, hit.end() - 190), right)[:257]
    if side:
        text = re.sub(r"\bthe Seller\b", side["label"], text)
        text = re.sub(r"\bthe Buyer\b", side["other_label"], text)
    return text if len(text) <= 260 else text[:257] + "…"


def _weakness(row: dict, body: str, hit) -> str | None:
    """필수·이익조항의 찾은 자리가 **제 구실을 못 하면** 그 까닭. 하면 "".
    이 조항이 아예 아니면 None (require 의 "absent")."""

    after = body[hit.end():hit.end() + 60]
    # **같은 문장 안에서만** 봅니다. "Payment: T/T. Packing to be advised." 의
    # 미정은 포장 이야기인데, 결제조건을 '추후 결정'으로 봤습니다. (2026-10-03)
    end = re.search(r"[.;](?:\s|$)", after)
    if end:
        after = after[:end.start()]
    if _UNDECIDED_AFTER.search(after):
        return "적혀 있으나 '추후 결정'입니다. 정해진 내용이 없습니다."
    if not row["neg_ok"]:
        if _NEG_BEFORE.search(body[max(0, hit.start() - 25):hit.start()]):
            return "부정문입니다 — 이 조항이 '없다'고 적혀 있습니다."
        if _NEG_AFTER_KO.search(body[hit.end():hit.end() + 16]):
            return "부정문입니다 — 이 조항이 '없다'고 적혀 있습니다."
    scope = _scope(body, hit.start(), hit.end())
    for pattern, reason in row["weak"]:
        if re.search(pattern, scope, re.I):
            return reason
    if row["require"]:
        # 셋째 칸이 "absent" 면, 필수 요소가 없는 자리는 이 조항이 **아닙니다**
        # (None). "WARRANTY: 12 months from the date of shipment" 는 선적 조항이
        # 적혀 있으나 부족한 것이 아니라, 선적을 **언급**만 한 것입니다.
        # '부족'으로 내면 보증 조항을 선적 조항이라며 근거로 보여 줍니다. (2026-10-03)
        patterns, reason = row["require"][:2]
        absent = row["require"][2:] == ("absent",)
        if not any(re.search(p, scope, re.I) for p in patterns):
            return None if absent else reason
    return ""


# ── 우리 쪽 정하기 ──────────────────────────────────────────────────────────
#
# **우리는 수출자, 곧 매도인입니다.** (2026-10-02 사용자 확인)
#
# 규칙은 방향을 Seller·Buyer 로 봅니다 — "the Seller shall indemnify the Buyer"
# 는 독소, 거꾸로는 유리. 그런데 가공무역·위탁 계약서는 "Party A / Party B" 로만
# 부릅니다. 그러면 방향을 못 봐서, 우리에게 유리한 조항도 똑같이 짚습니다.
#
# 앞머리의 당사자 정의에서 **한국에 있는 쪽이 하나뿐일 때만** 그쪽을 매도인으로
# 바꿔 읽습니다. 둘 다 한국이거나 둘 다 아니면 건드리지 않습니다 — 틀리게
# 정하느니 정하지 않는 편이 낫습니다.
#
# 국문의 갑·을은 다루지 않습니다. "을" 은 조사와 글자가 같아 바꾸면 문장이
# 망가집니다.

_PARTY_DEF = re.compile(
    r"(?P<name>[A-Z][^;:\n]{1,120}?),?\s*\(?\s*hereinafter\s+(?:referred\s+to\s+as\s+|called\s+)?"
    r"(?:the\s+)?[\"“']?(?P<label>Party\s+[A-Z]|(?:First|Second)\s+Party)\b[\"”']?")
_KOREA_HQ = re.compile(r"\b(?:Republic\s+of\s+Korea|South\s+Korea|Korea|Seoul|Busan|Incheon)\b"
                       r"|대한민국|한국|서울|부산|인천")
# 주소 뒤에서 본문이 시작하는 자리 — "Korea. Whereas it …". "U.S.A., and" 나
# "Co., Ltd." 의 마침표에서는 끊지 않습니다.
_SENTENCE_START = re.compile(r"\.\s+(?=[A-Z][a-z]+\s+[a-z])")


def _clean_name(raw: str) -> str:
    """"San Francisco, U.S.A., and Haneul Weaving Co., Ltd." → 회사 이름만."""

    name = re.split(r"\b(?:between|and)\s+", raw)[-1]
    # "Hana Co., Ltd. of Busan, Korea" — 주소가 이름 뒤에 붙는 꼴
    name = re.split(r",?\s+(?:of|a company|having|with its)\s+(?=[A-Z]|its|principal)", name)[0]
    return name.strip(" ,")


def our_side(text: str) -> dict | None:
    """당사자 정의에서 우리(한국 수출자) 쪽을 찾습니다. 못 정하면 None.

    주소는 정의 **뒤**("hereinafter … Party B, having its head office at Seoul")
    에도, **앞**("ABC Co., Ltd. of Seoul, Korea (hereinafter Party B)")에도
    옵니다. 뒤쪽을 먼저 보고, 한 곳으로 안 갈리면 앞쪽을 봅니다.
    """

    body = re.sub(r"\s+", " ", str(text or ""))[:6000]
    defs = list(_PARTY_DEF.finditer(body))
    labels = {re.sub(r"\s+", " ", d.group("label")) for d in defs}
    if len(defs) != 2 or len(labels) != 2:
        return None
    names = [_clean_name(d.group("name")) for d in defs]
    name_at = [d.end("name") - len(d.group("name").rstrip(" ,")) +
               d.group("name").rstrip(" ,").rfind(n) for d, n in zip(defs, names)]

    after_end = name_at[1]
    stop = _SENTENCE_START.search(body, defs[1].end())
    after = [(defs[0].end(), after_end),
             (defs[1].end(), min(stop.start() if stop else len(body), defs[1].end() + 250))]
    before = [(name_at[0], defs[0].start("label")), (name_at[1], defs[1].start("label"))]
    korean = []
    for spans in (after, before):
        korean = [i for i, (a, b) in enumerate(spans) if a < b and _KOREA_HQ.search(body[a:b])]
        if len(korean) == 1:
            break
    if len(korean) != 1:
        return None
    i = korean[0]
    return {"label": re.sub(r"\s+", " ", defs[i].group("label")), "name": names[i],
            "other_label": re.sub(r"\s+", " ", defs[1 - i].group("label")),
            "other_name": names[1 - i]}


def _as_seller(body: str) -> str:
    return as_seller_with(our_side(body), body)


def as_seller_with(side: dict | None, body: str) -> str:
    """정해 둔 우리 쪽(side)으로 글을 바꿔 읽습니다. 조항 하나만 바꿀 때 씁니다
    — 조항 하나에는 당사자 정의가 없어 our_side 를 다시 못 구합니다. (2026-10-03)"""

    if not side:
        return body
    for label, role in ((side["label"], "the Seller"), (side["other_label"], "the Buyer")):
        words = r"\s+".join(map(re.escape, label.split()))
        body = re.sub(rf"\b(?:the\s+)?{words}\b", role, body)
    return body


def _vetoed(body: str, pos: int, avoid) -> bool:
    """찾은 자리가 든 **문장**에 avoid 말이 있는가.

    문장 경계는 마침표로 봅니다. 그래서 "U.S." 같은 줄임말에서 일찍 끊길 수
    있는데, 부정말을 찾는 일에는 해롭지 않습니다 — 창이 좁아질 뿐입니다.
    """

    start = body.rfind(".", 0, pos) + 1
    end = body.find(".", pos)
    sentence = body[start:(len(body) if end < 0 else end)]
    return any(re.search(word, sentence, re.I) for word in avoid)
