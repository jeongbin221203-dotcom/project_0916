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


@pytest.fixture()
def app():
    flask_app = create_app(TestConfig)
    with flask_app.app_context():
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
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
