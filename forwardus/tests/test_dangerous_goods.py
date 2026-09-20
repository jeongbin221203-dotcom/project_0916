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


def test_unchecked_cargo_carries_no_dangerous_goods_fields():
    assert validate_dangerous_goods({}) == {"is_dangerous": False, "un_number": "", "dg_class": ""}
    assert validate_dangerous_goods({"is_dangerous": False, "un_number": "UN1263"})["un_number"] == ""


@pytest.mark.parametrize("raw,expected", [("UN1263", "UN1263"), ("un1263", "UN1263"),
                                          ("1263", "UN1263"), (" UN 1263 ", "UN1263")])
def test_un_number_is_normalised(raw, expected):
    """UN번호는 서류마다 표기가 달라 들어오는 대로 받고 한 가지 모양으로 맞춥니다."""

    result = validate_dangerous_goods({"is_dangerous": True, "un_number": raw, "dg_class": "3"})
    assert result == {"is_dangerous": True, "un_number": expected, "dg_class": "3"}


@pytest.mark.parametrize("payload,field", [
    ({"is_dangerous": True, "un_number": "", "dg_class": "3"}, "un_number"),
    ({"is_dangerous": True, "un_number": "UN126", "dg_class": "3"}, "un_number"),
    ({"is_dangerous": True, "un_number": "ABCD", "dg_class": "3"}, "un_number"),
    ({"is_dangerous": True, "un_number": "UN1263", "dg_class": ""}, "dg_class"),
    ({"is_dangerous": True, "un_number": "UN1263", "dg_class": "99"}, "dg_class"),
])
def test_dangerous_goods_needs_un_number_and_class(payload, field):
    """위험물이라고 체크했으면 UN번호와 급이 반드시 있어야 서류를 만들 수 있습니다."""

    with pytest.raises(ValidationError) as error:
        validate_dangerous_goods(payload)
    assert error.value.field == field


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
        {**CARGO, "is_dangerous": True, "un_number": "1263", "dg_class": "3"},
        {**CARGO, "product_description": "배터리", "is_dangerous": True,
         "un_number": "UN3480", "dg_class": "9"},
        {**CARGO, "product_description": "포장재"},
    ]}})
    assert metrics["dangerous_classes"] == ["3", "9"]
    assert metrics["lines"][0]["un_number"] == "UN1263"
    assert metrics["lines"][2]["is_dangerous"] is False

    # 위험물이 없으면 빈 목록입니다.
    assert planning_service.cargo_metrics({"cargo": CARGO})["dangerous_classes"] == []


def test_dangerous_goods_are_stored_on_the_shipment(create_shipment):
    """저장한 뒤에도 UN번호와 급이 남아야 서류에 쓸 수 있습니다."""

    shipment = create_shipment(cargo={**CARGO, "is_dangerous": True,
                                      "un_number": "un1263", "dg_class": "3"})
    cargo = shipment.cargos[0]
    assert cargo.is_dangerous is True
    assert cargo.un_number == "UN1263" and cargo.dg_class == "3"
    assert cargo.to_dict()["dg_class"] == "3"


def test_dangerous_goods_api(client):
    response = client.get("/planning/api/dangerous-goods?dg_class=3&mode=AIR&country=DE")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["available"] and data["label"].startswith("3급")
    assert "독일로" in data["destination_note"]
