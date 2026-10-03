"""실제 무역분쟁에서 다툰 조항 문구 (2026-10-03).

왜 이 파일이 있나
  손으로 만든 예문은 잘 잡히는데, 판결문·중재판정에 **인용된 실제 문구**를 넣어
  보니 기존 조항이 상당수를 놓쳤습니다.
      claim_period   법원이 유효하다고 본 모범 문구 3건 — 모두 못 찾음
      lc_soft_clause 대법원·미국 판결의 소프트 조항 6건 — 모두 못 찾음
      payment_on_resale  대법원 98다47443 — 못 찾음
  그리고 판례에 여러 번 나오는데 우리에게 없던 유형이 있었습니다(약관 충돌,
  상대 언어본 우선, 바이어 서명 조건부 지급, 청구 즉시 지급 보증 …).

  문구 옆에 출처를 적습니다. "취지" 는 판결이 원문을 인용하지 않아 뜻을 옮긴
  것입니다. 출처 목록과 사건 요지는 커밋 메시지에 남깁니다.

순서
  **걸리면 안 되는 문장을 먼저** 적습니다. 판례에서 이긴 쪽의 문구(우리에게
  유리한 문구)가 대부분입니다.
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses


def _found(line: str) -> set[str]:
    return contract_clauses.find_in("SALES CONTRACT\n" + line)


# ── 걸리면 안 되는 문장 ─────────────────────────────────────────────────────
SAFE = [
    # claim_period — 하자 클레임이 아닌 '며칠 안에'
    ("claim_period", "The Seller shall notify the Buyer of the shipment within 7 days after loading."),
    ("claim_period", "Payment shall be made within 30 days after the date of invoice."),
    # lc_soft_clause — 독립 기관·수익자가 발행하는 서류, 우리를 지키는 문장
    ("lc_soft_clause", "Inspection certificate issued by SGS at the port of loading."),
    ("lc_soft_clause", "Beneficiary's certificate stating that one set of non-negotiable "
                       "documents has been sent to the applicant."),
    ("lc_soft_clause", "Certificate of origin issued by the Korea Chamber of Commerce and Industry."),
    ("lc_soft_clause", "Quality certificate signed by the Seller's quality manager."),
    ("lc_soft_clause", "The L/C shall not require any certificate signed by the Buyer."),
    ("lc_soft_clause", "The L/C shall be available with any bank in Korea by negotiation."),
    ("lc_soft_clause", "The Buyer's approval of the sample shall be given before shipment and "
                       "payment shall be made at sight."),
    ("lc_soft_clause", "매수인의 승인을 받은 샘플과 같은 품질로 선적하고, 대금은 일람불로 지급한다."),
    # payment_on_resale — 재판매와 무관하게 지급
    ("payment_on_resale", "Payment shall not be conditional upon the Buyer's resale of the Goods."),
    ("payment_on_resale", "매수인의 최종 고객이 대금을 지급하지 않더라도 매수인은 대금을 지급하여야 한다."),
    # full_return — 조건이 붙은 반품, 반품 금지
    ("full_return", "The Buyer may return defective goods within 14 days after written notice "
                    "and joint inspection."),
    ("full_return", "Goods may not be returned unconditionally."),
    ("full_return", "If the Buyer is not satisfied with the quality, the parties shall appoint "
                    "SGS to inspect the goods, and the goods shall not be returned."),
    # inspection_buyer_sole — 선적지 독립 검사가 최종인 꼴은 우리에게 유리
    ("inspection_buyer_sole", "The certificate of quality and quantity issued by SGS at the port "
                              "of loading shall be final and binding upon both parties."),
    ("inspection_buyer_sole", "Inspection at the port of loading by SGS shall be final; any "
                              "re-inspection at the port of destination is for reference only."),
    ("inspection_buyer_sole", "The inspection at the port of destination shall not be final."),
    # battle_of_forms — 우리 조건이 우선하는 꼴
    ("battle_of_forms", "The Seller's terms and conditions shall prevail over any terms in the "
                        "Buyer's purchase order."),
    ("battle_of_forms", "Any terms in the Buyer's purchase order shall not apply."),
    ("battle_of_forms", "The Buyer's purchase order shall be subject to this Contract, which "
                        "shall prevail."),
    ("battle_of_forms", "In case of conflict, this Contract shall prevail over the Buyer's purchase order."),
    # foreign_language_prevails — 영문·국문 우선, 참고용 번역
    ("foreign_language_prevails", "In case of any discrepancy, the English version shall prevail."),
    ("foreign_language_prevails", "In case of discrepancy, the Korean version shall prevail."),
    ("foreign_language_prevails", "The Chinese version is for reference only and the English "
                                  "version shall prevail."),
    ("foreign_language_prevails", "The Chinese version shall not prevail over the English version."),
    # acceptance_signature_payment — 간주 인수가 붙은 꼴
    ("acceptance_signature_payment",
     "Payment shall be made within 30 days after the acceptance certificate is signed by the "
     "Buyer, provided that if the Buyer fails to sign within 10 days after commissioning, "
     "acceptance shall be deemed given."),
    ("acceptance_signature_payment", "Payment by L/C at sight against documents including an "
                                     "inspection certificate issued by the Seller."),
    # on_demand_bond — 바이어가 우리에게 주는 보증, 보증 거절
    ("on_demand_bond", "The Buyer shall procure a payment guarantee payable on first written "
                       "demand in favour of the Seller."),
    ("on_demand_bond", "The Seller shall not be required to provide any bond payable on demand."),
    ("on_demand_bond", "The performance bond shall become effective only upon receipt of a "
                       "conforming L/C and shall be payable only against a final arbitral award."),
    # time_essence_cancel — 유예기간·불가항력·대금에 대한 essence
    ("time_essence_cancel", "If shipment is delayed by more than 30 days after a written notice "
                            "granting an additional period of 15 days, the Buyer may cancel the "
                            "delayed shipment only."),
    ("time_essence_cancel", "The Buyer may cancel the order if the delay exceeds 60 days due to "
                            "force majeure."),
    ("time_essence_cancel", "Time is of the essence for payment."),
    ("time_essence_cancel", "If the Buyer delays payment, the Seller may cancel the order."),
    # cover_purchase — 상한이 있거나, 우리가 재판매하는 꼴
    ("cover_purchase", "The Buyer may purchase substitute goods; the Seller's liability for any "
                       "price difference shall not exceed 10% of the price of the delayed goods."),
    ("cover_purchase", "If the Buyer fails to take delivery, the Seller may resell the goods and "
                       "the Buyer shall bear the difference."),
    ("cover_purchase", "The Seller shall procure substitute goods at its own cost to replace "
                       "defective goods."),
    # one_way_force_majeure — 양쪽 모두, 통지 요건
    ("one_way_force_majeure", "Neither party shall be liable for failure to perform due to force majeure."),
    ("one_way_force_majeure", "The Seller shall not be relieved of its obligations by force "
                              "majeure unless the event is notified within 7 days."),
    ("one_way_force_majeure", "Force majeure shall apply to both parties."),
    # unilateral_amendment — 서면 합의로만, 사소한 변경
    ("unilateral_amendment", "This Contract may be amended only by a written agreement signed by both parties."),
    ("unilateral_amendment", "The Buyer may change the delivery address by written notice at "
                             "least 30 days before shipment, at the Buyer's cost."),
    ("unilateral_amendment", "The Buyer may not amend these terms."),
    # ── 실제 계약서 1,310 건(SEC EDGAR · CUAD)에서 걸렸던 문장 (2026-10-03) ──
    ("time_essence_cancel", "Time is of the essence of this Agreement."),
    ("time_essence_cancel", "TPC acknowledges that time is of the essence in the payment of all "
                            "compensation due hereunder."),
    ("time_essence_cancel", "If the Supplier fails to deliver the Products after thirty (30) days "
                            "after the prescribed deadline, the Purchaser shall be entitled to "
                            "cancel the Order of such batch of Products."),
    ("time_essence_cancel", "If Buyer establishes a revised delivery date and Seller fails to "
                            "deliver by that revised date, Buyer may cancel the Order."),
    ("time_essence_cancel", "If such delay continues for more than two (2) months following the "
                            "initial forty-five (45)-day period, Purchaser may cancel the Purchase Order."),
    ("time_essence_cancel", "If an excused delay lasts more than sixty (60) days, Buyer may "
                            "immediately terminate the Agreement."),
    ("claim_period", "Party A has received over 50 justified complaints within 30 days about the "
                     "same subject."),
    ("claim_period", "The Supplier shall use commercially reasonable efforts to ensure that all "
                     "complaints are appropriately closed within 90 days."),
    ("claim_period", "The Supplier shall promptly correct the defects identified or supply new "
                     "Products within 30 days after receipt of the notice."),
    ("foreign_language_prevails", "All other websites (be they Chinese language or non-Chinese "
                                  "language) owned or controlled by the Licensee."),
    ("one_way_force_majeure", "Termination under Section 14.2(g) (Force Majeure Event for the "
                              "Licensor), shall not relieve the Supplier of its obligation to "
                              "deliver Products ordered prior to the effective date of termination."),
    ("inspection_buyer_sole", "Payment shall be made no later than 30 days after arrival at "
                              "destination port, basis the agreed assay results, against the "
                              "Final Invoice."),
]


@pytest.mark.parametrize("key,line", SAFE, ids=[f"{k}:{s[:30]}" for k, s in SAFE])
def test_분쟁에서_이긴_쪽의_문구는_짚지_않는다(key, line):
    assert key not in _found(line)


# ── 실제 분쟁 문구 — 기존 조항이 놓치던 것 ───────────────────────────────────
REAL = [
    # 클레임 기한 — 법원이 유효하다고 본 문구 (우리에게 유리한 이익조항)
    ("claim_period", "Tokyo District Court 2020.12.8",
     "The seller is not liable for complaints regarding the quality or quantity of the products "
     "unless the buyer notifies the seller within 15 days after the goods have arrived at the "
     "port of destination."),
    ("claim_period", "OLG Saarbrücken 1993.1.13",
     "Notice of defects is valid only if made within 8 days after the date of delivery."),
    ("claim_period", "Rechtbank Arnhem 2009.2.11",
     "Any complaint regarding quantity or damage must be reported by registered letter or fax "
     "within 5 working days of delivery. Complaints not reported cannot be accepted."),
    # 소프트 조항
    ("lc_soft_clause", "대법원 2000다63691",
     "Inspection Cert. Issued by MR. LIU YUE HONG of WEIHAI IMP. & EXP. CORP, Stamped by "
     "WEIHAI IMP. & EXP. CORP. 1 Original"),
    ("lc_soft_clause", "Hamilton Bank v. Kookmin Bank (2d Cir. 2001)",
     "Copy of authenticated telex from issuing bank to advising bank, indicating quantity to be "
     "shipped, destination, and nominating transporting company."),
    ("lc_soft_clause", "무역 실무 포럼 사례",
     "Signed commercial invoice countersigned by an authorized representative of the applicant."),
    ("lc_soft_clause", "대한상의 무역클레임 상담사례",
     "Inspection certificate signed by the importer or its nominated agent."),
    ("lc_soft_clause", "Hilaturas Miel v. Republic of Iraq (S.D.N.Y. 2008)",
     "The Bank shall not make any payment under this L/C unless the authorized United Nations "
     "officials approve such payment."),
    ("lc_soft_clause", "대법원 2017다235036 (취지)",
     "신용장 대금은 개설의뢰인의 지급동의서가 제출되어야 지급된다."),
    ("lc_soft_clause", "Gian Singh v. Banque de l'Indochine (PC 1974)",
     "A certificate signed by Balwant Singh holder of Malaysian passport E13276 certifying that "
     "the vessel has been built according to specifications."),
    # 재판매 조건부 결제 — 신용장 특수조건 꼴
    ("payment_on_resale", "대법원 98다47443",
     "최종매수인이 선하증권의 선적일로부터 75일 내에 신용장에 언급된 상품대금을 지급하지 않는 "
     "경우 인수된 어음과 서류들은 만기일에 지급되지 않는다."),
    # 무조건 반품
    ("full_return", "절강성 고급인민법원 (2011) 浙商外终字 第16号",
     "If the buyer is not satisfied with the machine's performance up to twenty days after "
     "delivery, the machine can be returned unconditionally to the seller."),
    # 수입국 검사기관이 최종
    ("inspection_buyer_sole", "CIETAC 심천 1999.4.7",
     "The parties agree that the goods shall be inspected by Guangdong Import and Export "
     "Commodities Inspection Bureau and that the inspection certificate issued by Guangdong "
     "Inspection Bureau is final and binding upon both parties."),
    # 소유권 유보 (필수)
    ("title", "Coutinho & Ferrostaal v. Tracomex (2015 BCSC 787)",
     "The Product shall remain the property of the Seller until full payment of the price has "
     "been received."),
    ("title", "Usinor Industeel v. Leeco Steel (N.D. Ill. 2002)",
     "Usinor remains the owner of the goods up to the complete and total payment of all sums due."),
]

# ── 실제 분쟁 문구 — 새 조항 ─────────────────────────────────────────────────
REAL_NEW = [
    ("battle_of_forms", "OGH 2017.6.29 8 Ob 104/16a",
     "AGB: the exclusive validity of our purchase terms is expressly agreed. For all orders "
     "exclusively our purchase terms apply."),
    ("battle_of_forms", "Hanwha v. Cedar · KCAB 2020~2024 (취지)",
     "The terms and conditions of the Buyer's purchase order shall prevail over any terms of "
     "the Seller's quotation or proforma invoice."),
    ("foreign_language_prevails", "NY Dept. of Health v. Rusi Technology (2022)",
     "This Contract is made in Chinese and English. In case of any discrepancy, the Chinese "
     "text shall prevail."),
    ("acceptance_signature_payment", "대법원 2021다242185 (2025.3.27)",
     "The first installment period shall start on the date on which the commissioning "
     "confirmation document is signed."),
    ("on_demand_bond", "Edward Owen v. Barclays (CA 1978)",
     "The Seller shall furnish a performance guarantee payable on demand without proof or conditions."),
    ("on_demand_bond", "대법원 2013다53700",
     "보증의뢰인이 수입계약을 불이행했다고 수익자가 판단하여 서면으로 청구하면 조건 없이 "
     "보증금액을 지급한다."),
    ("time_essence_cancel", "서울고법 2012나29719 (취지)",
     "If shipment is delayed by more than 7 days for reasons attributable to the Seller, the "
     "Buyer may cancel the order."),
    ("time_essence_cancel", "ICC Award 8128 (취지)",
     "Time of delivery is of the essence of this Contract."),
    ("cover_purchase", "서울고법 2008나14857 · CRCICA 2023 (취지)",
     "If the Seller fails to deliver on time, the Buyer may purchase substitute goods from a "
     "third party and the Seller shall bear all excess costs."),
    ("one_way_force_majeure", "CISG 판례의 매도인 불가항력 배척 (취지)",
     "Force majeure shall excuse only the Buyer's performance. The Seller shall not be relieved "
     "of its obligations by any force majeure event."),
    ("unilateral_amendment", "대한상의 상담사례 (L/C 단가 일방 인하, 취지)",
     "The Buyer may amend these terms and conditions at any time by written notice to the "
     "Seller, and such amendments shall bind the Seller."),
]


@pytest.mark.parametrize("key,source,line", REAL + REAL_NEW,
                         ids=[f"{k}:{s}" for k, s, _ in REAL + REAL_NEW])
def test_실제_분쟁_문구를_찾는다(key, source, line):
    assert key in _found(line), source


def test_새_독소조항에는_고치는_법이_있다():
    for key in {k for k, _, _ in REAL_NEW}:
        row = contract_clauses.by_key(key)
        assert row and row["category"] == "toxic" and row["fix"], key
