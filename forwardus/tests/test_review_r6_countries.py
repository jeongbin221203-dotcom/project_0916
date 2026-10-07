"""전 국가 점검 — 제재 국가, 나라 찾기, 예시 스케줄 소요일."""

import pytest

from app.collectors import location_client
from app.processors import country_export_guide, trade_controls


@pytest.mark.parametrize("question, code", [
    ("인도네시아에 수출하려면", "ID"), ("도미니카공화국 수출", "DO"), ("적도기니 수출", "GQ"),
    ("튀르키예 수출", "TR"), ("타이완 수출", "TW"), ("마카오 수출", "MO"), ("인도 수출", "IN"),
    ("미국 말고 인도로 수출", "IN"), ("중국 수출", "CN"), ("가나 수출 인증", "GH"),
])
def test_나라를_정확히_찾는다(question, code):
    assert country_export_guide.find_country(question)[0] == code


@pytest.mark.parametrize("question", ["결제 수단으로 수출", "서류 가나다순 수출", "말리 수 있나 수출",
                                       "오만한 바이어 서류", "인도조건이 뭐예요 서류", "개인도 수출할 수 있나요"])
def test_일반_낱말을_나라로_읽지_않는다(question):
    assert country_export_guide.find_country(question) is None


def test_북한은_견적을_만들지_않는다(app, shipment_payload):
    from app.services import planning_service
    from app.validators import ValidationError
    payload = {**shipment_payload, "destination_code": "KPCHO", "schedule_id": "x"}
    with app.app_context():
        with pytest.raises(ValidationError) as caught:
            planning_service.create_shipment(payload)
    assert caught.value.code == "TRADE_CONTROL" and "남북교류협력법" in str(caught.value)


def test_제재_국가는_한_번_더_확인을_받는다(app):
    from app.services import planning_service
    from app.validators import ValidationError
    with app.app_context():
        with pytest.raises(ValidationError) as caught:
            planning_service._check_trade_controls({"country_code": "IR"}, {})
        assert caught.value.code == "RESTRICTED_CONFIRM"
        planning_service._check_trade_controls({"country_code": "IR"}, {"restricted_confirmed": True})
        with pytest.raises(ValidationError) as blocked:
            planning_service._check_trade_controls({"country_code": "KP"}, {"restricted_confirmed": True})
        assert blocked.value.code == "TRADE_CONTROL"
        planning_service._check_trade_controls({"country_code": "JP"}, {})        # 일반 국가는 그대로


def test_북한_가이드는_일반세율을_말하지_않는다():
    text = country_export_guide.guide("KP", "북한")
    assert "남북교류협력법" in text and "일반세율(MFN)" not in text


def test_자료_없는_나라는_자료가_없다고_밝힌다():
    assert "정리해 둔 인증 자료가 없습니다" in country_export_guide.guide("LK", "스리랑카")


def test_점령지_항구는_대표_항구가_아니다():
    ports = {item["code"]: item for item in location_client._all_locations()}
    assert not ports["UAMPW"]["major"] and ports["UAMPW"]["note"]
    assert not ports["ECN"]["major"]


def test_이란은_중동_일정으로_계산한다():
    assert {i["region"] for i in location_client._all_locations() if i["country_code"] == "IR"} == {"middle_east"}


@pytest.mark.parametrize("dest", ["USNYC", "NLRTM", "INNSA"])
def test_예시_스케줄도_항로_계산과_모순되지_않는다(app, shipment_payload, dest):
    from app.services import planning_service
    with app.app_context():
        payload = {**shipment_payload, "destination_code": dest}
        result = planning_service.search_schedules(payload)
        real = planning_service.transit_summary(payload["origin_code"], dest)["sea"][payload["sea_mode"]]["min"]
        assert min(item["transit_days"] for item in result["items"] if item.get("source") == "mock") == real


def test_모든_화면_푸터에_면책_문구가_있다(client):
    page = client.get("/dashboard").get_data(as_text=True)
    assert "참고용" in page and "법률·세무·관세 자문이 아닙니다" in page


def test_관세청_조회_화면에_환경변수_이름이_보이지_않는다(client):
    page = client.get("/lookup/").get_data(as_text=True)
    assert "UNIPASS_KEY" not in page and "DATA_GO_KR_SERVICE_KEY" not in page and "키 없음" not in page


def test_예시_스케줄_안내에_키_이름과_발급_주소가_없다():
    from app.collectors import schedule_client
    for service in ("FCL", "AIR"):
        note = schedule_client._missing_key_note(service)
        assert "HMM_API_KEY" not in note and "apiportal" not in note and "발급" not in note


def test_루트_requirements는_한_곳을_가리킨다():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2] / "requirements.txt"
    if root.exists():
        assert "-r forwardus/requirements.txt" in root.read_text(encoding="utf-8")


@pytest.mark.parametrize("title, chapters, shown", [
    ("CE 마킹(해당 지침이 있는 품목)", {"19"}, False), ("GPSR — 일반 소비재도 EU 책임자 필요", {"33"}, False),
    ("CE 마킹(해당 지침이 있는 품목)", {"84"}, True), ("CE 마킹(해당 지침이 있는 품목)", set(), True),
    ("CE 마킹(해당 지침이 있는 품목)", {"19", "85"}, True), ("할랄 인증", {"84"}, False), ("할랄 인증", {"19"}, True),
    ("BIS 인증(ISI/CRS)", {"33"}, False), ("BIS 인증(ISI/CRS)", {"85"}, True),
])
def test_품목에_안_걸리는_국가_공통_인증은_숨긴다(title, chapters, shown):
    from app.services.required_docs_service import _cert_fits
    assert _cert_fits(title, chapters) is shown


@pytest.mark.parametrize("item, asks", [
    ({"hs_code": "8507.60", "product_description": "packs"}, True),
    ({"hs_code": "", "product_description": "Lithium-ion battery packs"}, True),
    ({"hs_code": "", "product_description": "리튬 보조배터리"}, True),
    ({"hs_code": "3304.99", "product_description": "Skin care cream 50ml"}, False),
    ({"hs_code": "8507.60", "product_description": "x", "is_dangerous": True}, False),
])
def test_배터리는_위험물_체크_없이_통과하지_않는다(item, asks):
    from app.services import planning_service
    from app.validators import ValidationError
    if asks:
        with pytest.raises(ValidationError) as caught:
            planning_service._check_battery_goods([item], {})
        assert caught.value.code == "DG_CONFIRM"
        planning_service._check_battery_goods([item], {"dg_confirmed": True})
    else:
        planning_service._check_battery_goods([item], {})


def test_특수컨테이너_초과화물은_컨테이너_어림_조언을_하지_않는다(app):
    from app.services import planning_service
    with app.app_context():
        result = planning_service.calculate_cargo({"cargo": {"items": [{
            "product_description": "Excavator", "quantity": 1, "length_cm": 950, "width_cm": 290, "height_cm": 300,
            "weight_per_package_kg": 22500, "package_type": "wooden_crate", "special_container_type": "flat_rack"}]}})
    assert result["needs_forwarder_quote"] is True
    advice = result["sea_mode_advice"]
    assert advice["mode"] == "" and "포워더" in advice["reason"]


def test_일반_화물은_그대로_조언한다(app):
    from app.services import planning_service
    with app.app_context():
        result = planning_service.calculate_cargo({"cargo": {"items": [{
            "product_description": "Cream", "quantity": 12, "length_cm": 50, "width_cm": 40, "height_cm": 30,
            "weight_per_package_kg": 10, "package_type": "carton"}]}})
    assert not result.get("needs_forwarder_quote")
    assert result["sea_mode_advice"]["mode"] in ("LCL", "FCL", "")


@pytest.mark.parametrize("code", ["EG", "NG", "KE", "TZ", "IQ", "KW", "QA", "BH", "OM", "IL", "AR", "CL", "CO", "PE", "PK",
                                   "BD", "UA", "DZ", "MA", "UZ", "KZ", "BY", "ET"])
def test_자료를_채운_나라는_인증_안내가_있다(code):
    note = country_export_guide.NOTES[code]
    assert note["certs"] and note["watch"]
    # 단정 대신 확인 필요를 남깁니다 — 조사 자료가 공식 원문 대조 전입니다
    joined = " ".join(note["certs"] + note["watch"])
    assert "확인" in joined


def test_기존_나라_안내는_덮어쓰지_않는다():
    from app.processors.country_notes_extra import EXTRA_NOTES
    assert not (set(EXTRA_NOTES) & {"US", "CN", "JP", "SA", "AE", "IN", "VN"})
    assert "UKCA" in " ".join(country_export_guide.NOTES["GB"]["certs"])


def test_필수서류_목록에_새_나라_인증이_들어간다():
    from app.services import required_docs_service
    rows = required_docs_service._country_notes("NG", "나이지리아", {"85"})
    assert any("SONCAP" in row["title"] for row in rows)
