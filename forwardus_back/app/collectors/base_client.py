"""Shared HTTP helper and result normalization for external API clients."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from flask import current_app, has_app_context

from config import Config

ERROR_MESSAGES = {
    "API_TIMEOUT": "외부 데이터 조회 시간이 초과되었습니다.",
    "API_AUTH_FAILED": "외부 API 인증에 실패했습니다. API Key를 확인해주세요.",
    "API_RATE_LIMITED": "외부 API 호출 한도를 초과했습니다. 잠시 후 다시 시도해주세요.",
    "API_HTTP_ERROR": "외부 API 요청이 실패했습니다.",
    "API_SERVER_ERROR": "외부 API 서버에 일시적인 오류가 발생했습니다.",
    "API_EMPTY_RESPONSE": "외부 API 응답이 비어 있습니다.",
    "API_INVALID_RESPONSE": "외부 API 응답 형식이 올바르지 않습니다.",
    "API_MISSING_FIELD": "외부 API 응답에 필수 항목이 없습니다.",
    "API_CONNECTION_ERROR": "외부 API에 연결할 수 없습니다.",
    "MOCK_DATA_ERROR": "Mock 데이터를 불러오지 못했습니다.",
}


def ok(data: Any, source: str) -> dict:
    return {"success": True, "data": data, "source": source}


def fail(error_code: str, source: str, message: str | None = None) -> dict:
    return {
        "success": False,
        "error_code": error_code,
        "message": message or ERROR_MESSAGES.get(error_code, "외부 데이터 조회에 실패했습니다."),
        "source": source,
    }


def get_config(key: str, default: Any = None) -> Any:
    if has_app_context():
        return current_app.config.get(key, default)
    return getattr(Config, key, default)


def request_json(method: str, url: str, *, required_fields: list[str] | None = None, **kwargs) -> dict:
    """Call an external JSON API and normalize every failure mode into an error result."""

    timeout = get_config("API_TIMEOUT_SECONDS", 8)
    try:
        response = httpx.request(method, url, timeout=timeout, **kwargs)
    except httpx.TimeoutException:
        return fail("API_TIMEOUT", "api")
    except httpx.HTTPError:
        return fail("API_CONNECTION_ERROR", "api")

    if response.status_code in (401, 403):
        return fail("API_AUTH_FAILED", "api")
    if response.status_code == 429:
        return fail("API_RATE_LIMITED", "api")
    if response.status_code >= 500:
        return fail("API_SERVER_ERROR", "api")
    if response.status_code >= 400:
        return fail("API_HTTP_ERROR", "api")
    if not response.content:
        return fail("API_EMPTY_RESPONSE", "api")
    try:
        payload = response.json()
    except ValueError:
        return fail("API_INVALID_RESPONSE", "api")
    if payload in (None, [], {}):
        return fail("API_EMPTY_RESPONSE", "api")
    if required_fields:
        if not isinstance(payload, dict):
            return fail("API_INVALID_RESPONSE", "api")
        missing = [field for field in required_fields if field not in payload]
        if missing:
            return fail("API_MISSING_FIELD", "api", f"외부 API 응답에 필수 항목이 없습니다: {', '.join(missing)}")
    return ok(payload, "api")


@lru_cache(maxsize=32)
def _read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_mock(name: str) -> Any:
    """Load a JSON file from data/mock/. Results are cached per process."""

    mock_dir = Path(get_config("MOCK_DATA_DIR", Config.MOCK_DATA_DIR))
    return _read_json(str(mock_dir / f"{name}.json"))
