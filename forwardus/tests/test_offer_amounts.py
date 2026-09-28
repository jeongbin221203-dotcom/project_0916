"""오퍼시트에 적힌 **돈·수량·중량**을 읽기. (2026-09-28)

왜 있나
  값이 조용히 망가지는 자리였습니다. 항구가 비면 사람이 눈치채지만, 단가가
  2.40 대신 240 으로 들어가면 그대로 송장이 나갑니다.

    '2,40'      (유럽 단가 = 2.40)  ->  240       백 배 큼
    '8.616,00'  (유럽식 = 8616)     ->  8.616     천 배 작음

  유럽·남미 오퍼시트는 쉼표를 소수점으로 씁니다. 단가는 보통 2,40 · 6,50 처럼
  작은 수라 이 모양이 **가장 자주** 나옵니다.

어떻게 가리나
  **미국식 천 단위 쉼표는 반드시 세 자리씩 묶습니다.** 그러니 쉼표 뒤
  자릿수만 보면 뜻이 정해집니다. 마침표와 쉼표가 둘 다 있으면 뒤에 오는 쪽이
  소수점입니다 — 이것은 어느 나라에서나 같습니다.
"""

from __future__ import annotations

import pytest

from app.services.intake_service import _as_number


# (적힌 글, 읽어야 할 값)
READS = [
    # 미국식
    ("8616.00", "8616.00"), ("8,616.00", "8,616.00"), ("6.50", "6.50"),
    ("1,234,567.89", "1,234,567.89"),
    # 쉼표 뒤가 세 자리 -> 천 단위 (지금까지대로)
    ("8,616", "8,616"), ("1,234,567", "1,234,567"),
    # 쉼표 뒤가 한두 자리 -> 소수점일 수밖에 없습니다
    ("2,40", "2.40"), ("6,50", "6.50"), ("1,8", "1.8"),
    # 마침표와 쉼표가 둘 다 -> 뒤에 오는 쪽이 소수점
    ("8.616,00", "8616.00"), ("1.234.567,89", "1234567.89"),
    ("8 616,00", "8616.00"),
    # 통화가 붙어 옵니다
    ("USD 8,616.00", "8,616.00"), ("US$6,50", "6.50"), ("$8,616.00", "8,616.00"),
    ("3,10 USD", "3.10"),
    # 단위가 붙어 옵니다
    ("720 PCS", "720"), ("1,200 pcs", "1,200"), ("50 CTN", "50"),
    ("500 KG", "500"), ("500.00 KGS", "500.00"),
]

# 뜻을 가릴 수 없는 것. **그대로 두어 빈 칸이 되게** 합니다.
LEAVE_ALONE = [
    "0.5 MT",      # 톤은 1000을 곱해야 합니다. 그건 짐작입니다.
    "TBD", "-", "무료", "약 8,616",
]


@pytest.mark.parametrize("written,want", READS)
def test_적힌_대로_읽는다(written, want):
    assert _as_number(written) == want


@pytest.mark.parametrize("written", LEAVE_ALONE)
def test_뜻을_못_가리면_건드리지_않는다(written):
    """바꿔 놓으면 parse_number 가 엉뚱한 숫자로 읽습니다.

    그대로 두면 읽기에 실패해 빈 칸이 되고, 사람이 채웁니다.
    빈 칸은 사람이 채우지만 **틀린 값은 아무도 못 알아챕니다.**
    """

    assert _as_number(written) == written


def test_유럽식_단가가_백배로_커지지_않는다(app):
    """실제로 칸에 들어가는 값까지 봅니다. (_item 을 거쳐서)"""

    from app.services import document_extract_service as extract

    line = extract._item({"product_description": "면 타월",
                          "package_count": "1.800 PCS",
                          "unit_price": "2,40",
                          "amount": "4.320,00"}, [], 1)
    assert float(line["unit_price"]) == pytest.approx(2.40)
    assert float(line["amount"]) == pytest.approx(4320.00)
    assert float(line["quantity"]) == pytest.approx(1800)
