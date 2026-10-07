"""전수 점검 4회차(전문가) — 막으면 안 되는 것부터 시험합니다."""

import pytest

from app.collectors.container_client import container_check_digit, container_no_valid
from app.processors import export_requirements
from app.validators.cargo_validator import dg_consistency


@pytest.mark.parametrize("first_ten, digit", [("OOLU123456", 7), ("HLXU123456", 1), ("CSQU305438", 3)])
def test_컨테이너_검증숫자_L_V_W_포함(first_ten, digit):
    assert container_check_digit(first_ten) == digit
    assert container_no_valid(first_ten + str(digit))


def test_틀린_검증숫자는_여전히_거절():
    assert not container_no_valid("OOLU1234560")


def test_납축전지_UN2794는_포장등급_없어도_경고없음():
    assert dg_consistency("2794", "8", "") == []
    assert dg_consistency("2795", "8", "") == []


def test_다른_8급은_포장등급_없으면_경고():
    assert any("포장등급" in note for note in dg_consistency("1789", "8", ""))


def _ids(hs):
    return {item["key"] for item in export_requirements.check(hs)}


@pytest.mark.parametrize("hs", ["0401", "0402", "0407"])
def test_유제품_알은_동물검역(hs):
    assert "animal" in _ids(hs + "10")


def test_꿀은_동물검역에서_제외():
    assert "animal" not in _ids("040900")


def _ci(rows, total=None):
    return {"commercial_invoice": {"items": rows, "invoice_value": total}}


def test_단위가_붙은_수량도_검산한다():
    from app.processors.document_validator import _item_findings
    bad = _item_findings(_ci([{"quantity": "2,000 PCS", "unit_price": "3.2", "amount": "5,000"}]), {})
    assert any("수량 × 단가" in f["message"] for f in bad)


def test_맞는_줄은_단위가_붙어도_통과():
    from app.processors.document_validator import _item_findings
    ok = _item_findings(_ci([{"quantity": "2,000 PCS", "unit_price": "3.2", "amount": "6,400"}], "6400"), {})
    assert ok == []


class _S:
    def __init__(self, code, origin, dest):
        self.incoterms, self.origin_name, self.destination_name = code, origin, dest


def test_Incoterms는_지정장소와_판을_붙인다():
    from app.services.document_service import _incoterms_text
    assert _incoterms_text(_S("FOB", "Incheon, Korea", "Los Angeles")) == "FOB INCHEON, INCOTERMS 2020"
    assert _incoterms_text(_S("CIF", "Incheon", "Los Angeles")) == "CIF LOS ANGELES, INCOTERMS 2020"
    assert _incoterms_text(_S("", "Incheon", "LA")) == ""


def test_장소가_붙어도_서류간_대조는_코드로():
    from app.processors.document_validator import _normalize
    assert _normalize("incoterms", "FOB INCHEON, INCOTERMS 2020") == _normalize("incoterms", "FOB")


def test_상업송장에_원산지_칸이_있다():
    from app.services import document_service
    assert "country_of_origin" in document_service.DOCUMENT_FIELDS["commercial_invoice"]
    from app.processors.document_form import LAYOUTS
    names = {name for row in LAYOUTS["commercial_invoice"]["rows"] for cell in row for name in cell[0].split("+")}
    assert "country_of_origin" in names
