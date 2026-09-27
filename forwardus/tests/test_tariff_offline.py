"""관세청 관세율표를 굳혀 둔 내부 표를 지킵니다.

왜 굳혔나
  세율은 **돈이 걸린 값**입니다. UNI-PASS 관세율 조회는 키가 있어야 하고 기관이
  멈추면 빈손이었습니다. 관세청이 공공데이터포털에 파일로 내놓는 표
  (관세청_품목번호별 관세율표 · 공공누리 제1유형)를 data/build_tariff.py 로
  굳혀 두면 **키 없이도, 기관이 멈춰도** 답합니다. (2026-09-27)

굳히다가 찾은 것
  우리가 적어 둔 HSK 세 개가 **존재하지 않는 부호**였습니다.
    3304990000 · 8507600000 · 8708299000
  기관이 "조회된 관세율 정보가 없습니다"로 답한 것이 맞았는데, 우리는 그것을
  "기관 미등재"로 적어 두고 발표 자료에까지 옮겼습니다.
  실제 부호는 3304991000 · 8507602000 · 8708290000 입니다.
"""

import json
import socket
from pathlib import Path

import pytest

from app.collectors import base_client, customs_client

TABLE_PATH = Path(__file__).resolve().parents[1] / "data" / "mock" / "tariff_rates.json"

# 우리나라 수출 상위 품목. prime_cache_capped.py 의 TOP_HS 와 같아야 합니다.
TOP_HS = ("3304991000", "8507602000", "3306100000", "1902301010", "8708290000")

# 전에 잘못 적어 두었던 부호. 다시 새어 들어오면 여기서 걸립니다.
WRONG_HS = ("3304990000", "8507600000", "8708299000")


@pytest.fixture
def no_network():
    """바깥으로 나가는 길을 끊습니다. 진짜 기관이 멈춘 것과 같아집니다."""

    real = socket.socket

    class Blocked(socket.socket):
        def connect(self, *args, **kwargs):
            raise OSError("이 테스트에서는 바깥으로 나갈 수 없습니다")

        def connect_ex(self, *args, **kwargs):
            raise OSError("이 테스트에서는 바깥으로 나갈 수 없습니다")

    socket.socket = Blocked
    try:
        yield
    finally:
        socket.socket = real
        base_client.clear_outages()


@pytest.fixture(scope="module")
def table():
    if not TABLE_PATH.exists():
        pytest.skip("data/mock/tariff_rates.json 이 없습니다. python data/build_tariff.py 로 만드세요")
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))


def test_표가_전_품목을_덮는다(table):
    """품목표에 있는 부호는 거의 모두 세율이 있어야 합니다."""

    catalog = json.loads(
        (TABLE_PATH.parent / "hsk_codes.json").read_text(encoding="utf-8"))["codes"]
    missing = [code for code in catalog if code not in table["codes"]]
    assert len(missing) <= 5, f"세율이 없는 부호가 {len(missing):,}개입니다: {missing[:10]}"
    assert table["count"] >= 10_000, table["count"]


def test_출처와_이용허락을_적어_둔다(table):
    """남의 자료를 쓰는 것이니 출처와 이용조건을 파일 안에 남깁니다."""

    assert "관세청" in table["source"]
    assert "공공누리" in table["license"]
    assert table["url"].startswith("https://www.data.go.kr/")
    assert table["base_date"], "기준일이 비어 있으면 언제 자료인지 알 수 없습니다"


@pytest.mark.parametrize("hs", TOP_HS)
def test_기관이_멈춰도_세율이_나온다(app, no_network, hs):
    """키·기관 없이도 세율이 나와야 합니다. 못 내면 견적이 멈춥니다."""

    with app.app_context():
        found = customs_client.fetch_tariff_rates(hs)
    assert found["success"], f"{hs}: {found.get('message')}"
    assert found["source"] in ("internal", "stored"), found["source"]
    rates = {row["code"]: row["rate"] for row in found["data"]}
    assert "A" in rates, f"{hs}: 기본세율(A)이 없습니다"


def test_내부_표로_답할_때는_방금_받은_값이라_하지_않는다(app, no_network):
    """출처는 "internal" 이고, 기준일을 함께 알려야 합니다."""

    with app.app_context():
        found = customs_client.tariff_rates_offline("3304991000")
    assert found and found["source"] == "internal"
    assert found["base_date"] in found["message"]
    assert "확인" in found["message"], "신고 전에 확인하라는 말이 있어야 합니다"


@pytest.mark.parametrize("hs", WRONG_HS)
def test_없는_부호는_없다고_말한다(app, no_network, hs):
    """존재하지 않는 HSK 로는 세율을 지어내지 않아야 합니다.

    전에 우리가 이 셋을 적어 두고 기관 탓으로 돌렸습니다. 내부 표가 생겼다고
    없는 부호에 아무 세율이나 붙이면 더 나쁩니다.
    """

    with app.app_context():
        assert customs_client.tariff_rates_offline(hs) is None


def test_협정세율이_들어_있다(app, no_network):
    """FTA 협정세율이 있어야 도착국별 세율을 보여 줄 수 있습니다."""

    with app.app_context():
        found = customs_client.fetch_tariff_rates("3306100000")
    kinds = {row["code"] for row in found["data"]}
    # FUS1 한-미 · FEU1 한-EU · FCN1 한-중
    assert {"FUS1", "FEU1", "FCN1"} <= kinds, sorted(kinds)


def test_적용기간이_모든_줄에_있다(app, no_network):
    """압축해 담을 때 적용기간을 한 번만 적었습니다. 펼칠 때 되살아나야 합니다."""

    with app.app_context():
        found = customs_client.tariff_rates_offline("3306100000")
    for row in found["data"]:
        assert row["start_date"] and row["end_date"], row
