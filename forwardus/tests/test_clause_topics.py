"""계약 조항 주제 분류기 — 규칙이 놓친 조항을 '직접 확인'으로 띄웁니다.

왜 이 파일이 있나 (2026-10-03)
  규칙은 처음 보는 표현을 놓칩니다. 공개 계약 자료(CUAD·LEDGAR·SEC EDGAR)로
  만든 주제 분류기가 그 빈틈을 메웁니다. 여기서 지키는 것:

    - 규칙에 없는 표현을 **띄운다**  (만든 이유)
    - 계약서가 아닌 문서·국문에서 **안 띄운다**  (오탐이 미탐보다 나쁩니다)
    - 규칙이 이미 본 주제는 **되풀이하지 않는다**
    - 판정(독소·필수)을 **바꾸지 않는다**
    - 학습과 서버가 **같은 계산**을 한다
"""

from __future__ import annotations

import json

import pytest

from app.processors import clause_topics as ct
from app.processors import contract_clauses as cc
from app.services import contract_clause_service as svc

CATEGORY = {row["key"]: row["category"] for row in cc.CLAUSES}

# 일부러 규칙 낱말을 피해 쓴 문장 — 규칙은 놓치고, 분류기는 띄워야 합니다.
UNSEEN = [
    ("jurisdiction", "Each party irrevocably submits to the courts sitting in the Borough of "
                     "Manhattan for any action relating to this Agreement and waives any "
                     "objection to venue."),
    ("indemnity", "The Supplier shall defend and hold harmless the Purchaser from all third-party "
                  "claims, suits and judgments arising from the Products."),
    ("assignment", "Neither party may transfer or delegate any rights or obligations hereunder "
                   "without the prior written approval of the other."),
    ("force_majeure", "Neither party shall be responsible for failure to perform caused by fire, "
                      "flood, war, riot, strikes, epidemics or acts of government."),
    ("insurance", "Supplier shall maintain commercial general liability coverage of not less than "
                  "USD 2,000,000 per occurrence naming Purchaser as additional insured."),
    ("audit", "Upon reasonable notice the Purchaser may examine and copy the Supplier's books and "
              "records relating to the Products."),
    ("jury_waiver", "EACH PARTY HEREBY KNOWINGLY AND VOLUNTARILY GIVES UP ITS RIGHT TO A TRIAL BY "
                    "JURY IN ANY PROCEEDING."),
]

NOT_CONTRACTS = [
    "Dear Mr. Kim, Thank you for your offer. We would like to order 1,200 pcs. Please send the "
    "original B/L by courier once you receive our T/T payment. Best regards, John",
    "COMMERCIAL INVOICE Invoice No. FW-0041 Date: 2026-10-02 Shipper: FORWARDUS Consignee: "
    "Buyer GmbH Terms: FOB Busan, Incoterms 2020 Payment: T/T 30 days",
    "Seoul, Oct 2 - Korean exporters face higher tariffs as the US raised customs duties on "
    "steel. Analysts said suppliers may need to absorb part of the increase.",
]


def _candidates(doc: str) -> list[dict]:
    return ct.candidates(doc, cc.analyze(doc)["clauses"], CATEGORY)


def test_모델이_있고_출처를_밝힌다():
    model = ct.model()
    assert model, "data/processed/clause_topics.json 이 없습니다 (data/build_clause_topics.py)"
    assert any("CUAD" in s for s in model["sources"])
    assert any("LEDGAR" in s for s in model["sources"])
    assert "other" in model["classes"]


def test_쓰는_주제는_모두_정밀도_90_이상():
    report = ct.model()["report"]
    for topic, info in ct.model()["topics"].items():
        if info.get("threshold") is None:
            continue
        assert report[topic]["precision"] >= 0.9, (topic, report[topic])


def test_무역_주제가_들어_있다():
    """CUAD·LEDGAR 에 없던 것 — EDGAR 공급계약서의 조항 제목으로 채웠습니다."""

    topics = ct.model()["topics"]
    for topic in ("delivery", "inspection", "title", "packing", "force_majeure"):
        assert topics.get(topic, {}).get("threshold") is not None, topic


@pytest.mark.parametrize("topic,line", UNSEEN, ids=[t for t, _ in UNSEEN])
def test_규칙이_놓친_표현을_띄운다(topic, line):
    doc = "SALES CONTRACT\n" + line
    keys = ct.model()["topics"][topic]["keys"]
    assert not set(keys) & set(cc.analyze(doc)["clauses"]), "규칙이 이미 잡았습니다 — 예문을 바꾸세요"
    assert topic in {c["topic"] for c in _candidates(doc)}


@pytest.mark.parametrize("doc", NOT_CONTRACTS, ids=["메일", "송장", "기사"])
def test_계약서가_아닌_문서에서는_안_띄운다(doc):
    assert not _candidates(doc)


def test_국문_조항은_분류하지_않는다():
    """학습 자료가 거의 영문입니다(국문 302문장). 국문은 규칙으로만 판정합니다.

    영문 제목이 붙은 국문 조항("제22조 (Assignment) …")은 제목 덕에 주제가 맞게
    나오기도 하지만, 국문 판단을 믿을 근거가 부족해 **일부러** 보지 않습니다.
    이 선택을 바꾸려면 국문 학습 자료부터 늘려야 합니다. (2026-10-03)
    """

    doc = "제22조 (Assignment) 어느 당사자도 상대방의 사전 서면 동의 없이 권리를 넘길 수 없다."
    assert ct.classify(doc), "장치가 없으면 뜨는 예문이어야 시험이 됩니다"
    assert not _candidates(doc)


def test_차가_작은_후보는_띄우지_않는다():
    """주제별 문턱은 넘어도 차가 1.4 아래면 버립니다. 짧은 무역 문장에서 틀렸습니다.

    사양 변경 조항을 '인도'로 봤습니다(차 1.23). (2026-10-03)
    """

    line = ("Article 4 The Buyer may change the specifications or packaging at any time, and "
            "such change shall not affect the price or the delivery date.")
    (top, topic), (second, _) = ct.score(line)[:2]
    threshold = ct.model()["topics"][topic]["threshold"]
    assert threshold <= top - second < ct.MIN_MARGIN, "주제 문턱은 넘고 최저선은 못 넘는 예문이어야 합니다"
    assert ct.classify(line) is None


def test_규칙이_본_주제는_되풀이하지_않는다():
    doc = ("SALES CONTRACT\nArticle 14 This Contract shall be governed by the laws of Korea.\n"
           "Article 15 The validity and performance of this contract are to be determined "
           "under the laws of England and Wales.\n")
    assert "governing_law" in cc.analyze(doc)["clauses"]
    assert "governing_law" not in {c["topic"] for c in _candidates(doc)}


def test_판정을_바꾸지_않는다():
    """빠진 필수조항은 빠진 채로 두고 '이 문장일 수 있습니다'만 덧붙입니다."""

    doc = ("SALES CONTRACT\nArticle 17 Neither party shall be responsible for failure to "
           "perform caused by fire, flood, war, riot, strikes, epidemics or acts of government.\n")
    result = svc.review(doc)
    fm = next(row for row in result["missing"] if row["key"] == "force_majeure")
    assert "flood" in fm["maybe"]
    assert "force_majeure" not in result["present"]


def test_학습과_서버가_같은_계산을_한다():
    """빌드 스크립트의 score 와 서버의 score 가 같은 1위·같은 차를 내야 문턱이 맞습니다."""

    import importlib.util
    from pathlib import Path

    path = Path(ct.__file__).resolve().parents[2] / "data" / "build_clause_topics.py"
    spec = importlib.util.spec_from_file_location("build_clause_topics", path)
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    model = ct.model()
    for _topic, line in UNSEEN:
        topic, margin = build.score(model, line)
        ranked = ct.score(line)
        assert topic == ranked[0][1]
        assert abs(margin - (ranked[0][0] - ranked[1][0])) < 1e-6


def test_모델이_없으면_조용히_빈_답(monkeypatch, tmp_path):
    monkeypatch.setattr(ct, "MODEL_PATH", tmp_path / "없음.json")
    ct.model.cache_clear()
    try:
        assert ct.candidates("SALES CONTRACT Neither party shall be responsible for fire.",
                             {}, CATEGORY) == []
        assert ct.classify("anything") is None
    finally:
        ct.model.cache_clear()


# ── 조항 제목 (2026-10-03) ──────────────────────────────────────────────────
# 분류기는 국문을 못 보고 영문도 절반쯤만 띄웁니다. 계약서는 거의 언제나 조항에
# 제목을 답니다 — 국문도. 제목이 주제를 말하면 학습 자료 없이도 정확합니다.

HEADS = [
    ("제14조(권리의 양도) 어느 당사자도 …", "assignment"),
    ("제20조(계약상 지위의 이전) …", "assignment"),
    ("제11조(손해배상의 제한) …", "liability_cap"),      # '배상'이 아니라 '책임 한도'
    ("제6조(선적 전 검사) …", "inspection"),              # '선적'이 아니라 '검사'
    ("제8조(계약의 해지 및 손해배상) …", "termination"),
    ("제2조(물품의 인도) …", "delivery"),
    ("제16조(상계) …", "set_off"),
    ("제22조 [최혜 대우] …", "mfn"),
    ("Article 7 Force Majeure. Neither party …", "force_majeure"),
    ("12. GOVERNING LAW: This Contract …", "governing_law"),
    ("Section 9 - Most Favored Customer - Supplier …", "mfn"),
    ("Article 14 Set-off. The Buyer …", "set_off"),
]
NOT_HEADS = [
    "제1조(목적) 본 계약은 …",
    "제21조(기타) …",
    "제4조(규격 변경) 매수인이 규격을 변경하는 경우 단가와 납기를 다시 정한다.",   # 계약 변경이 아님
    "Article 12 The Buyer shall pay the price within 30 days.",                     # 제목이 아님
    "Article 3 This Contract shall not be automatically renewed.",
]


@pytest.mark.parametrize("head,topic", HEADS, ids=[h[:14] for h, _ in HEADS])
def test_조항_제목으로_주제를_안다(head, topic):
    found = ct.heading_topic(head)
    assert found and found["topic"] == topic


@pytest.mark.parametrize("head", NOT_HEADS, ids=[h[:14] for h in NOT_HEADS])
def test_주제가_아닌_제목은_넘어간다(head):
    found = ct.heading_topic(head)
    assert not found or found["topic"] != "amendment"
    if "목적" in head or "기타" in head or "Article" in head:
        assert found is None


def test_국문_계약서에서_규칙이_놓친_조항을_제목으로_띄운다():
    doc = ("물품매매계약서\n제1조(목적) 본 계약은 물품 공급 조건을 정한다.\n"
           "제14조(권리의 양도) 어느 당사자도 상대방의 사전 서면 승낙 없이 이 계약상 지위를 "
           "넘기지 못한다.\n")
    assert "assignment" in {c["topic"] for c in _candidates(doc)}


def test_목차에_속지_않는다():
    """목차를 그대로 두면 "제12조(비밀유지) …… 5" 가 줄마다 후보가 됩니다."""

    doc = ("SALES CONTRACT\n목차\n제7조(불가항력) ........ 3\n제9조(준거법) ........ 4\n"
           "제12조(비밀유지) ........ 5\n제14조(권리의 양도) ........ 6\n제15조(보험) ........ 6\n"
           "제16조(상계) ........ 7\n제1조(목적) 본 계약은 물품 공급 조건을 정한다.\n")
    assert not _candidates(doc)


# ── 수출자 입장 (2026-10-03) ───────────────────────────────────────────────
# '직접 확인' 조항에 우리(매도인) 입장을 붙입니다. 가장 나쁜 실수는 **불리한
# 조항을 유리하다고** 하는 것이라, 그런 꼴(U)을 따로 모아 지킵니다.

STANCE = [
    # F 유리 · U 불리 · M 쌍방 · ? 확인 필요
    ("Article 20 Neither party may assign this Contract without consent.", "assignment", "M"),
    ("3. EXCLUSIVITY: The Seller shall supply the Products exclusively to the Buyer.", "exclusivity", "U"),
    ("The Buyer shall indemnify the Seller against all class actions.", "indemnity", "F"),
    ("The Seller shall indemnify the Buyer against all third-party claims.", "indemnity", "U"),
    ("Article 16 The courts of Seoul shall have exclusive jurisdiction.", "jurisdiction", "F"),
    ("제18조 (관할) 서울중앙지방법원을 관할법원으로 한다.", "jurisdiction", "F"),
    ("The courts of New York shall have exclusive jurisdiction.", "jurisdiction", "U"),
    ("Each Party irrevocably waives any right to trial by jury.", "jury_waiver", "F"),
    ("Punitive damages are expressly excluded under this Agreement.", "liability_cap", "F"),
    ("Neither Party shall be liable for consequential damages.", "liability_cap", "F"),
    ("The Buyer shall be entitled to punitive damages.", "liability_cap", "U"),
    ("The Seller shall not be liable for any indirect loss.", "liability_cap", "F"),
    ("The Seller's liability shall not exceed the invoice value.", "liability_cap", "F"),
    ("The Buyer may terminate this Contract at any time upon notice.", "termination", "U"),
    ("The Seller may terminate this Contract if payment is overdue.", "termination", "F"),
    ("The Buyer may not set off any claim against the price.", "set_off", "F"),
    ("All payments shall be made in US Dollars.", "payment", "?"),
    ("매수인은 매도인의 동의 없이 계약을 해지할 수 있다.", "termination", "U"),
    ("매도인은 대금이 연체되면 계약을 해지할 수 있다.", "termination", "F"),
    ("매도인은 간접손해에 대하여 책임을 지지 아니한다.", "liability_cap", "F"),
    ("매수인은 제3자의 청구로부터 매도인을 면책한다.", "indemnity", "F"),       # '면책한다' = 지켜 줄 의무
    ("어느 당사자도 상대방의 중대한 위반이 있는 경우에만 해지할 수 있다.", "termination", "M"),
]
# 불리한데 유리로 읽히기 쉬운 꼴 — F 가 나오면 안 됩니다
NEVER_FAVORABLE = [
    ("Goods made in Korea shall be governed by the laws of New York.", "governing_law"),
    ("The Korean exporter submits to the courts of Singapore.", "jurisdiction"),
    ("Arbitration shall be seated in Hong Kong; the language shall be Korean.", "disputes"),
    ("The Seller may not terminate this Contract for any reason.", "termination"),
    ("The Seller shall be entitled to no compensation upon termination.", "termination"),
    ("The Seller may only claim within 7 days, failing which all claims are waived.", "warranty"),
    ("The Seller may be deemed to have waived its right to claim after 7 days.", "warranty"),
    ("The Buyer shall have the right to reject the goods at its sole discretion.", "inspection"),
    ("The Buyer shall not be required to pay until resale.", "payment"),
    ("매도인은 계약을 해지할 수 없다.", "termination"),
    ("매도인은 어떠한 경우에도 가격을 인상하지 못한다.", "price"),
]
CODE = {"favorable": "F", "unfavorable": "U", "mutual": "M", "unclear": "?"}


@pytest.mark.parametrize("text,topic,want", STANCE, ids=[t[:24] for t, _, _ in STANCE])
def test_수출자_입장을_판정한다(text, topic, want):
    assert CODE[ct.stance(text, topic)["stance"]] == want


@pytest.mark.parametrize("text,topic", NEVER_FAVORABLE, ids=[t[:24] for t, _ in NEVER_FAVORABLE])
def test_불리한_조항을_유리하다고_하지_않는다(text, topic):
    assert ct.stance(text, topic)["stance"] != "favorable"


def test_PartyAB_계약서는_우리_쪽으로_바꿔_읽고_판정한다():
    """Party A 가 우리(Party B) 장부를 본다 — 상대 권리라 불리합니다."""

    doc = ("CONTRACT between the following parties concerned: Acme Inc., hereinafter referred to "
           "as Party A, having its head office at Tokyo, Japan, and Hana Co., Ltd., hereinafter "
           "referred to as Party B, having its head office at Seoul, Korea. Whereas the parties "
           "agree as follows.\nArticle 17 Upon reasonable notice Party A may examine and copy the "
           "books and records of Party B relating to the Products.\n")
    audit = [c for c in _candidates(doc) if c["topic"] == "audit"]
    assert audit and audit[0]["stance"] == "unfavorable"
    assert "Party A may examine" in audit[0]["sentence"]     # 보여 주는 문장은 원문 그대로


def test_모델_파일이_json_으로_읽힌다():
    json.loads(ct.MODEL_PATH.read_text(encoding="utf-8"))
