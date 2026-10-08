"""r11 무역 실무 재점검 회귀 — 걸리면 안 되는 문장을 먼저 확인한다."""

from pathlib import Path

import pytest

from app.processors import export_requirements, trade_controls


@pytest.mark.parametrize("text", ["아이스크림 컴퍼니", "크림치즈 수입상", "Kerchner Trading"])
def test_평범한_상호는_점령지로_보지_않는다(text):
    assert trade_controls.region_in_text(text) == ""


@pytest.mark.parametrize("text", ["크림반도 무역", "Sevastopol port", "Крым", "Yalta trading", "Donbass LLC", "South Ossetia"])
def test_점령지_이름은_잡는다(text):
    assert trade_controls.region_in_text(text)


def test_서류_화면은_입력이_바뀌면_확인_표시를_지운다():
    js = (Path(__file__).resolve().parents[1] / "app/static/js/doc_form.js").read_text(encoding="utf-8")
    assert "confirmedSignature" in js and "delete confirmedFlags[key]" in js


def test_건설기계와_자동차는_다른_절차():
    machinery = [r["key"] for r in export_requirements.check("8429.52", is_used=True)]
    car = [r["key"] for r in export_requirements.check("8703.23", is_used=True)]
    assert "used_machinery" in machinery and "used_vehicle" not in machinery
    assert "used_vehicle" in car and "used_machinery" not in car


def test_태블릿_단어만으로_배터리_확인을_요구하지_않는다():
    from app.services import planning_service as p
    assert not p._BATTERY_WORDS.search("tablet press for pills")
    assert p._BATTERY_WORDS.search("tablet pc")


@pytest.mark.parametrize("name", ["러시아", "북한", "Iran", "Russian Federation", "Islamic Republic of Iran", "이란", "Syria"])
def test_바이어_국가를_이름으로_적어도_제재_검사(name):
    from app.validators import ValidationError
    from app.services.planning_service import check_trade_controls
    with pytest.raises(ValidationError):
        check_trade_controls(["US", name], {})


@pytest.mark.parametrize("name", ["미국", "Vietnam", "일본", "United States"])
def test_평범한_나라_이름은_통과(name):
    from app.services.planning_service import check_trade_controls
    check_trade_controls(["US", name], {})


def test_컨테이너에_안_들어가는_화물은_합산_결과에도_경고():
    from app.processors.cargo_calculator import calculate_cargo_lines
    m = calculate_cargo_lines([{"length_cm": 600, "width_cm": 250, "height_cm": 260, "weight_per_package_kg": 20000,
                                "quantity": 1, "package_type": "carton"}], strict=False)
    assert m["oversize_warning"]
    ok = calculate_cargo_lines([{"length_cm": 50, "width_cm": 40, "height_cm": 30, "weight_per_package_kg": 10,
                                 "quantity": 1, "package_type": "carton"}], strict=False)
    assert not ok["oversize_warning"]


def test_HS_없이_품명만으로도_중고차_절차_카드():
    keys = [r["key"] for r in export_requirements.check("", is_used=True, product_name="Used Hyundai Sonata car")]
    assert "used_vehicle" in keys
    # 품명에 'car' 가 들어간 다른 낱말(carbon, cardigan)은 걸리지 않는다
    keys = [r["key"] for r in export_requirements.check("", is_used=True, product_name="carbon cardigan")]
    assert "used_vehicle" not in keys
    # HS 가 분명하면 품명은 보지 않는다
    keys = [r["key"] for r in export_requirements.check("6109.10", is_used=True, product_name="used car seat cover")]
    assert "used_vehicle" not in keys


def test_중고_일반_안내의_CE는_기계류에만():
    from app.processors import used_goods
    assert "CE" not in used_goods.generic({"62"})
    assert "CE" in used_goods.generic({"84"}) and "CE" in used_goods.generic(None)


def test_저장한_서류는_인쇄해도_초안_표시가_남는다():
    root = Path(__file__).resolve().parents[1]
    html = (root / "app/templates/document/view.html").read_text(encoding="utf-8")
    line = next(l for l in html.splitlines() if "paper_notice" in l)
    assert "no_print" not in line
    css = (root / "app/static/css/document.css").read_text(encoding="utf-8")
    assert ".paper_notice" in css


def test_env_example의_빈_마스터_값이_기본값을_가리지_않는다(monkeypatch):
    import importlib

    import config
    monkeypatch.setenv("MASTER_EMAIL", "")
    monkeypatch.setenv("MASTER_PASSWORD", "")
    try:
        reloaded = importlib.reload(config)
        assert reloaded.Config.MASTER_EMAIL and reloaded.Config.MASTER_PASSWORD
    finally:
        monkeypatch.undo()
        importlib.reload(config)
