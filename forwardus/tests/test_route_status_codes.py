"""실패 사유에 맞는 상태코드를 주는가.

여태 기관 조회 라우트는 `200 if result["success"] else 502` 라고 적었습니다.
그래서 **적은 번호가 잘못된 것**(우리 잘못)도 502(기관 장애)로 나갔습니다.
화면과 감시 도구는 그걸 "관세청이 죽었다"로 읽습니다. 관세청은 멀쩡한데
우리가 잘못 적은 것이라, 고쳐야 할 곳을 엉뚱한 데서 찾게 됩니다.
전 화면을 그려 보다 /customs-filing/clearance-code 에서 찾았고, 같은 자리가
7곳이라 app/routes/__init__.py 에서 막습니다. (2026-09-26)
"""

from __future__ import annotations

import pytest

from app.routes import collector_response


@pytest.mark.parametrize("code,status", [
    ("VALIDATION_ERROR", 400),      # 우리가 잘못 적었습니다
    ("API_AUTH_FAILED", 503),       # 우리 쪽 키가 없습니다 (기관은 멀쩡)
    ("API_TIMEOUT", 502),           # 기관이 응답하지 않습니다
    ("API_ERROR", 502),
    ("", 502),
])
def test_실패_사유마다_상태코드가_다르다(app, code, status):
    with app.test_request_context("/"):
        _, got = collector_response({"success": False, "error_code": code, "message": "x"})
    assert got == status


def test_성공하면_200(app):
    with app.test_request_context("/"):
        _, got = collector_response({"success": True, "data": []})
    assert got == 200


def test_번호를_안_주면_400이지_502가_아니다(client, create_shipment):
    """입력을 안 준 것은 기관 장애가 아닙니다."""

    shipment = create_shipment()
    response = client.get(
        f"/documents/{shipment.shipment_id}/customs-filing/clearance-code")
    assert response.status_code == 400


def test_있을_수_없는_사업자등록번호도_400이다(client, create_shipment):
    shipment = create_shipment()
    response = client.get(
        f"/documents/{shipment.shipment_id}/customs-filing/clearance-code"
        "?business_no=0000000000")
    assert response.status_code == 400
    assert "있을 수 없는" in response.get_json()["message"]
