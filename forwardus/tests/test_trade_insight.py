"""메인 무역 상담의 데이터 도구 — 관세청 국가별 수출 실적 · 무역보험공사 수출결제정보.

외부 API는 부르지 않습니다. 실제 응답 모양(2026-09 확인)을 그대로 흉내 냅니다.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.collectors import ai_client, file_cache, ksure_client, trade_stats_client
from app.services import support_chat_service
from app.services import trade_insight_service as insight


@pytest.fixture(autouse=True)
def _memory_cache(monkeypatch):
    """받아 둔 파일을 쓰지도 남기지도 않습니다."""

    store = {}
    monkeypatch.setattr(file_cache, "read", lambda name: (store[name], 0.0) if name in store else None)
    monkeypatch.setattr(file_cache, "write", lambda name, data: store.__setitem__(name, data))
    return store


@pytest.fixture
def keyed(monkeypatch):
    real = trade_stats_client.get_config

    def config(name, default=None):
        return "test-key" if name == "DATA_GO_KR_SERVICE_KEY" else real(name, default)

    for module in (trade_stats_client, ksure_client):
        monkeypatch.setattr(module, "get_config", config)
    # 결제 통계는 따로 흉내 내지 않은 테스트에서는 "데이터 없음"입니다. 밖으로 나가지 않습니다.
    monkeypatch.setattr(ksure_client, "request_text", _ksure({})[0])


# --- 관세청 ----------------------------------------------------------------------

def _customs_row(month, iso, name, usd, hs="610910"):
    return {"year": month, "statCd": iso, "statCdCntnKor1": name, "hsCd": hs,
            "statKor": "티셔츠", "expDlr": str(usd), "expWgt": "10", "impDlr": "0", "impWgt": "0"}


def _customs(data_by_period):
    """(start, end) → 그 기간의 줄. 총계 줄을 맨 앞에 붙입니다. (실제 응답과 같은 모양)"""

    calls = []

    def fake_call(url, params, label):
        calls.append(params)
        rows = data_by_period.get((params["hsSgn"], params["strtYymm"], params["endYymm"]), [])
        total = sum(int(row["expDlr"]) for row in rows)
        head = [{"year": "총계", "statCd": "-", "statCdCntnKor1": "-", "hsCd": "-",
                 "expDlr": str(total)}] if rows else []
        return {"success": True, "source": "api", "data": head + rows}

    return fake_call, calls


def test_나라별로_달을_더하고_금액은_달러다(app, keyed, monkeypatch):
    fake, _ = _customs({("6109", "202501", "202512"): [
        _customs_row("2025.01", "US", "미국", 100), _customs_row("2025.02", "US", "미국", 50),
        _customs_row("2025.01", "VN", "베트남", 30)]})
    monkeypatch.setattr(trade_stats_client, "_call", fake)

    with app.app_context():
        data = trade_stats_client.exports_by_country("6109", "202501", "202512")["data"]

    assert data["countries"]["US"]["export_usd"] == 150
    assert data["total_export_usd"] == 180
    assert data["last_month"] == "2025.02"


def test_올해는_같은_달까지만_지난해와_견준다(app, keyed, monkeypatch):
    year = date.today().year
    fake, calls = _customs({
        ("6109", f"{year}01", f"{year}12"): [_customs_row(f"{year}.08", "US", "미국", 300),
                                             _customs_row(f"{year}.03", "VN", "베트남", 100)],
        ("6109", f"{year - 1}01", f"{year - 1}08"): [_customs_row(f"{year - 1}.05", "US", "미국", 200),
                                                     _customs_row(f"{year - 1}.05", "VN", "베트남", 100)],
    })
    monkeypatch.setattr(trade_stats_client, "_call", fake)

    with app.app_context():
        result = insight.fetch_customs_export_stats("티셔츠", target_year=year, hs_codes=["6109"])

    assert result["success"] and result["partial_year"] is True
    assert result["period"] == f"{year}년 1~8월"
    assert result["compare_period"] == f"{year - 1}년 1~8월"
    # 지난해는 1~8월만 부릅니다. 12개월과 견주면 모두 역성장으로 보입니다.
    assert calls[-1]["endYymm"] == f"{year - 1}08"
    us, vn = result["top_countries"]
    assert (us["country"], us["export_usd"], us["yoy_pct"], us["share_pct"]) == ("미국", 300, 50.0, 75.0)
    assert us["export_usd_text"] == "300달러" and us["yoy_text"] == "+50.0%"
    assert vn["yoy_text"] == "+0.0%"
    assert result["total_yoy_pct"] == pytest.approx(33.3)


def test_작은_시장의_폭증은_성장국으로_꼽지_않는다(app, keyed, monkeypatch):
    fake, _ = _customs({
        ("6109", "202501", "202512"): [_customs_row("2025.12", "US", "미국", 90_000_000),
                                       _customs_row("2025.12", "TW", "대만", 9_000_000),
                                       _customs_row("2025.12", "LY", "리비아", 800_000)],
        ("6109", "202401", "202412"): [_customs_row("2024.12", "US", "미국", 100_000_000),
                                       _customs_row("2024.12", "TW", "대만", 6_000_000),
                                       _customs_row("2024.12", "LY", "리비아", 4_000)],
    })
    monkeypatch.setattr(trade_stats_client, "_call", fake)

    with app.app_context():
        result = insight.fetch_customs_export_stats("티셔츠", target_year=2025, hs_codes=["6109"])

    assert [row["country"] for row in result["fastest_growing"]] == ["대만"]
    assert result["top_countries"][0]["export_usd_text"] == "9,000만 달러"


def test_여러_류를_더하고_없는_부호는_버린다(app, keyed, monkeypatch):
    fake, calls = _customs({
        ("61", "202501", "202512"): [_customs_row("2025.12", "US", "미국", 100, "6109")],
        ("62", "202501", "202512"): [_customs_row("2025.12", "US", "미국", 50, "6203")],
    })
    monkeypatch.setattr(trade_stats_client, "_call", fake)

    with app.app_context():
        result = insight.fetch_customs_export_stats("의류", target_year=2025,
                                                    hs_codes=["61", "62", "9999"])

    assert [row["hs_code"] for row in result["hs_codes"]] == ["61", "62"]
    assert result["rejected_hs_codes"] == ["9999"]
    assert result["top_countries"][0]["export_usd"] == 150


def test_부호가_없으면_품목표에서_품명으로_찾는다(app, keyed, monkeypatch):
    fake, calls = _customs({("3304", "202501", "202512"): [_customs_row("2025.12", "US", "미국", 1, "3304")]})
    monkeypatch.setattr(trade_stats_client, "_call", fake)

    with app.app_context():
        result = insight.fetch_customs_export_stats("립스틱", target_year=2025)

    assert result["hs_codes"][0]["hs_code"] == "3304"
    assert "품목표" in result["hs_basis"]


def test_키가_없거나_못_찾으면_지어내지_않고_이유를_돌려준다(app, monkeypatch):
    monkeypatch.setattr(trade_stats_client, "available", lambda: False)
    with app.app_context():
        result = insight.fetch_customs_export_stats("의류")
    assert result["success"] is False and "DATA_GO_KR_SERVICE_KEY" in result["message"]


# --- 무역보험공사 ------------------------------------------------------------------

def _ksure_item(late=(20.8, 22.9), days=(57.1, 57.4), lc=21.2, oa=67.8, long_tail=2.5):
    series = lambda values: [{"YEAR": str(2024 + i), "VALUE": v} for i, v in enumerate(values)]
    return {
        "lastUpdateDate": "2026.01.01", "yearList": [2024, 2025],
        "paymentTerms": [
            {"CODE": "PDR_OATT", "CODE_NM": "O/A(T/T 포함)", "PAYMENT_TERMS": [{"YEAR": "2025", "CNT": 10.0, "VALUE": oa}]},
            {"CODE": "PDR_LC", "CODE_NM": "L/C", "PAYMENT_TERMS": [{"YEAR": "2025", "CNT": 3.0, "VALUE": lc}]},
            {"CODE": "PDR_DA", "CODE_NM": "D/A", "PAYMENT_TERMS": [{"YEAR": "2025", "CNT": 1.0, "VALUE": 4.4}]},
            {"CODE": "PDR_DP", "CODE_NM": "D/P", "PAYMENT_TERMS": [{"YEAR": "2025", "CNT": 1.0, "VALUE": 2.8}]},
        ],
        "paymentPeriod": [
            {"CODE": "30_UNDER", "CODE_NM": "30일 이내", "PAYMENT_PERIOD": [{"YEAR": "2025", "CNT": 5, "VALUE": 38.0}]},
            {"CODE": "120_OVER", "CODE_NM": "120일 초과", "PAYMENT_PERIOD": [{"YEAR": "2025", "CNT": 1, "VALUE": long_tail}]},
        ],
        "averagePaymentPeriod": series(days), "latePaymentRate": series(late),
        "averagelatePaymentPeriod": series((16.2, 14.7)),
    }


def _ksure(items: dict):
    """ctryCd → item. 코드가 없으면 전체 나라 평균."""

    calls = []

    def fake_request(method, url, **kwargs):
        code = kwargs["params"].get("ctryCd", "")
        calls.append(code)
        item = items.get(code)
        body = ({"response": {"header": {"resultCode": 0}, "body": {"items": {"item": [item]}}}}
                if item else {"response": {"header": {"resultCode": 3, "resultMsg": "데이터 없음"},
                                           "body": None}})
        return {"success": True, "source": "api", "data": json.dumps(body, ensure_ascii=False)}

    return fake_request, calls


@pytest.mark.parametrize("name, expected", [
    ("베트남", ("베트남", "176")), ("UAE", ("아랍에미리트 연합", "280")),
    ("아랍에미리트", ("아랍에미리트 연합", "280")), ("미국", ("미국", "450")), ("USA", ("미국", "450")),
])
def test_나라_이름을_무역보험공사_숫자_코드로_찾는다(app, name, expected):
    with app.app_context():
        found = ksure_client.find_country(name)
    assert (found["name"], found["code"]) == expected


def test_모르는_나라는_짐작하지_않는다(app):
    with app.app_context():
        assert ksure_client.find_country("없는나라") is None


def test_결제_통계를_전체_평균과_견줘_등급과_주의점을_낸다(app, keyed, monkeypatch):
    fake, calls = _ksure({"176": _ksure_item(), "": _ksure_item(late=(17.0, 18.3), days=(73.0, 73.5))})
    monkeypatch.setattr(ksure_client, "request_text", fake)

    with app.app_context():
        result = insight.fetch_ksure_payment_risk("베트남")

    assert calls == ["176", ""]            # 나라 → 전체 나라 평균
    assert result["country"] == "베트남" and result["year"] == "2025"
    assert result["payment_terms"][0] == {"name": "O/A(T/T 포함)", "code": "PDR_OATT",
                                          "share_pct": 67.8, "prev_share_pct": None, "year": "2025"}
    assert result["late_payment_rate_pct"] == 22.9
    assert result["benchmark_all_countries"]["late_payment_rate_pct"] == 18.3
    assert result["risk_level"] == "주의"          # 22.9 / 18.3 = 1.25
    assert "공식 국가등급이 아닙니다" in result["risk_level_basis"]
    text = " ".join(result["cautions"])
    assert "L/C 비중 21.2%" in text and "연체율 22.9%로 전체 나라 평균(18.3%)보다 높습니다" in text
    assert "20.8% → 22.9%" in text and "D/A·D/P(추심) 비중 7.2%" in text


def test_외상이_많고_오래_걸리는_나라는_등급을_올린다(app, keyed, monkeypatch):
    fake, _ = _ksure({"280": _ksure_item(late=(30.0, 30.0), lc=12.2, oa=78.1, long_tail=13.8),
                      "": _ksure_item(late=(18.3, 18.3))})
    monkeypatch.setattr(ksure_client, "request_text", fake)

    with app.app_context():
        result = insight.fetch_ksure_payment_risk("UAE")

    assert result["risk_level"] == "높음"
    text = " ".join(result["cautions"])
    assert "O/A(T/T 사후송금 포함)" in text and "120일 넘게 걸리는 거래가 13.8%" in text


def test_받아_둔_통계를_쓰고_API가_멈추면_예전_것을_쓴다(app, keyed, monkeypatch):
    fake, calls = _ksure({"450": _ksure_item()})
    monkeypatch.setattr(ksure_client, "request_text", fake)
    with app.app_context():
        assert ksure_client.payment_info("450")["source"] == "api"
        assert ksure_client.payment_info("450")["success"]
        assert calls == ["450"]                 # 두 번째는 받아 둔 것
        # 하루가 지나 다시 받으려는데 API가 멈췄으면 예전 것이라도 씁니다.
        monkeypatch.setattr(file_cache, "read", lambda name: ({"late_payment_rate": []}, 5.0))
        monkeypatch.setattr(ksure_client, "request_text",
                            lambda *a, **k: {"success": False, "error_code": "API_TIMEOUT", "source": "api",
                                             "message": "timeout"})
        assert ksure_client.payment_info("450")["source"] == "cache"


def test_통계가_없는_나라는_없다고_한다(app, keyed, monkeypatch):
    fake, _ = _ksure({})
    monkeypatch.setattr(ksure_client, "request_text", fake)
    with app.app_context():
        result = ksure_client.payment_info("999")
    assert result["success"] is False and result["error_code"] == "API_NO_DATA"


# --- 도구 실행과 Function Calling ------------------------------------------------------

def test_모르는_도구와_인자는_거절하고_오류를_던지지_않는다(app, monkeypatch):
    assert insight.run_tool("drop_database", {})["success"] is False

    seen = {}
    monkeypatch.setitem(insight.HANDLERS, "fetch_ksure_payment_risk",
                        lambda **kwargs: seen.update(kwargs) or {"success": True})
    insight.run_tool("fetch_ksure_payment_risk", {"country_name": "미국", "evil": "x"})
    assert seen == {"country_name": "미국"}

    def boom(**kwargs):
        raise RuntimeError("외부 응답이 이상함")

    monkeypatch.setitem(insight.HANDLERS, "fetch_ksure_payment_risk", boom)
    assert insight.run_tool("fetch_ksure_payment_risk", {"country_name": "미국"})["success"] is False


def test_도구_정의는_OpenAI_function_모양이다():
    names = [tool["function"]["name"] for tool in insight.TOOLS]
    assert names == ["get_item_trade_statistics", "fetch_customs_export_stats", "fetch_ksure_payment_risk"]
    for tool in insight.TOOLS:
        assert tool["type"] == "function"
        params = tool["function"]["parameters"]
        assert params["type"] == "object" and set(params["required"]) <= set(params["properties"])


def _openai(message: dict) -> dict:
    return {"success": True, "source": "api",
            "data": json.dumps({"choices": [{"message": message, "finish_reason": "stop"}]})}


def test_AI가_도구를_부르면_실행해_결과를_돌려주고_답을_받는다(app, monkeypatch):
    sent = []
    replies = iter([
        _openai({"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {
                "name": "fetch_ksure_payment_risk", "arguments": '{"country_name": "베트남"}'}},
            {"id": "call_2", "type": "function", "function": {
                "name": "fetch_customs_export_stats", "arguments": "not json"}}]}),
        _openai({"role": "assistant", "content": "베트남 연체율은 22.9%입니다."}),
    ])
    monkeypatch.setattr(ai_client, "get_config",
                        lambda name, default=None: "key" if name == "AI_API_KEY" else default)
    monkeypatch.setattr(ai_client, "request_text",
                        lambda method, url, **kw: sent.append(kw["json"]) or next(replies))
    ran = []

    def run(name, arguments):
        ran.append((name, arguments))
        return {"success": name == "fetch_ksure_payment_risk", "source": "x", "late": 22.9}

    result = ai_client.chat([{"role": "user", "content": "베트남 결제 리스크?"}],
                            tools=insight.TOOLS, run_tool=run)

    assert result["data"] == "베트남 연체율은 22.9%입니다."
    assert ran == [("fetch_ksure_payment_risk", {"country_name": "베트남"}),
                   ("fetch_customs_export_stats", {})]          # 깨진 인자는 빈 인자로
    assert "tools" in sent[0]
    tool_messages = [m for m in sent[1]["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["call_1", "call_2"]
    assert json.loads(tool_messages[0]["content"])["late"] == 22.9
    assert [call["success"] for call in result["tools_used"]] == [True, False]


def test_도구만_부르고_끝나지_않으면_마지막엔_도구를_빼고_답하게_한다(app, monkeypatch):
    sent = []
    call = _openai({"role": "assistant", "content": None, "tool_calls": [
        {"id": "c", "type": "function", "function": {"name": "fetch_ksure_payment_risk",
                                                      "arguments": "{}"}}]})
    replies = iter([call] * ai_client.MAX_TOOL_ROUNDS + [_openai({"content": "답"})])
    monkeypatch.setattr(ai_client, "get_config",
                        lambda name, default=None: "key" if name == "AI_API_KEY" else default)
    monkeypatch.setattr(ai_client, "request_text",
                        lambda method, url, **kw: sent.append(kw["json"]) or next(replies))

    result = ai_client.chat([], tools=insight.TOOLS, run_tool=lambda *a: {"success": True})

    assert result["data"] == "답"
    assert "tools" not in sent[-1]


# --- 상담 창구 -------------------------------------------------------------------

def test_메인_상담은_도구를_넘기고_근거를_돌려준다(client, monkeypatch):
    seen = {}

    def fake_chat(messages, **kwargs):
        seen["tools"] = kwargs.get("tools")
        seen["force_tool"] = kwargs.get("force_tool")
        seen["system"] = [m["content"] for m in messages if m["role"] == "system"]
        return {"success": True, "source": "api", "data": "브리핑",
                "tools_used": [
                    {"name": "fetch_customs_export_stats", "success": True,
                     "source": insight.CUSTOMS_SOURCE + " + " + insight.KSURE_SOURCE,
                     "output": {"period": "2025년 연간(1~12월)", "compare_period": "2024년 연간(1~12월)",
                                "hs_codes": [{"hs_code": "61"}, {"hs_code": "62"}]}},
                    {"name": "fetch_ksure_payment_risk", "success": True, "source": insight.KSURE_SOURCE,
                     "output": {"country": "베트남", "year": "2025", "last_update": "2026.01.01"}},
                    {"name": "fetch_ksure_payment_risk", "success": False, "source": ""}]}

    monkeypatch.setattr(support_chat_service.ai_client, "chat", fake_chat)
    body = client.post("/api/support-chat", json={"question": "의류 수출 국가 추천해줘"}).get_json()

    assert seen["tools"] is insight.TOOLS
    assert seen["force_tool"] is True          # "추천" — 기억으로 답하지 못하게 도구를 반드시 부릅니다
    assert any("오늘은" in text for text in seen["system"])
    assert body["data"]["sources"] == ["관세청 품목별·국가별 수출입실적", "한국무역보험공사 수출결제정보"]
    basis = body["data"]["basis"]
    assert basis[0] == "관세청 수출 실적: 2025년 연간(1~12월) (비교 2024년 연간(1~12월)) · HS 61, 62 · 단위 달러"
    assert basis[1].startswith("무역보험공사 결제 통계: 베트남 2025년")
    assert "ForwardUs 참고 등급" in basis[2]
    # 도구 결과 전체는 화면으로 보내지 않습니다.
    assert "output" not in json.dumps(body, ensure_ascii=False)


def test_오른쪽_아래_짧은_상담_창은_도구를_쓰지_않는다(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(support_chat_service.ai_client, "chat",
                        lambda messages, **kw: seen.update(kw) or {"success": True, "source": "api",
                                                                   "data": "짧은 답"})
    body = client.post("/api/support-chat", json={"question": "FOB?", "style": "brief"}).get_json()
    assert "tools" not in seen and "sources" not in body["data"]


def test_시스템_프롬프트에_데이터_분석_원칙과_레이아웃이_있다():
    prompt = support_chat_service.SYSTEM_PROMPT
    for text in ("[API 데이터 기반 전문 분석 원칙]", "막연한 일반론은 엄격히 금지",
                 "fetch_customs_export_stats", "fetch_ksure_payment_risk",
                 "💡 사수의 핵심 인사이트", "📊 관세청 실적 기반 국가별 수출액 분석",
                 "| 국가명 | 최근 연간 수출액 | 전년 대비 증감률 | 시장 포인트 |",
                 "🛡️ 무역보험공사 데이터 기반 대금 결제 주의점", "📄 ForwardUs 다음 단계 안내",
                 "[📄 서류 작성하러 가기](/documents/new)", "#hs:", "❓ 실무자가 지금 바로 체크해야 할 후속 질문 3개",
                 "ForwardUs 참고 등급", "수치를 지어내지 말고", "기억으로 쓰는 것은 금지", "HS_AMBIGUOUS"):
        assert text in prompt, text


@pytest.mark.parametrize("text, expected", [
    ("의류 수출하고 싶은데 국가 추천해줘", True), ("베트남 결제 리스크 어때?", True),
    ("립스틱 수출액 비교해줘", True), ("FOB가 뭔가요?", False),
])
def test_수치를_물으면_도구를_반드시_부르게_한다(text, expected):
    assert support_chat_service.wants_data(text) is expected


def test_첫_왕복에만_도구를_강제한다(app, monkeypatch):
    sent = []
    replies = iter([
        _openai({"content": None, "tool_calls": [{"id": "c", "type": "function", "function": {
            "name": "fetch_ksure_payment_risk", "arguments": "{}"}}]}),
        _openai({"content": "답"}),
    ])
    monkeypatch.setattr(ai_client, "get_config",
                        lambda name, default=None: "key" if name == "AI_API_KEY" else default)
    monkeypatch.setattr(ai_client, "request_text",
                        lambda method, url, **kw: sent.append(kw["json"]) or next(replies))

    ai_client.chat([], tools=insight.TOOLS, run_tool=lambda *a: {"success": True}, force_tool=True)

    assert [body["tool_choice"] for body in sent] == ["required", "auto"]


def test_넓은_품목은_정해_둔_범위로_조회한다(app):
    with app.app_context():
        hs = insight.resolve_hs("의류")
    assert [code for code, _ in hs["codes"]] == ["61", "62"] and hs["basis"] == "broad"


def test_검색이_여러_호로_흩어지면_짐작하지_않고_되묻는다(app, keyed, monkeypatch):
    rows = [{"code": f"{h}.00-0000"} for h in ("8486", "8486", "8541", "9030", "8523", "7409")]
    monkeypatch.setattr(insight.hsk_catalog, "search", lambda query, limit=12: rows)
    with app.app_context():
        result = insight.fetch_customs_export_stats("정밀장비")
    assert result["success"] is False and result["error_code"] == "HS_AMBIGUOUS"
    assert result["candidates"][0]["hs_code"] == "8486"


def test_상위_나라에는_결제_통계_요약을_붙인다(app, keyed, monkeypatch):
    fake, _ = _customs({("6109", "202501", "202512"): [_customs_row("2025.12", "VN", "베트남", 500),
                                                       _customs_row("2025.12", "XX", "없는나라", 100)],
                        ("6109", "202401", "202412"): []})
    monkeypatch.setattr(trade_stats_client, "_call", fake)
    ksure, _ = _ksure({"176": _ksure_item(), "": _ksure_item(late=(17.0, 18.3))})
    monkeypatch.setattr(ksure_client, "request_text", ksure)

    with app.app_context():
        result = insight.fetch_customs_export_stats("티셔츠", target_year=2025, hs_codes=["6109"])

    vn, unknown = result["top_countries"]
    assert vn["payment_risk"]["available"] and vn["payment_risk"]["late_payment_rate_pct"] == 22.9
    assert vn["payment_risk"]["lc_share_pct"] == 21.2
    assert unknown["payment_risk"]["available"] is False       # 모르는 나라는 숫자 없이
    assert insight.KSURE_SOURCE in result["source"]
    assert vn["yoy_text"] == "비교 불가(전년 실적 없음)"


# --- K-stat 품목별 수출입실적 표 ----------------------------------------------------------

def _code_row(month, iso, hs, name, exp, imp=0):
    row = _customs_row(month, iso, "나라", exp, hs)
    row.update({"statKor": name, "impDlr": str(imp)})
    return row


def test_세부_부호별로_수출_수입을_더한다(app, keyed, monkeypatch):
    fake, _ = _customs({("8542", "202501", "202512"): [
        _code_row("2025.01", "US", "854232", "메모리", 1000, 100),
        _code_row("2025.02", "CN", "854232", "메모리", 500, 0),
        _code_row("2025.01", "US", "854231", "프로세서와 컨트롤러", 300, 50)]})
    monkeypatch.setattr(trade_stats_client, "_call", fake)

    with app.app_context():
        codes = trade_stats_client.exports_by_country("8542", "202501", "202512")["data"]["codes"]

    assert codes["854232"] == {"hs_code": "854232", "name": "메모리", "export_usd": 1500, "import_usd": 100}
    assert codes["854231"]["import_usd"] == 50


def test_K_stat처럼_순위_전년_당해_증감률_무역수지를_천불로_낸다(app, keyed, monkeypatch):
    fake, calls = _customs({
        ("8542", "202501", "202512"): [
            _code_row("2025.12", "US", "854232", "메모리[모듈 포함]", 94_613_265_400, 19_409_609_000),
            _code_row("2025.12", "US", "854231", "프로세서와 컨트롤러", 36_684_760_000, 33_585_810_000),
            _code_row("2025.12", "US", "854239", "기타", 10_000, 0)],
        ("8542", "202401", "202412"): [
            _code_row("2024.12", "US", "854232", "메모리", 72_019_704_000),
            _code_row("2024.12", "US", "854231", "프로세서와 컨트롤러", 35_845_619_000)],
    })
    monkeypatch.setattr(trade_stats_client, "_call", fake)

    with app.app_context():
        result = insight.get_item_trade_statistics("메모리")

    assert result["success"] and result["hs_codes"][0]["hs_code"] == "8542"
    first, second, third = result["rows"]
    assert (first["rank"], first["hs_code"], first["name"]) == (1, "854232", "메모리")
    assert first["name_full"] == "메모리[모듈 포함]"
    assert first["export_kusd"] == 94_613_265 and first["export_text"] == "94,613,265"
    assert first["prev_export_text"] == "72,019,704" and first["yoy_text"] == "+31.4%"
    assert first["trade_balance_kusd"] == 94_613_265 - 19_409_609
    assert second["rank"] == 2 and second["group_hs_code"] == "8542"
    assert third["yoy_text"] == "비교 불가(전년 실적 없음)"
    assert third["name"] == "기타 (8542)"          # 이름만으로는 무슨 품목인지 모릅니다
    assert result["total"]["export_usd_text"].endswith("달러")
    assert result["total"]["yoy_text"] == "+21.7%"      # 131,298,045 / 107,865,323
    assert "천 달러" in result["unit"]
    assert result["table_columns"][-1] == "무역수지(천불)"


def test_올해_누계는_전년_같은_달까지와_견준다(app, keyed, monkeypatch):
    year = date.today().year
    fake, calls = _customs({
        ("3304", f"{year}01", f"{year}12"): [_code_row(f"{year}.08", "US", "330499", "기타", 2000)],
        ("3304", f"{year - 1}01", f"{year - 1}08"): [_code_row(f"{year - 1}.08", "US", "330499", "기타", 1000)],
    })
    monkeypatch.setattr(trade_stats_client, "_call", fake)

    with app.app_context():
        result = insight.get_item_trade_statistics("화장품", period="ytd")

    assert result["period"] == f"{year}년 1~8월 누계"
    assert result["compare_period"] == f"{year - 1}년 1~8월"
    assert calls[-1]["endYymm"] == f"{year - 1}08"
    assert result["rows"][0]["yoy_text"] == "+100.0%"


@pytest.mark.parametrize("period, expected", [
    ("latest", (2025, False)), ("", (2025, False)), ("ytd", (2026, True)), ("누계", (2026, True)),
    ("2023", (2023, False)), ("1999", (2025, False)),
])
def test_기간_해석(period, expected):
    assert insight._item_period(period, date(2026, 9, 22)) == expected


def test_긴_법조문_품명은_괄호를_떼고_줄인다():
    assert insight._short_name("메모리[모듈(module)을 포함한다]") == "메모리"
    assert len(insight._short_name("가" * 80)) == insight.SHORT_NAME_CHARS


def test_품목_통계_도구가_맨_앞에_등록되어_있다():
    tool = insight.TOOLS[0]["function"]
    assert tool["name"] == "get_item_trade_statistics"
    assert set(tool["parameters"]["properties"]) == {"item_name", "hs_code", "period", "top"}
    assert tool["parameters"]["properties"]["period"]["enum"] == ["latest", "ytd"]
    assert insight.HANDLERS["get_item_trade_statistics"] is insight.get_item_trade_statistics


def test_품목_통계_답에는_천불_단위_근거가_붙는다(client, monkeypatch):
    def fake_chat(messages, **kwargs):
        return {"success": True, "source": "api", "data": "표",
                "tools_used": [{"name": "get_item_trade_statistics", "success": True,
                                "source": insight.ITEM_SOURCE,
                                "output": {"period": "2025년 연간(1~12월)", "compare_period": "2024년 연간(1~12월)",
                                           "hs_codes": [{"hs_code": "8542"}]}}]}

    monkeypatch.setattr(support_chat_service.ai_client, "chat", fake_chat)
    body = client.post("/api/support-chat", json={"question": "메모리 수출 실적 알려줘"}).get_json()

    assert body["data"]["basis"][0] == ("관세청 품목별 실적: 2025년 연간(1~12월) (비교 2024년 연간(1~12월)) "
                                        "· HS 8542 · 단위 천 달러(천불)")
    assert support_chat_service.wants_data("메모리 수출 증감률 보여줘")


def test_시스템_프롬프트에_K_stat_표_지침이_있다():
    prompt = support_chat_service.SYSTEM_PROMPT
    for text in ("[품목별 수출 실적 및 통계 조회 질문 대응]", "get_item_trade_statistics",
                 "K-stat 통계 화면처럼", "💡 **품목 실적 핵심 요약", "📊 **품목별 수출입 실적 현황 (K-stat 기반)**",
                 "| 순위 | HS코드 | 품목명 | 전년 실적(천불) | 당해연도 수출액(천불) | 증감률 | 무역수지(천불) |",
                 # 돋보기 🔎는 HS CODE 검색 자리입니다. 거의 같은 모양의 🔍를
                 # 답변 머리글에 쓰면 눌러야 하는 것처럼 보여 나침반으로 바꿨습니다.
                 "🧭 **20년 차 실무 사수의 관전 포인트**",
                 "🔗 **ForwardUs 액션 버튼**",
                 "[📄 해당 품목 서류 작성하러 가기](/documents/new)", "[🔎 HS CODE 상세 조회](#hs:품명)",
                 "템플릿'의 제목"):
        assert text in prompt, text
