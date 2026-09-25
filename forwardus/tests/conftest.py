"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from config import TestConfig  # noqa: E402


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    """테스트는 **바깥으로 나가지 않습니다.** `live` 표시가 있을 때만 허용합니다.

    왜 막나
      테스트가 실제 기관을 부르면 세 가지가 한꺼번에 나빠집니다.
        1. 키를 씁니다. 공공데이터포털은 하루 호출 수가 정해져 있어, 테스트를
           한 번 돌릴 때마다 실제 조회에 쓸 몫이 줄어듭니다. 넘기면 그날은
           화면에서도 조회가 안 됩니다.
        2. 기관이 멈추면 우리 테스트가 같이 빨개집니다. 우리 코드는 멀쩡한데요.
        3. 그날 환율·그날 응답에 따라 결과가 달라져, 어제 초록이던 것이
           오늘 빨개집니다.

      실제로 `test_fx_board.py`와 `test_exchange_client.py`가 그날 환율을
      받아 오고 있었습니다. 파일 첫 줄에 "바깥은 부르지 않습니다"라고 적혀
      있었는데도요. 사람이 지키기로 한 규칙은 이렇게 샙니다. 그래서 막습니다.

    실제로 부르고 싶으면
        @pytest.mark.live 를 붙이고  `pytest -m live` 로 따로 돌립니다.
    """

    if request.node.get_closest_marker("live"):
        return

    import socket

    real_connect = socket.socket.connect

    def blocked(self, address, *args, **kwargs):
        # 같은 컴퓨터 안(테스트 서버·DB)은 막지 않습니다. 바깥만 막습니다.
        host = address[0] if isinstance(address, tuple) else str(address)
        if host in ("127.0.0.1", "::1", "localhost"):
            return real_connect(self, address, *args, **kwargs)
        raise RuntimeError(
            f"테스트가 바깥({host})을 부르려 했습니다. 기관을 실제로 부르면 "
            "키를 쓰고 결과가 날마다 달라집니다. 응답을 흉내 내거나, 정말 "
            "불러야 하면 @pytest.mark.live 를 붙이세요.")

    monkeypatch.setattr(socket.socket, "connect", blocked)


@pytest.fixture(autouse=True)
def _fresh_exchange_cache():
    """환율은 한 번 받으면 한 시간 기억해 둡니다.

    테스트끼리는 그 기억이 넘어가면 안 됩니다. 앞 테스트가 흉내 낸 응답이
    다음 테스트에 그대로 남으면, 무엇을 보고 통과한 것인지 알 수 없습니다.
    """

    from app.collectors import exchange_client

    exchange_client.clear_cache()
    yield
    exchange_client.clear_cache()


@pytest.fixture(autouse=True)
def _isolated_file_cache(tmp_path, monkeypatch):
    """받아 둔 참고자료 파일(data/cache)을 테스트마다 빈 폴더로 바꿉니다.

    실제 캐시가 남아 있으면 흉내 낸 응답 대신 그 파일을 읽어 버립니다.
    """

    from app.collectors import file_cache, hs_open_client

    monkeypatch.setattr(file_cache, "cache_dir", lambda: tmp_path / "cache")
    hs_open_client.clear_cache()
    yield
    hs_open_client.clear_cache()


@pytest.fixture(autouse=True)
def _fresh_outages():
    """닿지 않은 기관을 건너뛴 기록이 테스트 사이에 넘어가지 않게 합니다."""

    from app.collectors import base_client

    base_client.clear_outages()
    yield
    base_client.clear_outages()


@pytest.fixture()
def app():
    flask_app = create_app(TestConfig)
    with flask_app.app_context():
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    """마스터로 로그인한 브라우저.

    Shipment 화면은 로그인해야 열리고, 서비스로 바로 만든 Shipment는
    작성자가 없어 마스터만 봅니다. 권한 자체는 tests/test_permissions.py에서 봅니다.
    """

    from app.models import User

    test_client = app.test_client()
    master = User.query.filter_by(email=app.config["MASTER_EMAIL"]).one()
    with test_client.session_transaction() as session:
        session["user_id"] = master.id
    return test_client


@pytest.fixture()
def anon_client(app):
    """로그인하지 않은 브라우저."""

    return app.test_client()


@pytest.fixture()
def cargo_input():
    return {
        "length_cm": 50,
        "width_cm": 40,
        "height_cm": 30,
        "quantity": 500,
        "weight_per_package_kg": 8,
        "package_type": "carton",
        "product_description": "Skin care cream 50ml",
        "hs_code": "3304.99",
        "net_weight_kg": 3500,
    }


@pytest.fixture()
def shipment_payload(cargo_input):
    return {
        "project_name": "10월 LA 화장품 출하",
        "transport_mode": "SEA",
        "sea_mode": "LCL",
        "origin_code": "KRPUS",
        "destination_code": "USLAX",
        "requested_departure_date": (date.today() + timedelta(days=10)).isoformat(),
        "buyer_required_date": (date.today() + timedelta(days=60)).isoformat(),
        "incoterms": "FOB",
        "currency": "USD",
        "invoice_value": 25000,
        "cargo": cargo_input,
        "exporter_name": "Forward Cosmetics Co., Ltd.",
        "exporter_address": "Seoul, Korea",
        "buyer": {"name": "ABC Beauty Inc.", "country": "US", "address": "Los Angeles, CA"},
    }


@pytest.fixture()
def create_shipment(app, shipment_payload):
    from app.services import planning_service

    def _create(**overrides):
        payload = {**shipment_payload, **overrides}
        schedules = planning_service.search_schedules(payload)
        payload["schedule_id"] = schedules["items"][0]["schedule_id"]
        return planning_service.create_shipment(payload)

    return _create


@pytest.fixture(scope="session")
def customs_api_up() -> bool:
    """관세청 UNI-PASS가 지금 응답하는지 한 번만 확인합니다.

    실데이터를 확인하는 테스트는 관세청이 멈추면 같이 실패합니다. 그건 우리
    코드가 틀린 것이 아니라 바깥이 안 되는 것이라, 실패 대신 건너뜁니다.
    (호출을 많이 하면 관세청이 잠시 막기도 합니다)
    """

    import httpx

    try:
        response = httpx.get(
            "https://unipass.customs.go.kr:38010/ext/rest/hsSgnQry/searchHsSgn",
            params={"crkyCn": "probe", "hsSgnStrtt": "샴푸"}, timeout=8)
        return response.status_code < 500
    except Exception:                      # noqa: BLE001 - 연결 자체가 안 되는 경우
        return False


@pytest.fixture()
def needs_customs_api(customs_api_up):
    if not customs_api_up:
        pytest.skip("관세청 UNI-PASS가 응답하지 않아 건너뜁니다. (코드 문제가 아닙니다)")
