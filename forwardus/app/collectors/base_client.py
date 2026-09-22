"""Shared HTTP helper and result normalization for external API clients."""

from __future__ import annotations

import json
import threading
import time
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
    "API_NOT_FOUND": "외부 API에 해당 자료가 없습니다.",
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


# --- 닿지 않는 기관을 매번 다시 기다리지 않습니다 ---------------------------------
#
# 관세청이 회선에서 막히면 한 번 부를 때마다 8초를 버립니다. HS 검색은 한 번에
# 여덟 번을 부르므로 화면이 30초를 기다리다 끊겼습니다.
#
# 그래서 닿지 않은 기관은 잠시 부르지 않고 바로 "안 됩니다"로 답합니다.
# 어느 기관을 왜 건너뛰는지 메시지에 적으므로 조용히 사라지지 않습니다.
# 수집기마다 되돌아갈 길(내부 품목표·예시 자료)이 이미 있어서, 답이 빨라질 뿐
# 틀려지지는 않습니다.
#
# 건너뛰는 것은 **닿지 않을 때**뿐입니다. 404나 500처럼 응답이 온 경우는
# 기관이 살아 있다는 뜻이라 세지 않고, 바로 잊습니다.
UNREACHABLE = ("API_TIMEOUT", "API_CONNECTION_ERROR")

_outage_lock = threading.Lock()
_unreachable_until: dict[str, float] = {}


def _host(url: str) -> str:
    return url.split("/")[2] if "://" in url else url


def clear_outages() -> None:
    """건너뛰기 기록을 모두 지웁니다. (테스트와 회선이 돌아왔을 때)"""

    with _outage_lock:
        _unreachable_until.clear()


def _skip_seconds(host: str) -> float:
    """이 기관을 앞으로 몇 초 더 건너뛰는지. 0이면 불러도 됩니다."""

    with _outage_lock:
        return max(0.0, _unreachable_until.get(host, 0.0) - time.monotonic())


def _remember_reach(host: str, error_code: str | None) -> None:
    with _outage_lock:
        if error_code not in UNREACHABLE:
            _unreachable_until.pop(host, None)     # 응답이 왔습니다. 살아 있습니다.
            return
        seconds = float(get_config("API_OUTAGE_SECONDS", 60))
        if seconds > 0:
            _unreachable_until[host] = time.monotonic() + seconds


def request_text(method: str, url: str, **kwargs) -> dict:
    """Call an external API that answers with text (XML 등) and normalize failures."""

    response = _request(method, url, **kwargs)
    if isinstance(response, dict):
        return response
    return ok(response.text, "api")


def _request(method: str, url: str, **kwargs):
    """Perform the call and map every failure mode to an error result."""

    host = _host(url)
    skipping = _skip_seconds(host)
    if skipping:
        return fail("API_CONNECTION_ERROR", "api",
                    f"{host}에 닿지 않아 {int(skipping) + 1}초 동안 부르지 않습니다. "
                    f"그동안은 가지고 있는 자료로 답합니다.")

    # 느린 외부 API(WITS 등)는 호출하는 쪽에서 더 긴 시간을 줄 수 있습니다.
    timeout = kwargs.pop("timeout", None) or get_config("API_TIMEOUT_SECONDS", 8)
    try:
        response = httpx.request(method, url, timeout=timeout, **kwargs)
    except httpx.TimeoutException:
        _remember_reach(host, "API_TIMEOUT")
        return fail("API_TIMEOUT", "api")
    except httpx.HTTPError:
        _remember_reach(host, "API_CONNECTION_ERROR")
        return fail("API_CONNECTION_ERROR", "api")
    _remember_reach(host, None)

    if response.status_code in (401, 403):
        return fail("API_AUTH_FAILED", "api")
    if response.status_code == 429:
        return fail("API_RATE_LIMITED", "api")
    if response.status_code >= 500:
        return fail("API_SERVER_ERROR", "api")
    if response.status_code == 404:
        return fail("API_NOT_FOUND", "api")
    if response.status_code >= 400:
        return fail("API_HTTP_ERROR", "api")
    if not response.content:
        return fail("API_EMPTY_RESPONSE", "api")
    return response


def request_json(method: str, url: str, *, required_fields: list[str] | None = None, **kwargs) -> dict:
    """Call an external JSON API and normalize every failure mode into an error result."""

    response = _request(method, url, **kwargs)
    if isinstance(response, dict):
        return response
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
def _read_json(path: str, mtime: float) -> Any:
    """``mtime`` is part of the cache key so edited data is picked up."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_mock(name: str) -> Any:
    """Load a JSON file from data/mock/.

    Results are cached per process, but the cache key includes the file's
    modification time, so rebuilding the data does not need a server restart.
    """

    mock_dir = Path(get_config("MOCK_DATA_DIR", Config.MOCK_DATA_DIR))
    path = mock_dir / f"{name}.json"
    return _read_json(str(path), path.stat().st_mtime)
