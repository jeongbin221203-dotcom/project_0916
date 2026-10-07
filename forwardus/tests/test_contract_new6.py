"""새 독소조항 6종(2026-10-06) — 원천징수 gross-up · 중재인 일방 지명 · 인허가 바이어 명의 ·
매출채권 양도 금지 · ESG 비용 전가 · 브라질 대리인 보상.

전문가 점검 4회차가 "수출자에게 꼭 필요한데 아예 없다"고 짚은 것입니다. 걸리면 안 되는 문장(우리에게
유리하거나 정상인 반대 방향)을 먼저 시험합니다.
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses
from app.services import contract_clause_service as service

H = "SALES CONTRACT\n"
NEW = ("withholding_no_grossup", "arbitrator_one_sided", "licence_in_buyer_name",
       "receivables_assign_ban", "esg_cost_shift", "br_agent_indemnity")


def _found(doc: str) -> set[str]:
    return contract_clauses.find_in(H + doc)


# ── 걸리면 안 되는 문장 ───────────────────────────────────────────────────────
SAFE = [
    # gross-up 이 있거나, 세금을 바이어가 지거나, 원천징수를 말하지 않음
    ("withholding_no_grossup", "If the Buyer is required by law to withhold any tax, the Buyer shall gross up the "
                               "payment so that the Seller receives the full invoice amount."),
    ("withholding_no_grossup", "If the Buyer is required to withhold tax, the Buyer shall pay such additional "
                               "amounts as will result in the Seller receiving the full amount."),
    ("withholding_no_grossup", "Any withholding tax shall be borne by the Buyer."),
    ("withholding_no_grossup", "The Seller shall bear its own income taxes in Korea."),
    ("withholding_no_grossup", "원천징수세액은 매수인이 부담하고 매도인에게 대금 전액을 지급한다."),
    ("withholding_no_grossup", "The Buyer shall not withhold or deduct any tax from the price."),
    # 말뭉치(EDGAR·CUAD)에서 새로 걸렸던 정상 문장 — 재무 정의·회계·바이어가 세금을 보전
    ("withholding_no_grossup", "Net Proceeds are all payments which Purchaser receives in a Liquidity Event net of "
                               "any Taxes payable by Purchaser."),
    ("withholding_no_grossup", "Income taxes paid, net of tax refunds received, were 86,066 in thousands."),
    ("withholding_no_grossup", "The prices set forth in Attachment A are net of all taxes and duties, and the "
                               "Buyer will reimburse the Seller for any taxes imposed in connection with this "
                               "Agreement."),
    # 중재인 — 합의·각자 지명·기관 규칙·우리가 지명
    ("arbitrator_one_sided", "The arbitrators shall be appointed in accordance with the ICC Rules."),
    ("arbitrator_one_sided", "Each party shall appoint one arbitrator, and the two arbitrators shall appoint the "
                             "chair."),
    ("arbitrator_one_sided", "The sole arbitrator shall be appointed by agreement of the parties."),
    ("arbitrator_one_sided", "The arbitrator shall be appointed by the Seller."),
    ("arbitrator_one_sided", "The sole arbitrator shall be appointed jointly by the Buyer and the Seller."),
    ("arbitrator_one_sided", "중재인은 양 당사자가 합의하여 선정한다."),
    # 인허가 — 우리 명의·상표(다른 조항)
    ("licence_in_buyer_name", "The marketing authorisation shall be held in the name of the Seller, and the "
                              "Distributor shall assist with filings."),
    ("licence_in_buyer_name", "The Distributor shall not hold any registration in its own name."),
    ("licence_in_buyer_name", "The trademark registration shall be held in the name of the Distributor."),
    ("licence_in_buyer_name", "The Seller shall obtain the import licence for the Goods."),
    # 채권 — 양도 허용·바이어의 양도·계약 양도
    ("receivables_assign_ban", "The Seller may assign its receivables under this Contract to a bank or a "
                               "factoring company."),
    ("receivables_assign_ban", "The Buyer shall not assign its payment obligations without the Seller's consent."),
    ("receivables_assign_ban", "Neither party may assign this Contract without the other party's written consent."),
    ("receivables_assign_ban", "The Seller shall not assign any receivables, except to a bank or an export credit "
                               "insurer."),
    ("receivables_assign_ban", "매도인은 대금 채권을 은행에 양도할 수 있다."),
    # ESG — 바이어 부담·각자 부담·준수 의무
    ("esg_cost_shift", "The Buyer shall bear all CBAM certificate costs as the importer."),
    ("esg_cost_shift", "Each party shall bear its own carbon border adjustment costs."),
    ("esg_cost_shift", "The Seller shall not be liable for CBAM costs."),
    ("esg_cost_shift", "The Seller shall comply with the Supplier Code of Conduct in force on the date of this "
                       "Contract."),
    # 브라질 — 대리인 아닌 거래·다른 나라
    ("br_agent_indemnity", "The Distributor purchases the Goods for its own account and resale in Brazil."),
    ("br_agent_indemnity", "The Seller shall pay the Agent a commission of 5% of the net invoice value."),
    ("br_agent_indemnity", "Termination indemnity shall be one month of average commission."),
]


@pytest.mark.parametrize("key,doc", SAFE, ids=[f"{k}:{d[:26]}" for k, d in SAFE])
def test_정상_유리한_문장은_독소가_아니다(key, doc):
    assert key not in _found(doc)


# ── 걸려야 하는 문장 ──────────────────────────────────────────────────────────
FLAGGED = [
    ("withholding_no_grossup", "All payments shall be made after deduction of tax at source. The Company shall "
                               "not be required to gross up any payment."),
    ("withholding_no_grossup", "The Buyer shall not be required to gross up any payment."),
    ("withholding_no_grossup", "There shall be no gross-up for withholding taxes."),
    ("withholding_no_grossup", "All payments shall be net of any withholding tax."),
    ("withholding_no_grossup", "Any withholding tax shall be borne by the Seller."),
    ("withholding_no_grossup", "The Seller shall bear all withholding tax imposed in India."),
    ("withholding_no_grossup", "원천징수세액은 매도인이 부담한다."),
    ("arbitrator_one_sided", "The arbitration shall be conducted by a sole arbitrator appointed by the Buyer."),
    ("arbitrator_one_sided", "The Buyer may appoint the sole arbitrator in its discretion."),
    ("arbitrator_one_sided", "중재인은 매수인이 단독으로 지명한다."),
    ("licence_in_buyer_name", "The marketing authorisation and product registration shall be held in the name of "
                              "the Distributor."),
    ("licence_in_buyer_name", "The Distributor shall obtain the product registration in its own name."),
    ("licence_in_buyer_name", "The SFDA registration certificate shall be held by the Distributor in the name of "
                              "the Distributor."),
    ("licence_in_buyer_name", "수입 허가증은 판매점 명의로 등록한다."),
    ("receivables_assign_ban", "The Seller shall not assign, transfer or factor any receivables arising under "
                               "this Contract."),
    ("receivables_assign_ban", "The Seller may not assign the receivables, including to banks or factoring "
                               "companies."),
    ("receivables_assign_ban", "Factoring of the invoices is not permitted."),
    ("receivables_assign_ban", "매도인은 이 계약에 따른 매출채권을 양도할 수 없다."),
    ("esg_cost_shift", "The Seller shall bear all costs and losses arising from any detention under forced labour "
                       "laws, regardless of whether forced labour is proven."),
    ("esg_cost_shift", "The Seller shall pay all CBAM certificate costs relating to the Goods."),
    ("esg_cost_shift", "CBAM charges shall be borne by the Seller."),
    ("esg_cost_shift", "The Buyer may unilaterally amend this Supplier Code of Conduct, which shall be binding "
                       "upon publication."),
    ("br_agent_indemnity", "The Seller shall not terminate this Agreement without just cause and shall pay the "
                           "Representative an indemnity equal to 1/12 of total commissions."),
    ("br_agent_indemnity", "This Agency Agreement is subject to Brazilian Law No. 4.886/65."),
    ("br_agent_indemnity", "해지 시 대리인에게 총 수수료의 12분의 1을 보상한다."),
]


@pytest.mark.parametrize("key,doc", FLAGGED, ids=[f"{k}:{d[:26]}" for k, d in FLAGGED])
def test_위험한_문구를_찾는다(key, doc):
    assert key in _found(doc)


# ── 짜임새 ──────────────────────────────────────────────────────────────────
def test_새_조항은_모두_독소고_묶음이_있다():
    for key in NEW:
        row = contract_clauses.by_key(key)
        assert row and row["category"] == "toxic"
        assert key in contract_clauses.TOXIC_GROUP
        assert row["fix"] and row["why"] and row["risk"]


def test_조항_수는_독소_61개_모두_93개다():
    kinds = {}
    for row in contract_clauses.CLAUSES:
        kinds[row["category"]] = kinds.get(row["category"], 0) + 1
    assert kinds == {"must": 14, "gain": 18, "toxic": 61}
    assert len(contract_clauses.CLAUSES) == 93


@pytest.mark.parametrize("key", NEW)
def test_조항은_제_예문을_찾는다(key):
    example = contract_clauses.fill_blanks(contract_clauses.by_key(key)["text_en"]).split(")", 1)[1]
    assert key in _found(example)


@pytest.mark.parametrize("country,key", [("IN", "withholding_no_grossup"), ("VN", "withholding_no_grossup"),
                                         ("SA", "licence_in_buyer_name"), ("BR", "br_agent_indemnity")])
def test_도착국에_흔한_조항으로_앞세운다(country, key):
    toxic = service.checklist("FOB", country=country)["toxic"]
    assert next(row for row in toxic if row["key"] == key)["for_country"]


def test_다른_나라에서는_앞세우지_않는다():
    toxic = service.checklist("FOB", country="DE")["toxic"]
    assert not next(row for row in toxic if row["key"] == "br_agent_indemnity")["for_country"]


def test_계약서에_없으면_도착국_주의로_안내한다():
    result = service.review(H + "PAYMENT T/T within 30 days after B/L date.", "FOB", "IN")
    watch = {row["key"]: row for row in result["watch_country"]}
    assert "withholding_no_grossup" in watch
    assert "gross-up" in watch["withholding_no_grossup"]["watch_note"]
    assert "gross-up" in service.as_text(result)


def test_독소로_짚으면_고치는_법과_근거를_보여_준다():
    result = service.review(H + "The Seller shall not assign, transfer or factor any receivables arising under "
                                "this Contract.", "FOB")
    row = next(row for row in result["toxic"] if row["key"] == "receivables_assign_ban")
    assert row["evidence"] and "은행·팩토링사" in row["fix"]
    assert "허용" in service.toxic_note("receivables_assign_ban")


def test_고치는_법이_권하는_문장은_다시_독소로_짚지_않는다():
    for key in NEW:
        fix = contract_clauses.by_key(key)["fix"]
        # fix 속 영어 인용문만 — 한글 설명은 계약서 문장이 아닙니다.
        quotes = [part for part in fix.split("'") if part.isascii() and len(part) > 25]
        for quote in quotes:
            assert key not in _found(quote), (key, quote)
