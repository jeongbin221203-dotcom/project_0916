"""서류에서 읽은 값이 **끝까지 이어지는가.** (2026-09-28)

무엇이 났나
  서류에서 1,200 PCS 를 제대로 읽어 놓고도 화면에 이 오류가 떴습니다.

      수량 × 단가가 금액과 맞지 않습니다.
      24 × 4.5 = 108.00 인데 금액은 5,400.00 입니다.

  검증기는 멀쩡했습니다. unit_quantity 가 있으면 그것으로 곱합니다.
  **값이 검증기까지 못 간 것**입니다.

  두 군데서 버려지고 있었습니다.
    document_pipeline_service.ITEM_KEYS   초안이 들고 다닐 칸 목록에 없음
    document_start_service._item_fields   화면에 칸 자체가 없음

  읽기만 고치면 안 됩니다. 읽은 값이 지나는 길을 **끝까지** 봐야 합니다.
"""

from __future__ import annotations

import pytest

from app.services import (document_extract_service as extract,
                          document_pipeline_service as pipeline,
                          document_start_service as start)
from app.validators import ValidationError
from app.validators.cargo_validator import validate_commercial_line


RAW = {
    "transport_mode": "SEA", "total_packages": 40, "total_amount": 10600,
    "items": [{"product_description": "3-fold manual umbrella",
               "pieces": 1200, "units_per_package": 50, "piece_unit": "PCS",
               "package_unit": "CTN", "length_cm": 60, "width_cm": 40, "height_cm": 35,
               "gross_weight_kg": 408, "net_weight_kg": 360,
               "unit_price": 4.50, "amount": 5400}],
}


def test_읽은_값이_검증기까지_간다(app):
    """서류 읽기 -> 초안 -> 검증기. 어디서도 버려지면 안 됩니다."""

    form = extract.to_form(RAW)
    draft = pipeline._clean_draft({**form["fields"], "items": form["items"]})
    line = draft["items"][0]

    assert line["quantity"] == "24"              # CBM·중량의 기준
    assert line["unit_quantity"] == "1200"       # 단가의 기준
    assert line["price_unit"] == "PCS"

    checked = validate_commercial_line(line)     # 여기서 터지면 화면에 빨간 글이 뜹니다
    assert checked["amount"] == pytest.approx(5400)
    assert checked["unit_price"] == pytest.approx(4.5)


def test_낱개_수량이_없으면_틀렸다고_한다(app):
    """고치기 전에 나던 그 오류입니다. 이 경우에는 **틀렸다고 하는 것이 맞습니다.**

    포장 개수 24에 낱개 단가 4.50을 곱하면 108이고 금액은 5,400이니까요.
    """

    line = {"product_description": "우산", "package_type": "carton", "quantity": "24",
            "length_cm": "60", "width_cm": "40", "height_cm": "35",
            "weight_per_package_kg": "17", "unit_price": "4.5", "amount": "5400"}
    with pytest.raises(ValidationError) as caught:
        validate_commercial_line(line)
    assert "24" in str(caught.value) and "5,400" in str(caught.value)


@pytest.mark.parametrize("key", ["unit_quantity", "price_unit"])
def test_초안이_그_칸을_들고_다닌다(key):
    """ITEM_KEYS 에 없으면 _clean_draft 가 조용히 버립니다."""

    assert key in pipeline.ITEM_KEYS


@pytest.mark.parametrize("key", ["sea_mode", "buyer_required_date"])
def test_초안이_서류에서_읽은_칸도_들고_다닌다(key):
    assert key in pipeline.DRAFT_KEYS


@pytest.mark.parametrize("key", ["unit_quantity", "price_unit"])
def test_화면에_칸이_있다(app, key):
    """칸이 없으면 사람이 보지도 고치지도 못합니다.

    서류에서 읽어 놓고도 화면에서 사라져, 왜 금액이 안 맞는지 알 수 없습니다.
    """

    names = {field["name"] for field in start._item_fields({"package_type": []})}
    assert key in names


def test_포장_개수_라벨이_또렷하다(app):
    """"포장 개수"만으로는 낱개와 헷갈립니다."""

    fields = {field["name"]: field for field in start._item_fields({"package_type": []})}
    assert "상자" in fields["quantity"]["label"]
