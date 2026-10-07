"""전수 점검 4회차(사용자) — 정상 입력을 막지 않는지부터 시험합니다."""

import pytest

from app.validators.document_validator import clean_document_fields


def test_선택_칸인_순중량을_비워도_다른_칸을_저장할_수_있다():
    current = {"payment_terms": "T/T", "net_weight_kg": "", "gross_weight_kg": 120.0}
    updated = clean_document_fields({"payment_terms": "L/C at sight", "net_weight_kg": ""}, current)
    assert updated["payment_terms"] == "L/C at sight"
    assert updated["net_weight_kg"] == ""


def test_순중량에_글자를_넣으면_여전히_막는다():
    from app.validators import ValidationError
    with pytest.raises(ValidationError):
        clean_document_fields({"net_weight_kg": "열 근"}, {})


def test_다른_숫자_칸은_비우면_여전히_막는다():
    from app.validators import ValidationError
    with pytest.raises(ValidationError):
        clean_document_fields({"gross_weight_kg": ""}, {"gross_weight_kg": 10.0})


def _codes(query, kind=None):
    from app.collectors import location_client
    return [item["code"] for item in (location_client.search_locations(query, kind).get("data") or [])]


@pytest.mark.parametrize("query, code", [("LA", "USLAX"), ("L.A.", "USLAX"), ("엘에이", "USLAX"),
                                          ("NY", "USNYC"), ("LB", "USLGB"), ("Los Angles", "USLAX")])
def test_흔한_약어가_엉뚱한_항구가_아니라_맞는_항구로(query, code):
    assert code in _codes(query, "port")[:3]


def test_두바이_바다_도착지는_제벨알리():
    assert "AEJEA" in _codes("두바이", "port")[:2]
    assert "AEJEA" in _codes("Dubai", "port")[:2]


def test_공항으로_두바이를_찾으면_DXB는_그대로():
    assert "DXB" in _codes("Dubai", "airport")


def test_기존_검색은_바뀌지_않는다():
    assert _codes("Busan", "port")[:1] and _codes("호치민", "port")


@pytest.mark.parametrize("name, code", [("Vietnam", "VN"), ("베트남", "VN"), ("Indonesia", "ID"), ("Germany", "DE"),
                                         ("Singapore", "SG"), ("Mexico", "MX"), ("Japan", "JP"), ("us", "US")])
def test_Buyer_국가는_이름이어도_올바른_코드로(name, code):
    from app.services.document_start_service import _country_code
    assert _country_code({"buyer_country": name}) == code


def test_알_수_없는_국가는_자르지_않고_거절():
    from app.services.document_start_service import _country_code
    from app.validators import ValidationError
    with pytest.raises(ValidationError):
        _country_code({"buyer_country": "Narnia"})
    assert _country_code({"buyer_country": ""}) == ""


@pytest.mark.parametrize("raw, expected", [("1,000", 1000.0), ("48,000.00", 48000.0), ("12", 12.0), ("1,234,567.5", 1234567.5),
                                            ("2.5", 2.5), (" 3 000 ", 3000.0)])
def test_정상적인_쉼표_숫자는_그대로_읽는다(raw, expected):
    from app.validators.cargo_validator import parse_number
    assert parse_number(raw, "단가") == expected


@pytest.mark.parametrize("raw", ["2,5", "1,5", "12,34", "1,2345", ",5"])
def test_소수점인지_모르는_쉼표는_묻는다(raw):
    from app.validators import ValidationError
    from app.validators.cargo_validator import parse_number
    with pytest.raises(ValidationError):
        parse_number(raw, "단가")


def _validate(data):
    from app.processors.document_validator import validate_documents
    return validate_documents({"commercial_invoice": data}, {}, {"commercial_invoice": "상업송장"}, {})


def test_영문_칸의_한글은_경고한다():
    result = _validate({"exporter": "주식회사 포워더스", "consignee": "ABC Inc."})
    assert any(f["kind"] == "language" and f["field"] == "exporter" for f in result["findings"])


def test_영문만_있으면_한글_경고가_없다():
    result = _validate({"exporter": "FORWARDUS CO., LTD.", "consignee": "ABC Inc.",
                        "items": [{"product_description": "TOOTHPASTE 100G"}]})
    assert not [f for f in result["findings"] if f["kind"] == "language"]


def test_품목_줄의_한글_품명도_짚는다():
    result = _validate({"items": [{"product_description": "치약 100g"}]})
    assert any(f["kind"] == "language" and "품목 1줄" in f["message"] for f in result["findings"])
