"""전문가 점검 2회차(2026-10-04) — 1차 수정 뒤에도 새던 곳과 회귀.

원인이 셋으로 모였습니다.
  문장 경계   마침표로 자르니 "0.5% … up to a maximum of 5%" 의 상한이 잘려 안 보였습니다
  제목 줄     "Governing Law." 제목에서 먼저 잡혀 본문의 외국법·상한을 보지 않았습니다
  당사자 이름  Principal/Agent 까지 바꿔 EU 대리인 검출이 꺼졌고(회귀), Buyer+Supplier
              조합은 안 바꿨으며, 근거에 "The the Seller" 가 나왔습니다
그리고 우리를 지키는 문구(배심 포기·징벌적 배제·확정된 금액만 상계)를 독소로 짚었습니다.
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses
from app.services import contract_clause_service as service

H = "SALES CONTRACT\n"


def _found(doc: str) -> set[str]:
    return contract_clauses.find_in(doc if doc.startswith(("SALES", "SUPPLY", "AGENCY", "수출", "OEM"))
                                    else H + doc)


def _status(doc: str, key: str) -> str:
    row = contract_clauses.analyze(H + doc)["clauses"].get(key)
    return row["status"] if row else "absent"


# ── 걸리면 안 됨 ──────────────────────────────────────────────────────────────
SAFE = [
    ("uncapped_ld", "Seller shall pay liquidated damages of 0.5% of the contract price per week of "
                    "delay, up to a maximum of 5% of the contract price."),
    ("uncapped_ld", "8. Delivery Time; Liquidated Damages. Seller shall pay 1% of the price per week "
                    "of delay. The total liquidated damages shall not exceed 5% of the price."),
    ("us_jury_punitive", "In no event shall either party be liable for punitive damages."),
    ("us_jury_punitive", "Neither party shall be liable for any punitive or exemplary damages."),
    ("us_jury_punitive", "EACH PARTY WAIVES ITS RIGHT TO A JURY TRIAL."),
    ("buyer_set_off", "The Buyer may set off only amounts that have been finally determined by an "
                      "arbitral award or agreed in writing by the Seller."),
    ("title", "Ownership of all drawings and moulds developed by the Seller shall pass to the Buyer."),
    ("title", "The Seller warrants that title to the Goods shall pass free of any lien."),
    ("termination_at_will", "Either party may terminate this Agreement for convenience upon ninety "
                            "(90) days' written notice."),
    ("foreign_forum", "The courts of Tokyo shall have non-exclusive jurisdiction, without prejudice "
                      "to the Seller's right to bring proceedings in Korea."),
    ("inspection_buyer_sole", "The inspection at the port of destination by an independent surveyor "
                              "shall be final."),
    ("china_domestic_arb", "All disputes shall be submitted to HKIAC for arbitration in Hong Kong."),
    ("buyer_nominated_cost", "제6조 매수인이 지정한 검사기관은 선적 전 매도인의 공장에서 검사할 수 있다. "
                             "검사 비용은 매수인이 부담한다."),
    ("cert_test_cost", "제6조 AQL 검사에 불합격하면 재검사 비용은 매도인이 부담한다."),
]


@pytest.mark.parametrize("key,doc", SAFE, ids=[f"{k}:{d[:26]}" for k, d in SAFE])
def test_정상_문구는_짚지_않는다(key, doc):
    assert key not in _found(doc)


def test_계약서_다른_곳의_간주_인수가_있으면_서명_조건부_지급이_아니다():
    doc = ("3. Payment: 10% within 30 days after signature of the Final Acceptance Certificate by "
           "the Purchaser. 4. If the Purchaser fails to carry out the acceptance test within 30 days "
           "after installation, the machine shall be deemed accepted.")
    assert "acceptance_signature_payment" not in _found(doc)


def test_견본만_선수금이고_본_물량은_외상이면_B_L_직송은_독소다():
    doc = ("Samples: 100% T/T in advance before shipment. Bulk orders: 30% T/T in advance and 70% "
           "within 60 days after B/L date. The Seller shall send the original B/L directly to the "
           "Buyer by courier immediately after shipment.")
    assert "docs_before_payment" in _found(doc)


# ── 놓치면 안 됨 ──────────────────────────────────────────────────────────────
AGENCY = ("AGENCY AGREEMENT\nThe Principal appoints the Agent as its exclusive commercial agent in "
          "Germany to negotiate sales on behalf of the Principal. Upon termination for any reason, "
          "the Agent shall not be entitled to any indemnity or compensation.")

MISSED = [
    ("agency_law_eu", AGENCY),
    ("recall_cost", "SUPPLY AGREEMENT\nBuyer and Supplier agree as follows. Supplier shall bear all "
                    "costs of such recall, including customer compensation."),
    ("recall_cost", "SUPPLY AGREEMENT\nBuyer and Supplier agree as follows. Supplier shall bear all "
                    "costs of such recall, including customer compensation, unless Supplier proves "
                    "that it is not responsible."),
    ("termination_at_will", "Buyer may terminate this Agreement or any individual contract at any time "
                            "by giving Supplier thirty (30) days' notice."),
    ("inspection_buyer_sole", "Products shall be deemed accepted only when Buyer notifies Supplier of "
                              "passing the inspection."),
    ("one_way_force_majeure", "If the Buyer is prevented from performing by force majeure, the Buyer "
                              "shall not be liable."),
    ("payment_fx_approval", "The L/C shall be opened subject to the Buyer obtaining the import licence "
                            "and foreign exchange clearance from the Reserve Bank of India."),
    ("tariff_absorption", "The price is CFR Nhava Sheva. Any anti-dumping duty imposed in India on the "
                          "goods shall be borne by Seller."),
    ("psi_cost_delay", "Goods shall be inspected before shipment by SGS appointed by Buyer. Cost of "
                       "inspection and any delay caused by re-inspection shall be borne by Seller."),
    ("battle_of_forms", "In case of conflict between this Agreement and any Purchase Order, the "
                        "Purchase Order shall prevail."),
    ("battle_of_forms", "제2조 발주서와 본 계약이 상충하는 경우 발주서가 우선한다."),
    ("one_way_nda", "The Seller shall not disclose any information of the Buyer to any third party."),
    ("one_way_nda", "제11조 매도인은 매수인의 정보를 제3자에게 누설하여서는 아니 된다."),
    ("gulf_agent_lock", "The Supplier appoints the Distributor as its exclusive distributor in Saudi "
                        "Arabia. The Supplier shall not terminate or refuse to renew this Agreement "
                        "without the Distributor's consent."),
    ("evergreen", "This Agreement renews automatically for one-year periods unless either party gives "
                  "notice at least 180 days prior to expiry."),
    ("evergreen", "This Contract shall be automatically renewed for successive three-year periods "
                  "unless either party gives notice at least twelve (12) months before expiry, and any "
                  "such notice shall take effect seven (7) days after receipt."),
    ("open_warranty", "The Seller warrants that the Goods shall be free from defects in material and "
                      "workmanship. The Seller shall not compete with the Buyer for two (2) years "
                      "after termination."),
    ("open_warranty", "The Supplier shall remedy any defect regardless of the time of discovery."),
    ("term_conflict", "Notwithstanding the trade term, the Seller shall bear all risks until the Goods "
                      "arrive at the Buyer's warehouse, and the Buyer shall bear the unloading cost."),
    ("china_domestic_arb", "All disputes shall be submitted to CIETAC for arbitration in Shanghai, and "
                           "notices shall be sent to the Seller in Seoul."),
    ("uncapped_ld", "제9조 매도인이 납기를 지체하는 경우 지체 1일당 계약금액의 0.5%를 지체상금으로 "
                    "매수인에게 지급한다."),
]


@pytest.mark.parametrize("key,doc", MISSED, ids=[f"{k}:{d[:26]}" for k, d in MISSED])
def test_위험한_문구를_찾는다(key, doc):
    assert key in _found(doc)


# ── 필수·이익: 있는 것을 있다고 ────────────────────────────────────────────────
PRESENT = [
    ("lc_deadline", "The L/C shall be opened within 15 days after signing."),
    ("lc_deadline", "The Buyer shall cause the L/C to be issued within 10 days after this Contract."),
    ("no_set_off", "Customer shall pay all amounts without set-off, deduction or counterclaim."),
    ("liability_cap", "제8조 매도인의 총 배상책임은 해당 선적분 대금을 한도로 한다."),
    ("claim_period", "제7조 매수인은 도착 후 30일 이내에 서면으로 클레임을 제기하여야 한다."),
    ("packing", "Packing in cartons on pallets suitable for ocean transport."),
    ("goods", "The Goods are described in Annex A (Specifications) attached hereto."),
    ("goods", "Subject: one (1) CNC horizontal machining centre, model HMC-800, as per Annex 1."),
    ("shipment", "Delivery shall be made within seven (7) months after receipt of the down payment."),
    ("inspection", "An acceptance test shall be carried out at the Purchaser's plant within 30 days."),
    ("eu_epr_cost", "All extended producer responsibility registrations, fees, reporting and take-back "
                    "obligations under the Batteries Regulation (EU) 2023/1542 in each Member State "
                    "shall be undertaken and paid by the Seller."),
]


@pytest.mark.parametrize("key,line", PRESENT, ids=[f"{k}:{s[:26]}" for k, s in PRESENT])
def test_적어_둔_조항을_찾는다(key, line):
    if key == "eu_epr_cost":
        assert key in _found(line)
    else:
        assert _status(line, key) == "present"


# ── 제목 줄에서 잡혀도 본문으로 판정 ───────────────────────────────────────────
@pytest.mark.parametrize("line", [
    "11. Governing Law. This Contract shall be governed by the laws of the Federal Republic of Germany.",
    "Governing law: English law.",
    "This Contract shall be construed in accordance with English law.",
    "The law governing this contract shall be the laws of India.",
    "This Contract is subject to the laws of Singapore.",
    "제15조 본 계약은 중화인민공화국 법률에 따른다.",
])
def test_외국법_준거법은_확인하라고_한다(line):
    assert _status(line, "governing_law") == "weak"


# ── 당사자 이름 ───────────────────────────────────────────────────────────────
def test_근거는_계약서_원문_이름으로_보여_준다():
    doc = ("SUPPLY AGREEMENT between ABC Inc. (the \"Customer\") and Hana Co. (the \"Supplier\"). "
           "The Supplier shall supply the Products to the Customer. The Supplier shall defend, "
           "indemnify and hold the Customer harmless from any and all losses and damages.")
    row = contract_clauses.analyze(doc)["clauses"]["unlimited_damages"]
    assert "Supplier" in row["evidence"] and "Seller" not in row["evidence"]
    assert "the the" not in row["evidence"].lower()


def test_갑을_주소가_없어도_주식회사를_우리로_본다():
    doc = ('수출계약서\n주식회사 대한산업(이하 "갑")과 베트남 하노이 소재 VINA Trading JSC(이하 "을")는 '
           "다음과 같이 계약한다. 제5조 갑은 30일 전 서면 통지로 언제든지 본 계약을 해지할 수 있다.")
    side = contract_clauses.our_side(doc)
    assert side and side["label"] == "갑" and side["name"] == "주식회사 대한산업"
    assert "termination_at_will" not in contract_clauses.find_in(doc)


def test_갑을_이름에_조사와_제목이_붙지_않는다():
    doc = ('OEM 의류 생산 및 공급 계약서\n베트남 호치민 소재 SAIGON FASHION JSC(이하 "갑")와 대한민국 '
           '서울 소재 주식회사 한빛텍스타일(이하 "을")은 다음과 같이 계약한다.')
    side = contract_clauses.our_side(doc)
    assert side["name"] == "주식회사 한빛텍스타일"
    assert side["other_name"] == "SAIGON FASHION JSC"


def test_갑을_방향을_못_정하면_알린다():
    doc = ('수출계약서\nABC(이하 "갑")과 XYZ(이하 "을")는 다음과 같이 계약한다. 제5조 갑은 언제든지 '
           "본 계약을 해지할 수 있다. 제6조 대금은 전신환으로 지급한다.")
    result = service.review(doc, "FOB")
    assert result["side_unknown"] is True
    assert "갑" in service.as_text(result | {"summary": ""}) and "못 정했" in service.as_text(result | {"summary": ""})


# ── 화면·문구 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("key", ["uncapped_ld", "exclusive_no_moq", "ddp_no_ior", "us_jury_punitive",
                                 "agency_law_eu", "reexport_control"])
def test_독소_머리말이_고치는_법과_맞는다(key):
    assert "넣는 것이 아니라 빼는 것" not in service.toxic_note(key)


def test_EU_대리인_머리말은_적어_두어도_효력이_없다고_한다():
    assert "적어 두어도" in service.toxic_note("agency_law_eu")


def test_재수출_통제는_넣으라고_안내한다():
    result = service.review(H + "Payment by T/T. Delivery FOB Busan.", "FOB", "AE")
    text = service.as_text(result | {"summary": ""})
    line = next(l for l in text.splitlines() if "재수출" in l)
    assert "넣으세요" in line


def test_DDP_가_아니면_DDP_도착국_주의를_띄우지_않는다():
    result = service.review(H + "Payment by T/T.", "FOB", "IN")
    assert "ddp_no_ior" not in {row["key"] for row in result["watch_country"]}


@pytest.mark.parametrize("doc,key", [
    ("The courts have exclusive jurisdiction. This Agreement is governed exclusively by Korean law.", "min_order"),
    ("Disputes go to the China International Economic and Trade Arbitration Commission.", "deemed_acceptance"),
    ("A PSI agency appointed by the importing country shall inspect the goods.", "agency_protection"),
])
def test_엉뚱한_낱말로_이익조항을_권하지_않는다(doc, key):
    result = service.review(H + doc + " Payment by T/T.", "FOB")
    assert key not in {row["key"] for row in result["gain"]}


def test_문구가_판정_기준과_맞는다():
    assert "90일" not in contract_clauses.by_key("evergreen")["text_ko"]
    assert "찾지 않습니다" not in contract_clauses.by_key("us_jury_punitive")["text_ko"]
