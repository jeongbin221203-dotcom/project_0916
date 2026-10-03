"""조항마다 **제 예문**을 찾는가 (2026-10-03).

왜 이 파일이 있나
  조항 설명에는 예문(text_en)이 붙어 있습니다 — 독소는 '지울 문구', 필수·이익은
  '넣을 문구'. 사용자는 이 예문을 보고 자기 계약서를 고칩니다. 그런데 EU EPR
  조항이 **제 예문을 못 찾고** 있었습니다(규칙의 거리 100자를 예문이 넘었습니다).
  규칙을 고치다 예문과 어긋나면 여기서 알게 합니다.
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses

# 일부러 예문을 '찾지 않는' 조항과 그 까닭.
NOT_SELF = {
    # 예문이 **넣어야 할** 보호 문구입니다 — 이것이 없을 때가 독소입니다.
    "reexport_control",
}
# 가공계약에서만 보는 조항 — 가공계약 머리를 붙여서 봅니다.
PROCESSING_HEAD = ("BONDED PROCESSING TRADE CONTRACT\nThe Buyer shall supply the yarn to the "
                   "Seller for processing into finished fabric.\n")

ROWS = [row for row in contract_clauses.CLAUSES if row["key"] not in NOT_SELF]


def _example(row: dict) -> str:
    text = row["text_en"]
    return text.split(")", 1)[1] if text.startswith("(") else text


@pytest.mark.parametrize("row", ROWS, ids=[row["key"] for row in ROWS])
def test_조항은_제_예문을_찾는다(row):
    head = PROCESSING_HEAD if row["context"] else "SALES CONTRACT\n"
    judged = contract_clauses.analyze(head + _example(row))["clauses"].get(row["key"])
    assert judged and judged["status"] == "present", (row["key"], judged)


def test_예외_목록은_실제로_예외다():
    """예외로 둔 조항이 어느새 제 예문을 찾게 되면 목록에서 빼야 합니다."""

    for key in NOT_SELF:
        row = contract_clauses.by_key(key)
        assert key not in contract_clauses.find_in("SALES CONTRACT\n" + _example(row))
