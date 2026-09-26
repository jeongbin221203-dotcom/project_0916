"""㉖ 수출 상위 품목으로 HS부호를 정확히 찾는가.

우리나라 수출 상위 품목 196개로 재 보니, 이름 맞히기만으로는
**맨 위가 바로 맞는 것이 47%**였고 31개는 한 건도 못 찾았습니다.
  '반도체' → 2807(황산) 이 먼저
  '노트북' → 4820(공책)
  '철강판' · '자동차부품' · '합성수지' → 한 건도 없음
그 부호로 신고하면 품목분류가 통째로 틀립니다.

품목표의 이름은 법령 문장이라 사람이 부르는 말과 다릅니다. 8542는
"전자집적회로"이지 "반도체"가 아니고, 8471은 "자동자료처리기계"이지
"컴퓨터"가 아닙니다. 그래서 **사람이 부르는 이름을 호(4자리)에 직접** 이었습니다.
호까지만 잇습니다 — 그 아래 세분은 규격·재질로 갈리므로 사람이 고릅니다.
(2026-09-26)
"""

from __future__ import annotations

import re

import pytest

from app.collectors import hsk_catalog


def _codes(rows):
    return [re.sub(r"[.\-]", "", str(row.get("code") or "")) for row in rows]


# 손으로 확인한 것만 몇 개 골라 못 박아 둡니다. 전체는 아래 전수 검사가 봅니다.
@pytest.mark.parametrize("word,head", [
    ("반도체", "854"), ("메모리반도체", "8542"), ("이차전지", "8507"),
    ("리튬이온배터리", "8507"), ("자동차", "8703"), ("자동차부품", "8708"),
    ("휴대폰", "8517"), ("컴퓨터", "8471"), ("노트북", "8471"),
    ("철강판", "72"), ("열연강판", "7208"), ("합성수지", "39"),
    ("타이어", "4011"), ("화장품", "3304"), ("라면", "1902"),
    ("선박", "89"), ("의약품", "300"), ("조선", None),
])
def test_수출_상위_품목은_맨_위가_맞는다(app, word, head):
    rows = hsk_catalog.search(word) or []
    if head is None:
        pytest.skip("표에 없는 말")
    assert rows, f"'{word}' 로 아무것도 못 찾습니다"
    assert _codes(rows)[0].startswith(head), \
        f"'{word}' 맨 위가 {_codes(rows)[:3]} (기대 {head}…)"


def test_표에_적은_호가_모두_품목표에_있다(app):
    """적어 두고도 없는 호면 그 낱말은 사실상 꺼져 있는 것입니다."""

    levels = hsk_catalog._catalog().get("levels") or {}
    dead = [(name, head) for name, heads in hsk_catalog.HEADINGS.items()
            for head in heads if head not in levels]
    assert not dead, f"품목표에 없는 호: {dead}"


def test_표에_적은_말은_모두_그_호를_낸다(app):
    """전수. 하나라도 어긋나면 그 품목은 잘못 신고됩니다."""

    wrong = []
    for name, heads in hsk_catalog.HEADINGS.items():
        rows = hsk_catalog.search(name) or []
        got = _codes(rows)
        if not got:
            wrong.append(f"{name}: 아무것도 없음")
        elif not any(got[0].startswith(head) for head in heads):
            wrong.append(f"{name}: 맨 위 {got[0]} (기대 {heads})")
    assert not wrong, f"{len(wrong)}개가 어긋납니다: {wrong[:10]}"


def test_호_안에서는_기타가_맨_위에_오지_않는다(app):
    """맨 위에 '기타'가 뜨면 그게 무엇인지 알 수가 없습니다."""

    rows = hsk_catalog.search("자동차부품") or []
    assert rows
    assert hsk_catalog._plain(rows[0]["name"]) not in hsk_catalog.GENERIC


def test_고른_부호가_어느_계통인지_함께_온다(app):
    """같은 이름이 여러 부호에 붙어 있습니다. 계통이 없으면 고를 수가 없습니다."""

    rows = hsk_catalog.search("기타") or []
    assert rows
    for row in rows[:5]:
        assert row.get("path"), f"{row['code']} 에 계통이 없습니다"
        assert len(row["path"]) >= 2
