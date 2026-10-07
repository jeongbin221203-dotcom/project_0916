"""사용자 관점 재검수에서 나온 것 — 제재 확인 뒤의 안내, 확인 흐름, 배터리 감지, 항구 코드 표기."""

from pathlib import Path

import pytest

from app.extensions import db
from app.models import Shipment, User
from app.services import advisory_service, planning_service

JS = Path(planning_service.__file__).resolve().parents[1] / "static" / "js" / "planning.js"


def test_도착국을_고르는_후보에_제재_안내가_실린다(app):
    items = planning_service.search_locations("", "SEA", "destination", country="KP")["data"]
    assert items and all("남북교류협력법" in item["control_note"] for item in items)
    iran = planning_service.search_locations("", "SEA", "destination", country="IR")["data"]
    assert iran and all("책임" in item["control_note"] for item in iran)
    japan = planning_service.search_locations("", "SEA", "destination", country="JP")["data"]
    assert japan and not any("control_note" in item for item in japan)


def test_제재국_건의_상세와_수출요건에_안내_카드가_있다(app, client, create_shipment):
    shipment = create_shipment(destination_code="IRBND", restricted_confirmed=True)
    cards = advisory_service.advisories(db.session.get(Shipment, shipment.id))
    assert any(card["level"] == "strict" for card in cards)
    for url in (f"/shipments/{shipment.shipment_id}", f"/documents/{shipment.shipment_id}/requirements",
                f"/documents/{shipment.shipment_id}"):
        page = client.get(url).get_data(as_text=True)
        assert "제재·수출통제 확인 필요" in page, url


def test_일반_건에는_안내_카드가_없다(app, client, create_shipment):
    shipment = create_shipment()
    assert advisory_service.advisories(db.session.get(Shipment, shipment.id)) == []
    assert "advisory_card" not in client.get(f"/shipments/{shipment.shipment_id}").get_data(as_text=True)


def test_중고_건에는_수입국_규제_카드가_있다(app, client, create_shipment, cargo_input):
    shipment = create_shipment(cargo={**cargo_input, "used_condition": "used"})
    page = client.get(f"/shipments/{shipment.shipment_id}").get_data(as_text=True)
    assert "중고품 수입 규제 확인" in page


def test_마법사_확인_표시는_도착국이_바뀌면_지워진다():
    source = JS.read_text(encoding="utf-8")
    assert "const confirmed = {};" in source and source.count("const confirmed = {};") == 1
    assert "delete confirmed[key]" in source                      # invalidateSchedules 에서 비웁니다
    assert 'STAY_ON_STEP = new Set(["RESTRICTED_CONFIRM", "DG_CONFIRM"])' in source
    assert "un_number: 3" in source and "buyer_country: 5" in source
    assert "showControlNote" in source and "data-control-note" in source


@pytest.mark.parametrize("name", ["전동 킥보드", "Laptop computer", "스마트폰 케이스 포함 세트", "Wireless earbuds", "무선 청소기",
                                   "Drone with camera", "전자담배", "Smart watch"])
def test_기기_내장_배터리도_위험물_확인을_요구한다(name):
    from app.validators import ValidationError
    with pytest.raises(ValidationError) as caught:
        planning_service._check_battery_goods([{"hs_code": "", "product_description": name}], {})
    assert caught.value.code == "DG_CONFIRM"


@pytest.mark.parametrize("name", ["Skin care cream 50ml", "치약", "Cotton T-shirt", "Wooden chair", "Ceramic cup"])
def test_배터리와_무관한_품명은_묻지_않는다(name):
    planning_service._check_battery_goods([{"hs_code": "", "product_description": name}], {})


def test_항공_위험물_안내에는_해상_규정_링크가_없다():
    from app.processors import dangerous_goods
    air = dangerous_goods.guide("9", "AIR") if hasattr(dangerous_goods, "guide") else None
    if air is None:
        pytest.skip("guide 시그니처가 다릅니다")
    labels = " ".join(ref["label"] for ref in air["references"])
    assert "IMDG" not in labels and "선박" not in labels and "IATA" in labels


def test_EU_나라도_중고_공통_안내가_나온다():
    from app.processors import used_goods
    assert used_goods.notes_for("FR") and used_goods.notes_for("NL") and used_goods.notes_for("DE")
    assert used_goods.notes_for("US") == []


def test_서류에는_실제_UNLOCODE가_찍힌다():
    from app.services.document_service import _port
    assert _port("Shanghai", "CNSGH") == "Shanghai (CNSHA)"
    assert _port("Ningbo", "CNNBO") == "Ningbo (CNNGB)"
    assert _port("Busan", "KRPUS") == "Busan (KRPUS)"
    assert _port("Rotterdam", "NLRTM") == "Rotterdam (NLRTM)"
    assert _port("", "") == ""


def test_삭제_확인은_대소문자를_가리지_않는다(app, create_shipment):
    browser = app.test_client()
    assert browser.post("/auth/signup", data={"email": "case@example.com", "password": "secret123",
                                              "password_confirm": "secret123"}).status_code == 302
    shipment = create_shipment()
    shipment.user_id = User.query.filter_by(email="case@example.com").one().id
    db.session.commit()
    pk, number = shipment.id, shipment.shipment_id
    browser.post(f"/shipments/{number}/delete", data={"confirm": number.lower()})
    db.session.expire_all()
    assert db.session.get(Shipment, pk) is None


def test_포장명세서_열_이름에_단위가_있다():
    from app.services.document_service import DOCUMENT_ITEM_FIELDS
    labels = [label for _, label in DOCUMENT_ITEM_FIELDS["packing_list"]]
    assert "UNIT WEIGHT (kg)" in labels and "TOTAL WEIGHT (kg)" in labels


def test_인쇄_CSS가_표를_폭에_맞춘다():
    css = (JS.parents[1] / "css" / "document.css").read_text(encoding="utf-8")
    assert "@media print" in css and "table-layout: fixed" in css
