"""받아 둔 값을 "방금 기관에서 받았다"고 말하지 않는지 지킵니다.

왜 이 테스트가 있나
  이 프로젝트에서 source == "api" 는 **방금 기관에서 받았다**는 뜻입니다.
  lookup_service._probe 가 그것으로 "응답함"을 판단하고, planning_service 도
  api 일 때만 실데이터로 씁니다.

  그런데 받아 둔 파일에서 꺼내면서 "api" 라고 적는 곳이 아홉 군데 있었습니다.
    - trade_stats_client.top_destinations  조회를 안 하고 item_trade 결과를
      더하기만 하는데 "api" 로 못 박았습니다.
    - ksure_client.payment_info           캐시를 읽고 "api" 라 적었습니다.
      (같은 함수 아래쪽 폴백은 "cache" 라고 바르게 적고 있었습니다)
    - exchange_client                     파일에서 꺼낸 것을 "market"
      (= "실제 시장 환율로 환산") 이라 적었습니다.

  며칠 전 값을 최신이라고 화면에 내보내면, 사용자는 그 값으로 신고합니다.
  (2026-09-27 scripts/checks/cache_offline.py 가 찾았습니다)

전수 확인은 scripts/checks/cache_offline.py 가 47가지로 합니다.
여기서는 **다시 그렇게 되면 바로 아는 것**만 봅니다.
"""

import socket

import pytest

from app.collectors import base_client, exchange_client, ksure_client, trade_stats_client

# 받아 둔 값을 뜻하는 출처. snapshot 은 "stored", file_cache 를 직접 쓰는 곳은
# "cache", 품목표처럼 원래 로컬인 것은 "internal" 입니다.
SAVED = {"stored", "cache", "internal"}


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
        # 소켓을 막으면 base_client 가 "이 기관은 닿지 않는다"고 기억합니다.
        # 지우지 않으면 뒤따르는 테스트의 진짜 호출이 로컬에서 거부됩니다.
        base_client.clear_outages()


def test_받아_둔_값을_방금_받았다고_말하지_않는다(app, no_network):
    """저장분으로 답할 때는 source 가 "api" 가 아니어야 합니다.

    키와 받아 둔 파일을 **둘 다** 심습니다. 키가 없으면 각 함수가 캐시를
    읽기 전에 "키 없음"으로 돌아서므로, 고친 것을 되돌려도 테스트가 통과합니다.
    (실제로 그랬습니다 — 키를 심기 전에는 아무것도 지키지 못했습니다)
    소켓은 막혀 있으니 바깥으로 나가지는 않습니다.
    """

    from app.collectors import file_cache, snapshot

    app.config["OPEN_EXCHANGE_RATES_APP_ID"] = "test-only-not-a-real-key"
    app.config["DATA_GO_KR_SERVICE_KEY"] = "test-only-not-a-real-key"
    with app.app_context():
        file_cache.write("fx_oxr_latest", {"rates": {"KRW": 1390.0, "JPY": 150.0}})
        file_cache.write("ksure_payment_all", {"rows": [{"country": "미국"}]})
        file_cache.write(snapshot._key("item_trade_3304_"), {"data": {
            "from": "202401", "to": "202412", "rows": [{
                "country": "미국", "country_code": "US", "product": "화장품",
                "hs_code": "3304", "export_usd_thousand": 1000,
                "export_weight_kg": 10, "import_usd_thousand": 0,
                "import_weight_kg": 0}]}, "extra": {}})
        exchange_client.clear_cache()
        checks = {
            "수출 상대국": lambda: trade_stats_client.top_destinations("3304"),
            "결제정보": lambda: ksure_client.payment_info("US"),
            "고시환율": exchange_client.fetch_krw_rates,
        }
        lied = []
        for label, call in checks.items():
            found = call() or {}
            if found.get("success") and found.get("source") == "api":
                lied.append(label)
    assert lied == [], f"망을 끊었는데 'api'라고 적습니다: {lied}"


def test_더한_값은_원래_출처를_물려받는다(app, no_network):
    """top_destinations 는 item_trade 의 출처를 그대로 써야 합니다.

    이 함수는 조회를 하지 않습니다. item_trade 가 준 줄을 나라별로 더하기만
    합니다. 그러니 출처도 그대로 물려받는 것이 맞습니다.

    받아 둔 실적을 **직접 심습니다.** 실제 캐시에 기대면 시험 설정에서는
    캐시 폴더가 임시 폴더라(conftest) 늘 건너뛰게 되어 아무것도 못 지킵니다.
    """

    from app.collectors import file_cache, snapshot

    with app.app_context():
        file_cache.write(snapshot._key("item_trade_3304_"), {"data": {
            "from": "202401", "to": "202412", "rows": [{
                "country": "미국", "country_code": "US", "product": "화장품",
                "hs_code": "3304", "export_usd_thousand": 1000,
                "export_weight_kg": 10, "import_usd_thousand": 0,
                "import_weight_kg": 0}]}, "extra": {}})
        base = trade_stats_client.item_trade("3304")
        rolled = trade_stats_client.top_destinations("3304")

    assert base["success"] and base["source"] == "stored", base
    assert rolled["success"], rolled
    assert rolled["source"] == base["source"], (
        f"item_trade 는 {base['source']} 인데 top_destinations 는 {rolled['source']} 입니다")


def test_저장해_둔_환율을_다시_저장해_날짜를_새로_찍지_않는다(app, no_network):
    """파일에서 꺼낸 환율은 다시 저장하지 않아야 합니다.

    다시 저장하면 saved_date 가 오늘로 찍혀 STORED_MAX_DAYS(30일)가 영영
    오지 않습니다. 한 달 지난 환율이 계속 "0일 전"으로 보였습니다.
    """

    from app.collectors import file_cache

    old_date = "2026-09-01"
    # 시험 설정은 바깥 키가 전부 비어 있습니다. 그런데 이 버그는 **시장 환율
    # 갈래**에서만 납니다(_from_open_exchange_rates). 키가 없으면 그 갈래에
    # 들어가지도 않아, 고친 것을 되돌려도 테스트가 통과했습니다.
    # 그래서 키가 있는 것으로 해 둡니다. 소켓은 막혀 있으니 바깥으로는
    # 나가지 않고, 심어 둔 fx_oxr_latest 파일을 읽습니다.
    app.config["OPEN_EXCHANGE_RATES_APP_ID"] = "test-only-not-a-real-key"
    with app.app_context():
        # 시장 시세표와 마지막 실환율을 둘 다 심습니다. 시장 시세표가 있으면
        # exchange_client 가 그것으로 답하는데, 그때 다시 저장하면 안 됩니다.
        file_cache.write("fx_oxr_latest", {"rates": {"KRW": 1390.0, "JPY": 150.0}})
        file_cache.write(exchange_client.LAST_GOOD_FILE, {
            "krw_per_unit": {"USD": 1380.0, "KRW": 1.0},
            "applied_date": old_date, "origin": "customs", "saved_date": old_date})

        # 기억해 둔 환율을 버립니다. 이것을 안 하면 앞 테스트가 불러 둔 값이
        # 그대로 돌아와 _read_krw_rates 가 아예 돌지 않고, 테스트가 아무것도
        # 지키지 못합니다. (고친 것을 일부러 되돌려도 통과했습니다)
        exchange_client.clear_cache()
        exchange_client.fetch_krw_rates()
        after = file_cache.read(exchange_client.LAST_GOOD_FILE)

    assert after, "저장해 둔 환율이 사라졌습니다"
    assert after[0].get("saved_date") == old_date, (
        f"saved_date 가 {after[0].get('saved_date')} 로 새로 찍혔습니다. "
        "낡은 환율이 계속 '0일 전'으로 보입니다")


def test_진단_화면이_받아_둔_값을_예시라고_말하지_않는다(app):
    """lookup_service 의 상태 글이 stored·cache 를 예시로 찍으면 안 됩니다.

    전에는 이 셋이 전부 "예시 데이터로 대체"였습니다. 실제로 받아 낸 값인데
    예시라고 말하면, 보는 사람이 기관 연동이 안 되는 줄로 압니다.
    """

    from app.services import lookup_service

    with app.app_context():
        for source in SAVED | {"market"}:
            row = lookup_service._probe(
                "시험", "NONE", lambda s=source: {"success": True, "source": s, "data": [1]})
            assert "예시" not in row["state"], f"{source} → {row['state']}"
            # 받아 둔 값은 "지금 응답함"도 아닙니다.
            if source != "internal":
                assert row["ok"] is False, f"{source} 를 지금 응답한 것으로 봅니다"
