"""계약서 조항 점검.

여기서 보는 것은 "조항을 많이 아는가"가 아니라 **함부로 단정하지 않는가**입니다.
  - 빠진 필수조항과 들어 있는 독소조항을 실제로 집어내는가
  - 보이지 않는 것을 "없다"가 아니라 "안 보인다"로 다루는가
  - 인코텀즈에 안 걸리는 조항(보험)을 억지로 요구하지 않는가
  - 독소조항을 **문안으로 내보내지 않는가** (그건 빼야 할 문장입니다)
  - AI 키 없이도 도는가
"""

from __future__ import annotations

import pytest

from app.processors import contract_clauses
from app.services import ServiceError, contract_clause_service as service

DANGEROUS = """SALES CONTRACT
Payment shall be made within 30 days after the Buyer receives payment from its
end customer. The Buyer may terminate this Contract at any time for convenience
upon written notice, without liability. The courts of Japan shall have
exclusive jurisdiction. The Seller shall indemnify the Buyer against any and
all losses without limitation.
"""

SOUND = """SALES CONTRACT
1. DESCRIPTION OF GOODS as per Annex 1 (commodity, HS code, specification).
2. PRICE: CIF Yokohama, Incoterms 2020.
3. PAYMENT by irrevocable letter of credit at sight.
4. SHIPMENT: latest 30 Nov. Partial shipment allowed. Transhipment allowed.
5. INSPECTION at the port of loading; certificate final and binding.
6. INSURANCE: ICC(C) for 110% of invoice value.
7. FORCE MAJEURE: acts of God, war, strike, export restriction.
8. GOVERNING LAW: laws of the Republic of Korea. CISG shall not apply.
9. ARBITRATION in Seoul under the rules of KCAB INTERNATIONAL.
10. RETENTION OF TITLE: title shall pass upon payment in full.
"""


def test_독소조항을_집어낸다():
    result = service.review(DANGEROUS, "FOB")
    keys = {row["key"] for row in result["toxic"]}
    assert {"payment_on_resale", "termination_at_will",
            "foreign_forum", "unlimited_damages"} <= keys


def test_빠진_필수조항을_집어낸다():
    result = service.review(DANGEROUS, "FOB")
    missing = {row["key"] for row in result["missing"]}
    # 이 계약서에는 중재·준거법·불가항력·소유권 유보가 없습니다.
    assert {"arbitration", "governing_law", "force_majeure", "title"} <= missing


def test_갖춘_계약서는_필수조항을_다_찾는다():
    result = service.review(SOUND, "CIF")
    assert result["missing"] == []
    assert result["toxic"] == []


def test_보험조항은_CIF_CIP에서만_요구한다():
    fob = {row["key"] for row in service.checklist("FOB")["must"]}
    cif = {row["key"] for row in service.checklist("CIF")["must"]}
    assert "insurance" not in fob
    assert "insurance" in cif


def test_빈_글은_판정하지_않는다():
    with pytest.raises(ServiceError):
        service.review("   ", "FOB")


def test_독소조항은_문안으로_내보내도_빼라고_말한다():
    body = service.clause_text(["termination_at_will"])
    assert "넣는 것이 아니라 빼는 것" in body


def test_문안에는_늘_법률자문이_아니라고_적는다():
    body = service.clause_text(["arbitration"])
    assert "법률 자문이 아닙니다" in body
    assert "KCAB" in body


def test_고른_조항이_없으면_내보내지_않는다():
    with pytest.raises(ServiceError):
        service.clause_text([])


def test_찾은_것은_보인다는_뜻일_뿐이다():
    """글자를 찾았을 뿐, 그 조항이 유리하게 쓰였다는 뜻은 아닙니다."""

    text = service.as_text(service.review(SOUND, "CIF"))
    assert "글자를 찾은 결과" in text
    assert "법률 자문이 아닙니다" in text


def test_모든_조항에_문안과_설명이_있다():
    for row in contract_clauses.CLAUSES:
        assert row["title"] and row["why"] and row["risk"], row["key"]
        assert row["text_en"].strip(), row["key"]
        assert row["text_ko"].strip(), row["key"]
        assert row["detect"], row["key"]
        if row["category"] == "toxic":
            # 독소조항은 "어떻게 고치나"가 없으면 알려 줘도 쓸 데가 없습니다.
            assert row["fix"], row["key"]


def test_화면_창구가_돈다(client):
    listed = client.get("/contract/clauses?incoterms=CIF").get_json()
    assert listed["success"]
    assert len(listed["data"]["groups"]["must"]) == 10

    judged = client.post("/contract/review", data={"text": DANGEROUS, "incoterms": "FOB"})
    data = judged.get_json()["data"]
    assert len(data["toxic"]) >= 4
    assert "법률 자문이 아닙니다" in data["summary"]

    exported = client.post("/contract/export", json={"keys": ["arbitration"]})
    assert exported.status_code == 200
    assert "contract-clauses.md" in exported.headers["Content-Disposition"]


def test_읽을_수_없는_파일은_밝힌다(client):
    answer = client.post("/contract/review", data={
        "file": (__import__("io").BytesIO(b"x"), "계약서.hwp")})
    assert answer.status_code == 400
    assert "PDF" in answer.get_json()["message"]
