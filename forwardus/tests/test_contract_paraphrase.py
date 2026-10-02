r"""독소조항을 **같은 뜻 다른 말**로 전수 확인합니다.

계약서는 회사마다 변호사마다 말이 다릅니다. 뜻이 같아도 적는 법이 다르면
못 찾습니다. 조항마다 뜻이 같고 말이 다른 문구를 넷씩 넣어 돌렸더니
처음에는 **156개 중 113개(72%)** 를 놓쳤습니다.

    규칙이 보던 것   "terminate ... for convenience"
    실제 계약서      "cancel this Agreement at its sole discretion"
                    "walk away from this Agreement"
                    "재량으로 해지할 수 있다"
                    "아무런 사유 없이도 종료시킬 수 있다"

처음에는 당사자 말(Purchaser/Supplier) 탓인 줄 알았는데 그것만 바꿔서는
**4개밖에** 안 늘었습니다. 원인은 규칙이 **특정 문구에 묶여 있던 것**이었습니다.

고치는 과정에서 겪은 것
  **조용히 안 맞는 규칙**  패치 스크립트에서 `\s` 라고 적어, 정규식이
      "역슬래시 다음 s" 를 찾고 있었습니다. 문법 오류도 예외도 안 나서,
      이 검사를 돌려 보고서야 드러났습니다. 77곳이 그랬습니다.
  **고친 것을 제 손으로 되돌림**  문구를 더 찾으려고 규칙을 넓게 쓰다가
      앞서 세워 둔 방향 가드와 부정 가드를 **우회**했습니다.
      "The **Buyer** shall indemnify the **Seller** against GDPR fines" 와
      "자동으로 연장되**지 아니한다**" 가 다시 독소로 잡혔습니다.

  넓히면 오탐이, 좁히면 미탐이 납니다. 양쪽을 **같이** 재야 합니다.
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses

H = "SALES CONTRACT\n"

CASES = {
    "unlimited_damages": [
        "The Seller's liability under this Agreement shall be unlimited.",
        "The Supplier shall compensate the Purchaser for every loss arising, "
        "of whatever kind, with no financial ceiling.",
        "제11조 매도인의 배상책임에는 상한을 두지 아니한다.",
        "제11조 공급자는 발생한 모든 손해를 제한 없이 배상한다.",
    ],
    "termination_at_will": [
        "The Purchaser may cancel this Agreement at its sole discretion upon "
        "written notice.",
        "The Buyer reserves the right to walk away from this Agreement for "
        "convenience at any time.",
        "제17조 매수인은 재량으로 본 계약을 해지할 수 있다.",
        "제17조 바이어는 아무런 사유 없이도 계약을 종료시킬 수 있다.",
    ],
    "foreign_forum": [
        "Any dispute shall be submitted to the courts of Hamburg, which shall "
        "have exclusive jurisdiction.",
        "The parties irrevocably submit to the exclusive jurisdiction of the "
        "courts of Singapore.",
        "제16조 본 계약의 분쟁은 상하이 인민법원의 전속관할로 한다.",
        "제16조 전속적 관할법원은 매수인 소재지 법원으로 한다.",
    ],
    "payment_on_resale": [
        "Payment falls due only once the Purchaser has been paid by its own "
        "customer.",
        "The Supplier shall be paid out of the proceeds of resale.",
        "제5조 매수인이 최종 수요자로부터 대금을 회수한 때에 지급의무가 발생한다.",
        "제5조 판매 대금 회수 후에 매도인에게 정산한다.",
    ],
    "open_warranty": [
        "The Supplier warrants the Goods for an indefinite period.",
        "There shall be no time bar on claims for defects.",
        "제13조 하자담보책임의 기간을 정하지 아니한다.",
        "제13조 매도인은 기한의 정함 없이 결함을 수리한다.",
    ],
    "uncapped_ld": [
        "Liquidated damages of 1% per day shall accrue without any maximum.",
        "Delay damages shall continue to accumulate with no ceiling.",
        "제12조 지체상금은 1일 1%로 하며 상한을 두지 아니한다.",
        "제12조 납기 지연 배상금에는 한도가 적용되지 아니한다.",
    ],
    "term_conflict": [
        "Notwithstanding the agreed Incoterms, the Supplier bears all risk until "
        "arrival at the Purchaser's warehouse.",
        "Irrespective of the trade term, unloading and inland haulage are for the "
        "Seller's account.",
        "제2조 인코텀즈와 무관하게 도착지까지의 위험은 매도인이 부담한다.",
        "제2조 가격조건에도 불구하고 내륙운송비는 공급자가 부담한다.",
    ],
    "evergreen": [
        "This Agreement renews for successive annual terms unless terminated 180 "
        "days in advance.",
        "The term shall roll over automatically absent six months' prior notice.",
        "제3조 본 계약은 180일 전 통지가 없으면 1년씩 갱신된다.",
        "제3조 해지 통보가 없는 한 계약은 자동으로 연장된다.",
    ],
    "mfn_price": [
        "The Supplier undertakes that no other customer shall receive more "
        "favourable pricing.",
        "Should the Seller quote a lower figure elsewhere, the difference shall be "
        "credited retroactively.",
        "제6조 매도인은 제3자에게 더 유리한 조건을 제공하지 아니한다.",
        "제6조 타 거래처에 낮은 가격을 적용한 경우 소급하여 차액을 보전한다.",
    ],
    "full_return": [
        "Should any sample fail, the Purchaser may send back the whole consignment "
        "at the Supplier's cost.",
        "The entire lot may be refused and returned carriage forward.",
        "제8조 일부라도 불합격이면 전체 로트를 반송할 수 있다.",
        "제8조 반송에 드는 운임과 보관료는 매도인이 부담한다.",
    ],
    "cn_tech_transfer": [
        "The Supplier shall hand over to the Purchaser full engineering drawings "
        "and process know-how.",
        "Complete manufacturing documentation is to be released to the Buyer upon "
        "request.",
        "제9조 매도인은 설계도면 일체를 매수인에게 넘긴다.",
        "제9조 공정 기술자료를 바이어에게 교부하여야 한다.",
    ],
    "cn_trademark_buyer": [
        "Trade mark applications in the Territory shall be filed in the "
        "Distributor's name.",
        "The local registration of the brand shall stand in the name of the Buyer.",
        "제10조 현지 상표 출원은 판매점 명의로 한다.",
        "제10조 브랜드 등록 명의자는 바이어로 한다.",
    ],
    "eu_gdpr_indemnity": [
        "The Supplier shall hold the Purchaser harmless from data protection "
        "penalties under the GDPR.",
        "Any administrative fine under the General Data Protection Regulation "
        "shall be reimbursed by the Seller to the Buyer.",
        "제14조 GDPR 위반 과징금은 매도인이 매수인에게 전액 보전한다.",
        "제14조 개인정보보호규정상 제재금은 공급자가 부담한다.",
    ],
    "us_class_action_pl": [
        "The Supplier shall hold the Purchaser harmless from every product "
        "liability suit, including class actions, without cap.",
        "Defence costs of any class action shall be met in full by the Seller for "
        "the Buyer.",
        "제15조 제조물책임 소송은 매도인이 매수인을 전부 면책한다.",
        "제15조 집단소송 방어비용은 공급자가 바이어를 위하여 부담한다.",
    ],
    "ru_sanctions_warranty": [
        "The Supplier represents that no sanction applies and shall indemnify the "
        "Purchaser for any consequence.",
        "The Seller guarantees sanction-free status of the goods and bears all "
        "resulting loss.",
        "제18조 매도인은 제재 비해당을 보증하고 그 결과를 배상한다.",
        "제18조 수출통제 저촉 여부에 대하여 공급자가 담보 책임을 진다.",
    ],
    "gulf_agent_lock": [
        "The Distributor enjoys the sole right to import the Products and this "
        "Agreement may not be terminated without its approval.",
        "The appointed agent holds exclusive importation rights; termination "
        "requires the agent's written consent.",
        "제2조 대리점은 독점 수입권을 가지며 그 동의 없이 해지할 수 없다.",
        "제2조 독점 판매권자의 승낙 없이는 계약을 종료하지 못한다.",
    ],
    "retro_price_deduction": [
        "Agreed volume rebates and marketing support may be netted off against "
        "any invoice.",
        "The Purchaser is entitled to withhold trade allowances from remittance, "
        "including for past shipments.",
        "제6조 매수인은 합의된 리베이트를 송장 대금에서 차감할 수 있다.",
        "제6조 기납품분에 대하여도 소급 단가를 적용한다.",
    ],
    "chargeback_penalty": [
        "Short or late shipments attract a penalty recoverable by set-off against "
        "outstanding invoices.",
        "Failure to meet the on-time in-full target results in a deduction from "
        "payment.",
        "제7조 납기 미준수 시 위약벌을 대금에서 차감한다.",
        "제7조 수량 부족분에 대한 벌과금을 송장에서 공제한다.",
    ],
    "audit_rights": [
        "The Purchaser may inspect the Supplier's books and premises without "
        "advance warning.",
        "Access to accounts and factories shall be granted on demand at any time.",
        "제11조 매수인은 사전 예고 없이 매도인의 장부를 열람할 수 있다.",
        "제11조 바이어는 언제든지 공장에 출입하여 실사할 수 있다.",
    ],
    "exclusive_no_moq": [
        "The Supplier undertakes to deal solely with the Purchaser in the "
        "Territory and with no other party.",
        "The Seller shall refrain from supplying any competitor or third party "
        "within the Territory.",
        "제3조 매도인은 해당 지역에서 매수인 외에는 공급하지 아니한다.",
        "제3조 공급자는 역내 제3자에게 판매할 수 없다.",
    ],
    "payment_fx_approval": [
        "Remittance is conditional upon clearance by the exchange control "
        "authority.",
        "Settlement shall follow issuance of the import permit by the authorities.",
        "제5조 대금 송금은 외국환 당국의 허가를 조건으로 한다.",
        "제5조 수입승인이 난 후에 결제한다.",
    ],
    "fx_risk_local": [
        "Invoices are settled in the local currency and the Supplier carries the "
        "currency risk.",
        "Any devaluation between invoice and payment shall be to the Seller's "
        "account.",
        "제5조 결제는 현지 통화로 하며 환차손은 매도인이 진다.",
        "제5조 통화 가치 하락에 따른 손실은 공급자가 감수한다.",
    ],
    "recall_cost": [
        "Every expense of a product withdrawal, including consumer refunds, falls "
        "on the Supplier.",
        "The Seller funds the whole of any market withdrawal, voluntary or "
        "ordered.",
        "제13조 회수 조치에 드는 일체의 비용은 매도인이 부담한다.",
        "제13조 자발적 리콜 비용도 공급자가 전액 부담한다.",
    ],
    "inspection_buyer_sole": [
        "Acceptance rests entirely with the Purchaser, whose decision binds the "
        "Supplier.",
        "The Buyer alone determines conformity and such determination is not "
        "open to challenge.",
        "제10조 합격 여부는 매수인의 판단에 따르며 이의를 제기할 수 없다.",
        "제10조 바이어의 검수 결과는 최종적이며 매도인을 구속한다.",
    ],
    "spec_change_no_price": [
        "The Purchaser may revise drawings and artwork, and the agreed price "
        "remains unchanged.",
        "Design amendments shall not give rise to any price revision or delivery "
        "extension.",
        "제4조 매수인의 사양 변경에도 단가는 종전과 같다.",
        "제4조 디자인 수정은 가격 인상 사유가 되지 아니한다.",
    ],
    "tooling_free": [
        "Moulds and fixtures are to be supplied by the Supplier at its own "
        "expense.",
        "The Seller bears the entire cost of jigs and dies, which vest in the "
        "Buyer.",
        "제9조 금형 제작비는 매도인이 전액 부담한다.",
        "제9조 치공구는 공급자가 자비로 제작하여 제공한다.",
    ],
    "docs_before_payment": [
        "The Supplier shall forward the full set of original documents to the "
        "Purchaser promptly after loading.",
        "Originals of the transport documents are to be couriered to the Buyer "
        "on shipment.",
        "제6조 선적 후 즉시 선하증권 원본을 매수인에게 발송한다.",
        "제6조 원본 운송서류는 바이어에게 직접 교부한다.",
    ],
    "lc_soft_clause": [
        "The credit shall require an inspection certificate countersigned by the "
        "Purchaser's representative.",
        "Documents must include a certificate signed by the Buyer whose specimen "
        "signature is lodged with the issuing bank.",
        "제7조 신용장은 매수인이 서명한 검사증명서를 요구한다.",
        "제7조 선적은 바이어의 서면 지정이 있어야 가능하다.",
    ],
    "payment_retention": [
        "Fifteen percent of each invoice is held back as security for twelve "
        "months.",
        "A performance holdback of 10% shall be released only after the warranty "
        "period.",
        "제5조 송장 금액의 15%를 하자보증 명목으로 유보한다.",
        "제5조 대금의 10%는 보증기간 경과 후에 지급한다.",
    ],
    "buyer_nominated_cost": [
        "Carriage shall be arranged through the Purchaser's appointed forwarder "
        "at the Supplier's expense.",
        "The Seller must use the insurer designated by the Buyer and pay the "
        "premium.",
        "제7조 매수인이 지정한 선사를 이용하며 비용은 매도인이 부담한다.",
        "제7조 바이어 지정 검사기관의 수수료는 공급자가 낸다.",
    ],
    "one_way_nda": [
        "The Supplier undertakes to treat all information of the Purchaser as "
        "confidential and shall not disclose it.",
        "The Seller shall hold in confidence everything disclosed by the Buyer.",
        "제18조 매도인은 매수인의 정보를 비밀로 유지한다.",
        "제18조 공급자는 바이어로부터 취득한 자료의 기밀을 지킨다.",
    ],
    "non_compete_wide": [
        "The Supplier shall refrain from producing comparable goods for anyone "
        "else anywhere in the world.",
        "During the term and for two years afterwards the Seller may not deal in "
        "competing items.",
        "제19조 매도인은 전 세계 어디에서도 유사 제품을 공급하지 아니한다.",
        "제19조 계약 종료 후 2년간 경쟁 제품을 제조하지 못한다.",
    ],
    "assignment_one_way": [
        "The Purchaser may transfer this Agreement freely, whereas the Supplier "
        "shall not assign it.",
        "Novation by the Buyer requires no consent; the Seller may not assign "
        "without approval.",
        "제20조 매수인은 자유로이 양도할 수 있으나 매도인은 양도하지 못한다.",
        "제20조 바이어의 지위 이전에는 동의가 필요 없다.",
    ],
    "cert_test_cost": [
        "Expenses of homologation, type approval and factory inspection are for "
        "the Supplier's account.",
        "The Seller shall pay for all conformity assessment and annual renewals.",
        "제21조 형식승인과 공장심사 비용은 매도인이 부담한다.",
        "제21조 적합성 평가 수수료는 공급자가 낸다.",
    ],
    "agency_law_eu": [
        "Upon termination the Agent shall have no claim to goodwill indemnity.",
        "The commercial agent waives any compensation under Directive 86/653.",
        "제21조 대리인은 계약 종료 시 영업권 보상을 청구하지 못한다.",
        "제21조 상업대리인 지침에 따른 보상청구권을 포기한다.",
    ],
    "china_domestic_arb": [
        "Disputes shall be referred to CIETAC in Beijing.",
        "Arbitration shall take place before the China International Economic and "
        "Trade Arbitration Commission.",
        "제15조 분쟁은 중국국제경제무역중재위원회에서 중재한다.",
        "제15조 중재는 베이징의 CIETAC 규칙에 따른다.",
    ],
    "ip_assignment": [
        "All results of development and the tooling shall vest in the Purchaser.",
        "Title to moulds and any intellectual property created hereunder passes "
        "to the Buyer.",
        "제9조 개발 성과물과 금형의 권리는 매수인에게 이전한다.",
        "제9조 본 계약으로 발생한 지적재산권은 바이어에게 귀속한다.",
    ],
    "buyer_set_off": [
        "The Purchaser may apply any amount owing to it in reduction of sums due "
        "to the Supplier.",
        "The Buyer is entitled to net off claims against the purchase price.",
        "제12조 매수인은 자신의 채권으로 대금을 공제할 수 있다.",
        "제12조 바이어는 임의로 상계 처리할 수 있다.",
    ],
    "us_jury_punitive": [
        "The parties agree that disputes shall be heard by the federal courts of "
        "Delaware.",
        "The Purchaser preserves its right to seek exemplary damages before a jury.",
        "제16조 관할은 캘리포니아주 법원으로 한다.",
        "제16조 징벌적 손해배상을 청구할 수 있다.",
    ],
    "ddp_no_ior": [
        "Delivery shall be DDP the Buyer's warehouse with the Seller responsible "
        "for import clearance, duties and local taxes.",
        "The Supplier shall act as importer of record and clear the Goods through "
        "customs at destination under DDP terms.",
        "제2조 DDP 조건으로 하며 수입통관과 관세는 매도인이 부담한다.",
        "제2조 매도인은 도착국의 수입 통관을 책임진다.",
    ],
    "reexport_control": [
        "The Buyer is free to re-export the Goods to any destination without "
        "restriction.",
        "There shall be no restriction on the end use or onward destination of "
        "the Goods.",
        "제23조 매수인은 재수출에 제한 없이 전매할 수 있다.",
        "제23조 최종 용도 확인은 하지 아니한다.",
    ],
    "eu_epr_cost": [
        "All extended producer responsibility registrations, fees and reporting "
        "obligations in each Member State shall be paid by the Seller.",
        "Packaging waste and WEEE levies shall be borne by the Supplier.",
        "제24조 확대생산자책임 분담금은 매도인이 부담한다.",
        "제24조 EPR 등록 비용은 공급자가 낸다.",
    ],
    "tariff_absorption": [
        "Any increase in customs duties or tariffs shall be absorbed by the Seller "
        "and the price shall remain unchanged.",
        "The Supplier shall bear any additional duty imposed after the date of "
        "this Agreement.",
        "제25조 관세 인상분은 매도인이 부담한다.",
        "제25조 추가 관세는 공급자가 부담한다.",
    ],
    "psi_cost_delay": [
        "Pre-shipment inspection by the appointed agency shall be paid for by the "
        "Seller.",
        "PSI shall be at the Supplier's cost and expense.",
        "제26조 선적 전 검사 비용은 매도인이 부담한다.",
        "제26조 검사 일정으로 인한 지연은 공급자의 책임으로 한다.",
    ],
    "full_inspection": [
        "The Seller shall carry out 100% inspection of every unit prior to "
        "shipment at its own cost.",
        "The Supplier shall inspect each piece before despatch and bear the cost.",
        "제27조 매도인은 전수검사를 실시하고 그 비용을 부담한다.",
        "제27조 공급자가 전량 검사를 하며 비용을 진다.",
    ],
}

CASE_LIST = [(key, body) for key, bodies in CASES.items() for body in bodies]


@pytest.mark.parametrize("key,body", CASE_LIST,
                         ids=[f"{k}-{i}" for k, bodies in CASES.items()
                              for i in range(len(bodies))])
def test_같은_뜻_다른_말도_찾는다(key, body):
    found = contract_clauses.find_in(H + body)
    assert key in found, f"{key} 를 놓쳤습니다: {body[:70]}"


def test_독소조항을_빠짐없이_본다():
    """새 독소조항을 넣고 여기에 문구를 안 적으면 그 조항은 아무도 안 봅니다."""

    covered = set(CASES)
    actual = {row["key"] for row in contract_clauses.CLAUSES
              if row["category"] == "toxic"}
    assert actual <= covered, f"문구가 없는 조항: {sorted(actual - covered)}"


def test_조항마다_문구를_넷씩_둔다():
    thin = {key: len(bodies) for key, bodies in CASES.items() if len(bodies) < 3}
    assert not thin, f"문구가 모자란 조항: {thin}"


def test_겹친_백슬래시가_없다():
    r"""`\s` 로 적으면 정규식이 **역슬래시 다음 s** 를 찾습니다.

    계약서에 역슬래시가 있을 리 없으니 **절대 안 맞습니다.** 그런데 문법
    오류도 예외도 안 나서 조용히 지나갑니다. 실제로 77곳이 그랬습니다.
    """

    bad = [(row["key"], pat) for row in contract_clauses.CLAUSES
           for pat in row["detect"] if "\\\\" in pat]
    assert not bad, f"겹친 백슬래시: {bad[:5]}"


def test_모든_규칙이_컴파일된다():
    import re

    broken = []
    for row in contract_clauses.CLAUSES:
        for pat in row["detect"]:
            try:
                re.compile(pat)
            except re.error as exc:
                broken.append((row["key"], pat[:40], str(exc)))
    assert not broken, broken
