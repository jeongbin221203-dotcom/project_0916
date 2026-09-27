"""컨테이너·B/L 조회."""

from __future__ import annotations

from datetime import date

import pytest

from app.collectors import container_client
from app.services import container_tracking_service as tracking
from app.validators import ValidationError


def test_cargo_api_removes_display_separators(app, monkeypatch):
    from app.collectors.base_client import ok

    calls = []
    def request(method, url, **kwargs):
        calls.append(kwargs["params"])
        return ok("<response><tCnt>0</tCnt></response>", "api")

    app.config["UNIPASS_API_KEYS"] = {
        "CARGO_CLEARANCE_PROGRESS": "test-key", "CONTAINER_DETAIL": "test-key"}
    monkeypatch.setattr(container_client, "request_text", request)
    with app.app_context():
        container_client.cargo_progress(cargo_no=" 26QiFR1069i-2008 ")
        container_client.container_detail(" 26QiFR1069i-2008 ")
    assert len(calls) == 2
    assert all(params["cargMtNo"] == "26QIFR1069I2008" for params in calls)


def test_bl_lookups_use_the_same_normalization_as_saved_numbers(app, monkeypatch):
    from app.collectors.base_client import ok

    calls = []
    def request(method, url, **kwargs):
        calls.append(kwargs["params"])
        return ok("<response><tCnt>0</tCnt></response>", "api")

    app.config["UNIPASS_API_KEYS"] = {
        "CARGO_CLEARANCE_PROGRESS": "test-key", "EXPORT_PERFORMANCE_BY_DECLARATION": "test-key"}
    monkeypatch.setattr(container_client, "request_text", request)
    with app.app_context():
        container_client.cargo_progress(mbl_no=" hdmu-123 456 ", hbl_no=" house-123 ", bl_year="2026")
        container_client.export_performance(bl_no=" hdmu-123 456 ")
    assert calls[0]["mblNo"] == calls[1]["blNo"] == "HDMU123456"
    assert calls[0]["hblNo"] == "HOUSE123"
    assert calls[0]["blYy"] == "2026"


def test_container_service_error_is_not_hidden(app, monkeypatch):
    from app.collectors.base_client import fail, ok

    monkeypatch.setattr(container_client, "cargo_progress", lambda **kw: ok(None, "api"))
    monkeypatch.setattr(container_client, "container_detail", lambda number: fail("API_TIMEOUT", "api"))
    result = tracking.track("26QiFR1069i-2008")
    assert not result["available"]
    assert "기록 유무를 확인할 수 없습니다" in result["message"]
    assert any(note.startswith("컨테이너내역:") for note in result["notes"])


@pytest.mark.parametrize("error_code", ["API_AUTH_FAILED", "API_TIMEOUT", "API_CONNECTION_ERROR"])
def test_failed_lookup_does_not_claim_customs_has_no_records(app, monkeypatch, error_code):
    from app.collectors.base_client import fail, ok

    monkeypatch.setattr(container_client, "cargo_progress",
                        lambda **kw: fail(error_code, "api"))
    monkeypatch.setattr(container_client, "container_detail", lambda number: ok([], "api"))
    result = tracking.track("00ANLU083N59007001")
    assert not result["available"]
    assert "기록 유무를 확인할 수 없습니다" in result["message"]
    assert "관세청에 기록이 없습니다" not in result["message"]
    assert result["notes"]


def test_completed_empty_lookup_reports_no_records(app, monkeypatch):
    from app.collectors.base_client import ok

    monkeypatch.setattr(container_client, "cargo_progress", lambda **kw: ok(None, "api"))
    monkeypatch.setattr(container_client, "container_detail", lambda number: ok([], "api"))
    result = tracking.track("00ANLU083N59007001")
    assert "관세청에 기록이 없습니다" in result["message"]
    assert not result["notes"]


def test_number_shape_decides_where_we_ask():
    """번호 모양만 보고 어디에 물어볼지 정합니다."""

    assert tracking.detect_kind("122100900340033") == "export_declaration"   # 숫자 15자리
    assert tracking.detect_kind("GESU6710278") == "container"               # 영문4+숫자7
    assert tracking.detect_kind("gesu 671-0278") == "container"             # 띄어쓰기·하이픈 무시
    assert tracking.detect_kind("00ANLU083N59007001") == "cargo"            # 15~19자리 혼합
    assert tracking.detect_kind("HDMUPGOHS9311600") == "bl"
    assert tracking.detect_kind("") == ""


def test_container_number_alone_says_it_cannot_be_looked_up(app):
    """관세청은 컨테이너 번호를 입력으로 받지 않습니다. 지어내지 않고 알려 줍니다."""

    with app.app_context():
        result = tracking.track("GESU6710278")

    assert result["available"] is False
    assert result["kind"] == "container"
    assert "B/L번호" in result["message"]
    # 조사가 맞아야 읽힙니다. (숫자로 끝나면 "이")
    assert "GESU6710278이" in result["message"]


def test_loading_deadline_counts_down_and_warns():
    """적재의무기한은 수출신고 수리일부터 30일입니다. 넘기면 신고수리가 취소됩니다."""

    today = date(2026, 9, 20)

    ok = tracking.deadline_status("2026-10-15", False, today)
    assert ok["kind"] == "ok" and ok["days"] == 25

    soon = tracking.deadline_status("2026-09-25", False, today)
    assert soon["kind"] == "soon" and soon["days"] == 5
    assert "과태료" in soon["text"]

    over = tracking.deadline_status("2026-09-10", False, today)
    assert over["kind"] == "over" and over["days"] == -10
    assert "취소" in over["text"]

    # 이미 실었으면 기한을 따지지 않습니다.
    done = tracking.deadline_status("2026-09-10", True, today)
    assert done["kind"] == "done"

    assert tracking.deadline_status("", False, today) == {}


def test_export_lookup_reports_shipment_and_deadline(app, monkeypatch):
    """수출신고번호로 물으면 실렸는지와 기한이 함께 나옵니다."""

    monkeypatch.setattr(container_client, "export_performance", lambda **kw: {
        "success": True, "source": "api", "data": [{
            "declaration_no": "122100900340033", "bl_no": "HDMU123", "exporter": "포워더스(주)",
            "manufacturer": "", "shipped": False, "shipped_label": "미선적",
            "accepted_date": "2026-09-01", "load_deadline": "2026-10-01",
            "departure_date": "", "vessel_or_flight": "", "loading_place": "부산항",
            "shipped_weight": "", "cleared_weight": "1000", "shipped_packages": "",
            "cleared_packages": "10", "package_unit": "CT",
        }]})

    with app.app_context():
        result = tracking.track("122100900340033", today=date(2026, 9, 20))

    assert result["available"] is True
    row = result["export"][0]
    assert row["shipped"] is False
    assert row["deadline"]["days"] == 11
    assert row["deadline"]["kind"] == "ok"


def test_import_bl_needs_the_arrival_year(app, monkeypatch):
    """수입 통관 조회는 B/L번호만으로는 안 되고 입항년도가 있어야 합니다."""

    called = {}
    monkeypatch.setattr(container_client, "export_performance",
                        lambda **kw: {"success": True, "source": "api", "data": []})
    monkeypatch.setattr(container_client, "cargo_progress",
                        lambda **kw: called.update(kw) or {"success": True, "source": "api",
                                                           "data": None})
    with app.app_context():
        result = tracking.track("HDMUPGOHS9311600")

    assert called == {}                                   # 부르지 않았습니다.
    assert any("입항년도" in note for note in result["notes"])


def test_cargo_number_brings_containers_and_seals(app, monkeypatch):
    """화물관리번호로 물으면 컨테이너 번호와 봉인번호가 함께 나옵니다."""

    monkeypatch.setattr(container_client, "cargo_progress", lambda **kw: {
        "success": True, "source": "api", "data": {
            "kind": "detail", "cargo_no": "00ANLU083N59007001", "progress": "반출완료",
            "clearance": "수입신고수리", "mbl_no": "", "hbl_no": "", "bl_type": "",
            "carrier": "HMM", "carrier_code": "", "forwarder": "", "vessel": "HMM BLESSING",
            "voyage": "0012W", "vessel_country": "", "load_port": "Busan",
            "load_port_code": "", "discharge_port": "인천", "discharge_port_code": "",
            "arrival_customs": "인천세관", "arrival_date": "2026-09-01", "product": "샴푸",
            "cargo_type": "", "packages": "10", "package_unit": "CT", "weight": "1000",
            "weight_unit": "KG", "measurement": "", "container_count": "2",
            "container_no": "GESU6710278", "managed_cargo": "N", "events": [],
        }})
    monkeypatch.setattr(container_client, "container_detail", lambda cargo_no: {
        "success": True, "source": "api", "data": [
            {"container_no": "GESU6710278", "size_code": "45GP", "size_note": "40피트 하이큐브",
             "seals": ["103851"]},
            {"container_no": "KMTU9245255", "size_code": "45GP", "size_note": "40피트 하이큐브",
             "seals": ["103850"]},
        ]})

    with app.app_context():
        result = tracking.track("00ANLU083N59007001")

    assert result["available"] is True
    assert result["cargo"]["vessel"] == "HMM BLESSING"
    assert [box["container_no"] for box in result["containers"]] == ["GESU6710278", "KMTU9245255"]
    assert result["containers"][0]["seals"] == ["103851"]


def test_numbers_are_stored_in_a_checked_shape(app, create_shipment):
    with app.app_context():
        shipment = create_shipment()
        tracking.save_numbers(shipment, {
            "bl_no": "hdmu-pgohs 9311600", "export_declaration_no": "122100900340033"})
        assert shipment.bl_no == "HDMUPGOHS9311600"
        assert shipment.export_declaration_no == "122100900340033"

        with pytest.raises(ValidationError):
            tracking.save_numbers(shipment, {"export_declaration_no": "123"})
        with pytest.raises(ValidationError):
            tracking.save_numbers(shipment, {"cargo_no": "ABC"})


def test_shipment_without_numbers_says_what_to_do(app, create_shipment):
    with app.app_context():
        shipment = create_shipment()
        result = tracking.track_shipment(shipment)
    assert result["available"] is False
    assert "B/L번호" in result["message"]


def test_lookup_page_works_without_a_shipment(client):
    assert client.get("/tracking/container").status_code == 200
    html = client.get("/").get_data(as_text=True)
    assert "컨테이너 조회" in html


def test_seal_numbers_are_parsed_from_the_customs_xml():
    """관세청은 봉인번호를 세 칸으로 나눠 줍니다. 빈 칸은 버립니다."""

    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <cntrQryBrkdQryRtnVo><ntceInfo/>
      <cntrQryBrkdQryVo><cntrNo>GESU6710278</cntrNo><cntrStszCd>45GP</cntrStszCd>
        <cntrSelgNo1>103851</cntrSelgNo1><cntrSelgNo2/><cntrSelgNo3/></cntrQryBrkdQryVo>
      <tCnt>1</tCnt></cntrQryBrkdQryRtnVo>"""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml)
    row = next(root.iter("cntrQryBrkdQryVo"))
    seals = [(row.findtext(f"cntrSelgNo{i}") or "").strip() for i in (1, 2, 3)]
    assert [seal for seal in seals if seal] == ["103851"]
    assert container_client.CONTAINER_SIZE_NOTES["45"] == "40피트 하이큐브"


def test_particles_read_numbers_and_letters_aloud():
    """숫자·영문으로 끝나는 말도 사람은 한국어로 읽습니다.

    예전에는 "GESU6710278가(이)"처럼 괄호로 얼버무렸습니다.
    """

    from app.processors.korean import josa

    assert josa("GESU6710278", "이") == "GESU6710278이"   # 8 = 팔, ㄹ받침
    assert josa("LAX", "이") == "LAX가"                   # X = 엑스, 받침 없음
    assert josa("HMM", "로") == "HMM으로"                  # M = 엠, ㅁ받침
    assert josa("서울", "로") == "서울로"                    # ㄹ받침은 "로"
    assert josa("부산항", "로") == "부산항으로"
    # 알 수 없는 글자로 끝나면 예전처럼 둘 다 적습니다.
    assert josa("ロサンゼルス", "이") == "ロサンゼルス가(이)"
