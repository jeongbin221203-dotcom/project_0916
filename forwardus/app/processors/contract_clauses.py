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


def _clause(key, title, category, why, risk, text_en, text_ko, detect,
            applies=("always",), fix=""):
    CLAUSES.append({
        "key": key, "title": title, "category": category, "why": why, "risk": risk,
        "text_en": text_en.strip(), "text_ko": text_ko.strip(),
        "detect": tuple(detect), "applies": tuple(applies), "fix": fix,
    })


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
            r"물품\s*의?\s*명세", r"품명[^.]{0,30}(규격|수량|HS)"],
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
    detect=[r"\bpayment\b", r"letter of credit", r"\bL/?C\b", r"\bT/?T\b", r"결제\s*조건"],
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
    detect=[r"\bshipment\b", r"partial shipment", r"trans?[hs]ipment", r"선적\s*조건"],
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
    detect=[r"\binspection\b", r"certificate of inspection", r"검사\s*(기관|조건|증명)"],
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
    detect=[r"\binsurance\b", r"\bICC\s*\(", r"보험\s*(조건|금액|부보)"],
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
    detect=[r"force majeure", r"acts? of god", r"불가항력"],
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
    detect=[r"governing law", r"\bCISG\b", r"준거법"],
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
    detect=[r"retention of title", r"title .{0,30}shall pass",
            r"reservation of ownership", r"소유권\s*유보"],
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
    detect=[r"late payment", r"interest at", r"overdue", r"지연\s*이자", r"연체\s*이자"],
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
    detect=[r"price adjustment", r"price review", r"exchange rate .{0,40}(move|fluctuat)",
            r"가격\s*조정"],
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
    detect=[r"limitation of liability", r"aggregate liability", r"consequential",
            r"책임\s*한도", r"손해배상\s*한도"],
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
    detect=[r"export licen[cs]e", r"export control", r"수출\s*허가"],
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
    detect=[r"\btooling\b", r"\bmou?lds?\b", r"intellectual property", r"금형", r"도면"],
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
    detect=[r"minimum (order|purchase)", r"\bMOQ\b", r"cancellation charge", r"최소\s*주문"],
)

# ── 독소조항 ────────────────────────────────────────────────────────────────

_clause(
    "unlimited_damages", "무제한 손해배상", "toxic",
    why="상한이 없는 배상 약속은 거래 규모와 무관하게 회사를 무너뜨릴 수 있습니다.",
    risk="송장 1만 달러짜리 건에서 바이어의 영업손실 전부를 물게 됩니다.",
    text_en="""(지울 문구의 예)
The Seller shall indemnify the Buyer against any and all losses, damages and
expenses of whatever nature, including loss of profit, without limitation.""",
    text_ko="without limitation · any and all · loss of profit 이 함께 나오면 이 조항입니다.",
    detect=[r"without limitation", r"any and all (losses|damages)",
            r"unlimited liability",
            r"무제한\s*(으로)?[^.]{0,6}(배상|책임)",
            r"(한도|상한|제한)[^.]{0,3}없이[^.]{0,30}배상",
            r"배상[^.]{0,15}(한도|상한)[^.]{0,6}없"],
    fix="책임 한도(Limitation of Liability) 조항을 넣어 **송장 금액 상한**과 **간접손해 배제**로 바꿔 달라고 하세요.",
)

_clause(
    "termination_at_will", "바이어의 일방적 해지권", "toxic",
    why="상대가 언제든 이유 없이 끊을 수 있으면, 우리가 들인 준비 비용은 전부 우리 손해입니다.",
    risk="원자재를 사 두고 생산에 들어간 뒤 해지 통보를 받습니다.",
    text_en="""(지울 문구의 예)
The Buyer may terminate this Contract at any time for convenience upon written
notice, without liability.""",
    text_ko="for convenience · at any time · without liability 가 붙어 있으면 이 조항입니다.",
    detect=[r"terminate.{0,60}for convenience", r"at any time.{0,40}without (liability|cause)",
            r"일방적으로\s*해지", r"사유[^.]{0,10}불문[^.]{0,40}해지",
            r"언제든지[^.]{0,40}해지", r"이유\s*없이[^.]{0,30}해지",
            r"임의\s*로[^.]{0,20}해지"],
    fix="해지에 **사유와 예고기간**을 붙이고, 생산 착수 뒤에는 **취소 수수료**를 물도록 바꿉니다.",
)

_clause(
    "foreign_forum", "상대국 법원 전속관할", "toxic",
    why="상대 나라 법원에서 그 나라 법으로 다투면, 비용과 시간에서 우리가 크게 불리합니다.",
    risk="이겨도 집행에 몇 년이 걸리고, 변호사 비용이 청구금액을 넘습니다.",
    text_en="""(지울 문구의 예)
The courts of <BUYER'S COUNTRY> shall have exclusive jurisdiction over any
dispute arising out of this Contract.""",
    text_ko="exclusive jurisdiction 과 상대국 이름이 함께 나오면 이 조항입니다. 중재 조항과 **같이** 있으면 서로 모순됩니다.",
    detect=[r"exclusive jurisdiction", r"courts? of .{0,40}shall have",
            r"전속\s*적?[^.]{0,4}관할", r"관할\s*법원[^.]{0,30}(매수인|바이어)"],
    fix="**중재(KCAB, 서울)** 로 바꾸거나, 최소한 **제3국 중재**로 바꿔 달라고 하세요.",
)

_clause(
    "payment_on_resale", "재판매 대금 수령 조건부 결제", "toxic",
    why="바이어가 팔아야 우리가 받는 구조입니다. 안 팔리면 영영 못 받습니다.",
    risk="사실상 위탁판매인데 계약서는 매매로 되어 있어, 물건도 돈도 없는 상태가 됩니다.",
    text_en="""(지울 문구의 예)
Payment shall be made within 30 days after the Buyer receives payment from its
end customer.""",
    text_ko="after the Buyer receives payment · upon resale 이 나오면 이 조항입니다.",
    detect=[r"after the buyer .{0,20}receive[sd]? payment", r"upon resale",
            r"from its (end )?customer",
            r"재판매[^.]{0,30}(대금|수령|지급)",
            r"최종\s*(고객|수요자|구매자)[^.]{0,30}(대금|수령|지급)"],
    fix="**선적일 또는 B/L일 기준**으로 기한을 바꾸고, 안 되면 L/C나 수출보험으로 막으세요.",
)

_clause(
    "open_warranty", "기간 제한 없는 하자보증", "toxic",
    why="보증 기간이 없으면 몇 년 뒤 클레임에도 대응해야 합니다.",
    risk="3년 전 선적분으로 전량 교체를 요구받습니다.",
    text_en="""(지울 문구의 예)
The Seller warrants the Goods against any defect without time limitation.""",
    text_ko="보증에 **기간**과 **범위**가 없으면 이 조항입니다.",
    detect=[r"warrant.{0,80}without (any )?(time )?limit",
            r"perpetual warranty", r"무기한\s*(보증|하자)"],
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
    detect=[r"liquidated damages", r"penalt(y|ies) .{0,30}per day", r"지연\s*배상금"],
    fix="“**총 계약금액의 5%를 넘지 않는다**”는 상한 문장을 반드시 붙이세요.",
)

_clause(
    "term_conflict", "인코텀즈와 어긋나는 비용·위험 문구", "toxic",
    why="“FOB인데 도착지까지 위험은 판매자가 진다” 같은 문장은 조건을 통째로 뒤집습니다.",
    risk="FOB 가격을 받고 DAP 책임을 지게 됩니다.",
    text_en="""(살펴볼 문구의 예)
Notwithstanding the trade term, the Seller shall bear all risks and costs until
the Goods are delivered to the Buyer's warehouse.""",
    text_ko="notwithstanding the trade term · regardless of Incoterms 가 보이면 그 뒤를 꼭 읽으세요.",
    detect=[r"notwithstanding .{0,40}(trade term|incoterms)",
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
    detect=[r"automatically renew", r"successive .{0,30}periods", r"자동\s*(연장|갱신)"],
    fix="예고기간을 **30~60일**로 줄이거나, 자동 연장을 빼고 **합의 연장**으로 바꾸세요.",
)

_clause(
    "mfn_price", "최혜대우 가격 조항 (MFN)", "toxic",
    why="다른 어느 바이어에게도 이보다 싸게 팔 수 없게 묶는 조항입니다.",
    risk="신규 거래처에 판촉가를 주면 이 바이어에게 소급해서 차액을 물어 줘야 합니다.",
    text_en="""(살펴볼 문구의 예)
The Seller shall not sell the Goods to any third party at a price lower than
that offered to the Buyer, and shall refund the difference if it does so.""",
    text_ko="most favoured · no less favourable · price lower than 이 나오면 이 조항입니다.",
    detect=[r"most favou?red", r"no less favou?rable",
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
    detect=[r"reject the entire", r"return freight",
            r"전량[^.]{0,6}반품", r"전부[^.]{0,6}반품",
            r"반송\s*(운임|비용)[^.]{0,30}매도인"],
    fix="**불량분만 교체·감액**으로 바꾸고, 불합격 판정은 **선적지 검사기관**이 하도록 하세요.",
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


def find_in(text: str) -> set[str]:
    """올린 계약서에서 **보이는** 조항의 key.

    보인다/안 보인다만 말합니다. 보인다고 해서 그 조항이 우리에게 유리하게
    쓰여 있다는 뜻은 아닙니다.
    """

    # **줄바꿈을 지웁니다.**
    #
    # 찾는 말은 "price lower than that offered"처럼 여러 낱말입니다. 그런데
    # PDF에서 읽은 계약서는 줄이 꺾여 있어 "than"과 "that" 사이에 줄바꿈이
    # 들어갑니다. 그러면 한 칸(space)을 찾는 규칙이 안 맞아, **실제 계약서에서만
    # 못 잡습니다.** 시험에서는 한 줄로 넣어 잘 잡혔습니다. (2026-09-26)
    body = _drop_page_furniture(str(text or ""))
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
        return set()
    found = set()
    for row in CLAUSES:
        for pattern in row["detect"]:
            if re.search(pattern, body, re.I | re.S):
                found.add(row["key"])
                break
    return found
