"""기업 수출 상위 · 개인 수출 상위 품목표를 지킵니다.

왜 이 테스트가 있나
  같은 검색창에 회사 담당자와 개인 판매자가 같이 들어옵니다. 회사는
  "이차전지 양극재"라 적고, 개인은 "보조배터리"라 적습니다. 표를 손볼 때
  한쪽이 조용히 빠지면, 그 말을 쓰는 사람은 부호를 못 찾고 아무 부호나
  적어 신고합니다. (2026-09-27)

전체 정확도는 scripts/checks/m26_biz_personal.py 가 460개 × 말버릇 8가지로
잽니다. 여기서는 **빠지면 바로 아는 것**만 봅니다.
"""

import pytest

from app.collectors import hsk_catalog

# 표에 있어야 하는 대표 품목. 지워지거나 다른 호로 바뀌면 여기서 걸립니다.
BUSINESS_SAMPLE = {
    "이차전지 양극재": "8507",
    "황산니켈": "2833",
    "냉연코일": "7209",
    "MLCC": "8532",
    "굴삭기부품": "8431",
}

PERSONAL_SAMPLE = {
    "보조배터리": "8507",
    "반팔티": "6109",
    "즉석밥": "1904",
    "쿠션퍼프": "9616",
    "카드지갑": "4202",
}

# 무역을 모르는 분이 실제로 적는 말버릇. 하나라도 0건이면 안 됩니다.
HABITS = ("{}", "{} HS코드", "{} 품목번호", "{}는 몇번이에요", "{} 수출하려는데")


def test_both_tables_are_wired_into_the_lookup():
    """두 표가 실제 찾기 표(HEADINGS)에 들어가 있어야 합니다."""

    assert len(hsk_catalog.HEADINGS_BUSINESS) >= 200
    assert len(hsk_catalog.HEADINGS_PERSONAL) >= 200
    for table in (hsk_catalog.HEADINGS_BUSINESS, hsk_catalog.HEADINGS_PERSONAL):
        for word in table:
            assert word in hsk_catalog.HEADINGS, word


def test_hand_picked_headings_win_over_the_new_tables():
    """손으로 고른 HEADINGS 가 기업·개인 표보다 우선입니다.

    '장갑'은 HEADINGS 가 6116(편물)·4203(가죽) 둘을 봅니다. 개인 표가
    6116 하나로 덮어쓰면 가죽장갑을 내보내는 분이 못 찾습니다.
    """

    assert hsk_catalog.HEADINGS["장갑"] == ("6116", "4203")


def test_every_heading_in_the_new_tables_exists_in_the_catalog(app):
    """적어 둔 호가 품목표에 실제로 있는 호여야 합니다.

    없는 호를 적어 두면 그 말로 찾을 때 조용히 0건이 됩니다.
    """

    with app.app_context():
        catalog = hsk_catalog._catalog()
        assert catalog, "품목표가 없으면 이 테스트는 뜻이 없습니다"
        have = {code[:4] for code in catalog["codes"]}
        missing = sorted({
            head
            for table in (hsk_catalog.HEADINGS_BUSINESS, hsk_catalog.HEADINGS_PERSONAL)
            for heads in table.values()
            for head in heads
            if head not in have
        })
    assert missing == []


@pytest.mark.parametrize("name,heading", sorted(BUSINESS_SAMPLE.items()))
def test_business_words_find_their_heading(app, name, heading):
    _assert_every_habit_finds(app, name, heading)


@pytest.mark.parametrize("name,heading", sorted(PERSONAL_SAMPLE.items()))
def test_personal_words_find_their_heading(app, name, heading):
    _assert_every_habit_finds(app, name, heading)


def _assert_every_habit_finds(app, name: str, heading: str) -> None:
    """이름 그대로도, 말버릇을 얹어도 같은 호가 맨 위에 와야 합니다."""

    with app.app_context():
        for habit in HABITS:
            query = habit.format(name)
            rows = hsk_catalog.search(query) or []
            codes = [str(row.get("code") or "") for row in rows]
            assert codes, f"{query!r} 이 0건입니다"
            assert codes[0].startswith(heading), f"{query!r} → {codes[:3]}"


def test_a_narrowing_word_is_not_thrown_away_by_the_table(app):
    """뒤에 붙은 말이 재질을 좁혀 줄 때 그 좁힘을 버리지 않습니다.

    '장갑'은 표에서 6116·4203 으로 갑니다. 그런데 '장갑 고무'라고 적으면
    고무장갑(4015)이 나와야 합니다. 표를 이름 맞히기보다 먼저 보면 이
    좁힘이 사라집니다 — 그래서 **못 찾았을 때만** 표를 봅니다.
    """

    with app.app_context():
        rows = hsk_catalog.search("장갑 고무") or []
        codes = [str(row.get("code") or "") for row in rows]
    assert codes, "장갑 고무가 0건입니다"
    assert codes[0].startswith("4015"), codes[:3]
