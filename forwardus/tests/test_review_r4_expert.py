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


def _hit(entry_must, question):
    from app.services.knowledge_service import _compact, _must_hit
    asked = _compact(question)
    return any(_must_hit(word, asked, question) for word in entry_must)


@pytest.mark.parametrize("question", ["D/P는 서류 인도 조건인가요", "Shipping documents 목록", "CBM calculation 방법",
                                       "CIF 보험은 ICC(A)인가요?", "ICC(C)가 뭐예요?", "FOB 인도 장소는 어디예요"])
def test_짧은_낱말이_엉뚱한_나라_안내를_고르지_않는다(question):
    assert not _hit(["인도", "doc", "cul", "icc"], question)


@pytest.mark.parametrize("question", ["인도 수출하기", "인도로 수출할 때 인증", "India CE 마킹 doc", "필리핀 ICC 인증", "CUL 마크"])
def test_진짜_질문은_그대로_걸린다(question):
    assert _hit(["인도", "doc", "cul", "icc"], question)


@pytest.mark.parametrize("raw, expected", [("2,000 PCS", 2000.0), ("500 M2", 500.0), ("500 M3", 500.0),
                                            ("2 000 PCS", 2000.0), ("12 DZ (144 PCS)", 12.0), ("1,234,567 KG", 1234567.0),
                                            ("7.5 MT", 7.5)])
def test_수량_단위_붙은_값을_읽는다(raw, expected):
    from app.processors.document_validator import _qty_number
    assert _qty_number(raw) == expected


@pytest.mark.parametrize("raw", ["2,5 KG", "10,5 MT", "abc", "", "PCS"])
def test_뜻이_모호하면_읽지_않고_건너뛴다(raw):
    from app.processors.document_validator import _qty_number
    assert _qty_number(raw) is None


def test_항공_청구중량은_05kg_올림():
    from app.processors.cargo_calculator import _air_ceiling
    assert _air_ceiling(38.55) == 39.0
    assert _air_ceiling(39.0) == 39.0
    assert _air_ceiling(4.97) == 5.0
    assert _air_ceiling(39.01) == 39.5


def test_포장등급_없는_UN번호는_오경고하지_않는다():
    from app.validators.cargo_validator import dg_consistency
    for un, cls in (("3473", "3"), ("3477", "8"), ("3528", "3"), ("3356", "5.1")):
        assert dg_consistency(un, cls, "") == []


@pytest.mark.parametrize("hs, key, expected", [("410110", "animal", True), ("510111", "animal", True),
                                                ("050100", "animal", False), ("160431", "cites", True),
                                                ("900190", "pharma", False), ("901890", "pharma", True)])
def test_수출요건_규칙_정정(hs, key, expected):
    from app.processors import export_requirements
    assert (key in {item["key"] for item in export_requirements.check(hs)}) is expected


@pytest.mark.parametrize("question", ["FTA 원산지증명서는 수출신고 전에 받아야 하나요?", "한중 FTA 원산지증명서는 자율발급인가요?",
                                       "원산지증명서는 언제 발급해야 하나요?"])
def test_발급_시점_방식_질문은_창구_안내가_가로채지_않는다(question):
    from app.services.support_chat_service import _asks_about_origin
    assert not _asks_about_origin(question)


def test_발급처를_묻는_질문은_창구를_안내하고_자율발급도_밝힌다():
    from app.services.support_chat_service import _asks_about_origin, origin_answer
    assert _asks_about_origin("원산지증명서 어디서 받아요?")
    assert "자율발급" in origin_answer() and "발급 기관이 따로 있습니다" not in origin_answer()


class _Cargo:
    def __init__(self, temperature="", container_type="40GP", quantity=1):
        self.temperature_requirement, self.container_type, self.container_quantity = temperature, container_type, quantity


def test_원산지는_수출신고_화면에서_고친_값을_따른다():
    from app.services.document_service import _origin_text

    class S:
        country_of_origin = "CN · 중국"
    assert _origin_text(S()) == "CHINA"

    class K:
        country_of_origin = "KR · 대한민국"
    assert _origin_text(K()) == "THE REPUBLIC OF KOREA"

    class E:
        country_of_origin = ""
    assert _origin_text(E()) == "THE REPUBLIC OF KOREA"
