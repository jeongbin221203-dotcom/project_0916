"""이 건에 필요한 서류를 **한 목록**으로 모읍니다. (원산지증명서 + 인증서 + 검역증 …)

왜 한 목록인가
  예전에는 원산지증명서만 따로 챙기는 자리가 있었습니다. 그런데 관세사에게 넘길 때
  필요한 것은 원산지증명서만이 아닙니다. 식품이면 위생증명서, 전자기기를 미국에 보내면
  FCC, 배터리가 들어가면 MSDS와 위험물신고서가 같이 갑니다. 챙기는 자리가 흩어져
  있으면 하나씩 빠지고, 빠진 채로 신고가 들어가 통관이 멈춥니다.

어디서 모으나 — 확실한 것부터입니다
  1. 관세청 세관장확인  HS 10자리 기준. 답이 오면 이것이 기준입니다.
  2. 우리 규칙표        HS 류(類) 기준 (식품·검역·화장품·위험물 …)
  3. FTA 원산지증명서   도착국에 쓸 협정이 있을 때
  4. 도착국 인증        우리가 정리해 둔 나라별 자료 (미국 FCC·FDA, EU CE, 중국 CCC …)
  5. AI 탐색            위 넷이 못 잡은 것만 보강합니다

AI에 대해 지키는 것
  - **마지막에만** 부릅니다. 1~4로 이미 잡힌 것은 다시 묻지 않습니다.
  - AI가 낸 것은 "AI가 찾은 것"이라고 표시하고, 기관 주소는 붙이지 않습니다.
    (AI가 만든 주소는 없는 주소일 수 있습니다. 주소는 우리 표에서만 꺼냅니다)
  - 키가 없거나 AI가 멈춰도 1~4만으로 목록이 나옵니다.
"""

from __future__ import annotations

import json
import re

from app.collectors import ai_client

# AI에게 물을 때 한 번에 보는 품목 수. 품목이 많아도 앞의 몇 개면 성격이 드러납니다.
AI_ITEM_LIMIT = 3
AI_MAX_TOKENS = 900
AI_PROMPT = """당신은 한국에서 수출 통관을 맡는 관세사입니다.
아래 물건을 그 나라로 보낼 때 **수출·수입 통관에 실제로 첨부해야 하는 서류**를 찾아 주세요.

이미 챙기고 있는 것은 다시 적지 마세요:
{known}

규칙
- 상업송장·포장명세서·B/L처럼 어느 건에나 있는 기본 서류는 빼세요.
- 정말 이 품목·이 나라라서 필요한 것만 적으세요. 없으면 빈 목록을 주세요.
- 확실하지 않으면 넣지 마세요. 지어내는 것보다 비는 편이 낫습니다.
- 주소(URL)는 적지 마세요.

JSON만 답하세요. 설명을 덧붙이지 마세요.
{{"documents": [{{"title": "서류 이름 (한국어)", "agency": "발급·신청 기관",
  "why": "왜 필요한지 한 문장", "confidence": "high 또는 low"}}]}}"""


def _same_paper(one: str, other: str) -> str | bool:
    """두 서류 이름이 같은 것을 가리키는지 봅니다.

    AI는 "FCC 적합성 선언서"라고 적고 우리 자료는 "무선·전자기기 FCC"라고 적습니다.
    글자가 달라도 **같은 인증**입니다. 그래서 영문 약어(FCC·FDA·CCC·NOM·CE·PSE …)가
    겹치거나, 한쪽이 다른 쪽에 통째로 들어 있으면 같은 것으로 봅니다.
    """

    a, b = re.sub(r"\s+", "", one).lower(), re.sub(r"\s+", "", other).lower()
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    marks_a = set(re.findall(r"[A-Z]{2,}", one))
    marks_b = set(re.findall(r"[A-Z]{2,}", other))
    return bool(marks_a & marks_b)


def _known_titles(found: list[dict]) -> str:
    lines = [f"- {row['title']}" for row in found]
    return "\n".join(lines) if lines else "- (아직 없음)"


def _country_notes(country_code: str) -> list[dict]:
    """도착국에서 걸리는 인증. 우리가 정리해 둔 나라별 자료에서 꺼냅니다."""

    from app.processors import country_export_guide

    code = str(country_code or "").upper()
    note = country_export_guide.NOTES.get(code)
    if not note and code in country_export_guide._eu_members():
        note = country_export_guide.EU_NOTE
    if not note:
        return []
    found = []
    for line in note.get("certs", []):
        # "**NOM 강제인증** — 없으면 통관 거부" → 앞의 굵은 부분이 서류 이름입니다.
        title = line.split("—")[0].replace("**", "").strip()
        if not title:
            continue
        found.append({"key": f"country_{code}_{len(found)}", "title": title,
                      "documents": [], "agency": "도착국 인증기관",
                      "why": line.replace("**", ""), "source": "country",
                      "link": "", "confidence": "high"})
    return found


def _fta_origin(shipment) -> dict | None:
    """도착국에 쓸 협정이 있으면 원산지증명서를 목록에 올립니다."""

    from app.services import document_service

    guide = document_service.origin_certificate_guide(shipment)
    if not guide.get("available") or not guide.get("agreements"):
        return None
    names = " · ".join(row["agreement"] for row in guide["agreements"][:2])
    return {"key": "origin", "title": "원산지증명서 (C/O)", "documents": [],
            "agency": "세관 또는 대한상공회의소 (협정에 따라 자율발급)",
            "why": f"{names} 특혜관세를 받으려면 필요합니다. 협정마다 서식이 다릅니다.",
            "source": "fta", "link": "", "confidence": "high"}


def ai_extra(items: list[dict], country_name: str, found: list[dict]) -> list[dict]:
    """AI가 찾은 나머지. 키가 없거나 답이 이상하면 빈 목록입니다."""

    if not ai_client.available() or not items:
        return []
    lines = [f"- 품명 {row.get('product_description') or '(적지 않음)'} / "
             f"HS부호 {row.get('hs_code') or '(적지 않음)'}"
             for row in items[:AI_ITEM_LIMIT]]
    question = (f"도착국: {country_name or '(적지 않음)'}\n물건:\n" + "\n".join(lines))
    result = ai_client.chat(
        [{"role": "system", "content": AI_PROMPT.format(known=_known_titles(found))},
         {"role": "user", "content": question}],
        max_tokens=AI_MAX_TOKENS)
    if not result["success"]:
        return []
    try:
        text = str(result["data"]).strip()
        # 코드 울타리로 감싸 오는 경우가 있습니다.
        if text.startswith("```"):
            text = text.split("```")[1].removeprefix("json").strip()
        rows = json.loads(text).get("documents") or []
    except (ValueError, IndexError, AttributeError):
        return []

    known = [row["title"] for row in found]
    extra = []
    for row in rows:
        title = str(row.get("title") or "").strip()
        if not title or any(_same_paper(title, other) for other in known):
            continue
        extra.append({"key": f"ai_{len(extra)}", "title": title, "documents": [],
                      "agency": str(row.get("agency") or "").strip(),
                      "why": str(row.get("why") or "").strip(),
                      "source": "ai", "link": "",
                      "confidence": "low" if row.get("confidence") == "low" else "high"})
        known.append(title)
    return extra[:6]


def collect(shipment, *, use_ai: bool = True) -> dict:
    """이 건에 필요한 서류 한 목록. 올린 파일이 있으면 붙여서 돌려줍니다."""

    from app.processors import export_requirements
    from app.services import requirement_service

    cargos = list(shipment.cargos)
    found: list[dict] = []
    seen: set[str] = set()

    def add(row: dict) -> None:
        if row["key"] in seen:
            return
        seen.add(row["key"])
        found.append(row)

    # 1·2. 관세청 세관장확인 + 우리 규칙표
    customs_laws = []
    for cargo in cargos:
        for item in export_requirements.check(cargo.hs_code,
                                              is_dangerous=cargo.is_dangerous):
            # 원산지증명서는 품목이 아니라 협정이 정합니다. 아래 3에서 따로 봅니다.
            if item["key"] == "origin":
                continue
            add({"key": item["key"], "title": item["title"],
                 "documents": item.get("documents") or [],
                 "agency": item.get("agency", ""), "why": item.get("why", ""),
                 "source": "rule", "link": item.get("link", ""), "confidence": "high"})
        if cargo.hs_code:
            official = requirement_service.official_requirements(cargo.hs_code)
            for law in official.get("laws") or []:
                customs_laws.append({**law, "hs_code": cargo.hs_code})

    for law in customs_laws:
        name = law.get("law_name") or law.get("name") or "세관장확인 요건"
        add({"key": f"customs_{name}", "title": f"{name} 요건승인",
             "documents": [], "agency": law.get("agency", "요건확인기관"),
             "why": f"HS {law.get('hs_code', '')}는 관세법 제226조 세관장확인대상입니다. "
                    "요건승인이 없으면 수출신고가 수리되지 않습니다.",
             "source": "customs", "link": "", "confidence": "high"})

    # 3. FTA 원산지증명서
    origin = _fta_origin(shipment)
    if origin:
        add(origin)

    # 4. 도착국 인증
    for row in _country_notes(getattr(shipment, "destination_country", "")):
        add(row)

    # 5. AI 탐색 — 위에서 못 잡은 것만
    ai_used = False
    if use_ai:
        items = [{"product_description": cargo.product_description, "hs_code": cargo.hs_code}
                 for cargo in cargos]
        extra = ai_extra(items, getattr(shipment, "destination_name", "")
                         or getattr(shipment, "destination_code", ""), found)
        ai_used = bool(extra)
        for row in extra:
            add(row)

    # 올린 파일 붙이기
    uploads = list(shipment.requirement_documents)
    by_key: dict[str, list] = {}
    for doc in uploads:
        by_key.setdefault(doc.requirement_key, []).append(doc)
    for row in found:
        row["uploads"] = [{"id": doc.id, "filename": doc.filename,
                           "status": doc.review_status, "status_label": doc.review_label,
                           "summary": doc.review_summary or ""}
                          for doc in by_key.get(row["key"], [])]
        row["uploaded"] = bool(row["uploads"])

    # 어느 칸에도 속하지 않게 올린 파일(직접 올린 그 밖의 서류)
    others = [{"id": doc.id, "filename": doc.filename, "key": doc.requirement_key,
               "status": doc.review_status, "status_label": doc.review_label}
              for doc in uploads if doc.requirement_key not in seen]

    return {
        "documents": found,
        "others": others,
        "ready": sum(1 for row in found if row["uploaded"]),
        "total": len(found),
        "ai_used": ai_used,
        "ai_available": ai_client.available(),
        "note": "여기 나오는 것은 '확인해야 할 것'입니다. 최종 판단은 세관과 수입국이 합니다. "
                "올려 두신 파일은 관세사에게 넘길 자료에 함께 들어갑니다.",
    }
