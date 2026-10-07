"""실제 분쟁에서 나온 이익조항 셋 (2026-10-04).

  lc_conformity      신용장은 계약과 일치해야 하고, 다른 조건은 매도인 동의가 있어야 함
                     — Bulgrains v. Shinhan(2013) · Hanil Bank v. BNI(2000): 수익자명
                       한 글자 차이로 지급거절. 서울고법 2010나29609 · RBRG v. Sinocore
                       (2018): 계약과 다른 L/C 를 매수인 위반으로 봄
  payment_account    지정 계좌로만 지급, 계좌 변경은 대표자 서명 서면으로만
                     — Korea Trade Insurance v. Oved Apparel(S.D.N.Y. 2015): 중개인
                       지시로 다른 계좌에 보낸 대금 회수가 막힘
  deemed_acceptance  N일 안에 서명·이의가 없으면 인수로 봄
                     — 대법원 2021다242185: 러시아 바이어가 시운전 확인서 서명을 거부
                     — ACR Systems v. Woori Bank: 검수서 미발행 시 수익자 진술로 대체

걸리면 안 되는 문장을 먼저 둡니다.
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses


def _present(line: str) -> set[str]:
    return contract_clauses.find_in("SALES CONTRACT\n" + line)


SAFE = [
    # lc_conformity — 서류가 L/C 에 맞아야 한다는 말(우리 의무), L/C 와 무관한 일치
    ("lc_conformity", "The Seller shall present documents in strict conformity with the L/C."),
    ("lc_conformity", "The Goods shall conform to the specifications in this Contract."),
    ("lc_conformity", "The L/C need not conform to this Contract."),
    # payment_account — 계좌를 정하지 않은 결제 조항
    ("payment_account", "Payment shall be made by T/T within 30 days after the B/L date."),
    ("payment_account", "Seller's bank details shall be advised separately."),
    ("payment_account", "The Buyer may change its delivery address by written notice."),
    # deemed_acceptance — 우리가 인수한 것으로 보는 꼴, 계약·발주 승낙, 클레임 포기
    ("deemed_acceptance", "The Seller shall be deemed to have accepted the Buyer's purchase "
                          "order if it does not reject it within 3 days."),
    ("deemed_acceptance", "Any purchase order shall be deemed accepted unless the Seller "
                          "objects within 2 days."),
    ("deemed_acceptance", "Any claim not notified within 30 days shall be deemed waived."),
    # ── 실제 계약서 1,310 건에서 걸렸던 문장 ──
    ("lc_conformity", "ANY TERMS OR CONDITIONS OF ANY PURCHASE ORDER OR ACKNOWLEDGMENT WHICH ARE "
                      "INCONSISTENT WITH THIS AGREEMENT SHALL HAVE NO EFFECT AND ARE HEREBY REJECTED."),
    ("lc_conformity", "Leica may only reject purchase orders that are not in conformity with this Agreement."),
    ("deemed_acceptance", "Buyer's submission of a purchase order shall be deemed acceptance of "
                          "and agreement to AB's Terms."),
    ("deemed_acceptance", "Beginning performance of the work called for by this Order shall be "
                          "deemed acceptance of this Order."),
    ("deemed_acceptance", "Notwithstanding Siemens' acceptance or deemed acceptance of any shipment "
                          "of Product, Siemens shall have the rights and remedies set forth in Section 5."),
    ("deemed_acceptance", "Payment of invoices will not be deemed acceptance of Goods."),
    ("deemed_acceptance", "Such failure shall be deemed acceptance of the conclusions of the Qualified Expert."),
]


@pytest.mark.parametrize("key,line", SAFE, ids=[f"{k}:{s[:28]}" for k, s in SAFE])
def test_이익조항이_아닌_문장은_있다고_하지_않는다(key, line):
    assert key not in _present(line)


PRESENT = [
    ("lc_conformity", "The L/C shall strictly conform to the terms of this Contract."),
    ("lc_conformity", "Any L/C term or amendment inconsistent with this Contract shall not bind "
                      "the Seller without its prior written consent."),
    ("lc_conformity", "제4조 신용장은 본 계약 조건과 일치하여야 한다."),
    ("payment_account", "All payments shall be made only to the Seller's account designated in Annex 2."),
    ("payment_account", "Payment to any other account shall not discharge the Buyer's payment obligation."),
    ("payment_account", "제4조 계좌 변경은 매도인 대표자가 서명한 서면으로만 효력이 있다."),
    ("deemed_acceptance", "If the Buyer fails to sign the acceptance certificate within 10 days "
                          "after commissioning, the Goods shall be deemed accepted."),
    ("deemed_acceptance", "Inspection at the port of loading shall be final, failing which the "
                          "Goods shall be deemed accepted."),
    ("deemed_acceptance", "제7조 매수인이 10일 이내에 인수 확인서를 발급하지 아니하면 인수한 것으로 본다."),
]


@pytest.mark.parametrize("key,line", PRESENT, ids=[f"{k}:{s[:28]}" for k, s in PRESENT])
def test_실제_분쟁에서_나온_이익조항을_찾는다(key, line):
    assert key in _present(line)


def test_세_조항은_이익조항이고_설명이_있다():
    for key in ("lc_conformity", "payment_account", "deemed_acceptance"):
        row = contract_clauses.by_key(key)
        assert row and row["category"] == "gain", key
        assert row["why"] and row["risk"] and row["text_en"] and row["text_ko"]


def test_간주_인수가_있으면_서명_조건부_지급은_독소가_아니다():
    """짝: 바이어 서명 조건부 지급(독소)에 간주 인수(이익)를 붙이면 풀립니다."""

    line = ("The first instalment shall become due on the date on which the commissioning "
            "certificate is signed by the Buyer, provided that if the Buyer fails to sign within "
            "10 days the Goods shall be deemed accepted.")
    found = _present(line)
    assert "deemed_acceptance" in found
    assert "acceptance_signature_payment" not in found
