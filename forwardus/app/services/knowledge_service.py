"""미리 정리해 둔 무역 실무 자료에서 바로 답합니다. (AI를 부르지 않습니다)

왜 만드나
  상담 질문의 상당수는 "경력 20년 담당자가 자료를 안 찾고도 답하는" 것들입니다.
  인코텀즈가 무엇인지, 수출신고를 어디서 하는지, 멕시코 NOM이 무엇인지 같은 것은
  매번 AI에게 물을 이유가 없습니다. AI를 부르면 10~30초를 기다려야 하고, 답도
  그때그때 달라집니다. 그래서 그런 답은 **글로 적어 두고 그대로 냅니다.**

  반대로 "이 품목의 올해 미국 수출 실적"처럼 자료를 찾아야 하는 질문은 여기서
  답하지 않습니다. 그건 AI와 공공데이터 조회가 할 일입니다.

어떻게 생겼나
  app/knowledge/*.md 파일 하나가 주제 하나입니다. 맨 위에 머리글이 있습니다.

      ---
      title: 수출신고 (관세청)
      keywords: 수출신고, 수출면장, 적재의무기한
      must: 수출신고, 수출 신고
      links: 관세청 UNI-PASS|https://unipass.customs.go.kr
      see: forwarder-booking
      ---
      (본문 마크다운)

  title    답 위에 붙는 이름
  keywords 이 말이 질문에 있으면 점수를 얻습니다
  must     (있으면) 이 중 하나는 반드시 질문에 있어야 합니다 — 엉뚱한 답을 막습니다
  links    답 아래 "관련 링크". 주소는 사람이 적은 것만 씁니다 (AI가 만들지 않습니다)
  see      이어 보면 좋은 주제 (파일 이름)

무엇을 지키나
  - 글을 고치는 데 코드를 건드리지 않습니다. .md 파일만 더하면 주제가 늘어납니다.
  - 확실할 때만 바로 답합니다. 애매하면 답하지 않고, 대신 그 글을 AI에게
    참고자료로 넘깁니다. 그러면 비슷한 질문에도 같은 기준으로 답이 나옵니다.
  - 자료를 찾아야 하는 질문(실적·세율·시세)은 여기서 가로채지 않습니다.
"""

from __future__ import annotations

import re
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"

# 이 점수를 넘어야 "바로 답"입니다. 낮추면 엉뚱한 주제가 튀어나옵니다.
ANSWER_SCORE = 6
# 이 점수만 넘으면 AI에게 참고자료로 넘깁니다. (바로 답하기엔 모자란 경우)
REFERENCE_SCORE = 4
# 주제를 정하는 말(must)이 맞으면 더해 줍니다. "인코텀즈는 어떻게 고르나요?"처럼
# 맞는 말이 하나뿐이어도 물어본 것이 그 주제임은 분명합니다.
MUST_BONUS = 3
# 질문이 이보다 길면 이 사람 사정이 섞인 질문입니다. 글 한 장으로 답하지 않습니다.
LONG_QUESTION = 160
# 이 사람의 건을 묻는 말. 있으면 저장해 둔 글로 바로 답하지 않고 AI에게 넘깁니다.
# ("멕시코에 화장품 500박스 보내는데 운임이 얼마?"에 NOM 인증 설명을 낼 수는 없습니다)
# "운임"만 보면 "운임톤이 뭐예요" 같은 **뜻을 묻는 말**까지 막힙니다.
# "얼마"가 이미 들어 있으니 값을 묻는 질문은 그쪽에서 걸립니다. (2026-09-26)
SPECIFIC_WORDS = ("얼마", "견적", "우리 회사", "저희", "제가", "며칠", "언제 도착",
                  # "계산해"만 보면 "CBM 어떻게 계산해요" 같은 **방법을 묻는 말**까지
                  # 막힙니다. 시켜서 해 달라는 꼴만 봅니다. (2026-09-26)
                  "계산해줘", "계산해 줘", "계산해주세", "계산해 주세",
                  "추천해", "알아봐", "찾아줘", "비교해줘", "비교해 줘",
                  "실적", "통계", "시장 규모",
                  "수출액", "얼마나 팔")
# 참고자료로 넘길 때 잘라내는 길이. 프롬프트가 너무 길면 답이 흐려집니다.
REFERENCE_CHARS = 2_600

_LOADED: list[dict] | None = None


def _incoterms_table() -> str:
    """11개 조건 요약을 코드가 들고 있는 정본(INCOTERMS_INFO)에서 그립니다.

    글로 또 적어 두면 표와 설명이 갈라집니다. 정의는 한 곳에만 둡니다.
    """

    from app.processors.cost_calculator import INCOTERMS_INFO

    lines = ["| 조건 | 뜻 | 위험이 넘어가는 때 | 판매자가 내는 비용 |",
             "| --- | --- | --- | --- |"]
    for row in INCOTERMS_INFO:
        sea = " (해상 전용)" if row.get("sea_only") else ""
        lines.append(f"| **{row['code']}** | {row['label']}{sea} | {row['risk']} | {row['seller_cost']} |")
    return "\n".join(lines)


# 머리글의 render: 이름 → 본문 뒤에 덧붙일 글을 만드는 함수.
def _issuer_table() -> str:
    """서류를 **어디서 어떻게** 받는지. 표는 processors/document_issuers가 정본입니다.

    "위생증명서·COA 등이 필요할 수 있습니다"까지만 답하던 것을 고치려고 붙였습니다.
    이름을 알아도 처음 수출하는 사람은 어디로 가야 하는지를 모릅니다.
    """

    from app.processors import document_issuers

    lines = ["", "### 어디서 어떻게 받나", "",
             "| 서류 | 발급처 | 걸리는 시간 | 신청 |",
             "| --- | --- | --- | --- |"]
    for row in document_issuers.ISSUERS:
        lines.append(f"| {row['title']} | {row['agency']} | {row.get('lead_time', '')} | "
                     f"{row.get('url', '')} |")
    lines += ["", "표에 없는 서류는 품목·나라에 따라 갈립니다. 화물을 적어 주시면 "
                  "그 건에 걸리는 것만 골라 드립니다."]
    return "\n".join(lines)


RENDERERS = {"incoterms": _incoterms_table, "document-issuers": _issuer_table}


def _compact(text: str) -> str:
    """띄어쓰기를 지워 비교합니다. "HS 코드"와 "HS코드"가 같은 말이 되게."""

    return re.sub(r"\s+", "", str(text or "")).lower()


def _split(line: str, sep: str = ",") -> list[str]:
    return [part.strip() for part in line.split(sep) if part.strip()]


def _parse(path: Path) -> dict | None:
    """머리글 + 본문. 머리글이 없으면 그 파일은 건너뜁니다."""

    raw = path.read_text(encoding="utf-8")
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", raw, re.S)
    if not match:
        return None
    head, body = match.group(1), match.group(2).strip()

    entry: dict = {"key": path.stem, "title": path.stem, "keywords": [], "must": [],
                   "links": [], "see": [], "ask": "", "body": body}
    for line in head.splitlines():
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        name, value = name.strip().lower(), value.strip()
        # direct: 이 답은 FAQ가 찾아 둔 자료보다 낫다는 표시입니다.
        # 비교 질문("FOB랑 CIF 차이")처럼, 자료를 요약하는 것보다 우리가 써 둔
        # 답을 그대로 내보내는 편이 정확한 주제에만 답니다. (2026-09-26)
        if name in ("title", "ask", "render", "direct"):
            entry[name] = value
        elif name in ("keywords", "must", "see"):
            entry[name] = _split(value)
        elif name == "links":
            for item in _split(value, ";;"):
                label, _, url = item.partition("|")
                if label.strip() and url.strip():
                    entry["links"].append({"label": label.strip(), "url": url.strip()})
    # 제목과 예시 질문도 찾는 말로 씁니다. 따로 또 적지 않아도 됩니다.
    entry["_match"] = [_compact(word) for word
                       in entry["keywords"] + [entry["title"]] if _compact(word)]
    entry["_must"] = [_compact(word) for word in entry["must"] if _compact(word)]
    return entry


def entries() -> list[dict]:
    """모든 주제. 한 번 읽어 두고 다시 씁니다. (파일이 몇십 개라 가볍습니다)"""

    global _LOADED
    if _LOADED is None:
        found = []
        for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
            try:
                entry = _parse(path)
            except OSError:
                entry = None
            if entry:
                found.append(entry)
        _LOADED = found
    return _LOADED


def reload() -> list[dict]:
    """글을 고친 뒤 다시 읽습니다. (테스트와 개발 중에 씁니다)"""

    global _LOADED
    _LOADED = None
    return entries()


def get(key: str) -> dict | None:
    return next((entry for entry in entries() if entry["key"] == key), None)


def topics() -> list[dict]:
    """무엇을 바로 답할 수 있는지 목록. 화면에서 보여 줄 때 씁니다."""

    return [{"key": entry["key"], "title": entry["title"], "ask": entry["ask"]}
            for entry in entries()]


def score(entry: dict, question: str) -> int:
    """질문과 얼마나 맞는지. 긴 말이 맞을수록 확실합니다.

    "수출"만 맞은 것과 "수출신고필증"이 맞은 것은 무게가 다릅니다. 두 글자짜리
    흔한 말로 주제가 정해지면 엉뚱한 답이 나갑니다. 그래서 맞은 말의 길이를 더합니다.
    """

    asked = _compact(question)
    if not asked:
        return 0
    if entry["_must"] and not any(word in asked for word in entry["_must"]):
        return 0
    total = sum(len(word) for word in entry["_match"] if word and word in asked)
    if total and entry["_must"]:
        total += MUST_BONUS
    return total


def _best(question: str) -> tuple[dict | None, int]:
    best, best_score = None, 0
    for entry in entries():
        value = score(entry, question)
        if value > best_score:
            best, best_score = entry, value
    return best, best_score


def find(question: str) -> dict | None:
    """바로 답할 주제. 확실하지 않으면 None입니다."""

    text = str(question or "").strip()
    # 긴 질문은 이 사람 사정이 섞여 있습니다. 글 한 장으로 답하면 동문서답이 됩니다.
    if len(text) > LONG_QUESTION:
        return None
    # "우리 건은 얼마인가요" 같은 질문도 마찬가지입니다. 글이 아니라 계산이 필요합니다.
    if any(word in text for word in SPECIFIC_WORDS):
        return None
    entry, value = _best(text)
    return entry if entry and value >= ANSWER_SCORE else None


def country(question: str) -> dict | None:
    """나라 이름을 대면 그 나라로 수출하는 법을 만들어 냅니다. (글이 없는 나라도)

    글로 적어 둔 주제(find)가 먼저입니다. "멕시코 NOM 인증"은 적어 둔 글이 답하고,
    "멕시코에 수출하려면?"은 여기서 절차·FTA·확인 창구를 묶어 답합니다.
    """

    from app.processors import country_export_guide

    text = str(question or "").strip()
    if len(text) > LONG_QUESTION or any(word in text for word in SPECIFIC_WORDS):
        return None
    return country_export_guide.answer(text)


def lookup(question: str) -> dict | None:
    """바로 답할 것 하나를 고릅니다. (적어 둔 글 또는 나라 안내)

    "멕시코 NOM 인증"은 적어 둔 글이, "멕시코에 수출하려면"은 나라 안내가 답합니다.
    가르는 기준은 간단합니다. **맞은 글이 그 나라 전용 글인가**입니다. 아니라면
    (예: 일반적인 '수출 절차' 글) 나라 안내가 더 맞는 답입니다.
    """

    from app.processors import country_export_guide

    entry = find(question)
    named = country_export_guide.find_country(str(question or ""))
    if not named:
        return entry
    code, place = named
    if entry:
        name = _compact(place)
        about_country = any(name in word for word in entry["_match"] + entry["_must"])
        if about_country:
            return entry

    # 그 나라 전용 글이 따로 있고, 인증·규제를 묻는 말이면 그 글을 냅니다.
    # "터키인증"처럼 나라 이름이 두 글자면 점수가 모자라 find()가 놓칩니다. 그렇다고
    # 일반 안내를 내면 "터키 수출하기"만 나와, 물어본 인증 이야기가 빠집니다.
    detail = _country_detail(code)
    if detail and any(word in str(question) for word in CERT_WORDS):
        return detail
    return country(question) or entry


# 나라 이름과 함께 나오면 "그 나라 인증 이야기"입니다.
CERT_WORDS = ("인증", "규제", "인허가", "라벨", "표시", "통관", "요건", "등록", "검사", "마크")


def _country_detail(code: str) -> dict | None:
    """그 나라 전용 글(cert-*.md). 나라 표에 적어 둔 이름으로 찾습니다."""

    from app.processors import country_export_guide

    note = country_export_guide.NOTES.get((code or "").upper())
    if not note and (code or "").upper() in country_export_guide._eu_members():
        note = country_export_guide.EU_NOTE
    return get(note.get("knowledge", "")) if note else None


def reference(question: str) -> str:
    """바로 답하진 않지만 AI가 참고할 글. 없으면 빈 글자입니다.

    이걸 넘기면 비슷한 질문에도 우리가 정리해 둔 기준·기관명·서류 이름으로
    답이 나옵니다. (질문마다 답이 달라지는 것을 막습니다)
    """

    entry, value = _best(question)
    if not entry or value < REFERENCE_SCORE:
        return ""
    text = body(entry)
    if len(text) > REFERENCE_CHARS:
        text = text[:REFERENCE_CHARS].rsplit("\n", 1)[0] + "\n…"
    lines = [f"아래는 우리가 정리해 둔 '{entry['title']}' 실무 자료입니다. "
             "이 내용을 근거로 답하고, 여기 적힌 기관명·서류 이름·절차를 그대로 쓰세요. "
             "여기 없는 주소를 지어내지 마세요.", "", text]
    if entry["links"]:
        lines += ["", "확인된 링크:"]
        lines += [f"- [{link['label']}]({link['url']})" for link in entry["links"]]
    return "\n".join(lines)


def body(entry: dict) -> str:
    """본문. render:가 있으면 코드가 들고 있는 표를 뒤에 붙입니다."""

    make = RENDERERS.get(entry.get("render", ""))
    return f"{entry['body']}\n\n{make()}" if make else entry["body"]


def answer(entry: dict) -> dict:
    """저장해 둔 글을 답 모양으로 만듭니다. (support_chat_service가 그대로 냅니다)

    render:가 있는 주제는 표를 글로 그리지 않고 **눌러 보는 표**를 띄웁니다.
    (widget) 화면을 옮기지 않고 답을 읽던 자리에서 조건을 눌러 볼 수 있습니다.
    AI에게 넘기는 참고자료(reference)에는 글로 된 표가 그대로 들어갑니다.
    """

    lines = [entry["body"] if entry.get("render") else body(entry)]
    related = [other for key in entry.get("see") or [] if (other := get(key))]
    if related:
        lines += ["", "**이어 보면 좋은 것**", ""]
        lines += [f"- {other['title']}" for other in related]
    data = {"answer": "\n".join(lines),
            "basis": ["미리 정리해 둔 무역 실무 자료에서 바로 답했습니다. "
                      "(AI를 부르지 않아 기다림이 없습니다)"],
            "knowledge": entry["key"]}
    if entry.get("render"):
        data["widget"] = entry["render"]
    if entry.get("links"):
        data["links"] = [{"kind": "agency", "label": link["label"], "url": link["url"],
                          "note": "확인된 공식 창구"} for link in entry["links"]]
    return data
