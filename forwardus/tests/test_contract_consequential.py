"""간접손해·영업손실까지 우리가 배상한다는 문장 (unlimited_damages 보강).

왜 이 파일이 있나 (2026-10-03)
  "Seller shall be liable for all indirect, consequential and special damages
  including loss of profit" 를 못 잡았습니다. 규칙이 without limitation ·
  any and all · unlimited 같은 말만 봤기 때문입니다. 간접손해를 떠안는 것이
  상한이 없는 배상의 가장 흔한 꼴인데도 그렇습니다.

  그런데 간접손해라는 말은 **좋은 조항**에 훨씬 더 자주 나옵니다.
      "Neither party shall be liable for any indirect or consequential damages"
  이것은 우리가 넣으라고 권하는 책임 한도 조항입니다. 그래서 **걸리면 안 되는
  문장을 먼저** 적고, 그다음에 잡아야 할 문장을 적습니다.
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses

# ── 걸리면 안 되는 문장 ─────────────────────────────────────────────────────
SAFE = [
    # 간접손해를 **빼는** 꼴 — 우리가 권하는 책임 한도 조항입니다.
    "Neither party shall be liable for any indirect, consequential or special damages, "
    "including loss of profit.",
    "In no event shall the Seller be liable for consequential damages or loss of profit.",
    "The Seller shall not be liable for any loss of profit, loss of business or indirect loss.",
    "The Seller shall be liable for direct damages only, excluding indirect damages and "
    "loss of profit.",
    "The Seller shall be liable for proven direct losses, but not for consequential losses.",
    "The Seller shall be liable to the Buyer for all damages other than indirect or "
    "consequential damages.",
    "The Seller's liability shall exclude indirect and consequential damages.",
    # 한도가 붙은 꼴 — 무제한이 아닙니다.
    "The Seller shall be liable for indirect damages up to an amount not exceeding the "
    "invoice value of the goods concerned.",
    "The Seller shall compensate the Buyer for loss of profit, limited to 10% of the "
    "contract price.",
    # 방향이 거꾸로 — 바이어가 우리 손해를 물어 줍니다.
    "The Buyer shall be liable for all indirect and consequential damages suffered by the Seller.",
    "The Buyer shall indemnify the Seller against all losses, including indirect losses "
    "and loss of profit.",
    "The Seller shall be entitled to recover its loss of profit from the Buyer.",
    # 뜻풀이
    '"Consequential Loss" means loss of profit, loss of revenue and loss of goodwill.',
    # 국문
    "어느 당사자도 간접손해, 특별손해 및 일실이익에 대하여 책임을 지지 아니한다.",
    "매도인은 간접손해 및 영업손실에 대하여 책임을 지지 않는다.",
    "매도인은 직접손해만 배상하며, 간접손해와 일실이익은 배상 범위에서 제외한다.",
    "매도인은 간접손해를 포함한 손해를 배상하되, 그 한도는 계약금액으로 한다.",
    "매수인은 매도인이 입은 간접손해와 영업손실을 배상한다.",
]


@pytest.mark.parametrize("line", SAFE, ids=[s[:28] for s in SAFE])
def test_간접손해를_빼거나_한도를_둔_문장은_짚지_않는다(line):
    assert "unlimited_damages" not in contract_clauses.find_in("SALES CONTRACT\n" + line)


# ── 잡아야 할 문장 ──────────────────────────────────────────────────────────
TOXIC = [
    "The Seller shall be liable for all indirect, consequential and special damages, "
    "including loss of profit, suffered by the Buyer.",
    "The Seller shall indemnify the Buyer for all direct and indirect losses, including "
    "loss of profits and loss of production.",
    "Seller shall compensate Buyer for any consequential damages arising from late delivery.",
    "The Supplier will be responsible for lost profits and loss of business of the Buyer "
    "caused by defective goods.",
    "매도인은 매수인의 간접손해와 일실이익까지 배상하여야 한다.",
    "공급자는 특별손해 및 영업손실을 포함한 모든 손해를 배상한다.",
]


@pytest.mark.parametrize("line", TOXIC, ids=[s[:28] for s in TOXIC])
def test_간접손해까지_우리가_떠안는_문장을_짚는다(line):
    assert "unlimited_damages" in contract_clauses.find_in("SALES CONTRACT\n" + line)


def test_Party_A_B_계약서에서도_방향을_본다():
    # 한국에 있는 Party A 가 우리(매도인)입니다. test_contract_our_side 와 같은 머리.
    head = ("CONTRACT between the following parties concerned: Hana Co., Ltd., hereinafter "
            "referred to as Party A, having its head office at Seoul, Korea, and Acme Inc., "
            "hereinafter referred to as Party B, having its head office at Tokyo, Japan. "
            "Whereas the parties agree as follows.\n")
    ours = head + "Party A shall be liable for all consequential damages and loss of profit of Party B."
    theirs = head + "Party B shall be liable for all consequential damages and loss of profit of Party A."
    assert "unlimited_damages" in contract_clauses.find_in(ours)
    assert "unlimited_damages" not in contract_clauses.find_in(theirs)


def test_책임_한도_조항은_그대로_있다고_본다():
    doc = ("SALES CONTRACT\nNeither party shall be liable for any indirect or consequential "
           "damages. The Seller's total liability shall not exceed the invoice value.")
    assert contract_clauses.analyze(doc)["clauses"].get("liability_cap", {}).get("status") == "present"
