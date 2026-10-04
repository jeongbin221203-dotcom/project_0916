"""수출자(매도인) 입장 — 방향이 뒤집히면 독소가 아닙니다 (2026-10-03).

왜 이 파일이 있나
  독소조항 55개의 예문에서 Seller ↔ Buyer 를 맞바꿔 보니 20개가 그대로
  걸렸습니다. 대부분은 바꾼 문장이 실무에 없거나(매도인이 재판매 대금을 받아야
  지급) 방향과 무관합니다(상대국 법원·인코텀즈 충돌). 그런데 아래 8개는 바꾼
  문장이 **실무에 흔하고 우리에게 유리합니다** — 바이어 연체 지연배상, 바이어의
  제재 확약, 독점 대리점의 경업금지. 이것을 지우라고 하면 우리가 손해입니다.

  각 조항마다 **유리한 쪽(걸리면 안 됨)**과 **원래 쪽(걸려야 함)**을 짝으로 둡니다.
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses

PAIRS = [
    # (key, 우리에게 유리 — 걸리면 안 됨, 우리에게 불리 — 걸려야 함)
    ("termination_at_will",
     "The Seller may terminate this Contract at any time for convenience upon written notice.",
     "The Buyer may terminate this Contract at any time for convenience upon written notice."),
    ("uncapped_ld",
     "The Buyer shall pay liquidated damages of 1% of the overdue amount for each day of delay "
     "in payment.",
     "The Seller shall pay liquidated damages of 1% of the contract value for each day of delay."),
    ("us_class_action_pl",
     "The Buyer shall defend, indemnify and hold harmless the Seller against all product "
     "liability claims, including class actions, arising from the Buyer's modification of the Goods.",
     "The Seller shall defend, indemnify and hold harmless the Buyer against all product "
     "liability claims, including class actions, without limitation."),
    ("ru_sanctions_warranty",
     "The Buyer warrants that neither the Buyer nor the end user is subject to any sanctions, "
     "and shall indemnify the Seller for all consequences thereof.",
     "The Seller warrants that neither the Goods nor the transaction is subject to any "
     "sanctions, and shall indemnify the Buyer for all consequences thereof."),
    ("non_compete_wide",
     "The Buyer shall not manufacture, sell or distribute any similar or competing products "
     "in the Territory during the term and for three (3) years thereafter.",
     "The Seller shall not manufacture, sell or supply any similar or competing products to "
     "any other party worldwide during the term and for three (3) years thereafter."),
    ("audit_rights",
     "The Seller may audit the Buyer's sales records at any time without prior notice.",
     "The Buyer may audit the Seller's facilities, books and records at any time without "
     "prior notice."),
    ("acceptance_signature_payment",
     "The first instalment shall become due on the date on which the commissioning "
     "confirmation document is signed by the Seller.",
     "The first instalment shall become due on the date on which the commissioning "
     "confirmation document is signed by the Buyer."),
    ("spec_change_no_price",
     "The Seller may change the specifications or packaging at any time, and such change "
     "shall not affect the price or the delivery date.",
     "The Buyer may change the specifications, packaging or labelling at any time, and such "
     "change shall not affect the price or the delivery date."),
]

PAIRS += [
    # 조항 설명의 예문을 못 찾고 있었습니다 — 'responsibility' 에서 'Seller' 까지가
    # 100자를 넘었습니다. 바이어가 내는 꼴은 우리에게 유리합니다.
    ("eu_epr_cost",
     "All extended producer responsibility registrations, fees and reporting obligations in "
     "each Member State shall be undertaken and paid by the Buyer as importer.",
     "All extended producer responsibility registrations, fees and reporting obligations in "
     "each Member State shall be undertaken and paid by the Seller."),
    ("eu_epr_cost",
     "Extended producer responsibility fees for packaging shall be borne by the Buyer.",
     "Extended producer responsibility fees for packaging shall be borne by the Seller."),
]

KO_PAIRS = [
    ("termination_at_will", "제5조 매도인은 언제든지 서면 통지로 본 계약을 해지할 수 있다.",
     "제5조 매수인은 언제든지 서면 통지로 본 계약을 해지할 수 있다."),
    ("non_compete_wide",
     "제9조 매수인은 계약기간 중 및 종료 후 3년간 경쟁 제품을 판매하여서는 아니 된다.",
     "제9조 매도인은 계약기간 중 및 종료 후 3년간 전 세계 어느 누구에게도 유사 제품을 공급할 수 없다."),
]

ALL = PAIRS + KO_PAIRS


@pytest.mark.parametrize("key,ours,_", ALL, ids=[f"{k}-유리" for k, _, _ in ALL])
def test_우리에게_유리한_방향은_독소가_아니다(key, ours, _):
    assert key not in contract_clauses.find_in("SALES CONTRACT\n" + ours)


@pytest.mark.parametrize("key,_,theirs", ALL, ids=[f"{k}-불리" for k, _, _ in ALL])
def test_우리에게_불리한_방향은_독소다(key, _, theirs):
    assert key in contract_clauses.find_in("SALES CONTRACT\n" + theirs)


ONE_WAY_NDA_THEN_OTHER = [
    # 다음 조항의 "both parties"(서명·검사)는 비밀유지 얘기가 아닙니다 (m_contract 2026-10-03)
    "The Seller shall keep confidential all information received from the Buyer and shall not "
    "disclose it to any third party. 19. AMENDMENT No amendment shall be effective unless "
    "signed by the authorised representatives of both parties.",
    "The Seller shall keep confidential all information received from the Buyer and shall not "
    "disclose it to any third party. 5. INSPECTION The certificate shall be final and binding "
    "on both parties as to quality and quantity.",
]
MUTUAL_NDA = [
    "The Seller shall keep confidential all information received from the Buyer. The Buyer "
    "shall likewise keep confidential all information received from the Seller.",
    "The Seller shall keep confidential all information received from the Buyer. Each party "
    "shall keep confidential the information disclosed by the other party.",
    "The Seller shall keep confidential all information received from the Buyer. This "
    "confidentiality obligation shall be mutual and binding on both parties.",
]


@pytest.mark.parametrize("doc", ONE_WAY_NDA_THEN_OTHER)
def test_다른_조항의_both_parties_로_일방_비밀유지를_놓치지_않는다(doc):
    assert "one_way_nda" in contract_clauses.find_in("SALES CONTRACT\n" + doc)


@pytest.mark.parametrize("doc", MUTUAL_NDA)
def test_비밀유지가_쌍방이면_일방이_아니다(doc):
    assert "one_way_nda" not in contract_clauses.find_in("SALES CONTRACT\n" + doc)


def test_양쪽_모두_해지할_수_있어도_우리에게는_위험하다():
    """'Either party' 는 바이어도 할 수 있다는 뜻입니다 — 생산한 뒤 끊기는 위험은 그대로."""

    line = "Either party may terminate this Contract at any time for convenience upon notice."
    assert "termination_at_will" in contract_clauses.find_in("SALES CONTRACT\n" + line)
