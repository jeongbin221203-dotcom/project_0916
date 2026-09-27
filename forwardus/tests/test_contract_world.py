"""전 세계 단위로 더한 독소조항 — **반대 방향부터** 잽니다.

왜 이 파일이 따로 있나
  조항을 더할 때 제가 규칙을 쓰고 제가 그 규칙에 맞는 문장을 지어 시험했습니다.
  순환 논증입니다. 사용자가 짚어 주어 우리에게 **유리한** 문장으로 다시 재 보니
  여덟 가운데 넷이 오탐이었습니다. (2026-09-27)

  잘못 잡는 것이 안 잡는 것보다 나쁩니다. 오탐은 쓰는 사람에게 멀쩡한 조항을
  지우라고 하게 만듭니다. 그래서 SAFE 를 먼저 둡니다.

  SAFE 에 넣는 문장은 "우리(매도인)에게 이미 유리하게 쓰인 문장"입니다.
  여기에 조항이 하나라도 걸리면 그 규칙이 낱말만 보고 편을 안 가린 것입니다.
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses

# 이 파일에서 새로 더한 조항들. 다른 조항이 함께 걸리는 것은 여기서 따지지 않습니다.
WORLD = {
    "agency_protection",
    "agency_law_eu",
    "cisg_silent",
    "china_domestic_arb",
    "ip_assignment",
    "buyer_set_off",
    "us_jury_punitive",
}

# (걸려야 하는 key, 계약서에 실제로 적혀 있을 문장)
CATCH = [
    ("agency_protection", "The Distributor is appointed as the exclusive agent for the territory of the UAE."),
    ("agency_protection", "Seller appoints Buyer as its sole representative in Brazil."),
    ("agency_protection", "본 계약에 따라 을은 사우디아라비아 지역의 독점 대리점으로 지정된다."),
    ("agency_law_eu", "The Agent shall not be entitled to any goodwill indemnity or compensation upon termination."),
    ("agency_law_eu", "The Agent hereby waives any claim for goodwill indemnity."),
    ("agency_law_eu", "계약 종료 시 대리인은 어떠한 보상금도 청구할 수 없다."),
    ("cisg_silent", "The United Nations Convention on Contracts for the International Sale of Goods shall not apply."),
    ("china_domestic_arb", "Disputes shall be submitted to the Shanghai Arbitration Commission for arbitration."),
    ("china_domestic_arb", "Arbitration shall take place at the Shenzhen Court of International Arbitration."),
    ("china_domestic_arb", "분쟁은 중국국제경제무역중재위원회(CIETAC) 베이징 본원의 전속 중재에 따른다."),
    ("ip_assignment", "All intellectual property rights in the Products shall vest in the Buyer."),
    # 금형·치공구라는 낱말 없이 낱말 사이가 먼 문장. 이 문장이 없으면 "IP 규칙의
    # 간격"을 되돌려도 금형 규칙이 덮어 주어 시험이 안 울립니다. (2026-09-27)
    ("ip_assignment", "All intellectual property rights in any designs, know-how or "
                      "improvements arising from this Contract shall vest exclusively in the Buyer."),
    ("ip_assignment", "The tooling and moulds shall be the property of Buyer upon payment."),
    ("ip_assignment", "개발 결과물에 관한 지식재산권은 갑에게 귀속한다."),
    ("buyer_set_off", "Buyer may set off any amounts owed against any claim whatsoever."),
    ("buyer_set_off", "매수인은 대금에서 손해액을 상계할 수 있다."),
    ("us_jury_punitive", "The courts of New York shall have jurisdiction over any dispute."),
    ("us_jury_punitive", "Seller hereby consents to the exclusive jurisdiction of the United States District Court."),
    ("us_jury_punitive", "본 계약의 분쟁은 미국 법원의 전속 관할로 한다."),
    ("us_jury_punitive", "뉴욕주 법원을 관할법원으로 한다."),
]

# 우리에게 유리하게 쓰인 문장 — 여기서는 **아무것도** 걸리면 안 됩니다.
SAFE = [
    "금형 및 치공구의 소유권은 매도인(을)에게 귀속한다.",
    "The tooling and moulds shall remain the sole property of the Seller.",
    "지식재산권은 매도인에게 유보되며 매수인에게 이전되지 아니한다.",
    "지식재산권은 각 당사자가 본래 보유한 범위에서 그대로 유지된다.",
    "매수인은 어떠한 경우에도 대금에서 상계하거나 공제할 수 없다.",
    "The Buyer shall have no right of set-off, deduction or counterclaim.",
    "본 계약은 미국 법원의 관할에 속하지 아니한다.",
    # 영어는 부정어가 앞에 옵니다. 파이썬 re 는 가변길이 뒤보기를 못 쓰므로
    # trial by jury·punitive damages 라는 낱말 자체를 규칙에서 뺐습니다.
    "Each Party irrevocably waives any right to trial by jury.",
    "Neither Party shall be liable for punitive, exemplary or consequential damages.",
    "대리인은 계약 종료 시 준거법이 정하는 보상금을 청구할 권리를 가진다.",
    "분쟁은 대한상사중재원의 중재로 해결한다.",
    "분쟁은 싱가포르국제중재센터(SIAC)의 중재로 최종 해결한다.",
    "Disputes shall be finally settled by arbitration under the ICC Rules in Singapore.",
    "The Seller may appoint additional distributors in the territory at its discretion.",
    "물품의 소유권은 대금 완납 시까지 매도인에게 남는다.",
    "대금은 선적 후 30일 내에 전신환으로 지급한다.",
]


@pytest.mark.parametrize("sentence", SAFE)
def test_우리에게_유리한_문장은_걸리지_않는다(sentence):
    hit = set(contract_clauses.find_in(sentence)) & WORLD
    assert not hit, f"오탐 {sorted(hit)} · {sentence}"


@pytest.mark.parametrize("key,sentence", CATCH)
def test_독소_문장은_집어낸다(key, sentence):
    assert key in contract_clauses.find_in(sentence), f"놓침 {key} · {sentence}"


def test_새_조항이_모두_목록에_있다():
    keys = {row["key"] for row in contract_clauses.CLAUSES}
    assert WORLD <= keys


def test_갈래를_뒤집지_않았다():
    """must 는 **안 보이면** 경고, toxic 은 **보이면** 경고입니다.

    처음에 "없으면 위험"인 것을 toxic 에 넣어, 제대로 쓴 계약서가 독소조항
    있음으로 찍혔습니다. 정반대였습니다.
    """

    by_key = {row["key"]: row for row in contract_clauses.CLAUSES}
    assert by_key["cisg_silent"]["category"] == "gain"
    assert by_key["agency_protection"]["category"] == "gain"
    for key in ("agency_law_eu", "china_domestic_arb", "ip_assignment",
                "buyer_set_off", "us_jury_punitive"):
        assert by_key[key]["category"] == "toxic", key


def test_독소조항_문안은_찾는_문구를_담는다():
    """toxic 의 text_en 은 **계약서에 적혀 있을 문구**여야 합니다.

    여기에 "넣을 문구"(고치는 방법)를 적으면, 그 문안을 계약서에 넣어 보는
    검사가 조항을 못 잡습니다. 고치는 방법은 fix 에 적습니다.
    """

    for row in contract_clauses.CLAUSES:
        if row["key"] not in WORLD or row["category"] != "toxic":
            continue
        assert row["key"] in contract_clauses.find_in(row["text_en"]), row["key"]
