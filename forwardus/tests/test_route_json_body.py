"""JSON 본문이 객체가 아닐 때 **500 이 나면 안 됩니다.**

여태 라우트마다 `request.get_json(silent=True) or {}` 라고 적었습니다.
본문이 `12345` 나 `"글자"` 로 오면 `or {}` 가 듣지 않아(숫자·글자는 참입니다)
그대로 서비스로 넘어갔고, 거기서 `payload.get(...)` 이 AttributeError 로
터졌습니다. 이용자에게는 500 만 가고 무엇이 잘못됐는지 한마디도 없습니다.
흔들어 보니 /planning/api/schedules 와 /planning/api/departure-check 에서
실제로 났습니다. 같은 자리가 21곳이라 app/routes/__init__.py 에서 막습니다.
(2026-09-26)
"""

from __future__ import annotations

import pytest

from app.routes import json_body


NOT_OBJECTS = [12345, "글자", [], [1, 2, 3], True, 3.14, None]


@pytest.mark.parametrize("body", NOT_OBJECTS)
@pytest.mark.parametrize("path", [
    "/planning/api/schedules",
    "/planning/api/departure-check",
    "/planning/api/cargo",
    "/planning/api/shipments",
])
def test_객체가_아닌_본문에도_500이_나지_않는다(client, path, body):
    response = client.post(path, json=body)
    assert response.status_code < 500, response.get_data(as_text=True)[:300]


@pytest.mark.parametrize("body", NOT_OBJECTS)
def test_json_body는_언제나_dict를_돌려준다(app, body):
    with app.test_request_context("/", json=body):
        assert json_body() == {}


def test_제대로_된_본문은_그대로_온다(app):
    with app.test_request_context("/", json={"a": 1}):
        assert json_body() == {"a": 1}
