"""예외 입력 회귀 테스트.

전 구간에 이상한 값을 수만 번 넣어 보고 실제로 터진 것들을 모았습니다.
(찾는 데 쓴 도구는 tests/_fuzz_*.py 에 있습니다)

여기 있는 것은 모두 "한때 500으로 죽었던" 입력입니다.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.validators import ValidationError

# 사람이 실수로, 또는 일부러 넣을 수 있는 값들.
NASTY = [None, "", " ", "abc", "1,000", "nan", "inf", "1e309", "\x00", "😀",
         True, False, 0, -1, 1.5, 10 ** 30, [], {}, [1], {"a": 1}]


def test_cargo_payload_of_any_shape_never_crashes(app):
    """화면이 보내는 cargo가 어떤 모양이어도 500으로 죽으면 안 됩니다."""

    from app.services import planning_service as ps

    shapes = [None, "", " ", "x", 1, [], [1], ["x"], {}, {"items": None},
              {"items": "x"}, {"items": [1, 2]}, {"items": [{}]}, [{"a": 1}]]
    with app.app_context():
        for shape in shapes:
            assert isinstance(ps.cargo_items({"cargo": shape}), list), shape
            for call in (ps.cargo_metrics, ps.calculate_cargo):
                try:
                    call({"cargo": shape})
                except ValidationError:
                    pass                        # 거절은 괜찮습니다. 죽는 것이 문제입니다.


def test_far_future_dates_are_refused_instead_of_overflowing(app):
    """9999-12-31에 소요일을 더하면 날짜 계산이 터집니다. 미리 막습니다."""

    from app.validators.shipment_validator import parse_date

    with app.app_context():
        for bad in ("9999-12-31", "0001-01-01", "1899-01-01", "2200-01-01"):
            with pytest.raises(ValidationError):
                parse_date(bad, "출발일")
        assert parse_date("2026-10-01", "출발일") == date(2026, 10, 1)


def test_eta_refuses_impossible_transit(app):
    from app.processors.schedule_calculator import calculate_eta

    with app.app_context():
        assert calculate_eta(date(2026, 9, 20), 14) == date(2026, 10, 4)
        for bad in (-1, "x", None, 10 ** 9, float("nan")):
            with pytest.raises(ValidationError):
                calculate_eta(date(2026, 9, 20), bad)


def test_transit_refuses_impossible_distance(app):
    """거리가 0이나 무한대면 "오늘 도착"이라는 거짓을 내지 않고 막습니다."""

    from app.processors import transit_calculator as tc

    with app.app_context():
        for bad in (0, -1, float("inf"), float("nan"), "x", None, 10 ** 9):
            with pytest.raises(ValidationError):
                tc.sea_transit(bad, [], "FCL", direct=True, region="asia")
            with pytest.raises(ValidationError):
                tc.air_transit(bad)
        # 정상 거리는 그대로 계산됩니다.
        assert tc.sea_transit(12_000, [], "FCL", direct=True, region="americas")["min"] > 0


def test_unknown_sea_mode_does_not_break_the_comparison(app):
    """화면이 FCL·LCL이 아닌 값을 보내도 비교 칸만 비고 끝나야 합니다."""

    from app.services import planning_service as ps

    with app.app_context():
        summary = ps.transit_summary("KRPUS", "USLAX")
        assert ps.sea_mode_difference(summary, "BULK") is None
        assert ps.sea_mode_difference(summary, "") is None
        assert ps.sea_mode_difference(summary, "FCL")["other"] == "LCL"


def test_helpers_accept_values_that_are_not_strings(app):
    """숫자나 True가 들어와도 .strip()에서 죽지 않아야 합니다."""

    from app.collectors import location_client
    from app.processors import dangerous_goods, export_requirements
    from app.services import planning_service as ps

    with app.app_context():
        for value in NASTY:
            assert location_client.find_location(value) is None or True
            assert isinstance(export_requirements.check(value), list)
            assert isinstance(dangerous_goods.search_un_numbers(value), list)
            assert isinstance(dangerous_goods.guide(value, "SEA", "US"), dict)
            assert isinstance(ps.air_route_status(value, "MEX"), dict)


def test_document_form_of_any_shape_is_survivable(app, create_shipment):
    from app.services import document_service
    from app.validators.document_validator import clean_document_fields

    with app.app_context():
        shipment = create_shipment()
        document_service.generate_documents(shipment)
        for shape in (None, "", [], {}, [1], "x", 1):
            assert isinstance(clean_document_fields(shape, {"doc_no": "x"}), dict)
            assert isinstance(clean_document_fields({"doc_no": "y"}, shape), dict)


def test_parties_payload_of_any_shape(app):
    from app.validators.shipment_validator import validate_parties

    with app.app_context():
        for shape in (None, "", [], 1, {"buyer": "x"}, {"buyer": 1}, {"buyer": []}):
            with pytest.raises(ValidationError):
                validate_parties(shape if isinstance(shape, dict) else {"buyer": shape})


def test_uploaded_file_never_escapes_its_folder(app, create_shipment):
    """파일 이름에 경로를 넣어도 정해진 폴더 안에만 저장돼야 합니다."""

    from app.services import requirement_service as rs

    class Fake:
        def __init__(self, name):
            self.filename, self.mimetype = name, "text/plain"

        def read(self):
            return b"CERTIFICATE"

    names = ["../../../etc/passwd.pdf", "..\\..\\windows\\evil.pdf",
             "/etc/passwd.pdf", "C:\\Windows\\evil.pdf"]
    with app.app_context():
        shipment = create_shipment()
        root = rs._upload_root().resolve()
        for name in names:
            document = rs.upload(shipment, Fake(name), "origin")
            where = (root / document.stored_name).resolve()
            assert where.parent == root, name
            assert "/" not in document.stored_name and "\\" not in document.stored_name
            rs.delete_upload(shipment, document.id)


def test_saved_numbers_are_stripped_of_symbols(app, create_shipment):
    from app.services import container_tracking_service as cts

    with app.app_context():
        shipment = create_shipment()
        cts.save_numbers(shipment, {"bl_no": "hdmu-pgohs 9311600<script>",
                                    "export_declaration_no": "abc122100900340033"})
        assert shipment.bl_no == "HDMUPGOHS9311600SCRIPT"
        assert shipment.export_declaration_no == "122100900340033"


@pytest.mark.parametrize("path", [
    "/planning/api/cargo", "/planning/api/schedule-outlook",
    "/planning/api/schedules", "/planning/api/shipments", "/api/support-chat",
])
def test_endpoints_never_return_500_for_junk(client, path):
    """깨진 요청에도 500이 아니라 사람이 읽을 수 있는 오류를 줘야 합니다."""

    bodies = [{}, [], None, {"cargo": "x"}, {"cargo": [1]}, {"buyer": 1},
              {"requested_departure_date": "9999-12-31"}, {"sea_mode": "BULK"},
              {"question": "x" * 5000}, {"history": "x"}]
    for body in bodies:
        assert client.post(path, json=body).status_code < 500, body
    # JSON 자체가 깨진 경우
    assert client.post(path, data="{oops", content_type="application/json").status_code < 500


@pytest.mark.parametrize("query", [
    "", "?q=", "?q=%00", "?q=" + "x" * 3000, "?hs=abc&country=ZZ",
    "?hs=" + "9" * 40, "?q=<script>alert(1)</script>", "?mode=XX&role=YY",
    "?year=abcd", "?q=%ED%8C%8C%EC%9D%BC",
])
def test_lookup_endpoints_never_return_500(client, query):
    paths = ["/planning/api/locations", "/planning/api/countries",
             "/planning/api/unlocode", "/planning/api/un-numbers",
             "/planning/api/tariff", "/planning/api/destination-tariff",
             "/tracking/container"]
    for path in paths:
        assert client.get(path + query).status_code < 500, path + query


def test_small_cargo_volume_never_rounds_to_zero(app):
    """3cm 상자도 자리를 차지합니다. CBM이 0이면 운임 기준이 서지 않습니다."""

    from app.processors.cargo_calculator import calculate_cargo_metrics, round_volume

    def cbm(size):
        return calculate_cargo_metrics(
            {"product_description": "샘플", "package_type": "carton", "quantity": 1,
             "length_cm": size, "width_cm": size, "height_cm": size,
             "weight_per_package_kg": 0.1}, strict=False)["total_cbm"]

    assert cbm(40) > 0
    assert cbm(3) > 0                   # 0.000027 CBM — 예전에는 0이었습니다.
    assert cbm(0.1) > 0
    # 큰 값은 예전처럼 넷째 자리에서 끊습니다.
    assert round_volume(0.123456) == 0.1235
    assert round_volume(0) == 0


def test_external_api_failures_never_break_the_page(app):
    """관세청이 안 되거나 응답이 깨져 와도 화면이 죽지 않아야 합니다."""

    from unittest.mock import patch

    import httpx

    from app.collectors import customs_client, exchange_client

    def response(status, text):
        return httpx.Response(status, text=text, request=httpx.Request("GET", "https://x"))

    broken = [
        lambda *a, **k: response(200, ""),
        lambda *a, **k: response(200, "<a><b></a>"),
        lambda *a, **k: response(200, "<html>점검 중</html>"),
        lambda *a, **k: response(401, "no"),
        lambda *a, **k: response(429, "slow"),
        lambda *a, **k: response(500, "boom"),
    ]
    with app.app_context():
        for maker in broken:
            with patch("httpx.request", side_effect=maker):
                for call in (lambda: customs_client.search_hs_codes("샴푸"),
                             lambda: customs_client.fetch_tariff_rates("3305100000"),
                             lambda: exchange_client.fetch_krw_rates()):
                    result = call()
                    # 모양이 무너지면 화면이 다음 줄에서 죽습니다.
                    assert isinstance(result, dict) and "success" in result

        # 끊기거나 느려도 마찬가지입니다. 내부 품목표나 예시 데이터로 넘어가면
        # 그렇다고 표시해야 하고(source=internal/mock), 넘어갈 것이 없으면 이유를 알려야 합니다.
        for error in (httpx.ReadTimeout("느림"), httpx.ConnectError("끊김")):
            with patch("httpx.request", side_effect=error):
                result = customs_client.search_hs_codes("샴푸")
                assert isinstance(result, dict) and "success" in result
                assert result["source"] in ("mock", "internal", "api")
                if result["success"]:
                    assert result["source"] in ("mock", "internal"), "실데이터인 척하면 안 됩니다"
                else:
                    assert result["message"]

                rates = customs_client.fetch_tariff_rates("3305100000")
                assert rates["success"] is False and rates["message"]


def test_many_items_and_repeated_submits(app, create_shipment):
    """품목이 많아도, 같은 요청을 여러 번 보내도 버텨야 합니다."""

    from app.services import document_service, planning_service as ps

    def item(index):
        return {"product_description": f"품목 {index}", "hs_code": "3305100000",
                "package_type": "carton", "quantity": 1, "length_cm": 10,
                "width_cm": 10, "height_cm": 10, "weight_per_package_kg": 1}

    with app.app_context():
        metrics = ps.cargo_metrics({"cargo": {"items": [item(i) for i in range(100)]}})
        assert len(metrics["lines"]) == 100
        assert metrics["quantity"] == 100

        # 더블클릭처럼 같은 일을 반복해도 번호가 겹치지 않아야 합니다.
        ids = [create_shipment().shipment_id for _ in range(3)]
        assert len(set(ids)) == 3

        from app.repositories import shipment_repository
        shipment = shipment_repository.get_by_shipment_id(ids[0])
        for _ in range(3):
            document_service.generate_documents(shipment)
            document_service.validate_shipment_documents(shipment)
        assert len(document_service.list_documents(shipment)) == len(document_service.DOCUMENT_TYPES)
