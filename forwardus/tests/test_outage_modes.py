"""기관이 멈추는 **세 가지 모양**에서 화면이 사는지 지킵니다.

세 가지가 서로 다릅니다
  ① 바깥이 전부 막힘   인터넷이 없습니다.            scripts/checks/cache_offline.py
  ② 키가 없거나 거부됨  기관은 살아 있습니다.          scripts/checks/keys_off.py
  ③ 기관 한 곳만 막힘   나머지는 멀쩡합니다.           scripts/checks/host_down.py

  ③ 이 실제로 가장 자주 일어납니다 — 관세청 정기점검·방화벽·DNS.
  그때 **그 기관과 무관한 조회까지 죽으면 안 됩니다.**

여기서는 전수가 아니라 **되돌아가면 바로 아는 것**만 봅니다. 전수는 위
스크립트 셋이 합니다. (2026-09-27)
"""

import socket

import httpx
import pytest

from app.collectors import base_client, customs_client, hsk_catalog

UNIPASS = "unipass.customs.go.kr"
SAVED = {"stored", "cache", "internal"}
TOP_HS = ("3304991000", "3306100000", "1902301010")


@pytest.fixture
def unipass_down(monkeypatch):
    """유니패스만 끊습니다. 나머지 기관은 그대로 씁니다."""

    real = httpx.request

    def maybe(method, url, **kwargs):
        if UNIPASS in str(url):
            raise httpx.ConnectError(f"{UNIPASS} 에 닿지 않습니다 (테스트)")
        return real(method, url, **kwargs)

    monkeypatch.setattr(httpx, "request", maybe)
    base_client.clear_outages()
    yield
    base_client.clear_outages()


@pytest.fixture
def all_down(monkeypatch):
    """바깥으로 나가는 길을 전부 끊습니다."""

    real = socket.socket

    class Blocked(socket.socket):
        def connect(self, *args, **kwargs):
            raise OSError("이 테스트에서는 바깥으로 나갈 수 없습니다")

        def connect_ex(self, *args, **kwargs):
            raise OSError("이 테스트에서는 바깥으로 나갈 수 없습니다")

    monkeypatch.setattr(socket, "socket", Blocked)
    base_client.clear_outages()
    yield
    monkeypatch.setattr(socket, "socket", real)
    base_client.clear_outages()


@pytest.fixture
def keys_off(app):
    """키를 모두 비웁니다. (해지·미발급·정지)"""

    for name in ("UNIPASS_API_KEYS", "CUSTOMS_CONFIRM_API_KEY", "DATA_GO_KR_SERVICE_KEY",
                 "OPEN_EXCHANGE_RATES_APP_ID", "AI_API_KEY", "EXCHANGE_API_KEY"):
        app.config[name] = {} if name == "UNIPASS_API_KEYS" else ""
    return app


@pytest.mark.parametrize("hs", TOP_HS)
def test_세율은_어떤_모양으로_멈춰도_나온다(app, all_down, hs):
    """세율은 돈이 걸린 값입니다. 못 내면 견적이 멈춥니다."""

    with app.app_context():
        found = customs_client.fetch_tariff_rates(hs)
    assert found["success"], f"{hs}: {found.get('message')}"
    assert found["source"] in SAVED, found["source"]
    assert any(row["code"] == "A" for row in found["data"]), "기본세율(A)이 없습니다"


def test_키가_없어도_세율과_국가코드가_나온다(keys_off, all_down):
    """키 정지는 망 단절과 다릅니다. 둘 다에서 굳혀 둔 표로 답해야 합니다."""

    with keys_off.app_context():
        rates = customs_client.fetch_tariff_rates("3306100000")
        codes = customs_client.fetch_country_codes()
    assert rates["success"] and rates["source"] in SAVED
    assert codes["success"] and codes["source"] in SAVED
    # 국가코드가 없으면 협정세율 구분명에서 나라를 못 읽어 원산지증명서가 빠집니다.
    assert len(codes["data"]) > 200, len(codes["data"])


def test_기관이_거부해도_빈_결과를_성공으로_주지_않는다(app, monkeypatch):
    """기관은 키가 정지돼도 200 에 오류문만 실어 보냅니다.

    그것을 정상 응답으로 읽으면 파서가 빈 결과를 내고, 수출요건이라면 화면에
    "해당 자료가 없다" — 곧 **"규제 없음"**으로 읽힙니다. 키가 정지된 것인데요.
    """

    refusal = "<trrtQryRtnVo><ntceInfo>등록되지 않은 인증키입니다.</ntceInfo></trrtQryRtnVo>"
    assert base_client.auth_refused(refusal), "인증 거부를 알아보지 못합니다"
    assert not base_client.auth_refused("<trrtQryRtnVo><trrtQryRsltVo/></trrtQryRtnVo>")

    class Refused:
        status_code = 200
        text = refusal
        content = refusal.encode("utf-8")

        def raise_for_status(self):
            return None

    monkeypatch.setattr(httpx, "request", lambda *a, **k: Refused())
    base_client.clear_outages()
    try:
        with app.app_context():
            got = base_client.request_text("GET", "https://unipass.customs.go.kr/x")
    finally:
        base_client.clear_outages()
    assert got["success"] is False, "인증 거부를 성공으로 읽습니다"
    assert got["error_code"] == "API_AUTH_FAILED"


def test_유니패스만_막혀도_무관한_것은_멀쩡하다(app, unipass_down):
    """한 기관이 막혔다고 화면이 통째로 멈추면 안 됩니다.

    품목표·표준품명·통화 목록은 바깥을 부르지 않습니다.
    """

    with app.app_context():
        rows = hsk_catalog.search("신선마늘(육쪽)") or []
        from app.collectors import exchange_client
        currencies = exchange_client.currency_options()
    assert rows, "유니패스가 막혔다고 품목표 찾기가 죽습니다"
    assert rows[0].get("std_kind") == "표준품명", rows[0].get("std_kind")
    assert currencies, "통화 목록이 바깥에 매여 있습니다"


def test_세율_출처를_그대로_물려준다(app, all_down):
    """tariff_guide 가 "api" 라고 못 박으면 저장분을 방금 받은 값으로 보여 줍니다."""

    from app.services import planning_service

    with app.app_context():
        guide = planning_service.tariff_guide("3306100000", "TR")
    if not guide.get("available"):
        pytest.skip("세율을 못 얻어 견줄 수 없습니다")
    assert guide["source"] in SAVED, guide["source"]
    # 협정을 찾으려면 국가코드표가 있어야 합니다. 함께 지켜집니다.
    assert guide.get("agreements"), "저장분으로는 협정을 못 찾습니다"
