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

from app.processors import contract_clauses
from app.services import ServiceError

MAX_TEXT = 400_000
DISCLAIMER = ("법률 자문이 아닙니다. 여기 문안은 출발점이고, 최종 계약서는 "
              "변호사 검토를 받으세요.")


def checklist(incoterms: str = "", present: set[str] | None = None) -> dict:
    """이 건에 걸리는 조항 점검표.

    present를 주면(올린 계약서에서 보인 조항) 줄마다 있음/없음을 함께 답니다.
    """

    present = present or set()
    out: dict[str, list[dict]] = {"must": [], "gain": [], "toxic": []}
    for row in contract_clauses.CLAUSES:
        if not contract_clauses.applies_to(row, incoterms):
            continue
        out[row["category"]].append({
            "key": row["key"], "title": row["title"], "why": row["why"],
            "risk": row["risk"], "text_ko": row["text_ko"], "fix": row["fix"],
            "present": row["key"] in present,
        })
    return out


def review(text: str, incoterms: str = "") -> dict:
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
    found = contract_clauses.find_in(body[:MAX_TEXT])
    rows = checklist(incoterms, found)
    return {
        "missing": [row for row in rows["must"] if not row["present"]],
        "toxic": [row for row in rows["toxic"] if row["present"]],
        "gain": [row for row in rows["gain"] if not row["present"]],
        "ok_must": [row for row in rows["must"] if row["present"]],
        "present": sorted(found),
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
    if result["toxic"]:
        lines += [f"### 🔴 지우거나 고쳐야 할 조항 {len(result['toxic'])}개", ""]
        for row in result["toxic"]:
            lines.append(f"- **{row['title']}** — {row['risk']}")
            if row["fix"]:
                lines.append(f"  - 고치는 법: {row['fix']}")
        lines.append("")
    if result["missing"]:
        lines += [f"### 🟠 빠진 필수조항 {len(result['missing'])}개", ""]
        for row in result["missing"]:
            lines.append(f"- **{row['title']}** — {row['why']}")
        lines.append("")
    if result["gain"]:
        lines += [f"### 🔵 챙기면 이로운 조항 {len(result['gain'])}개", ""]
        for row in result["gain"]:
            lines.append(f"- **{row['title']}** — {row['risk']}")
        lines.append("")
    if not (result["toxic"] or result["missing"]):
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
# 이만큼은 돼야 계약서 한 장으로 봅니다. 짧은 인용은 질문이지 계약서가 아닙니다.
CONTRACT_MIN_CHARS = 400
CONTRACT_MIN_CLAUSES = 2


def looks_like_contract(text: str) -> bool:
    """이 글이 계약서인가. 확실하지 않으면 False입니다(평소대로 상담으로 답합니다)."""

    body = str(text or "")
    if len(body) < CONTRACT_MIN_CHARS:
        return False
    lowered = body.lower()
    titled = any(word in lowered for word in CONTRACT_TITLES)
    clauses = len(contract_clauses.find_in(body))
    # 제목이 있으면 조항 둘, 제목이 없으면 조항 넷을 봅니다.
    return clauses >= (CONTRACT_MIN_CLAUSES if titled else CONTRACT_MIN_CLAUSES * 2)
