"""무작위 스윕을 테스트로 묶어 둡니다.

tests/_fuzz_*.py 는 조사할 때 크게 돌리는 도구이고, 여기서는 매번 돌 수 있게
작게 돌립니다. 새 코드를 넣다가 예외 처리를 빠뜨리면 여기서 걸립니다.

크게 돌리려면 도구를 직접 부르세요.
    python tests/_fuzz_deep.py 5000
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# 이 파일은 10분 가까이 걸립니다. 평소에는 빼고 돌리세요.
#     python -m pytest tests -m "not slow"
# 코드를 크게 고친 뒤에는 한 번씩 돌려 주세요.
#     python -m pytest tests/test_fuzz.py
pytestmark = pytest.mark.slow

HERE = Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def _restore_outbound(monkeypatch):
    """스윕이 막아 둔 바깥 연결을 테스트가 끝나면 되돌립니다.

    도구들은 block_outbound()로 httpx.request를 바꿔 끼우고 풀지 않습니다.
    그대로 두면 뒤에 도는 실제 관세청 테스트가 전부 연결 실패로 떨어집니다.
    원래 함수를 monkeypatch에 맡겨 두면 끝날 때 제자리로 돌아옵니다.
    """

    import httpx

    monkeypatch.setattr(httpx, "request", httpx.request)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_fuzz_{name}", HERE / f"_fuzz_{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_input_slot_survives_nasty_values():
    """검증기·계산기·서비스·라우트에 이상한 값을 넣어도 죽지 않아야 합니다."""

    sweep = _load("sweep")
    assert sweep.main() == 0, "예상 못 한 예외가 있습니다. 위 출력을 보세요."


def test_random_planning_payloads_survive():
    """운송 계획 전체를 무작위 입력으로 돌려 봅니다."""

    deep = _load("deep")
    assert deep.main(150) == 0


def test_document_layer_survives_nasty_forms():
    docs = _load("docs")
    assert docs.main(80) == 0


def test_broken_external_apis_and_extreme_scale():
    chaos = _load("chaos")
    assert chaos.main() == 0


@pytest.mark.parametrize("area", ["security"])
def test_no_way_out_of_the_sandbox(area):
    """올린 파일이 폴더를 벗어나거나 글이 태그로 살아나면 안 됩니다."""

    module = _load(area)
    assert module.main() == 0
