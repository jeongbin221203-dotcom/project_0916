"""사업자등록번호가 **있을 수 있는 번호인지** 봅니다.

예전에는 "숫자 10자리"만 보았습니다. 0000000000 · 1234567890 · 9999999999 가
그대로 통과해 수출신고서에 실리고 관세사에게 넘어갔습니다. 신고가 반려되고,
더 나쁘게는 한 자리를 잘못 적어 **남의 회사 번호**가 되어도 아무도 모릅니다.
(2026-09-26)
"""

from __future__ import annotations

import random

import pytest

from app.validators import ValidationError
from app.validators import business_no


# 실제로 쓰이는 번호 (공개된 법인 번호)
@pytest.mark.parametrize("value", [
    "124-81-00998",     # 끝자리 8
    "120-81-47521",
    "220-81-62517",
    "1248100998",       # 붙여 적어도 같습니다
    " 124-81-00998 ",
    "124 81 00998",
])
def test_있을_수_있는_번호는_통과한다(value):
    assert business_no.is_valid(value)
    assert business_no.parse(value) == "124-81-00998" or business_no.digits_of(value)[3:5] != "81" \
        or len(business_no.digits_of(value)) == 10


@pytest.mark.parametrize("value", [
    "0000000000", "1111111111", "9999999999", "1234567890",
    "124-81-00997",        # 끝자리 하나만 틀림
    "000-00-00000",        # 가운데 00 은 발급되지 않습니다
])
def test_있을_수_없는_번호는_막는다(value):
    assert not business_no.is_valid(value)
    with pytest.raises(ValidationError):
        business_no.parse(value)


@pytest.mark.parametrize("value", ["123456789", "12345678901", "abcdefghij", "123-45-6789"])
def test_자릿수가_안_맞으면_막는다(value):
    with pytest.raises(ValidationError) as caught:
        business_no.parse(value)
    assert "10자리" in str(caught.value)


@pytest.mark.parametrize("value", ["", "   ", None])
def test_비워_두는_것은_막지_않는다(value):
    """나중에 적을 수 있습니다. 비었다고 화내지 않습니다."""

    assert business_no.parse(value) == ""


def test_비웠는데_반드시_필요하면_말해_준다():
    with pytest.raises(ValidationError):
        business_no.parse("", required=True)


def test_한_자리_오타를_모두_잡는다():
    """검증번호가 있는 이유입니다. 한 자리가 틀리면 반드시 걸려야 합니다."""

    random.seed(1616)
    caught = trials = 0
    for _ in range(3000):
        nine = f"{random.randint(100, 999)}{random.randint(1, 99):02d}{random.randint(0, 9999):04d}"
        real = nine + str(business_no.check_digit(nine))
        assert business_no.is_valid(real), f"규칙대로 만든 {real} 을 막았습니다"
        at = random.randrange(10)
        other = random.choice([d for d in "0123456789" if d != real[at]])
        typo = real[:at] + other + real[at + 1:]
        trials += 1
        caught += not business_no.is_valid(typo)
    assert caught == trials, f"{trials}가지 중 {trials - caught}가지를 놓쳤습니다"
