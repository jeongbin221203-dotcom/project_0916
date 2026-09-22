"""Route smoke tests across the full Shipment flow."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize("path", ["/", "/planning/new", "/shipments", "/health"])
def test_static_pages_render(client, path):
    assert client.get(path).status_code == 200


def test_unknown_shipment_returns_404(client):
    assert client.get("/shipments/EXP-0000-00000").status_code == 404
    assert client.get("/tracking/EXP-0000-00000").status_code == 404


def test_api_errors_are_normalized(client):
    response = client.post("/planning/api/cargo", json={"length_cm": "abc"})
    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["field"] == "length_cm"


def test_location_autocomplete(client):
    body = client.get("/planning/api/locations?q=Los%20Angeles&mode=SEA&role=destination").get_json()
    assert body["success"] and body["source"] == "mock"
    assert body["data"][0]["code"] == "USLAX"


def test_full_flow(client, shipment_payload):
    schedules = client.post("/planning/api/schedules", json=shipment_payload).get_json()
    assert schedules["success"]
    payload = {**shipment_payload, "schedule_id": schedules["data"]["items"][0]["schedule_id"]}

    created = client.post("/planning/api/shipments", json=payload)
    assert created.status_code == 201
    shipment_id = created.get_json()["data"]["shipment_id"]

    detail = client.get(f"/shipments/{shipment_id}")
    assert detail.status_code == 200
    assert "Data Source: Mock".encode() in detail.data

    assert client.post(f"/shipments/{shipment_id}/status", data={"action": "book"}).status_code == 302
    assert client.post(f"/documents/{shipment_id}/generate").status_code == 302
    assert client.post(f"/documents/{shipment_id}/validate").status_code == 302
    assert client.get(f"/documents/{shipment_id}").status_code == 200
    assert client.get(f"/documents/{shipment_id}/commercial_invoice").status_code == 200
    assert client.get(f"/documents/{shipment_id}/shipping_instruction?edit=1").status_code == 200
    assert client.get(f"/documents/{shipment_id}/not_a_doc").status_code == 302

    for _ in range(3):
        assert client.post(f"/tracking/{shipment_id}/refresh").status_code == 302
    tracking = client.get(f"/tracking/{shipment_id}")
    assert tracking.status_code == 200 and b"Gate In" in tracking.data

    assert client.get(f"/assistant/{shipment_id}").status_code == 200
    answer = client.post(f"/assistant/{shipment_id}/api/ask", json={"question": "물류비가 왜 이렇게 나와?"}).get_json()
    # AI가 답하면 source가 ai, 키가 없거나 실패하면 규칙 기반으로 돌아갑니다.
    assert answer["success"] and answer["data"]["lines"]
    assert answer["data"]["source"] in ("ai", "rule")
    assert client.post(f"/assistant/{shipment_id}/payments", data={"preset": "logistics"}).status_code == 302
    assert client.post(f"/assistant/{shipment_id}/payments", data={
        "label": "Buyer 잔금", "direction": "in", "amount_krw": "30000000", "due_date": "2026-12-01",
    }).status_code == 302
    assert "운전자금".encode() in client.get(f"/assistant/{shipment_id}").data

    # 내 Dashboard는 로그인해야 열립니다.
    client.post("/auth/signup", data={"email": "flow@example.com", "password": "secret123",
                                      "password_confirm": "secret123"})
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200 and shipment_id.encode() in dashboard.data
