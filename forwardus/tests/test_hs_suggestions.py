from app.collectors import customs_client, customs_extra_client
from app.collectors.base_client import ok, fail
from app.services import hs_suggestion_service as suggestions, planning_service


def test_navigation_uses_api043_and_parses_counts(app, monkeypatch):
    app.config["UNIPASS_API_KEYS"] = {"HS_NAVIGATION": "test-key"}
    def request(method, url, **kwargs):
        assert url.endswith("/cmtrStatsQry/retrieveCmtrStats")
        assert kwargs["params"] == {"crkyCn": "test-key", "hsSgn": "2202999000"}
        return ok("""<cmtrStatsQryRtnVo><ntceInfo/>
          <cmtrStatsQryRsltVo><hs10Sgn>2202999000</hs10Sgn><prlstNm>DRINK</prlstNm>
          <acrsTcntRnk>1</acrsTcntRnk><prlstLnCnt>2,400</prlstLnCnt></cmtrStatsQryRsltVo>
          <tCnt>1</tCnt></cmtrStatsQryRtnVo>""", "api")
    monkeypatch.setattr(customs_extra_client, "request_text", request)
    with app.app_context():
        result = customs_extra_client.hs_navigation("2202.99-9000")
    assert result["data"][0]["count"] == 2400


def test_navigation_missing_count_is_not_zero(app, monkeypatch):
    import xml.etree.ElementTree as ET
    monkeypatch.setattr(customs_extra_client, "_call", lambda *a, **kw: ok(ET.fromstring(
        "<cmtrStatsQryRtnVo><cmtrStatsQryRsltVo><hs10Sgn>2202999000</hs10Sgn>"
        "<prlstLnCnt/></cmtrStatsQryRsltVo></cmtrStatsQryRtnVo>"), "api"))
    assert not customs_extra_client.hs_navigation("2202999000")["success"]


def candidates():
    return ok([{"code": "2202.99-9000", "name": "음료"},
               {"code": "2106.90-9099", "name": "조제식료품"}], "api")


def test_counts_shares_and_percentage_point_gaps(app, monkeypatch):
    def nav(code):
        count = 75 if code.startswith("2202") else 25
        return ok([{"code": code, "name": "example", "count": count, "rank": 1}], "api")
    monkeypatch.setattr(customs_extra_client, "hs_navigation", nav)
    with app.app_context():
        result = suggestions.compare(candidates(), "마시는 수액", ["음료"])
    assert result["navigation_summary"]["total"] == 100
    assert result["data"][0]["navigation"]["share"] == 75
    assert result["data"][1]["navigation"]["gap_pp"] == 50
    assert "전체 신고비율" in result["navigation_summary"]["note"]


def test_failed_candidate_suppresses_ratios(app, monkeypatch):
    monkeypatch.setattr(customs_extra_client, "hs_navigation", lambda code:
        ok([{"name": "DRINK", "count": 100}], "api") if code.startswith("2202")
        else fail("API_TIMEOUT", "api"))
    with app.app_context():
        result = suggestions.compare(candidates(), "음료", ["음료"])
    assert not result["navigation_summary"]["complete"]
    assert result["navigation_summary"]["total"] is None
    assert result["data"][0]["navigation"]["share"] is None


def test_mock_never_gets_declaration_statistics(app, monkeypatch):
    def unexpected(code):
        raise AssertionError("mock must not get real statistics")
    monkeypatch.setattr(customs_extra_client, "hs_navigation", unexpected)
    result = suggestions.compare({**candidates(), "source": "mock"}, "음료", ["음료"])
    assert "navigation_summary" not in result


def test_route_search_uses_ai_comparison(app, monkeypatch):
    monkeypatch.setattr(suggestions, "search", lambda q, c, o: {"routed": (q, c, o)})
    with app.app_context():
        result = planning_service.search_hs_codes("마시는 수액", compare_navigation=True,
                                                  country="US", order="tariff")
    assert result == {"routed": ("마시는 수액", "US", "tariff")}


def test_ai_terms_deduplicate_codes_across_terms(app, monkeypatch):
    row = {"code": "2202.99-9000", "name": "기타 음료"}
    result, _ = ai_search(app, monkeypatch, {"search_terms": ["음료", "음료수"]},
                          {"2202999000": "high"}, {"음료": [row], "음료수": [row]})
    assert len(result["data"]) == 1
    assert result["data"][0]["matched_terms"] == ["음료", "음료수"]


def ai_search(app, monkeypatch, analysis, assessments, catalog, navigation=None, query="마시는 수액",
              table=None):
    """Run the AI flow with OpenAI and customs mocked; no network calls.

    ``catalog`` is what the customs API returns per term; ``table`` is the internal
    HSK table (None = the file is missing, so the old API-only path runs).
    """
    from app.collectors import hs_ai_client, hs_open_client, hsk_catalog
    calls = []
    def search(term):
        calls.append(term)
        return ok(catalog.get(term, []), "api")
    monkeypatch.setattr(customs_client, "search_hs_codes", search)
    monkeypatch.setattr(hsk_catalog, "_catalog", lambda: table)
    monkeypatch.setattr(hs_open_client, "heading_names", lambda code: {"heading": "", "subheading": ""})
    monkeypatch.setattr(hs_ai_client, "analyze", lambda q: {
        "available": True, "summary": "", "hypotheses": [], "missing_details": [], **analysis})
    monkeypatch.setattr(hs_ai_client, "review", lambda q, a, rows: {
        "available": True, "message": "", "assessments": {
            c: {"match": m, "reason": "", "missing_details": []} for c, m in assessments.items()}})
    counts = navigation or {}
    monkeypatch.setattr(customs_extra_client, "hs_navigation", lambda code: ok(
        [{"name": "x", "count": counts.get("".join(ch for ch in code if ch.isdigit()), 1)}], "api"))
    with app.app_context():
        return suggestions.search(query), calls


def test_ai_terms_broaden_any_vague_input(app, monkeypatch):
    catalog = {"음료": [{"code": "2202.99-9000", "name": "기타 음료"}],
               "전해질": [{"code": "2106.90-9099", "name": "기타 조제식료품"}]}
    result, calls = ai_search(app, monkeypatch, {"search_terms": ["음료", "전해질"]},
                              {"2202999000": "high", "2106909099": "medium"}, catalog,
                              query="숙취 해소 워터")
    assert calls[0] == "숙취 해소 워터" and set(calls[1:]) == {"음료", "전해질"}
    assert [row["code"] for row in result["data"]] == ["2202.99-9000", "2106.90-9099"]
    assert result["data"][0]["priority"] == 1


def test_ai_hypothesis_needs_exact_customs_match(app, monkeypatch):
    catalog = {"2202999000": [{"code": "2202.99-9000", "name": "기타"}],
               "3004909999": [{"code": "3004.90-9910", "name": "다른 부호"}]}
    result, _ = ai_search(app, monkeypatch, {"search_terms": [], "hypotheses": [
        {"code": "2202999000", "reason": "음료"}, {"code": "3004909999", "reason": "의약품"}]},
        {"2202999000": "medium"}, catalog)
    assert [row["code"] for row in result["data"]] == ["2202.99-9000"]
    assert result["data"][0]["hypothesis"] == "음료"


def test_invented_tail_recovers_real_codes_under_same_hs6(app, monkeypatch):
    catalog = {"2007991000": [{"code": "2007.99-1000", "name": "잼ㆍ과실젤리와 마멀레이드"}],
               "2007999000": [{"code": "2007.99-9000", "name": "기타"}]}
    result, calls = ai_search(app, monkeypatch, {"search_terms": [], "hypotheses": [
        {"code": "2007999090", "reason": "잼"}]}, {"2007991000": "high", "2007999000": "medium"},
        catalog, query="딸기잼")
    assert [row["code"] for row in result["data"]] == ["2007.99-1000", "2007.99-9000"]
    assert "2007990000" in calls and "2008991000" not in calls
    assert result["searched_as"] == "2007999090"


def test_confirmed_hypothesis_is_not_probed(app, monkeypatch):
    catalog = {"2202999000": [{"code": "2202.99-9000", "name": "기타"}]}
    _, calls = ai_search(app, monkeypatch, {"search_terms": [], "hypotheses": [
        {"code": "2202999000", "reason": "음료"}]}, {"2202999000": "medium"}, catalog)
    assert not any(call.startswith("220299") and call != "2202999000" for call in calls)


JAM_TABLE = {
    "base_date": "2026-01-01",
    "levels": {"20": ["제20류 조제품", "Ch 20"], "2007": ["잼ㆍ과실젤리ㆍ마멀레이드", "Jams"],
               "200799": ["기타", "Other"], "2202": ["물과 그 밖의 비알코올 음료", "Waters"]},
    "codes": {"2007991000": ["잼ㆍ과실젤리와 마멀레이드", "Jams"], "2007999000": ["기타", "Other"],
              "2202999000": ["기타", "Other"]},
}


def test_internal_table_resolves_invented_tail_without_customs_calls(app, monkeypatch):
    result, calls = ai_search(app, monkeypatch, {"search_terms": [], "hypotheses": [
        {"code": "2007999090", "reason": "잼"}]}, {"2007991000": "high", "2007999000": "medium"},
        {}, query="딸기잼", table=JAM_TABLE)
    assert [row["code"] for row in result["data"]] == ["2007.99-1000", "2007.99-9000"]
    assert calls == ["딸기잼"]                              # AI 부호 확인에 관세청을 부르지 않음
    assert result["data"][1]["path"] == ["제20류 조제품", "잼ㆍ과실젤리ㆍ마멀레이드", "기타"]
    assert result["data"][0]["base_date"] == "2026-01-01"


def test_internal_table_confirms_existing_code(app, monkeypatch):
    result, calls = ai_search(app, monkeypatch, {"search_terms": [], "hypotheses": [
        {"code": "2202999000", "reason": "음료"}]}, {"2202999000": "medium"}, {}, table=JAM_TABLE)
    assert [row["code"] for row in result["data"]] == ["2202.99-9000"]
    assert result["data"][0]["hypothesis"] == "음료"
    assert "2202999000" not in calls


def test_offline_customs_result_is_labeled(app, monkeypatch):
    offline = {**ok([{"code": "2007.99-1000", "name": "잼", "base_date": "2026-01-01"}], "internal"),
               "base_date": "2026-01-01", "offline_note": "관세청이 응답하지 않아 ..."}
    from app.collectors import hs_ai_client
    monkeypatch.setattr(customs_client, "search_hs_codes", lambda term: offline)
    monkeypatch.setattr(hs_ai_client, "analyze", lambda q: {
        "available": False, "message": "", "search_terms": [], "hypotheses": []})
    monkeypatch.setattr(customs_extra_client, "hs_navigation", lambda code: fail("API_TIMEOUT", "api"))
    with app.app_context():
        result = suggestions.search("잼 제품")
    assert result["source"] == "internal" and result["base_date"] == "2026-01-01"
    assert result["offline_note"] and result["data"][0]["code"] == "2007.99-1000"


def test_low_relevance_ranks_last_despite_high_counts(app, monkeypatch):
    catalog = {"음료": [{"code": "8419.81-0000", "name": "음료 제조기"},
                      {"code": "2202.99-9000", "name": "기타 음료"}]}
    result, _ = ai_search(app, monkeypatch, {"search_terms": ["음료"]},
                          {"8419810000": "low", "2202999000": "high"}, catalog,
                          navigation={"8419810000": 9000, "2202999000": 10})
    assert [row["code"] for row in result["data"]] == ["2202.99-9000", "8419.81-0000"]
    assert result["data"][1]["relevance_label"] == "관련성 낮음"


def test_without_ai_falls_back_to_keywords(app, monkeypatch):
    from app.collectors import hs_ai_client
    calls = []
    monkeypatch.setattr(hs_ai_client, "analyze", lambda q: {
        "available": False, "message": "키 없음", "search_terms": [], "hypotheses": []})
    monkeypatch.setattr(customs_client, "search_hs_codes", lambda t: calls.append(t) or ok([], "api"))
    with app.app_context():
        result = suggestions.search("마시는 수액")
    assert calls == ["마시는 수액", "수액"]
    assert result["data"] == [] and result["ai_analysis"]["message"] == "키 없음"


def test_comparison_does_not_mutate_original_result(app, monkeypatch):
    found = candidates()
    monkeypatch.setattr(customs_extra_client, "hs_navigation", lambda c: ok([], "api"))
    with app.app_context():
        result = suggestions.compare(found, "음료", ["음료"])
    assert "navigation" not in found["data"][0]
    assert not result["navigation_summary"]["complete"]


def test_rank_orders_by_frequency_or_tariff_after_relevance():
    def row(code, count, rate):
        return {"code": code, "relevance": {"match": "medium"},
                "navigation": {"available": True, "count": count},
                "tariff": {"comparable": True, "rate": rate}}
    rows = [row("A", 10, 0.0), row("B", 500, 8.0), {**row("C", 900, 1.0), "relevance": {"match": "low"}}]
    assert [r["code"] for r in suggestions.rank(rows, "frequency")] == ["B", "A", "C"]
    assert [r["code"] for r in suggestions.rank(rows, "tariff")] == ["A", "B", "C"]


def test_review_ignores_codes_ai_invented(app, monkeypatch):
    from app.collectors import ai_client, hs_ai_client
    monkeypatch.setattr(ai_client, "available", lambda: True)
    monkeypatch.setattr(ai_client, "structured_chat", lambda *a, **kw: ok({"assessments": [
        {"code": "2202999000", "match": "high", "reason": "", "missing_details": []},
        {"code": "9999999999", "match": "high", "reason": "", "missing_details": []}]}, "api"))
    with app.app_context():
        result = hs_ai_client.review("음료", {}, [{"code": "2202.99-9000", "name": "음료"}])
    assert list(result["assessments"]) == ["2202999000"]
