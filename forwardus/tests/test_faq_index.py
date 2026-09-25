"""FAQ 지식베이스 검색·캐시.

빨라지는 것보다 "틀린 답을 자신 있게 돌려주지 않는 것"이 중요합니다.
그래서 여기서 보는 것은 대부분 '바로 답하지 않고 AI로 넘기는' 쪽입니다.
"""

from __future__ import annotations

import json

import pytest

from app.services import faq_cache, faq_index


@pytest.fixture()
def kb(tmp_path, monkeypatch):
    """작은 시험용 지식베이스. 실제 faq.jsonl과 무관하게 규칙만 봅니다."""

    rows = [
        {"id": "T-001", "category": "견적·계약·Incoterms",
         "question": "FOB와 CIF는 무엇이 다른가요?",
         "question_variants": ["fob cif 차이", "본선인도와 운임보험료포함 차이", "FOB랑 CIF 뭐가 달라요"],
         "short_answer": "비용 분기점이 다릅니다.", "detailed_answer": "결론 ... 처리 ... 주의 ...",
         "required_context": [], "cautions": ["계약서 문구가 우선합니다"],
         "keywords": ["fob", "cif", "인코텀즈", "운임", "보험", "가격조건"],
         "sources": [{"name": "ICC", "url": "https://iccwbo.org", "checked_on": None}],
         "applicability": {"countries": ["전체"], "items": ["전체"], "terms": ["FOB", "CIF"]},
         "freshness": "안정적 지식", "review_status": "전문가 검토 필요", "version": "1",
         "review": {"review_status": "approved", "reviewer": "김관세 관세사",
                    "reviewed_at": "2026-09-20T10:00:00+09:00", "approved_version": "1",
                    "review_notes": ""}},
        {"id": "T-002", "category": "HS 코드·수출신고·통관",
         "question": "HS 코드는 어떻게 확인하나요?",
         "question_variants": ["hs코드 찾는 법", "품목분류 어떻게 하나요", "에이치에스코드 확인"],
         "short_answer": "관세청에서 확인합니다.", "detailed_answer": "결론 ... 처리 ... 주의 ...",
         "required_context": ["품명", "재질"], "cautions": ["최종 판단은 세관"],
         "keywords": ["hs", "품목분류", "관세청", "사전심사", "통관", "수출신고"],
         "sources": [{"name": "관세청", "url": "https://www.customs.go.kr", "checked_on": None}],
         "applicability": {"countries": ["전체"], "items": ["전체"], "terms": ["전체"]},
         "freshness": "안정적 지식", "review_status": "전문가 검토 필요", "version": "1",
         "review": {"review_status": "approved", "reviewer": "김관세 관세사",
                    "reviewed_at": "2026-09-20T10:00:00+09:00", "approved_version": "1",
                    "review_notes": ""}},
        {"id": "T-003", "category": "운송·포워딩·보험·선적 일정",
         "question": "부산에서 로스앤젤레스까지 해상운임은 얼마인가요?",
         "question_variants": ["미주 서안 운임 시세", "la 해상운임", "부산 la 운임"],
         "short_answer": "그때그때 다릅니다. 조회해야 합니다.",
         "detailed_answer": "결론 ... 처리 ... 주의 ...",
         "required_context": ["컨테이너 종류"], "cautions": ["성수기 할증"],
         "keywords": ["운임", "해상", "시세", "부산", "la", "포워더"],
         "sources": [{"name": "한국무역협회", "url": "https://www.kita.net", "checked_on": None}],
         "applicability": {"countries": ["US"], "items": ["전체"], "terms": ["전체"]},
         "freshness": "실시간 확인 필요", "review_status": "전문가 검토 필요", "version": "1",
         "review": {"review_status": "approved", "reviewer": "김관세 관세사",
                    "reviewed_at": "2026-09-20T10:00:00+09:00", "approved_version": "1",
                    "review_notes": ""}},
    ]
    path = tmp_path / "faq.jsonl"
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                    encoding="utf-8")
    meta = tmp_path / "faq_meta.json"
    meta.write_text(json.dumps({"kb_version": "test1", "thresholds": {
        "direct": 0.5, "direct_high_risk": 0.6, "margin": 0.05, "context": 0.2}}), encoding="utf-8")
    monkeypatch.setattr(faq_index, "FAQ_PATH", path)
    monkeypatch.setattr(faq_index, "META_PATH", meta)
    faq_index.load(force=True)
    faq_cache.clear()
    yield rows
    faq_index._state.clear()
    faq_index.search.cache_clear()


def test_표기가_흔들려도_같은_FAQ를_찾는다(kb):
    for question in ["FOB와 CIF 차이가 뭔가요", "fob cif 차이점이먼가요", "에프오비랑 씨아이에프 차이",
                     "fob랑cif뭐가다른가요"]:
        hits = faq_index.search(question, 3)
        assert hits and hits[0][0]["id"] == "T-001", question


def test_맞는_질문은_바로_답한다(kb):
    verdict = faq_index.decide("FOB와 CIF는 무엇이 다른가요?")
    assert verdict["route"] == "faq_direct" and verdict["faq"]["id"] == "T-001"
    answer = faq_index.answer_text(verdict["faq"])
    # 출처와 "최종 확인은 전문가에게"가 반드시 붙습니다.
    assert "ICC" in answer and "확인" in answer


def test_조건이_얽힌_질문은_바로_답하지_않는다(kb):
    verdict = faq_index.decide("베트남에 화장품을 DDP로 보내는데 L/C 90일이면 FOB와 CIF 중 뭐가 낫나요")
    assert verdict["route"] != "faq_direct"
    assert verdict["reasons"]        # 왜 바로 답하지 않는지 이유가 남아야 합니다


def test_실시간_확인이_필요한_FAQ는_바로_답하지_않는다(kb):
    verdict = faq_index.decide("부산에서 로스앤젤레스까지 해상운임은 얼마인가요?")
    assert verdict["route"] != "faq_direct"


def test_지식베이스_밖_질문은_FAQ를_붙이지_않는다(kb):
    for question in ["점심 뭐 먹을까요", "파이썬 리스트 정렬하는 법", "부동산 취득세율 알려줘"]:
        assert faq_index.decide(question)["route"] == "llm", question


def test_질문의_나라를_안_다루는_FAQ는_바로_답하지_않는다(kb):
    # T-003은 미국 운임 FAQ입니다. 인도 운임을 물으면 그대로 돌려주면 안 됩니다.
    verdict = faq_index.decide("인도까지 해상운임 얼마인가요")
    assert verdict["route"] != "faq_direct"


def test_캐시는_지식베이스_버전과_함께_묶인다(kb):
    payload = {"answer": "답"}
    faq_cache.put("fob cif 차이", False, "test1", payload, "안정적 지식")
    assert faq_cache.get("fob cif 차이", False, "test1") == payload
    # 지식베이스가 바뀌면 예전 답은 쓰지 않습니다.
    assert faq_cache.get("fob cif 차이", False, "test2") is None


def test_실시간_정보는_캐시에_담지_않는다(kb):
    faq_cache.put("부산 la 운임", False, "test1", {"answer": "답"}, "실시간 확인 필요")
    assert faq_cache.get("부산 la 운임", False, "test1") is None


def test_개인정보가_섞인_질문과_대화중_질문은_캐시하지_않는다(kb):
    assert faq_cache.cacheable("FOB가 뭔가요", [], "") is True
    assert faq_cache.cacheable("FOB가 뭔가요", [{"role": "user", "content": "앞 대화"}], "") is False
    assert faq_cache.cacheable("FOB가 뭔가요", [], "지난 상담 요약") is False
    assert faq_cache.cacheable("담당자 메일 buyer@abc.com 로 보내면 되나요", [], "") is False
    assert faq_cache.cacheable("계좌 110123456789로 받아도 되나요", [], "") is False


def test_상담_흐름이_FAQ를_먼저_쓰고_AI를_부르지_않는다(kb, monkeypatch):
    from app.services import support_chat_service

    called = {"count": 0}

    def fake_chat(*args, **kwargs):
        called["count"] += 1
        return {"success": True, "source": "api", "data": "AI 답"}

    monkeypatch.setattr(support_chat_service.ai_client, "chat", fake_chat)

    first = support_chat_service.ask("FOB와 CIF는 무엇이 다른가요?")
    assert first["source"] == "faq" and called["count"] == 0
    assert first["data"]["faq_id"] == "T-001"

    # 같은 질문을 또 물으면 캐시에서 꺼냅니다. 이때도 AI를 부르지 않습니다.
    second = support_chat_service.ask("FOB와 CIF는 무엇이 다른가요?")
    assert second["source"] == "cache" and called["count"] == 0

    # 지식베이스 밖 질문은 예전처럼 AI에게 갑니다.
    third = support_chat_service.ask("점심 뭐 먹을까요")
    assert third["source"] == "api" and called["count"] == 1
