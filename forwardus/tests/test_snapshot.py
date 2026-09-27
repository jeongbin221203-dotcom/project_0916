"""기관이 막혔을 때 지난번에 받아 둔 값으로 답하는지 봅니다.

왜 필요한가
  2026-09-25 관세청 UNI-PASS가 통째로 닿지 않았습니다. 선사 목록·항공사 목록·
  걸리는 법령이 모두 빈 채로 나왔습니다. 어제까지 잘 받아 둔 값이 있었는데도
  서버를 다시 켜면 그마저 사라집니다.

  지어낸 값을 보여 주자는 것이 아닙니다. **실제로 받았던 값**을 언제 받은
  것인지와 함께 보여 주자는 것입니다.
"""

from __future__ import annotations

import pytest

from app.collectors import snapshot


@pytest.fixture(autouse=True)
def _store(monkeypatch):
    """파일 대신 메모리에 담습니다. 나이(일)는 테스트가 정합니다."""

    kept: dict = {}
    age = {"days": 0.0}
    monkeypatch.setattr(snapshot.file_cache, "write", lambda name, data: kept.__setitem__(name, data))
    monkeypatch.setattr(snapshot.file_cache, "read",
                        lambda name: (kept[name], age["days"]) if name in kept else None)
    return age


def test_받아_낸_답만_남긴다(_store):
    """예시나 내부 표를 남기면 그것이 다시 '실제로 받았던 값'인 척하게 됩니다."""

    snapshot.remember("ships_한진", {"success": True, "source": "mock", "data": [{"code": "HJSC"}]})
    snapshot.remember("ships_한진", {"success": True, "source": "internal", "data": [{"code": "HJSC"}]})
    snapshot.remember("ships_한진", {"success": False, "source": "api", "data": None})
    assert snapshot.recall("ships_한진", "registry") is None

    snapshot.remember("ships_한진", {"success": True, "source": "api", "data": [{"code": "HJSC"}]})
    assert snapshot.recall("ships_한진", "registry")["data"] == [{"code": "HJSC"}]


def test_빈_답은_남기지_않는다(_store):
    """'못 찾음'을 저장해 두면 나중에 찾을 수 있을 때도 못 찾습니다."""

    for empty in ([], {}, "", None):
        snapshot.remember("x", {"success": True, "source": "api", "data": empty})
    assert snapshot.recall("x") is None


def test_며칠_전_값인지_함께_알려_준다(_store):
    snapshot.remember("ships_한진", {"success": True, "source": "api", "data": [{"code": "HJSC"}]})
    _store["days"] = 12.4

    got = snapshot.recall("ships_한진", "registry")
    assert got["source"] == "stored"          # "api"와 같이 다루면 안 됩니다
    assert got["stored_days"] == 12
    assert "12일 전에 받아 둔 값" in got["stored_note"]


def test_너무_오래된_것은_쓰지_않는다(_store):
    snapshot.remember("port", {"success": True, "source": "api", "data": [{"t": 1}]})

    _store["days"] = 44
    assert snapshot.recall("port", "stats") is not None      # 통계는 45일까지
    _store["days"] = 46
    assert snapshot.recall("port", "stats") is None

    _store["days"] = 100
    assert snapshot.recall("port", "registry") is not None   # 등록부는 180일까지
    assert snapshot.recall("port") is None                   # 종류를 안 적으면 30일


def test_곁들인_값도_함께_남는다(_store):
    """적용일 같은 것이 빠지면 화면이 '언제 기준'인지 못 적습니다."""

    snapshot.remember("laws_3306100000_1", {"success": True, "source": "api",
                                            "data": [{"law_name": "약사법"}],
                                            "base_date": "2026-01-01"})
    assert snapshot.recall("laws_3306100000_1", "law")["base_date"] == "2026-01-01"


def test_이름에_이상한_글자가_있어도_담긴다(_store):
    """선사 이름·HS부호가 그대로 파일 이름이 됩니다. 경로를 벗어나면 안 됩니다."""

    snapshot.remember("ships_../../etc/passwd", {"success": True, "source": "api", "data": [1]})
    assert "/" not in snapshot._key("ships_../../etc/passwd")
    assert ".." not in snapshot._key("ships_../../etc/passwd")
    assert snapshot.recall("ships_../../etc/passwd", "registry")["data"] == [1]


def test_화물_추적은_저장하지_않는다():
    """어제 '부산 출항'이었다고 오늘도 그렇게 답하면 거짓말이 됩니다.

    움직이는 값은 못 받으면 못 받았다고 해야 합니다. 추적 쪽 코드가 저장 층을
    가져다 쓰기 시작하면 이 테스트가 막습니다.
    """

    import inspect

    from app.collectors import container_client, tracking_client

    for module in (container_client, tracking_client):
        source = inspect.getsource(module)
        assert "snapshot" not in source, module.__name__
