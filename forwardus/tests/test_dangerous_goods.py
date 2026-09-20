"""위험물 입력 검증과 안내를 확인합니다."""

from __future__ import annotations

import pytest

from app.processors import dangerous_goods
from app.processors.korean import josa
from app.services import planning_service
from app.validators import ValidationError
from app.validators.cargo_validator import validate_dangerous_goods

CARGO = {"product_description": "페인트", "package_type": "drum", "quantity": 10,
         "length_cm": 40, "width_cm": 40, "height_cm": 60, "weight_per_package_kg": 50}


DG = {"is_dangerous": True, "un_number": "UN1263", "dg_class": "3",
      "proper_shipping_name": "PAINT"}


def test_unchecked_cargo_carries_no_dangerous_goods_fields():
    assert validate_dangerous_goods({}) == {
        "is_dangerous": False, "un_number": "", "dg_class": "",
        "packing_group": "", "proper_shipping_name": "", "dg_warning": ""}
    assert validate_dangerous_goods({"is_dangerous": False, "un_number": "UN1263"})["un_number"] == ""


@pytest.mark.parametrize("raw,expected", [("UN1263", "UN1263"), ("un1263", "UN1263"),
                                          ("1263", "UN1263"), (" UN 1263 ", "UN1263")])
def test_un_number_is_normalised(raw, expected):
    """UN번호는 서류마다 표기가 달라 들어오는 대로 받고 한 가지 모양으로 맞춥니다."""

    result = validate_dangerous_goods({**DG, "un_number": raw, "packing_group": "ii"})
    assert result == {"is_dangerous": True, "un_number": expected, "dg_class": "3",
                      "packing_group": "II", "proper_shipping_name": "PAINT", "dg_warning": ""}


@pytest.mark.parametrize("payload,field", [
    ({**DG, "un_number": ""}, "un_number"),
    ({**DG, "un_number": "UN126"}, "un_number"),
    ({**DG, "un_number": "ABCD"}, "un_number"),
    ({**DG, "dg_class": ""}, "dg_class"),
    ({**DG, "dg_class": "99"}, "dg_class"),
    ({**DG, "proper_shipping_name": ""}, "proper_shipping_name"),
    ({**DG, "packing_group": "IV"}, "packing_group"),
])
def test_dangerous_goods_needs_every_declaration_field(payload, field):
    """위험물 신고서에 그대로 들어가는 항목이라 저장할 때는 모두 있어야 합니다."""

    with pytest.raises(ValidationError) as error:
        validate_dangerous_goods(payload)
    assert error.value.field == field


def test_incomplete_dangerous_goods_do_not_block_the_calculation():
    """입력하는 도중에는 막지 않습니다. CBM은 치수와 수량만 있으면 낼 수 있습니다."""

    result = validate_dangerous_goods({**DG, "un_number": ""}, strict=False)
    assert result["is_dangerous"] is True
    assert "UN번호는 네 자리" in result["dg_warning"]
    # 이미 적은 값은 지우지 않습니다.
    assert result["dg_class"] == "3" and result["proper_shipping_name"] == "PAINT"
    assert validate_dangerous_goods(DG, strict=False)["dg_warning"] == ""


def test_air_and_sea_rules_differ_for_the_same_class(app):
    """같은 물건이라도 해상은 되고 항공은 안 되는 경우가 많습니다."""

    sea = planning_service.dangerous_goods_guide("1", "SEA", "DE")
    air = planning_service.dangerous_goods_guide("1", "AIR", "DE")
    assert sea["status"] == "allowed" and "IMDG" in sea["rule"]
    assert air["status"] == "forbidden" and "IATA" in air["rule"]
    assert "항공" in air["status_label"]

    # 해상·항공 각각의 절차가 들어갑니다.
    assert any("컨테이너수납검사증" in step for step in sea["steps"])
    assert any("IATA DGR 교육" in step for step in air["steps"])
    # 급을 고르기 전에는 안내하지 않습니다.
    assert planning_service.dangerous_goods_guide("", "SEA", "DE")["available"] is False


def test_guide_explains_which_goods_belong_to_the_class(app):
    """"어느 품목인지"를 예시로 알려줍니다."""

    guide = planning_service.dangerous_goods_guide("9", "AIR", "US")
    assert "리튬" in guide["examples"]
    assert "리튬" in guide["mode_note"]
    assert "미국으로" in guide["destination_note"]      # 조사를 앞말에 맞춥니다.
    assert guide["references"]


def test_every_class_has_examples_and_mode_notes():
    """등급 자료가 비면 화면이 빈칸으로 나옵니다. 모두 채워져 있어야 합니다."""

    for code, info in dangerous_goods.DG_CLASSES.items():
        assert info["examples"] and info["air_note"] and info["sea_note"], code
        assert info["air"] in dangerous_goods.AIR_STATUS_LABELS, code


def test_korean_particle_matches_the_preceding_word():
    assert josa("독일", "로") == "독일로"          # ㄹ 받침은 "로"
    assert josa("미국", "로") == "미국으로"
    assert josa("호주", "로") == "호주로"          # 받침 없음
    assert josa("프랑스", "이") == "프랑스가"
    assert josa("독일", "이") == "독일이"
    assert josa("USA", "이") == "USA가(이)"        # 한글이 아니면 둘 다 적습니다.


def test_cargo_metrics_collect_dangerous_classes(app):
    """한 건에 위험물이 섞이면 부킹이 달라지므로 등급을 모아 둡니다."""

    metrics = planning_service.cargo_metrics({"cargo": {"items": [
        {**CARGO, **DG, "un_number": "1263"},
        {**CARGO, "product_description": "배터리", "is_dangerous": True, "un_number": "UN3480",
         "dg_class": "9", "proper_shipping_name": "LITHIUM ION BATTERIES"},
        {**CARGO, "product_description": "포장재"},
    ]}})
    assert metrics["dangerous_classes"] == ["3", "9"]
    assert metrics["lines"][0]["un_number"] == "UN1263"
    assert metrics["lines"][2]["is_dangerous"] is False

    # 위험물이 없으면 빈 목록입니다.
    assert planning_service.cargo_metrics({"cargo": CARGO})["dangerous_classes"] == []


def test_dangerous_goods_are_stored_on_the_shipment(create_shipment):
    """저장한 뒤에도 UN번호와 급이 남아야 서류에 쓸 수 있습니다."""

    shipment = create_shipment(cargo={**CARGO, **DG, "un_number": "un1263", "packing_group": "II"})
    cargo = shipment.cargos[0]
    assert cargo.is_dangerous is True
    assert cargo.un_number == "UN1263" and cargo.dg_class == "3"
    assert cargo.packing_group == "II" and cargo.proper_shipping_name == "PAINT"
    assert cargo.to_dict()["proper_shipping_name"] == "PAINT"


def test_preview_returns_warnings_instead_of_failing(app):
    """화면 계산은 위험물 칸이 덜 채워져도 CBM을 내고, 어느 품목인지 알려줍니다."""

    result = planning_service.calculate_cargo({"cargo": {"items": [
        {**CARGO},                                    # 1번: 위험물 아님
        {**CARGO, **DG, "un_number": ""},             # 2번: UN번호 없음
    ]}})
    assert result["total_cbm"] > 0                    # 계산은 그대로 됩니다.
    assert [w["line_no"] for w in result["dg_warnings"]] == [2]
    assert "UN번호" in result["dg_warnings"][0]["message"]
    # 등급이 비면 위험물 등급 집계에 들어가지 않습니다.
    assert result["dangerous_classes"] == ["3"]

    # 다 채우면 경고가 없습니다.
    done = planning_service.calculate_cargo({"cargo": {"items": [{**CARGO, **DG}]}})
    assert done["dg_warnings"] == []


def test_unchecking_dangerous_goods_clears_the_warning(app):
    """위험물 체크를 풀면 경고가 사라지고 계산이 정상으로 돌아와야 합니다."""

    broken = planning_service.calculate_cargo({"cargo": {"items": [{**CARGO, **DG, "un_number": ""}]}})
    assert broken["dg_warnings"]

    cleared = planning_service.calculate_cargo({"cargo": {"items": [
        {**CARGO, **DG, "un_number": "", "is_dangerous": False}]}})
    assert cleared["dg_warnings"] == []
    assert cleared["dangerous_classes"] == []
    assert cleared["total_cbm"] == broken["total_cbm"]


def test_dangerous_goods_api(client):
    response = client.get("/planning/api/dangerous-goods?dg_class=3&mode=AIR&country=DE")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["available"] and data["label"].startswith("3급")
    assert "독일로" in data["destination_note"]
