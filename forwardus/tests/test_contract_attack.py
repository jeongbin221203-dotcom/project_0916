"""조항표를 **깨뜨리려고** 만든 계약서들.

지금까지는 "맞는지"를 봤습니다. 이 파일은 "어떻게 하면 틀리게 만들 수 있나"를
봅니다. 실제로 셋이 뚫렸고, 그중 하나는 이 프로젝트에서 가장 위험한 종류였습니다.

뚫린 것 (2026-10-02)
  **목차만 보고 '다 갖췄다'**  계약서 앞에는 조항 제목이 줄줄이 적힌 목차가
      붙습니다. 제목만 보는 규칙이라 **내용이 하나도 없는데 필수조항 14개 중
      13개를 '있다'**고 했습니다.

      독소조항 오탐은 멀쩡한 조항을 지우게 만듭니다. 그런데 이건 **없는 조항을
      있다고** 해서, 사용자가 그 조항 **없이 계약하게** 만듭니다. 더 나쁩니다.

  **정의 조항을 의무로 읽음**  `"Chargeback" means any deduction asserted by a
      customer of the Buyer.` 는 낱말의 뜻을 적은 것인데 독소조항으로 짚었습니다.

  **최소 구매량이 있어도 '없다'고 함**  exclusive_no_moq 는 제목이 "독점 공급
      의무 — 최소 구매량을 함께 보세요" 인데, 최소 구매량이 있는지 없는지는
      보지 않았습니다. 독점만 보이면 떴습니다. MOQ 를 제대로 넣은 계약서에서도
      떠서, 고친 사람에게 다시 고치라고 했습니다.

막지 못한 것도 있습니다 — 본문을 별지로 뺀 계약서는 본문에 아무것도 없어
읽을 것이 없습니다. 그건 **맞는 동작**입니다(빠졌다고 말해야 합니다).
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses

MUST = {row["key"] for row in contract_clauses.CLAUSES if row["category"] == "must"}
TOXIC = {row["key"] for row in contract_clauses.CLAUSES if row["category"] == "toxic"}

# 실제 계약서 앞에 붙는 목차. 제목만 있고 내용은 하나도 없습니다.
TABLE_OF_CONTENTS = """SALES CONTRACT

TABLE OF CONTENTS

1. DESCRIPTION OF GOODS
2. PRICE AND INCOTERMS
3. PAYMENT TERMS
4. SHIPMENT
5. PACKING AND MARKING
6. INSPECTION
7. INSURANCE
8. FORCE MAJEURE
9. GOVERNING LAW
10. ARBITRATION
11. RETENTION OF TITLE
12. QUANTITY TOLERANCE
13. CONFIDENTIALITY
14. AMENDMENT AND NOTICES

(The terms of each article are set out in Annex 1.)
"""

# 제목 **뒤에 본문이 따라오는** 진짜 계약서. 목차 걷어내기가 이걸 지우면 안 됩니다.
REAL_WITH_HEADINGS = """SALES CONTRACT

1. DESCRIPTION OF GOODS
The Seller shall sell the goods specified in Annex 1, which forms an integral
part of this Contract.

5. PACKING AND MARKING
The Goods shall be packed in export standard seaworthy packing and each package
shall bear the shipping marks set out in Annex 2.

13. CONFIDENTIALITY
Each party shall keep confidential all information disclosed by the other party.
"""

# 뜻풀이만 있는 계약서
DEFINITIONS_ONLY = """SALES CONTRACT

1. DEFINITIONS
"Confidential Information" means any technical drawings, bills of materials or
process documentation provided by either party.
"Chargeback" means any deduction asserted by a customer of the Buyer.
"Set-off" means the discharge of mutual debts.
"Punitive damages" means damages awarded in excess of actual loss.
"""

# 독점과 최소 구매량이 **함께** 있는 계약서. 한쪽만 묶이지 않습니다.
EXCLUSIVE_WITH_MOQ = """SALES CONTRACT

3. EXCLUSIVITY: The Seller shall supply the Products exclusively to the Buyer in
   the Territory, provided that the Buyer purchases a minimum of 50,000 units per
   contract year. If the minimum is not met, the exclusivity shall automatically
   lapse and the Seller may supply any third party.
"""

# 독점만 있고 최소 구매량이 **없는** 계약서. 이건 떠야 합니다.
EXCLUSIVE_NO_MOQ = """SALES CONTRACT

3. EXCLUSIVITY: The Seller shall supply the Products exclusively to the Buyer in
   the Territory and shall not sell to any other party therein.
"""

# 이익조항을 제대로 넣어 고친 계약서
GUARDED = """SALES CONTRACT

11. LIMITATION OF LIABILITY: The Seller's aggregate liability under this Contract
    shall not exceed the invoice value of the relevant order.
12. SET-OFF: The Buyer shall pay all amounts in full without any set-off,
    deduction or withholding.
13. WARRANTY: twelve (12) months from the date of shipment.
8.  RETURN: only defective units may be returned within 14 days.
"""


def _toxic(text: str) -> set[str]:
    return contract_clauses.find_in(text) & TOXIC


def _must(text: str) -> set[str]:
    return contract_clauses.find_in(text) & MUST


def test_목차만으로는_필수조항을_찾지_않는다():
    """**가장 위험한 오탐이었습니다.**

    없는 조항을 '있다'고 하면 사용자는 그 조항 없이 계약합니다. 독소 오탐보다
    나쁩니다 — 독소 오탐은 멀쩡한 조항을 지우게 하지만, 이건 보호 장치가
    아예 없는 채로 내보냅니다.
    """

    found = _must(TABLE_OF_CONTENTS)
    assert len(found) <= 2, f"목차만 있는데 필수조항 {len(found)}개를 찾았습니다: {sorted(found)}"


def test_제목_뒤에_본문이_있으면_제대로_찾는다():
    """목차를 걷어내다 **진짜 조항까지 지우면** 안 됩니다.

    진짜 계약서도 제목 줄로 시작합니다. 다른 점은 제목 뒤에 본문이 따라온다는
    것이고, 그래서 제목 줄이 연달아 나오지 않습니다.
    """

    found = _must(REAL_WITH_HEADINGS)
    assert {"goods", "packing", "confidential"} <= found, sorted(found)


def test_뜻풀이는_의무가_아니다():
    """'Chargeback' means ... 는 낱말의 뜻이지 의무가 아닙니다."""

    found = _toxic(DEFINITIONS_ONLY)
    assert not found, f"정의 조항을 독소로 짚었습니다: {sorted(found)}"


def test_최소_구매량이_있으면_독점을_짚지_않는다():
    """독점이라도 MOQ 가 함께 있으면 한쪽만 묶이지 않습니다.

    조항 제목이 "최소 구매량을 함께 보세요" 인데 정작 보지 않고 있었습니다.
    """

    assert "exclusive_no_moq" not in _toxic(EXCLUSIVE_WITH_MOQ)


def test_최소_구매량이_없으면_독점을_짚는다():
    """위 예외가 너무 넓어 **진짜를 놓치면** 안 됩니다."""

    assert "exclusive_no_moq" in _toxic(EXCLUSIVE_NO_MOQ)


def test_제대로_고친_계약서는_독소가_없다():
    """책임 한도·상계 금지·보증 기한·반품 제한을 넣은 계약서.

    고친 사람에게 다시 고치라고 하면, 다음부터는 이 화면을 믿지 않습니다.
    """

    found = _toxic(GUARDED)
    assert not found, f"고친 계약서에서 독소 {sorted(found)} 를 짚었습니다"


@pytest.mark.parametrize("label,text", [
    ("목차", TABLE_OF_CONTENTS),
    ("뜻풀이", DEFINITIONS_ONLY),
    ("고친 계약서", GUARDED),
])
def test_공격_문서에서_독소가_뜨지_않는다(label, text):
    found = _toxic(text)
    assert not found, f"{label}: {sorted(found)}"


# ── 공격 10. 이익조항을 못 찾으면 '넣으세요'라고 합니다 ──────────────────────
#
# 이익조항의 미탐은 **이미 넣은 사람에게 "넣으세요"** 라고 하는 것입니다.
# 책임 한도는 여섯 가지 흔한 문구 중 **다섯을 놓치고** 있었습니다.
# 그리고 `consequential` 을 홀로 보던 탓에 **무제한 배상 조항을 '한도가 있다'**
# 로 읽었습니다. 정반대입니다. (2026-10-02)

CAP_PRESENT = [
    "The Seller's liability shall not exceed the invoice value.",
    "The Seller's aggregate liability under this Contract shall not exceed the "
    "invoice value of the relevant order.",
    "In no event shall the Seller's total liability exceed the price paid for the Goods.",
    "Liability is limited to the contract price.",
    "The Seller shall not be liable for any indirect or consequential loss.",
    "제11조 매도인의 총 손해배상책임은 해당 주문 금액을 초과하지 아니한다.",
    "제11조 책임의 한도는 송장 금액으로 한다.",
    "제11조 배상액은 송장 금액으로 한정한다.",
]

CAP_ABSENT = [
    # 무제한 배상입니다. '한도가 있다'로 읽으면 정반대입니다.
    "The Seller shall be liable for all direct, indirect and consequential damages "
    "without limitation.",
    "제11조 매도인은 손해 전부를 배상하며, 그 책임에는 한도가 없다.",
    "The Seller shall indemnify the Buyer for any and all losses of whatever nature.",
]


@pytest.mark.parametrize("body", CAP_PRESENT)
def test_책임_한도가_있으면_찾는다(body):
    """못 찾으면 이미 넣은 사람에게 '넣으세요'라고 하게 됩니다."""

    assert "liability_cap" in contract_clauses.find_in("SALES CONTRACT\n" + body)


@pytest.mark.parametrize("body", CAP_ABSENT)
def test_무제한_배상을_책임_한도로_읽지_않는다(body):
    """정반대를 '있다'고 하면, 보호 장치가 없는 채로 내보냅니다."""

    assert "liability_cap" not in contract_clauses.find_in("SALES CONTRACT\n" + body)
