"""미국이 **화장품이 아니라 의약품**으로 보는 품목을 짚어 주는가.

제33류는 대개 화장품이라 규칙이 류(2자리)로만 걸려 있었습니다. 그런데 미국은
아래를 화장품이 아니라 OTC 의약품으로 봅니다.
    자외선차단제(SPF)      21 CFR 352
    비듬 치료 샴푸          21 CFR 358
    불소 함유 치약          21 CFR 355
    발한억제(antiperspirant) 21 CFR 350
화장품으로 알고 MoCRA 로 등록해 보내면 **통관에서 반송**됩니다. 의약품은
시설 등록·제품 리스팅(NDC)과 Drug Facts 라벨이 따로 필요합니다.

선크림·치약은 우리나라가 미국에 많이 보내는 품목입니다. (2026-09-27)
"""

from __future__ import annotations

import pytest

from app.collectors import customs_client


def _titles(hs_code, country="US"):
    found = customs_client.fetch_regulations(hs_code, country)
    assert found["success"], found
    return [item["title"] for item in found["data"]["items"]]


@pytest.mark.parametrize("hs_code,word", [
    ("3304990000", "자외선차단"),      # 기초·색조 (선크림이면 의약품)
    ("3305100000", "비듬"),            # 샴푸
    ("3306100000", "불소"),            # 치약
    ("3307200000", "발한억제"),        # 데오도란트
])
def test_미국은_의약품으로_본다고_알려_준다(app, hs_code, word):
    titles = " · ".join(_titles(hs_code))
    assert word in titles, f"{hs_code} 안내에 '{word}' 이야기가 없습니다: {titles}"
    assert "MoCRA" in titles, "화장품 쪽 안내도 함께 있어야 합니다(둘 중 하나입니다)"


def test_왜_그런지와_무엇을_해야_하는지_적는다(app):
    found = customs_client.fetch_regulations("3306100000", "US")
    detail = next(item["detail"] for item in found["data"]["items"]
                  if "불소" in item["title"])
    assert "21 CFR 355" in detail, "근거 조문을 적어야 사람이 확인할 수 있습니다"
    assert "Drug Facts" in detail and "리스팅" in detail
    assert "반송" in detail, "왜 위험한지 적어야 합니다"


def test_다른_나라에는_붙지_않는다(app):
    """미국 규정입니다. 중국·일본에 붙이면 엉뚱한 안내가 됩니다."""

    for country in ("CN", "JP", "VN"):
        assert not any("OTC" in title for title in _titles("3306100000", country))


def test_화장품이_아닌_류는_그대로다(app):
    titles = _titles("8517120000")
    assert "FCC 인증" in titles
    assert not any("OTC" in title for title in titles)


def test_호_규칙이_류_규칙보다_앞에_온다(app):
    """더 좁은 규칙을 먼저 읽게 해야 사람이 먼저 봅니다."""

    titles = _titles("3306100000")
    assert titles.index("불소가 들어 있으면 OTC 의약품") \
        < titles.index("FDA MoCRA 시설 등록·제품 리스팅")
