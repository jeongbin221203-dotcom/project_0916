"""수출요건 확인과 증빙 서류 업로드·분석."""

from __future__ import annotations

import io

import pytest

from app.collectors import ai_client
from app.processors import export_requirements
from app.services import requirement_service
from app.validators import ValidationError


def test_cosmetics_need_a_free_sale_certificate():
    """화장품(33류)은 수입국이 자유판매증명서를 요구하는 경우가 많습니다."""

    items = export_requirements.check("3305100000")
    keys = [item["key"] for item in items]
    assert "cosmetic" in keys

    cosmetic = next(item for item in items if item["key"] == "cosmetic")
    assert "자유판매증명서 (CFS)" in cosmetic["documents"]
    assert cosmetic["agency"].startswith("식품의약품안전처")
    # 확인할 곳을 새 창으로 열 수 있게 주소를 함께 줍니다.
    assert cosmetic["lookup"]["url"].startswith("https://")


def test_machinery_is_flagged_for_strategic_goods_screening():
    """기계·전자는 사양에 따라 전략물자가 될 수 있어 판정부터 받아야 합니다."""

    items = export_requirements.check("8471300000")
    strategic = next(item for item in items if item["key"] == "strategic")
    assert "전략물자 판정서" in strategic["documents"]
    assert "yestrade" in strategic["lookup"]["url"]


def test_dangerous_cargo_adds_msds_regardless_of_hs_code():
    """위험물은 HS부호가 아니라 화물의 성질로 정해집니다."""

    plain = export_requirements.check("3208100000")
    dangerous = export_requirements.check("3208100000", is_dangerous=True)
    assert "dangerous" not in [item["key"] for item in plain]

    msds = next(item for item in dangerous if item["key"] == "dangerous")
    assert "물질안전보건자료 (MSDS)" in msds["documents"]


def test_unknown_chapter_says_so_instead_of_guessing():
    """규칙에 없는 류는 '없다'가 아니라 '직접 확인하라'고 알려 줍니다."""

    items = export_requirements.check("9999999999")
    assert items == []
    message = export_requirements.summary("9999999999", items)
    assert "관세법령정보포털" in message


def test_summary_asks_for_an_hs_code_when_missing():
    assert "HS부호를 입력하면" in export_requirements.summary("", [])


def test_requirements_cover_every_item_and_always_include_origin(app, create_shipment):
    """원산지증명서는 품목이 아니라 바이어가 정하므로 늘 함께 보여줍니다."""

    with app.app_context():
        shipment = create_shipment(cargo=[
            {"product_description": "샴푸", "hs_code": "3305100000", "package_type": "carton",
             "quantity": 100, "length_cm": 40, "width_cm": 30, "height_cm": 25,
             "weight_per_package_kg": 12},
            {"product_description": "노트북", "hs_code": "8471300000", "package_type": "carton",
             "quantity": 20, "length_cm": 40, "width_cm": 30, "height_cm": 10,
             "weight_per_package_kg": 3},
        ])
        check = requirement_service.requirements_for(shipment)

    assert [row["line_no"] for row in check["by_item"]] == [1, 2]
    keys = {item["key"] for item in check["requirements"]}
    assert {"cosmetic", "strategic", "origin"} <= keys
    assert all(item["uploaded"] is False for item in check["requirements"])


def test_upload_rejects_formats_we_cannot_read(app, create_shipment):
    with app.app_context():
        shipment = create_shipment()
        with pytest.raises(ValidationError):
            requirement_service.upload(shipment, _file(b"x", "virus.exe"), "cosmetic")
        with pytest.raises(ValidationError):
            requirement_service.upload(shipment, _file(b"", "empty.pdf"), "cosmetic")


def test_upload_then_analyze_reads_the_text_and_records_the_verdict(app, create_shipment, monkeypatch):
    """올린 서류의 글자를 읽어 이 건과 대조하고 결과를 남깁니다."""

    calls = {}

    def fake_review(text, context):
        calls["text"] = text
        calls["context"] = context
        return {"success": True, "source": "api", "data": {
            "document_type": "자유판매증명서(CFS)",
            "status": "check",
            "summary": "유효기간이 출항일보다 앞섭니다.",
            "findings": [{"label": "유효기간", "verdict": "differs", "detail": "2026-01-01에 만료됩니다."}],
        }}

    monkeypatch.setattr(ai_client, "available", lambda: True)
    monkeypatch.setattr(requirement_service.ai_client, "review_document", fake_review)

    with app.app_context():
        shipment = create_shipment()
        document = requirement_service.upload(
            shipment, _file("FREE SALE CERTIFICATE\nProduct: Shampoo".encode(), "cfs.txt"), "cosmetic")
        assert document.review_status == "pending"

        reviewed = requirement_service.analyze(shipment, document.id)
        assert reviewed.review_status == "check"
        assert "유효기간" in reviewed.review_summary
        assert reviewed.review_findings[0]["verdict"] == "differs"
        assert reviewed.reviewed_at is not None

        # 서류 본문과 이 건의 정보를 함께 넘겨야 대조할 수 있습니다.
        assert "FREE SALE CERTIFICATE" in calls["text"]
        assert calls["context"]["수출자"] == shipment.exporter_name
        assert calls["context"]["품목"][0]["HS부호"] == shipment.cargos[0].hs_code

        requirement_service.delete_upload(shipment, document.id)
        assert list(shipment.requirement_documents) == []


def test_analysis_without_a_key_says_so_instead_of_guessing(app, create_shipment, monkeypatch):
    """키가 없으면 지어내지 않고 키가 없다고 알려 줍니다."""

    monkeypatch.setattr(requirement_service.ai_client, "get_config",
                        lambda name, default=None: "" if name == "AI_API_KEY" else default,
                        raising=False)
    with app.app_context():
        shipment = create_shipment()
        document = requirement_service.upload(shipment, _file(b"CERTIFICATE", "c.txt"), "cosmetic")
        reviewed = requirement_service.analyze(shipment, document.id)
        assert reviewed.review_status == "failed"
        assert "AI_API_KEY" in reviewed.review_summary
        requirement_service.delete_upload(shipment, document.id)


def test_unreadable_scan_explains_why(app, create_shipment):
    """사진만 든 서류는 읽지 못합니다. 실패 이유를 사람 말로 알려 줍니다."""

    with app.app_context():
        shipment = create_shipment()
        document = requirement_service.upload(shipment, _file(b"\x89PNG\r\n", "scan.png"), "cosmetic")
        reviewed = requirement_service.analyze(shipment, document.id)
        assert reviewed.review_status == "failed"
        assert "사진" in reviewed.review_summary
        requirement_service.delete_upload(shipment, document.id)


class _Upload:
    """werkzeug FileStorage 대신 쓰는 최소한의 가짜 파일."""

    def __init__(self, data: bytes, filename: str):
        self._data = data
        self.filename = filename
        self.mimetype = "application/octet-stream"

    def read(self) -> bytes:
        return self._data


def _file(data: bytes, filename: str) -> _Upload:
    return _Upload(data, filename)
