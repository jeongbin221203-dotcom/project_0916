"""국가·바이어 유형별 독소조항 — **걸리면 안 되는 것부터** 봅니다.

왜 이 파일이 있나
  2026-10-02 에 조항을 33 -> 43개로 늘렸습니다. 늘리면서 세 번 같은 실수를
  되풀이했고, 전부 **걸리면 안 되는 문장을 먼저 두었을 때만** 드러났습니다.

    방향    "The Buyer shall indemnify the Seller against GDPR fines" 는 우리에게
            **유리**한데 독소로 짚었습니다. 같은 낱말이 쓰이므로 방향을 안 보면
            유리한 조항을 지우라고 하게 됩니다. (GDPR·집단소송·기술자료 셋)
    앞쪽 부정 "No chargebacks shall be permitted" 는 좋은 문장인데 짚었습니다.
            뒤를 보는 가드로는 못 걸립니다 — 부정이 앞에 있습니다.
    낱말 순서 영어는 "shall provide ... drawings" 로도 쓰고, 한국어는
            "언제든지 ... 점검" 으로도 씁니다. 한쪽만 보면 절반을 놓칩니다.

  그리고 이미 있던 조항 셋도 고쳤습니다. full_return 은 **거꾸로** 돌았습니다 —
  "전량 반품을 요구할 수 **없다**"(우리를 보호하는 문장)를 짚고, 실제 독소인
  "전량을 매도인에게 반품할 수 있으며"는 놓쳤습니다.

  오탐이 미탐보다 나쁩니다. 미탐은 못 찾은 것이지만, 오탐은 **멀쩡한 조항을
  지우라고** 하는 것입니다.
"""

from __future__ import annotations

import pytest

from app import create_app
from app.extensions import db
from app.processors import contract_clauses
from config import TestConfig

HEAD = "SALES CONTRACT\n물품매매계약서\n\n"

# 2026-10-02 에 더한 조항 16개.
NEW_KEYS = frozenset({
    # 국가별 — 권리를 잃는 쪽
    "cn_tech_transfer", "cn_trademark_buyer", "eu_gdpr_indemnity",
    "us_class_action_pl", "ru_sanctions_warranty", "gulf_agent_lock",
    # 바이어 유형별 — 대형 유통·브랜드 공급계약의 전형
    "retro_price_deduction", "chargeback_penalty", "audit_rights",
    "exclusive_no_moq",
    # 돈을 못 받는 자리 · 원가가 새는 자리
    "payment_fx_approval", "fx_risk_local", "recall_cost",
    "inspection_buyer_sole", "spec_change_no_price", "tooling_free",
})

# ── 걸리면 안 되는 문장 ─────────────────────────────────────────────────────
#
# 전부 우리에게 **유리하거나 중립**입니다. 하나라도 짚으면 사용자가 멀쩡한
# 조항을 지우게 됩니다.
SAFE = [
    ("기술자료를 주지 않는다",
     "제9조 매도인은 도면·기술자료를 매수인에게 제공하지 아니한다."),
    ("바이어가 우리에게 도면을 준다",
     "Article 9 The Buyer shall provide the Seller with technical drawings for "
     "the Buyer's own design."),
    ("상표는 우리 명의로",
     "제10조 상표는 매도인 명의로 등록하며, 매수인에게는 사용권만 부여한다."),
    ("바이어가 우리에게 GDPR 면책",
     "Article 14 The Buyer shall indemnify the Seller against any fines imposed "
     "under the General Data Protection Regulation."),
    ("바이어가 우리에게 집단소송 면책",
     "Article 15 The Buyer shall indemnify the Seller against all class actions "
     "relating to the Buyer's marketing."),
    ("제재 보증을 하지 않는다",
     "제18조 매도인은 제재 해당 여부에 관하여 어떠한 보증도 하지 아니한다."),
    ("독점이지만 해지는 자유",
     "Article 2 The Agent shall have the exclusive right to distribute the "
     "Products. Either party may terminate upon 90 days' notice."),
    ("소급 적용을 금지",
     "제6조 단가 조정은 장래 주문에만 적용하며, 소급하여 가격을 인하하지 아니한다."),
    ("판촉비를 공제하지 않는다",
     "제6조 판촉 비용은 대금에서 공제하지 아니하고 별도로 정산한다."),
    ("챠지백을 두지 않는다",
     "Article 7 No chargebacks or deductions shall be permitted under this Agreement."),
    ("벌금을 공제하지 않는다",
     "제7조 지체상금은 대금에서 공제하지 아니하고 별도로 청구한다."),
    ("연 1회·사전 통지 감사",
     "Article 11 The Buyer may audit the Seller's records once per calendar year "
     "upon thirty days' prior written notice."),
    ("예고 없이 감사하지 못한다",
     "제11조 매수인은 사전 통지 없이 감사를 실시할 수 없다."),
    ("바이어가 우리에게서만 산다",
     "Article 3 The Buyer shall purchase the Products exclusively from the Seller."),
    ("독점 공급 의무가 아니다",
     "제3조 매도인은 독점으로 공급할 의무가 없다."),
    # ── 2026-10-02 에 더한 여섯 조항의 '좋은 꼴' ─────────────────────────
    #
    # 셋은 **우리가 fix 에서 권하는 바로 그 해결책**입니다. 그걸 독소로 짚으면
    # 고친 조항을 다시 지우라고 하게 됩니다. 실제로 그랬습니다.
    ("L/C 로 받는다 — 승인에 매이지 않음",
     "제5조 대금은 취소불능 일람불 신용장으로 지급하며, 수입허가 지연은 매수인의 "
     "위험으로 한다."),
    ("승인 조건이 **아니다** (영문 부정)",
     "Article 5 Payment shall not be subject to any import licence or exchange "
     "control approval."),
    ("환율 위험은 바이어가",
     "제5조 환율 변동 위험은 매수인이 부담한다."),
    ("달러로 받는다",
     "Article 5 All payments shall be made in US Dollars."),
    ("리콜 비용은 바이어가",
     "제13조 리콜에 드는 비용은 매수인이 부담한다."),
    # fix 가 권하는 꼴 — 우리 결함으로 한정하고 상한을 둠
    ("리콜을 우리 결함으로 한정 + 상한",
     "Article 13 The Seller shall bear recall costs caused solely by the Seller's "
     "manufacturing defect, up to the invoice value."),
    # fix 가 권하는 꼴 — 제3 검사기관이 판정
    ("제3 검사기관(SGS)이 최종 판정",
     "Article 10 In case of dispute, the determination of SGS at the port of "
     "loading shall be final and binding on both parties."),
    ("바이어가 단독으로 정할 수 없다",
     "제10조 합격 여부는 별지의 기준에 따르며, 매수인이 단독으로 정할 수 없다."),
    # fix 가 권하는 꼴 — 규격을 바꾸면 단가를 다시 정함
    ("규격 변경 시 단가 재협의",
     "제4조 매수인이 규격을 변경하는 경우 단가와 납기를 다시 정한다."),
    ("규격 변경은 서면 합의로만",
     "Article 4 Any change to the specifications shall require the written "
     "agreement of both parties."),
    ("금형비를 청구한다",
     "제9조 금형 제작비는 매수인이 부담하며 별도로 청구한다."),
    ("금형을 무상으로 주지 않는다",
     "제9조 금형은 무상으로 제공하지 아니한다."),
    ("보증기간을 12개월로 정함",
     "제13조 하자보증기간은 선적일로부터 12개월로 한다."),
    ("상투어 — including without limitation",
     "Article 1 The Goods shall include, without limitation, packaging, manuals "
     "and spare parts as listed in Annex 1."),
]

# ── 잡아야 하는 문장 ────────────────────────────────────────────────────────
CATCH = [
    ("기술자료 제공 의무 (영문)", "cn_tech_transfer",
     "Article 9 The Seller shall provide the Buyer with complete technical "
     "drawings, bills of materials and manufacturing process documentation."),
    ("도면 제공 (국문)", "cn_tech_transfer",
     "제9조 매도인은 제품의 도면과 제조공정서를 매수인에게 제공하여야 한다."),
    ("상표를 바이어 명의로", "cn_trademark_buyer",
     "Article 10 The Buyer shall register the Seller's trademarks in the "
     "Territory in the Buyer's own name."),
    ("상표를 대리점 명의로 (국문)", "cn_trademark_buyer",
     "제10조 상표는 대리점 명의로 등록한다."),
    ("GDPR 과징금 전가", "eu_gdpr_indemnity",
     "Article 14 The Seller shall indemnify and hold the Buyer harmless against "
     "any fines or penalties imposed under the General Data Protection Regulation."),
    ("제조물책임 무한 면책", "us_class_action_pl",
     "Article 15 The Seller shall defend, indemnify and hold harmless the Buyer "
     "against all product liability claims, including class actions, without "
     "limitation."),
    ("제재 보증·면책", "ru_sanctions_warranty",
     "Article 18 The Seller warrants that the Goods are not subject to any "
     "sanctions and shall indemnify the Buyer for all consequences thereof."),
    ("독점 + 해지 제한 (두 문장에 나뉘어 있어도)", "gulf_agent_lock",
     "Article 2 The Agent shall have the exclusive right to import and distribute "
     "the Products in the Territory. This Agreement may not be terminated "
     "without the Agent's written consent."),
    ("판촉비·리베이트 공제", "retro_price_deduction",
     "Article 6 The Buyer may deduct any agreed rebate, markdown allowance or "
     "promotional funding from any payment due, including retroactively."),
    ("소급 단가 인하 (국문)", "retro_price_deduction",
     "제6조 매수인은 기납품분에 대하여도 소급하여 단가를 인하 적용할 수 있다."),
    ("챠지백·OTIF 벌금", "chargeback_penalty",
     "Article 7 Late or short deliveries shall incur a chargeback of 5% of the "
     "order value, which the Buyer may deduct from any invoice outstanding."),
    ("지체상금 대금 공제 (국문)", "chargeback_penalty",
     "제7조 납기 지연 시 위약금을 매수인이 대금에서 공제한다."),
    ("예고 없는 무제한 감사", "audit_rights",
     "Article 11 The Buyer may audit the Seller's facilities, books and records "
     "at any time without prior notice."),
    ("언제든지 실사 (국문 — 어찌말이 앞)", "audit_rights",
     "제11조 매수인은 언제든지 매도인의 공장을 현장 점검할 수 있다."),
    ("독점 공급 의무", "exclusive_no_moq",
     "Article 3 The Seller shall supply the Products exclusively to the Buyer in "
     "the Territory and shall not sell to any other party therein."),
    ("독점 공급 (국문)", "exclusive_no_moq",
     "제3조 매도인은 해당 지역에서 매수인에게 독점으로 공급하여야 한다."),
]

# ── 전에 거꾸로 돌던 조항들 ─────────────────────────────────────────────────
FIXED_SAFE = [
    ("반품을 제한하는 것 — full_return 이 짚으면 안 됩니다", "full_return",
     "제8조 매수인은 하자 있는 물품에 한하여 인도 후 14일 내에 반품할 수 있고, "
     "그 밖의 사유로는 전량 반품을 요구할 수 없다."),
    ("한국 법원 전속관할 — foreign_forum 이 짚으면 안 됩니다", "foreign_forum",
     "제16조 전속적 합의관할은 서울중앙지방법원으로 한다."),
    ("영문 한국 법원 — foreign_forum 이 짚으면 안 됩니다", "foreign_forum",
     "Article 16 The courts of Seoul shall have exclusive jurisdiction."),
    ("배심재판 포기 — us_jury_punitive 가 짚으면 안 됩니다", "us_jury_punitive",
     "제16조 양 당사자는 배심재판을 받을 권리를 포기한다."),
    ("징벌적 배제 — us_jury_punitive 가 짚으면 안 됩니다", "us_jury_punitive",
     "Article 17 Punitive damages are expressly excluded under this Agreement."),
]

FIXED_CATCH = [
    ("전량 반품 허용 — 낱말 사이에 말이 들어가도", "full_return",
     "제8조 매수인은 사유를 불문하고 인도받은 물품 전량을 매도인에게 반품할 수 있다."),
    ("외국 법원 전속관할", "foreign_forum",
     "제16조 전속적 합의관할은 뉴욕주 법원으로 한다."),
    ("배심재판 동의", "us_jury_punitive",
     "Article 16 The parties hereby consent to trial by jury in any action."),
    ("징벌적 손해배상 허용", "us_jury_punitive",
     "Article 17 The Buyer shall be entitled to punitive damages in addition to "
     "actual damages."),
]


@pytest.mark.parametrize("label,body", SAFE, ids=[row[0] for row in SAFE])
def test_걸리면_안_되는_문장은_독소를_짚지_않는다(label, body):
    """우리에게 유리하거나 중립인 문장. 짚으면 멀쩡한 조항을 지우게 됩니다.

    **새 조항만 보지 않고 독소조항 전부를 봅니다.** 새 조항을 넣다가 옛 조항의
    오탐을 깨울 수 있고, 실제로 그런 일이 있었습니다 — `without limitation` 이
    거의 모든 영문 계약서에서 무제한 손해배상으로 잡히고 있었습니다.
    """

    hits = {key for key in contract_clauses.find_in(HEAD + body)
            if (contract_clauses.by_key(key) or {}).get("category") == "toxic"}
    assert not hits, f"{label}: 오탐 {sorted(hits)}"


@pytest.mark.parametrize("label,want,body", CATCH, ids=[row[0] for row in CATCH])
def test_독소조항을_짚는다(label, want, body):
    hits = contract_clauses.find_in(HEAD + body)
    assert want in hits, f"{label}: {want} 를 놓쳤습니다. 짚은 것 {sorted(hits & NEW_KEYS)}"


@pytest.mark.parametrize("label,key,body", FIXED_SAFE, ids=[row[0] for row in FIXED_SAFE])
def test_고친_조항이_유리한_문장을_짚지_않는다(label, key, body):
    """full_return 은 전에 **거꾸로** 돌았습니다. 부정문을 짚고 독소를 놓쳤습니다."""

    assert key not in contract_clauses.find_in(HEAD + body), f"{label}: 오탐"


@pytest.mark.parametrize("label,key,body", FIXED_CATCH, ids=[row[0] for row in FIXED_CATCH])
def test_고친_조항이_독소를_짚는다(label, key, body):
    assert key in contract_clauses.find_in(HEAD + body), f"{label}: 미탐"


# ── 나라 축 ─────────────────────────────────────────────────────────────────

def test_나라_묶음이_맞다():
    """EU 회원국과 걸프 나라는 묶음으로 함께 걸립니다."""

    assert contract_clauses.groups_for("DE") == {"DE", "EU"}
    assert contract_clauses.groups_for("AE") == {"AE", "GULF"}
    assert contract_clauses.groups_for("KR") == {"KR"}
    assert contract_clauses.groups_for("") == set()


def test_나라별_조항을_골라_준다():
    keys = {row["key"] for row in contract_clauses.for_country("CN")}
    assert {"cn_tech_transfer", "cn_trademark_buyer", "china_domestic_arb"} <= keys
    assert {row["key"] for row in contract_clauses.for_country("FR")} >= {
        "eu_gdpr_indemnity", "agency_law_eu"}
    # 외환 통제가 있는 나라는 대금을 못 받는 쪽, 통화가 흔들리는 나라는 환차손 쪽.
    assert {row["key"] for row in contract_clauses.for_country("IN")} >= {
        "payment_fx_approval", "fx_risk_local"}
    assert "fx_risk_local" in {row["key"] for row in contract_clauses.for_country("TR")}
    # **억지로 채우지 않습니다.** 우리가 내보내는 나라(한국)에는 도착국 함정이
    # 없고, 그 나라에 특히 흔한 것이 없으면 빈 목록이어야 합니다. 아무 조항이나
    # 달아 두면 "이 나라에서 특히 흔하다"는 말을 믿을 수 없게 됩니다.
    assert contract_clauses.for_country("KR") == []


def test_나라는_찾는_일에_쓰이지_않는다():
    """도착국을 몰라도 다 찾아야 합니다.

    중국 중재 조항은 어디로 보내든 독소입니다. 나라를 찾는 조건으로 쓰면
    도착국을 안 적은 사람에게는 아무것도 안 찾아 주게 됩니다.
    """

    body = HEAD + ("제15조 분쟁은 중국국제경제무역중재위원회(CIETAC) 베이징에서 "
                   "중재로 해결한다.")
    assert "china_domestic_arb" in contract_clauses.find_in(body)


class _FakeShipment:
    def __init__(self, country="", code=""):
        self.destination_country = country
        self.destination_code = code


@pytest.mark.parametrize("country,code,want", [
    ("NL · 네덜란드", "NLRTM", "NL"),
    ("US · 미국", "USLAX", "US"),
    ("CN", "", "CN"),
    ("", "CNSHA", "CN"),
    ("", "AEJEA", "AE"),
    # 나라 칸이 한글만 있으면 도착지 부호로 넘어갑니다.
    ("네덜란드", "NLRTM", "NL"),
    # **한글만 있고 부호도 없으면 비웁니다.** 파이썬 isalpha() 는 한글도 True 라서
    # 전에는 "중국" 에서 "중국" 을 국가코드로 내놓았습니다. (2026-10-02)
    ("중국", "", ""),
    # 공항 부호(IATA)는 나라를 담지 않습니다. 억지로 맞추지 않습니다.
    ("", "ICN", ""),
    ("", "", ""),
])
def test_도착국을_ISO_두_글자로_꺼낸다(country, code, want):
    from app.services import contract_clause_service

    got = contract_clause_service.country_of(_FakeShipment(country, code))
    assert got == want, f"country={country!r} code={code!r} -> {got!r}"


@pytest.fixture()
def client():
    flask_app = create_app(TestConfig)
    with flask_app.app_context():
        db.create_all()
        yield flask_app.test_client()
        db.session.remove()
        db.drop_all()


def test_도착국을_주면_그_나라_조항을_앞세운다(client):
    got = client.get("/contract/clauses?incoterms=FOB&country=CN").get_json()["data"]
    toxic = got["groups"]["toxic"]
    assert got["country"] == "CN"
    assert set(got["country_watch"]) >= {"cn_tech_transfer", "cn_trademark_buyer"}
    # 앞의 세 줄이 중국 것입니다.
    assert all(row["for_country"] for row in toxic[:3]), \
        [row["key"] for row in toxic[:3]]
    # 나머지는 그대로 있습니다 — 걸러 내는 것이 아니라 순서만 바꿉니다.
    assert len(toxic) == len([r for r in contract_clauses.CLAUSES
                              if r["category"] == "toxic"])


def test_도착국이_없어도_그대로_돈다(client):
    got = client.get("/contract/clauses?incoterms=FOB").get_json()["data"]
    assert got["country"] == ""
    assert got["country_watch"] == []
    assert len(got["groups"]["toxic"]) >= 25


def test_계약서에_없는_그_나라_함정을_미리_알려_준다(client):
    """올리기 전에도 경고할 수 있어야 합니다.

    운송 계획에 도착국이 이미 적혀 있으므로, 계약서를 받기 전에 "중국으로
    보내시는군요 — 이 셋을 특히 보세요"를 말할 수 있습니다.
    """

    body = HEAD + "제5조 매수인은 선적서류 제시 후 30일 내에 대금을 지급한다."
    got = client.post("/contract/review",
                      json={"text": body, "incoterms": "FOB", "country": "CN"})
    data = got.get_json()["data"]
    assert data["country"] == "CN"
    assert not data["toxic"], "이 글에는 독소조항이 없습니다"
    watch = {row["key"] for row in data["watch_country"]}
    assert {"cn_tech_transfer", "cn_trademark_buyer"} <= watch
