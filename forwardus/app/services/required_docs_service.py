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


def _country_notes(country_code: str, name: str = "") -> list[dict]:
    """도착국에서 걸리는 인증. 우리가 정리해 둔 나라별 자료에서 꺼냅니다."""

    from app.processors import country_export_guide

    code = str(country_code or "").upper()
    note = country_export_guide.NOTES.get(code)
    if not note and code in country_export_guide._eu_members():
        note = country_export_guide.EU_NOTE
    if not note:
        return []
    # 그 나라 조심할 점은 인증마다 따로 적혀 있지 않습니다. 목록 맨 앞 줄에 함께 붙여
    # "이 나라는 이런 걸 조심하라"를 같이 보게 합니다.
    watch = [row.replace("**", "") for row in note.get("watch", [])]
    guide = note.get("knowledge", "")
    found = []
    for line in note.get("certs", []):
        # "**NOM 강제인증** — 없으면 통관 거부" → 앞의 굵은 부분이 이름, 뒤가 설명입니다.
        head, _, tail = line.partition("—")
        title = head.replace("**", "").strip()
        if not title:
            continue
        why = tail.replace("**", "").strip()
        if not why:
            why = "도착국에서 이 품목에 요구하는 인증입니다. 없으면 통관이 막힙니다."
        papers = watch if not found else []
        found.append({"key": f"country_{code}_{len(found)}", "title": title,
                      "documents": papers,
                      "agency": ("도착국 인증기관 — 필요 서류·발급처·기간은 "
                                 f"상담에서 \"{name or code} 인증\"이라고 물어보세요"
                                 if guide else "도착국 인증기관"),
                      "why": why, "source": "country",
                      "link": "", "confidence": "high"})
    return found


# 원산지증명서를 받으려면 함께 갖춰야 하는 증빙. 발급은 쉬워도 검증은 5년 뒤에 옵니다.
ORIGIN_EVIDENCE = [
    "원산지소명서 (품목별 원산지결정기준 충족 설명)",
    "자재명세서(BOM)와 제조공정도",
    "국내 공급자에게 받은 원산지확인서 또는 수입신고필증",
    "원가계산서 (부가가치기준을 쓸 때)",
]


def _fta_origin(shipment) -> dict | None:
    """도착국에 쓸 협정이 있으면 원산지증명서를 목록에 올립니다.

    협정마다 **발급 방식과 서식이 다릅니다.** 기관발급인지 자율발급인지, 어떤 서식에
    무엇을 적는지까지 적어 둡니다. "원산지증명서 필요"라고만 적으면, 자율발급 협정에서
    상공회의소를 찾아가거나 반대로 기관발급인데 송장에 문안만 적는 일이 생깁니다.
    """

    from app.services import document_service

    guide = document_service.origin_certificate_guide(shipment)
    if not guide.get("available") or not guide.get("agreements"):
        return None

    rows = guide["agreements"]
    names = " · ".join(row["agreement"] for row in rows[:3])
    first = rows[0]
    paper = first.get("certificate") or {}
    steps = first.get("steps") or {}
    method = paper.get("method", "")
    issuer = paper.get("issuer", "")

    lines = []
    for row in rows[:3]:
        mark = row.get("certificate") or {}
        bits = [f"**{row['agreement']}**"]
        if row.get("rate") not in (None, ""):
            bits.append(f"협정세율 {row['rate']}%")
        if mark.get("method"):
            bits.append(mark["method"])
        if mark.get("issuer"):
            bits.append(f"발급 {mark['issuer']}")
        if mark.get("form"):
            bits.append(f"서식: {mark['form']}")
        if mark.get("valid_for"):
            bits.append(f"유효기간 {mark['valid_for']}")
        lines.append(" · ".join(bits))
    lines.append("증빙 보관 5년 (사후 검증에 대비합니다)")

    why = (f"{names} 특혜관세를 받으려면 필요합니다. "
           + (steps.get("where") or "협정마다 서식과 발급 주체가 다릅니다."))
    return {"key": "origin", "title": "원산지증명서 (C/O)",
            "documents": lines + ORIGIN_EVIDENCE,
            "agency": (f"{method} · {issuer}".strip(" ·")
                       or "세관 또는 대한상공회의소 (협정에 따라 자율발급)"),
            "why": why, "source": "fta", "link": "", "confidence": "high"}


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


class _Item:
    """HS부호만 들고 오는 품목. (건을 만들기 전에 미리 보여 줄 때 씁니다)

    화물 모델과 같은 이름의 값만 갖습니다. 아래 collect가 화물에서 읽는 것이
    hs_code · product_description · is_dangerous 셋뿐이라 이걸로 충분합니다.
    """

    def __init__(self, hs_code: str = "", product_description: str = "",
                 is_dangerous: bool = False) -> None:
        self.hs_code = hs_code
        self.product_description = product_description
        self.is_dangerous = is_dangerous


def preview(hs_codes, country_code: str = "", country_name: str = "",
            products=None, dangerous: bool = False, *, use_ai: bool = True) -> dict:
    """건을 만들기 전에, **HS부호만으로** 필요한 서류를 미리 봅니다.

    서류 작성 화면에서 품목의 HS부호를 적으면 바로 이 목록이 뜹니다. 건을 만들고
    나서야 알려 주면, 인증에 몇 달 걸리는 것을 선적 직전에 알게 됩니다.

    FTA 원산지증명서는 건(Shipment)이 있어야 협정 세율을 볼 수 있어 여기서는 빠집니다.
    """

    codes = [code for code in (hs_codes or []) if code]
    names = list(products or [])
    items = [_Item(code, names[i] if i < len(names) else "", dangerous)
             for i, code in enumerate(codes)] or [_Item("", names[0] if names else "", dangerous)]
    return collect(_Preview(items, country_code, country_name), use_ai=use_ai)


class _Preview:
    """collect가 읽는 것만 흉내 냅니다. (건이 없으니 올린 파일도 없습니다)"""

    def __init__(self, items, country_code: str, country_name: str) -> None:
        self.cargos = items
        self.destination_country = country_code
        self.destination_code = country_code
        self.destination_name = country_name
        self.requirement_documents = []


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

    # 3. FTA 원산지증명서 (건이 있어야 협정 세율을 봅니다)
    origin = _fta_origin(shipment) if not isinstance(shipment, _Preview) else None
    if origin:
        add(origin)

    # 4. 도착국 인증
    country_code = (getattr(shipment, "destination_country", "") or "").strip().upper()
    if not country_code:
        # 도착국 칸이 비어 있으면 도착지 코드 앞 두 글자(UN/LOCODE)로 봅니다.
        port = (getattr(shipment, "destination_code", "") or "").strip().upper()
        country_code = port[:2] if len(port) >= 2 and port[:2].isalpha() else ""
    for row in _country_notes(country_code,
                              getattr(shipment, "destination_name", "") or ""):
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
