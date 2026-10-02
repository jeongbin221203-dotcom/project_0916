"""실물 PDF 6개(오퍼 5 · 보세가공 계약서 1)에서 드러난 빈틈.

왜 이 파일이 있나 (2026-10-02)
  실제 서류를 창구(/contract/review)에 올려 보니, 손으로 만든 예문에서는 안
  보이던 것이 넷 나왔습니다.

      unlimited_damages  "for all losses … without **monetary limit**"   (미탐)
      goods              오퍼는 조항이 아니라 **표**로 적습니다           (없다고 함)
      packing            "PACKING SPECIFICATIONS" · "EXPORT STANDARD PACKED"
      amendment          "Changes require mutual written agreement."

  필수조항을 '없다'고 하면 이미 적은 사람에게 '넣으세요'라고 합니다. 그래서
  미탐과 똑같이 다룹니다.

  아래 글은 PDF에서 **실제로 읽힌 글자**를 옮긴 것입니다. 오퍼 시트는 그림
  PDF라 OCR 이 읽었고, "Unit" 이 "보메" 로, "$" 가 "§" 로 바뀐 채 그대로 둡니다.
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses

TOXIC = {row["key"] for row in contract_clauses.CLAUSES if row["category"] == "toxic"}

BONDED_ART9 = (
    "BONDED PROCESSING TRADE CONTRACT\n"
    "Article 9 Subject to Articles 11 and 13, Party B shall indemnify Party A for all "
    "losses, costs, claims, and liabilities arising out of or related to the yarn, "
    "processing, storage, transport, or finished fabric, including losses caused in "
    "whole or in part by Party A's own instructions or negligence, without monetary "
    "limit. Party A shall have no corresponding indemnity obligation to Party B.\n"
    "Article 10 This contract and the specifications signed by both parties constitute "
    "the entire agreement between the parties concerning this transaction. No "
    "modification shall be effective unless made in writing and signed by the "
    "authorized representatives of both parties.\n")

OFFER_TABLE = (
    "FIRM OFFER\nGOODS & PACKING DETAILS\n"
    "Item Description Quantity Unit price (USD) Amount (USD)\n"
    "UMB-01 3-fold manual umbrella 21-inch ribs, polyester canopy, 1,200 PCS 4.50 5,400.00\n"
    "PACKING SPECIFICATIONS\n"
    "Model Cartons PCS / carton L x W x H (cm) Net / carton Gross / carton\n"
    "Remarks 1. Fixed order: 2,000 PCS. 3. No custom logo. "
    "Changes require mutual written agreement.\n")

# OCR 이 읽은 그대로입니다 — 오타를 고치지 않습니다.
OFFER_SHEET_OCR = (
    "Offer Sheet\nWE ARE PLEASED TO OFFER YOU AS BELOW.\n"
    "Item Name : Nylon 95% / spandex 5% fabric\nH.§ code : To be confirmed\n"
    "Description ㅁ .0# Quantity 보메 | Price | Amount\n"
    "Nylon 95% spandex 5% SMT-p0-0927 20,000 ¥Ds | §2.800( US $56,000.00\n"
    "PACKING: EXPORT STANDARD PACKED\nPAYMENT : BY T/T BEFORE SHIPMENT\n")

# 날짜만 바꾸는 이야기는 계약 변경 조항이 아닙니다.
OFFER_DATES_ONLY = (
    "FIRM OFFER\nShipment by April 19, 2027. If payment is late, revised dates "
    "require mutual written agreement.\n")


def test_금액_한도_없는_일방_면책을_짚는다():
    assert "unlimited_damages" in contract_clauses.find_in(BONDED_ART9) & TOXIC


@pytest.mark.parametrize("key", ["goods", "packing", "amendment"])
def test_표로_적은_오퍼의_필수조항을_있다고_본다(key):
    assert key in contract_clauses.find_in(OFFER_TABLE)


@pytest.mark.parametrize("key", ["goods", "packing"])
def test_OCR_오타가_섞여도_찾는다(key):
    assert key in contract_clauses.find_in(OFFER_SHEET_OCR)


def test_날짜만_바꾸는_문구는_계약_변경이_아니다():
    assert "amendment" not in contract_clauses.find_in(OFFER_DATES_ONLY)


@pytest.mark.parametrize("doc", [OFFER_TABLE, OFFER_SHEET_OCR, OFFER_DATES_ONLY],
                         ids=["오퍼 표", "오퍼 시트 OCR", "날짜만"])
def test_오퍼에서_독소가_뜨지_않는다(doc):
    assert not contract_clauses.find_in(doc) & TOXIC


SAFE = [
    ("goods", "The description, quantity and price of the goods shall be agreed later."),
    ("packing", "The Seller shall provide a packing list in three copies."),
    ("amendment", "Changes to the shipment dates require written consent."),
    ("amendment", "Minor changes do not require written agreement."),
    ("unlimited_damages",
     "The Buyer shall indemnify the Seller for all losses without monetary limit."),
    ("unlimited_damages", "The Buyer may place orders without monetary limit during the term."),
]


@pytest.mark.parametrize("key,line", SAFE, ids=[f"{k}:{s[:24]}" for k, s in SAFE])
def test_새_규칙이_넘치지_않는다(key, line):
    assert key not in contract_clauses.find_in("SALES CONTRACT\n" + line)
