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


def test_모델_파일이_json_으로_읽힌다():
    json.loads(ct.MODEL_PATH.read_text(encoding="utf-8"))
