"""우리는 수출자, 곧 매도인입니다 — Party A / Party B 계약서에서 우리 쪽 정하기.

왜 이 파일이 있나 (2026-10-02)
  규칙은 방향을 Seller·Buyer 로 봅니다. 가공무역 계약서는 "Party A / Party B"
  로만 불러서, 우리에게 유리한 조항("상대가 우리를 무제한 배상")도 독소로
  짚을 수 있었습니다. 당사자 정의에서 **한국에 있는 쪽이 하나뿐일 때만** 그쪽을
  매도인으로 읽습니다. 못 정하면 정하지 않습니다.
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses
from app.services import contract_clause_service

# 실물 보세가공 계약서 머리 (PDF 에서 읽힌 그대로 — 주소가 정의 뒤)
BONDED = (
    "BONDED PROCESSING TRADE CONTRACT\nThis contract is made and agreed on this "
    "Twenty-seventh day of September, 2026, by and\nbetween the following parties "
    "concerned:\nHarborline Fiber Trading Inc., hereinafter referred to as Party A,\n"
    "having its head office at\nSan Francisco, U.S.A., and\nHaneul Weaving Co., Ltd., "
    "hereinafter referred to as Party B,\nhaving its head office at\nSeoul, Republic of "
    "Korea.\nWhereas it is the mutual intent and desire of the parties to establish a "
    "reliable business relationship.\n")

A_KOREAN = (
    "CONTRACT between the following parties concerned: Hana Co., Ltd., hereinafter "
    "referred to as Party A, having its head office at Seoul, Korea, and Acme Inc., "
    "hereinafter referred to as Party B, having its head office at Tokyo, Japan. "
    "Whereas the parties agree as follows.\n")

BEFORE = (
    'AGREEMENT made between Acme Inc. of Tokyo, Japan (hereinafter "Party A") and '
    'Hana Co., Ltd. of Busan, Republic of Korea (hereinafter "Party B"). Whereas the '
    "parties agree as follows.\n")

UNDECIDED = [
    ("둘 다 한국",
     "between Hana Co., Ltd., hereinafter referred to as Party A, having its head office "
     "at Seoul, Korea, and Dul Co., Ltd., hereinafter referred to as Party B, having its "
     "head office at Busan, Korea. Whereas the parties agree."),
    ("둘 다 외국 — 본문에 Korea",
     "between Acme Inc., hereinafter referred to as Party A, having its head office at "
     "Tokyo, Japan, and Beta Ltd., hereinafter referred to as Party B, having its head "
     "office at Paris, France. Whereas goods made in Korea are sold."),
    ("Seller/Buyer 계약서", "SALES CONTRACT The Seller shall indemnify the Buyer."),
]

UNLIMITED = "for all losses, without monetary limit.\n"


@pytest.mark.parametrize("doc,label,name", [
    (BONDED, "Party B", "Haneul Weaving Co., Ltd."),
    (A_KOREAN, "Party A", "Hana Co., Ltd."),
    (BEFORE, "Party B", "Hana Co., Ltd."),
], ids=["실물 — 주소 뒤", "A 가 한국", "주소 앞"])
def test_한국에_있는_쪽을_우리로_본다(doc, label, name):
    side = contract_clauses.our_side(doc)
    assert side and side["label"] == label and side["name"] == name


@pytest.mark.parametrize("label,doc", UNDECIDED, ids=[r[0] for r in UNDECIDED])
def test_못_정하면_정하지_않는다(label, doc):
    assert contract_clauses.our_side(doc) is None


def test_실물_제9조_우리가_무제한_배상하면_독소():
    doc = BONDED + "Article 9 Party B shall indemnify Party A " + UNLIMITED
    assert "unlimited_damages" in contract_clauses.find_in(doc)


def test_상대가_우리를_무제한_배상하면_독소가_아니다():
    doc = BONDED + "Article 9 Party A shall indemnify Party B " + UNLIMITED
    assert "unlimited_damages" not in contract_clauses.find_in(doc)


def test_A가_한국이면_방향도_뒤집힌다():
    assert "unlimited_damages" in contract_clauses.find_in(
        A_KOREAN + "Article 9 Party A shall indemnify Party B " + UNLIMITED)
    assert "unlimited_damages" not in contract_clauses.find_in(
        A_KOREAN + "Article 9 Party B shall indemnify Party A " + UNLIMITED)


def test_판정_결과에_우리_쪽을_밝힌다():
    """방향이 뒤집히면 판정도 뒤집히므로, 누구를 우리로 읽었는지 보여 줍니다."""

    result = contract_clause_service.review(
        BONDED + "Article 9 Party B shall indemnify Party A " + UNLIMITED, "CIF", "US")
    assert result["our_side"]["label"] == "Party B"
    assert "Haneul Weaving Co., Ltd." in contract_clause_service.as_text(result)
