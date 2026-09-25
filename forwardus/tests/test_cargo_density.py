"""부피에 견주어 중량이 말이 되는지 짚어 주는지 봅니다.

왜 필요한가
  대시보드의 "Average Cost / CBM"이 1,025,567원으로 찍힌 적이 있습니다. 계산은
  맞았고, 저장된 값이 "50×50×50cm 상자 한 개가 2,400kg"이었습니다. 0.125CBM에
  2.4톤은 강철보다 무겁습니다. 아무도 안 말려서 그대로 집계까지 올라갔습니다.
"""

import pytest

from app.processors import cargo_calculator


def box(**over):
    line = {"length_cm": 50, "width_cm": 50, "height_cm": 50,
            "quantity": 1, "weight_per_package_kg": 30, "package_type": "carton"}
    line.update(over)
    return line


def test_보통_화물은_아무_말도_하지_않는다():
    # 0.125CBM에 30kg → 240kg/CBM. 흔한 일반 화물입니다.
    assert cargo_calculator.calculate_cargo_metrics(box())["density_warning"] == ""


def test_물보다_무거우면_짚어_주되_막지_않는다():
    # 0.125CBM에 250kg → 2,000kg/CBM.
    note = cargo_calculator.calculate_cargo_metrics(box(weight_per_package_kg=250))["density_warning"]
    assert "1CBM당 2,000kg" in note
    assert "물이 1CBM당 1,000kg" in note


def test_강철보다_무거우면_무슨_물질쯤인지_알려_준다():
    # 화면에서 실제로 나온 값입니다. 0.125CBM에 2,400kg → 19,200kg/CBM.
    note = cargo_calculator.calculate_cargo_metrics(box(weight_per_package_kg=2_400))["density_warning"]
    assert "1CBM당 19,200kg" in note
    assert "납만큼 무겁습니다" in note              # 19,200은 텅스텐(19,250)에 못 미칩니다
    assert "그런 화물이 맞으면 그대로 두세요" in note


def test_금괴는_틀렸다고_하지_않는다():
    """금 19,300 · 백금 21,450kg/CBM. 실제로 오가는 화물입니다.

    강철(7,850)을 넘는다고 "불가능"이라 하면 금괴 화물을 잘못 막습니다.
    """

    for density_kg, material in ((19_300, "금"), (21_450, "백금")):
        # 1CBM 상자 하나에 그 무게. 곧 밀도가 그대로 나옵니다.
        note = cargo_calculator.calculate_cargo_metrics(
            box(length_cm=100, width_cm=100, height_cm=100,
                weight_per_package_kg=density_kg))["density_warning"]
        assert f"{material}만큼 무겁습니다" in note
        assert "값이 잘못 적혔습니다" not in note


def test_오스뮴보다_무거우면_그때는_틀렸다고_말한다():
    """지구에서 가장 무거운 물질이 오스뮴 22,590kg/CBM입니다. 그 위는 없습니다."""

    # 5cm 정육면체에 10kg → 80,000kg/CBM. 실제 저장된 값입니다.
    note = cargo_calculator.calculate_cargo_metrics(
        box(length_cm=5, width_cm=5, height_cm=5, weight_per_package_kg=10))["density_warning"]
    assert "오스뮴" in note
    assert "값이 잘못 적혔습니다" in note


def test_경고가_나와도_계산은_그대로_된다():
    """막지 않습니다. 틀렸는지는 보낸 사람이 압니다."""

    result = cargo_calculator.calculate_cargo_metrics(box(weight_per_package_kg=2_400, quantity=21))
    assert result["total_cbm"] == pytest.approx(2.625)
    assert result["total_weight_kg"] == pytest.approx(50_400)


def test_여러_품목이면_몇_번째_품목인지_함께_알려_준다():
    result = cargo_calculator.calculate_cargo_lines(
        [box(), box(weight_per_package_kg=2_400)], strict=False)
    heavy = [w for w in result["warnings"] if "1CBM당" in w["message"]]
    assert len(heavy) == 1
    assert heavy[0]["line_no"] == 2          # 첫 품목은 멀쩡합니다


def test_부피나_중량이_없으면_아무_말도_하지_않는다():
    """화물을 아직 안 적은 상태를 잘못됐다고 하면 안 됩니다."""

    assert cargo_calculator.density_note(0, 1_000) == ""
    assert cargo_calculator.density_note(2.6, 0) == ""
    assert cargo_calculator.density_suspect(0, 1_000) is False


def test_집계는_물보다_무거운_정도로는_세지_않는다():
    """물보다 무거운 화물은 흔합니다. 그것까지 세면 정작 볼 건이 묻힙니다."""

    assert cargo_calculator.density_suspect(1, 2_000) is False      # 물보다 무거움
    assert cargo_calculator.density_suspect(1, 12_000) is True      # 강철보다 무거움
