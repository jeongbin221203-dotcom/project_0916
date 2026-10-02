"""독소조항 판정을 **문서 단위로** 흔듭니다.

왜 따로 있나
  test_contract_countries.py 는 한 문장씩 봅니다. 그런데 실제 계약서는 조항이
  20개 넘게 한 문서에 있고, PDF 에서 읽으면 줄이 꺾이고 쪽 머리글이 문장
  가운데 끼어듭니다. 한 문장씩 맞아도 문서로 묶으면 틀릴 수 있습니다.

여기서 찾은 것 (2026-10-02)
  **거의 모든 영문 계약서에서 뜨던 오탐** — unlimited_damages 규칙에
  `without limitation` 이 맨 낱말로 들어 있었습니다. 그런데 영문 계약서에서
  "including without limitation" 은 "~를 포함하되 이에 한정되지 않는"이라는
  상투어이고 책임 한도와 상관이 없습니다. 이 말은 실무 계약서 대부분에
  들어가므로, 이 오탐은 드문 일이 아니라 **거의 매번** 났을 것입니다.

  **제목에 적힌 표현조차 못 잡던 미탐** — open_warranty 는 제목이 "기간 제한
  없는 하자보증"인데 국문 규칙은 `무기한` 하나뿐이었습니다.

그리고 한 가지 더
  동시에 짚히는 것이 다 오탐은 아닙니다. 면책 범위에 한도가 없으면 그건
  무제한 책임이기도 하고, 대금에서 빼는 것은 상계이기도 합니다. 그걸 오탐으로
  적으면 **맞는 동작을 고치려** 들게 됩니다. ALSO 에 적어 둡니다.
"""

from __future__ import annotations

import random
import re
import time

import pytest

from app.processors import contract_clauses

HEAD = "SALES CONTRACT\n물품매매계약서\n\n"

# 걸리면 안 되는 조항들. 전부 우리에게 유리하거나 중립입니다.
SAFE_CLAUSES = [
    "제12조 (상계) 매수인은 본 계약상 대금지급의무를 어떠한 채권으로도 상계할 수 없다.",
    "제3조 (계약기간) 본 계약의 유효기간은 1년이며, 양 당사자가 서면으로 합의하지 "
    "아니하는 한 자동으로 연장되지 아니한다.",
    "제9조 (지식재산권) 본 계약의 이행으로 발생하는 금형 및 지식재산권은 매도인에게 귀속한다.",
    "제11조 (책임의 제한) 매도인의 총 손해배상책임은 해당 주문 금액의 100%를 초과하지 아니한다.",
    "제8조 (반품) 매수인은 하자 있는 물품에 한하여 인도 후 14일 내에 반품할 수 있고, "
    "그 밖의 사유로는 전량 반품을 요구할 수 없다.",
    "제15조 (분쟁해결) 본 계약에 관한 분쟁은 대한민국 서울에서 대한상사중재원의 중재로 해결한다.",
    "제14조 (준거법) 본 계약은 대한민국 법률에 따라 해석된다.",
    "제16조 (관할) 전속적 합의관할은 서울중앙지방법원으로 한다.",
    "제5조 (대금지급) 매수인은 선적서류 제시 후 30일 내에 대금을 지급한다.",
    "제17조 (해지) 어느 당사자도 상대방의 중대한 계약위반이 있고 30일의 시정기간이 "
    "지난 경우에만 본 계약을 해지할 수 있다.",
    "제13조 (하자보증) 하자보증기간은 선적일로부터 12개월로 한다.",
    "제4조 (규격 변경) 매수인이 규격을 변경하는 경우 단가와 납기를 다시 정한다.",
    # 영문 — 방향이 우리에게 유리한 것들
    "Article 9 The Buyer shall provide the Seller with technical drawings for the "
    "Buyer's own design.",
    "Article 14 The Buyer shall indemnify the Seller against any fines imposed under "
    "the General Data Protection Regulation.",
    "Article 7 No chargebacks or deductions shall be permitted under this Agreement.",
    "Article 11 The Buyer may audit the Seller's records once per calendar year upon "
    "thirty days' prior written notice.",
    "Article 3 The Buyer shall purchase the Products exclusively from the Seller.",
    "Article 10 In case of dispute, the determination of SGS at the port of loading "
    "shall be final and binding on both parties.",
    # 영문 상투어 — 실무 계약서 대부분에 들어갑니다
    "Article 1 The Goods shall include, without limitation, packaging, manuals and "
    "spare parts as listed in Annex 1.",
    "Article 20 This Agreement constitutes the entire agreement between the parties.",
    "Article 21 The headings in this Agreement are for convenience only.",
    "Article 23 If any provision is held invalid, the remainder shall continue in "
    "full force and effect.",
    "제16조 양 당사자는 배심재판을 받을 권리를 포기한다.",
    "Article 17 Punitive damages are expressly excluded under this Agreement.",
    "제6조 단가 조정은 장래 주문에만 적용하며, 소급하여 가격을 인하하지 아니한다.",
]

# 잡아야 하는 조항들. (열쇠, 문장)
TOXIC_CLAUSES = [
    ("ip_assignment", "제9조 금형·치공구 및 지식재산권은 매수인(갑)에게 귀속한다."),
    ("unlimited_damages",
     "제11조 매도인은 일체의 손해 전부를 배상하며, 그 책임에는 한도가 없다."),
    ("full_return",
     "제8조 매수인은 사유를 불문하고 인도받은 물품 전량을 매도인에게 반품할 수 있다."),
    ("evergreen",
     "제3조 만료 90일 전까지 서면 해지통지가 없으면 동일 조건으로 1년간 자동 연장된다."),
    ("payment_on_resale",
     "제5조 매수인은 물품을 제3자에게 재판매하여 그 대금을 회수한 후 30일 내에 지급한다."),
    ("termination_at_will",
     "제17조 매수인은 사유 없이 언제든지 30일 전 서면통지로 본 계약을 해지할 수 있다."),
    ("buyer_set_off",
     "제12조 매수인은 매도인에 대한 어떠한 채권으로도 대금지급의무와 상계할 수 있다."),
    ("open_warranty", "제13조 매도인은 기간의 제한 없이 하자를 보수하여야 한다."),
    ("cn_tech_transfer",
     "Article 9 The Seller shall provide the Buyer with complete technical drawings "
     "and bills of materials."),
    ("cn_trademark_buyer",
     "Article 10 The Buyer shall register the Seller's trademarks in the Buyer's own name."),
    ("eu_gdpr_indemnity",
     "Article 14 The Seller shall indemnify and hold the Buyer harmless against any "
     "fines imposed under the General Data Protection Regulation."),
    ("us_class_action_pl",
     "Article 15 The Seller shall indemnify and hold harmless the Buyer against all "
     "product liability claims, including class actions, without limitation."),
    ("ru_sanctions_warranty",
     "Article 18 The Seller warrants that the Goods are not subject to any sanctions "
     "and shall indemnify the Buyer for all consequences."),
    ("retro_price_deduction",
     "Article 6 The Buyer may deduct any agreed rebate or markdown allowance from any "
     "payment due, including retroactively."),
    ("chargeback_penalty",
     "Article 7 Late deliveries shall incur a chargeback of 5% of the order value, "
     "which the Buyer may deduct from any invoice."),
    ("audit_rights",
     "Article 11 The Buyer may audit the Seller's facilities and records at any time "
     "without prior notice."),
    ("exclusive_no_moq",
     "Article 3 The Seller shall supply the Products exclusively to the Buyer in the "
     "Territory and shall not sell to any other party therein."),
    ("foreign_forum", "제16조 전속적 합의관할은 뉴욕주 법원으로 한다."),
    ("us_jury_punitive", "Article 16 The parties hereby consent to trial by jury."),
    ("mfn_price",
     "Article 6 The Seller shall not offer the Products to any third party at a price "
     "lower than that offered to the Buyer."),
    ("payment_fx_approval",
     "Article 5 Payment shall be made subject to and upon receipt of approval from "
     "the Central Bank and the issuance of the import licence."),
    ("fx_risk_local",
     "Article 5 Payment shall be made in the local currency and the Seller shall bear "
     "any exchange rate fluctuation."),
    ("recall_cost",
     "Article 13 The Seller shall bear all costs of any recall, including retrieval, "
     "destruction and customer compensation, whether voluntary or mandated."),
    ("inspection_buyer_sole",
     "Article 10 The Buyer's inspection and determination of conformity shall be "
     "final, conclusive and binding on the Seller."),
    ("spec_change_no_price",
     "Article 4 The Buyer may change the specifications or packaging at any time, and "
     "such change shall not affect the price or the delivery date."),
    ("tooling_free",
     "Article 9 All tooling, moulds and jigs shall be provided by the Seller free of "
     "charge and shall become the property of the Buyer."),
]

# **정당하게 함께 짚히는 것들.** 오탐이 아닙니다.
#   면책 범위에 한도가 없으면 그건 무제한 책임이기도 합니다.
#   대금에서 빼는 것은 상계(set-off)이기도 합니다.
# 이걸 오탐으로 적으면 맞는 동작을 고치려 들게 됩니다.
ALSO = {
    "us_class_action_pl": {"unlimited_damages"},
    "retro_price_deduction": {"buyer_set_off"},
    "chargeback_penalty": {"buyer_set_off"},
    # 금형을 무상으로 주면서 **소유권까지** 넘기면 그건 권리 양도이기도 합니다.
    # tooling_free 의 fix 가 "ip_assignment 를 함께 보세요"라고 적어 둔 그대로입니다.
    "tooling_free": {"ip_assignment"},
    # 뉴욕주 법원 전속관할은 **상대국 법원**이면서 동시에 **미국 법원**입니다.
    # 미국 법원이면 배심재판과 징벌적 손해배상에 노출되므로 둘 다 짚는 것이 맞습니다.
    "foreign_forum": {"us_jury_punitive"},
}


def _toxic(text: str) -> set[str]:
    return {key for key in contract_clauses.find_in(text)
            if (contract_clauses.by_key(key) or {}).get("category") == "toxic"}


def _wrap(text: str, width: int = 58) -> str:
    """PDF 처럼 제 폭대로 줄을 꺾습니다."""
    out, line = [], ""
    for word in text.split():
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    out.append(line)
    return "\n".join(out)


def _hyphenate(text: str) -> str:
    """줄 끝에서 긴 영어 낱말을 하이픈으로 자릅니다."""
    def cut(match):
        word = match.group(0)
        half = len(word) // 2
        return f"{word[:half]}-\n{word[half:]}"
    return re.sub(r"\b[A-Za-z]{10,}\b", cut, text, count=3)


def _furniture(text: str) -> str:
    """쪽 번호를 문장 사이에 끼웁니다."""
    lines = text.split("\n")
    for pos in range(len(lines) - 1, 0, -4):
        lines.insert(pos, "- 7 -")
    return "\n".join(lines)


def test_통째로_멀쩡한_계약서는_독소_0건이다():
    """좋은 조항 25개를 한 문서로 묶어도 짚을 것이 없어야 합니다.

    조항끼리 섞여 생기는 오탐을 봅니다. 한 문장씩은 다 통과하는데 문서로
    묶으면 틀리는 일이 있습니다 — 규칙의 창(`[^.]{0,60}`)이 옆 조항까지
    넘어가기 때문입니다.
    """

    hits = _toxic(HEAD + "\n\n".join(SAFE_CLAUSES))
    assert not hits, f"멀쩡한 계약서에서 독소 {sorted(hits)} 를 짚었습니다"


@pytest.mark.parametrize("key,body", TOXIC_CLAUSES, ids=[row[0] for row in TOXIC_CLAUSES])
def test_멀쩡한_조항들_사이에_섞어도_그것만_짚는다(key, body):
    mixed = SAFE_CLAUSES + [body]
    random.Random(20261002).shuffle(mixed)
    hits = _toxic(HEAD + "\n\n".join(mixed))
    assert key in hits, f"{key} 를 못 찾았습니다"
    extra = hits - {key} - ALSO.get(key, set())
    assert not extra, f"{key} 와 함께 {sorted(extra)} 를 짚었습니다"


@pytest.mark.parametrize("name,mangle", [
    ("줄 꺾기", _wrap),
    ("줄 꺾기+하이픈", lambda t: _hyphenate(_wrap(t))),
    ("줄 꺾기+쪽 번호", lambda t: _furniture(_wrap(t))),
    ("셋 다", lambda t: _furniture(_hyphenate(_wrap(t)))),
])
def test_PDF_왜곡을_넣어도_찾는다(name, mangle):
    """PDF 에서 읽은 계약서는 줄이 꺾이고 낱말이 하이픈으로 갈리고 쪽 번호가 끼어듭니다.

    실제 계약서에서만 못 잡는 일이 있어, 흉내 내어 함께 봅니다.
    """

    missed = [key for key, body in TOXIC_CLAUSES
              if key not in contract_clauses.find_in(HEAD + mangle(body))]
    assert not missed, f"{name}: {missed} 를 놓쳤습니다"


def test_조항_순서를_바꿔도_결과가_같다():
    """같은 문서를 순서만 바꿔 넣으면 결과가 같아야 합니다.

    달라지면 규칙이 옆 조항에 기대고 있다는 뜻입니다.
    """

    base = SAFE_CLAUSES + [body for _, body in TOXIC_CLAUSES]
    want = contract_clauses.find_in(HEAD + "\n\n".join(base))
    rnd = random.Random(20261002)
    for turn in range(30):
        order = base[:]
        rnd.shuffle(order)
        got = contract_clauses.find_in(HEAD + "\n\n".join(order))
        assert got == want, (f"{turn}회차에서 달라졌습니다: "
                             f"더 {sorted(got - want)} 덜 {sorted(want - got)}")


def test_긴_문서에서도_빠르다():
    """되추적이 터지지 않는지. 긴 계약서는 쉽게 10만 자가 넘습니다.

    규칙에 `.{0,240}` 처럼 넓은 창이 있어, 겹치면 느려질 수 있습니다.
    """

    base = SAFE_CLAUSES + [body for _, body in TOXIC_CLAUSES]
    big = HEAD + "\n\n".join(base * 30)
    start = time.monotonic()
    contract_clauses.find_in(big)
    took = time.monotonic() - start
    assert took < 5.0, f"{len(big):,}자에 {took:.1f}초 걸렸습니다"
