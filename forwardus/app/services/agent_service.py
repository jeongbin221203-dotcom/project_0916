"""대화로 서류를 만드는 창구.

"패킹리스트만 만들어줘"처럼 서류 하나만 말해도, **그 서식이 요구하는 칸만**
되묻고 바로 초안을 그려 보여 줍니다. 선박도 스케줄도 없어도 됩니다.

여기서 지키는 선이 하나 있습니다.

    사람 말에서 값을 뽑는 일        AI
    뽑은 값이 맞는지 확인하는 일     우리 코드
    무엇이 아직 비었는지 정하는 일    우리 코드 (서식이 정합니다)
    서류를 그리는 일               우리 코드

AI에게 "다 모였다"를 판단하게 두지 않습니다. 빠진 칸은 서식이 정하는 것이고
그건 우리가 압니다. AI가 없어도(키가 없어도) 칸 목록을 보여 주고 받아
적는 데까지는 그대로 동작합니다.

서버는 상태를 갖지 않습니다. 지금까지 모은 값(draft)은 브라우저가 들고
다니고 매번 같이 보냅니다. 기존 상담 창구와 같은 방식입니다.
"""

from __future__ import annotations

from app.services import ServiceError, draft_document_service as drafts
from app.validators import ValidationError

MAX_MESSAGE = 2_000

# 어떤 말이 어떤 서식을 가리키는지. 규칙을 먼저 봅니다.
# AI가 없어도(키가 없어도) 여기까지는 됩니다.
DOC_WORDS = {
    "packing_list_std": ("패킹리스트", "패킹 리스트", "포장명세서", "포장 명세서",
                         "packing list", "packinglist", "p/l", "pl"),
    "commercial_invoice": ("상업송장", "상업 송장", "커머셜", "인보이스",
                           "commercial invoice", "c/i", "ci", "invoice"),
    "proforma_invoice": ("견적송장", "견적 송장", "프로포마", "프로파마",
                         "proforma", "p/i", "pi"),
}

# "그냥 만들어줘", "없어", "빈칸으로" — 더 안 적고 지금 것으로 그리라는 뜻입니다.
JUST_MAKE = ("그냥", "없어", "없습니다", "없음", "빈칸", "빈 칸", "공백", "모르겠",
             "생략", "건너", "패스", "바로", "지금", "이대로", "그대로", "만들어",
             "보여", "작성")

# 사람이 적어 줄 수 있는 칸. 서식 칸 이름과 짝지어 둡니다.
# (Shipment를 만들 때 쓰는 이름과 서식 칸 이름이 달라서 여기서 잇습니다)
ASK_LABELS = {
    "exporter_name": "보내는 회사 이름",
    "exporter_address": "보내는 회사 주소",
    "buyer_name": "받는 회사 이름 (Consignee)",
    "buyer_address": "받는 회사 주소",
    "origin_code": "출발지 (항구·공항)",
    "destination_code": "도착지 (항구·공항)",
    "incoterms": "거래 조건 (FOB · CIF 같은 것)",
    "currency": "통화 (USD 같은 것)",
    "invoice_no": "송장 번호",
    "buyer": "Buyer (받는 곳과 다를 때만)",
    "other_references": "기타 참조",
    "payment_terms": "결제 조건",
    "lc_no": "L/C 번호와 날짜",
    "shipping_marks": "화인 (Shipping Marks)",
    "remarks": "비고",
    "bank_info": "은행 정보",
    "validity_date": "견적 유효기한",
    "po_no": "Buyer 주문번호",
    "signed_by": "서명 (보내는 쪽)",
    "accepted_by": "서명 (받는 쪽)",
}

# 서식마다 사람에게 물어볼 칸. 순서가 곧 물어보는 순서입니다.
ASK_FOR = {
    "packing_list_std": [
        ("exporter_name", True), ("exporter_address", False),
        ("buyer_name", True), ("buyer_address", False),
        ("origin_code", True), ("destination_code", True),
        ("invoice_no", False), ("buyer", False), ("other_references", False),
        ("signed_by", False),
    ],
    "commercial_invoice": [
        ("exporter_name", True), ("exporter_address", False),
        ("buyer_name", True), ("buyer_address", False),
        ("origin_code", True), ("destination_code", True),
        ("incoterms", True), ("currency", False),
        ("payment_terms", False), ("lc_no", False),
        ("shipping_marks", False), ("remarks", False), ("signed_by", False),
    ],
    "proforma_invoice": [
        ("exporter_name", True), ("exporter_address", False),
        ("buyer_name", True), ("buyer_address", False),
        ("origin_code", True), ("destination_code", True),
        ("incoterms", True), ("currency", False),
        ("validity_date", False), ("po_no", False),
        ("payment_terms", False), ("bank_info", False),
        ("remarks", False), ("signed_by", False), ("accepted_by", False),
    ],
}

ITEM_NOTE = ("품목은 **품명 · 개수 · 한 상자 크기(가로x세로x높이 cm) · 한 상자 무게(kg)**"
             "가 있어야 부피와 중량이 계산됩니다.")


def detect_kind(text: str) -> str | None:
    """어떤 서류를 말하는지 찾습니다. 못 찾으면 None."""

    lowered = (text or "").lower().replace(" ", "")
    for kind, words in DOC_WORDS.items():
        if any(word.replace(" ", "") in lowered for word in words):
            return kind
    return None


def wants_to_finish(text: str) -> bool:
    """더 안 적고 지금 것으로 그리라는 말인지."""

    written = (text or "").strip()
    if not written:
        return True
    return any(word in written for word in JUST_MAKE)


def ask_list(kind: str) -> list[dict]:
    """이 서식이 요구하는 칸. 화면에 그대로 보여 줍니다."""

    rows = []
    for name, required in ASK_FOR.get(kind, []):
        rows.append({"field": name, "label": ASK_LABELS.get(name, name),
                     "required": required})
    return rows


def _ask_message(kind: str, draft: dict) -> str:
    """무엇을 적어야 하는지 적은 안내. 이미 적은 것은 값까지 보여 줍니다."""

    title = drafts.FORMS[kind]
    lines = [f"**{title}**를 만들겠습니다. 아래 내용을 알려 주세요.", ""]

    for row in ask_list(kind):
        mark = " *" if row["required"] else ""
        value = str(draft.get(row["field"]) or "").strip()
        lines.append(f"- {row['label']}{mark}"
                     + (f" — 적으신 것: {value}" if value else ""))

    items = draft.get("items") or []
    lines.append("")
    lines.append(f"- 품목{' — ' + str(len(items)) + '개 적으셨습니다' if items else ' *'}")
    lines.append("")
    lines.append(ITEM_NOTE)
    lines.append("")
    lines.append("아는 것만 한 번에 적어 주셔도 됩니다. "
                 "**그냥 만들어줘**라고 하시면 지금 있는 것만으로 초안을 그려 드립니다. "
                 "빈 칸은 비워 둔 채로 나옵니다.")
    lines.append("")
    lines.append("`*` 표시는 없으면 서류 모양이 제대로 안 나오는 칸입니다.")
    return "\n".join(lines)


def _pick_message(reason: str = "") -> str:
    lines = []
    if reason:
        lines += [reason, ""]
    lines.append("어떤 서류를 만들까요? 하나만 고르셔도 됩니다.")
    lines.append("")
    for kind, title in drafts.FORMS.items():
        if kind == "packing_list":      # ORDER# 양식은 서류 작성 화면에서 고릅니다.
            continue
        lines.append(f"- {title}")
    lines.append("")
    lines.append('예를 들어 "패킹리스트만 만들어줘"라고 하시면 됩니다.')
    return "\n".join(lines)


def _read_message(kind: str, message: str, draft: dict) -> list[str]:
    """적어 주신 글에서 값을 뽑아 draft에 넣습니다. 확인된 것만 넣습니다.

    돌려주는 것은 "이건 확인 못 했다"는 메모입니다.
    AI 키가 없으면 아무 것도 안 뽑고 빈 목록을 돌려줍니다. 그래도
    칸을 직접 채우는 길은 열려 있습니다.
    """

    from app.services import intake_service

    if not message.strip() or not intake_service.available():
        return []
    try:
        read = intake_service.read(message)
    except (ValidationError, ServiceError):
        return []

    form = read["form"]["fields"]
    # 서식이 쓰는 칸만 받습니다. 나머지는 이 서류와 상관이 없습니다.
    wanted = {name for name, _ in ASK_FOR.get(kind, [])}
    for name, value in form.items():
        if name in wanted and value and not str(draft.get(name) or "").strip():
            draft[name] = value
    if read["form"]["items"]:
        draft["items"] = read["form"]["items"]
    return list(read["notes"])


def turn(payload: dict) -> dict:
    """대화 한 번. 무엇을 물을지, 또는 무엇을 그렸는지 돌려줍니다."""

    if not isinstance(payload, dict):
        raise ValidationError("입력을 읽지 못했습니다.", "payload")

    message = str(payload.get("message") or "").strip()
    if len(message) > MAX_MESSAGE:
        raise ValidationError(f"{MAX_MESSAGE:,}자 아래로 줄여 주세요.", "message")

    draft = dict(payload.get("draft") or {})
    kind = draft.get("kind") or detect_kind(message)

    # 1) 어떤 서류인지 아직 모릅니다.
    if not kind:
        return {"reply": _pick_message(), "draft": draft, "stage": "pick"}

    first_time = draft.get("kind") != kind
    draft["kind"] = kind

    # 2) 방금 서류를 고르셨습니다. 무엇이 필요한지 먼저 보여 줍니다.
    if first_time:
        notes = _read_message(kind, message, draft)
        return {"reply": _ask_message(kind, draft), "draft": draft,
                "stage": "ask", "fields": ask_list(kind), "notes": notes}

    # 3) 답을 주셨습니다. 읽어서 채웁니다.
    notes = _read_message(kind, message, draft)

    # 4) 그릴까요, 더 물을까요.
    if not wants_to_finish(message):
        return {"reply": _ask_message(kind, draft), "draft": draft,
                "stage": "ask", "fields": ask_list(kind), "notes": notes}

    return {**make(kind, draft), "draft": draft, "notes": notes}


def make(kind: str, draft: dict) -> dict:
    """초안을 그립니다. 품목이 없으면 서류가 안 되니 되묻습니다."""

    if not (draft.get("items") or []):
        return {"reply": "품목을 알려 주셔야 서류가 나옵니다.\n\n" + ITEM_NOTE,
                "stage": "ask", "fields": ask_list(kind)}

    rendered = drafts.render(kind, draft)
    return {"reply": _done_message(rendered), "stage": "made",
            "kind": kind, "title": rendered["title"],
            "missing": rendered["missing"], "undecided": rendered["undecided"]}


def _done_message(rendered: dict) -> str:
    """다 만든 뒤에 건네는 말. 무엇이 비었는지 숨기지 않습니다."""

    lines = [f"**{rendered['title']}** 초안입니다.", ""]

    if rendered["undecided"]:
        lines.append("운송 계획이 없어서 아직 못 채운 칸이 있습니다. "
                     "출항일·선박명은 스케줄을 고르면 채워집니다.")
        lines.append("")
    if rendered["missing"]:
        names = ", ".join(row["label"] for row in rendered["missing"][:6])
        more = f" 외 {len(rendered['missing']) - 6}개" if len(rendered["missing"]) > 6 else ""
        lines.append(f"아직 빈 칸: {names}{more}")
        lines.append("적어 주시면 다시 그려 드립니다.")
        lines.append("")
    lines.append("**PDF로 받기**를 누르시면 파일로 내려받습니다.")
    lines.append("")
    lines.append("이제 **운송 계획**을 잡으시면 출항일·선박명까지 채운 "
                 "정식 서류로 만들 수 있습니다.")
    return "\n".join(lines)
