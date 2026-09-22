"""내부 HSK 품목표(관세청 HS부호 단위별 품목명)를 확인합니다.

앞부분은 작은 가짜 표로 동작을, 뒷부분은 저장소에 든 실제 파일이 멀쩡한지 봅니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.collectors import customs_client, hsk_catalog

TABLE = {
    "base_date": "2026-01-01", "source": "관세청_HS부호 단위별 품목명",
    "levels": {"20": ["제20류 채소ㆍ과실의 조제품", "Ch 20"],
               "2007": ["잼ㆍ과실젤리ㆍ마멀레이드", "Jams, fruit jellies"],
               "200799": ["기타", "Other"],
               "4011": ["고무로 만든 공기타이어(신품)", "New pneumatic tyres"]},
    "codes": {"2007991000": ["잼ㆍ과실젤리와 마멀레이드", "Jams, fruit jellies and marmalades"],
              "2007999000": ["기타", "Other"],
              "4011101000": ["래디알 구조의 것", "Radial"]},
}


@pytest.fixture()
def table(monkeypatch):
    monkeypatch.setattr(hsk_catalog, "_catalog", lambda: TABLE)


def test_lookup_children_and_path(table):
    assert hsk_catalog.lookup("2007.99-1000")["name"] == "잼ㆍ과실젤리와 마멀레이드"
    assert hsk_catalog.lookup("2007999090") is None
    assert [row["code"] for row in hsk_catalog.children("200799")] == ["2007.99-1000", "2007.99-9000"]
    assert hsk_catalog.path("2007999000") == ["제20류 채소ㆍ과실의 조제품", "잼ㆍ과실젤리ㆍ마멀레이드", "기타"]
    assert hsk_catalog.context("2007999000") == {"heading": "잼ㆍ과실젤리ㆍ마멀레이드", "subheading": "기타"}


def test_search_finds_other_rows_through_their_heading(table):
    """끝단 이름이 "기타"여도 상위 호 이름(잼)으로 찾습니다. 끝단에 든 것이 먼저입니다."""

    codes = [row["code"] for row in hsk_catalog.search("잼 ")]
    assert codes == []                                     # 한 글자는 관세청처럼 찾지 않습니다.
    codes = [row["code"] for row in hsk_catalog.search("과실 젤리")]
    assert codes == ["2007.99-1000", "2007.99-9000"]
    assert [row["code"] for row in hsk_catalog.search("radial")] == ["4011.10-1000"]
    assert [row["code"] for row in hsk_catalog.search("4011.10-1000")] == ["4011.10-1000"]


def test_table_before_this_years_revision_is_stale(table):
    from datetime import date

    assert not hsk_catalog.info(date(2026, 9, 21))["stale"]
    assert hsk_catalog.info(date(2027, 1, 1))["stale"]      # HS2027 시행일부터 갱신 필요


def test_stale_table_is_announced_on_fallback(app, table, monkeypatch):
    monkeypatch.setattr(hsk_catalog, "info", lambda: {**TABLE, "stale": True})
    result = customs_client.search_hs_codes_offline("과실젤리", "관세청이 응답하지 않아")
    assert result["stale"] and "개정 이전" in result["offline_note"]


def test_data_sources_credit_the_table(app, table):
    from app.services import lookup_service

    rows = [row for group in lookup_service.data_sources()["groups"] for row in group["rows"]]
    row = next(row for row in rows if "HS부호 단위별 품목명" in row["label"])
    assert "공공누리 제1유형" in row["label"] and "2026-01-01" in row["label"]


def test_missing_file_means_unavailable(monkeypatch):
    monkeypatch.setattr(hsk_catalog, "_catalog", lambda: None)
    assert not hsk_catalog.available()
    assert hsk_catalog.search("과실젤리") is None and hsk_catalog.children("2007") == []


def test_customs_outage_falls_back_to_internal_table(app, table, monkeypatch):
    app.config["UNIPASS_API_KEYS"] = {"HS_CODE_SEARCH": "k"}
    monkeypatch.setattr(customs_client, "request_text",
                        lambda *a, **k: {"success": False, "error_code": "API_TIMEOUT", "message": "x"})
    result = customs_client.search_hs_codes("과실젤리")
    assert result["source"] == "internal" and result["base_date"] == "2026-01-01"
    assert "2026-01-01 기준" in result["offline_note"]
    assert result["data"][0]["code"] == "2007.99-1000"


def test_without_table_customs_outage_still_uses_examples(app, monkeypatch):
    monkeypatch.setattr(hsk_catalog, "_catalog", lambda: None)
    app.config["UNIPASS_API_KEYS"] = {}
    assert customs_client.search_hs_codes("화장품")["source"] == "mock"


# --- 저장소에 든 실제 품목표 ------------------------------------------------------

def test_real_table_has_known_codes():
    """data/build_hsk.py로 만든 파일. 흔한 물품의 세번이 들어 있어야 합니다."""

    assert hsk_catalog.available()
    assert hsk_catalog.info()["base_date"]
    for code in ("2007991000", "4011101000", "3305100000", "1902301010"):
        assert hsk_catalog.lookup(code), code
    assert len(hsk_catalog.children("2007")) >= 2


def test_build_rejects_a_half_empty_table():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data"))
    import build_hsk

    sheets = [[["HS4단위", "한글품목명", "영문품목명"], ["2007", "잼", "Jams"]],
              [["HS10단위", "한글품목명", "영문품목명"], ["2007991000", "잼", "Jams"]]]
    levels, codes = build_hsk.convert(sheets)
    assert codes == {"2007991000": ["잼", "Jams"]} and levels == {"2007": ["잼", "Jams"]}
    with pytest.raises(SystemExit):
        build_hsk.check(levels, codes)                     # 10자리가 너무 적습니다.
    with pytest.raises(SystemExit):
        build_hsk.convert([[["HS10단위", "", ""], ["20079910", "잼", "Jams"]]])
    assert build_hsk.base_date("관세청_HS부호 단위별 품목명_20260101") == "2026-01-01"
