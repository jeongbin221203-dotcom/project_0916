"""⑪ 무역을 모르는 이용자가 **아는 말로** HS부호를 찾을 수 있는가.

일상어 226개로 확인했더니 48개가 아무것도 못 찾았고, 말버릇을 얹으면
("칫솔 hs코드", "양파는 몇 번이에요") 132가지가 못 찾았습니다.
찾기는 모든 낱말이 맞아야 해서 'hs코드'가 붙으면 통째로 실패했습니다.
무역을 모르는 분일수록 이렇게 적습니다. (2026-09-26)
"""

from __future__ import annotations

import pytest

from app.collectors import hsk_catalog


EVERYDAY_WORDS = [
    "쌀", "밀", "콩", "무", "배", "감", "귤", "소고기", "닭고기", "계란", "게", "참치",
    "빵", "생수", "마요네즈", "라면", "커피", "와인", "설탕",
    "치약", "칫솔", "바디워시", "물티슈", "생리대", "섬유유연제", "표백제", "방향제",
    "옷", "원피스", "스웨터", "목도리", "슬리퍼", "카펫", "양말", "신발", "가방",
    "선풍기", "전자레인지", "믹서기", "가습기", "제습기", "스피커", "옷장", "책장",
    "공책", "풀", "비닐봉지", "영양제", "체온계", "철", "못", "철사",
    "오토바이", "휠체어", "공", "약",
]


@pytest.mark.parametrize("word", EVERYDAY_WORDS)
def test_일상어로_HS부호를_찾는다(app, word):
    assert hsk_catalog.search(word), f"'{word}' 로 아무것도 못 찾습니다"


SHAPES = ["{0} hs코드", "{0} HS CODE", "{0} 수출하려는데 코드", "{0} 알려줘",
          "{0}는 몇 번이에요", "{0}은 몇번인가요", "{0} 품목번호"]


@pytest.mark.parametrize("word", ["칫솔", "양파", "치약", "라면", "게", "쌀"])
@pytest.mark.parametrize("shape", SHAPES)
def test_물어보듯_적어도_찾는다(app, word, shape):
    assert hsk_catalog.search(shape.format(word)), f"'{shape.format(word)}' 로 못 찾습니다"


def test_사전이_가리키는_두_낱말짜리_말도_찾는다(app):
    """'계란' → '새의 알'. 붙여서 '새의알' 로 찾으면 품목표와 안 맞습니다."""

    assert hsk_catalog.search("계란")
    assert hsk_catalog.search("옷장")          # → '침실용 가구'


def test_조사를_떼는_것은_한_건도_못_찾았을_때만이다(app):
    """먼저 떼면 '고구마'의 '마'처럼 진짜 이름의 끝글자를 자릅니다."""

    assert hsk_catalog.search("고구마")
    assert hsk_catalog._strip_particle("고구마") == "고구마"
    assert hsk_catalog._strip_particle("양파는") == "양파"
    assert hsk_catalog._strip_particle("게는") == "게"       # 사전에 있는 말이라 한 글자도 됩니다
    assert hsk_catalog._strip_particle("가위") == "가위"     # 사전에 없으니 '가' 로 자르지 않습니다


def test_사전이_가리키는_말은_모두_품목표에서_찾아진다(app):
    """적어 두고도 한 건도 안 나오면 그 낱말은 사실상 꺼져 있는 것입니다."""

    dead = []
    for word, targets in hsk_catalog.EVERYDAY.items():
        if not hsk_catalog.search(word):
            dead.append(f"{word} → {targets}")
    assert not dead, f"사전에 적어 두었는데 못 찾는 말: {dead}"
