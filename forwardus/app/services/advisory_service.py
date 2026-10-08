"""건 화면(상세·수출요건·서류 센터)에 붙이는 **안내 카드** — 제재·수출통제와 중고품 수입 규제.

사용자 점검: 이란으로 확인하고 만든 건의 상세·수출요건·서류 화면에 "제재"·"전략물자"라는 말이 한 번도 나오지 않았습니다.
그 카드는 `required_docs_service.collect()` 가 만들고 서류 작성(`/documents/new`) 화면에서만 붙었기 때문입니다.
여기서 같은 내용을 건 화면 어디서나 쓸 수 있게 한 곳에서 만듭니다(조회·외부 호출 없음 — 규칙표만 봅니다).
"""

from __future__ import annotations

from app.collectors import location_client
from app.processors import trade_controls, used_goods


def _countries(shipment) -> list[str]:
    destination = location_client.find_location(getattr(shipment, "destination_code", "") or "") or {}
    buyer = getattr(shipment, "buyer", None)
    codes = [destination.get("country_code", ""), (buyer.country if buyer else "") or ""]
    return [code.upper() for code in dict.fromkeys(codes) if code]


def advisories(shipment) -> list[dict]:
    """[{"level": blocked|strict|watch|used, "title", "text"}]. 없으면 빈 목록."""

    cards: list[dict] = []
    codes = _countries(shipment)
    for code in codes:
        level = trade_controls.level(code)
        if level:
            title = {"blocked": "수출 금지 대상 국가", "strict": "제재·수출통제 확인 필요", "watch": "주의 국가"}[level]
            cards.append({"level": level, "title": f"{title} — {trade_controls.CONTROLS[code][1]}",
                          "text": trade_controls.note(code).replace("**", "")})
    text = " ".join(str(getattr(shipment, key, "") or "") for key in ("exporter_name", "notify_party"))
    buyer = getattr(shipment, "buyer", None)
    region = trade_controls.region_in_text(text, buyer.name if buyer else "", buyer.address if buyer else "")
    if region:
        cards.append({"level": "strict", "title": "러시아 점령지 이름이 보입니다",
                      "text": f"'{region}' — 미국·EU 가 지역 단위로 포괄 제재해 거래가 불가능할 수 있습니다. "
                              + trade_controls.CHECK_FIRST.replace("**", "")})
    if any(getattr(cargo, "used_condition", "") for cargo in getattr(shipment, "cargos", []) or []):
        notes = []
        chapters = {(getattr(cargo, "hs_code", "") or "")[:2] for cargo in shipment.cargos
                    if (getattr(cargo, "hs_code", "") or "")[:2].isdigit()}
        for code in codes[:1] or [""]:
            notes += used_goods.notes_for(code, chapters or None)
        cards.append({"level": "used", "title": "중고품 수입 규제 확인 (수입국)",
                      "text": " ".join(notes + [used_goods.GENERIC])})
    return cards
