"""전문가 점검(2026-10-04)에서 나온 판정 오류 — 계약서 8종을 써서 돌려 본 결과.

  오탐  상한 있는 지연배상금 · 판매점(대리인 아님)·바이어 보상 배제를 'EU 상업대리인'
        · 전액 선수금인데 B/L 직송 · 예고 60일 자동연장 · 반품 운임을 '인증 비용'
        · 홍콩 중재를 '중국 국내' · 매수인이 위험을 지는 'notwithstanding' · 독일 DDP
  미탐  걸프 독점과 해지 제한이 다른 조 · 대리점 등록 의무 · 델라웨어 법원
        · 'cancel the PO' · 기간을 아예 안 적은 하자보증
  필수·이익  있는데 없다(수출용 포장·국문 결제·선적·검사), 없는데 있다(낱말만)
        · 바이어만 보호하는 책임 한도 · 'including without limitation' 을 '한도 없음'
        · 짝 독소가 있어도 정상으로 남는 필수조항 · 이 계약에 맞지 않는 이익조항 권유
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses
from app.services import contract_clause_service as service

H = "SALES CONTRACT\n"


def _found(line: str) -> set[str]:
    return contract_clauses.find_in(H + line)


def _status(line: str, key: str) -> str:
    row = contract_clauses.analyze(H + line)["clauses"].get(key)
    return row["status"] if row else "absent"


# ── 오탐 ────────────────────────────────────────────────────────────────────
SAFE = [
    ("uncapped_ld", "The Seller shall pay liquidated damages of 1% of the value of the delayed "
                    "Goods for each full week of delay, up to a maximum of 5% of the value of the "
                    "delayed Goods."),
    ("uncapped_ld", "제9조 매도인은 지연 1주마다 지연 물품 대금의 1%를 지연배상금으로 지급하되, 그 총액은 "
                    "지연 물품 대금의 5%를 넘지 아니한다."),
    ("agency_law_eu", "The Distributor buys and resells in its own name and is not a commercial "
                      "agent of the Seller."),
    ("agency_law_eu", "Where performance is suspended by force majeure, the Buyer shall not be "
                      "entitled to any compensation for the delay."),
    ("agency_law_eu", "If the Buyer fails to open the L/C on time, the Seller may cancel this "
                      "Contract and the Buyer shall not be entitled to any compensation."),
    ("docs_before_payment", "Payment: 100% T/T in advance before shipment. The Seller shall send "
                            "the original Bill of Lading directly to the Buyer by courier "
                            "immediately after shipment."),
    ("evergreen", "This Contract shall be automatically renewed for successive one-year periods "
                  "unless either party gives written notice at least sixty (60) days before expiry."),
    ("evergreen", "This Contract shall be automatically renewed for successive one-year periods "
                  "unless either party gives two (2) months' written notice."),
    ("cert_test_cost", "If any part of a shipment fails inspection, the Buyer may reject the "
                       "entire shipment and the Seller shall bear all return freight, duties and storage."),
    ("china_domestic_arb", "All disputes shall be submitted to CIETAC Hong Kong Arbitration "
                           "Center for arbitration in Hong Kong."),
    ("china_domestic_arb", "All disputes shall be settled by arbitration in Seoul under the rules "
                           "of the Korean Commercial Arbitration Board. The courts of Shanghai "
                           "shall have exclusive jurisdiction."),
    ("term_conflict", "Notwithstanding the trade term, the Buyer shall bear all risks and costs "
                      "from the time the Goods are handed over at the Seller's factory."),
    ("agency_protection", "The Seller appoints the Buyer as its non-exclusive distributor in Japan."),
]


@pytest.mark.parametrize("key,line", SAFE, ids=[f"{k}:{s[:26]}" for k, s in SAFE])
def test_전문가가_정상이라고_본_문장은_짚지_않는다(key, line):
    assert key not in _found(line)


# ── 미탐 ────────────────────────────────────────────────────────────────────
GULF = ("EXCLUSIVE DISTRIBUTION AGREEMENT\n1. The Seller grants the Buyer the exclusive right to "
        "import and distribute the Products in the UAE.\n2. Prices are set out in Annex 1.\n"
        "3. This Agreement shall be automatically renewed each year. This Agreement may not be "
        "terminated without the Buyer's written consent.\n")

MISSED = [
    ("gulf_agent_lock", GULF),
    ("gulf_agent_lock", "The Distributor shall register this Agreement with the Ministry of "
                        "Economy of the UAE as a commercial agency within thirty (30) days."),
    ("us_jury_punitive", "The parties submit to the exclusive jurisdiction of the state and federal "
                         "courts located in Wilmington, Delaware."),
    ("time_essence_cancel", "If any shipment is delayed by more than five (5) days, Buyer may "
                            "cancel the PO without liability."),
    ("open_warranty", "The Seller warrants that the Goods shall be free from defects in material "
                      "and workmanship and fit for the Buyer's intended purpose. These warranties "
                      "shall survive inspection, acceptance and payment."),
]


@pytest.mark.parametrize("key,doc", MISSED, ids=[f"{k}:{d[:26]}" for k, d in MISSED])
def test_전문가가_위험하다고_본_문장을_짚는다(key, doc):
    assert key in contract_clauses.find_in(doc if doc.startswith(("EXCLUSIVE",)) else H + doc)


def test_보증_기간을_적으면_기간_없는_보증이_아니다():
    doc = ("The Seller warrants that the Goods shall be free from defects in material and "
           "workmanship. The warranty period shall be twelve (12) months from the date of shipment.")
    assert "open_warranty" not in _found(doc)


# ── 필수·이익: 있는데 '없다' ─────────────────────────────────────────────────
PRESENT = [
    ("packing", "Packing: in cartons on pallets suitable for ocean transport."),
    ("packing", "제6조 물품은 수출용 표준 포장으로 한다."),
    ("goods", "Product: Industrial sewing machine, Model MC-220. Quantity: 500,000 pcs. "
              "Unit price: USD 0.42."),
    ("inspection", "제7조 매수인은 물품 도착 후 14일 이내에 검사하여야 하며, 그 기간 내에 서면 이의가 "
                   "없으면 합격한 것으로 본다."),
    ("payment", "제3조 매수인은 선적일로부터 30일 이내에 전신환으로 대금을 지급한다."),
    ("shipment", "제4조 매도인은 2026년 11월 30일까지 부산항에서 선적한다."),
    ("min_order", "The Buyer shall purchase not less than 10,000 units per year."),
    ("min_order", "The Buyer shall purchase a minimum annual volume of USD 500,000."),
    ("no_set_off", "제8조 매수인은 어떠한 사유로도 대금을 상계하거나 공제할 수 없다."),
]


@pytest.mark.parametrize("key,line", PRESENT, ids=[f"{k}:{s[:26]}" for k, s in PRESENT])
def test_적어_둔_필수_이익조항을_있다고_본다(key, line):
    assert _status(line, key) == "present"


# ── 필수·이익: 없는데 '있다' ─────────────────────────────────────────────────
NOT_PRESENT = [
    ("shipment", "Payment: T/T within 30 days after the shipment date."),
    ("inspection", "Article 9 Quality and Inspection. The Seller warrants that the Goods are free "
                   "from defects without time limitation."),
    ("suspend_delivery", "제4조 매도인은 선수금 수령 후 60일 이내에 선적한다."),
    ("lc_deadline", "Payment by irrevocable letter of credit payable at 180 days after B/L date, "
                    "to be opened by the Buyer through a prime bank."),
]


@pytest.mark.parametrize("key,line", NOT_PRESENT, ids=[f"{k}:{s[:26]}" for k, s in NOT_PRESENT])
def test_낱말만_있는_필수_이익조항은_있다고_하지_않는다(key, line):
    assert _status(line, key) != "present"


def test_선적_전_며칠까지인_신용장_개설_기한은_있다():
    line = ("The Buyer shall cause an irrevocable letter of credit to be opened at least thirty "
            "(30) days before the shipment date.")
    assert _status(line, "lc_deadline") == "present"


# ── 책임 한도 ───────────────────────────────────────────────────────────────
def test_바이어만_보호하는_책임_한도는_우리_한도가_아니다():
    line = ("In no event shall Buyer be liable to Seller for any amount, and Buyer's aggregate "
            "liability shall not exceed the amount paid under this Order.")
    assert _status(line, "liability_cap") == "weak"


def test_including_without_limitation_은_한도_없음이_아니다():
    line = ("The Seller shall indemnify the Buyer against third party claims to the extent caused "
            "by the Seller's breach, including without limitation reasonable legal fees, subject "
            "to the limitation of liability in Clause 12.")
    row = contract_clauses.analyze(H + line)["clauses"].get("liability_cap")
    assert not row or "없다" not in row.get("reason", "")


# ── 짝 독소가 있으면 필수조항은 무력 ───────────────────────────────────────────
@pytest.mark.parametrize("must,line", [
    ("force_majeure", "Force majeure shall excuse only the Buyer's performance."),
    ("arbitration", "All disputes shall be finally settled by arbitration administered by the "
                    "China International Economic and Trade Arbitration Commission in Beijing."),
    ("inspection", "Inspection shall be made at the port of destination and the Buyer's "
                   "inspection results shall be final and binding on the Seller."),
])
def test_짝_독소가_있으면_필수조항은_무력이다(must, line):
    assert _status(line, must) == "weak"


# ── 판정 화면(review) ───────────────────────────────────────────────────────
def test_CIP_인데_ICC_C_면_보험이_부족하다():
    doc = H + ("Price: CIP Chicago, Incoterms 2020. Insurance: the Seller shall insure the Goods for "
               "110% of the invoice value against Institute Cargo Clauses (C).")
    result = service.review(doc, "CIP")
    assert "insurance" in {row["key"] for row in result["weak"]}


def test_외국법이_준거법이면_확인하라고_한다():
    result = service.review(H + "This Contract shall be governed by the laws of the People's "
                                "Republic of China.", "FOB")
    assert "governing_law" in {row["key"] for row in result["weak"]}


def test_한국법이_준거법이면_그대로다():
    result = service.review(H + "This Contract shall be governed by the laws of the Republic of "
                                "Korea.", "FOB")
    assert "governing_law" not in {row["key"] for row in result["weak"]}


def test_TT_계약에는_신용장_이익조항을_권하지_않는다():
    result = service.review(H + "Payment: 30% T/T in advance and 70% T/T against copy of B/L.", "FOB")
    gains = {row["key"] for row in result["gain"]}
    assert not gains & {"lc_deadline", "lc_conformity"}
    assert not gains & {"agency_protection", "min_order", "deemed_acceptance"}


def test_신용장_계약에는_신용장_이익조항을_권한다():
    result = service.review(H + "Payment by irrevocable L/C at sight.", "FOB")
    assert "lc_conformity" in {row["key"] for row in result["gain"]}


def test_독일_DDP_는_현지_수입자_문제로_단정하지_않는다():
    doc = H + ("Delivery shall be DDP Hamburg, Incoterms 2020, with the Seller responsible for "
               "import clearance, duties and local taxes.")
    assert "ddp_no_ior" not in {row["key"] for row in service.review(doc, "DDP", "DE")["toxic"]}
    assert "ddp_no_ior" in {row["key"] for row in service.review(doc, "DDP", "BR")["toxic"]}


def test_도착국_주의_조항을_상담_답변에도_적는다():
    result = service.review(H + "Payment by T/T.", "FOB", "AE")
    text = service.as_text(result | {"summary": ""})
    assert "도착국" in text and "등록 대리인" in text


# ── 문구 ────────────────────────────────────────────────────────────────────
def test_오탈자가_없다():
    words = "\n".join(str(v) for row in contract_clauses.CLAUSES for v in row.values())
    for bad in ("팔는데", "챠지백"):
        assert bad not in words, bad


def test_조항_이름을_두_번_쓰지_않는다():
    import re

    keys = [row["key"] for row in contract_clauses.CLAUSES]
    rows = service.checklist("CIF")
    for group in rows.values():
        for row in group:
            for field in ("why", "risk", "text_ko", "fix"):
                text = row[field]
                assert not re.search(r"’\s*\(", text), (row["key"], field, text[:120])
                assert not re.search(r"조항\s+(?:" + "|".join(keys) + r")\b", text), (row["key"], field)


def test_재수출_통제_문안은_빼라고_하지_않는다():
    body = service.clause_text(["reexport_control"])
    assert "넣는 것이 아니라 빼는 것" not in body
