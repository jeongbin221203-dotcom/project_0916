"""AI 상담이 "요건이 없습니다"라고 단정하지 않는지 봅니다.

왜 필요한가
  화면에서 이렇게 답한 적이 있습니다.

      "현재 확인해야 할 수출 요건은 없습니다."

  그 건은 HS부호가 비어 있었고, 관세청 조회도 막혀 있었습니다. **아무것도
  확인하지 못한 상태**였는데 "없다"고 답한 것입니다. 이 말을 믿고 보내면
  통관에서 막히고, 그때는 배가 이미 떠난 뒤입니다.

  찾지 못한 것과 없는 것은 다릅니다. 그 구분이 자료에 실려 나가야 AI가
  구분해서 말할 수 있습니다.
"""

from __future__ import annotations

from app.services import assistant_service


def test_HS부호가_비면_그렇다고_자료에_적는다(app, create_shipment):
    shipment = create_shipment()
    for cargo in shipment.cargos:
        cargo.hs_code = ""

    context = assistant_service.ai_context(shipment)

    assert context["요건조회_상태"] == "일부 실패"
    적힌_것 = " ".join(context["요건조회_못한_것"])
    assert "HS부호가 비어 있는 품목" in 적힌_것


def test_목록이_비어도_없다는_뜻이_아니라고_함께_적는다(app, create_shipment):
    """AI가 빈 목록을 '요건 없음'으로 읽지 않게 하는 마지막 방어선입니다."""

    shipment = create_shipment()
    context = assistant_service.ai_context(shipment)

    assert "요건목록_읽는_법" in context
    assert "'요건이 없다'는 뜻이" in context["요건목록_읽는_법"]


def test_도착국_인증까지_모아서_넘긴다(app, create_shipment):
    """내부 규칙표에만 있는 것이 아니라 도착국 인증도 함께 가야 합니다.

    예전에는 export_requirements.check()만 돌려서, 그 표에 없는 품목이면
    목록이 통째로 비었습니다.
    """

    shipment = create_shipment()
    shipment.destination_country = "US"
    for cargo in shipment.cargos:
        cargo.hs_code = "3304990000"          # 화장품

    titles = " ".join(row["확인할 것"]
                      for row in assistant_service.ai_context(shipment)["확인해야_할_수출요건"])
    assert "FDA" in titles


def test_프롬프트가_없다고_말하지_말라고_이른다():
    """자료를 잘 넘겨도 프롬프트가 허락하면 AI는 단정합니다. 둘 다 막습니다."""

    prompt = assistant_service.AI_SYSTEM_PROMPT
    assert "확인할 요건이 없습니다" in prompt
    assert "절대 말하지 마세요" in prompt
    assert "요건조회_상태" in prompt
