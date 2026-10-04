"""전문가 점검 3회차(2026-10-04) — 새 계약서 6종(터키 TRY·브라질 DDP·중국 임가공 갑/을·한국 자체
약관·미국 MSA Company/Supplier·이집트 L/C+PSI)에서 나온 것.

약한 곳은 셋이었습니다 — 'Company'·'Principal' 이름, 환율·관세 위험국, 국문 갑/을의 바이어 우위.
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses
from app.services import contract_clause_service as service

H = "SALES CONTRACT\n"
MSA = ('MASTER SUPPLY AGREEMENT between Acme Inc. ("Company") and Hana Co., Ltd. ("Supplier"). '
       "Supplier shall supply the Products to Company. Company shall pay Supplier. ")


def _found(doc: str) -> set[str]:
    return contract_clauses.find_in(doc if doc.startswith(("MASTER", "SALES", "수출", "임가공")) else H + doc)


def _status(doc: str, key: str) -> str:
    row = contract_clauses.analyze(H + doc)["clauses"].get(key)
    return row["status"] if row else "absent"


SAFE = [
    ("tooling_free", "If a recall is necessary, the Seller shall bear all costs of the recall, including "
                     "customer remedies."),
    ("us_jury_punitive", "The parties submit to the exclusive jurisdiction of the courts located in Chicago, "
                         "Illinois. EACH PARTY WAIVES ITS RIGHT TO A JURY TRIAL. In no event shall either "
                         "party be liable for punitive damages."),
]


@pytest.mark.parametrize("key,doc", SAFE, ids=[f"{k}:{d[:24]}" for k, d in SAFE])
def test_정상_문구는_짚지_않는다(key, doc):
    assert key not in _found(doc)


MISSED = [
    ("buyer_set_off", MSA + "Company may set off against any amount owed by Supplier any amount it claims."),
    ("assignment_one_way", MSA + "Company may assign this Agreement without consent. Supplier may not assign "
                                 "this Agreement without Company's prior written consent."),
    ("termination_at_will", "Each party shall keep confidential the information listed in Exhibit B. The "
                            "Buyer may terminate this Contract for convenience upon 10 days notice."),
    ("termination_at_will", "Either party may terminate for material breach; in addition, the Buyer may "
                            "terminate this Contract for convenience at any time."),
    ("termination_at_will", "제10조 매수인은 30일 전에 서면으로 통지하여 이 계약을 해지할 수 있다."),
    ("china_domestic_arb", "Disputes shall be resolved by the Shanghai International Arbitration Center (SHIAC)."),
    ("china_domestic_arb", "제15조 분쟁은 상해국제중재센터의 중재로 해결한다."),
    ("inspection_buyer_sole", "제7조 완성품의 검사는 매수인이 지정한 검사원이 실시한다. 매수인의 판정은 최종적이다."),
    ("fx_risk_local", "All prices are in Brazilian Reais. Any exchange loss shall be borne by the Seller."),
    ("fx_risk_local", "The price is fixed in Turkish Lira and shall not be adjusted for any change in the "
                      "exchange rate."),
    ("tariff_absorption", "The Seller shall bear any tariff, duty or trade remedy imposed on the Products by "
                          "the United States, including Section 301 duties."),
    ("tariff_absorption", "Any additional customs duty, anti-dumping duty or safeguard measure imposed by the "
                          "Republic of Turkey on the Goods after the date of this Contract shall be borne by "
                          "the Seller and deducted from the balance payment."),
    ("payment_fx_approval", "The L/C will be opened after the Buyer obtains approval of the Central Bank of "
                            "Egypt for the foreign currency allocation."),
    ("payment_fx_approval", "Payment of the balance is subject to the Buyer obtaining the necessary allocation "
                            "from its bank."),
    ("psi_cost_delay", "Pre-shipment inspection by an inspection company nominated by the Buyer. Inspection "
                       "fees and any demurrage arising from delays in inspection shall be for the Seller's account."),
    ("unlimited_damages", "The Seller shall defend, indemnify and hold harmless the Buyer from all losses "
                          "arising out of the Products, including product liability claims."),
    ("us_class_action_pl", "The Seller shall defend, indemnify and hold harmless the Buyer from all losses "
                           "arising out of the Products, including product liability claims."),
    ("us_jury_punitive", "The parties submit to the courts in Kent County, Michigan."),
    ("us_jury_punitive", "The parties submit to the U.S. District Court for the Northern District of Georgia."),
    ("chargeback_penalty", "The Seller shall pay a chargeback of 3% for each delivery that is not on time and in full."),
    ("cover_purchase", "If the Seller fails to deliver, the Buyer may cancel the order and purchase substitute "
                       "products, and the Seller shall pay all excess costs incurred."),
    ("mfn_price", "If the Seller offers lower prices to any other customer, the Seller shall offer the same "
                  "prices to the Buyer retroactively."),
    ("spec_change_no_price", "The Buyer may change the Specifications at any time; the Seller shall implement "
                             "such changes without adjustment to the price unless otherwise agreed."),
    ("ip_assignment", MSA + "All inventions, developments and improvements made by Supplier in the course of "
                            "performing this Agreement shall be the exclusive property of Company."),
    ("exclusive_no_moq", "The Seller appoints the Buyer as its exclusive representative in Brazil."),
    ("one_way_nda", "제11조 매도인은 매수인의 디자인, 사양서 및 거래처 정보를 제3자에게 누설하여서는 아니 된다."),
    # 브라질 대리인 해지 보상(법 4.886/65, 수수료의 1/12)은 맞는 조항이 없습니다 — 걸프·EU
    # 조항에 붙이면 제목과 나라가 틀립니다. 새 조항으로 넣을지는 따로 정합니다.
]


@pytest.mark.parametrize("key,doc", MISSED, ids=[f"{k}:{d[:24]}" for k, d in MISSED])
def test_위험한_문구를_찾는다(key, doc):
    assert key in _found(doc)


PRESENT = [
    ("payment", "The Buyer shall pay each invoice within 30 days of the invoice date by wire transfer."),
    ("amendment", "This Agreement may only be amended in a writing signed by both parties."),
    ("amendment", "This Contract may be amended only by written agreement of both parties."),
    ("quantity_tol", "Quantity: 2,000 MT (+/- 10% at Seller's option)."),
    ("suspend_delivery", "The Seller may suspend deliveries while any payment is overdue."),
    ("no_set_off", "The Buyer shall not withhold, set off or deduct any amount from the price."),
    ("claim_period", "The Buyer shall notify any defect in writing within 30 days after arrival, failing "
                     "which the Goods shall be deemed accepted."),
    ("lc_deadline", "Payment by L/C payable at 180 days from B/L date, to be opened within 15 days from "
                    "contract date."),
    ("goods", "1. GOODS. Polypropylene homopolymer, grade HP-550J, 500 MT, packed in 25 kg bags."),
]


@pytest.mark.parametrize("key,line", PRESENT, ids=[f"{k}:{s[:24]}" for k, s in PRESENT])
def test_흔한_문구의_필수_이익조항을_있다고_본다(key, line):
    assert _status(line, key) == "present"


def test_최소_구매_의무가_없다고_적힌_것은_있음이_아니다():
    assert _status("Clause 6 - Minimum Purchases. The Buyer has no obligation to purchase minimum "
                   "quantities.", "min_order") != "present"


def test_바이어만_보호하는_책임_한도는_Company_계약서에서도_부족이다():
    doc = MSA + "IN NO EVENT SHALL COMPANY BE LIABLE TO SUPPLIER FOR ANY DAMAGES."
    row = contract_clauses.analyze(doc)["clauses"].get("liability_cap")
    assert row and row["status"] == "weak"


@pytest.mark.parametrize("line", ["This Contract shall be governed by Brazilian law.",
                                  "This Contract shall be governed by Turkish law."])
def test_외국법_형용사도_확인한다(line):
    assert _status(line, "governing_law") == "weak"


def test_한국법에_싱가포르_중재는_외국법이_아니다():
    line = ("This Contract shall be governed by Korean law, and any arbitration shall be held in "
            "Singapore under the SIAC Rules.")
    assert _status(line, "governing_law") == "present"


def test_DDP_브라질은_문구가_없어도_독소다():
    result = service.review(H + "Delivery DDP Sao Paulo. The Exporter shall pay import duty.", "DDP", "BR")
    assert "ddp_no_ior" in {row["key"] for row in result["toxic"]}
    assert "ddp_no_ior" not in {row["key"] for row in result["watch_country"]}


def test_재수출을_막아_두었으면_넣으라고_하지_않는다():
    result = service.review(H + "The Buyer shall not re-export the Goods to any sanctioned country.", "FOB", "TR")
    assert "reexport_control" not in {row["key"] for row in result["watch_country"]}


def test_원자재_매매에는_금형_이익조항을_권하지_않는다():
    result = service.review(H + "Polypropylene homopolymer 500 MT. Payment by T/T.", "CFR")
    assert not {row["key"] for row in result["gain"]} & {"ip", "buyer_design_ip", "exit_buyback"}


def test_일반_매매에는_가공_손모율을_권하지_않는다():
    result = service.review(H + "This warranty shall not apply to defects caused by materials supplied by "
                                "the Buyer. Payment by T/T.", "FOB")
    assert "material_yield" not in {row["key"] for row in result["gain"]}


def test_역할_이름만_정한_계약서는_빈_이름표를_쓰지_않는다():
    doc = MSA + "Company may set off against any amount owed by Supplier any amount it claims."
    text = service.as_text(service.review(doc, "FOB") | {"summary": ""})
    assert "— **" not in text and "Supplier —" not in text


def test_직접_확인_문장도_원문_이름이다():
    doc = MSA + "Supplier warrants that Company may return any Product for any reason within one year."
    result = service.review(doc, "FOB")
    for item in result["check"]:
        assert "Seller" not in item["sentence"] and "Buyer" not in item["sentence"]


def test_근거는_대문자_원문과_번호_제목을_지킨다():
    doc = MSA + "ARTICLE 12 TERM AND TERMINATION 12.1 COMPANY MAY SET OFF ANY AMOUNT IT CLAIMS AGAINST SUPPLIER."
    row = contract_clauses.analyze(doc)["clauses"].get("buyer_set_off")
    assert row and "SUPPLIER" in row["evidence"] and "ARTICLE 12" not in row["evidence"]
