"""올린 파일이 **계약서인가 오퍼시트인가**. (2026-09-28)

왜 중요한가
  이 판정이 길을 가릅니다.
    계약서로 보면  -> 조항을 살펴보고, **서류 칸은 통째로 비웁니다**
    아니면        -> 서류 읽기로 가서 칸을 채웁니다

  오퍼시트를 계약서로 잘못 보면 화면에 이렇게 뜹니다.
      "업로드해주신 계약서에서 아래 13가지 정보가 누락되어 있습니다"
  같은 파일을 서류 읽기로 넣으면 31칸이 다 차는데도요.

무엇이 잘못됐었나
  제목이 없으면 조항 4개로 계약서라고 봤습니다. 그런데 오퍼시트에서 걸린
  조항이 incoterms · insurance · payment · shipment 였습니다.
  **어느 무역서류에나 있는 것들입니다.** 그래서 오퍼시트가 전부 계약서가 됐습니다.

  놓치는 것보다 잘못 잡는 것이 나쁩니다.
    계약서를 놓치면   조항을 못 짚어 주지만 상담은 됩니다
    잘못 보면        멀쩡히 읽히는 서류의 칸이 통째로 비어 버립니다
"""

from __future__ import annotations

import pytest

from app.services import contract_clause_service as service

# 오퍼시트·송장이 늘 갖는 말. 이것만으로 계약서가 되면 안 됩니다.
OFFER_SHEET = """FIRM OFFER
HONG KIL DONG CO., LTD.
Seoul, Republic of Korea
We make the following firm offer on the terms stated below:
Payment    T/T (telegraphic transfer), 100% in advance.
Shipment   Within 60 calendar days after receipt of full T/T payment.
Shipping port   Busan, Republic of Korea
Destination     Port of Istanbul, Turkey
Trade term      CIF Port of Istanbul, Turkey - Incoterms 2020
Packing    Each umbrella in a polybag; 50 PCS per export carton. Total: 40 cartons.
Remarks    Prices include ocean freight and insurance to the named destination.
           Minimum order: 2,000 PCS per shipment.
Item UMB-01  1,200 PCS  4.50  5,400.00
Item UMB-02    800 PCS  6.50  5,200.00
TOTAL 40 cartons x 50 PCS  2,000 PCS  10,600.00
"""

REAL_CONTRACT = """SALES CONTRACT
This contract is made and agreed by and between the parties concerned.
1. GOVERNING LAW: This Contract shall be governed by the laws of the Republic of Korea.
2. ARBITRATION: All disputes shall be finally settled by arbitration in Seoul
   under the rules of KCAB INTERNATIONAL.
3. FORCE MAJEURE: Neither party shall be liable for acts of God, war or strike.
4. TERMINATION: Either party may terminate this Contract upon 30 days written notice.
5. Each party shall provide the commercial invoice, packing list, and transport
   documents required for customs clearance.
6. PAYMENT by irrevocable letter of credit at sight.
7. SHIPMENT: latest 30 November. Partial shipment allowed.
"""


def test_오퍼시트를_계약서로_보지_않는다():
    """가격조건·결제·선적·보험은 장사 서류면 다 있습니다."""

    assert service.looks_like_contract(OFFER_SHEET) is False


def test_진짜_계약서는_잡는다():
    """준거법·중재·해지·불가항력이 있으면 계약서입니다."""

    assert service.looks_like_contract(REAL_CONTRACT) is True


def test_계약서가_다른_서류를_언급해도_계약서다():
    """**제목은 머리에서만 찾습니다.**

    계약서는 본문에서 "commercial invoice, packing list" 같은 다른 서류를
    언급합니다. 본문 전체를 뒤지면 그것에 걸려 진짜 계약서를 놓칩니다.
    (2026-09-28 — 본문 2,038번째 글자의 "commercial invoice" 에 걸렸습니다)
    """

    assert "commercial invoice" in REAL_CONTRACT.lower()
    assert "packing list" in REAL_CONTRACT.lower()
    assert service.looks_like_contract(REAL_CONTRACT) is True


@pytest.mark.parametrize("title", [
    "OFFER SHEET", "FIRM OFFER", "QUOTATION", "PROFORMA INVOICE",
    "COMMERCIAL INVOICE", "PACKING LIST", "BILL OF LADING", "CERTIFICATE OF ORIGIN",
])
def test_스스로_적어_둔_이름을_믿는다(title):
    """머리에 무엇이라고 적혀 있으면 그 말을 믿습니다. 조항이 몇 개든요."""

    body = title + "\n" + REAL_CONTRACT[len("SALES CONTRACT"):]
    assert service.looks_like_contract(body) is False


def test_짧은_인용은_계약서가_아니다():
    """한 조항만 물어본 것은 질문이지 계약서가 아닙니다."""

    assert service.looks_like_contract("준거법은 한국법으로 하고 중재는 대한상사중재원") is False


def test_기능을_내렸으면_계약서_길로_안_간다(app, monkeypatch):
    """화면에서 내린 기능(CONTRACT_CLAUSES_ON=0)의 답이 대화창에 나오면 안 됩니다.

    /contract/* 는 404 인데 올린 파일은 조항 점검으로 가고 있었습니다.
    그때 서류 칸이 통째로 비어 "13가지가 누락되었습니다"가 떴습니다.
    """

    from flask import current_app

    from app.services import attachment_service

    body = REAL_CONTRACT.encode("utf-8")

    # 켜 두면 계약서로 보고 조항을 살펴봅니다. (.txt 라야 글자로 읽힙니다)
    current_app.config["CONTRACT_CLAUSES_ON"] = True
    on = attachment_service._contract_answer("계약서.txt", body, "")
    assert on is not None and on["document"]["document_type"] == "contract"

    # 내렸으면 그 길로 안 갑니다. 글자 파일은 거절하고, PDF 는 서류 읽기로 갑니다.
    current_app.config["CONTRACT_CLAUSES_ON"] = False
    with pytest.raises(Exception):
        attachment_service._contract_answer("계약서.txt", body, "")
    assert attachment_service._contract_answer("계약서.pdf", body, "") is None


# 제목이 없는 서류 — 조항 개수로만 가려야 하는 자리입니다.
UNTITLED_OFFER = """HONG KIL DONG CO., LTD.
Seoul, Republic of Korea
We are pleased to quote as follows:
Payment    T/T 100% in advance before shipment.
Shipment   Within 60 calendar days after receipt of payment.
Trade term CIF Port of Istanbul, Turkey - Incoterms 2020
Insurance  Prices include ocean freight and insurance to the named destination.
Inspection Seller's pre-shipment inspection to be final.
Packing    50 PCS per export carton. Total: 40 cartons.
Minimum order: 2,000 PCS per shipment.
Price adjustment: subject to change on raw material cost.
"""


def test_제목이_없어도_장사_조항만으로는_계약서가_아니다():
    """**이것이 원래 문제였습니다.**

    걸린 조항이 incoterms · insurance · payment · shipment · inspection ·
    min_order · price_adjust — 전부 장사 서류면 다 있는 것입니다.
    제목이 없으면 조항 4개로 계약서라고 보던 규칙에 그대로 걸렸습니다.

    (제목이 있는 서류는 NOT_CONTRACT_TITLES 가 먼저 막아 주므로, 조항을
     좁힌 것이 실제로 듣는지는 **제목 없는 서류로만** 잴 수 있습니다.
     2026-09-28 되돌림 검사에서 드러남)
    """

    from app.processors import contract_clauses

    everyday = set(contract_clauses.find_in(UNTITLED_OFFER))
    assert len(everyday) >= 4, f"장사 조항이 넷은 걸려야 시험이 뜻이 있습니다: {sorted(everyday)}"
    assert not (everyday & service.CONTRACT_ONLY_CLAUSES), sorted(everyday)
    assert service.looks_like_contract(UNTITLED_OFFER) is False


def test_제목이_없어도_계약서다운_조항이_많으면_계약서다():
    """고치다가 제목 없는 진짜 계약서를 놓치면 안 됩니다."""

    body = "\n".join(REAL_CONTRACT.splitlines()[1:])      # 제목 줄만 뺍니다
    # 머리 세 줄 어디에도 "sales contract" 같은 **제목**이 없습니다.
    # (본문에 contract 라는 낱말이 나오는 것과는 다릅니다)
    head = service._title_area(body)
    assert not any(word in head for word in service.CONTRACT_TITLES), head
    assert service.looks_like_contract(body) is True
