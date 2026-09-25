"""미리 정리해 둔 실무 자료로 바로 답하는지 확인합니다.

지키려는 것은 둘입니다.
  1. 흔한 질문은 AI를 부르지 않고 **그 자리에서** 답한다. (기다림이 없어야 합니다)
  2. 자료를 찾아야 하는 질문은 가로채지 않는다. (실적·세율·이 사람 건의 운임)
"""

from __future__ import annotations

import re

import pytest

from app.processors import country_export_guide
from app.services import knowledge_service as knowledge


@pytest.fixture(autouse=True)
def _fresh():
    knowledge.reload()


def test_모든_지식_파일이_읽힌다():
    entries = knowledge.entries()
    assert len(entries) >= 20
    for entry in entries:
        assert entry["title"] and entry["title"] != entry["key"], f"{entry['key']}에 title이 없습니다"
        assert entry["keywords"], f"{entry['key']}에 keywords가 없습니다"
        assert len(entry["body"]) > 400, f"{entry['key']} 본문이 너무 짧습니다"


def test_링크는_모두_주소_모양이다():
    for entry in knowledge.entries():
        for link in entry["links"]:
            assert link["url"].startswith(("http://", "https://", "/")), \
                f"{entry['key']}의 링크가 주소가 아닙니다: {link}"


def test_see가_가리키는_주제가_실제로_있다():
    keys = {entry["key"] for entry in knowledge.entries()}
    for entry in knowledge.entries():
        for key in entry["see"]:
            assert key in keys, f"{entry['key']}가 없는 주제 {key}를 가리킵니다"


@pytest.mark.parametrize("question, key", [
    ("인코텀즈는 어떻게 고르나요?", "incoterms-2020"),
    ("FOB랑 CIF는 어떻게 다른가요?", "incoterms-2020"),
    ("수출신고는 어디서 하나요?", "export-declaration"),
    ("적재의무기한이 뭔가요", "export-declaration"),
    ("LCL FCL 기준이 뭔가요", "lcl-fcl-cbm"),
    ("수출할 때 꼭 필요한 서류가 뭔가요?", "shipping-documents"),
    ("포워더 부킹 어떻게 해요", "forwarder-booking"),
    ("신용장 서류 언제까지 내야 하나요", "letter-of-credit"),
    ("멕시코 NOM 인증이 뭔가요", "cert-mexico-nom"),
    ("중국 CCC 인증 절차 알려줘", "cert-china-ccc"),
    ("일본 PSE 인증 필요한가요", "cert-japan-pse"),
    ("유럽 CE 마킹 어떻게 받나요", "cert-eu-ce"),
    ("미국 FCC 인증 받아야 하나요", "cert-usa"),
    ("관세환급 받을 수 있나요", "duty-drawback"),
    ("HS 코드는 어떻게 찾나요", "hs-code-basics"),
])
def test_흔한_질문은_바로_답한다(question, key):
    found = knowledge.find(question)
    assert found is not None, f"{question} 에 답할 주제를 못 찾았습니다"
    assert found["key"] == key


@pytest.mark.parametrize("question", [
    "우리 회사 화장품을 멕시코에 500박스 보내는데 운임이 얼마나 나올까요",
    "부산에서 LA까지 며칠 걸려요",
    "이 품목 미국 수출 실적 알려줘",
    "안녕하세요",
])
def test_찾아봐야_하는_질문은_가로채지_않는다(question):
    assert knowledge.find(question) is None
    assert knowledge.country(question) is None


def test_인코텀즈는_대화_속_표로_답한다():
    entry = knowledge.find("인코텀즈 알려줘")
    data = knowledge.answer(entry)
    # 글로 그린 표 대신 눌러 보는 표를 띄웁니다.
    assert data["widget"] == "incoterms"
    assert "| 조건 |" not in data["answer"]
    # AI에게 넘기는 참고자료에는 표가 글로 들어갑니다.
    assert "| 조건 |" in knowledge.reference("인코텀즈 알려줘")


def test_답에는_근거와_링크가_붙는다():
    data = knowledge.answer(knowledge.find("수출신고는 어디서 하나요?"))
    assert data["basis"] and "AI" in data["basis"][0]
    assert any("unipass" in link["url"] for link in data["links"])


def test_가까운_주제는_AI_참고자료로_넘어간다():
    # 바로 답하기엔 모자라도, 우리가 정리해 둔 글을 AI가 근거로 씁니다.
    hint = knowledge.reference("컨테이너에 얼마나 실을 수 있나요")
    assert "실무 자료" in hint


class Test국가안내:
    def test_자료가_있는_나라는_상세를_함께_낸다(self):
        data = knowledge.country("멕시코에 수출하려면 어떻게 하나요")
        assert "NOM" in data["body"]
        assert "멕시코 수출 안내" == data["title"]

    def test_자료가_없는_나라도_빈손으로_보내지_않는다(self):
        data = knowledge.country("케냐에 수출하려면 어떻게 하나요")
        assert data is not None
        assert "KOTRA" in data["body"] and "TradeNAVI" in data["body"]
        # 지어내지 않고 "확인하라"고 합니다.
        assert "확인" in data["body"]

    def test_FTA가_있는_나라는_협정을_알려준다(self):
        assert "한·베트남 FTA" in knowledge.country("베트남 수출 절차")["body"]
        assert "RCEP" in knowledge.country("베트남 수출 절차")["body"]
        assert "한·EU FTA" in knowledge.country("폴란드 수출 절차")["body"]

    def test_FTA가_없는_나라는_일반세율이라고_말한다(self):
        assert "일반세율" in knowledge.country("멕시코 수출 절차")["body"]

    def test_나라_이름만_있고_수출_이야기가_아니면_답하지_않는다(self):
        assert country_export_guide.find_country("일본 여행 좋았어요") is None

    def test_긴_이름이_먼저_맞는다(self):
        code, _ = country_export_guide.find_country("파푸아뉴기니 수출 절차")
        assert code == "PG"


class Test상담연결:
    def test_지식으로_답하면_AI를_부르지_않는다(self, monkeypatch):
        from app.services import support_chat_service

        def 부르면안됨(*args, **kwargs):  # noqa: N802
            raise AssertionError("저장해 둔 자료로 답해야 하는데 AI를 불렀습니다")

        monkeypatch.setattr(support_chat_service.ai_client, "chat", 부르면안됨)
        result = support_chat_service.ask("인코텀즈는 어떻게 고르나요?")
        assert result["success"] and result["source"] == "knowledge"
        assert result["data"]["widget"] == "incoterms"

    def test_나라_질문도_AI_없이_답한다(self, monkeypatch):
        from app.services import support_chat_service

        monkeypatch.setattr(support_chat_service.ai_client, "chat",
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("AI 호출")))
        result = support_chat_service.ask("베트남에 수출하려면 어떤 절차를 밟나요?")
        assert result["source"] == "knowledge"
        assert "베트남" in result["data"]["answer"]


# ----- 주소가 실제로 열리는지 (바깥을 두드리므로 live 표시) -----
# 실행:  python -m pytest tests/test_knowledge.py -m live -q
# fda.gov·fcc.gov는 사람이 아닌 접속을 막아 404·403을 돌려줍니다. 브라우저에서는 열립니다.
BOT_BLOCKED = ("fda.gov", "fcc.gov", "eur-lex.europa.eu", "utradehub.or.kr")


@pytest.mark.live
def test_지식에_적힌_주소가_열린다():
    import ssl
    import urllib.error
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    found = set()
    for entry in knowledge.entries():
        found |= {link["url"] for link in entry["links"] if link["url"].startswith("http")}
        found |= set(re.findall(r"\]\((https?://[^)]+)\)", entry["body"]))

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    def 두드리기(url):
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(request, timeout=25, context=context) as response:
                return url, response.status
        except urllib.error.HTTPError as error:
            return url, error.code
        except Exception as error:  # noqa: BLE001 - 어떤 이유든 "못 열었다"입니다
            return url, type(error).__name__

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(두드리기, sorted(found)))

    broken = [(url, status) for url, status in results
              if status not in (200, 301, 302, 403, 405)
              and not any(host in url for host in BOT_BLOCKED)]
    assert not broken, f"열리지 않는 주소: {broken}"
