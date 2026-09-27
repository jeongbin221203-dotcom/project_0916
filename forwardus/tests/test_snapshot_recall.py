"""받아 둔 값을 **기관이 막혔을 때 꺼내 쓰는가.**

저장(remember)만 하고 꺼내 보는(recall) 곳이 없으면, 파일에 남겨 두고도
기관이 죽으면 빈손으로 답합니다. 실제로 간이정액 환급율과 수출이행기간
단축품목이 그랬습니다 — 같은 파일의 다른 조회는 다 꺼내 보는데 이 둘만
빠져 있었습니다. (2026-09-27 저장분으로 답하는지 확인하다 찾음)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COLLECTORS = sorted((ROOT / "app" / "collectors").glob("*_client.py"))


def _names(text: str, call: str) -> set[str]:
    """snapshot.remember("x_...") / recall("x_...") 의 이름 앞머리를 모읍니다."""

    return {match.group(1) for match in
            re.finditer(rf'snapshot\.{call}\(\s*f?"([a-z_]+?)_?\{{', text)}


@pytest.mark.parametrize("path", COLLECTORS, ids=lambda p: p.name)
def test_저장하는_것은_꺼내_쓰기도_한다(path):
    text = path.read_text(encoding="utf-8")
    kept = _names(text, "remember")
    if not kept:
        pytest.skip("이 파일은 저장하지 않습니다")
    recalled = _names(text, "recall")
    forgotten = sorted(kept - recalled)
    assert not forgotten, (
        f"{path.name}: {forgotten} 는 저장만 하고 꺼내 보지 않습니다. "
        "기관이 막히면 받아 둔 값이 있어도 빈손으로 답합니다.")


def test_기관이_막혀도_받아_둔_값으로_답한다(app, monkeypatch, tmp_path):
    """저장해 둔 것이 있으면 꺼내 옵니다."""

    from app.collectors import file_cache, snapshot

    monkeypatch.setattr(file_cache, "cache_dir", lambda: tmp_path)
    snapshot.remember("refund_rate_3306100000",
                      {"success": True, "source": "api",
                       "data": [{"hs_code": "3306100000", "amount_krw": "12"}]})

    from app.collectors import base_client, customs_extra_client
    monkeypatch.setattr(base_client, "request_text", lambda *a, **k: {
        "success": False, "error_code": "API_TIMEOUT", "source": "api",
        "message": "기관이 응답하지 않습니다."})

    found = customs_extra_client.refund_rate("3306100000")
    assert found["success"], "저장해 둔 값이 있는데 빈손으로 답합니다"
    assert found["source"] == "stored", "어디서 온 값인지 밝혀야 합니다"
    assert found["data"]


def test_저장해_둔_것이_없으면_없다고_한다(app, monkeypatch, tmp_path):
    """지어내지 않습니다."""

    from app.collectors import base_client, customs_extra_client, file_cache

    monkeypatch.setattr(file_cache, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(base_client, "request_text", lambda *a, **k: {
        "success": False, "error_code": "API_TIMEOUT", "source": "api",
        "message": "기관이 응답하지 않습니다."})

    found = customs_extra_client.refund_rate("9999999999")
    assert not found["success"]
