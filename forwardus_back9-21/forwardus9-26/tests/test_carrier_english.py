"""선사 조회를 영문으로도 할 수 있어야 합니다.

관세청 등록부는 한글 상호만 받습니다. 그런데 실무에서 부르는 이름은 영문입니다.
"HMM"이라고 적었는데 "조회되지 않습니다"가 나오면, 사람은 우리 서비스가 고장 난 줄 압니다.
"""

from unittest.mock import patch

import pytest

from app.collectors import carrier_client


@pytest.mark.parametrize("영문, 한글", [
    ("HMM", "에이치엠엠"),
    ("hmm", "에이치엠엠"),
    ("Maersk", "머스크"),
    ("Maersk Line A/S", "머스크"),
    ("MSC", "엠에스씨"),
    ("Hapag-Lloyd", "하파그로이드"),
    ("KMTC", "고려해운"),
    ("SM LINE", "에스엠상선"),
])
def test_영문_상호를_한글로_바꾼다(영문, 한글):
    assert carrier_client.korean_name_of(영문) == 한글


def test_모르는_영문이면_빈_글자(app):
    assert carrier_client.korean_name_of("Nobody Shipping Co") == ""


def test_영문으로_찾으면_한글_상호로_부른다(app):
    """관세청에는 한글로 물어봐야 합니다."""

    보낸값 = {}

    def 가짜(method, url, **kwargs):
        보낸값.update(kwargs.get("params") or {})
        return {"success": True, "data": "<x/>", "source": "api"}

    with patch.object(carrier_client, "request_text", 가짜), \
         patch.object(carrier_client, "_unipass_key", lambda name: "키"):
        carrier_client.search_shipping_companies("HMM")

    assert 보낸값.get("shipCoNm") == "에이치엠엠"


def test_네_글자_영문은_선사부호로_봅니다(app):
    """MAEU처럼 네 글자면 상호가 아니라 부호입니다. 부호 조회로 넘깁니다."""

    불린곳 = {}

    def 가짜(method, url, **kwargs):
        불린곳.update(kwargs.get("params") or {})
        return {"success": True, "data": "<x/>", "source": "api"}

    with patch.object(carrier_client, "request_text", 가짜), \
         patch.object(carrier_client, "_unipass_key", lambda name: "키"):
        carrier_client.search_shipping_companies("MAEU")

    assert 불린곳.get("shipCoSgn") == "MAEU"      # 상호가 아니라 부호로 물었습니다
    assert "shipCoNm" not in 불린곳


def test_모르는_영문에는_무엇을_하라고_알려준다(app):
    with patch.object(carrier_client, "_unipass_key", lambda name: "키"):
        result = carrier_client.search_shipping_companies("Nobody Shipping Company")

    assert result["success"] is False
    assert "한글 상호" in result["message"] and "선사부호" in result["message"]


def test_화면_안내문도_영문을_받는다고_적는다(app):
    from app.services import lookup_service

    hint = lookup_service.LOOKUPS["shipping_company"]["hint"]
    assert "영문" in hint and "조회되지 않습니다" not in hint
