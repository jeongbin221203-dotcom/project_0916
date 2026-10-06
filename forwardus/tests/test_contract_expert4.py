"""전문가 점검 4회차(2026-10-05) — 새 계약서 10종(일본 종합상사·인도·독일 구매약관·인도네시아
플랜트·UAE L/C·국문 갑/을 베트남·미국 OEM·사우디 대리점·중영 이중언어·말레이시아 위탁재고).

가장 컸던 것: 영어 부정문("no …", "not entitled", "has no right")과 우리에게 유리한 국문 문장을
독소로 짚어, 유리한 조항을 지우라고 하면서 같은 조항을 넣으라고 했습니다.
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses
from app.services import contract_clause_service as service

H = "SALES CONTRACT\n"


def _found(doc: str) -> set[str]:
    return contract_clauses.find_in(H + doc)


def _status(doc: str, key: str) -> str:
    row = contract_clauses.analyze(H + doc)["clauses"].get(key)
    return row["status"] if row else "absent"


# ── A. 정상·보호 문장을 독소로 짚지 않는다 (먼저 봅니다) ─────────────────────────
SAFE = [
    ("retro_price_deduction", "There shall be no retroactive price reduction."),
    ("retro_price_deduction", "No rebate, markdown allowance or promotional funding shall be deducted from any "
                              "payment."),
    ("chargeback_penalty", "No chargebacks, fines or OTIF penalties shall be deducted from invoices."),
    ("buyer_set_off", "The Buyer is not entitled to set off any claims against the purchase price."),
    ("full_return", "The Buyer has no right to return unsold goods."),
    ("exclusive_no_moq", "The Seller is under no obligation to supply exclusively to the Buyer."),
    ("tooling_free", "The Seller shall have no obligation to provide tooling free of charge."),
    ("unlimited_damages", "The Seller's liability shall in no case be unlimited."),
    ("termination_at_will", "Neither party shall be entitled to terminate this Agreement for convenience."),
    ("docs_before_payment", "선적서류 원본은 대금 전액 입금 확인 후 매수인에게 송부한다."),
    ("docs_before_payment", "B/L 원본은 잔금 입금 후 3일 이내에 매수인에게 발송한다."),
    ("docs_before_payment", "Upon receipt of the balance, the Seller shall courier the full set of original B/L "
                            "to the Buyer."),
    ("docs_before_payment", "The Seller shall forward the original documents to the Buyer within 3 days after "
                            "receipt of 100% payment."),
    ("docs_before_payment", "The Seller shall send the original transport documents through the Seller's bank "
                            "on D/P terms."),
    ("inspection_buyer_sole", "매수인은 물품 수령 후 30일이 지나면 품질에 관한 이의를 제기할 수 없다."),
    ("inspection_buyer_sole", "매수인은 검사 결과에 대하여 이의를 제기할 수 없다."),
    ("termination_at_will", "매수인은 정당한 사유 없이 이 계약을 해지할 수 없다."),
    ("ip_assignment", "Tools, moulds and drawings provided or paid for by the Purchaser remain the property of "
                      "the Purchaser."),
    ("ddp_no_ior", "The Seller shall deliver the Goods DAP Riyadh; the Buyer shall be responsible for customs "
                   "clearance and import duties in Saudi Arabia."),
    ("lc_soft_clause", "Shipment shall be made on a vessel subject to the Buyer's nomination under FOB terms."),
    ("lc_soft_clause", "Shipment within 30 days after receipt of L/C on the vessel as per the Buyer's nomination."),
    ("unlimited_damages", "매도인은 어떠한 경우에도 무제한의 손해배상 책임을 지지 아니한다."),
]


@pytest.mark.parametrize("key,doc", SAFE, ids=[f"{k}:{d[:24]}" for k, d in SAFE])
def test_정상_보호_문장은_독소가_아니다(key, doc):
    assert key not in _found(doc)


def test_바이어_이의_불가는_우리_클레임_기한이다():
    assert _status("매수인은 물품 수령 후 30일이 지나면 품질에 관한 이의를 제기할 수 없다.", "claim_period") == "present"


# ── B. 포기·부정한 필수·이익조항을 '있음'으로 보지 않는다 ─────────────────────────
NOT_PRESENT = [
    ("late_interest", "The Seller shall not be entitled to charge interest on late payments."),
    ("late_interest", "Late payment interest: not applicable."),
    ("late_interest", "The Seller waives any right to interest on overdue payments."),
    ("suspend_delivery", "The Seller shall not suspend deliveries for any reason, including non-payment."),
    ("title", "물품의 소유권은 선적과 동시에 매수인에게 이전한다. 대금은 선적 후 60일 이내에 지급한다."),
    ("min_order", "Minimum Purchase. None."),
    ("insurance", "Insurance: none."),
    ("export_licence", "The Seller shall obtain all export licences at its own risk; failure to obtain a licence "
                       "shall not excuse performance."),
    ("claim_period", "Notice of defects shall be deemed timely if given within 10 working days of discovery. The "
                     "Supplier waives the objection of late notice of defects (§ 377 HGB)."),
]


@pytest.mark.parametrize("key,doc", NOT_PRESENT, ids=[f"{k}:{d[:24]}" for k, d in NOT_PRESENT])
def test_포기하거나_없다고_적은_조항은_있음이_아니다(key, doc):
    assert _status(doc, key) != "present"


def test_조건절_하지_아니하면은_부정이_아니다():
    doc = "매수인은 물품 도착 후 14일 이내에 검사하고, 이 기간 내에 이의를 제기하지 아니하면 물품은 합격한 것으로 본다."
    assert _status(doc, "claim_period") == "present"


# ── C. 있는 필수·이익조항을 찾는다 ──────────────────────────────────────────────
PRESENT = [
    ("title", "The Seller retains ownership of the Goods until the purchase price has been paid in full."),
    ("title", "Property in the Goods shall not pass to the Buyer until the Seller has received payment in full."),
    ("title", "The Seller reserves title to the Goods until full payment."),
    ("title", "Title shall not pass until payment in full has been received."),
    ("title", "The Goods remain the Seller's property until paid for in full."),
    ("title", "물품의 소유권은 대금 완납 시까지 매도인에게 있다."),
    ("payment", "매수인은 선적일로부터 60일 이내에 매도인이 지정한 계좌로 전신송금한다."),
    ("goods", "Goods: Power module SJ-450, 20,000 pcs."),
    ("goods", "Product: Hot-rolled steel coil, 1,000 MT."),
    ("goods", "매도인은 PP 수지 500톤을 매수인에게 공급한다."),
    ("quantity_tol", "수량은 ±5% 범위에서 매도인이 정한다."),
    ("packing", "25kg 포대, 팔레트 적재, 화인은 매수인의 지시에 따른다."),
    ("late_interest", "매수인이 대금 지급을 지체하면 매도인은 연 15%의 비율로 계산한 지연손해금을 청구할 수 있다."),
    ("suspend_delivery", "매수인이 대금을 지급하지 아니하는 경우 매도인은 이후의 선적을 중지할 수 있다."),
    ("payment_account", "Payments shall be made only to the bank account of the Seller stated in this Contract."),
]


@pytest.mark.parametrize("key,doc", PRESENT, ids=[f"{k}:{d[:24]}" for k, d in PRESENT])
def test_흔한_문형의_조항을_있다고_본다(key, doc):
    assert _status(doc, key) == "present"


# ── D. 독소조항을 찾는다 ──────────────────────────────────────────────────────
MISSED = [
    ("acceptance_signature_payment",
     "10% of the price is payable upon issuance of the Provisional Acceptance Certificate, which shall be issued by "
     "the Buyer at its discretion. The Line shall not be deemed accepted by reason of commercial use."),
    ("termination_at_will", "The Buyer may terminate this Agreement or any purchase order without cause upon 15 "
                            "days' written notice."),
    ("termination_at_will", "In addition the Buyer may terminate this Agreement upon one (1) month's prior notice."),
    ("termination_at_will", "The Buyer may terminate this Agreement for any reason or no reason upon 30 days' notice."),
    ("payment_fx_approval", "다만 매수인이 베트남 국가은행의 외화송금 승인을 받지 못한 경우 승인을 받을 때까지 지급을 "
                            "유예할 수 있다."),
    ("lc_soft_clause", "The credit becomes operative only upon receipt of the issuing bank's amendment advising "
                       "that the import permit has been obtained."),
    ("lc_soft_clause", "This L/C is not operative until the issuing bank receives the Buyer's approval of the "
                       "sample."),
    ("payment_on_resale", "The Buyer shall pay for Products sold during each calendar month within 90 days after "
                          "the end of that month."),
    ("full_return", "Products unsold after 6 months shall be returned to the Seller or destroyed at the Seller's "
                    "cost."),
    ("battle_of_forms", "These Terms of Purchase apply exclusively. Conflicting or deviating terms of the Supplier "
                        "shall not apply."),
    ("uncapped_ld", "If the Supplier is in delay, the Purchaser may claim a contractual penalty of 0.3% per working "
                    "day, up to 5%; the right to claim further damages remains reserved."),
    ("foreign_language_prevails", "This Contract is made in English and Bahasa Indonesia; in case of conflict the "
                                  "Bahasa Indonesia version prevails."),
    ("foreign_language_prevails", "本合同中英文两种文本如有冲突，以中文为准。"),
    ("ip_assignment", "All rights to inventions, designs and improvements made by the Seller in the performance of "
                      "this Agreement shall belong to the Buyer."),
    ("open_warranty", "The Seller shall be liable for latent defects discovered within one year after the Buyer "
                      "becomes aware of them."),
    ("non_compete_wide", "The Seller shall not manufacture or sell products having similar functions or appearance "
                         "to any third party worldwide during the term and for three years thereafter."),
    ("retro_price_deduction", "If the Buyer reduces its retail price, the Seller shall issue a credit on all "
                              "Products in the Buyer's inventory and channel inventory."),
    ("evergreen", "This Agreement shall be renewed automatically for equal periods unless both parties agree "
                  "otherwise in writing."),
]


@pytest.mark.parametrize("key,doc", MISSED, ids=[f"{k}:{d[:24]}" for k, d in MISSED])
def test_위험한_문구를_찾는다(key, doc):
    assert key in _found(doc)


def test_일본_리콜_면책은_미국_집단소송이_아니라_리콜_비용이다():
    doc = ("The Seller shall indemnify the Buyer against all losses including recall expenses and product "
           "liability claims, irrespective of the Seller's negligence.")
    found = _found(doc)
    assert "recall_cost" in found


def test_중국식_甲方_乙方_머리에서_우리_쪽을_읽는다():
    doc = ("销售合同 SALES CONTRACT\n甲方（买方）Party A (Buyer): Shanghai Huaxin Trading Co., Ltd.\n"
           "乙方（卖方）Party B (Seller): Hana Co., Ltd.\n"
           "Party A may terminate this Contract at any time by written notice. "
           "Party A may deduct any amount owed by Party B from any payment.")
    analysis = contract_clauses.analyze(doc)
    assert analysis["side"] and analysis["side"]["label"].startswith("Party B")
    assert "termination_at_will" in {k for k, v in analysis["clauses"].items() if v["status"] == "present"}


def test_플랜트_계약의_Employer_Contractor_를_읽는다():
    doc = ("CONTRACT FOR SUPPLY AND INSTALLATION between PT Maju (the \"Employer\") and Hana Co., Ltd. "
           "(the \"Contractor\"). The Contractor shall supply the Line. The Employer shall pay the Contractor. "
           "The Employer may terminate this Contract at any time for convenience.")
    assert "termination_at_will" in contract_clauses.find_in(doc)


def test_정의를_못_읽은_Party_A_B_계약서는_방향을_모른다고_알린다():
    doc = H + "Party A may terminate this Contract at any time. Party B shall deliver the Goods to Party A."
    assert service.review(doc, "FOB")["side_unknown"]


# ── F. 근거·바꿔 읽기 ─────────────────────────────────────────────────────────
def test_숫자_뒤_조사_을은_바꾸지_않는다():
    doc = ('본 계약은 주식회사 한빛(이하 "갑", 매도인)과 VINA Co.(이하 "을", 매수인) 사이에 체결한다. '
           "갑은 지연 1일당 대금의 1천분의 3을 지체상금으로 지급하되 100분의 10을 한도로 한다.")
    body = contract_clauses.normalized(doc)
    assert "1천분의 3을" in body and "100분의 10을" in body


def test_근거는_조_제목이_아니라_본문_문장이다():
    doc = "Limitation of Liability. In no event shall the Seller's liability exceed the contract price."
    row = contract_clauses.analyze(H + doc)["clauses"]["liability_cap"]
    assert "exceed" in row["evidence"]


def test_CISG_한_줄은_준거법이_부족하다():
    assert _status("The CISG shall apply.", "governing_law") == "weak"
