"""질문을 '무엇을 묻는지(의도)'와 '어떤 조건에서 묻는지(조건)'로 나눕니다.

왜 나누나
  1) 검색은 조건이 붙을수록 흐려집니다. "베트남에 화장품 DDP로 보내는데 FOB랑 뭐가 달라요"에서
     검색에 쓸 말은 "FOB와 DDP 차이"이고, 나라·품목은 **답을 고를 때** 쓰는 조건입니다.
     그렇다고 조건을 버리면 안 됩니다. 검색용 핵심과 적용 조건을 따로 들고 갑니다.
  2) 되묻기는 의도마다 다릅니다. 운임을 물으면 출발·도착지와 화물이 있어야 하고,
     용어 뜻을 물으면 아무것도 더 필요 없습니다. 의도를 모르면 엉뚱한 것을 되묻습니다.

AI를 부르지 않습니다. 말뭉치 규칙으로만 나눕니다. (한 번 더 부르면 그만큼 느려집니다)
"""

from __future__ import annotations

import re

from app.services import faq_index

# --- 의도 ---------------------------------------------------------------------------
# 앞에 있는 것이 먼저 잡힙니다. 좁은 의도부터 둡니다.
INTENT_RULES = [
    ("term_definition", re.compile(
        r"(뭔가요|뭐예요|뭐야|무엇인가요|무슨 뜻|뜻이|의미가|차이가|차이점|다른가요|다릅니까|"
        r"란 무엇|이란\b|개념)")),
    ("document_fix", re.compile(
        r"(정정|수정|잘못 ?(적|썼|기재)|오기|틀리게|재발행|취소.*신고|신고.*취소|불일치)")),
    ("payment_risk", re.compile(
        r"(대금|결제|입금|미수|못 받|떼이|네고|신용장|l/c|엘씨|t/t|d/[pa]|추심|연체|회수)", re.I)),
    ("shipping_quote", re.compile(
        r"(운임|운송비|운송|배송|얼마나 (걸|드)|며칠|일정|스케줄|부킹|선적|컨테이너|lcl|fcl|"
        r"항공|해상|포워더)", re.I)),
    ("tariff", re.compile(r"(관세|세율|tariff|hts|관세율|환급)", re.I)),
    ("origin_fta", re.compile(
        r"(fta|원산지|c/?o|특혜관세|협정세율|누적기준|세번변경|부가가치기준)", re.I)),
    ("labeling", re.compile(r"(라벨|표시사항|표기|포장 ?표시|성분표|유통기한 ?표시)")),
    ("regulation", re.compile(
        r"(요건|규제|허가|승인|인증|등록|금지|제한|표시|성분|검역|위생|세관장확인|전략물자|제재)")),
]

# 의도마다 "이게 없으면 답이 달라지는" 조건. 앞에 올수록 먼저 묻습니다.
REQUIRED_SLOTS = {
    "origin_fta": [("countries", "어느 나라로 보내시나요 (협정마다 증명 방식이 다릅니다)"),
                   ("item", "무슨 물건인가요 (품명·재질·HS 코드)")],
    "labeling": [("countries", "어느 나라로 보내시나요 (표시 규정은 나라마다 다릅니다)"),
                 ("item", "무슨 물건인가요 (품목·용도)")],
    "regulation": [("countries", "어느 나라로 보내시나요"),
                   ("item", "무슨 물건인가요 (품명·재질·용도)")],
    "tariff": [("countries", "어느 나라로 보내시나요"),
               ("hs", "HS 코드를 아시면 알려 주세요 (모르면 품명·재질·용도)")],
    "shipping_quote": [("route", "출발지와 도착지가 어디인가요"),
                       ("cargo", "화물이 무엇이고 얼마나 되나요 (수량·중량·부피)"),
                       ("mode", "해상과 항공 중 어느 쪽을 보고 계신가요")],
    "payment_risk": [("payments", "결제 조건이 무엇인가요 (T/T·L/C·D/P 등)"),
                     ("timeline", "언제 선적했고 약정 결제일은 언제였나요")],
    "document_fix": [("document", "어떤 서류인가요 (상업송장·B/L·수출신고필증 등)"),
                     ("stage", "지금 어디까지 진행됐나요 (발행·은행 제시·선적·통관)")],
}
# 용어 뜻을 묻는 질문에는 아무것도 되묻지 않습니다.
NO_ASK_INTENTS = {"term_definition", "general"}
# 절차·기한·방법을 묻는 질문도 되묻지 않습니다. 조건 없이도 일반 절차로 답할 수 있습니다.
# ("수출신고 수리 후 선적은 언제까지 해야 하나요"에 출발지를 되묻던 잘못을 여기서 막습니다)
PROCEDURE = re.compile(r"(언제까지|기한|며칠 ?안에|절차|방법|순서|어떻게 (하|되|받|쓰|확인|신고)|"
                       r"어디서 (받|하|신청)|무엇을 준비|뭘 준비|뭐부터|어떤 서류)")

MODE_WORDS = re.compile(r"(해상|항공|특송|우편|lcl|fcl|컨테이너|벌크)", re.I)
DATE_WORDS = re.compile(r"(\d{4}년|\d{1,2}월|올해|내년|작년|이번 달|다음 달|\d{4}-\d{2})")
DOCUMENT_WORDS = re.compile(
    r"(상업송장|인보이스|invoice|포장명세서|패킹리스트|packing|b/?l|선하증권|수출신고필증|"
    r"신고필증|원산지증명|c/?o|계약서|견적서|offer)", re.I)
STAGE_WORDS = re.compile(r"(발행|제시|선적|출항|통관|신고|수리|입항|도착)")
CARGO_WORDS = re.compile(r"(\d+\s*(kg|킬로|톤|cbm|박스|개|pcs|파렛|팔레트|카톤))|중량|부피|수량", re.I)
ROUTE_WORDS = re.compile(r"(부산|인천|광양|평택|울산|김포|로스앤젤레스|la\b|뉴욕|상하이|도쿄|"
                         r"호치민|하이퐁|함부르크|로테르담|출발지|도착지|에서.*까지|→)", re.I)
# 사용자가 앞 조건을 고치는 말. 이게 있으면 새 조건이 옛 조건을 덮습니다.
CORRECTION = re.compile(r"(아니라|아니고|말고|대신|바뀌|변경|정정|취소하고|다시)")
# 검색에서 빼도 되는 상황 설명. (조건은 따로 들고 가므로 버리는 게 아닙니다)
SITUATION = re.compile(r"^(저희|우리|제가|이번에|지금|처음|현재|작년|올해)[^.?!]{0,40}(입니다|인데요?|"
                       r"하는데요?|합니다|예요|이에요|됐어요|했어요)[.,]?\s*")


def detect_intent(question: str) -> str:
    text = str(question or "")
    for name, pattern in INTENT_RULES:
        if pattern.search(text):
            return name
    return "general"


def split_question(question: str, history: list | None = None) -> dict:
    """검색용 핵심 질문과 적용 조건으로 나눕니다. 조건은 지우지 않고 따로 보관합니다."""

    text = str(question or "").strip()
    conditions = read_conditions(text, history)

    core = text
    # 1) 앞에 붙은 상황 설명 문장을 덜어 냅니다. ("저희는 처음 수출하는데요, ~")
    for _ in range(2):
        trimmed = SITUATION.sub("", core).strip()
        if trimmed == core or len(trimmed) < 8:
            break
        core = trimmed
    # 2) 여러 문장이면 물음표가 있는 문장만 남깁니다. (묻는 말이 핵심입니다)
    sentences = [part.strip() for part in re.split(r"(?<=[.?!])\s+", core) if part.strip()]
    asked = [part for part in sentences if "?" in part or part.endswith(("요", "까", "나"))]
    if asked:
        core = " ".join(asked[-2:])
    # 3) 조건 표현은 검색에서 빼 둡니다. (조건은 conditions에 남아 있습니다)
    for word in conditions["countries_raw"] + conditions["item_words"]:
        core = core.replace(word, " ")
    core = re.sub(r"\b\d{4}[.\-]?\d{2}(\d{4})?\b", " ", core)       # HS 번호
    core = re.sub(r"\s+", " ", core).strip()
    if len(core) < 6:                     # 너무 깎였으면 원문을 씁니다
        core = text
    return {"core": core, "conditions": conditions, "original": text,
            "intent": detect_intent(text)}


def read_conditions(question: str, history: list | None = None) -> dict:
    """답을 바꾸는 조건들. 앞 대화에서 확정된 것도 함께 봅니다.

    사용자가 고친 값이 있으면(아니라·말고·바뀌었어요) 이번 질문 값이 앞 대화를 덮습니다.
    """

    text = str(question or "")
    earlier_turns = [str(turn.get("content") or "") for turn in (history or [])[-6:]
                     if turn.get("role") == "user"]
    earlier = " ".join(earlier_turns)

    here = _slots(text)
    before = _slots(earlier)
    corrected = bool(CORRECTION.search(text))

    merged = {}
    for key in here:
        if isinstance(here[key], list):
            # 이번 질문에 값이 있으면 그것만 씁니다(정정). 없으면 앞 대화 값을 잇습니다.
            merged[key] = here[key] or ([] if corrected and key in ("countries", "countries_raw")
                                        else before[key])
        else:
            merged[key] = here[key] or ("" if corrected and key == "hs" else before[key])
    merged["corrected"] = corrected
    merged["from_history"] = bool(earlier.strip())
    return merged


def _slots(text: str) -> dict:
    lowered = faq_index.normalize(text)
    asked = faq_index.question_conditions(text)
    countries_raw = [word for word in faq_index.COUNTRY_WORDS
                     if re.search(rf"(?<![0-9a-z가-힣]){re.escape(word)}", lowered)]
    hs10 = re.search(r"\b(\d{10})\b", text)
    hs6 = re.search(r"\b(\d{4})[.\-]?(\d{2})\b", text)
    return {
        "countries": sorted(asked["countries"]),
        "countries_raw": countries_raw,
        "hs": hs10.group(1) if hs10 else ((hs6.group(1) + hs6.group(2)) if hs6 else ""),
        "hs10": hs10.group(1) if hs10 else "",
        "item_words": sorted(asked["items"]),
        "terms": sorted(asked["terms"]),
        "payments": sorted(asked["payments"]),
        "mode": (MODE_WORDS.search(text).group(0) if MODE_WORDS.search(text) else ""),
        "date": (DATE_WORDS.search(text).group(0) if DATE_WORDS.search(text) else ""),
        "document": (DOCUMENT_WORDS.search(text).group(0) if DOCUMENT_WORDS.search(text) else ""),
        "stage": (STAGE_WORDS.search(text).group(0) if STAGE_WORDS.search(text) else ""),
        "cargo": bool(CARGO_WORDS.search(text)),
        "route": bool(ROUTE_WORDS.search(text)),
    }


# 되묻기 기준 (튜닝 데이터 140문항으로 고름 · 2026-09-24)
#   질문이 짧고(뜻 낱말 8개 이하) 조건이 거의 없을 때(1개 이하)만 되묻습니다.
#   상황을 길게 적어 온 질문은 일반 안내로 답하는 편이 낫습니다 — 그 편이 사람이 덜 답답합니다.
#   이 값에서 되묻기 정밀도 0.48(11/23) · 재현율 0.34(10/29) 였습니다.
#   (전부 되묻게 두면 정밀도 0.20까지 떨어집니다)
ASK_MAX_TOKENS = 8
ASK_MAX_FILLED = 1
COUNTED_SLOTS = ("countries", "hs", "item_words", "terms", "payments", "mode",
                 "document", "stage")


def underspecified(question: str, conditions: dict) -> bool:
    """되물을 만큼 덜 적힌 질문인가. (짧고 조건이 거의 없음)"""

    words = len(set(faq_index.content_tokens(question)))
    filled = sum(1 for slot in COUNTED_SLOTS if conditions.get(slot))
    return words <= ASK_MAX_TOKENS and filled <= ASK_MAX_FILLED


def missing_slots(intent: str, conditions: dict, question: str = "") -> list[str]:
    """이 의도에서 아직 모자란 것. 답이 달라지는 것만 묻습니다. (최대 3개)

    질문에 이미 상황이 길게 적혀 있으면 되묻지 않습니다. 물어야 할 것이 있어도,
    적어 온 내용으로 일반 안내를 해 주는 편이 대화가 앞으로 갑니다.
    """

    if intent in NO_ASK_INTENTS:
        return []
    if question and PROCEDURE.search(question):
        return []
    if question and not underspecified(question, conditions):
        return []
    asks: list[str] = []
    for slot, sentence in REQUIRED_SLOTS.get(intent, []):
        if _has(slot, conditions):
            continue
        asks.append(sentence)
    return asks[:3]


def _has(slot: str, conditions: dict) -> bool:
    if slot == "countries":
        return bool(conditions.get("countries"))
    if slot == "hs":
        return bool(conditions.get("hs")) or bool(conditions.get("item_words"))
    if slot == "item":
        return bool(conditions.get("item_words")) or bool(conditions.get("hs"))
    if slot == "route":
        return bool(conditions.get("route"))
    if slot == "cargo":
        return bool(conditions.get("cargo"))
    if slot == "mode":
        return bool(conditions.get("mode"))
    if slot == "payments":
        return bool(conditions.get("payments"))
    if slot == "timeline":
        return bool(conditions.get("date")) or bool(conditions.get("stage"))
    if slot == "document":
        return bool(conditions.get("document"))
    if slot == "stage":
        return bool(conditions.get("stage"))
    return True
