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


# ── 챗봇에서 바로 ──────────────────────────────────────────────────────────

def test_상담창에_계약서를_붙여_넣으면_조항으로_답한다(app):
    from app.services import support_chat_service

    with app.app_context():
        answer = support_chat_service.ask(DANGEROUS * 2)
    assert answer["success"] and answer["source"] == "contract"
    assert "지우거나 고쳐야 할 조항" in answer["data"]["answer"]
    assert len(answer["data"]["contract"]["toxic"]) >= 4


def test_계약서가_아닌_말은_평소대로_답한다(app):
    """길다고 다 계약서로 보면, 긴 상담글이 전부 조항 점검으로 갑니다."""

    from app.services import support_chat_service

    long_question = "부산에서 이스탄불로 타이어를 보내려고 합니다. " * 20
    with app.app_context():
        assert not service.looks_like_contract(long_question)
        assert not service.looks_like_contract("계약서에 뭐가 들어가야 하나요?")
        answer = support_chat_service.ask("FOB랑 CIF는 어떻게 다른가요?")
    assert answer["source"] != "contract"


def test_상담창에_계약서_파일을_붙이면_조항으로_답한다(app):
    from app.services import attachment_service

    with app.app_context():
        result = attachment_service.handle(
            "contract.txt", (DANGEROUS * 2).encode("utf-8"),
            message="이 계약서 괜찮나요?", mode="consult")
    assert result["document"]["document_type"] == "contract"
    assert result["route"] == "consult"
    assert len(result["contract"]["toxic"]) >= 4
    assert "법률 자문이 아닙니다" in result["answer"]


def test_계약서가_아닌_글자파일은_이유를_밝힌다(app):
    from app.services import attachment_service

    with app.app_context():
        with pytest.raises(ServiceError) as caught:
            attachment_service.handle("memo.txt", "오늘 할 일".encode("utf-8"),
                                      message="", mode="consult")
    assert "계약서" in str(caught.value)


# ── 부호만 적어 보냈을 때 ──────────────────────────────────────────────────

def test_HS부호만_적어_보내면_그_부호로_답한다(app):
    from app.services import support_chat_service

    with app.app_context():
        answer = support_chat_service.ask("4004001010")
    assert answer["success"] and answer["source"] == "hs_code"
    body = answer["data"]["answer"]
    assert "4004.00-1010" in body
    assert "확정 분류가 아닙니다" in body


def test_없는_10자리는_앞_6자리_아래를_보여_준다(app):
    """뒤 네 자리만 틀린 일이 흔합니다. 없다고만 하면 다음에 할 일이 없습니다."""

    from app.services import support_chat_service

    with app.app_context():
        body = support_chat_service.ask("2402200000")["data"]["answer"]
    assert "2402.20-1000" in body and "2402.20-9000" in body
    assert "담배" in body


def test_아예_없는_부호에는_요건이_없다고_말하지_않는다(app):
    """없는 부호를 '걸리는 요건 없음'이라고 하면 안전하다고 말하는 꼴입니다."""

    from app.services import support_chat_service

    with app.app_context():
        body = support_chat_service.ask("9999999999")["data"]["answer"]
    assert "이 부호가 없습니다" in body
    assert "걸리는 요건이 없습니다" not in body


def test_부호가_아닌_숫자는_되묻는다(app):
    from app.services import support_chat_service

    with app.app_context():
        assert support_chat_service.ask("12345")["source"] == "clarification"


# --- 한국어 계약서 · PDF 에서 읽은 모양 -------------------------------------------------
#
# 한국어 계약 문구 26개로 확인해 보니 8개가 안 잡혔고, 그중 **7개가 독소조항**이었습니다.
# 한국어로 쓴 계약서는 무제한 손해배상·일방적 해지권·상대국 전속관할·최혜대우가
# 그대로 통과했습니다. 규칙이 "물품 명세"처럼 토씨 없는 말만 찾고 있었기 때문입니다.
# (2026-09-26)

KO_CLAUSES = {
    "goods": "제1조 (물품의 명세) 물품의 품명, HS부호, 규격 및 수량은 별지 1과 같다.",
    "title": "제10조 (소유권 유보) 물품의 소유권은 대금이 전액 지급될 때까지 매도인에게 유보된다.",
    "unlimited_damages": "제17조 매도인은 모든 직접·간접 손해를 한도 없이 배상한다.",
    "termination_at_will": "제18조 매수인은 사유를 불문하고 언제든지 본 계약을 해지할 수 있다.",
    "foreign_forum": "제19조 본 계약에 관한 소송은 매수인 소재지 법원을 전속적 관할법원으로 한다.",
    "payment_on_resale": "제20조 매수인은 최종 고객에게 재판매하여 대금을 수령한 후 지급한다.",
    "term_conflict": "제23조 인코텀즈 조건에도 불구하고 매도인은 최종 목적지 인도 시까지 "
                     "모든 위험과 비용을 부담한다.",
    "mfn_price": "제25조 매도인은 다른 어떠한 고객에게 제공하는 가격보다 불리하지 아니한 "
                 "최혜 가격을 제공한다.",
    "full_return": "제26조 불합격 시 매수인은 전량을 반품할 수 있으며, 반송 운임은 매도인이 부담한다.",
}


@pytest.mark.parametrize("key,text", sorted(KO_CLAUSES.items()))
def test_한국어_계약서에서도_조항이_보인다(key, text):
    assert key in contract_clauses.find_in(text)


# 정상적으로 쓴 조항이 독소조항으로 찍히면, 이용자는 바이어에게 "이 문구를 빼 달라"고
# 하고 바이어는 "그런 문구 없다"고 합니다. 한 번에 신뢰가 무너집니다.
KO_NORMAL = [
    "제13조 (책임 한도) 총 손해배상 한도는 송장금액을 초과하지 아니하며, "
    "간접손해는 배상하지 아니한다.",
    "제17조 (해지) 상대방이 계약을 중대하게 위반하고 30일 내 시정하지 아니한 경우 해지할 수 있다.",
    "제18조 (관할) 소송이 필요한 경우 서울중앙지방법원을 관할법원으로 한다.",
    "제19조 (반품) 하자가 확인된 수량에 한하여 반품할 수 있으며, 비용은 귀책 당사자가 부담한다.",
    "제20조 (배상) 당사자는 자신의 귀책사유로 발생한 손해를 배상한다.",
    "제21조 (가격) 단가는 별지 2의 가격표에 따르며, 연 1회 협의하여 조정할 수 있다.",
]


@pytest.mark.parametrize("text", KO_NORMAL)
def test_정상_한국어_조항은_독소조항으로_찍히지_않는다(text):
    toxic = {row["key"] for row in contract_clauses.CLAUSES if row["category"] == "toxic"}
    assert not (contract_clauses.find_in(text) & toxic)


def test_줄_끝에서_하이픈으로_갈린_낱말을_도로_붙인다():
    """PDF 는 제 폭대로 줄을 꺾으며 긴 낱말을 자릅니다. 다른 왜곡은 다 견디는데
    이것만 조항을 4.5%에서 놓쳤습니다."""

    assert "uncapped_ld" in contract_clauses.find_in(
        "The Seller shall pay liqui-\ndated damages of 1% for each day of delay.")


def test_쪽_머리글이_문장_한가운데_끼어도_찾는다():
    """계약서는 여러 쪽입니다. 쪽 번호·머리글이 문장을 끊습니다."""

    paper = ("The Seller shall not sell the Goods to any third party at a price lower than\n"
             "- 16 -\n"
             "SALES CONTRACT (cont'd)\n"
             "that offered to the Buyer, and shall refund the difference.")
    assert "mfn_price" in contract_clauses.find_in(paper)


def test_별지_제목만_있는_줄은_물품_명세가_아니다():
    """'Annex 1: Specification (attached)' 한 줄에도 물품 명세가 있다고 했습니다."""

    assert "goods" not in contract_clauses.find_in("Annex 1: Specification (attached)")
