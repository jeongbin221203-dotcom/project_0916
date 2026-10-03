"""계약서 조항 점검 — 이 건에 필요한 조항을 짚고, 올린 계약서를 읽어 판정합니다.

무엇을 하나
  1. 점검표   이 건(인코텀즈·결제조건)에 걸리는 필수·이익·독소 조항을 냅니다.
  2. 판정     올린 계약서를 읽어 **빠진 필수조항**과 **들어 있는 독소조항**을 찾습니다.
  3. 문안     고른 조항의 영문 문안과 한글 설명을 한 벌로 내보냅니다.

지키는 것
  - **법률 자문이 아닙니다.** 어느 답에도 그 말을 붙입니다.
  - 판정은 **글자를 찾은 결과**입니다. 찾았다/못 찾았다만 말하고,
    "이 조항이 유효하다"거나 "이 계약은 안전하다"고는 말하지 않습니다.
  - AI를 쓰지 않습니다. 키가 없어도 그대로 돕니다. (글자로만 찾습니다)
  - 올린 파일은 **저장하지 않습니다.** 읽고 판정만 합니다.
"""

from __future__ import annotations

from app.processors import clause_topics, contract_clauses
from app.services import ServiceError

MAX_TEXT = 400_000
DISCLAIMER = ("법률 자문이 아닙니다. 여기 문안은 출발점이고, 최종 계약서는 "
              "변호사 검토를 받으세요.")


def checklist(incoterms: str = "", present: set[str] | None = None,
              country: str = "", analysis: dict | None = None) -> dict:
    """이 건에 걸리는 조항 점검표.

    present를 주면(올린 계약서에서 보인 조항) 줄마다 있음/없음을 함께 답니다.

    country(도착국 2자리)를 주면 그 나라에 **특히 흔한** 조항에 for_country 를
    달고, 독소 묶음에서 앞으로 올립니다. 계약서를 올리기 전에도 "중국으로
    보내시는군요 — 이 셋을 특히 보세요"를 말할 수 있습니다. (2026-10-02)

    **찾는 일에는 나라를 쓰지 않습니다.** 도착국을 몰라도 다 찾아야 하고,
    중국 중재 조항은 어디로 보내든 독소입니다.
    """

    present = present or set()
    # analysis(analyze 결과)를 주면 줄마다 판정(status)·근거 문장·까닭을 답니다.
    # 가공계약에만 있는 조항(context)은 그 문서가 가공계약일 때만 냅니다. (2026-10-02)
    judged = (analysis or {}).get("clauses", {})
    contexts = (analysis or {}).get("context", set())
    tags = contract_clauses.groups_for(country)
    out: dict[str, list[dict]] = {"must": [], "gain": [], "toxic": []}
    for row in contract_clauses.CLAUSES:
        if not contract_clauses.applies_to(row, incoterms):
            continue
        if row["context"] and row["key"] not in contexts:
            continue
        seen = judged.get(row["key"]) or {}
        out[row["category"]].append({
            "key": row["key"], "title": row["title"], "why": row["why"],
            "risk": row["risk"], "text_ko": row["text_ko"], "fix": row["fix"],
            "present": row["key"] in present,
            "status": seen.get("status") or ("present" if row["key"] in present else "absent"),
            "evidence": seen.get("evidence", ""),
            "reason": seen.get("reason", ""),
            "countries": list(row["countries"]),
            "for_country": bool(tags & set(row["countries"])),
        })
    if tags:
        # 그 나라 것을 앞으로. 그 안에서는 원래 순서를 지킵니다(sort 는 안정적입니다).
        for category in out:
            out[category].sort(key=lambda item: not item["for_country"])
    return out


def review(text: str, incoterms: str = "", country: str = "") -> dict:
    """올린 계약서 판정.

    missing  빠진 필수조항 — 넣어야 합니다
    toxic    들어 있는 독소조항 — 지우거나 고쳐야 합니다
    gain     아직 없는 이익조항 — 챙기면 우리가 덜 잃습니다
    present  보이는 조항 전부
    """

    body = str(text or "")
    if not body.strip():
        raise ServiceError("읽을 글이 없습니다. 계약서 파일이나 글을 넣어 주세요.",
                           "VALIDATION_ERROR")
    analysis = contract_clauses.analyze(body[:MAX_TEXT])
    found = {key for key, row in analysis["clauses"].items() if row["status"] == "present"}
    rows = checklist(incoterms, found, country, analysis)
    # 도착국에 흔한데 **아직 안 보이는** 독소조항. 올린 계약서에 없더라도
    # 협상 중에 들어올 수 있어 미리 알려 줍니다. (2026-10-02)
    watch = [row for row in rows["toxic"] if row["for_country"] and not row["present"]]
    # 규칙이 **주제째 놓친** 조항 — 주제 분류기가 고릅니다. 판정은 바꾸지 않고
    # 빠진 필수조항에 "이 문장일 수 있습니다"를 덧붙이거나, '확인 필요'로 냅니다.
    # (2026-10-03, app/processors/clause_topics.py)
    category = {row["key"]: row["category"] for row in contract_clauses.CLAUSES}
    maybe = clause_topics.candidates(body[:MAX_TEXT], analysis["clauses"], category)
    missing = [row for row in rows["must"] if row["status"] == "absent"]
    for row in missing:
        hint = next((c for c in maybe if c["kind"] == "must" and row["key"] in c["keys"]), None)
        row["maybe"] = hint["sentence"] if hint else ""
    return {
        "missing": missing,
        "check": [c for c in maybe if c["kind"] == "check"],
        "toxic": [row for row in rows["toxic"] if row["present"]],
        # **적혀 있으나 제 구실을 못 하는** 필수·이익조항 — 미정·부정·불리·무력.
        # '있다'고 하면 안심시키고, '없다'고 하면 이미 쓴 사람에게 넣으라고
        # 합니다. 둘 다 아니라서 따로 냅니다. (2026-10-02)
        "weak": [row for row in rows["must"] + rows["gain"] if row["status"] == "weak"],
        "gain": [row for row in rows["gain"] if row["status"] == "absent"],
        "ok_must": [row for row in rows["must"] if row["present"]],
        "present": sorted(found),
        "country": (country or "").upper(),
        "watch_country": watch,
        # Party A/B 계약서에서 누구를 우리(매도인)로 읽었는지. 틀렸으면
        # 사용자가 바로 알아야 합니다 — 방향이 뒤집히면 판정도 뒤집힙니다.
        "our_side": contract_clauses.our_side(body[:MAX_TEXT]),
        "checked": len(body),
        "note": DISCLAIMER,
    }


def read_file(filename: str, data: bytes) -> str:
    """계약서 파일에서 글자만 꺼냅니다. (PDF·사진·텍스트)

    서류 읽기와 같은 길을 씁니다. 사진·스캔이면 OCR로 읽고, OCR을 쓸 수 없으면
    빈 글자가 나옵니다. **AI는 부르지 않습니다.**
    """

    from app.services import document_extract_service as extract

    name = str(filename or "")
    if name.lower().endswith((".txt", ".md")):
        return data.decode("utf-8", errors="replace")
    text, images = extract.read_upload(name, data)
    if text.strip():
        return text
    # 스캔본이면 우리 컴퓨터의 OCR로 읽습니다. 없으면 빈 글자입니다.
    return extract.ocr_text(text, images)



def country_of(shipment) -> str:
    """이 건의 도착국 ISO 2자리. 못 알아내면 빈 글자입니다.

    도착국을 알면 그 나라에 흔한 독소조항을 앞세울 수 있습니다. 계약서를 올리기
    전에도 경고가 되므로, 운송 계획에 적힌 값을 그대로 씁니다. (2026-10-02)

    document_service 가 FTA 협정을 찾을 때 쓰는 방식과 같습니다.
      1) destination_country ("NL" 또는 "NL · 네덜란드")
      2) 비어 있으면 destination_code 앞 두 글자 (UN/LOCODE)

    **못 알아내면 비웁니다.** 억지로 맞추면 엉뚱한 나라의 조항을 앞세웁니다.
    공항 부호(IATA · ICN·LAX)는 나라를 담지 않으므로 이 길로는 못 알아냅니다.
    """

    # **isascii() 를 함께 봅니다.** 파이썬 isalpha() 는 한글도 True 라서,
    # "네덜란드" 에서 "네덜" 을 국가코드로 내놓았습니다. (2026-10-02 실제로 그랬습니다)
    # 나라 칸에 한글만 적힌 건은 도착지 부호 쪽으로 넘깁니다.
    def _iso2(value: str) -> str:
        head = value[:2]
        return head if len(head) == 2 and head.isascii() and head.isalpha() else ""

    text = str(getattr(shipment, "destination_country", "") or "").strip().upper()
    found = _iso2(text)
    if found:
        return found
    code = str(getattr(shipment, "destination_code", "") or "").strip().upper()
    # UN/LOCODE 는 다섯 글자(NLRTM)입니다. 세 글자는 공항 부호(ICN)라 나라가 없습니다.
    return _iso2(code) if len(code) == 5 else ""

def clause_text(keys) -> str:
    """고른 조항의 문안을 한 벌로. 계약서에 그대로 붙여 쓸 수 있게 냅니다."""

    picked = [contract_clauses.by_key(key) for key in keys or []]
    picked = [row for row in picked if row]
    if not picked:
        raise ServiceError("내보낼 조항을 골라 주세요.", "VALIDATION_ERROR")
    lines = ["# 계약서 조항 문안", "",
             f"※ {DISCLAIMER}", ""]
    for row in picked:
        mark = contract_clauses.CATEGORIES[row["category"]]
        lines += [f"## [{mark}] {row['title']}", "",
                  f"왜 필요한가: {row['why']}",
                  f"빠지면/있으면: {row['risk']}", ""]
        if row["category"] == "toxic":
            lines += ["이 조항은 **넣는 것이 아니라 빼는 것**입니다.", ""]
            if row["fix"]:
                lines += [f"고치는 법: {row['fix']}", ""]
        lines += ["```", row["text_en"], "```", "", row["text_ko"], "", "---", ""]
    return "\n".join(lines).rstrip() + "\n"


def as_text(result: dict) -> str:
    """판정을 사람이 읽는 글로. 무역 상담 답변에 그대로 씁니다."""

    lines = ["## 계약서 조항 점검", ""]
    side = result.get("our_side")
    if side:
        lines += [f"우리 쪽(매도인·수출자)을 **{side['label']} — {side['name']}**, "
                  f"상대(매수인)를 **{side['other_label']} — {side['other_name']}** 로 "
                  "읽었습니다. 반대라면 판정도 반대가 됩니다.", ""]
    if result["toxic"]:
        lines += [f"### 🔴 지우거나 고쳐야 할 조항 {len(result['toxic'])}개", ""]
        for row in result["toxic"]:
            lines.append(f"- **{row['title']}** — {row['risk']}")
            if row.get("evidence"):
                lines.append(f"  - 근거: “{row['evidence']}”")
            if row["fix"]:
                lines.append(f"  - 고치는 법: {row['fix']}")
        lines.append("")
    if result.get("weak"):
        lines += [f"### 🟡 적혀 있으나 제 구실을 못 하는 조항 {len(result['weak'])}개", ""]
        for row in result["weak"]:
            lines.append(f"- **{row['title']}** — {row['reason']}")
            if row.get("evidence"):
                lines.append(f"  - 근거: “{row['evidence']}”")
        lines.append("")
    if result["missing"]:
        lines += [f"### 🟠 빠진 필수조항 {len(result['missing'])}개", ""]
        for row in result["missing"]:
            lines.append(f"- **{row['title']}** — {row['why']}")
            if row.get("maybe"):
                lines.append(f"  - 규칙은 못 찾았지만 이 문장일 수 있습니다: “{row['maybe']}”")
        lines.append("")
    if result.get("check"):
        lines += [f"### ⚪ 규칙이 판정하지 못한 조항 {len(result['check'])}개 (직접 확인)", ""]
        for item in result["check"]:
            lines.append(f"- **{item['title']}** 조항으로 보입니다 — “{item['sentence']}”")
        lines.append("")
    if result["gain"]:
        lines += [f"### 🔵 챙기면 이로운 조항 {len(result['gain'])}개", ""]
        for row in result["gain"]:
            lines.append(f"- **{row['title']}** — {row['risk']}")
        lines.append("")
    if not (result["toxic"] or result["missing"] or result.get("weak")):
        lines += ["필수조항은 다 보이고, 독소조항은 보이지 않습니다. "
                  "다만 **글자를 찾은 결과**일 뿐이라 내용까지 맞다는 뜻은 아닙니다.", ""]
    lines += [f"※ {result['note']}"]
    return "\n".join(lines)

# 계약서인지 가리는 표지.
#
# 왜 필요한가
#   상담 창에 계약서를 통째로 붙여 넣는 일이 많습니다. 그걸 그냥 AI에게
#   넘기면 "요약해 드릴게요" 같은 답이 돌아옵니다. 정작 물어보고 싶은 것은
#   **빠진 조항과 위험한 조항**입니다. 계약서로 보이면 그쪽으로 답합니다.
#
# 두 가지를 함께 봅니다. 하나만 보면 헛짚습니다.
#   - 계약서라고 적혀 있는가 (제목·머리글)
#   - 조항이 실제로 두 가지 이상 보이는가
CONTRACT_TITLES = (
    "sales contract", "purchase contract", "supply agreement", "distribution agreement",
    "sales agreement", "purchase order terms", "terms and conditions of sale",
    "매매계약", "수출계약", "공급계약", "판매계약", "대리점계약", "총판계약", "계약서",
)
# 스스로 **계약서가 아니라고** 적어 둔 서류. 그 말을 믿습니다.
#
# 오퍼시트·견적서·송장은 가격조건과 결제·선적·보험을 다 적습니다. 그래서
# 조항 개수만 보면 전부 계약서로 걸립니다. 실제로 오퍼시트 세 장이 모두
# 계약서로 판정되어, 서류 칸이 빈 채로 "13가지가 누락되었습니다"가 떴습니다.
# (2026-09-28)
NOT_CONTRACT_TITLES = (
    "offer sheet", "firm offer", "quotation", "proforma invoice",
    "commercial invoice", "packing list", "bill of lading", "air waybill",
    "certificate of origin", "purchase order",
    "오퍼시트", "견적서", "상업송장", "포장명세서", "선하증권", "원산지증명서",
    "주문서", "발주서",
)

# **계약서다운** 조항. 제목이 없을 때는 이것들로 셉니다.
#
# incoterms · payment · shipment · insurance · packing · inspection 은
# 장사 서류면 다 있으므로 여기에 넣지 않습니다. 넣으면 오퍼시트가 계약서가
# 됩니다 — 실제로 그랬습니다.
CONTRACT_ONLY_CLAUSES = frozenset({
    # 필수·이익 조항 가운데 **계약서에만** 나오는 것
    "governing_law", "arbitration", "force_majeure", "title",
    "liability_cap", "late_interest", "ip", "cisg_silent", "agency_protection",
    # 독소조항. 이런 문구는 오퍼시트에 안 적습니다.
    "evergreen", "foreign_forum", "full_return", "mfn_price", "open_warranty",
    "payment_on_resale", "term_conflict", "termination_at_will",
    "uncapped_ld", "unlimited_damages", "us_jury_punitive",
    "buyer_set_off", "ip_assignment", "china_domestic_arb", "agency_law_eu",
})

# 여기에 **넣지 않은** 것 — 장사 서류면 다 있습니다.
#   incoterms · payment · shipment · insurance · inspection · goods
#   min_order · price_adjust · export_licence
# 실제로 오퍼시트 세 장에서 걸린 것이 incoterms·insurance·payment·shipment
# 넷이었고, 그것만으로 계약서 판정이 나 서류 칸이 통째로 비었습니다.

# 이만큼은 돼야 계약서 한 장으로 봅니다. 짧은 인용은 질문이지 계약서가 아닙니다.
# 제목을 찾는 범위. 무역서류는 **첫 몇 줄에** 무엇인지 적습니다.
#
# 글자 수로 자르면 안 됩니다. 짧은 계약서는 600자 안에 이미 "commercial
# invoice, packing list" 같은 본문이 들어옵니다. 그 언급에 걸려 진짜
# 계약서를 놓쳤습니다. 줄로 셉니다. (2026-09-28)
TITLE_LOOKUP_LINES = 3


def _title_area(text: str) -> str:
    """서류가 스스로 무엇이라고 적어 둔 자리. 빈 줄을 뺀 첫 몇 줄입니다."""

    rows = [row.strip() for row in str(text or "").splitlines() if row.strip()]
    return " ".join(rows[:TITLE_LOOKUP_LINES]).lower()

CONTRACT_MIN_CHARS = 400
CONTRACT_MIN_CLAUSES = 2

# 제목이 없을 때 필요한 **계약서다운** 조항 수.
#
# 조항 종류를 좁혔으니 문턱도 다시 잡습니다. 예전에는 아무 조항이나 넷이었고,
# 그래서 오퍼시트(incoterms·insurance·payment·shipment)가 전부 걸렸습니다.
# 지금은 준거법·중재·불가항력 같은 것만 셉니다. 오퍼시트에는 이런 조항이
# **하나도 없습니다.** 셋이면 계약서로 봐도 됩니다. (2026-09-28)
CONTRACT_MIN_ONLY_CLAUSES = 3


def looks_like_contract(text: str) -> bool:
    """이 글이 계약서인가. 확실하지 않으면 False입니다(평소대로 상담으로 답합니다).

    잘못 보면 두 가지가 한꺼번에 나빠집니다.
      계약서를 놓치면  조항을 못 짚어 줍니다 (아쉽지만 상담은 됩니다)
      계약서로 잘못 보면 **서류 칸이 통째로 비고** "13가지가 누락되었습니다"가
                      뜹니다. 멀쩡히 읽히는 서류인데도요.
    뒤쪽이 더 나쁩니다. 그래서 확실할 때만 계약서로 봅니다.
    """

    body = str(text or "")
    if len(body) < CONTRACT_MIN_CHARS:
        return False
    lowered = body.lower()
    # **제목은 첫 몇 줄에서만 찾습니다.**
    #
    # 본문까지 뒤지면 안 됩니다. 계약서는 "each party shall provide the
    # commercial invoice, packing list, and transport documents" 처럼 다른
    # 서류를 본문에서 언급합니다. 그것 때문에 진짜 계약서를 놓쳤습니다.
    # (2026-09-28 — 본문 2,038번째 글자의 "commercial invoice" 에 걸렸습니다)
    head = _title_area(body)
    # 스스로 오퍼시트·송장이라고 적어 둔 것은 계약서가 아닙니다.
    if any(word in head for word in NOT_CONTRACT_TITLES):
        return False
    if any(word in head for word in CONTRACT_TITLES):
        return len(contract_clauses.find_in(body)) >= CONTRACT_MIN_CLAUSES
    # 제목이 없으면 **계약서다운 조항**만 셉니다.
    # 가격조건·결제·선적은 장사 서류면 다 있어 세지 않습니다.
    found = set(contract_clauses.find_in(body)) & CONTRACT_ONLY_CLAUSES
    return len(found) >= CONTRACT_MIN_ONLY_CLAUSES
