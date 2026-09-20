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
